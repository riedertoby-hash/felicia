from datetime import date

from django.contrib import messages
from django.core.exceptions import ValidationError
from django.core.paginator import Paginator
from django.http import HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from apps.orgs.decorators import org_required

from . import services
from .forms import QuantityForm
from .models import CartItem, Order

KIND = "customer"


def _render_cart_badge(request):
    return render(
        request, "orders/partials/cart_badge.html", {"cart_count": services.cart_count(request.org, request.user)}
    )


@require_POST
@org_required("shop.order", kind=KIND)
def add(request, variant_id):
    variant = get_object_or_404(services.visible_variants(request.tenant).select_related("product"), pk=variant_id)
    form = QuantityForm(request.POST)
    quantity = form.cleaned_data["quantity"] if form.is_valid() else variant.min_qty
    try:
        services.add_to_cart(customer=request.org, user=request.user, variant=variant, quantity=quantity)
        text, ok = f"{variant.product.name} ({variant.name}) im Warenkorb.", True
    except ValidationError as exc:
        text, ok = exc.messages[0], False
    if request.headers.get("HX-Request"):
        response = render(
            request,
            "orders/partials/add_result.html",
            {"ok": ok, "text": text, "cart_count": services.cart_count(request.org, request.user)},
        )
        return response
    (messages.success if ok else messages.error)(request, text)
    return redirect(request.POST.get("next") or "shop:index")


@org_required("shop.order", kind=KIND)
def cart(request):
    addresses = list(request.org.addresses.all())
    address = _chosen_address(request, addresses)
    groups = services.group_cart(request.org, request.user, address)
    return render(
        request,
        "orders/cart.html",
        {
            "groups": groups,
            "addresses": addresses,
            "address": address,
            "grand_total": sum((g.goods_value for g in groups), 0),
        },
    )


def _chosen_address(request, addresses):
    wanted = request.GET.get("adresse") or request.POST.get("adresse")
    if wanted == "abholung":
        return None
    for a in addresses:
        if str(a.pk) == wanted:
            return a
    return next((a for a in addresses if a.is_default), addresses[0] if addresses else None)


@require_POST
@org_required("shop.order", kind=KIND)
def update_item(request, pk):
    item = get_object_or_404(CartItem, pk=pk, customer=request.org, user=request.user)
    form = QuantityForm(request.POST)
    if form.is_valid():
        try:
            services.set_quantity(item, form.cleaned_data["quantity"])
        except ValidationError as exc:
            messages.error(request, exc.messages[0])
    return redirect(_cart_url(request))


@require_POST
@org_required("shop.order", kind=KIND)
def remove_item(request, pk):
    CartItem.objects.filter(pk=pk, customer=request.org, user=request.user).delete()
    return redirect(_cart_url(request))


def _cart_url(request):
    url = "/kunde/warenkorb/"
    if request.POST.get("adresse"):
        url += f"?adresse={request.POST['adresse']}"
    return url


@require_POST
@org_required("shop.order", kind=KIND)
def checkout(request):
    addresses = list(request.org.addresses.all())
    address = _chosen_address(request, addresses)
    choices = {}
    for key, value in request.POST.items():
        if key.startswith("option_"):
            supplier_id = int(key.split("_", 1)[1])
            try:
                day = date.fromisoformat(request.POST.get(f"date_{supplier_id}", ""))
            except ValueError:
                day = None
            choices[supplier_id] = (int(value) if value.isdigit() else None, day)
    try:
        orders = services.place_orders(
            request=request,
            customer=request.org,
            user=request.user,
            address=address,
            choices=choices,
            note=request.POST.get("note", "")[:1000],
        )
    except ValidationError as exc:
        messages.error(request, exc.messages[0])
        return redirect(_cart_url(request))
    return render(request, "orders/thanks.html", {"orders": orders})


@org_required("shop.order", kind=KIND)
def order_list(request):
    qs = Order.objects.filter(customer=request.org).select_related("supplier")
    page = Paginator(qs, 30).get_page(request.GET.get("page"))
    return render(request, "orders/customer_list.html", {"page": page})


@org_required("shop.order", kind=KIND)
def order_detail(request, pk):
    order = get_object_or_404(Order.objects.select_related("supplier", "invoice"), pk=pk, customer=request.org)
    return render(request, "orders/customer_detail.html", {"order": order, "lines": order.lines.all()})


@require_POST
@org_required("shop.order", kind=KIND)
def reorder(request, pk):
    order = get_object_or_404(Order, pk=pk, customer=request.org)
    missing = services.reorder(order=order, customer=request.org, user=request.user)
    if missing:
        messages.warning(request, "Nicht mehr erhältlich: " + ", ".join(missing))
    messages.success(request, "Artikel in den Warenkorb gelegt.")
    return redirect("orders:cart")


@org_required("shop.order", kind=KIND)
def delivery_note(request, pk):
    from apps.billing.pdf import render_pdf

    order = get_object_or_404(Order, pk=pk, customer=request.org)
    pdf = render_pdf("documents/delivery_note.html", {"orders": [order]})
    return _pdf_response(pdf, f"Lieferschein-{order.number}.pdf")


def _pdf_response(pdf, filename):
    response = HttpResponse(pdf, content_type="application/pdf")
    response["Content-Disposition"] = f'inline; filename="{filename}"'
    return response
