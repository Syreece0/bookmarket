from django.urls import path

from . import views

app_name = "catalog"

urlpatterns = [
    path("", views.book_list, name="list"),
    path("new/", views.book_create, name="create"),
    path("edit/<int:pk>/", views.book_edit, name="edit"),
    path("kind/<str:kind>/", views.kind_list, name="kind"),
    path("category/<slug:slug>/", views.category_list, name="category"),
    path("<slug:slug>/preview/", views.book_preview, name="preview"),
    path("<slug:slug>/", views.book_detail, name="detail"),
]
