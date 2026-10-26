from django.urls import path

from . import views

app_name = "engagement"

urlpatterns = [
    path("wishlist/", views.wishlist, name="wishlist"),
    path("wishlist/toggle/<int:pk>/", views.wishlist_toggle, name="wishlist_toggle"),
    path("reviews/add/<int:pk>/", views.review_create, name="review_create"),
    path("reviews/report/<int:pk>/", views.review_report, name="review_report"),
    path("notifications/", views.notifications, name="notifications"),
]
