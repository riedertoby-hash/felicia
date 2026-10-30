from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.db.models import Count, Min, Prefetch, Q
from django.shortcuts import get_object_or_404, render

from apps.catalog.models import Category, Label, Product, Temperature, Variant
from apps.orgs.models import Organization

from .search import search_products

PAGE_SIZE = 24
SORTS = {"": "Relevanz", "name": "Name", "price": "Preis aufsteigend", "new": "Neueste"}


def _visible(request):
    return (
        Product.objects.visible(request.tenant)
        .select_related("supplier", "category")
        .prefetch_related(Prefetch("variants", queryset=Variant.objects.filter(is_active=True)), "labels")
    )


def _filtered(request, qs):
    params = request.GET
    q = params.get("q", "").strip()
    category_id = params.get("kategorie", "")
    if category_id.isdigit():
        qs = qs.filter(Q(category_id=category_id) | Q(category__parent_id=category_id))
    supplier_id = params.get("lieferant", "")
    if supplier_id.isdigit():
        qs = qs.filter(supplier_id=supplier_id)
    label_ids = [x for x in params.getlist("label") if x.isdigit()]
    for label_id in label_ids:
        qs = qs.filter(labels__id=label_id)
    temperature = params.get("temperatur", "")
    if temperature in Temperature.values:
        qs = qs.filter(temperature=temperature)
    qs = search_products(qs, q) if q else qs
    sort = params.get("sort", "")
    if sort == "name" or (not q and sort == ""):
        qs = qs.order_by("name")
    elif sort == "price":
        qs = qs.annotate(min_price=Min("variants__customer_price")).order_by("min_price", "name")
    elif sort == "new":
        qs = qs.order_by("-created_at")
    return qs, {
        "q": q,
        "kategorie": category_id,
        "lieferant": supplier_id,
        "labels": label_ids,
        "temperatur": temperature,
        "sort": sort,
    }


@login_required
def index(request):
    qs, active = _filtered(request, _visible(request))
    page = Paginator(qs, PAGE_SIZE).get_page(request.GET.get("page"))
    context = {"page": page, "active": active, "sorts": SORTS}
    if request.headers.get("HX-Request") and request.headers.get("HX-Target") == "results":
        return render(request, "shop/partials/results.html", context)
    categories = Category.objects.filter(tenant=request.tenant, parent__isnull=True).prefetch_related("children")
    context.update(
        {
            "categories": categories,
            "labels": Label.objects.filter(tenant=request.tenant),
            "suppliers": Organization.objects.filter(tenant=request.tenant, kind="supplier", status="active").order_by(
                "name"
            ),
            "temperatures": Temperature.choices,
        }
    )
    return render(request, "shop/index.html", context)


@login_required
def product_detail(request, pk):
    product = get_object_or_404(_visible(request), pk=pk)
    more = _visible(request).filter(supplier=product.supplier).exclude(pk=product.pk)[:4]
    return render(request, "shop/product.html", {"product": product, "more": more})


def _active_suppliers(request):
    return Organization.objects.filter(tenant=request.tenant, kind="supplier", status="active").select_related(
        "supplier_profile"
    )


@login_required
def suppliers(request):
    qs = (
        _active_suppliers(request)
        .annotate(product_count=Count("products", filter=Q(products__is_active=True)))
        .order_by("name")
    )
    return render(request, "shop/suppliers.html", {"suppliers": qs})


@login_required
def supplier_detail(request, pk):
    supplier = get_object_or_404(_active_suppliers(request), pk=pk)
    qs, active = _filtered(request, _visible(request).filter(supplier=supplier))
    page = Paginator(qs, PAGE_SIZE).get_page(request.GET.get("page"))
    context = {
        "supplier": supplier,
        "profile": supplier.supplier_profile,
        "page": page,
        "active": active,
        "sorts": SORTS,
    }
    if request.headers.get("HX-Request") and request.headers.get("HX-Target") == "results":
        return render(request, "shop/partials/results.html", context)
    return render(request, "shop/supplier.html", context)
