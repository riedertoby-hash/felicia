from allauth.account.models import EmailAddress
from django.contrib import messages
from django.contrib.auth import get_user_model, login
from django.core.exceptions import PermissionDenied, ValidationError
from django.core.mail import send_mail
from django.db import transaction
from django.shortcuts import get_object_or_404, redirect, render
from django.template.loader import render_to_string
from django.urls import reverse
from django.views.decorators.http import require_POST

from . import services
from .decorators import org_required
from .forms import InviteForm, InviteSignupForm, RoleForm
from .middleware import SESSION_KEY
from .models import Invitation, Membership

User = get_user_model()


@org_required("team.manage")
def team(request):
    org = request.org
    members = (
        Membership.objects.filter(organization=org)
        .select_related("user", "role")
        .order_by("role__sort", "user__last_name")
    )
    for m in members:
        m.role_form = RoleForm(org=org, initial={"role": m.role}, prefix=f"m{m.pk}")
    return render(
        request,
        "orgs/team.html",
        {
            "members": members,
            "invitations": Invitation.objects.open().filter(organization=org).select_related("role"),
            "invite_form": InviteForm(org=org),
        },
    )


@require_POST
@org_required("team.manage")
def invite(request):
    form = InviteForm(request.POST, org=request.org)
    if form.is_valid():
        try:
            invitation, token = services.invite(
                organization=request.org,
                email=form.cleaned_data["email"],
                role=form.cleaned_data["role"],
                request=request,
            )
        except ValidationError as exc:
            messages.error(request, exc.messages[0])
        else:
            _send_invitation(request, invitation, token)
            messages.success(request, f"Einladung an {invitation.email} verschickt.")
    else:
        messages.error(request, "Bitte eine gültige E-Mail-Adresse angeben.")
    return redirect("orgs:team")


def _send_invitation(request, invitation, token):
    link = request.build_absolute_uri(reverse("orgs:accept", args=[token]))
    context = {"invitation": invitation, "link": link, "inviter": request.user}
    send_mail(
        subject=f"Einladung zu {invitation.organization.name}",
        message=render_to_string("orgs/email/invitation.txt", context),
        from_email=None,
        recipient_list=[invitation.email],
    )


@require_POST
@org_required("team.manage")
def change_role(request, pk):
    membership = get_object_or_404(Membership, pk=pk, organization=request.org)
    form = RoleForm(request.POST, org=request.org, prefix=f"m{pk}")
    if form.is_valid():
        try:
            services.change_role(membership=membership, role=form.cleaned_data["role"], request=request)
            messages.success(request, f"Rolle von {membership.user} geändert.")
        except (ValidationError, PermissionDenied) as exc:
            messages.error(request, _msg(exc))
    return redirect("orgs:team")


@require_POST
@org_required("team.manage")
def remove_member(request, pk):
    membership = get_object_or_404(Membership, pk=pk, organization=request.org)
    try:
        services.remove_member(membership=membership, request=request)
        messages.success(request, f"{membership.user} entfernt.")
    except (ValidationError, PermissionDenied) as exc:
        messages.error(request, _msg(exc))
    return redirect("orgs:team")


@require_POST
@org_required("team.manage")
def revoke_invitation(request, pk):
    invitation = get_object_or_404(Invitation.objects.open(), pk=pk, organization=request.org)
    services.revoke_invitation(invitation=invitation, request=request)
    messages.success(request, f"Einladung an {invitation.email} zurückgezogen.")
    return redirect("orgs:team")


def accept(request, token):
    invitation = Invitation.find_open(token)
    if invitation is None or invitation.organization.tenant_id != request.tenant.pk:
        return render(request, "orgs/invitation_invalid.html", status=404)

    if request.user.is_authenticated:
        if request.method == "POST":
            try:
                services.accept_invitation(invitation=invitation, user=request.user, request=request)
            except (ValidationError, PermissionDenied) as exc:
                messages.error(request, _msg(exc))
                return redirect("home")
            request.session[SESSION_KEY] = invitation.organization_id
            messages.success(request, f"Willkommen bei {invitation.organization.name}.")
            return redirect("home")
        return render(request, "orgs/invitation_accept.html", {"invitation": invitation})

    if User.objects.filter(email=invitation.email).exists():
        login_url = reverse("account_login") + "?next=" + request.path
        return render(request, "orgs/invitation_login.html", {"invitation": invitation, "login_url": login_url})

    form = InviteSignupForm(request.POST or None, email=invitation.email)
    if request.method == "POST" and form.is_valid():
        with transaction.atomic():
            user = User.objects.create_user(
                email=invitation.email,
                password=form.cleaned_data["password1"],
                first_name=form.cleaned_data["first_name"],
                last_name=form.cleaned_data["last_name"],
            )
            # The token reached this address, so the address is verified.
            EmailAddress.objects.create(user=user, email=user.email, verified=True, primary=True)
            services.accept_invitation(invitation=invitation, user=user, request=request)
        login(request, user, backend="django.contrib.auth.backends.ModelBackend")
        request.session[SESSION_KEY] = invitation.organization_id
        messages.success(request, f"Willkommen bei {invitation.organization.name}.")
        return redirect("home")
    return render(request, "orgs/invitation_signup.html", {"invitation": invitation, "form": form})


@require_POST
def switch(request):
    try:
        org_id = int(request.POST.get("organization", ""))
    except ValueError:
        org_id = None
    if any(m.organization_id == org_id for m in request.memberships):
        request.session[SESSION_KEY] = org_id
    return redirect("home")


def _msg(exc):
    if isinstance(exc, ValidationError):
        return exc.messages[0]
    return str(exc) or "Nicht erlaubt."
