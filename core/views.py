from django.db.models import Avg, Count, Q
from django.http import Http404
from django.shortcuts import render

from catalog.models import Book, Category

from .models import HeroSlide, SiteSettings


def home(request):
    published = Book.objects.published().select_related("category", "seller")
    top_categories = Category.objects.filter(parent__isnull=True).order_by("order", "name")[:8]
    ctx = {
        "slides": HeroSlide.objects.filter(is_active=True),
        "categories": top_categories,
        "featured": published.filter(is_featured=True)[:8],
        "newest": published.order_by("-published_at")[:8],
        "bestsellers": Book.objects.bestsellers()[:8],
        "fiction_count": published.filter(category__kind=Category.Kind.FICTION).count(),
        "nonfiction_count": published.filter(category__kind=Category.Kind.NONFICTION).count(),
    }
    return render(request, "core/home.html", ctx)


POLICY_FIELDS = {
    "terms": ("Terms and Conditions", "terms_text"),
    "privacy": ("Privacy Policy", "privacy_text"),
    "refunds": ("Refund Policy", "refund_policy_text"),
    "support": ("Customer Support", "support_info"),
}


def policy_page(request, slug):
    if slug not in POLICY_FIELDS:
        raise Http404
    title, field = POLICY_FIELDS[slug]
    return render(request, "core/policy.html", {"title": title, "body": getattr(SiteSettings.load(), field)})


def error_404(request, exception=None):
    return render(request, "404.html", status=404)


def error_500(request):
    return render(request, "500.html", status=500)
