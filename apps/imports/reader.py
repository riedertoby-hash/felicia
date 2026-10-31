"""Read CSV or Excel files from other systems and map their column names to ours."""

import csv
import io
import re

MAX_ROWS = 5000
MAX_BYTES = 5 * 1024 * 1024


class ReadError(Exception):
    pass


def norm(text):
    text = str(text or "").strip().lower()
    for a, b in (("ä", "ae"), ("ö", "oe"), ("ü", "ue"), ("ß", "ss"), ("é", "e"), ("è", "e"), ("à", "a")):
        text = text.replace(a, b)
    return re.sub(r"[^a-z0-9]", "", text)


def read_table(uploaded):
    """Return a list of {original header: cell text} dicts."""
    if uploaded.size > MAX_BYTES:
        raise ReadError("Datei ist grösser als 5 MB.")
    name = (uploaded.name or "").lower()
    raw = uploaded.read()
    if name.endswith((".xlsx", ".xlsm")):
        rows = _read_excel(raw)
    elif name.endswith(".xls"):
        raise ReadError("Altes Excel-Format (.xls): bitte als .xlsx oder CSV speichern.")
    else:
        rows = _read_csv(raw)
    rows = [r for r in rows if any((v or "").strip() for v in r.values())]
    if not rows:
        raise ReadError("Die Datei enthält keine Datenzeilen.")
    if len(rows) > MAX_ROWS:
        raise ReadError(f"Maximal {MAX_ROWS} Zeilen pro Import.")
    return rows


def _read_csv(raw):
    for encoding in ("utf-8-sig", "cp1252"):
        try:
            text = raw.decode(encoding)
            break
        except UnicodeDecodeError:
            continue
    else:
        raise ReadError("Zeichensatz der Datei nicht erkannt.")
    sample = text[:4096]
    delimiter = max([";", ",", "\t"], key=sample.count)
    reader = csv.DictReader(io.StringIO(text), delimiter=delimiter)
    if not reader.fieldnames:
        raise ReadError("Keine Spaltenüberschriften gefunden.")
    return [{k: (v or "") for k, v in row.items() if k} for row in reader]


def _read_excel(raw):
    from openpyxl import load_workbook

    try:
        wb = load_workbook(io.BytesIO(raw), read_only=True, data_only=True)
    except Exception as exc:  # noqa: BLE001 - any parse problem means: not a usable workbook
        raise ReadError("Excel-Datei konnte nicht gelesen werden.") from exc
    sheet = wb.worksheets[0]
    rows_iter = sheet.iter_rows(values_only=True)
    try:
        headers = [str(h).strip() if h is not None else "" for h in next(rows_iter)]
    except StopIteration as exc:
        raise ReadError("Das erste Tabellenblatt ist leer.") from exc
    result = []
    for values in rows_iter:
        row = {}
        for header, value in zip(headers, values, strict=False):
            if header:
                row[header] = _cell_text(value)
        result.append(row)
    return result


def _cell_text(value):
    if value is None:
        return ""
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return str(value).strip()


def map_columns(rows, aliases):
    """aliases: {field: [possible header names]}. Returns (mapped rows, {field: original header}, unknown)."""
    headers = list(rows[0].keys())
    lookup = {norm(a): field for field, names in aliases.items() for a in [field, *names]}
    mapping, unknown = {}, []
    for header in headers:
        field = lookup.get(norm(header))
        if field and field not in mapping:
            mapping[field] = header
        else:
            unknown.append(header)
    mapped = [{field: (row.get(header) or "").strip() for field, header in mapping.items()} for row in rows]
    return mapped, mapping, unknown
