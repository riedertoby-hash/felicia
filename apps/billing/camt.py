"""Read ISO 20022 bank files (camt.054 credit notifications, also camt.053 statements) and match
incoming payments to open invoices by their QR/SCOR reference."""

import re
from dataclasses import dataclass
from datetime import date
from decimal import Decimal, InvalidOperation

from defusedxml import ElementTree
from django.db import transaction
from django.utils import timezone

from apps.audit.services import log

from .models import Invoice, Payment

MAX_BYTES = 10 * 1024 * 1024


class CamtError(Exception):
    pass


@dataclass
class Entry:
    amount: Decimal
    currency: str
    reference: str
    booked_on: date
    debtor: str
    bank_id: str


def _local(tag):
    return tag.rsplit("}", 1)[-1]


def _find(node, path):
    """Namespace-agnostic search: path like 'Amt' or 'RmtInf/Strd/CdtrRefInf/Ref'."""
    current = [node]
    for part in path.split("/"):
        current = [child for n in current for child in n.iter() if _local(child.tag) == part and child is not n]
        if not current:
            return None
    return current[0]


def _text(node, path, default=""):
    found = _find(node, path)
    return (found.text or "").strip() if found is not None and found.text else default


def normalize_ref(ref):
    return re.sub(r"\s+", "", ref or "").upper()


def parse(raw):
    if len(raw) > MAX_BYTES:
        raise CamtError("Datei ist grösser als 10 MB.")
    try:
        root = ElementTree.fromstring(raw)
    except Exception as exc:  # noqa: BLE001 - any XML problem means: not a bank file
        raise CamtError("Keine gültige camt-Datei (XML).") from exc
    if not any(_local(el.tag) in ("BkToCstmrDbtCdtNtfctn", "BkToCstmrStmt") for el in root.iter()):
        raise CamtError("Keine camt.054/053-Datei.")
    entries = []
    for ntry in (el for el in root.iter() if _local(el.tag) == "Ntry"):
        if _text(ntry, "CdtDbtInd") != "CRDT":
            continue
        booked = _text(ntry, "BookgDt/Dt") or _text(ntry, "ValDt/Dt") or str(timezone.localdate())
        ntry_ref = _text(ntry, "AcctSvcrRef") or _text(ntry, "NtryRef")
        details = [el for el in ntry.iter() if _local(el.tag) == "TxDtls"] or [ntry]
        for i, tx in enumerate(details):
            amount_node = _find(tx, "Amt") if tx is not ntry else _find(ntry, "Amt")
            try:
                amount = Decimal((amount_node.text or "").strip())
            except (AttributeError, InvalidOperation):
                continue
            currency = amount_node.get("Ccy", "CHF")
            reference = normalize_ref(_text(tx, "CdtrRefInf/Ref") or _text(tx, "RmtInf/Ustrd"))
            debtor = _text(tx, "Dbtr/Nm") or _text(tx, "Dbtr/Pty/Nm")
            tx_id = _text(tx, "AcctSvcrRef") if tx is not ntry else ""
            bank_id = tx_id or f"{ntry_ref}:{i}:{amount}:{reference}"
            entries.append(
                Entry(
                    amount=amount,
                    currency=currency,
                    reference=reference,
                    booked_on=date.fromisoformat(booked[:10]),
                    debtor=debtor[:140],
                    bank_id=bank_id[:100],
                )
            )
    return entries


@transaction.atomic
def apply(entries, *, organization, request=None):
    """Book entries for the organization; returns the list of created Payment objects (duplicates skipped)."""
    results = []
    known = set(Payment.objects.filter(organization=organization).values_list("bank_id", flat=True))
    for entry in entries:
        if entry.bank_id in known:
            continue  # this booking was imported before
        known.add(entry.bank_id)
        invoice = None
        if entry.reference:
            invoice = Invoice.objects.select_for_update().filter(issuer=organization, reference=entry.reference).first()
        if invoice is None:
            status = Payment.Status.UNMATCHED
        elif invoice.status != Invoice.Status.OPEN:
            status = Payment.Status.DUPLICATE
        else:
            invoice.paid_amount += entry.amount
            due = invoice.total + invoice.fees_total
            if invoice.paid_amount >= due:
                invoice.status = Invoice.Status.PAID
                invoice.paid_at = entry.booked_on
                status = Payment.Status.OVERPAID if invoice.paid_amount > due else Payment.Status.MATCHED
            else:
                status = Payment.Status.PARTIAL
            invoice.save(update_fields=["paid_amount", "status", "paid_at", "updated_at"])
        payment = Payment.objects.create(
            organization=organization,
            invoice=invoice if status != Payment.Status.UNMATCHED else None,
            amount=entry.amount,
            currency=entry.currency,
            reference=entry.reference,
            booked_on=entry.booked_on,
            debtor=entry.debtor,
            bank_id=entry.bank_id,
            status=status,
        )
        results.append(payment)
    paid = sum(1 for p in results if p.status in ("matched", "overpaid"))
    log(
        "payments.imported",
        request=request,
        organization=organization,
        changes={"zahlungen": len(results), "bezahlt": paid},
    )
    return results
