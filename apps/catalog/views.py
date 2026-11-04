from django.contrib import messages
from django.core.paginator import Paginator
from django.db import transaction
from django.db.models import Count, Min, Q
from django.http import HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from apps.audit.services import log
from apps.orgs.decorators import org_required

from . import csv_import, pricing
from .forms import CsvUploadForm, ProductForm, VariantFormSet
from .models import Product, Variant

KIND = "supplier"
SESSION_CSV = "catalog_csv_import"


def _products(request):
    return Product.objects.filter(supplier=request.org)


@org_required("catalog.view", kind=KIND)
def product_list(request):
    qs = (
        _products(request)
        .select_related("category")
        .annotate(variant_count=Count("variants"), min_price=Min("variants__customer_price"))
    )
    q = request.GET.get("q", "").strip()
    if q:
        qs = qs.filter(Q(name__icontains=q) | Q(variants__sku__icontains=q)).distinct()
    state = request.GET.get("status", "")
    if state == "active":
        qs = qs.filter(is_active=True)
    elif state == "inactive":
        qs = qs.filter(is_active=False)
    page = Paginator(qs.order_by("name"), 50).get_page(request.GET.get("page"))
    return render(
        request,
        "catalog/product_list.html",
        {
            "page": page,
            "q": q,
            "status": state,
            "commission": pricing.commission_for(request.org),
            "can_edit": request.membership.has_perm("catalog.edit"),
        },
    )


def _price_snapshot(product):
    if not product.pk:
        return {}
    return {v.pk: (v.name, str(v.customer_price)) for v in product.variants.all()}


@org_required("catalog.view", kind=KIND)
def product_edit(request, pk=None):
    can_edit = request.membership.has_perm("catalog.edit")
    can_prices = request.membership.has_perm("prices.edit")
    if pk:
        product = get_object_or_404(_products(request), pk=pk)
    else:
        if not can_edit:
            messages.error(request, "Ihre Rolle erlaubt keine neuen Artikel.")
            return redirect("catalog:list")
        product = Product(tenant=request.tenant, supplier=request.org)
    commission = pricing.commission_for(request.org)
    before = _price_snapshot(product)
    form = ProductForm(request.POST or None, request.FILES or None, instance=product, tenant=request.tenant)
    formset = VariantFormSet(
        request.POST or None,
        instance=product,
        prefix="v",
        form_kwargs={"commission": commission, "can_edit_prices": can_prices},
    )
    if request.method == "POST":
        if not can_edit:
            messages.error(request, "Ihre Rolle erlaubt keine Änderungen an Artikeln.")
            return redirect("catalog:edit", pk=product.pk)
        if form.is_valid() and formset.is_valid():
            if not can_prices and any(f.has_changed() and not f.instance.pk for f in formset.forms):
                messages.error(request, "Neue Varianten mit Preis darf nur erfassen, wer Preise bearbeiten darf.")
            else:
                _save(request, form, formset, product, before, created=pk is None)
                messages.success(request, f"«{product.name}» gespeichert.")
                if "save_new" in request.POST:
                    return redirect("catalog:new")
                return redirect("catalog:list")
    if not can_edit:
        for f in [form, *formset.forms]:
            for field in f.fields.values():
                field.disabled = True
    return render(
        request,
        "catalog/product_form.html",
        {
            "form": form,
            "formset": formset,
            "product": product,
            "commission": commission,
            "can_edit": can_edit,
            "can_prices": can_prices,
        },
    )


@transaction.atomic
def _save(request, form, formset, product, before, created):
    form.save()
    formset.save()
    product.update_search_vector()
    after = _price_snapshot(product)
    changes = {}
    for vid, (name, price) in after.items():
        old = before.get(vid)
        if old is None:
            changes[name] = [None, price]
        elif old[1] != price:
            changes[name] = [old[1], price]
    for vid, (name, price) in before.items():
        if vid not in after:
            changes[name] = [price, None]
    log(
        "catalog.created" if created else "catalog.updated",
        request=request,
        organization=request.org,
        target=product,
        changes=changes,
    )


