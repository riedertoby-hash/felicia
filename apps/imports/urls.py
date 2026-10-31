from django.urls import path

from . import views

app_name = "imports"
urlpatterns = [
    path("", views.upload, name="upload"),
    path("bestaetigen/", views.confirm, name="confirm"),
    path("<int:pk>/", views.batch_detail, name="batch"),
    path("<int:pk>/einladen/", views.batch_invite, name="batch_invite"),
    path("organisation/<int:pk>/einladen/", views.invite_org, name="invite_org"),
]
