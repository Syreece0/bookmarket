from django.contrib import admin

from .models import Entitlement, Order, OrderItem


class ItemInline(admin.TabularInline):
    model = OrderItem
    extra = 0
    can_delete = False
    readonly_fields = [f.name for f in OrderItem._meta.fields if f.name != "id"]


@admin.register(Order)
class OrderAdmin(admin.ModelAdmin):
    list_display = ("reference", "customer", "status", "total", "currency", "created_at")
    list_filter = ("status",)
    search_fields = ("reference", "customer__email")
    inlines = [ItemInline]

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(Entitlement)
class EntitlementAdmin(admin.ModelAdmin):
    list_display = ("user", "book", "source", "granted_at", "revoked_at")
    list_filter = ("source",)
