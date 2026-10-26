from django.conf import settings
from django.core.mail import send_mail

from .models import Notification


def notify(user, title, body="", url="", email=False):
    """Create an in-site notification for exactly one recipient. Callers must only put information
    in `body` that this recipient is entitled to see."""
    Notification.objects.create(user=user, title=title[:120], body=body[:300], url=url[:200])
    if email and user.email:
        try:
            send_mail(title, body, settings.DEFAULT_FROM_EMAIL, [user.email], fail_silently=True)
        except Exception:  # email must never break a purchase
            pass
