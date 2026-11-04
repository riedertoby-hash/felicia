from datetime import timedelta
from decimal import Decimal

import pytest
from django.core import mail
from django.core.files.uploadedfile import SimpleUploadedFile
from django.urls import reverse

from apps.billing import camt, dunning
from apps.billing import services as billing
from apps.billing.models import BillingSettings, Invoice, Payment
from tests.test_billing import delivered  # noqa: F401
from tests.test_orders import address  # noqa: F401

pytestmark = pytest.mark.django_db


@pytest.fixture
def invoice(supplier_a, customer, delivered):  # noqa: F811
    inv = billing.create_sale_invoice(supplier=supplier_a, customer=customer, orders=delivered)
    s = BillingSettings.for_org(supplier_a)
    s.reminder_fee = Decimal("20")
    s.save()
    return inv


def camt054(entries):
    """Minimal ISO 20022 camt.054.001.08 credit notification as Swiss banks deliver it."""
    ntries = "".join(
        f"""
      <Ntry><NtryRef>{bank_id}</NtryRef><Amt Ccy="CHF">{amount}</Amt><CdtDbtInd>{ind}</CdtDbtInd>
        <BookgDt><Dt>2026-11-03</Dt></BookgDt><ValDt><Dt>2026-11-03</Dt></ValDt>
        <AcctSvcrRef>{bank_id}</AcctSvcrRef>
        <NtryDtls><TxDtls><Refs><AcctSvcrRef>{bank_id}-1</AcctSvcrRef></Refs>
          <Amt Ccy="CHF">{amount}</Amt><CdtDbtInd>{ind}</CdtDbtInd>
          <RltdPties><Dbtr><Pty><Nm>Restaurant Linde</Nm></Pty></Dbtr></RltdPties>
          <RmtInf><Strd><CdtrRefInf><Tp><CdOrPrtry><Prtry>SCOR</Prtry></CdOrPrtry></Tp><Ref>{ref}</Ref></CdtrRefInf></Strd></RmtInf>
        </TxDtls></NtryDtls></Ntry>"""
        for bank_id, amount, ref, ind in entries
    )
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<Document xmlns="urn:iso:std:iso:20022:tech:xsd:camt.054.001.08"><BkToCstmrDbtCdtNtfctn>
  <GrpHdr><MsgId>MSG1</MsgId><CreDtTm>2026-11-03T10:00:00</CreDtTm></GrpHdr>
  <Ntfctn><Id>N1</Id><Acct><Id><IBAN>CH9300762011623852957</IBAN></Id></Acct>{ntries}</Ntfctn>
