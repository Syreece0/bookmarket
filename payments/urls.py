from django.urls import path

from . import views

app_name = "payments"

urlpatterns = [
    path("callback/", views.callback, name="callback"),
    path("webhook/paystack/", views.webhook, name="webhook"),
]
