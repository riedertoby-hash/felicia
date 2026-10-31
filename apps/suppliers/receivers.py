from django.dispatch import receiver

from apps.orgs.signals import organization_created

from .models import SupplierProfile


@receiver(organization_created)
def create_profile(sender, organization, owner, options, **kwargs):
    if organization.kind == "supplier":
        from apps.operator.models import SupplierTerms

        SupplierProfile.objects.create(
            organization=organization, contact_email=owner.email if owner else "", legal_name=organization.name
        )
        SupplierTerms.objects.get_or_create(organization=organization)
