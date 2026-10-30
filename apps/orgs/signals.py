from django.dispatch import Signal

# Sent after a new organization exists. kwargs: organization, owner, options (dict)
organization_created = Signal()
