from allauth.account.signals import password_changed, password_reset
from allauth.mfa.signals import authenticator_added, authenticator_removed
from django.contrib.auth import get_user_model
from django.contrib.auth.signals import user_logged_in, user_logged_out, user_login_failed
from django.dispatch import receiver

from .services import log


@receiver(user_logged_in)
def on_login(sender, request, user, **kwargs):
    log("auth.login", request=request, actor=user)


@receiver(user_logged_out)
def on_logout(sender, request, user, **kwargs):
    if user is not None:
        log("auth.logout", request=request, actor=user)


@receiver(user_login_failed)
def on_login_failed(sender, credentials, request=None, **kwargs):
    email = (credentials or {}).get("email") or (credentials or {}).get("username") or ""
    user = get_user_model().objects.filter(email=str(email).lower()).first()
    if user is not None:
        log("auth.login_failed", request=request, actor=user)


@receiver(password_changed)
def on_password_changed(sender, request, user, **kwargs):
    log("auth.password_changed", request=request, actor=user)


@receiver(password_reset)
def on_password_reset(sender, request, user, **kwargs):
    log("auth.password_reset", request=request, actor=user)


@receiver(authenticator_added)
def on_mfa_added(sender, request, user, authenticator, **kwargs):
    log("auth.mfa_added", request=request, actor=user, changes={"type": authenticator.type})


@receiver(authenticator_removed)
def on_mfa_removed(sender, request, user, authenticator, **kwargs):
    log("auth.mfa_removed", request=request, actor=user, changes={"type": authenticator.type})
