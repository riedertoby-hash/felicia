from datetime import date, timedelta
from decimal import Decimal, InvalidOperation

from django import forms
from django.contrib import messages
from django.core.exceptions import ValidationError
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone

from apps.audit.services import log
from apps.delivery import services as delivery
from apps.orgs.decorators import org_required

from . import standing as standing_services
from .models import Order, StandingOrder
from .services import check_quantity


class CreateForm(forms.Form):
    name = forms.CharField(label="Bezeichnung", max_length=80, required=False, help_text="z.B. Gemüse für die Woche")
    interval_weeks = forms.TypedChoiceField(
        label="Rhythmus", choices=StandingOrder.Interval.choices, coerce=int, widget=forms.RadioSelect, initial=1
    )
    first_date = forms.TypedChoiceField(label="Erste Lieferung", coerce=date.fromisoformat)

    def __init__(self, *args, dates, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["first_date"].choices = [(d.isoformat(), f"{d:%A, %d.%m.%Y}") for d in dates]


def _future_dates(option, count=8):
    return delivery.possible_dates(option, 0, count=count)


@org_required("shop.order", kind="customer")
def create(request, order_pk):
    order = get_object_or_404(Order, pk=order_pk, customer=request.org)
    option = order.supplier.delivery_options.filter(
        is_active=True, name=order.delivery_name, kind=order.delivery_kind
    ).first()
    dates = _future_dates(option) if option else []
    form = CreateForm(request.POST or None, dates=dates)
    if request.method == "POST" and form.is_valid():
        try:
            standing = standing_services.create_from_order(
                order=order,
                user=request.user,
                interval_weeks=form.cleaned_data["interval_weeks"],
                first_date=form.cleaned_data["first_date"],
                name=form.cleaned_data["name"],
                request=request,
            )
            messages.success(request, "Dauerauftrag angelegt. Sie können ihn jederzeit anpassen oder pausieren.")
            return redirect("orders:standing", pk=standing.pk)
        except ValidationError as exc:
            messages.error(request, exc.messages[0])
    return render(request, "orders/standing_create.html", {"order": order, "form": form, "option": option})


@org_required("shop.order", kind="customer")
def standing_list(request):
    today = timezone.localdate()
    items = (
        StandingOrder.objects.filter(customer=request.org)
        .select_related("supplier", "option")
        .prefetch_related("items__variant__product")
    )
    for s in items:
        s.next_dates = s.upcoming(today + timedelta(days=1), count=4) if s.is_active else []
    return render(request, "orders/standing_list.html", {"standing_orders": items})


def _own(request, pk):
    return get_object_or_404(
        StandingOrder.objects.select_related("supplier", "option", "address"), pk=pk, customer=request.org
    )


@org_required("shop.order", kind="customer")
def detail(request, pk):
    s = _own(request, pk)
    if request.method == "POST":
        action = request.POST.get("action")
        if action == "quantities":
            _save_quantities(request, s)
        elif action in ("skip", "unskip"):
            day = request.POST.get("date", "")
            dates = set(s.skipped_dates)
            (dates.add if action == "skip" else dates.discard)(day)
            s.skipped_dates = sorted(dates)
            s.save(update_fields=["skipped_dates", "updated_at"])
            messages.success(
                request,
                f"Lieferung vom {date.fromisoformat(day):%d.%m.%Y} "
                f"{'ausgelassen' if action == 'skip' else 'wieder aktiv'}.",
            )
        elif action == "pause":
            try:
                s.paused_until = date.fromisoformat(request.POST.get("paused_until", "")) or None
            except ValueError:
                s.paused_until = None
            s.save(update_fields=["paused_until", "updated_at"])
            messages.success(
                request, f"Pausiert bis {s.paused_until:%d.%m.%Y}." if s.paused_until else "Pause aufgehoben."
            )
        elif action == "end":
            s.is_active = False
            s.save(update_fields=["is_active", "updated_at"])
            messages.success(request, "Dauerauftrag beendet.")
        elif action == "resume":
            s.is_active = True
            s.save(update_fields=["is_active", "updated_at"])
            messages.success(request, "Dauerauftrag wieder aktiv.")
        log("standing.updated", request=request, organization=request.org, target=s, changes={"aktion": action})
        return redirect("orders:standing", pk=s.pk)
    today = timezone.localdate()
    return render(
        request,
        "orders/standing_detail.html",
        {
            "s": s,
            "items": s.items.select_related("variant__product"),
            "next_dates": s.upcoming(today + timedelta(days=1), count=6),
        },
    )


def _save_quantities(request, s):
    errors = []
    for item in s.items.select_related("variant__product"):
        raw = request.POST.get(f"qty_{item.pk}", "").replace(",", ".").strip()
        try:
            qty = Decimal(raw)
        except InvalidOperation:
            errors.append(f"{item.variant.product.name}: ungültige Menge")
            continue
        if qty <= 0:
            item.delete()
            continue
        try:
            check_quantity(item.variant, qty)
        except ValidationError as exc:
            errors.append(f"{item.variant.product.name}: {exc.messages[0]}")
            continue
        item.quantity = qty
        item.save(update_fields=["quantity"])
    if errors:
        messages.error(request, "; ".join(errors))
    else:
        messages.success(request, "Mengen gespeichert.")


@org_required("orders.view", kind="supplier")
def supplier_list(request):
    today = timezone.localdate()
    items = (
        StandingOrder.objects.filter(supplier=request.org, is_active=True)
        .select_related("customer", "option")
        .prefetch_related("items__variant__product")
    )
    for s in items:
        s.next_dates = s.upcoming(today + timedelta(days=1), count=3)
    return render(request, "orders/standing_supplier.html", {"standing_orders": items})
