from django import forms
from django.contrib import messages
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_POST

from apps.audit.services import log
from apps.orgs.decorators import org_required

from .models import SCOPE_PERMISSION, SCOPES, ApiKey


class KeyForm(forms.Form):
    name = forms.CharField(label="Bezeichnung", max_length=80, help_text="z.B. Warenwirtschaft, Lager-App")
    scopes = forms.MultipleChoiceField(label="Darf", choices=SCOPES, widget=forms.CheckboxSelectMultiple)

    def __init__(self, *args, membership, **kwargs):
        super().__init__(*args, **kwargs)
        # Nobody can hand out more rights than they have themselves.
        self.fields["scopes"].choices = [(k, label) for k, label in SCOPES if membership.has_perm(SCOPE_PERMISSION[k])]


@org_required("org.edit", kind="supplier")
def key_list(request):
    form = KeyForm(request.POST or None, membership=request.membership)
    new_key = None
    if request.method == "POST" and form.is_valid():
        key, new_key = ApiKey.issue(
            organization=request.org,
            name=form.cleaned_data["name"],
            scopes=form.cleaned_data["scopes"],
            user=request.user,
        )
        log("api.key_created", request=request, organization=request.org, target=key, changes={"rechte": key.scopes})
        form = KeyForm(membership=request.membership)
    return render(
        request,
        "api/keys.html",
        {
            "form": form,
            "new_key": new_key,
            "base_url": request.build_absolute_uri("/api/v1/"),
            "keys": ApiKey.objects.filter(organization=request.org).select_related("created_by"),
            "scope_labels": dict(SCOPES),
        },
    )


@require_POST
@org_required("org.edit", kind="supplier")
def revoke(request, pk):
    key = get_object_or_404(ApiKey, pk=pk, organization=request.org, revoked_at__isnull=True)
    key.revoked_at = timezone.now()
    key.save(update_fields=["revoked_at"])
    log("api.key_revoked", request=request, organization=request.org, target=key)
    messages.success(request, f"Schlüssel «{key.name}» widerrufen.")
    return redirect("api:keys")
