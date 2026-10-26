from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.core.paginator import Paginator
from django.db import transaction
from django.db.models import Count, Q, Sum
from django.db.models.functions import TruncDate
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_POST

from accounts.decorators import admin_required, seller_required
from accounts.models import AuthorApplication, User
from catalog.models import Book
from core.models import AuditLog, audit
from core.money import ZERO
from core.ratelimit import ratelimit
from engagement.models import Review
from engagement.services import notify
from finance.models import LedgerEntry, PayoutAccount, PayoutRequest
from finance.services import (FinanceError, create_adjustment, refund_item, request_payout, seller_balances,
                              transition_payout)
from orders.models import Order, OrderItem

from .forms import (AdjustmentForm, PayoutAccountForm, PayoutActionForm, PayoutRequestForm, RefundForm,
                    RejectForm)
from .periods import PERIODS, resolve_period

SOLD_STATES = (Order.Status.PAID, Order.Status.REFUNDED)


def _sum(qs, field):
    return qs.aggregate(s=Sum(field))["s"] or ZERO


@login_required
def home(request):
    user = request.user
    if user.is_platform_admin:
        return redirect("dashboard:platform")
    if user.is_approved_author:
        return redirect("dashboard:seller")
    return redirect("library:home")


def _seller_context(user, request):
    key, label, start, end = resolve_period(request)
    items = OrderItem.objects.filter(
        seller=user, order__status__in=SOLD_STATES, allocated_at__isnull=False, unit_price__gt=0)
    if start:
        items = items.filter(order__paid_at__gte=start, order__paid_at__lte=end)
    live = items.filter(refunded_at__isnull=True)
    refunded = items.filter(refunded_at__isnull=False)
    adjustments = LedgerEntry.objects.filter(seller=user, kind=LedgerEntry.Kind.ADJUSTMENT)
    if start:
        adjustments = adjustments.filter(created_at__gte=start, created_at__lte=end)

    fees_seller = _sum(items, "fee_borne_by_seller")
    adj_total = _sum(adjustments, "amount")
    net = _sum(live, "seller_net") - _sum(refunded, "fee_borne_by_seller") + adj_total

    daily = (live.annotate(day=TruncDate("order__paid_at")).values("day")
             .annotate(total=Sum("unit_price"), units=Count("id")).order_by("day"))
    per_book = (items.values("book__title", "book_id").annotate(
        units=Count("id", filter=Q(refunded_at__isnull=True)), gross=Sum("unit_price")).order_by("-gross")[:15])
    books = Book.objects.filter(seller=user)
    return {
        "period": key, "period_label": label, "periods": PERIODS,
        "start": request.GET.get("start", ""), "end": request.GET.get("end", ""),
        "gross": _sum(items, "unit_price"), "units": live.count(),
        "commission": _sum(live, "commission_amount"), "refunds": _sum(refunded, "unit_price"),
        "payment_fees": _sum(items, "payment_fee"), "fees_seller": fees_seller,
        "adjustments": adj_total, "net": net,
        "balances": seller_balances(user),
        "book_counts": {
            "total": books.count(),
            "published": books.filter(status=Book.Status.PUBLISHED).count(),
            "pending": books.filter(status=Book.Status.PENDING).count(),
            "rejected": books.filter(status=Book.Status.REJECTED).count(),
        },
        "per_book": per_book,
        "recent": items.select_related("order", "book").order_by("-order__paid_at")[:10],
        "chart": {"labels": [d["day"].isoformat() for d in daily], "totals": [float(d["total"]) for d in daily],
                  "units": [d["units"] for d in daily]},
    }


@seller_required
def seller_dashboard(request):
    user = request.user
    if user.is_platform_admin:
        return redirect("dashboard:personal")
    return render(request, "dashboard/seller.html", {**_seller_context(user, request), "personal": False})


@admin_required
def personal_dashboard(request):
    """The administrator's own book sales, kept apart from platform-wide analytics."""
    return render(request, "dashboard/seller.html", {**_seller_context(request.user, request), "personal": True})


