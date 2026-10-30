from django.contrib import messages
from django.core.exceptions import ValidationError
from django.core.paginator import Paginator
from django.db.models import Count, Max, Q, Sum
from django.http import HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_POST

from apps.audit.services import log
from apps.orders.models import Order
from apps.orgs.decorators import org_required
from apps.orgs.models import Organization

from . import services
from .forms import BillingSettingsForm, CustomerTermsForm, OperatorIssuerForm
from .models import BillingSettings, CustomerTerms, Invoice
from .pdf import invoice_pdf


def _pdf_response(invoice):
    response = HttpResponse(invoice_pdf(invoice), content_type="application/pdf")
    response["Content-Disposition"] = f'inline; filename="Rechnung-{invoice.number}.pdf"'
    return response


def _filter_status(qs, status):
    today = timezone.localdate()
    if status == "offen":
        return qs.filter(status="open")
    if status == "ueberfaellig":
        return qs.filter(status="open", due_date__lt=today)
    if status == "bezahlt":
        return qs.filter(status="paid")
    return qs


# --- Supplier ------------------------------------------------------------------------------------


@org_required("finance.view", kind="supplier")
def supplier_invoices(request):
    qs = Invoice.objects.filter(issuer=request.org, kind="sale").select_related("recipient")
    status = request.GET.get("status", "")
    page = Paginator(_filter_status(qs, status), 50).get_page(request.GET.get("page"))
    pending = (
        Order.objects.filter(supplier=request.org, status="delivered", invoice__isnull=True)
        .values("customer__pk", "customer__name")
        .annotate(n=Count("pk"), total=Sum("total"))
        .order_by("customer__name")
    )
    return render(
        request,
        "billing/supplier_invoices.html",
        {
            "page": page,
            "status": status,
            "pending": pending,
            "open_total": services.open_amount(qs),
            "overdue_total": services.open_amount(qs.filter(due_date__lt=timezone.localdate())),
            "can_manage": request.membership.has_perm("finance.manage"),
            "received": Invoice.objects.filter(recipient=request.org, kind="commission")[:12],
        },
    )


@require_POST
@org_required("finance.manage", kind="supplier")
def create_invoice(request, customer_id):
    customer = get_object_or_404(Organization, pk=customer_id, tenant=request.tenant, kind="customer")
    orders = services.invoiceable_orders(request.org, customer)
    try:
        invoice = services.create_sale_invoice(supplier=request.org, customer=customer, orders=orders, request=request)
        messages.success(request, f"Rechnung {invoice.number} erstellt und an {customer.name} gesendet.")
        return redirect("billing:supplier_invoice", pk=invoice.pk)
    except ValidationError as exc:
        messages.error(request, exc.messages[0])
        return redirect("billing:supplier_invoices")


def _own_issued(request, pk):
    return get_object_or_404(Invoice, pk=pk, issuer=request.org)


@org_required("finance.view", kind="supplier")
def supplier_invoice(request, pk):
    invoice = _own_issued(request, pk)
    return render(
        request,
        "billing/invoice_detail.html",
        {
            "invoice": invoice,
            "lines": invoice.lines.all(),
            "can_manage": request.membership.has_perm("finance.manage"),
            "side": "issuer",
        },
    )


@org_required("finance.view")
def invoice_pdf_view(request, pk):
    """Issuer or recipient may download; nobody else."""
    invoice = get_object_or_404(Invoice, Q(issuer=request.org) | Q(recipient=request.org), pk=pk)
    return _pdf_response(invoice)


@require_POST
@org_required("finance.manage")
def invoice_paid(request, pk):
    invoice = get_object_or_404(Invoice, pk=pk, issuer=request.org)
    try:
        services.set_paid(invoice=invoice, paid=request.POST.get("paid") == "1", request=request)
    except ValidationError as exc:
        messages.error(request, exc.messages[0])
    return redirect(request.POST.get("next") if str(request.POST.get("next", "")).startswith("/") else "/")


@require_POST
@org_required("finance.manage")
def invoice_cancel(request, pk):
    invoice = get_object_or_404(Invoice, pk=pk, issuer=request.org)
    try:
        services.cancel_invoice(invoice=invoice, request=request)
        messages.success(request, f"Rechnung {invoice.number} storniert. Die Bestellungen sind wieder verrechenbar.")
    except ValidationError as exc:
        messages.error(request, exc.messages[0])
    return redirect(request.POST.get("next") if str(request.POST.get("next", "")).startswith("/") else "/")


