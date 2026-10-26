from decimal import Decimal

from django.conf import settings
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models
from django.utils.translation import gettext_lazy as _


class SiteSettings(models.Model):
    """Singleton holding configurable branding and policy values."""

    class FeeAllocation(models.TextChoices):
        PLATFORM = "platform", _("Platform pays payment-processing fees")
        SELLER = "seller", _("Seller (author) pays payment-processing fees")
        SPLIT = "split", _("Fees split 50/50 between platform and seller")

    site_name = models.CharField(max_length=80, default="The Book Shelf")
    tagline = models.CharField(
        max_length=200, default="Uncover a world of literary delights. Explore and shop our library of e-books."
    )
    logo = models.ImageField(upload_to="branding/", blank=True)
    default_currency = models.CharField(max_length=3, default="NGN")
    commission_rate = models.DecimalField(
        max_digits=5, decimal_places=4, default=Decimal("0.2000"),
        validators=[MinValueValidator(Decimal("0")), MaxValueValidator(Decimal("1"))],
        help_text=_("Platform commission on external-author sales, as a fraction (0.20 = 20%)."),
    )
    fee_allocation = models.CharField(max_length=10, choices=FeeAllocation.choices, default=FeeAllocation.PLATFORM)
    payout_hold_days = models.PositiveIntegerField(default=7, help_text=_("Days before new earnings become withdrawable."))
    minimum_payout = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal("1000.00"))
    max_upload_mb = models.PositiveIntegerField(default=50)
    support_email = models.EmailField(blank=True)
    support_info = models.TextField(blank=True)
    terms_text = models.TextField(blank=True)
    privacy_text = models.TextField(blank=True)
    refund_policy_text = models.TextField(blank=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name_plural = "Site settings"

    def __str__(self):
        return self.site_name

    def save(self, *args, **kwargs):
        self.pk = 1
        super().save(*args, **kwargs)

    @classmethod
    def load(cls):
        obj, _created = cls.objects.get_or_create(pk=1)
        return obj


class HeroSlide(models.Model):
    title = models.CharField(max_length=120)
    subtitle = models.CharField(max_length=240, blank=True)
    image = models.ImageField(upload_to="hero/", blank=True)
    cta_text = models.CharField(max_length=40, default="Explore")
    cta_url = models.CharField(max_length=200, default="/books/")
    order = models.PositiveIntegerField(default=0)
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ["order", "id"]

    def __str__(self):
        return self.title


class AuditLog(models.Model):
    """Append-only record of important administrative actions."""

    actor = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL, related_name="+")
    action = models.CharField(max_length=80)
    target = models.CharField(max_length=200, blank=True)
    detail = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.created_at:%Y-%m-%d %H:%M} {self.action} {self.target}"


def audit(actor, action, target="", detail=""):
    return AuditLog.objects.create(actor=actor, action=action, target=str(target)[:200], detail=detail)
