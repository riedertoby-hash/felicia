from django.contrib import messages
from django.db import transaction
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from apps.audit.services import log
from apps.orgs.decorators import org_required

from .forms import FeeTierFormSet, OptionForm, ZoneForm
from .models import DeliveryOption, DeliveryZone

KIND = "supplier"


def _options(request):
    return DeliveryOption.objects.filter(supplier=request.org)


@org_required("org.view", kind=KIND)
def overview(request):
    return render(
        request,
        "delivery/overview.html",
        {
            "options": _options(request).prefetch_related("zones__fee_tiers"),
            "can_edit": request.membership.has_perm("delivery.edit"),
        },
    )


@org_required("delivery.edit", kind=KIND)
def option_edit(request, pk=None):
    option = get_object_or_404(_options(request), pk=pk) if pk else DeliveryOption(supplier=request.org)
    form = OptionForm(request.POST or None, instance=option)
    if request.method == "POST" and form.is_valid():
        form.save()
        log(
            "delivery.updated",
            request=request,
            organization=request.org,
            target=option,
            changes={"lieferart": option.name},
        )
        messages.success(request, f"«{option.name}» gespeichert.")
        if not option.is_pickup and not option.zones.exists():
            messages.info(request, "Jetzt noch mindestens eine Lieferzone erfassen.")
            return redirect("delivery:zone_new", option_pk=option.pk)
        return redirect("delivery:overview")
    return render(request, "delivery/option_form.html", {"form": form, "option": option})


@require_POST
@org_required("delivery.edit", kind=KIND)
def option_delete(request, pk):
    option = get_object_or_404(_options(request), pk=pk)
    log("delivery.updated", request=request, organization=request.org, target=option, changes={"gelöscht": option.name})
    option.delete()
    messages.success(request, "Lieferart gelöscht.")
    return redirect("delivery:overview")


@org_required("delivery.edit", kind=KIND)
def zone_edit(request, option_pk, pk=None):
    option = get_object_or_404(_options(request), pk=option_pk)
    zone = get_object_or_404(DeliveryZone, pk=pk, option=option) if pk else DeliveryZone(option=option)
    form = ZoneForm(request.POST or None, instance=zone)
    tiers = FeeTierFormSet(request.POST or None, instance=zone, prefix="t")
    if request.method == "POST" and form.is_valid() and tiers.is_valid():
        with transaction.atomic():
            form.save()
            tiers.save()
        log(
            "delivery.updated",
            request=request,
            organization=request.org,
            target=zone,
            changes={
                "zone": zone.name,
                "mindestbestellwert": str(zone.min_order_value),
                "gebühren": [[str(t.from_value), str(t.fee)] for t in zone.fee_tiers.all()],
            },
        )
        messages.success(request, f"Zone «{zone.name}» gespeichert.")
        return redirect("delivery:overview")
    return render(request, "delivery/zone_form.html", {"form": form, "tiers": tiers, "option": option, "zone": zone})


@require_POST
@org_required("delivery.edit", kind=KIND)
def zone_delete(request, option_pk, pk):
    zone = get_object_or_404(DeliveryZone, pk=pk, option__pk=option_pk, option__supplier=request.org)
    zone.delete()
    messages.success(request, "Zone gelöscht.")
    return redirect("delivery:overview")
