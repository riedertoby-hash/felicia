from django.db import models


class Tenant(models.Model):
    """A marketplace operator instance. Today there is one; the schema is ready for more."""

    slug = models.SlugField(unique=True)
    name = models.CharField("Name", max_length=120)
    domain = models.CharField("Domain", max_length=253, blank=True, help_text="z.B. shop.feldzutisch.ch")
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "Mandant"
        verbose_name_plural = "Mandanten"

    def __str__(self):
        return self.name


class TimeStampedModel(models.Model):
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        abstract = True


class TenantModel(TimeStampedModel):
    """Base for all business data: every row belongs to exactly one tenant."""

    tenant = models.ForeignKey(Tenant, on_delete=models.PROTECT, related_name="+")

    class Meta:
        abstract = True


class Sequence(models.Model):
    """Gap-free counters for order and invoice numbers (row-locked while incrementing)."""

    key = models.CharField(max_length=80, unique=True)
    value = models.PositiveBigIntegerField(default=0)

    def __str__(self):
        return f"{self.key}={self.value}"

    @classmethod
    def next(cls, key):
        from django.db import transaction

        with transaction.atomic():
            obj, _ = cls.objects.select_for_update().get_or_create(key=key)
            obj.value += 1
            obj.save(update_fields=["value"])
            return obj.value
