from django.urls import path

from . import views

app_name = "dashboard"

urlpatterns = [
    path("", views.home, name="home"),
    path("seller/", views.seller_dashboard, name="seller"),
    path("personal/", views.personal_dashboard, name="personal"),
    path("books/", views.my_books, name="my_books"),
    path("payouts/", views.payouts, name="payouts"),
    path("payouts/account/", views.payout_account_save, name="payout_account"),
    path("payouts/request/", views.payout_request, name="payout_request"),
    path("payouts/<int:pk>/cancel/", views.payout_cancel, name="payout_cancel"),
    # Platform administration
    path("platform/", views.platform, name="platform"),
    path("manage/applications/", views.applications, name="applications"),
    path("manage/applications/<int:pk>/<str:decision>/", views.application_decide, name="application_decide"),
    path("manage/books/", views.book_queue, name="book_queue"),
    path("manage/books/<int:pk>/file/", views.book_review_file, name="book_review_file"),
    path("manage/books/<int:pk>/<str:decision>/", views.book_decide, name="book_decide"),
    path("manage/sales/", views.sales, name="sales"),
    path("manage/sales/<int:pk>/refund/", views.sale_refund, name="sale_refund"),
    path("manage/payouts/", views.payout_queue, name="payout_queue"),
    path("manage/payouts/<int:pk>/<str:action>/", views.payout_action, name="payout_action"),
    path("manage/adjustment/", views.adjustment, name="adjustment"),
    path("manage/reviews/", views.reviews_queue, name="reviews"),
    path("manage/reviews/<int:pk>/<str:action>/", views.review_moderate, name="review_moderate"),
    path("manage/audit/", views.audit_log, name="audit"),
]
