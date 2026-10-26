"""Small cache-based rate limiter for login and sensitive actions."""
from functools import wraps

from django.core.cache import cache
from django.http import HttpResponse


def client_ip(request):
    return request.META.get("REMOTE_ADDR", "unknown")


def hit(key, limit, window):
    """Register a hit; return True when the caller is over the limit."""
    cache.add(key, 0, timeout=window)
    try:
        count = cache.incr(key)
    except ValueError:
        cache.set(key, 1, timeout=window)
        count = 1
    return count > limit


def ratelimit(scope, limit=10, window=60, methods=("POST",)):
    def decorator(view):
        @wraps(view)
        def wrapper(request, *args, **kwargs):
            if request.method in methods:
                ident = request.user.pk if request.user.is_authenticated else client_ip(request)
                if hit(f"rl:{scope}:{ident}", limit, window):
                    return HttpResponse("Too many attempts. Please wait a minute and try again.", status=429)
            return view(request, *args, **kwargs)

        return wrapper

    return decorator
