from django.urls import path

from . import views

app_name = "orgs"
urlpatterns = [
    path("", views.team, name="team"),
    path("einladen/", views.invite, name="invite"),
    path("mitglied/<int:pk>/rolle/", views.change_role, name="change_role"),
    path("mitglied/<int:pk>/entfernen/", views.remove_member, name="remove_member"),
    path("einladung/<int:pk>/zurueckziehen/", views.revoke_invitation, name="revoke_invitation"),
    path("einladung/<str:token>/", views.accept, name="accept"),
    path("wechseln/", views.switch, name="switch"),
]
