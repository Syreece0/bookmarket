from django.contrib import admin

from core.models import audit

from .models import Notification, Review, ReviewReport, WishlistItem


@admin.register(Review)
class ReviewAdmin(admin.ModelAdmin):
    list_display = ("book", "user", "rating", "status", "report_count", "created_at")
    list_filter = ("status", "rating")

    def save_model(self, request, obj, form, change):
        super().save_model(request, obj, form, change)
        if "status" in form.changed_data:
            audit(request.user, "review.moderated", obj, obj.status)


admin.site.register(ReviewReport)
admin.site.register(WishlistItem)
admin.site.register(Notification)
