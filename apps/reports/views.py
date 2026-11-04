from django.core.exceptions import PermissionDenied
from django.shortcuts import render
from django.utils import timezone

from apps.orgs.decorators import org_required

from . import exports, periods, services


def _scope(request):
    """Which orders the current organization may evaluate."""
    org = request.org
    if org.kind == "supplier":
        if not request.membership.has_perm("finance.view"):
            raise PermissionDenied("Ihre Rolle erlaubt keine Auswertungen.")
        return {"supplier": org}
    if org.kind == "operator":
        if not request.membership.has_perm("platform.terms"):
            raise PermissionDenied("Ihre Rolle erlaubt keine Auswertungen.")
        return {"tenant": request.tenant}
    raise PermissionDenied("Auswertungen gibt es für Lieferanten und Betreiber.")


@org_required()
def dashboard(request):
    scope = _scope(request)
    today = timezone.localdate()
    period = periods.resolve(request.GET, today)
    orders = services.orders_in(period, **scope)
    year_period = periods.resolve({"zeitraum": "jahr"}, today) if period.key != "vorjahr" else period
    chart_start = min(period.start, year_period.start)
    chart_end = max(period.end, year_period.end)
    context = {
        "period": period,
        "choices": periods.CHOICES,
        "kpi": services.kpis(orders),
        "chart": services.monthly(
            services.orders_in(periods.Period("x", chart_start, chart_end, ""), **scope), chart_start, chart_end
        ),
        "products": services.top_products(orders),
        "customers": services.top_customers(orders),
        "is_operator": request.org.kind == "operator",
    }
    if request.org.kind == "operator":
        context["suppliers"] = services.by_supplier(orders)
        context["open"] = services.open_invoices(issuer=request.org)
    else:
        context["open"] = services.open_invoices(issuer=request.org)
    return render(request, "reports/dashboard.html", context)


@org_required()
def export(request, kind):
    scope = _scope(request)
    period = periods.resolve(request.GET, timezone.localdate())
    if kind == "umsatz":
        return exports.sales_lines(period, **scope)
    if kind == "rechnungen":
        return exports.invoice_list(request.org, period)
    if kind == "journal":
        return exports.journal(request.org, period)
    raise PermissionDenied("Unbekannter Export.")