@require_POST
@org_required("catalog.edit", kind=KIND)
def product_toggle(request, pk):
    product = get_object_or_404(_products(request), pk=pk)
    product.is_active = not product.is_active
    product.save(update_fields=["is_active", "updated_at"])
    log(
        "catalog.updated",
        request=request,
        organization=request.org,
        target=product,
        changes={"is_active": [not product.is_active, product.is_active]},
    )
    if request.headers.get("HX-Request"):
        return render(request, "catalog/partials/toggle.html", {"p": product, "can_edit": True})
    return redirect("catalog:list")


@require_POST
@org_required("catalog.edit", kind=KIND)
def product_delete(request, pk):
    product = get_object_or_404(_products(request), pk=pk)
    log("catalog.deleted", request=request, organization=request.org, target=product)
    product.delete()
    messages.success(request, f"«{product.name}» gelöscht.")
    return redirect("catalog:list")


@org_required("catalog.edit", kind=KIND)
def csv_upload(request):
    can_prices = request.membership.has_perm("prices.edit")
    if not can_prices:
        messages.error(request, "Der Import setzt Preise und braucht deshalb das Recht «Preise bearbeiten».")
        return redirect("catalog:list")
    form = CsvUploadForm(request.POST or None, request.FILES or None)
    if request.method == "POST" and form.is_valid():
        text = form.cleaned_data["file"]
        rows, error = csv_import.parse(text, supplier=request.org)
        if error:
            form.add_error("file", error)
        else:
            request.session[SESSION_CSV] = text
            return render(
                request,
                "catalog/csv_preview.html",
                {
                    "rows": rows,
                    "has_errors": any(r.errors for r in rows),
                    "error_count": sum(1 for r in rows if r.errors),
                },
            )
    return render(request, "catalog/csv_upload.html", {"form": form, "columns": csv_import.COLUMNS})


@require_POST
@org_required("catalog.edit", kind=KIND)
def csv_confirm(request):
    if not request.membership.has_perm("prices.edit"):
        return redirect("catalog:list")
    text = request.session.pop(SESSION_CSV, None)
    if not text:
        messages.error(request, "Bitte die Datei nochmals hochladen.")
        return redirect("catalog:csv")
    rows, error = csv_import.parse(text, supplier=request.org)
    if error or any(r.errors for r in rows):
        messages.error(request, "Die Datei enthält Fehler. Bitte korrigieren und erneut hochladen.")
        return redirect("catalog:csv")
    created, updated = csv_import.apply(rows, supplier=request.org)
    log(
        "catalog.imported", request=request, organization=request.org, changes={"neu": created, "aktualisiert": updated}
    )
    messages.success(request, f"Import abgeschlossen: {created} neu, {updated} aktualisiert.")
    return redirect("catalog:list")


@org_required("catalog.view", kind=KIND)
def csv_template(request):
    response = HttpResponse(csv_import.TEMPLATE.encode("utf-8-sig"), content_type="text/csv; charset=utf-8")
    response["Content-Disposition"] = 'attachment; filename="artikel-vorlage.csv"'
    return response


@org_required("catalog.view", kind=KIND)
def csv_export(request):
    import csv
    import io

    buf = io.StringIO()
    writer = csv.writer(buf, delimiter=";")
    writer.writerow(csv_import.COLUMNS)
    temps = {"ambient": "ungekühlt", "chilled": "gekühlt", "frozen": "tiefgekühlt"}
    variants = (
        Variant.objects.filter(product__supplier=request.org)
        .select_related("product__category")
        .order_by("product__name", "sort")
    )
    for v in variants:
        p = v.product
        writer.writerow(
            [
                p.name,
                v.name,
                v.unit,
                v.customer_price,
                v.vat_rate,
                v.min_qty,
                p.category.name if p.category else "",
                temps[p.temperature],
                p.shelf_life_days or "",
                p.lead_time_days,
                p.origin,
                v.sku,
                p.description,
            ]
        )
    response = HttpResponse(buf.getvalue().encode("utf-8-sig"), content_type="text/csv; charset=utf-8")
    response["Content-Disposition"] = 'attachment; filename="artikel.csv"'
    return response
