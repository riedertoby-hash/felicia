from allauth.mfa.models import Authenticator
from allauth.usersessions.models import UserSession
from django.contrib.auth.decorators import login_required
from django.shortcuts import render

from .middleware import requires_mfa


@login_required
def security(request):
    authenticators = Authenticator.objects.filter(user=request.user)
    return render(
        request,
        "accounts/security.html",
        {
            "has_totp": authenticators.filter(type=Authenticator.Type.TOTP).exists(),
            "passkey_count": authenticators.filter(type=Authenticator.Type.WEBAUTHN).count(),
            "mfa_required": requires_mfa(request),
            "session_count": UserSession.objects.filter(user=request.user).count(),
        },
    )
