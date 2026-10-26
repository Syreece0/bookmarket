from functools import wraps

from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied


def seller_required(view):
    """Approved authors and the platform administrator may sell books."""

    @wraps(view)
    @login_required
    def wrapper(request, *args, **kwargs):
        if not request.user.can_sell:
            raise PermissionDenied
        return view(request, *args, **kwargs)

    return wrapper


def admin_required(view):
    @wraps(view)
    @login_required
    def wrapper(request, *args, **kwargs):
        if not request.user.is_platform_admin:
            raise PermissionDenied
        return view(request, *args, **kwargs)

    return wrapper
