from django.urls import path

from . import views

app_name = "suppliers"
urlpatterns = [
    path("", views.dashboard, name="dashboard"),
    path("profil/", views.profile, name="profile"),
    path("bank/", views.bank, name="bank"),
    path("benachrichtigungen/", views.notifications, name="notifications"),
]
