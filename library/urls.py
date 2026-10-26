from django.urls import path

from . import views

app_name = "library"

urlpatterns = [
    path("", views.home, name="home"),
    path("read/<slug:slug>/", views.read, name="read"),
    path("file/<slug:slug>/", views.stream, name="stream"),
    path("download/<slug:slug>/", views.download, name="download"),
    path("progress/<slug:slug>/", views.save_progress, name="progress"),
]
