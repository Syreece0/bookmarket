import hashlib
import hmac
import json
from decimal import Decimal
from unittest import mock

from django.core.exceptions import PermissionDenied
from django.core.files.base import ContentFile
from django.test import TestCase, override_settings
from django.urls import reverse

from accounts.models import User
from catalog.models import Book, Category
from core.models import SiteSettings
from core.money import q, split_commission, to_minor_units
from finance.models import LedgerEntry, PayoutRequest
from finance.services import (FinanceError, allocate_order, refund_item, request_payout, seller_balances,
                              transition_payout)
from orders.models import Entitlement, Order
from orders.services import CheckoutError, create_pending_order
from payments.models import PaymentTransaction
from payments.services import finalize_payment, verify_signature

SECRET = "sk_test_unit"


def make_pdf_bytes():
    from pypdf import PdfWriter
    import io
    w = PdfWriter()
    for _ in range(3):
        w.add_blank_page(width=200, height=200)
    buf = io.BytesIO()
    w.write(buf)
    return buf.getvalue()


class Base(TestCase):
    def setUp(self):
        self.site = SiteSettings.load()
        self.admin = User.objects.create_superuser("root", "root@x.com", "pw-pw-pw-12345")
        self.author = User.objects.create_user("auth", "auth@x.com", "pw-pw-pw-12345", role=User.Role.AUTHOR)
        self.author2 = User.objects.create_user("auth2", "auth2@x.com", "pw-pw-pw-12345", role=User.Role.AUTHOR)
        self.buyer = User.objects.create_user("buyer", "buyer@x.com", "pw-pw-pw-12345")
        self.other = User.objects.create_user("other", "other@x.com", "pw-pw-pw-12345")
        self.fic = Category.objects.create(name="Fantasy", slug="fantasy", kind="fiction")
        self.nonfic = Category.objects.create(name="Biography", slug="biography", kind="nonfiction")

    def book(self, seller, price="5000.00", title="Book", category=None, status=Book.Status.PUBLISHED):
        b = Book(seller=seller, title=title, author_name="A", description="d", category=category or self.fic,
                 price=Decimal(price), currency="NGN", file_format="pdf", page_count=3, status=status)
        b.cover.save("c.jpg", ContentFile(b"x"), save=False)
        b.file.save("b.pdf", ContentFile(make_pdf_bytes()), save=False)
        b.save()
        return b

    def paid_order(self, buyer, books, fee="0"):
        order = create_pending_order(buyer, books)
        order.status = Order.Status.PAID
        order.save()
        allocate_order(order, Decimal(fee))
        for item in order.items.all():
            Entitlement.objects.create(user=buyer, book=item.book, order_item=item)
        return order


class MoneyTests(TestCase):
    def test_commission_example_from_spec(self):
        commission, seller = split_commission(Decimal("5000"), Decimal("0.20"))
        self.assertEqual(commission, Decimal("1000.00"))
        self.assertEqual(seller, Decimal("4000.00"))

    def test_split_always_sums_to_gross(self):
        for g in ["0.01", "19.99", "333.33", "1234.57"]:
            c, s = split_commission(Decimal(g), Decimal("0.20"))
            self.assertEqual(c + s, q(g))

    def test_minor_units(self):
        self.assertEqual(to_minor_units(Decimal("5000.00")), 500000)


