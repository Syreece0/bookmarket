from django.contrib import admin

from .models import PaymentTransaction, PaymentWebhookEvent


class ReadOnly(admin.ModelAdmin):
    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(PaymentTransaction)
class PaymentTransactionAdmin(ReadOnly):
    list_display = ("reference", "order", "amount", "currency", "status", "created_at")
    list_filter = ("status",)
    search_fields = ("reference", "order__reference")


@admin.register(PaymentWebhookEvent)
class WebhookEventAdmin(ReadOnly):
    list_display = ("received_at", "event_type", "idempotency_key", "processed", "outcome")
