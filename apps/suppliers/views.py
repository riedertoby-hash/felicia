from django.contrib import messages
from django.shortcuts import redirect, render

from apps.audit.services import diff, log, snapshot
from apps.orgs.decorators import org_required

from .forms import BankForm, NotificationForm, ProfileForm

KIND = "supplier"


def _profile(request):
    return request.org.supplier_profile


@org_required(kind=KIND)
def dashboard(request):
    profile = _profile(request)
    terms = getattr(request.org, "terms", None)
    return render(
        request,
        "suppliers/dashboard.html",
        {
            "profile": profile,
            "checklist": profile.completeness(),
            "commission": terms.effective_commission() if terms else None,
            "base_fee": terms.effective_base_fee() if terms else None,
        },
    )


def _save_with_audit(request, form, action, fields, before, masked=()):
    form.save()
    changes = diff(before, snapshot(form.instance, fields), fields, masked=masked)
    if changes:
        log(action, request=request, organization=request.org, target=request.org, changes=changes)


@org_required("org.view", kind=KIND)
def profile(request):
    instance = _profile(request)
    can_edit = request.membership.has_perm("org.edit")
    audit_fields = [f for f in ProfileForm.Meta.fields if f != "logo"]
    before = snapshot(instance, audit_fields)
    form = ProfileForm(request.POST or None, request.FILES or None, instance=instance)
    if request.method == "POST":
        if not can_edit:
            messages.error(request, "Ihre Rolle erlaubt keine Änderungen am Profil.")
            return redirect("suppliers:profile")
        if form.is_valid():
            _save_with_audit(request, form, "org.updated", audit_fields, before)
            messages.success(request, "Profil gespeichert.")
            return redirect("suppliers:profile")
    if not can_edit:
        for field in form.fields.values():
            field.disabled = True
    return render(request, "suppliers/profile.html", {"form": form, "can_edit": can_edit})


@org_required("org.bank", kind=KIND)
def bank(request):
    instance = _profile(request)
    before = snapshot(instance, ["account_holder", "iban"])
    form = BankForm(request.POST or None, instance=instance, initial={"iban": ""})
    if request.method == "POST" and form.is_valid():
        _save_with_audit(request, form, "org.bank_updated", ["account_holder", "iban"], before, masked=("iban",))
        messages.success(request, "Bankverbindung gespeichert.")
        return redirect("suppliers:bank")
    return render(request, "suppliers/bank.html", {"form": form, "profile": instance})


@org_required("org.edit", kind=KIND)
def notifications(request):
    instance = _profile(request)
    before = snapshot(instance, NotificationForm.Meta.fields)
    form = NotificationForm(request.POST or None, instance=instance)
    if request.method == "POST" and form.is_valid():
        _save_with_audit(request, form, "org.updated", NotificationForm.Meta.fields, before)
        messages.success(request, "Benachrichtigungen gespeichert.")
        return redirect("suppliers:notifications")
    return render(request, "suppliers/notifications.html", {"form": form})
