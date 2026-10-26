import uuid
from decimal import Decimal

from django.conf import settings
from django.core.exceptions import PermissionDenied
from django.db import models
from django.utils import timezone


class LedgerEntry(models.Model):
    """Append-only, signed ledger. Mistakes are corrected by new reversing entries, never edits or deletes.

    Two accounts are tracked:
      SELLER   - what a seller (external author or the administrator acting as seller) is owed.
      PLATFORM - the platform's commission revenue and the fees it bears.
    Informational kinds (GROSS_*) describe the sale but do not move a seller's withdrawable balance.
    """

    class Account(models.TextChoices):
        SELLER = "seller", "Seller"
        PLATFORM = "platform", "Platform"

    class Kind(models.TextChoices):
        GROSS_SALE = "gross_sale", "Gross sale"
        GROSS_REFUND = "gross_refund", "Gross refund"
        EARNING = "earning", "Seller earning (after commission)"
        FEE_SHARE = "fee_share", "Payment fee charged to seller"
        REFUND = "refund", "Refund reversal"
        CHARGEBACK = "chargeback", "Chargeback reversal"
        ADJUSTMENT = "adjustment", "Manual adjustment"
        PAYOUT = "payout", "Payout reserved/paid"
        PAYOUT_REVERSAL = "payout_reversal", "Payout released"
        COMMISSION = "commission", "Platform commission"
        COMMISSION_REVERSAL = "commission_reversal", "Commission reversal"
        PLATFORM_FEE = "platform_fee", "Payment fee borne by platform"

    BALANCE_KINDS = (Kind.EARNING, Kind.FEE_SHARE, Kind.REFUND, Kind.CHARGEBACK, Kind.ADJUSTMENT, Kind.PAYOUT, Kind.PAYOUT_REVERSAL)

    account = models.CharField(max_length=10, choices=Account.choices, db_index=True)
    kind = models.CharField(max_length=24, choices=Kind.choices, db_index=True)
    seller = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.PROTECT, related_name="ledger_entries")
    order_item = models.ForeignKey("orders.OrderItem", null=True, blank=True, on_delete=models.PROTECT, related_name="ledger_entries")
    amount = models.DecimalField(max_digits=12, decimal_places=2)
    currency = models.CharField(max_length=3)
    key = models.CharField(max_length=120, unique=True, help_text="Idempotency key: the same event can never post twice.")
    available_at = models.DateTimeField(default=timezone.now, db_index=True)
    note = models.CharField(max_length=240, blank=True)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+")
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        ordering = ["-created_at", "-id"]
        indexes = [models.Index(fields=["seller", "kind", "created_at"])]

    def save(self, *args, **kwargs):
        if self.pk:
            raise PermissionDenied("Ledger entries are immutable. Post a reversing entry instead.")
        super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise PermissionDenied("Ledger entries cannot be deleted. Post a reversing entry instead.")


class PayoutAccount(models.Model):
    """Bank details. Only the owner and administrators can ever see these."""

    user = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="payout_account")
    bank_name = models.CharField(max_length=80)
    account_number = models.CharField(max_length=20)
    account_name = models.CharField(max_length=120)
    updated_at = models.DateTimeField(auto_now=True)

    def masked_number(self):
        return "•" * max(len(self.account_number) - 4, 0) + self.account_number[-4:]


class PayoutRequest(models.Model):
    class Status(models.TextChoices):
        PENDING = "pending", "Pending"
        APPROVED = "approved", "Approved"
        PROCESSING = "processing", "Processing"
        PAID = "paid", "Paid"
        FAILED = "failed", "Failed"
        REJECTED = "rejected", "Rejected"
        CANCELLED = "cancelled", "Cancelled"

    TRANSITIONS = {
        "pending": {"approved", "rejected", "cancelled"},
        "approved": {"processing", "failed", "rejected"},
        "processing": {"paid", "failed"},
    }
    RELEASING = {"failed", "rejected", "cancelled"}

    seller = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="payout_requests")
    amount = models.DecimalField(max_digits=12, decimal_places=2)
    currency = models.CharField(max_length=3)
    status = models.CharField(max_length=12, choices=Status.choices, default=Status.PENDING, db_index=True)
    destination_snapshot = models.CharField(max_length=300, help_text="Bank details as they were when requested.")
    provider_reference = models.CharField(max_length=120, blank=True)
    note = models.CharField(max_length=240, blank=True)
    requested_at = models.DateTimeField(auto_now_add=True)
    processed_at = models.DateTimeField(null=True, blank=True)
    handled_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+")

    class Meta:
        ordering = ["-requested_at"]
        constraints = [models.CheckConstraint(condition=models.Q(amount__gt=0), name="payout_amount_positive")]


class RefundRecord(models.Model):
    class Kind(models.TextChoices):
        REFUND = "refund", "Refund"
        CHARGEBACK = "chargeback", "Chargeback"

    order_item = models.OneToOneField("orders.OrderItem", on_delete=models.PROTECT, related_name="refund_record")
    kind = models.CharField(max_length=12, choices=Kind.choices, default=Kind.REFUND)
    amount = models.DecimalField(max_digits=12, decimal_places=2)
    reason = models.CharField(max_length=240)
    provider_reference = models.CharField(max_length=120, blank=True, help_text="Reference of the refund processed at the payment provider.")
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL, related_name="+")
    created_at = models.DateTimeField(auto_now_add=True)


def new_adjustment_key():
    return f"adj:{uuid.uuid4().hex}"
