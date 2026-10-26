from django.conf import settings
from django.contrib.auth.models import AbstractUser
from django.db import models
from django.utils import timezone
from django.utils.translation import gettext_lazy as _


class User(AbstractUser):
    """Custom user (set before the first migration). Role drives dashboards and permissions."""

    class Role(models.TextChoices):
        CUSTOMER = "customer", _("Customer")
        AUTHOR = "author", _("Author")
        ADMIN = "admin", _("Administrator")

    email = models.EmailField(_("email address"), unique=True)
    role = models.CharField(max_length=10, choices=Role.choices, default=Role.CUSTOMER, db_index=True)
    display_name = models.CharField(max_length=80, blank=True)
    bio = models.TextField(blank=True)

    def save(self, *args, **kwargs):
        if self.is_superuser:
            self.role = self.Role.ADMIN
        super().save(*args, **kwargs)

    @property
    def is_platform_admin(self):
        return self.is_authenticated and (self.role == self.Role.ADMIN or self.is_superuser)

    @property
    def is_approved_author(self):
        return self.is_authenticated and self.role == self.Role.AUTHOR

    @property
    def can_sell(self):
        return self.is_platform_admin or self.is_approved_author

    @property
    def public_name(self):
        return self.display_name or self.get_full_name() or self.username


class AuthorAgreement(models.Model):
    """Versioned author terms. Published versions are never edited; publish a new version instead."""

    version = models.PositiveIntegerField(unique=True)
    title = models.CharField(max_length=120, default="Author Agreement")
    body = models.TextField()
    commission_rate_disclosed = models.DecimalField(max_digits=5, decimal_places=4, default="0.2000")
    is_active = models.BooleanField(default=False, help_text="Only one version should be active.")
    published_at = models.DateTimeField(default=timezone.now)

    class Meta:
        ordering = ["-version"]

    def __str__(self):
        return f"{self.title} v{self.version}"

    @classmethod
    def current(cls):
        return cls.objects.filter(is_active=True).order_by("-version").first()


class AuthorApplication(models.Model):
    class Status(models.TextChoices):
        PENDING = "pending", _("Pending")
        APPROVED = "approved", _("Approved")
        REJECTED = "rejected", _("Rejected")

    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="author_applications")
    pen_name = models.CharField(max_length=80)
    bio = models.TextField()
    sample_url = models.URLField(blank=True)
    genres = models.CharField(max_length=200, blank=True)
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.PENDING, db_index=True)
    decision_note = models.TextField(blank=True)
    decided_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+")
    decided_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]
        constraints = [
            models.UniqueConstraint(
                fields=["user"], condition=models.Q(status="pending"), name="one_pending_application_per_user"
            )
        ]

    def __str__(self):
        return f"{self.pen_name} ({self.status})"


class AuthorAgreementAcceptance(models.Model):
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="agreement_acceptances")
    agreement = models.ForeignKey(AuthorAgreement, on_delete=models.PROTECT, related_name="acceptances")
    application = models.ForeignKey(AuthorApplication, null=True, on_delete=models.SET_NULL, related_name="acceptances")
    accepted_at = models.DateTimeField(auto_now_add=True)
    ip_address = models.GenericIPAddressField(null=True, blank=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["user", "agreement"], name="one_acceptance_per_version")]