class CommissionTests(Base):
    def test_external_author_20_80(self):
        order = self.paid_order(self.buyer, [self.book(self.author)])
        item = order.items.get()
        self.assertEqual(item.commission_amount, Decimal("1000.00"))
        self.assertEqual(item.seller_net, Decimal("4000.00"))
        self.assertEqual(LedgerEntry.objects.get(kind="commission").amount, Decimal("1000.00"))

    def test_admin_personal_sale_has_no_commission(self):
        order = self.paid_order(self.buyer, [self.book(self.admin)])
        item = order.items.get()
        self.assertEqual(item.commission_amount, Decimal("0.00"))
        self.assertFalse(LedgerEntry.objects.filter(kind="commission").exists())
        self.assertTrue(item.seller_is_admin)

    def test_fee_policies(self):
        for policy, seller_fee in (("platform", "0.00"), ("seller", "75.00"), ("split", "37.50")):
            with self.subTest(policy):
                LedgerEntry.objects.all().delete if False else None
                self.site.fee_allocation = policy
                self.site.save()
                buyer = User.objects.create_user(f"b{policy}", f"b{policy}@x.com", "pw-pw-pw-12345")
                order = self.paid_order(buyer, [self.book(self.author, title=f"T{policy}")], fee="75.00")
                item = order.items.get()
                self.assertEqual(item.fee_borne_by_seller, Decimal(seller_fee))
                self.assertEqual(item.fee_borne_by_seller + item.fee_borne_by_platform, Decimal("75.00"))

    def test_allocation_is_idempotent(self):
        order = self.paid_order(self.buyer, [self.book(self.author)])
        before = LedgerEntry.objects.count()
        allocate_order(order, Decimal("0"))
        self.assertEqual(LedgerEntry.objects.count(), before)

    def test_ledger_entries_are_immutable(self):
        self.paid_order(self.buyer, [self.book(self.author)])
        entry = LedgerEntry.objects.first()
        with self.assertRaises(PermissionDenied):
            entry.amount = Decimal("1")
            entry.save()
        with self.assertRaises(PermissionDenied):
            entry.delete()


class RefundAndPayoutTests(Base):
    def test_refund_revokes_access_and_reverses_earnings(self):
        order = self.paid_order(self.buyer, [self.book(self.author)])
        item = order.items.get()
        refund_item(item.pk, self.admin, "customer request")
        self.assertFalse(Entitlement.objects.active().filter(user=self.buyer).exists())
        total = sum(e.amount for e in LedgerEntry.objects.filter(seller=self.author, kind__in=LedgerEntry.BALANCE_KINDS))
        self.assertEqual(total, Decimal("0.00"))
        with self.assertRaises(FinanceError):
            refund_item(item.pk, self.admin, "again")

    def test_payout_lifecycle_and_balance(self):
        from finance.models import PayoutAccount
        self.site.payout_hold_days = 0
        self.site.save()
        self.paid_order(self.buyer, [self.book(self.author)])
        PayoutAccount.objects.create(user=self.author, bank_name="B", account_number="0123456789", account_name="A")
        self.assertEqual(seller_balances(self.author)["withdrawable"], Decimal("4000.00"))
        with self.assertRaises(FinanceError):
            request_payout(self.author, Decimal("9999"))
        req = request_payout(self.author, Decimal("2500"))
        self.assertEqual(seller_balances(self.author)["withdrawable"], Decimal("1500.00"))
        with self.assertRaises(FinanceError):  # cannot jump to paid
            transition_payout(req.pk, "paid", self.admin, reference="X")
        transition_payout(req.pk, "approved", self.admin)
        transition_payout(req.pk, "processing", self.admin)
        with self.assertRaises(FinanceError):  # paid needs a reference
            transition_payout(req.pk, "paid", self.admin)
        transition_payout(req.pk, "paid", self.admin, reference="TRF123")
        self.assertEqual(seller_balances(self.author)["paid_out"], Decimal("2500.00"))

    def test_failed_payout_releases_funds(self):
        from finance.models import PayoutAccount
        self.site.payout_hold_days = 0
        self.site.save()
        self.paid_order(self.buyer, [self.book(self.author)])
        PayoutAccount.objects.create(user=self.author, bank_name="B", account_number="0123456789", account_name="A")
        req = request_payout(self.author, Decimal("2000"))
        transition_payout(req.pk, "rejected", self.admin, note="no")
        self.assertEqual(seller_balances(self.author)["withdrawable"], Decimal("4000.00"))

    def test_hold_period_blocks_withdrawal(self):
        from finance.models import PayoutAccount
        self.paid_order(self.buyer, [self.book(self.author)])  # default 7-day hold
        PayoutAccount.objects.create(user=self.author, bank_name="B", account_number="0123456789", account_name="A")
        self.assertEqual(seller_balances(self.author)["pending"], Decimal("4000.00"))
        with self.assertRaises(FinanceError):
            request_payout(self.author, Decimal("2000"))


