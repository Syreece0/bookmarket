from .models import SiteSettings


def site(request):
    ctx = {"site": SiteSettings.load(), "cart_count": 0, "wishlist_count": 0, "unread_notifications": 0}
    cart = request.session.get("cart") if hasattr(request, "session") else None
    if cart:
        ctx["cart_count"] = len(cart)
    user = getattr(request, "user", None)
    if user is not None and user.is_authenticated:
        from engagement.models import Notification, WishlistItem

        ctx["wishlist_count"] = WishlistItem.objects.filter(user=user).count()
        ctx["unread_notifications"] = Notification.objects.filter(user=user, is_read=False).count()
    return ctx
