from django.urls import path

from . import views

app_name = "orders"

urlpatterns = [
    path("cart/", views.cart, name="cart"),
    path("cart/add/<int:pk>/", views.cart_add, name="cart_add"),
    path("cart/remove/<int:pk>/", views.cart_remove, name="cart_remove"),
    path("checkout/", views.checkout, name="checkout"),
    path("get-free/<int:pk>/", views.claim_free, name="claim_free"),
    path("orders/", views.order_list, name="order_list"),
    path("orders/<str:reference>/", views.order_detail, name="order_detail"),
]