@override_settings(PAYSTACK_SECRET_KEY=SECRET)
class PaymentTests(Base):
    def setUp(self):
        super().setUp()
        self.b = self.book(self.author)
        self.order = create_pending_order(self.buyer, [self.b])
        self.txn = PaymentTransaction.objects.create(order=self.order, reference="PAY-1", amount=self.order.total, currency="NGN")

    def verification(self, **over):
        data = {"status": "success", "reference": "PAY-1", "amount": 500000, "currency": "NGN", "fees": 7500}
        data.update(over)
        return {"status": True, "data": data}

    def test_success_marks_paid_and_grants_access(self):
        finalize_payment("PAY-1", self.verification())
        self.order.refresh_from_db()
        self.assertEqual(self.order.status, Order.Status.PAID)
        self.assertTrue(Entitlement.objects.active().filter(user=self.buyer, book=self.b).exists())
        self.assertEqual(self.order.items.get().payment_fee, Decimal("75.00"))

    def test_duplicate_notification_changes_nothing(self):
        finalize_payment("PAY-1", self.verification())
        ledger, ents = LedgerEntry.objects.count(), Entitlement.objects.count()
        finalize_payment("PAY-1", self.verification())
        self.assertEqual((LedgerEntry.objects.count(), Entitlement.objects.count()), (ledger, ents))

    def test_wrong_amount_is_rejected(self):
        txn = finalize_payment("PAY-1", self.verification(amount=100))
        self.order.refresh_from_db()
        self.assertEqual(txn.status, PaymentTransaction.Status.MISMATCH)
        self.assertEqual(self.order.status, Order.Status.PENDING)
        self.assertFalse(Entitlement.objects.exists())

    def test_wrong_currency_is_rejected(self):
        txn = finalize_payment("PAY-1", self.verification(currency="USD"))
        self.assertEqual(txn.status, PaymentTransaction.Status.MISMATCH)

    def test_failed_payment(self):
        finalize_payment("PAY-1", {"status": True, "data": {"status": "failed", "reference": "PAY-1"}})
        self.order.refresh_from_db()
        self.assertEqual(self.order.status, Order.Status.FAILED)
        self.assertFalse(Entitlement.objects.exists())

    def test_signature_verification(self):
        body = b'{"event":"charge.success"}'
        good = hmac.new(SECRET.encode(), body, hashlib.sha512).hexdigest()
        self.assertTrue(verify_signature(body, good))
        self.assertFalse(verify_signature(body, "bad"))
        self.assertFalse(verify_signature(body, ""))

    def test_webhook_rejects_invalid_signature(self):
        r = self.client.post(reverse("payments:webhook"), data="{}", content_type="application/json", HTTP_X_PAYSTACK_SIGNATURE="nope")
        self.assertEqual(r.status_code, 400)

    def test_webhook_valid_and_duplicate(self):
        body = json.dumps({"event": "charge.success", "data": {"reference": "PAY-1"}}).encode()
        sig = hmac.new(SECRET.encode(), body, hashlib.sha512).hexdigest()
        with mock.patch("payments.services.fetch_verification", return_value=self.verification()):
            r1 = self.client.post(reverse("payments:webhook"), data=body, content_type="application/json", HTTP_X_PAYSTACK_SIGNATURE=sig)
            r2 = self.client.post(reverse("payments:webhook"), data=body, content_type="application/json", HTTP_X_PAYSTACK_SIGNATURE=sig)
        self.assertEqual((r1.status_code, r2.status_code), (200, 200))
        self.assertEqual(Entitlement.objects.count(), 1)
        self.assertEqual(LedgerEntry.objects.filter(kind="commission").count(), 1)

    def test_callback_redirect_alone_is_not_payment(self):
        self.client.force_login(self.buyer)
        with mock.patch("payments.services.fetch_verification", return_value={"status": True, "data": {"status": "abandoned"}}):
            self.client.get(reverse("payments:callback") + "?reference=PAY-1")
        self.order.refresh_from_db()
        self.assertNotEqual(self.order.status, Order.Status.PAID)
        self.assertFalse(Entitlement.objects.exists())


class CheckoutTests(Base):
    def test_cannot_repurchase_owned_book(self):
        b = self.book(self.author)
        self.paid_order(self.buyer, [b])
        with self.assertRaises(CheckoutError):
            create_pending_order(self.buyer, [b])

    def test_unpublished_book_cannot_be_bought(self):
        with self.assertRaises(CheckoutError):
            create_pending_order(self.buyer, [self.book(self.author, status=Book.Status.PENDING)])

    def test_free_book_creates_no_money_records(self):
        from orders.services import claim_free_book
        b = self.book(self.author, price="0.00")
        claim_free_book(self.buyer, b)
        self.assertTrue(Entitlement.objects.active().filter(user=self.buyer, book=b).exists())
        self.assertFalse(LedgerEntry.objects.exists())


