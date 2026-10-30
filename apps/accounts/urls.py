from django.urls import path

from . import views

urlpatterns = [
    path("sicherheit/", views.security, name="account_security"),
]
