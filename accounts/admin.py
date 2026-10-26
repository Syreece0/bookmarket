from django.contrib import admin
from django.contrib.auth.admin import UserAdmin

from .models import AuthorAgreement, AuthorAgreementAcceptance, AuthorApplication, User


@admin.register(User)
class CustomUserAdmin(UserAdmin):
    list_display = ("username", "email", "role", "is_active", "date_joined")
    list_filter = ("role", "is_active", "is_staff")
    fieldsets = UserAdmin.fieldsets + (("Marketplace", {"fields": ("role", "display_name", "bio")}),)


@admin.register(AuthorAgreement)
class AuthorAgreementAdmin(admin.ModelAdmin):
    list_display = ("title", "version", "is_active", "published_at")

    def get_readonly_fields(self, request, obj=None):
        # A version that has been accepted must never be edited; publish a new version instead.
        if obj and obj.acceptances.exists():
            return ("version", "title", "body", "commission_rate_disclosed", "published_at")
        return ()


@admin.register(AuthorApplication)
class AuthorApplicationAdmin(admin.ModelAdmin):
    list_display = ("pen_name", "user", "status", "created_at")
    list_filter = ("status",)


@admin.register(AuthorAgreementAcceptance)
class AcceptanceAdmin(admin.ModelAdmin):
    list_display = ("user", "agreement", "accepted_at", "ip_address")

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False
