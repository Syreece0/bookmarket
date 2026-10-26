from django import forms
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db import IntegrityError
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from catalog.models import Book
from core.ratelimit import ratelimit
from orders.models import Entitlement

from .models import Notification, Review, ReviewReport, WishlistItem


class ReviewForm(forms.ModelForm):
    rating = forms.IntegerField(min_value=1, max_value=5)

    class Meta:
        model = Review
        fields = ("rating", "text")
        widgets = {"text": forms.Textarea(attrs={"rows": 4})}


@login_required
def wishlist(request):
    items = WishlistItem.objects.filter(user=request.user).select_related("book", "book__category")
    return render(request, "engagement/wishlist.html", {"items": items})


@login_required
@require_POST
def wishlist_toggle(request, pk):
    book = get_object_or_404(Book.objects.published(), pk=pk)
    obj, created = WishlistItem.objects.get_or_create(user=request.user, book=book)
    if not created:
        obj.delete()
        messages.info(request, "Removed from your wishlist.")
    else:
        messages.success(request, "Saved to your wishlist.")
    return redirect(request.POST.get("next") or book.get_absolute_url())


@login_required
@require_POST
@ratelimit("review", limit=10, window=3600)
def review_create(request, pk):
    book = get_object_or_404(Book.objects.published(), pk=pk)
    if not Entitlement.objects.active().filter(user=request.user, book=book).exists():
        messages.error(request, "Only readers who own this book can review it.")
        return redirect(book.get_absolute_url())
    form = ReviewForm(request.POST)
    if form.is_valid():
        review = form.save(commit=False)
        review.book, review.user = book, request.user
        try:
            review.save()
            messages.success(request, "Thank you for your review.")
        except IntegrityError:
            messages.info(request, "You have already reviewed this book.")
    else:
        messages.error(request, "Please choose a rating from 1 to 5 and write a short review.")
    return redirect(book.get_absolute_url())


@login_required
@require_POST
def review_report(request, pk):
    review = get_object_or_404(Review, pk=pk)
    _, created = ReviewReport.objects.get_or_create(
        review=review, reporter=request.user, defaults={"reason": request.POST.get("reason", "Reported")[:240]})
    if created:
        review.report_count += 1
        if review.report_count >= 3 and review.status == Review.Status.PUBLISHED:
            review.status = Review.Status.FLAGGED
        review.save(update_fields=["report_count", "status"])
    messages.info(request, "Thanks. A moderator will take a look.")
    return redirect(review.book.get_absolute_url())


@login_required
def notifications(request):
    qs = Notification.objects.filter(user=request.user)[:50]
    items = list(qs)
    Notification.objects.filter(user=request.user, is_read=False).update(is_read=True)
    return render(request, "engagement/notifications.html", {"items": items})
