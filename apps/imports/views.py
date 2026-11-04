from django import forms
from django.contrib import messages
from django.core.exceptions import ValidationError
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_POST

from apps.orgs.decorators import org_required
from apps.orgs.models import Organization

from . import services
from .models import ImportBatch
from .reader import ReadError, read_table

PERM = "platform.suppliers.manage"
SESSION_KEY = "operator_import"


class UploadForm(forms.Form):
    kind = forms.ChoiceField(
        label="Was importieren Sie?", choices=ImportBatch.Kind.choices, widget=forms.RadioSelect, initial="suppliers"
    )
    supplier = forms.ModelChoiceField(
        label="Artikel gehören zu",
        queryset=Organization.objects.none(),
        required=False,
        empty_label="– Spalte «Lieferant» in der Datei –",
        widget=forms.Select(attrs={"data-show-if": "kind=products"}),
    )
    file = forms.FileField(label="Datei (CSV oder Excel .xlsx)")

    def __init__(self, *args, tenant, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["supplier"].queryset = Organization.objects.filter(tenant=tenant, kind="supplier").order_by("name")


def _parse(kind, rows, tenant, supplier):
    if kind == "suppliers":
        result, mapping, unknown = services.parse_suppliers(rows, tenant)
        return {"rows": result, "mapping": mapping, "unknown": unknown}
    if kind == "customers":
        result, mapping, unknown = services.parse_customers(rows, tenant)
        return {"rows": result, "mapping": mapping, "unknown": unknown}
    parsed, orphans, mapping, unknown = services.parse_products(rows, tenant, supplier)
    return {"groups": parsed, "orphans": orphans, "mapping": mapping, "unknown": unknown}


@org_required(PERM, kind="operator")
def upload(request):
    form = UploadForm(request.POST or None, request.FILES or None, tenant=request.tenant)
    if request.method == "POST" and form.is_valid():
        try:
            rows = read_table(form.cleaned_data["file"])
        except ReadError as exc:
            form.add_error("file", str(exc))
        else:
            kind = form.cleaned_data["kind"]
            supplier = form.cleaned_data.get("supplier")
            request.session[SESSION_KEY] = {
                "kind": kind,
                "rows": rows,
                "supplier": supplier.pk if supplier else None,
                "filename": form.cleaned_data["file"].name[:200],
            }
            result = _parse(kind, rows, request.tenant, supplier)
            if kind == "products":
                all_rows = [r for rs in result["groups"].values() for r in rs]
                ok = sum(1 for r in all_rows if not r.errors)
                bad = len(all_rows) - ok + len(result["orphans"])
            else:
                ok = sum(1 for r in result["rows"] if r.ok and r.action != "existiert")
                bad = len(result["rows"]) - ok
            return render(
                request,
                "imports/preview.html",
                {
                    **result,
                    "kind": kind,
                    "ok_count": ok,
                    "skip_count": bad,
                    "kind_label": dict(ImportBatch.Kind.choices)[kind],
                },
            )
    return render(
        request,
        "imports/upload.html",
        {
            "form": form,
            "batches": ImportBatch.objects.filter(tenant=request.tenant)[:20],
            "aliases": {
                "Lieferanten": services.SUPPLIER_ALIASES,
                "Kunden": services.CUSTOMER_ALIASES,
                "Artikel": services.PRODUCT_ALIASES,
            },
        },
    )


@require_POST
@org_required(PERM, kind="operator")
def confirm(request):
    data = request.session.pop(SESSION_KEY, None)
    if not data:
        messages.error(request, "Bitte die Datei nochmals hochladen.")
        return redirect("imports:upload")
    supplier = (
        Organization.objects.filter(pk=data["supplier"], tenant=request.tenant, kind="supplier").first()
        if data["supplier"]
        else None
    )
    result = _parse(data["kind"], data["rows"], request.tenant, supplier)
    if data["kind"] == "suppliers":
        batch = services.apply_suppliers(result["rows"], request=request, filename=data["filename"])
    elif data["kind"] == "customers":
        batch = services.apply_customers(result["rows"], request=request, filename=data["filename"])
    else:
        batch = services.apply_products(result["groups"], request=request, filename=data["filename"])
        batch.skipped_count += len(result["orphans"])
        batch.save(update_fields=["skipped_count"])
    if request.POST.get("invite") and data["kind"] != "products":
        sent, _ = services.invite_batch(batch, request)
        batch.invitations_sent_at = timezone.now()
        batch.save(update_fields=["invitations_sent_at"])
        messages.success(request, f"{sent} Einladung{'en' if sent != 1 else ''} verschickt.")
    return redirect("imports:batch", pk=batch.pk)


@org_required(PERM, kind="operator")
def batch_detail(request, pk):
    batch = get_object_or_404(ImportBatch, pk=pk, tenant=request.tenant)
    orgs = batch.organizations.all().prefetch_related("memberships").order_by("name")
    return render(request, "imports/batch.html", {"batch": batch, "orgs": orgs})


@require_POST
@org_required(PERM, kind="operator")
def batch_invite(request, pk):
    batch = get_object_or_404(ImportBatch, pk=pk, tenant=request.tenant)
    sent, skipped = services.invite_batch(batch, request)
    batch.invitations_sent_at = timezone.now()
    batch.save(update_fields=["invitations_sent_at"])
    messages.success(
        request,
        f"{sent} Einladung{'en' if sent != 1 else ''} verschickt"
        + (f", {skipped} übersprungen (ohne E-Mail, schon Mitglieder oder bereits eingeladen)." if skipped else "."),
    )
    return redirect("imports:batch", pk=pk)


@require_POST
@org_required(PERM, kind="operator")
def invite_org(request, pk):
    org = get_object_or_404(Organization, pk=pk, tenant=request.tenant, kind__in=["supplier", "customer"])
    email = request.POST.get("email", "").strip()
    try:
        forms.EmailField().clean(email)
        services.invite_owner(org=org, email=email, request=request)
        messages.success(request, f"Einladung an {email} verschickt.")
    except ValidationError as exc:
        messages.error(request, exc.messages[0])
    next_url = request.POST.get("next", "")
    return redirect(next_url if next_url.startswith("/betreiber/") else "operator:dashboard")
