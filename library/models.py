from django.conf import settings
from django.db import models


class ReadingProgress(models.Model):
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="reading_progress")
    book = models.ForeignKey("catalog.Book", on_delete=models.CASCADE, related_name="+")
    location = models.CharField(max_length=300, blank=True, help_text="PDF page number or EPUB CFI")
    percent = models.DecimalField(max_digits=5, decimal_places=2, default=0)
    font_scale = models.PositiveSmallIntegerField(default=100)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["user", "book"], name="one_progress_per_user_book")]


class DownloadAuditRecord(models.Model):
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="+")
    book = models.ForeignKey("catalog.Book", on_delete=models.CASCADE, related_name="+")
    ip_address = models.GenericIPAddressField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
