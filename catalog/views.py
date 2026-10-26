from django.contrib import messages
from django.core.exceptions import PermissionDenied
from django.core.paginator import Paginator
from django.db.models import Avg, Count, Q
from django.http import FileResponse, Http404
from django.shortcuts import get_object_or_404, redirect, render

from accounts.decorators import seller_required
from core.ratelimit import ratelimit

from .forms import BookForm
from .models import Book, Category

SORTS = {
    "newest": ("-published_at", "Newest"),
    "price_asc": ("price", "Price: low to high"),
    "price_desc": ("-price", "Price: high to low"),
    "rating": ("-avg_rating", "Top rated"),
    "popular": ("-units", "Best selling"),
}


def _listing(request, base_qs, title, kind=None, category=None):
    qs = base_qs.select_related("category", "seller").annotate(
        avg_rating=Avg("reviews__rating", filter=Q(reviews__status="published")),
        units=Count("order_items", filter=Q(order_items__order__status="paid", order_items__refunded_at__isnull=True), distinct=True),
    )
    q = request.GET.get("q", "").strip()
    if q:
        qs = qs.filter(Q(title__icontains=q) | Q(author_name__icontains=q) | Q(description__icontains=q))
    if kind:
        qs = qs.filter(category__kind=kind)
    price = request.GET.get("price")
    if price == "free":
        qs = qs.filter(price=0)
    elif price == "paid":
        qs = qs.filter(price__gt=0)
    sub = request.GET.get("category")
    if sub:
        qs = qs.filter(Q(category__slug=sub) | Q(category__parent__slug=sub))
    sort = request.GET.get("sort", "newest")
    if sort not in SORTS:
        sort = "newest"
    qs = qs.order_by(SORTS[sort][0], "-id")
    page = Paginator(qs, 12).get_page(request.GET.get("page"))
    params = request.GET.copy()
    params.pop("page", None)
    return render(request, "catalog/list.html", {
        "page": page, "title": title, "kind": kind, "q": q, "sort": sort, "sorts": SORTS, "price": price,
        "active_category": sub, "category": category, "querystring": params.urlencode(),
        "categories": Category.objects.filter(parent__isnull=True, **({"kind": kind} if kind else {})).prefetch_related("children"),
    })


def book_list(request):
    return _listing(request, Book.objects.published(), "All books", kind=request.GET.get("kind") or None)


def kind_list(request, kind):
    if kind not in Category.Kind.values:
        raise Http404
    return _listing(request, Book.objects.published(), Category.Kind(kind).label + " books", kind=kind)


def category_list(request, slug):
    category = get_object_or_404(Category, slug=slug)
    scope = Q(category=category) | Q(category__parent=category)
    return _listing(request, Book.objects.published().filter(scope), category.name, kind=category.kind, category=category)


def book_detail(request, slug):
    book = get_object_or_404(Book.objects.select_related("category", "seller"), slug=slug)
    user = request.user
    is_owner_or_staff = user.is_authenticated and (book.seller_id == user.id or user.is_platform_admin)
    if book.status != Book.Status.PUBLISHED and not is_owner_or_staff:
        raise Http404
    from engagement.models import Review, WishlistItem
    from orders.models import Entitlement

    owned = user.is_authenticated and Entitlement.objects.active().filter(user=user, book=book).exists()
    reviews = Review.objects.filter(book=book, status=Review.Status.PUBLISHED).select_related("user")
    stats = reviews.aggregate(avg=Avg("rating"), n=Count("id"))
    ctx = {
        "book": book, "owned": owned, "reviews": reviews[:20], "rating_avg": stats["avg"], "rating_count": stats["n"],
        "in_wishlist": user.is_authenticated and WishlistItem.objects.filter(user=user, book=book).exists(),
        "in_cart": str(book.pk) in request.session.get("cart", []),
        "can_review": owned and not Review.objects.filter(book=book, user=user).exists(),
        "related": Book.objects.published().filter(category=book.category).exclude(pk=book.pk)[:4],
    }
    return render(request, "catalog/detail.html", ctx)


def book_preview(request, slug):
    """Public free preview. Only the generated sample PDF is ever served, never the full file."""
    book = get_object_or_404(Book.objects.published(), slug=slug)
    if not book.has_preview:
        raise Http404
    return FileResponse(book.preview_file.open("rb"), content_type="application/pdf", headers={"Content-Disposition": "inline"})


@seller_required
@ratelimit("book_upload", limit=20, window=3600)
def book_create(request):
    form = BookForm(request.POST or None, request.FILES or None, seller=request.user)
    if request.method == "POST" and form.is_valid():
        book = form.save()
        if book.status == Book.Status.PENDING:
            messages.success(request, "Book submitted for review. You will be notified of the decision.")
        else:
            messages.success(request, "Book published.")
        return redirect("dashboard:my_books")
    return render(request, "catalog/book_form.html", {"form": form, "editing": False})


@seller_required
def book_edit(request, pk):
    book = get_object_or_404(Book, pk=pk)
    if book.seller_id != request.user.id:
        raise PermissionDenied
    form = BookForm(request.POST or None, request.FILES or None, instance=book, seller=request.user)
    if request.method == "POST" and form.is_valid():
        updated = form.save()
        msg = "Changes saved." if updated.status == Book.Status.PUBLISHED else "Changes saved and sent for review."
        messages.success(request, msg)
        return redirect("dashboard:my_books")
    return render(request, "catalog/book_form.html", {"form": form, "editing": True, "book": book})
