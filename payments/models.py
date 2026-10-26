from django.db import models


class PaymentTransaction(models.Model):
    class Status(models.TextChoices):
        INITIATED = "initiated", "Initiated"
        SUCCESS = "success", "Succeeded"
        FAILED = "failed", "Failed"
        MISMATCH = "mismatch", "Amount/currency mismatch"

    order = models.ForeignKey("orders.Order", on_delete=models.PROTECT, related_name="payments")
    provider = models.CharField(max_length=20, default="paystack")
    reference = models.CharField(max_length=64, unique=True)
    amount = models.DecimalField(max_digits=12, decimal_places=2)
    currency = models.CharField(max_length=3)
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.INITIATED, db_index=True)
    provider_fee = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    verification_payload = models.JSONField(null=True, blank=True)
    failure_reason = models.CharField(max_length=240, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    verified_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at"]


class PaymentWebhookEvent(models.Model):
    """Every webhook delivery is stored. The unique key makes duplicate deliveries harmless."""

    provider = models.CharField(max_length=20, default="paystack")
    idempotency_key = models.CharField(max_length=160, unique=True)
    event_type = models.CharField(max_length=60)
    payload = models.JSONField()
    processed = models.BooleanField(default=False)
    outcome = models.CharField(max_length=120, blank=True)
    received_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-received_at"]