@seller_required
def my_books(request):
    books = Book.objects.filter(seller=request.user).select_related("category")
    return render(request, "dashboard/my_books.html", {"books": books})


@seller_required
def payouts(request):
    user = request.user
    account = PayoutAccount.objects.filter(user=user).first()
    account_form = PayoutAccountForm(instance=account)
    request_form = PayoutRequestForm()
    ctx = {
        "balances": seller_balances(user), "account": account, "account_form": account_form,
        "request_form": request_form, "requests": PayoutRequest.objects.filter(seller=user)[:30],
        "entries": LedgerEntry.objects.filter(seller=user, kind__in=LedgerEntry.BALANCE_KINDS)[:30],
    }
    return render(request, "dashboard/payouts.html", ctx)


@seller_required
@require_POST
def payout_account_save(request):
    account = PayoutAccount.objects.filter(user=request.user).first()
    form = PayoutAccountForm(request.POST, instance=account)
    if form.is_valid():
        obj = form.save(commit=False)
        obj.user = request.user
        obj.save()
        messages.success(request, "Bank details saved.")
    else:
        messages.error(request, "Please check your bank details: " + "; ".join(sum(form.errors.values(), [])))
    return redirect("dashboard:payouts")


@seller_required
@require_POST
@ratelimit("payout_request", limit=5, window=3600)
def payout_request(request):
    form = PayoutRequestForm(request.POST)
    if not form.is_valid():
        messages.error(request, "Enter a valid amount.")
        return redirect("dashboard:payouts")
    try:
        req = request_payout(request.user, form.cleaned_data["amount"])
    except FinanceError as exc:
        messages.error(request, str(exc))
    else:
        messages.success(request, "Payout requested. You will be notified when it is reviewed.")
        for admin in User.objects.filter(role=User.Role.ADMIN, is_active=True):
            notify(admin, "New payout request", f"Payout #{req.pk} is waiting for review.", "/dashboard/manage/payouts/")
    return redirect("dashboard:payouts")


@seller_required
@require_POST
def payout_cancel(request, pk):
    payout = get_object_or_404(PayoutRequest, pk=pk, seller=request.user)  # sellers can only touch their own
    try:
        transition_payout(payout.pk, PayoutRequest.Status.CANCELLED, request.user)
        messages.success(request, "Payout request cancelled.")
    except FinanceError as exc:
        messages.error(request, str(exc))
    return redirect("dashboard:payouts")


# ----------------------------------------------------------------- Platform administration


@admin_required
def platform(request):
    L = LedgerEntry
    K = L.Kind
    key, label, start, end = resolve_period(request)
    ledger = L.objects.all()
    if start:
        ledger = ledger.filter(created_at__gte=start, created_at__lte=end)

    def total(qs, *kinds):
        return _sum(qs.filter(kind__in=kinds), "amount")

    gross_all = total(ledger, K.GROSS_SALE)
    gross_admin = _sum(ledger.filter(kind=K.GROSS_SALE, seller__role=User.Role.ADMIN), "amount")
    commission = total(ledger, K.COMMISSION, K.COMMISSION_REVERSAL)
    platform_fees = -total(ledger, K.PLATFORM_FEE)
    author_liability = _sum(
        L.objects.filter(account=L.Account.SELLER, seller__role=User.Role.AUTHOR, kind__in=L.BALANCE_KINDS), "amount")
    payouts_qs = PayoutRequest.objects.all()
    ctx = {
        "period": key, "period_label": label, "periods": PERIODS,
        "start": request.GET.get("start", ""), "end": request.GET.get("end", ""),
        "customers": User.objects.filter(role=User.Role.CUSTOMER).count(),
        "authors": User.objects.filter(role=User.Role.AUTHOR).count(),
        "pending_apps": AuthorApplication.objects.filter(status=AuthorApplication.Status.PENDING).count(),
        "published_books": Book.objects.published().count(),
        "pending_books": Book.objects.filter(status=Book.Status.PENDING).count(),
        "completed_orders": Order.objects.filter(status__in=SOLD_STATES, total__gt=0).count(),
        "gross_all": gross_all, "gross_admin": gross_admin, "gross_external": gross_all - gross_admin,
        "commission": commission, "platform_fees": platform_fees,
        "refunds": -total(ledger, K.GROSS_REFUND),
        "chargebacks": _sum(ledger.filter(kind=K.CHARGEBACK), "amount") * -1,
        "author_liability": author_liability,
        "paid_total": _sum(payouts_qs.filter(status=PayoutRequest.Status.PAID), "amount"),
        "failed_count": payouts_qs.filter(status=PayoutRequest.Status.FAILED).count(),
        "failed_total": _sum(payouts_qs.filter(status=PayoutRequest.Status.FAILED), "amount"),
        "pending_payouts": payouts_qs.filter(status__in=[PayoutRequest.Status.PENDING, PayoutRequest.Status.APPROVED,
                                                         PayoutRequest.Status.PROCESSING]).count(),
        "flagged_reviews": Review.objects.filter(status=Review.Status.FLAGGED).count(),
    }
    return render(request, "dashboard/platform.html", ctx)