</BkToCstmrDbtCdtNtfctn></Document>""".encode()


# --- reminders -----------------------------------------------------------------------------------


def test_reminder_schedule(invoice, django_capture_on_commit_callbacks):
    due = invoice.due_date
    with django_capture_on_commit_callbacks(execute=True):
        assert dunning.run_reminders(today=due + timedelta(days=6)) == []
        first = dunning.run_reminders(today=due + timedelta(days=7))
    assert len(first) == 1 and first[0].level == 1 and first[0].fee == 0
    assert mail.outbox[-1].subject.startswith("Zahlungserinnerung")
    assert mail.outbox[-1].attachments[0][2] == "application/pdf"
    invoice.refresh_from_db()
    assert dunning.run_reminders(today=due + timedelta(days=8)) == []  # not twice
    second = dunning.run_reminders(today=invoice.last_reminder_on + timedelta(days=14))
    assert second[0].level == 2 and second[0].fee == Decimal("20")
    invoice.refresh_from_db()
    assert invoice.amount_due == invoice.total + Decimal("20")
    third = dunning.run_reminders(today=invoice.last_reminder_on + timedelta(days=14))
    assert third[0].level == 3
    assert dunning.run_reminders(today=invoice.last_reminder_on + timedelta(days=60)) == []  # max level


def test_reminders_can_be_disabled_and_skip_paid(supplier_a, invoice):
    s = BillingSettings.for_org(supplier_a)
    s.reminders_enabled = False
    s.save()
    assert dunning.run_reminders(today=invoice.due_date + timedelta(days=30)) == []
    s.reminders_enabled = True
    s.save()
    Invoice.objects.filter(pk=invoice.pk).update(status="paid")
    assert dunning.run_reminders(today=invoice.due_date + timedelta(days=30)) == []


def test_manual_reminder_and_pdf(login, supplier_a, customer, invoice):
    client = login(supplier_a.owner)
    client.post(reverse("billing:remind", args=[invoice.pk]), {"next": "/"})
    reminder = invoice.reminders.get()
    assert reminder.manual
    response = login(customer.owner).get(reverse("billing:reminder_pdf", args=[reminder.pk]))
    assert response.content.startswith(b"%PDF")
    assert login(supplier_a.clerk).post(reverse("billing:remind", args=[invoice.pk])).status_code == 403


# --- bank file -----------------------------------------------------------------------------------


def test_camt_parse_ignores_debits(invoice):
    entries = camt.parse(camt054([("B1", "139.00", invoice.reference, "CRDT"), ("B2", "50.00", "", "DBIT")]))
    assert len(entries) == 1
    e = entries[0]
    assert (e.amount, e.reference, e.debtor, str(e.booked_on)) == (
        Decimal("139.00"),
        invoice.reference,
        "Restaurant Linde",
        "2026-11-03",
    )


def test_camt_import_marks_invoice_paid_and_is_idempotent(login, supplier_a, invoice):
    client = login(supplier_a.owner)
    body = camt054([("B1", str(invoice.total), invoice.reference, "CRDT"), ("B2", "12.00", "RF00UNKNOWN", "CRDT")])
    client.post(reverse("billing:payments"), {"file": SimpleUploadedFile("camt.xml", body)})
    invoice.refresh_from_db()
    assert invoice.status == "paid" and invoice.paid_amount == invoice.total
    assert set(Payment.objects.values_list("status", flat=True)) == {"matched", "unmatched"}
    client.post(reverse("billing:payments"), {"file": SimpleUploadedFile("camt.xml", body)})
    assert Payment.objects.count() == 2  # same file twice: nothing new


def test_partial_payment_and_manual_assignment(login, supplier_a, invoice):
    client = login(supplier_a.owner)
    client.post(
        reverse("billing:payments"),
        {
            "file": SimpleUploadedFile(
                "c.xml", camt054([("P1", "100.00", invoice.reference, "CRDT"), ("P2", "39.00", "", "CRDT")])
            )
        },
    )
    invoice.refresh_from_db()
    assert invoice.status == "open" and invoice.amount_due == Decimal("39.00")
    unmatched = Payment.objects.get(status="unmatched")
    client.post(reverse("billing:payment_assign", args=[unmatched.pk]), {"invoice": invoice.pk})
    invoice.refresh_from_db()
    assert invoice.status == "paid"


def test_payments_of_other_supplier_do_not_match(login, supplier_b, invoice):
    login(supplier_b.owner).post(
        reverse("billing:payments"),
        {"file": SimpleUploadedFile("c.xml", camt054([("X1", str(invoice.total), invoice.reference, "CRDT")]))},
    )
    invoice.refresh_from_db()
    assert invoice.status == "open"
    assert Payment.objects.get().status == "unmatched"


def test_bad_bank_file(login, supplier_a):
    page = login(supplier_a.owner).post(
        reverse("billing:payments"),
        {"file": SimpleUploadedFile("x.xml", b"<!DOCTYPE x [<!ENTITY a SYSTEM 'file:///etc/passwd'>]><x>&a;</x>")},
    )
    assert "Keine gültige camt-Datei" in page.content.decode()


def test_clerk_and_customer_cannot_import_payments(login, supplier_a, customer):
    assert login(supplier_a.clerk).get(reverse("billing:payments")).status_code == 403
    assert login(customer.owner).get(reverse("billing:payments")).status_code == 403
