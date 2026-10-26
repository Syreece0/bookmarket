from decimal import Decimal

from django.db import transaction
from django.utils import timezone

from catalog.models import Book
from core.models import SiteSettings

from .models import Entitlement, Order, OrderItem


class CheckoutError(Exception):
    pass


def owned_book_ids(user):
    return set(Entitlement.objects.active().filter(user=user).values_list("book_id", flat=True))


@transaction.atomic
def create_pending_order(user, books):
    """Create a PENDING order from a list of paid, published books. Totals come from the database
    price, never from anything the browser sent."""
    site = SiteSettings.load()
    owned = owned_book_ids(user)
    lines = [b for b in books if b.status == Book.Status.PUBLISHED and not b.is_free and b.pk not in owned]
    if not lines:
        raise CheckoutError("Your cart has nothing to buy. Books you already own are skipped.")
    if any(b.currency != site.default_currency for b in lines):
        raise CheckoutError("Some books use a currency that is not supported at checkout yet.")
    order = Order.objects.create(customer=user, currency=site.default_currency)
    total = Decimal("0.00")
    for b in lines:
        OrderItem.objects.create(
            order=order, book=b, seller=b.seller, title_snapshot=b.title, currency=b.currency,
            unit_price=b.price, seller_is_admin=b.seller.is_platform_admin,
        )
        total += b.price
    order.total = total
    order.save(update_fields=["total"])
    return order


@transaction.atomic
def claim_free_book(user, book):
    """Free books skip the payment provider and create no monetary commission or ledger entries."""
    if book.status != Book.Status.PUBLISHED or not book.is_free:
        raise CheckoutError("This book is not available as a free download.")
    existing = Entitlement.objects.filter(user=user, book=book).first()
    if existing:
        if existing.revoked_at is None:
            return existing
        raise CheckoutError("Access to this book was withdrawn. Please contact support.")
    order = Order.objects.create(customer=user, currency=book.currency, status=Order.Status.PAID, paid_at=timezone.now())
    item = OrderItem.objects.create(
        order=order, book=book, seller=book.seller, title_snapshot=book.title, currency=book.currency,
        unit_price=Decimal("0.00"), seller_is_admin=book.seller.is_platform_admin, allocated_at=timezone.now(),
    )
    return Entitlement.objects.create(user=user, book=book, order_item=item, source=Entitlement.Source.FREE)