@admin_required
def applications(request):
    apps = AuthorApplication.objects.select_related("user").order_by("status", "-created_at")[:100]
    return render(request, "dashboard/applications.html", {"applications": apps, "reject_form": RejectForm()})


@admin_required
@require_POST
@transaction.atomic
def application_decide(request, pk, decision):
    app = get_object_or_404(AuthorApplication.objects.select_for_update(), pk=pk, status=AuthorApplication.Status.PENDING)
    app.decided_by, app.decided_at = request.user, timezone.now()
    if decision == "approve":
        app.status = AuthorApplication.Status.APPROVED
        user = app.user
        if not user.is_platform_admin:
            user.role = User.Role.AUTHOR
        user.display_name = user.display_name or app.pen_name
        user.save()
        notify(user, "Author application approved", "You can now upload books from your dashboard.", "/dashboard/", email=True)
    elif decision == "reject":
        form = RejectForm(request.POST)
        app.status = AuthorApplication.Status.REJECTED
        app.decision_note = form.cleaned_data["reason"] if form.is_valid() else ""
        notify(app.user, "Author application update", "Your application was not approved. " + app.decision_note[:200],
               "/accounts/become-an-author/", email=True)
    else:
        raise PermissionDenied
    app.save()
    audit(request.user, f"author_application.{decision}", app)
    messages.success(request, f"Application {app.status}.")
    return redirect("dashboard:applications")


@admin_required
def book_queue(request):
    books = Book.objects.filter(status=Book.Status.PENDING).select_related("seller", "category").order_by("created_at")
    return render(request, "dashboard/book_queue.html", {"books": books, "reject_form": RejectForm()})


@admin_required
def book_review_file(request, pk):
    """Let the reviewer read the submitted file before deciding."""
    from django.http import FileResponse
    book = get_object_or_404(Book, pk=pk)
    ctype = "application/pdf" if book.file_format == Book.Format.PDF else "application/epub+zip"
    resp = FileResponse(book.file.open("rb"), content_type=ctype)
    resp["Content-Disposition"] = "inline"
    return resp


@admin_required
@require_POST
@transaction.atomic
def book_decide(request, pk, decision):
    book = get_object_or_404(Book.objects.select_for_update(), pk=pk, status=Book.Status.PENDING)
    if decision == "approve":
        book.publish(request.user)
        notify(book.seller, "Book approved", f"“{book.title}” is now live.", book.get_absolute_url(), email=True)
    elif decision == "reject":
        form = RejectForm(request.POST)
        reason = form.cleaned_data["reason"] if form.is_valid() else "Did not meet our content guidelines."
        book.reject(request.user, reason)
        notify(book.seller, "Book not approved", f"“{book.title}”: {reason[:200]}", "/dashboard/books/", email=True)
    else:
        raise PermissionDenied
    audit(request.user, f"book.{decision}", book)
    messages.success(request, f"“{book.title}” {book.status}.")
    return redirect("dashboard:book_queue")


