from django.contrib import messages
from django.core.paginator import Paginator
from django.db.models import Count, Q
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_POST

from apps.audit.models import ACTION_LABELS, AuditEvent
from apps.audit.services import diff, log, snapshot
from apps.orgs.decorators import org_required
from apps.orgs.models import Membership, Organization

from .forms import SettingsForm, TermsForm
from .models import MarketplaceSettings, SupplierTerms

KIND = Organization.Kind.OPERATOR


def _tenant_orgs(request, kind):
    return Organization.objects.filter(tenant=request.tenant, kind=kind)


@org_required(kind=KIND)
def dashboard(request):
    suppliers = _tenant_orgs(request, Organization.Kind.SUPPLIER)
    counts = suppliers.aggregate(
        pending=Count("pk", filter=Q(status="pending")),
        active=Count("pk", filter=Q(status="active")),
        blocked=Count("pk", filter=Q(status="blocked")),
    )
    return render(
        request,
        "operator/dashboard.html",
        {
            "counts": counts,
            "customer_count": _tenant_orgs(request, Organization.Kind.CUSTOMER).count(),
            "pending": suppliers.filter(status="pending").order_by("created_at")[:10],
            "settings": MarketplaceSettings.for_tenant(request.tenant),
        },
    )


@org_required("platform.suppliers.view", kind=KIND)
def suppliers(request):
    qs = _tenant_orgs(request, Organization.Kind.SUPPLIER).select_related("supplier_profile", "terms")
    status = request.GET.get("status", "")
    if status in Organization.Status.values:
        qs = qs.filter(status=status)
    q = request.GET.get("q", "").strip()
    if q:
        qs = qs.filter(Q(name__icontains=q) | Q(supplier_profile__city__icontains=q))
    page = Paginator(qs.order_by("name"), 50).get_page(request.GET.get("page"))
    return render(
        request,
        "operator/suppliers.html",
        {"page": page, "status": status, "q": q, "statuses": Organization.Status.choices},
    )


@org_required("platform.suppliers.view", kind=KIND)
def supplier_detail(request, pk):
    org = get_object_or_404(_tenant_orgs(request, Organization.Kind.SUPPLIER), pk=pk)
    terms, _ = SupplierTerms.objects.get_or_create(organization=org)
    can_edit_terms = request.membership.has_perm("platform.terms")
    form = TermsForm(request.POST or None, instance=terms)
    if request.method == "POST":
        if not can_edit_terms:
            messages.error(request, "Ihre Rolle erlaubt diese Aktion nicht.")
            return redirect("operator:supplier", pk=pk)
        fields = ["commission_percent", "base_fee_monthly"]
        before = snapshot(terms, fields)
        if form.is_valid():
            form.save()
            changes = diff(before, snapshot(terms, fields), fields)
            if changes:
                log("org.terms_updated", request=request, organization=org, target=org, changes=changes)
            messages.success(request, "Konditionen gespeichert.")
            return redirect("operator:supplier", pk=pk)
    return render(
        request,
        "operator/supplier_detail.html",
        {
            "org": org,
            "profile": getattr(org, "supplier_profile", None),
            "terms": terms,
            "form": form,
            "can_edit_terms": can_edit_terms,
            "members": Membership.objects.filter(organization=org).select_related("user", "role"),
            "events": AuditEvent.objects.filter(organization=org)[:20],
        },
    )


STATUS_ACTIONS = {
    "approve": (Organization.Status.ACTIVE, "org.approved", "freigeschaltet"),
    "block": (Organization.Status.BLOCKED, "org.blocked", "gesperrt"),
    "unblock": (Organization.Status.ACTIVE, "org.unblocked", "entsperrt"),
}


@require_POST
@org_required("platform.suppliers.manage", kind=KIND)
def set_status(request, pk):
    org = get_object_or_404(Organization.objects.filter(tenant=request.tenant).exclude(kind=KIND), pk=pk)
    action = request.POST.get("action")
    if action not in STATUS_ACTIONS:
        messages.error(request, "Unbekannte Aktion.")
        return redirect("operator:dashboard")
    status, event, verb = STATUS_ACTIONS[action]
    old = org.status
    org.status = status
    org.status_changed_at = timezone.now()
    org.save(update_fields=["status", "status_changed_at", "updated_at"])
    log(event, request=request, organization=org, target=org, changes={"status": [old, status]})
    messages.success(request, f"{org.name} {verb}.")
    if request.headers.get("HX-Request"):
        return render(request, "operator/partials/supplier_row.html", {"org": org})
    return redirect(request.POST.get("next") or "operator:suppliers")


@org_required("platform.customers.view", kind=KIND)
def customers(request):
    qs = _tenant_orgs(request, Organization.Kind.CUSTOMER).select_related("customer_profile")
    q = request.GET.get("q", "").strip()
    if q:
        qs = qs.filter(Q(name__icontains=q) | Q(memberships__user__email__icontains=q)).distinct()
    page = Paginator(qs.order_by("name"), 50).get_page(request.GET.get("page"))
    return render(request, "operator/customers.html", {"page": page, "q": q})


@org_required("platform.settings", kind=KIND)
def settings_view(request):
    obj = MarketplaceSettings.for_tenant(request.tenant)
    fields = SettingsForm.Meta.fields
    before = snapshot(obj, fields)
    form = SettingsForm(request.POST or None, instance=obj)
    if request.method == "POST" and form.is_valid():
        form.save()
        changes = diff(before, snapshot(obj, fields), fields)
        if changes:
            log("settings.updated", request=request, organization=request.org, changes=changes)
        messages.success(request, "Einstellungen gespeichert.")
        return redirect("operator:settings")
    return render(request, "operator/settings.html", {"form": form})


@org_required("platform.audit", kind=KIND)
def audit(request):
    qs = AuditEvent.objects.filter(tenant=request.tenant).select_related("organization")
    action = request.GET.get("action", "")
    if action:
        qs = qs.filter(action=action)
    q = request.GET.get("q", "").strip()
    if q:
        qs = qs.filter(Q(actor_label__icontains=q) | Q(organization__name__icontains=q) | Q(target_label__icontains=q))
    page = Paginator(qs, 100).get_page(request.GET.get("page"))
    return render(
        request,
        "operator/audit.html",
        {"page": page, "action": action, "q": q, "actions": sorted(ACTION_LABELS.items(), key=lambda x: x[1])},
    )
