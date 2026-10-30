from django.apps import AppConfig


class CustomersConfig(AppConfig):
    name = "apps.customers"
    label = "customers"

    def ready(self):
        from . import receivers  # noqa: F401