@admin_required
def sales(request):
    items = (OrderItem.objects.filter(order__status__in=SOLD_STATES, unit_price__gt=0)
             .select_related("order", "order__customer", "seller", "book").order_by("-order__paid_at"))
    page = Paginator(items, 25).get_page(request.GET.get("page"))
    return render(request, "dashboard/sales.html", {"page": page, "refund_form": RefundForm()})


@admin_required
@require_POST
@ratelimit("refund", limit=30, window=3600)
def sale_refund(request, pk):
    form = RefundForm(request.POST)
    if not form.is_valid():
        messages.error(request, "A reason is required.")
        return redirect("dashboard:sales")
    try:
        item = refund_item(pk, request.user, form.cleaned_data["reason"], kind=form.cleaned_data["kind"],
                           provider_reference=form.cleaned_data["provider_reference"])
    except (FinanceError, OrderItem.DoesNotExist) as exc:
        messages.error(request, str(exc) or "Sale not found.")
    else:
        notify(item.order.customer, "Refund recorded", f"Access to “{item.title_snapshot}” was removed after a refund.", "/orders/")
        notify(item.seller, "A sale was reversed", f"A sale of “{item.title_snapshot}” was reversed.", "/dashboard/")
        messages.success(request, "Sale reversed and access revoked. Remember to complete the refund with your payment provider.")
    return redirect("dashboard:sales")


@admin_required
def payout_queue(request):
    qs = PayoutRequest.objects.select_related("seller").order_by("-requested_at")[:100]
    return render(request, "dashboard/payout_queue.html", {"payouts": qs, "action_form": PayoutActionForm(),
                                                           "adjustment_form": AdjustmentForm()})


@admin_required
@require_POST
def payout_action(request, pk, action):
    mapping = {"approve": "approved", "processing": "processing", "paid": "paid", "failed": "failed", "reject": "rejected"}
    if action not in mapping:
        raise PermissionDenied
    form = PayoutActionForm(request.POST)
    data = form.cleaned_data if form.is_valid() else {"reference": "", "note": ""}
    try:
        payout = transition_payout(pk, mapping[action], request.user, reference=data["reference"], note=data["note"])
    except FinanceError as exc:
        messages.error(request, str(exc))
    else:
        notify(payout.seller, f"Payout {payout.status}", f"Payout #{payout.pk} is now {payout.status}.", "/dashboard/payouts/")
        messages.success(request, f"Payout #{payout.pk} marked {payout.status}.")
    return redirect("dashboard:payout_queue")


@admin_required
@require_POST
@ratelimit("adjustment", limit=20, window=3600)
def adjustment(request):
    form = AdjustmentForm(request.POST)
    if form.is_valid():
        seller = User.objects.filter(email__iexact=form.cleaned_data["seller_email"], role__in=[User.Role.AUTHOR, User.Role.ADMIN]).first()
        if not seller:
            messages.error(request, "No seller with that email.")
        else:
            try:
                create_adjustment(seller, form.cleaned_data["amount"], form.cleaned_data["reason"], request.user)
                messages.success(request, "Adjustment recorded in the ledger.")
            except FinanceError as exc:
                messages.error(request, str(exc))
    else:
        messages.error(request, "Check the adjustment form.")
    return redirect("dashboard:payout_queue")


@admin_required
def audit_log(request):
    page = Paginator(AuditLog.objects.select_related("actor"), 50).get_page(request.GET.get("page"))
    return render(request, "dashboard/audit.html", {"page": page})


@admin_required
def reviews_queue(request):
    reviews = Review.objects.filter(status=Review.Status.FLAGGED).select_related("book", "user")
    return render(request, "dashboard/reviews.html", {"reviews": reviews})


@admin_required
@require_POST
def review_moderate(request, pk, action):
    review = get_object_or_404(Review, pk=pk)
    review.status = Review.Status.HIDDEN if action == "hide" else Review.Status.PUBLISHED
    review.save(update_fields=["status"])
    audit(request.user, f"review.{action}", review)
    return redirect("dashboard:reviews")
