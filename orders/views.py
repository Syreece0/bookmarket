from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from catalog.models import Book
from core.ratelimit import ratelimit
from payments.services import PaymentError, initiate_payment

from .models import Entitlement, Order
from .services import CheckoutError, claim_free_book, create_pending_order, owned_book_ids


def _cart_ids(request):
    return [int(x) for x in request.session.get("cart", []) if str(x).isdigit()]


def cart(request):
    books = list(Book.objects.published().filter(pk__in=_cart_ids(request)).select_related("seller"))
    owned = owned_book_ids(request.user) if request.user.is_authenticated else set()
    total = sum((b.price for b in books if b.pk not in owned), start=0)
    return render(request, "orders/cart.html", {"books": books, "owned": owned, "total": total})


@require_POST
def cart_add(request, pk):
    book = get_object_or_404(Book.objects.published(), pk=pk)
    if book.is_free:
        return _claim_redirect(request, book)
    ids = request.session.get("cart", [])
    if str(book.pk) not in ids:
        ids.append(str(book.pk))
    request.session["cart"] = ids
    messages.success(request, f"“{book.title}” added to your cart.")
    return redirect(request.POST.get("next") or "orders:cart")


def _claim_redirect(request, book):
    if not request.user.is_authenticated:
        return redirect(f"/accounts/login/?next={book.get_absolute_url()}")
    return redirect("orders:claim_free", pk=book.pk)


@require_POST
def cart_remove(request, pk):
    request.session["cart"] = [x for x in request.session.get("cart", []) if x != str(pk)]
    return redirect("orders:cart")


@login_required
@require_POST
def claim_free(request, pk):
    book = get_object_or_404(Book.objects.published(), pk=pk)
    try:
        claim_free_book(request.user, book)
    except CheckoutError as exc:
        messages.error(request, str(exc))
        return redirect(book.get_absolute_url())
    messages.success(request, "Added to your library.")
    return redirect("library:home")


@login_required
@require_POST
@ratelimit("checkout", limit=15, window=300)
def checkout(request):
    books = list(Book.objects.published().filter(pk__in=_cart_ids(request)).select_related("seller"))
    try:
        order = create_pending_order(request.user, books)
        url = initiate_payment(order, request)
    except (CheckoutError, PaymentError) as exc:
        messages.error(request, str(exc))
        return redirect("orders:cart")
    return redirect(url)


@login_required
def order_list(request):
    orders = Order.objects.filter(customer=request.user).prefetch_related("items")
    return render(request, "orders/order_list.html", {"orders": orders})


@login_required
def order_detail(request, reference):
    order = get_object_or_404(Order.objects.prefetch_related("items__book"), reference=reference, customer=request.user)
    return render(request, "orders/order_detail.html", {"order": order})
