from django.contrib import admin

from core.models import audit

from .models import Book, Category


@admin.register(Category)
class CategoryAdmin(admin.ModelAdmin):
    list_display = ("name", "kind", "parent", "order", "is_featured")
    list_filter = ("kind", "is_featured")
    prepopulated_fields = {"slug": ("name",)}


@admin.register(Book)
class BookAdmin(admin.ModelAdmin):
    list_display = ("title", "seller", "category", "price", "status", "is_featured")
    list_filter = ("status", "category__kind", "is_featured")
    search_fields = ("title", "author_name")
    readonly_fields = ("file_format", "page_count", "reviewed_by", "reviewed_at", "published_at")

    def save_model(self, request, obj, form, change):
        super().save_model(request, obj, form, change)
        if change and "status" in form.changed_data:
            audit(request.user, "book.status_changed", obj, f"-> {obj.status}")
