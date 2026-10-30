from django import forms
from django.contrib import messages
from django.db.models import Count
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from apps.audit.services import log
from apps.orgs.decorators import org_required

from .models import Category, Label

KIND = "operator"
PERM = "platform.settings"


class CategoryForm(forms.ModelForm):
    class Meta:
        model = Category
        fields = ["name", "parent", "sort"]

    def __init__(self, *args, tenant, **kwargs):
        super().__init__(*args, **kwargs)
        qs = Category.objects.filter(tenant=tenant, parent__isnull=True)
        if self.instance.pk:
            qs = qs.exclude(pk=self.instance.pk)
        self.fields["parent"].queryset = qs
        self.fields["parent"].empty_label = "– keine (Hauptkategorie) –"


class LabelForm(forms.ModelForm):
    class Meta:
        model = Label
        fields = ["name"]


@org_required(PERM, kind=KIND)
def taxonomy(request):
    categories = (
        Category.objects.filter(tenant=request.tenant, parent__isnull=True)
        .annotate(product_count=Count("products"))
        .prefetch_related("children")
    )
    return render(
        request,
        "catalog/operator/taxonomy.html",
        {
            "categories": categories,
            "labels": Label.objects.filter(tenant=request.tenant).annotate(product_count=Count("products")),
            "category_form": CategoryForm(tenant=request.tenant),
            "label_form": LabelForm(),
        },
    )


@org_required(PERM, kind=KIND)
def category_edit(request, pk=None):
    instance = get_object_or_404(Category, pk=pk, tenant=request.tenant) if pk else Category(tenant=request.tenant)
    form = CategoryForm(request.POST or None, instance=instance, tenant=request.tenant)
    if request.method == "POST" and form.is_valid():
        if (
            Category.objects.filter(
                tenant=request.tenant, parent=form.cleaned_data["parent"], name__iexact=form.cleaned_data["name"]
            )
            .exclude(pk=instance.pk)
            .exists()
        ):
            form.add_error("name", "Diese Kategorie gibt es schon.")
        else:
            form.save()
            log(
                "settings.updated",
                request=request,
                organization=request.org,
                target=instance,
                changes={"kategorie": instance.name},
            )
            messages.success(request, f"Kategorie «{instance}» gespeichert.")
            return redirect("catalog_admin:taxonomy")
    return render(request, "catalog/operator/category_form.html", {"form": form, "category": instance})


@require_POST
@org_required(PERM, kind=KIND)
def category_delete(request, pk):
    category = get_object_or_404(Category, pk=pk, tenant=request.tenant)
    if category.products.exists() or category.children.exists():
        messages.error(request, "Nur leere Kategorien ohne Unterkategorien können gelöscht werden.")
    else:
        category.delete()
        messages.success(request, f"Kategorie «{category.name}» gelöscht.")
    return redirect("catalog_admin:taxonomy")


@require_POST
@org_required(PERM, kind=KIND)
def label_add(request):
    form = LabelForm(request.POST)
    if form.is_valid():
        name = form.cleaned_data["name"].strip()
        if Label.objects.filter(tenant=request.tenant, name__iexact=name).exists():
            messages.error(request, "Dieses Label gibt es schon.")
        else:
            Label.objects.create(tenant=request.tenant, name=name)
            messages.success(request, f"Label «{name}» hinzugefügt.")
    return redirect("catalog_admin:taxonomy")


@require_POST
@org_required(PERM, kind=KIND)
def label_delete(request, pk):
    label = get_object_or_404(Label, pk=pk, tenant=request.tenant)
    label.delete()
    messages.success(request, f"Label «{label.name}» entfernt.")
    return redirect("catalog_admin:taxonomy")
