from django.contrib import admin

from .models import LedgerEntry, PayoutAccount, PayoutRequest, RefundRecord


class ReadOnlyAdmin(admin.ModelAdmin):
    """Financial records are changed only through finance.services so every change is audited."""

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(LedgerEntry)
class LedgerEntryAdmin(ReadOnlyAdmin):
    list_display = ("created_at", "account", "kind", "seller", "amount", "currency", "key")
    list_filter = ("account", "kind")
    search_fields = ("key", "seller__email")


@admin.register(PayoutRequest)
class PayoutRequestAdmin(ReadOnlyAdmin):
    list_display = ("id", "seller", "amount", "status", "requested_at")
    list_filter = ("status",)


@admin.register(RefundRecord)
class RefundRecordAdmin(ReadOnlyAdmin):
    list_display = ("order_item", "kind", "amount", "created_at")


@admin.register(PayoutAccount)
class PayoutAccountAdmin(ReadOnlyAdmin):
    list_display = ("user", "bank_name")