class AccessControlTests(Base):
    def test_download_requires_ownership(self):
        b = self.book(self.author)
        url = reverse("library:download", args=[b.slug])
        self.assertEqual(self.client.get(url).status_code, 302)  # anonymous -> login
        self.client.force_login(self.other)
        self.assertEqual(self.client.get(url).status_code, 403)
        self.assertEqual(self.client.get(reverse("library:stream", args=[b.slug])).status_code, 403)

    def test_owner_can_download_and_read(self):
        b = self.book(self.author)
        self.paid_order(self.buyer, [b])
        self.client.force_login(self.buyer)
        self.assertEqual(self.client.get(reverse("library:download", args=[b.slug])).status_code, 200)
        self.assertEqual(self.client.get(reverse("library:read", args=[b.slug])).status_code, 200)

    def test_refunded_buyer_loses_access(self):
        b = self.book(self.author)
        order = self.paid_order(self.buyer, [b])
        refund_item(order.items.get().pk, self.admin, "x")
        self.client.force_login(self.buyer)
        self.assertEqual(self.client.get(reverse("library:download", args=[b.slug])).status_code, 403)

    def test_customer_cannot_open_dashboards(self):
        self.client.force_login(self.buyer)
        for name in ("dashboard:seller", "dashboard:platform", "dashboard:payout_queue", "dashboard:applications"):
            self.assertEqual(self.client.get(reverse(name)).status_code, 403, name)

    def test_author_cannot_open_admin_pages(self):
        self.client.force_login(self.author)
        self.assertEqual(self.client.get(reverse("dashboard:platform")).status_code, 403)
        r = self.client.post(reverse("dashboard:adjustment"), {"seller_email": "auth@x.com", "amount": "100", "reason": "x"})
        self.assertEqual(r.status_code, 403)

    def test_author_cannot_edit_another_authors_book(self):
        b = self.book(self.author2)
        self.client.force_login(self.author)
        self.assertEqual(self.client.get(reverse("catalog:edit", args=[b.pk])).status_code, 403)

    def test_author_sees_only_own_sales(self):
        self.paid_order(self.buyer, [self.book(self.author, title="Mine"), self.book(self.author2, title="Theirs")])
        self.client.force_login(self.author)
        r = self.client.get(reverse("dashboard:seller") + "?period=all")
        self.assertContains(r, "Mine")
        self.assertNotContains(r, "Theirs")

    def test_only_owner_cancels_own_payout(self):
        from finance.models import PayoutAccount
        self.site.payout_hold_days = 0
        self.site.save()
        self.paid_order(self.buyer, [self.book(self.author)])
        PayoutAccount.objects.create(user=self.author, bank_name="B", account_number="0123456789", account_name="A")
        req = request_payout(self.author, Decimal("2000"))
        self.client.force_login(self.author2)
        self.assertEqual(self.client.post(reverse("dashboard:payout_cancel", args=[req.pk])).status_code, 404)

    def test_unpublished_book_hidden_from_public(self):
        b = self.book(self.author, status=Book.Status.PENDING)
        self.assertEqual(self.client.get(b.get_absolute_url()).status_code, 404)
        self.client.force_login(self.author)
        self.assertEqual(self.client.get(b.get_absolute_url()).status_code, 200)

    def test_preview_never_serves_full_file(self):
        b = self.book(self.author)
        self.assertEqual(self.client.get(reverse("catalog:preview", args=[b.slug])).status_code, 404)  # no preview generated


