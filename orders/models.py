import uuid
from decimal import Decimal

from django.conf import settings
from django.db import models
from django.utils import timezone


def new_reference():
    return "ORD-" + uuid.uuid4().hex[:14].upper()


class Order(models.Model):
    class Status(models.TextChoices):
        PENDING = "pending", "Pending payment"
        PAID = "paid", "Paid"
        FAILED = "failed", "Failed"
        CANCELLED = "cancelled", "Cancelled"
        REFUNDED = "refunded", "Refunded"

    customer = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="orders")
    reference = models.CharField(max_length=32, unique=True, default=new_reference, editable=False)
    status = models.CharField(max_length=12, choices=Status.choices, default=Status.PENDING, db_index=True)
    currency = models.CharField(max_length=3)
    total = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal("0.00"))
    created_at = models.DateTimeField(auto_now_add=True)
    paid_at = models.DateTimeField(null=True, blank=True, db_index=True)

    class Meta:
        ordering = ["-created_at"]
        constraints = [models.CheckConstraint(condition=models.Q(total__gte=0), name="order_total_non_negative")]

    def __str__(self):
        return self.reference


class OrderItem(models.Model):
    """One purchased book. Commission and fee splits are snapshotted at payment time so later policy
    changes never rewrite history."""

    order = models.ForeignKey(Order, on_delete=models.PROTECT, related_name="items")
    book = models.ForeignKey("catalog.Book", on_delete=models.PROTECT, related_name="order_items")
    seller = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="sold_items")
    title_snapshot = models.CharField(max_length=200)
    currency = models.CharField(max_length=3)
    unit_price = models.DecimalField(max_digits=10, decimal_places=2)
    seller_is_admin = models.BooleanField(default=False, help_text="Administrator personal sale: no commission.")

    # Filled in when payment is verified:
    commission_rate = models.DecimalField(max_digits=5, decimal_places=4, default=Decimal("0"))
    commission_amount = models.DecimalField(max_digits=10, decimal_places=2, default=Decimal("0.00"))
    payment_fee = models.DecimalField(max_digits=10, decimal_places=2, default=Decimal("0.00"))
    fee_borne_by_seller = models.DecimalField(max_digits=10, decimal_places=2, default=Decimal("0.00"))
    fee_borne_by_platform = models.DecimalField(max_digits=10, decimal_places=2, default=Decimal("0.00"))
    seller_net = models.DecimalField(max_digits=10, decimal_places=2, default=Decimal("0.00"))
    allocated_at = models.DateTimeField(null=True, blank=True)

    refunded_at = models.DateTimeField(null=True, blank=True, db_index=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["order", "book"], name="one_line_per_book_per_order")]

    def __str__(self):
        return f"{self.order.reference}: {self.title_snapshot}"


class EntitlementQuerySet(models.QuerySet):
    def active(self):
        return self.filter(revoked_at__isnull=True)


class Entitlement(models.Model):
    """The right to read/download a book. Kept separate from orders so future sources
    (subscriptions, gifts, promos) can grant access without touching the payment flow."""

    class Source(models.TextChoices):
        PURCHASE = "purchase", "Purchase"
        FREE = "free", "Free book"
        # Future: SUBSCRIPTION, GIFT, PROMO

    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="entitlements")
    book = models.ForeignKey("catalog.Book", on_delete=models.PROTECT, related_name="entitlements")
    order_item = models.OneToOneField(OrderItem, null=True, blank=True, on_delete=models.PROTECT, related_name="entitlement")
    source = models.CharField(max_length=12, choices=Source.choices, default=Source.PURCHASE)
    granted_at = models.DateTimeField(default=timezone.now)
    revoked_at = models.DateTimeField(null=True, blank=True)
    revoked_reason = models.CharField(max_length=120, blank=True)

    objects = EntitlementQuerySet.as_manager()

    class Meta:
        constraints = [models.UniqueConstraint(fields=["user", "book"], name="one_entitlement_per_user_book")]
        ordering = ["-granted_at"]

    @property
    def is_active(self):
        return self.revoked_at is None
