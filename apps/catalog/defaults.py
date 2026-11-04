from .models import Category, Label

CATEGORIES = [
    ("Gemüse", ["Salate", "Kartoffeln"]),
    ("Obst", ["Beeren"]),
    ("Milchprodukte", ["Käse", "Milch & Joghurt", "Butter & Rahm"]),
    ("Eier", []),
    ("Fleisch & Wurst", []),
    ("Fisch", []),
    ("Brot & Backwaren", []),
    ("Getreide & Mehl", []),
    ("Öl & Essig", []),
    ("Honig & Aufstriche", []),
    ("Konserven & Eingemachtes", []),
    ("Getränke", ["Säfte", "Wein", "Bier"]),
    ("Kräuter & Gewürze", []),
    ("Blumen & Pflanzen", []),
]
LABELS = [
    "Bio Suisse",
    "Demeter",
    "IP-Suisse",
    "Regio Garantie",
    "Schweizer Berg",
    "Schweizer Alp",
    "Vegan",
    "Glutenfrei",
    "Laktosefrei",
]


def seed_catalog_defaults(tenant):
    """Create the default shop structure once; existing entries are left alone."""
    for sort, (name, children) in enumerate(CATEGORIES, start=1):
        parent, _ = Category.objects.get_or_create(tenant=tenant, parent=None, name=name, defaults={"sort": sort * 10})
        for child_sort, child in enumerate(children, start=1):
            Category.objects.get_or_create(tenant=tenant, parent=parent, name=child, defaults={"sort": child_sort})
    for name in LABELS:
        Label.objects.get_or_create(tenant=tenant, name=name)