class CatalogTests(Base):
    def test_fiction_nonfiction_filtering(self):
        self.book(self.author, title="Dragon", category=self.fic)
        self.book(self.author, title="Life Story", category=self.nonfic)
        r = self.client.get(reverse("catalog:kind", args=["fiction"]))
        self.assertContains(r, "Dragon")
        self.assertNotContains(r, "Life Story")

    def test_subcategory_inherits_kind(self):
        sub = Category.objects.create(name="Epic", slug="epic", parent=self.nonfic, kind="fiction")
        self.assertEqual(sub.kind, "nonfiction")

    def test_search(self):
        self.book(self.author, title="Zebra Tales")
        self.book(self.author, title="Other")
        r = self.client.get(reverse("catalog:list") + "?q=zebra")
        self.assertContains(r, "Zebra Tales")
        self.assertNotContains(r, ">Other<")

    def test_bestsellers_use_real_sales(self):
        b = self.book(self.author, title="Hit")
        self.book(self.author, title="Flop")
        self.assertFalse(Book.objects.bestsellers().exists())
        self.paid_order(self.buyer, [b])
        self.assertEqual([x.title for x in Book.objects.bestsellers()], ["Hit"])


class UploadTests(Base):
    def test_pdf_inspection(self):
        from catalog.services import inspect_book_file
        from django.core.exceptions import ValidationError
        from django.core.files.uploadedfile import SimpleUploadedFile
        fmt, pages = inspect_book_file(SimpleUploadedFile("a.pdf", make_pdf_bytes()))
        self.assertEqual((fmt, pages), ("pdf", 3))
        with self.assertRaises(ValidationError):
            inspect_book_file(SimpleUploadedFile("evil.pdf", b"MZ not a pdf"))
        with self.assertRaises(ValidationError):
            inspect_book_file(SimpleUploadedFile("a.exe", b"x"))
        with self.assertRaises(ValidationError):
            inspect_book_file(SimpleUploadedFile("a.epub", b"not a zip"))

    def test_preview_has_fewer_pages(self):
        from catalog.services import build_pdf_preview
        from pypdf import PdfReader
        from django.core.files.uploadedfile import SimpleUploadedFile
        pv = build_pdf_preview(SimpleUploadedFile("a.pdf", make_pdf_bytes()), 1)
        import io
        self.assertEqual(len(PdfReader(io.BytesIO(pv.read())).pages), 1)


class AuthorApplicationTests(Base):
    def test_apply_and_approve(self):
        from accounts.models import AuthorAgreement, AuthorApplication
        AuthorAgreement.objects.create(version=1, body="terms", is_active=True)
        self.client.force_login(self.buyer)
        r = self.client.post(reverse("accounts:become_author"), {"pen_name": "P", "bio": "bio", "genres": "", "sample_url": "", "accept_agreement": "on"})
        self.assertEqual(r.status_code, 302)
        app = AuthorApplication.objects.get()
        self.assertEqual(app.acceptances.count(), 1)
        self.client.force_login(self.admin)
        self.client.post(reverse("dashboard:application_decide", args=[app.pk, "approve"]))
        self.buyer.refresh_from_db()
        self.assertEqual(self.buyer.role, User.Role.AUTHOR)

    def test_must_accept_agreement(self):
        from accounts.models import AuthorAgreement, AuthorApplication
        AuthorAgreement.objects.create(version=1, body="terms", is_active=True)
        self.client.force_login(self.buyer)
        self.client.post(reverse("accounts:become_author"), {"pen_name": "P", "bio": "bio"})
        self.assertFalse(AuthorApplication.objects.exists())


class ReviewTests(Base):
    def test_only_owners_can_review_once(self):
        from engagement.models import Review
        b = self.book(self.author)
        self.client.force_login(self.buyer)
        self.client.post(reverse("engagement:review_create", args=[b.pk]), {"rating": 5, "text": "great"})
        self.assertEqual(Review.objects.count(), 0)
        self.paid_order(self.buyer, [b])
        self.client.post(reverse("engagement:review_create", args=[b.pk]), {"rating": 5, "text": "great"})
        self.client.post(reverse("engagement:review_create", args=[b.pk]), {"rating": 1, "text": "again"})
        self.assertEqual(Review.objects.count(), 1)


class CsrfTests(Base):
    def test_post_without_csrf_token_is_blocked(self):
        from django.test import Client
        c = Client(enforce_csrf_checks=True)
        c.force_login(self.buyer)
        self.assertEqual(c.post(reverse("orders:checkout")).status_code, 403)


class SmokeTests(Base):
    def test_public_pages_render(self):
        from django.core.management import call_command
        call_command("bootstrap")
        for url in ("/", "/books/", "/books/kind/fiction/", "/accounts/login/", "/accounts/register/", "/cart/", "/page/terms/"):
            self.assertEqual(self.client.get(url).status_code, 200, url)
