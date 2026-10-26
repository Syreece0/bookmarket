from decimal import Decimal

from django.conf import settings
from django.core.files.storage import storages
from django.core.validators import MinValueValidator
from django.db import models
from django.db.models import Count, Q
from django.urls import reverse
from django.utils import timezone
from django.utils.text import slugify
from django.utils.translation import gettext_lazy as _


def private_storage():
    """Callable storage so migrations don't embed environment-specific paths."""
    return storages["private"]


class Category(models.Model):
    """Hierarchical: top-level categories carry the Fiction/Nonfiction kind; children inherit it."""

    class Kind(models.TextChoices):
        FICTION = "fiction", _("Fiction")
        NONFICTION = "nonfiction", _("Nonfiction")

    name = models.CharField(max_length=80)
    slug = models.SlugField(max_length=90, unique=True)
    kind = models.CharField(max_length=12, choices=Kind.choices, db_index=True)
    parent = models.ForeignKey("self", null=True, blank=True, on_delete=models.PROTECT, related_name="children")
    description = models.CharField(max_length=240, blank=True)
    image = models.ImageField(upload_to="categories/", blank=True)
    order = models.PositiveIntegerField(default=0)
    is_featured = models.BooleanField(default=False)

    class Meta:
        verbose_name_plural = "categories"
        ordering = ["order", "name"]

    def __str__(self):
        return f"{self.parent.name} / {self.name}" if self.parent_id else self.name

    def save(self, *args, **kwargs):
        if self.parent_id:
            self.kind = self.parent.kind  # subcategories always inherit the parent's kind
        if not self.slug:
            self.slug = slugify(self.name)
        super().save(*args, **kwargs)

    def get_absolute_url(self):
        return reverse("catalog:category", args=[self.slug])


class BookQuerySet(models.QuerySet):
    def published(self):
        return self.filter(status=Book.Status.PUBLISHED)

    def bestsellers(self):
        return (
            self.published()
            .annotate(
                units=Count(
                    "order_items",
                    filter=Q(order_items__order__status="paid", order_items__refunded_at__isnull=True),
                    distinct=True,
                )
            )
            .filter(units__gt=0)
            .order_by("-units", "-published_at")
        )


class Book(models.Model):
    class Status(models.TextChoices):
        DRAFT = "draft", _("Draft")
        PENDING = "pending", _("Pending review")
        PUBLISHED = "published", _("Published")
        REJECTED = "rejected", _("Rejected")
        ARCHIVED = "archived", _("Archived")

    class Format(models.TextChoices):
        PDF = "pdf", "PDF"
        EPUB = "epub", "EPUB"

    seller = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="books")
    title = models.CharField(max_length=200)
    slug = models.SlugField(max_length=220, unique=True, blank=True)
    author_name = models.CharField(max_length=120, help_text=_("Name shown to readers."))
    description = models.TextField()
    category = models.ForeignKey(Category, on_delete=models.PROTECT, related_name="books")
    language = models.CharField(max_length=40, default="English")
    price = models.DecimalField(max_digits=10, decimal_places=2, default=Decimal("0.00"), validators=[MinValueValidator(Decimal("0"))])
    currency = models.CharField(max_length=3, default="NGN")
    cover = models.ImageField(upload_to="covers/")
    file = models.FileField(upload_to="books/%Y/%m/", storage=private_storage)
    file_format = models.CharField(max_length=4, choices=Format.choices)
    page_count = models.PositiveIntegerField(default=0)
    preview_pages = models.PositiveSmallIntegerField(default=10, help_text=_("Pages offered as a free PDF preview (0 disables)."))
    preview_file = models.FileField(upload_to="previews/%Y/%m/", storage=private_storage, blank=True)

    status = models.CharField(max_length=10, choices=Status.choices, default=Status.DRAFT, db_index=True)
    rejection_reason = models.TextField(blank=True)
    reviewed_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+")
    reviewed_at = models.DateTimeField(null=True, blank=True)
    is_featured = models.BooleanField(default=False)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    published_at = models.DateTimeField(null=True, blank=True, db_index=True)

    objects = BookQuerySet.as_manager()

    class Meta:
        ordering = ["-created_at"]
        indexes = [models.Index(fields=["status", "-published_at"])]

    def __str__(self):
        return self.title

    @property
    def is_free(self):
        return self.price == 0

    @property
    def kind(self):
        return self.category.kind

    @property
    def length_label(self):
        unit = "pages" if self.file_format == self.Format.PDF else "sections"
        return f"{self.page_count} {unit}" if self.page_count else ""

    @property
    def has_preview(self):
        return bool(self.preview_file)

    def get_absolute_url(self):
        return reverse("catalog:detail", args=[self.slug])

    def _unique_slug(self):
        base = slugify(self.title)[:200] or "book"
        slug, n = base, 2
        while Book.objects.filter(slug=slug).exclude(pk=self.pk).exists():
            slug, n = f"{base}-{n}", n + 1
        return slug

    def save(self, *args, **kwargs):
        if not self.slug:
            self.slug = self._unique_slug()
        super().save(*args, **kwargs)

    def publish(self, reviewer):
        self.status = self.Status.PUBLISHED
        self.reviewed_by, self.reviewed_at = reviewer, timezone.now()
        self.rejection_reason = ""
        if not self.published_at:
            self.published_at = self.reviewed_at
        self.save()

    def reject(self, reviewer, reason):
        self.status = self.Status.REJECTED
        self.reviewed_by, self.reviewed_at = reviewer, timezone.now()
        self.rejection_reason = reason
        self.save()
