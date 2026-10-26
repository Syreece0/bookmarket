from django import forms
from django.core.exceptions import ValidationError
from django.utils import timezone
from django.utils.text import slugify

from core.models import SiteSettings

from .models import Book, Category
from .services import build_pdf_preview, inspect_book_file, optimise_cover

MAX_COVER_MB = 5


class BookForm(forms.ModelForm):
    class Meta:
        model = Book
        fields = ("title", "author_name", "description", "category", "language", "price", "cover", "file", "preview_pages")
        widgets = {"description": forms.Textarea(attrs={"rows": 6})}
        labels = {"file": "Book file (PDF or EPUB)", "price": "Price (0 for a free book)"}

    def __init__(self, *args, **kwargs):
        self.seller = kwargs.pop("seller")
        super().__init__(*args, **kwargs)
        self.site = SiteSettings.load()
        # Only leaf-or-sub categories can be chosen so fiction/nonfiction stays unambiguous.
        self.fields["category"].queryset = Category.objects.select_related("parent").order_by("kind", "parent__name", "name")
        if self.instance.pk:
            self.fields["file"].required = False
            self.fields["cover"].required = False
        self._detected = None

    def clean_cover(self):
        cover = self.cleaned_data.get("cover")
        if cover and hasattr(cover, "size") and cover.size > MAX_COVER_MB * 1024 * 1024:
            raise ValidationError(f"Cover images must be {MAX_COVER_MB} MB or smaller.")
        return cover

    def clean_file(self):
        upload = self.cleaned_data.get("file")
        if not upload or not hasattr(upload, "size"):
            return upload
        if upload.size > self.site.max_upload_mb * 1024 * 1024:
            raise ValidationError(f"Book files must be {self.site.max_upload_mb} MB or smaller.")
        self._detected = inspect_book_file(upload)
        return upload

    def clean_price(self):
        price = self.cleaned_data["price"]
        if price < 0:
            raise ValidationError("Price cannot be negative.")
        return price

    def save(self, commit=True):
        book = super().save(commit=False)
        if not book.pk:
            book.seller = self.seller
        book.currency = self.site.default_currency
        upload = self.cleaned_data.get("file") if self._detected else None
        if upload is not None:
            book.file_format, book.page_count = self._detected
        if "cover" in self.changed_data and self.cleaned_data.get("cover"):
            try:
                book.cover.save(f"{slugify(book.title) or 'cover'}.jpg", optimise_cover(self.cleaned_data["cover"]), save=False)
            except Exception:
                pass  # keep the original upload if resizing fails
        if book.file_format == Book.Format.PDF and book.preview_pages and (upload is not None or "preview_pages" in self.changed_data):
            source = upload if upload is not None else book.file
            preview = build_pdf_preview(source, book.preview_pages)
            if preview:
                book.preview_file.save("preview.pdf", preview, save=False)
        elif book.file_format != Book.Format.PDF or not book.preview_pages:
            book.preview_file = ""
        # Non-admin sellers always go through review; admin-owned books publish directly.
        if self.seller.is_platform_admin:
            book.status = Book.Status.PUBLISHED
            book.reviewed_by, book.reviewed_at = self.seller, timezone.now()
            book.published_at = book.published_at or book.reviewed_at
        else:
            book.status = Book.Status.PENDING
            book.rejection_reason = ""
        if commit:
            book.save()
        return book
