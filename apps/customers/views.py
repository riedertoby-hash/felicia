from django.contrib import messages
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from apps.audit.services import diff, log, snapshot
from apps.orgs.decorators import org_required

from .forms import AddressForm, ProfileForm
from .models import Address

KIND = "customer"


@org_required(kind=KIND)
def dashboard(request):
    return render(
        request,
        "customers/dashboard.html",
        {
            "profile": request.org.customer_profile,
            "addresses": request.org.addresses.all()[:3],
        },
    )


@org_required("org.edit", kind=KIND)
def profile(request):
    instance = request.org.customer_profile
    fields = ProfileForm.Meta.fields
    before = snapshot(instance, fields)
    form = ProfileForm(request.POST or None, instance=instance)
    if request.method == "POST" and form.is_valid():
        form.save()
        changes = diff(before, snapshot(instance, fields), fields)
        if changes:
            log("org.updated", request=request, organization=request.org, target=request.org, changes=changes)
        messages.success(request, "Profil gespeichert.")
        return redirect("customers:profile")
    return render(request, "customers/profile.html", {"form": form})


@org_required("customer.addresses", kind=KIND)
def addresses(request):
    return render(request, "customers/addresses.html", {"addresses": request.org.addresses.all()})


@org_required("customer.addresses", kind=KIND)
def address_edit(request, pk=None):
    instance = get_object_or_404(Address, pk=pk, organization=request.org) if pk else Address(organization=request.org)
    form = AddressForm(request.POST or None, instance=instance)
    if request.method == "POST" and form.is_valid():
        address = form.save()
        log("address.saved", request=request, organization=request.org, target=address)
        messages.success(request, "Adresse gespeichert.")
        return redirect("customers:addresses")
    return render(request, "customers/address_form.html", {"form": form, "address": instance})


@require_POST
@org_required("customer.addresses", kind=KIND)
def address_delete(request, pk):
    address = get_object_or_404(Address, pk=pk, organization=request.org)
    log("address.deleted", request=request, organization=request.org, target=address)
    address.delete()
    messages.success(request, "Adresse gelöscht.")
    return redirect("customers:addresses")
