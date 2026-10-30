from django.apps import AppConfig


class SuppliersConfig(AppConfig):
    name = "apps.suppliers"
    label = "suppliers"

    def ready(self):
        from . import receivers  # noqa: F401
