from django.dispatch import receiver

from apps.orgs.signals import organization_created

from .models import CustomerProfile


@receiver(organization_created)
def create_profile(sender, organization, owner, options, **kwargs):
    if organization.kind == "customer":
        CustomerProfile.objects.create(
            organization=organization,
            customer_type=options.get("customer_type", "business"),
            billing_email=owner.email if owner else "",
            billing_name=organization.name,
        )