@org_required("finance.manage", kind="supplier")
def supplier_settings(request):
    settings = BillingSettings.for_org(request.org)
    form = BillingSettingsForm(request.POST or None, instance=settings, prefix="s")
    customers = Organization.objects.filter(orders_placed__supplier=request.org).distinct().order_by("name")
    terms_form = CustomerTermsForm(None, customers=customers, prefix="c")
    if request.method == "POST" and "save_settings" in request.POST and form.is_valid():
        form.save()
        log(
            "billing.settings",
            request=request,
            organization=request.org,
            changes={"modus": settings.invoice_mode, "frist": settings.payment_terms_days},
        )
        messages.success(request, "Rechnungseinstellungen gespeichert.")
        return redirect("billing:supplier_settings")
    if request.method == "POST" and "save_terms" in request.POST:
        terms_form = CustomerTermsForm(request.POST, customers=customers, prefix="c")
        if terms_form.is_valid():
            CustomerTerms.objects.update_or_create(
                supplier=request.org,
                customer=terms_form.cleaned_data["customer"],
                defaults={
                    "invoice_mode": terms_form.cleaned_data["invoice_mode"],
                    "payment_terms_days": terms_form.cleaned_data["payment_terms_days"],
                },
            )
            messages.success(request, "Abweichung gespeichert.")
            return redirect("billing:supplier_settings")
    return render(
        request,
        "billing/supplier_settings.html",
        {
            "form": form,
            "terms_form": terms_form,
            "terms": CustomerTerms.objects.filter(supplier=request.org).select_related("customer"),
            "has_iban": bool(request.org.supplier_profile.iban),
        },
    )


@require_POST
@org_required("finance.manage", kind="supplier")
def delete_terms(request, pk):
    CustomerTerms.objects.filter(pk=pk, supplier=request.org).delete()
    return redirect("billing:supplier_settings")


@org_required("finance.view", kind="supplier")
def supplier_customers(request):
    """Who ordered how much, when, and what is still open."""
    year = int(request.GET.get("jahr", timezone.localdate().year))
    orders = Order.objects.filter(supplier=request.org, created_at__year=year).exclude(status="cancelled")
    rows = (
        orders.values("customer__pk", "customer__name")
        .annotate(n=Count("pk"), revenue=Sum("goods_total"), last=Max("created_at"))
        .order_by("-revenue")
    )
    open_by_customer = dict(
        Invoice.objects.filter(issuer=request.org, status="open")
        .values("recipient")
        .annotate(s=Sum("total"))
        .values_list("recipient", "s")
    )
    for row in rows:
        row["open"] = open_by_customer.get(row["customer__pk"], 0)
    return render(
        request,
        "billing/supplier_customers.html",
        {"rows": rows, "year": year, "total": orders.aggregate(s=Sum("goods_total"))["s"] or 0},
    )


# --- Customer ------------------------------------------------------------------------------------


@org_required("finance.view", kind="customer")
def customer_invoices(request):
    qs = Invoice.objects.filter(recipient=request.org).select_related("issuer")
    status = request.GET.get("status", "")
    page = Paginator(_filter_status(qs, status), 50).get_page(request.GET.get("page"))
    return render(
        request,
        "billing/customer_invoices.html",
        {"page": page, "status": status, "open_total": services.open_amount(qs)},
    )


@org_required("finance.view", kind="customer")
def customer_invoice(request, pk):
    invoice = get_object_or_404(Invoice, pk=pk, recipient=request.org)
    return render(
        request, "billing/invoice_detail.html", {"invoice": invoice, "lines": invoice.lines.all(), "side": "recipient"}
    )


# --- Operator ------------------------------------------------------------------------------------


@org_required("platform.terms", kind="operator")
def operator_invoices(request):
    qs = Invoice.objects.filter(issuer=request.org, kind="commission").select_related("recipient")
    status = request.GET.get("status", "")
    page = Paginator(_filter_status(qs, status), 50).get_page(request.GET.get("page"))
    from apps.operator.models import MarketplaceSettings

    settings = MarketplaceSettings.for_tenant(request.tenant)
    period = services.last_closed_period(settings.commission_period, timezone.localdate())
    return render(
        request,
        "billing/operator_invoices.html",
        {
            "page": page,
            "status": status,
            "open_total": services.open_amount(qs),
            "period": period,
            "period_label": services.period_label(*period),
            "issuer_ready": bool(settings.iban and settings.city),
        },
    )


@require_POST
@org_required("platform.terms", kind="operator")
def operator_run(request):
    created = services.run_commission_invoicing(request.tenant)
    messages.success(
        request,
        f"{len(created)} Provisionsrechnung{'en' if len(created) != 1 else ''} erstellt."
        if created
        else "Keine neuen Provisionsrechnungen – alles bereits verrechnet.",
    )
    return redirect("billing:operator_invoices")


@org_required("platform.terms", kind="operator")
def operator_invoice(request, pk):
    invoice = _own_issued(request, pk)
    return render(
        request,
        "billing/invoice_detail.html",
        {"invoice": invoice, "lines": invoice.lines.all(), "can_manage": True, "side": "issuer"},
    )


@org_required("platform.settings", kind="operator")
def operator_issuer(request):
    from apps.operator.models import MarketplaceSettings

    obj = MarketplaceSettings.for_tenant(request.tenant)
    form = OperatorIssuerForm(request.POST or None, instance=obj, initial={"iban": ""})
    if request.method == "POST" and form.is_valid():
        if not form.cleaned_data.get("iban"):
            form.instance.iban = MarketplaceSettings.objects.get(pk=obj.pk).iban
        form.save()
        log("settings.updated", request=request, organization=request.org, changes={"rechnungsdaten": "geändert"})
        messages.success(request, "Rechnungsdaten gespeichert.")
        return redirect("billing:operator_invoices")
    return render(request, "billing/operator_issuer.html", {"form": form, "settings": obj})
