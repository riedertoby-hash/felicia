from dataclasses import dataclass
from datetime import date, timedelta

from apps.billing.services import MONTHS_DE, month_bounds, quarter_bounds


@dataclass
class Period:
    key: str
    start: date
    end: date
    label: str

    @property
    def query(self):
        return f"zeitraum={self.key}&von={self.start:%Y-%m-%d}&bis={self.end:%Y-%m-%d}"


def resolve(params, today):
    key = params.get("zeitraum", "monat")
    if key == "monat":
        start, end = month_bounds(today)
        return Period(key, start, end, f"{MONTHS_DE[start.month - 1]} {start.year}")
    if key == "vormonat":
        start, end = month_bounds(today.replace(day=1) - timedelta(days=1))
        return Period(key, start, end, f"{MONTHS_DE[start.month - 1]} {start.year}")
    if key == "quartal":
        start, end = quarter_bounds(today)
        return Period(key, start, end, f"Q{(start.month - 1) // 3 + 1} {start.year}")
    if key == "jahr":
        return Period(key, date(today.year, 1, 1), date(today.year, 12, 31), str(today.year))
    if key == "vorjahr":
        return Period(key, date(today.year - 1, 1, 1), date(today.year - 1, 12, 31), str(today.year - 1))
    try:
        start = date.fromisoformat(params.get("von", ""))
        end = date.fromisoformat(params.get("bis", ""))
        if start > end or (end - start).days > 3 * 366:
            raise ValueError
    except ValueError:
        return resolve({"zeitraum": "monat"}, today)
    return Period("frei", start, end, f"{start:%d.%m.%Y} – {end:%d.%m.%Y}")


CHOICES = [
    ("monat", "Dieser Monat"),
    ("vormonat", "Letzter Monat"),
    ("quartal", "Dieses Quartal"),
    ("jahr", "Dieses Jahr"),
    ("vorjahr", "Letztes Jahr"),
    ("frei", "Frei wählen"),
]
