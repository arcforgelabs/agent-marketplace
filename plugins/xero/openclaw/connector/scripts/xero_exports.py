#!/usr/bin/env python3
"""Pure, network-free normalizers for file-producing Xero operating-model exports.

These helpers turn raw Xero Accounting API payloads into normalized, long-format
rows that match a downstream operating-model contract:

* ``flatten_pnl_tracking`` — turns a ``Reports/ProfitAndLoss`` report fetched with
  a ``trackingCategoryID`` (one column per tracking option) into one row per
  (account, tracking option), with an Income/Cost/Net reconciliation per segment.
* ``normalize_journals`` — turns ``/Journals`` lines into account-transaction rows
  signed by P&L direction (revenue positive, costs negative).

The connector CLI (``xero reports export-pnl-tracking`` / ``xero journals
export``) does the network + auth and calls these. Keeping the transforms here
means they can be unit-tested against fixtures with no Xero account.

Segment naming (e.g. Xero's ``Woodside`` option → an operating-model
``Woodside Surgery`` label, the untracked column → ``Shared / Unassigned``) is
deliberately NOT hardcoded: callers pass ``segment_map`` / ``untracked_label`` so
the connector stays generic across businesses.
"""

from __future__ import annotations

import csv
import re
import time
from datetime import date
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any


# Canonical output schemas (order matters — these are the CSV headers).
PNL_TRACKING_FIELDS = [
    "period_start",
    "period_end",
    "tracking_category",
    "account_code",
    "account_name",
    "account_class",
    "amount",
    "source_report",
    "exported_at",
    "notes",
]

ACCOUNT_TRANSACTION_FIELDS = [
    "transaction_date",
    "source_type",
    "source_id",
    "contact_name",
    "account_code",
    "account_name",
    "tracking_category",
    "description",
    "gross_amount",
    "tax_amount",
    "net_amount",
    "source_report",
    "exported_at",
    "notes",
]

PAYMENT_FIELDS = [
    "payment_date",
    "payment_id",
    "payment_type",
    "status",
    "source_type",
    "source_id",
    "invoice_id",
    "invoice_number",
    "contact_name",
    "contact_id",
    "amount",
    "account_name",
    "source_report",
    "exported_at",
    "notes",
]

AGED_RECEIVABLE_FIELDS = [
    "as_at_date",
    "contact_name",
    "invoice_number",
    "invoice_date",
    "due_date",
    "tracking_category",
    "amount_due",
    "current",
    "one_month",
    "two_months",
    "three_months_or_more",
    "source_report",
    "exported_at",
    "notes",
]

AGED_PAYABLE_FIELDS = [
    "as_at_date",
    "contact_name",
    "bill_number",
    "bill_date",
    "due_date",
    "tracking_category",
    "amount_due",
    "current",
    "one_month",
    "two_months",
    "three_months_or_more",
    "source_report",
    "exported_at",
    "notes",
]

BANK_TRANSACTION_FIELDS = [
    "date",
    "direction",
    "type",
    "contact_name",
    "bank_account",
    "account_code",
    "account_name",
    "account_class",
    "amount",
    "reference",
    "source_id",
    "notes",
]

# Section title (lower-cased, sans "less ") → operating-model account class.
SECTION_CLASSES = {
    "income": "REVENUE",
    "trading income": "REVENUE",
    "other income": "REVENUE",
    "cost of sales": "DIRECTCOSTS",
    "operating expenses": "EXPENSE",
    "expenses": "EXPENSE",
}

# Xero AccountType values that belong on the Profit & Loss (used to filter the
# general ledger down to P&L movement when reconstructing account transactions).
PNL_ACCOUNT_TYPES = {
    "REVENUE",
    "SALES",
    "OTHERINCOME",
    "DIRECTCOSTS",
    "EXPENSE",
    "OVERHEADS",
    "DEPRECIATN",
}


class ExportError(RuntimeError):
    """Raised when a report/journal payload cannot be normalized."""


def parse_money(value: Any) -> Decimal:
    """Parse a Xero cell/amount into a Decimal. Blank/dash → 0."""
    text = str(value if value is not None else "").strip().replace("$", "").replace(",", "")
    if text in {"", "-"}:
        return Decimal("0")
    negative = text.startswith("(") and text.endswith(")")
    if negative:
        text = text[1:-1]
    try:
        number = Decimal(text)
    except InvalidOperation:
        return Decimal("0")
    return -number if negative else number


def money_str(value: Decimal) -> str:
    return str(value.quantize(Decimal("0.01")))


def normalize_section_class(title: str) -> str | None:
    """Map a P&L section title to an account class, or None to skip the section."""
    key = (title or "").strip().lower()
    if key.startswith("less "):
        key = key[len("less "):]
    return SECTION_CLASSES.get(key)


def resolve_segment_label(raw: str, segment_map: dict[str, str], untracked_label: str) -> str:
    """Apply caller-supplied renames; the untracked column maps to untracked_label."""
    name = (raw or "").strip()
    if name == "" or name.lower() in {"unassigned", "no tracking", "(unassigned)", "none"}:
        return untracked_label
    return segment_map.get(name, segment_map.get(name.lower(), name))


def accounts_by_id(accounts: list[dict[str, Any]]) -> dict[str, dict[str, str]]:
    """Index a Xero Accounts list by AccountID → {code, name, type, class}."""
    index: dict[str, dict[str, str]] = {}
    for acct in accounts or []:
        account_id = str(acct.get("AccountID") or "").strip()
        if not account_id:
            continue
        index[account_id] = {
            "code": str(acct.get("Code") or "").strip(),
            "name": str(acct.get("Name") or "").strip(),
            "type": str(acct.get("Type") or "").strip(),
            "class": str(acct.get("Class") or "").strip(),
        }
    return index


def accounts_by_name(accounts: list[dict[str, Any]]) -> dict[str, dict[str, str]]:
    index: dict[str, dict[str, str]] = {}
    for acct in accounts or []:
        name = str(acct.get("Name") or "").strip().lower()
        if name:
            index.setdefault(name, {
                "code": str(acct.get("Code") or "").strip(),
                "name": str(acct.get("Name") or "").strip(),
            })
    return index


def _cell_account_id(cell: dict[str, Any]) -> str:
    for attr in cell.get("Attributes") or []:
        if attr.get("Id") == "account":
            return str(attr.get("Value") or "").strip()
    return ""


def flatten_pnl_tracking(
    report: dict[str, Any],
    accounts: list[dict[str, Any]],
    *,
    period_start: str,
    period_end: str,
    segment_map: dict[str, str] | None = None,
    untracked_label: str = "Unassigned",
    source_report: str = "Xero ProfitAndLoss (tracking)",
    exported_at: str = "",
    note: str = "",
    skip_zero: bool = True,
) -> tuple[list[dict[str, str]], dict[str, Any]]:
    """Flatten a tracking-split P&L report into long-format rows + reconciliation.

    ``report`` is one element of the Accounting API ``Reports`` array (the object
    with ``Rows``). The header row's cells (after the first label cell, before the
    trailing ``Total`` column) name the tracking-option columns.
    """
    segment_map = segment_map or {}
    by_id = accounts_by_id(accounts)
    by_name = accounts_by_name(accounts)
    rows_in = report.get("Rows") if isinstance(report, dict) else None
    if not isinstance(rows_in, list) or not rows_in:
        raise ExportError("report has no Rows; pass the report object with a trackingCategoryID")

    header = rows_in[0]
    if header.get("RowType") != "Header":
        raise ExportError("first report row is not a Header; cannot read tracking columns")
    header_cells = header.get("Cells") or []
    # Columns 1..n are tracking options; the last one is the "Total" column.
    raw_labels = [str(c.get("Value") or "").strip() for c in header_cells[1:]]
    if raw_labels and raw_labels[-1].lower() == "total":
        raw_labels = raw_labels[:-1]
    if not raw_labels:
        raise ExportError("no tracking-option columns found; was trackingCategoryID supplied?")

    out_rows: list[dict[str, str]] = []
    # recon[segment] = {"REVENUE": Decimal, "cost": Decimal, "net": Decimal-from-summary}
    recon: dict[str, dict[str, Decimal]] = {}

    def segment_for(index: int) -> str:
        return resolve_segment_label(raw_labels[index], segment_map, untracked_label)

    def walk(section_rows: list[dict[str, Any]], account_class: str | None) -> None:
        for row in section_rows:
            row_type = row.get("RowType")
            if row_type == "Section":
                section_class = normalize_section_class(row.get("Title", ""))
                walk(row.get("Rows") or [], section_class)
                continue
            cells = row.get("Cells") or []
            if not cells:
                continue
            label = str(cells[0].get("Value") or "").strip()
            value_cells = cells[1:]
            # "Net Profit" is the reconciliation reference. Xero emits it as a plain
            # Row inside an untitled trailing section (not a SummaryRow), so capture
            # it by label regardless of row type or section class. Match any row whose
            # label starts with "net profit" (e.g. "Net Profit", "Net Profit (Loss)",
            # "Net Profit for the Period") — this excludes "Gross Profit", "Total
            # Income", etc. while tolerating report-specific bottom-line wording.
            if label.lower().startswith("net profit"):
                for idx in range(min(len(raw_labels), len(value_cells))):
                    seg = segment_for(idx)
                    bucket = recon.setdefault(seg, {"REVENUE": Decimal("0"), "cost": Decimal("0"), "net_summary": Decimal("0")})
                    bucket["net_summary"] = parse_money(value_cells[idx].get("Value"))
                continue
            if row_type != "Row" or account_class is None:
                continue
            # An account-detail row. Resolve account code/name from the label cell's
            # AccountID attribute (robust to duplicate names), falling back to name.
            account_id = _cell_account_id(cells[0])
            meta = by_id.get(account_id) or by_name.get(label.lower()) or {}
            account_code = meta.get("code", "")
            account_name = meta.get("name") or label
            for idx in range(min(len(raw_labels), len(value_cells))):
                amount = parse_money(value_cells[idx].get("Value"))
                if skip_zero and amount == 0:
                    continue
                seg = segment_for(idx)
                out_rows.append({
                    "period_start": period_start,
                    "period_end": period_end,
                    "tracking_category": seg,
                    "account_code": account_code,
                    "account_name": account_name,
                    "account_class": account_class,
                    "amount": money_str(amount),
                    "source_report": source_report,
                    "exported_at": exported_at,
                    "notes": note,
                })
                bucket = recon.setdefault(seg, {"REVENUE": Decimal("0"), "cost": Decimal("0"), "net_summary": Decimal("0")})
                if account_class == "REVENUE":
                    bucket["REVENUE"] += amount
                else:
                    bucket["cost"] += amount

    walk(rows_in[1:], None)

    segments_summary = {}
    for seg, bucket in recon.items():
        income = bucket["REVENUE"]
        cost = bucket["cost"]
        net_computed = income - cost
        net_summary = bucket["net_summary"]
        segments_summary[seg] = {
            "income": money_str(income),
            "cost": money_str(cost),
            "net_computed": money_str(net_computed),
            "net_reported": money_str(net_summary),
            "net_delta": money_str(net_computed - net_summary),
        }

    reconciliation = {
        "segments": segments_summary,
        "row_count": len(out_rows),
        "columns": raw_labels,
    }
    return out_rows, reconciliation


def reconciliation_breaches(reconciliation: dict[str, Any], tolerance: Decimal) -> list[str]:
    """Return human-readable breach messages where |net_computed - net_reported| > tolerance."""
    breaches: list[str] = []
    for seg, summary in (reconciliation.get("segments") or {}).items():
        delta = abs(parse_money(summary.get("net_delta")))
        if delta > tolerance:
            breaches.append(
                f"{seg}: net_computed {summary.get('net_computed')} vs net_reported "
                f"{summary.get('net_reported')} (delta {summary.get('net_delta')})"
            )
    return breaches


def _line_tracking_label(
    line: dict[str, Any],
    *,
    category_id: str,
    category_name: str,
    segment_map: dict[str, str],
    untracked_label: str,
) -> str:
    """Resolve a journal line's tracking-option label for the wanted category."""
    for tc in line.get("TrackingCategories") or []:
        matches_id = category_id and str(tc.get("TrackingCategoryID") or "") == category_id
        matches_name = category_name and str(tc.get("Name") or "").lower() == category_name.lower()
        if matches_id or matches_name or (not category_id and not category_name):
            option = str(tc.get("Option") or "").strip()
            if option:
                return resolve_segment_label(option, segment_map, untracked_label)
    return untracked_label


def normalize_journals(
    journals: list[dict[str, Any]],
    accounts: list[dict[str, Any]],
    *,
    from_date: str,
    to_date: str,
    category_id: str = "",
    category_name: str = "",
    account_ids: set[str] | None = None,
    option_labels: set[str] | None = None,
    segment_map: dict[str, str] | None = None,
    untracked_label: str = "Unassigned",
    source_report: str = "Xero Journals (general ledger)",
    exported_at: str = "",
    note: str = "",
    pnl_only: bool = True,
) -> tuple[list[dict[str, str]], dict[str, Any]]:
    """Turn /Journals lines into account-transaction rows signed by P&L direction.

    Sign convention: revenue positive, costs negative. Xero journals post revenue
    as a credit (negative NetAmount) and costs as a debit (positive NetAmount), so
    revenue lines are negated to read positive and cost lines to read negative.
    """
    segment_map = segment_map or {}
    by_id = accounts_by_id(accounts)
    by_code: dict[str, dict[str, str]] = {m["code"]: m for m in by_id.values() if m.get("code")}
    rows: list[dict[str, str]] = []
    # totals[(account_code, segment)] = Decimal(net)
    totals: dict[tuple[str, str], Decimal] = {}
    skipped_non_pnl_lines = 0
    skipped_undated_lines = 0
    windowed = bool(from_date or to_date)

    for journal in journals or []:
        jdate = _journal_date(journal)
        # In a windowed export, a journal whose date cannot be parsed must be
        # EXCLUDED (treated as out-of-window) rather than silently included with a
        # blank transaction_date. Count its lines so the exclusion is visible.
        if windowed and not jdate:
            skipped_undated_lines += len(journal.get("JournalLines") or [])
            continue
        if from_date and jdate and jdate < from_date:
            continue
        if to_date and jdate and jdate > to_date:
            continue
        source_type = str(journal.get("SourceType") or "").strip()
        source_id = str(journal.get("SourceID") or journal.get("Reference") or "").strip()
        reference = str(journal.get("Reference") or "").strip()
        for line in journal.get("JournalLines") or []:
            account_id = str(line.get("AccountID") or "").strip()
            account_code = str(line.get("AccountCode") or "").strip()
            meta = by_id.get(account_id) or by_code.get(account_code) or {}
            account_type = (meta.get("type") or str(line.get("AccountType") or "")).strip().upper()
            account_class = (meta.get("class") or "").strip().upper()
            if pnl_only and account_type not in PNL_ACCOUNT_TYPES:
                # Exclude lines whose account type is not a known P&L type,
                # including empty/unknown types. A P&L-only export must not
                # leak balance-sheet or untyped lines.
                skipped_non_pnl_lines += 1
                continue
            # When an account restriction is active, a line whose AccountID does not
            # match is excluded — including a line with a blank AccountID, which must
            # not slip through a restricted export.
            if account_ids and account_id not in account_ids:
                continue
            segment = _line_tracking_label(
                line,
                category_id=category_id,
                category_name=category_name,
                segment_map=segment_map,
                untracked_label=untracked_label,
            )
            if option_labels and segment not in option_labels:
                continue
            # Xero journals post revenue as a credit (negative NetAmount) and costs
            # as a debit (positive NetAmount). Negating uniformly yields the
            # operating-model convention: revenue positive, costs negative.
            net = -parse_money(line.get("NetAmount"))
            gross = -parse_money(line.get("GrossAmount"))
            tax = -parse_money(line.get("TaxAmount"))
            account_name = meta.get("name") or str(line.get("AccountName") or "").strip()
            description = str(line.get("Description") or "").strip() or reference
            rows.append({
                "transaction_date": jdate or "",
                "source_type": source_type,
                "source_id": source_id,
                "contact_name": "",
                "account_code": account_code or meta.get("code", ""),
                "account_name": account_name,
                "tracking_category": segment,
                "description": description,
                "gross_amount": money_str(gross),
                "tax_amount": money_str(tax),
                "net_amount": money_str(net),
                "source_report": source_report,
                "exported_at": exported_at,
                "notes": note,
            })
            key = (account_code or meta.get("code", ""), segment)
            totals[key] = totals.get(key, Decimal("0")) + net

    by_account_segment = [
        {"account_code": code, "tracking_category": seg, "net_amount": money_str(total)}
        for (code, seg), total in sorted(totals.items())
    ]
    reconciliation = {
        "row_count": len(rows),
        "by_account_segment": by_account_segment,
        "from_date": from_date,
        "to_date": to_date,
        "skipped_non_pnl_lines": skipped_non_pnl_lines,
        "skipped_undated_lines": skipped_undated_lines,
    }
    return rows, reconciliation


def _journal_date(journal: dict[str, Any]) -> str | None:
    """Return the journal date as YYYY-MM-DD, honoring the Xero timezone offset.

    Xero emits JournalDate in MS-JSON format: ``/Date(millis+HHMM)/`` where the
    optional ``±HHMM`` suffix is a UTC offset. We apply that offset to the epoch
    millis before formatting so the local accounting date is preserved (matching
    how xero_core.xero_iso_date_from_value handles the same wire format). Falls
    back to an ISO date-string prefix if the value is already ISO-ish.
    """
    raw = journal.get("JournalDate")
    if isinstance(raw, str):
        match = re.search(r"/Date\((-?\d+)(?:([+-])(\d{2})(\d{2}))?\)", raw)
        if match:
            millis = int(match.group(1))
            if match.group(2):  # apply the ±HHMM timezone offset to the epoch
                sign = 1 if match.group(2) == "+" else -1
                offset_ms = sign * (int(match.group(3)) * 60 + int(match.group(4))) * 60 * 1000
                millis += offset_ms
            return time.strftime("%Y-%m-%d", time.gmtime(millis / 1000))
        if len(raw) >= 10 and raw[:4].isdigit():
            return raw[:10]
    return None


def _ms_json_date(raw: Any) -> str | None:
    """Parse a Xero MS-JSON date (``/Date(millis±HHMM)/``) to YYYY-MM-DD, honoring
    the optional ±HHMM timezone offset; falls back to an ISO-ish prefix. Returns
    None when unparseable. Mirrors ``_journal_date`` for the payments wire shape."""
    if isinstance(raw, str):
        match = re.search(r"/Date\((-?\d+)(?:([+-])(\d{2})(\d{2}))?\)", raw)
        if match:
            millis = int(match.group(1))
            if match.group(2):
                sign = 1 if match.group(2) == "+" else -1
                offset_ms = sign * (int(match.group(3)) * 60 + int(match.group(4))) * 60 * 1000
                millis += offset_ms
            return time.strftime("%Y-%m-%d", time.gmtime(millis / 1000))
        if len(raw) >= 10 and raw[:4].isdigit():
            return raw[:10]
    return None


def normalize_payments(
    payments: list[dict[str, Any]],
    *,
    from_date: str = "",
    to_date: str = "",
    source_report: str = "Xero payments export",
    exported_at: str = "",
    note: str = "",
    include_deleted: bool = False,
) -> list[dict[str, str]]:
    """Flatten Xero ``GET /Payments`` records to the operating-model payments
    schema. Amount stays positive; ``source_type`` (ACCREC = cash in, ACCPAY =
    cash out) carries direction. DELETED payments are dropped unless
    ``include_deleted``. The date window, when given, filters on payment date."""
    rows: list[dict[str, str]] = []
    for payment in payments:
        if not isinstance(payment, dict):
            continue
        status = str(payment.get("Status") or "").strip().upper()
        if not include_deleted and status == "DELETED":
            continue
        pdate = _ms_json_date(payment.get("Date")) or ""
        if from_date and pdate and pdate < from_date:
            continue
        if to_date and pdate and pdate > to_date:
            continue
        ptype = str(payment.get("PaymentType") or "").strip()
        upper = ptype.upper()
        if upper.startswith("ACCREC"):
            source_type = "ACCREC"
        elif upper.startswith("ACCPAY"):
            source_type = "ACCPAY"
        else:
            source_type = ptype
        invoice = payment.get("Invoice") if isinstance(payment.get("Invoice"), dict) else {}
        contact = invoice.get("Contact") if isinstance(invoice.get("Contact"), dict) else {}
        account = payment.get("Account") if isinstance(payment.get("Account"), dict) else {}
        payment_id = str(payment.get("PaymentID") or "").strip()
        notes_parts = []
        if from_date or to_date:
            notes_parts.append(f"Payments export from {from_date or '...'} to {to_date or '...'}.")
        notes_parts.append("Amount is positive; source_type ACCREC = cash in, ACCPAY = cash out.")
        if note:
            notes_parts.append(note)
        rows.append({
            "payment_date": pdate,
            "payment_id": payment_id,
            "payment_type": ptype,
            "status": status,
            "source_type": source_type,
            "source_id": payment_id,
            "invoice_id": str(invoice.get("InvoiceID") or "").strip(),
            "invoice_number": str(invoice.get("InvoiceNumber") or "").strip(),
            "contact_name": str(contact.get("Name") or "").strip(),
            "contact_id": str(contact.get("ContactID") or "").strip(),
            "amount": money_str(parse_money(payment.get("Amount"))),
            "account_name": str(account.get("Name") or "").strip(),
            "source_report": source_report,
            "exported_at": (exported_at or "")[:10],
            "notes": " ".join(notes_parts),
        })
    return rows


def _days_overdue(as_at_date: str, due_date: str) -> int | None:
    """Whole days the invoice/bill is overdue at ``as_at_date`` (negative/zero =
    not yet due). Returns None when either date is unparseable."""
    try:
        ay, am, ad = (int(part) for part in as_at_date.split("-"))
        dy, dm, dd = (int(part) for part in due_date.split("-"))
    except (ValueError, AttributeError):
        return None
    return (date(ay, am, ad) - date(dy, dm, dd)).days


def _age_bucket(days_overdue: int | None) -> str:
    """Map days-overdue to an aged bucket column. No due date / not overdue →
    current; 1-30 → one_month; 31-60 → two_months; 61+ → three_months_or_more."""
    if days_overdue is None or days_overdue <= 0:
        return "current"
    if days_overdue <= 30:
        return "one_month"
    if days_overdue <= 60:
        return "two_months"
    return "three_months_or_more"


def normalize_aged_invoices(
    invoices: list[dict[str, Any]],
    *,
    as_at_date: str,
    kind: str,
    source_report: str = "",
    exported_at: str = "",
    note: str = "",
) -> list[dict[str, str]]:
    """Flatten outstanding Xero invoices/bills to the aged-receivables/payables
    schema. ``kind`` is "receivable" (ACCREC → invoice_number/invoice_date) or
    "payable" (ACCPAY → bill_number/bill_date). The full amount_due lands in the
    single aged bucket matching its days-overdue (the other buckets are 0.00), so
    amount_due always equals current+one_month+two_months+three_months_or_more.
    tracking_category is left blank by design: Xero invoice tracking is line-level,
    so a single header value would be ambiguous."""
    number_field = "invoice_number" if kind == "receivable" else "bill_number"
    date_field = "invoice_date" if kind == "receivable" else "bill_date"
    rows: list[dict[str, str]] = []
    for invoice in invoices:
        if not isinstance(invoice, dict):
            continue
        amount_due = parse_money(invoice.get("AmountDue"))
        if amount_due == 0:
            continue
        due = _ms_json_date(invoice.get("DueDate")) or ""
        doc_date = _ms_json_date(invoice.get("Date")) or ""
        bucket = _age_bucket(_days_overdue(as_at_date, due) if due else None)
        contact = invoice.get("Contact") if isinstance(invoice.get("Contact"), dict) else {}
        amt = money_str(amount_due)
        zero = money_str(Decimal("0"))
        notes_parts = [f"Outstanding {kind} aged at {as_at_date}; full amount in the matching bucket."]
        if note:
            notes_parts.append(note)
        rows.append({
            "as_at_date": as_at_date,
            "contact_name": str(contact.get("Name") or "").strip(),
            number_field: str(invoice.get("InvoiceNumber") or invoice.get("Reference") or "").strip(),
            date_field: doc_date,
            "due_date": due,
            "tracking_category": "",
            "amount_due": amt,
            "current": amt if bucket == "current" else zero,
            "one_month": amt if bucket == "one_month" else zero,
            "two_months": amt if bucket == "two_months" else zero,
            "three_months_or_more": amt if bucket == "three_months_or_more" else zero,
            "source_report": source_report,
            "exported_at": (exported_at or "")[:10],
            "notes": " ".join(notes_parts),
        })
    return rows


def normalize_bank_transactions(
    transactions: list[dict[str, Any]],
    accounts: list[dict[str, Any]],
    *,
    exported_at: str = "",
    note: str = "",
    from_date: str = "",
    to_date: str = "",
) -> list[dict[str, str]]:
    """Flatten Xero ``GET /BankTransactions`` (actual cash through bank accounts —
    Spend/Receive Money, NOT accruals) to one row per line item. direction is
    'out' for SPEND*, 'in' for RECEIVE*. amount is the line amount (positive);
    the account_name is the cash category. DELETED/VOIDED are dropped."""
    by_code: dict[str, dict[str, Any]] = {}
    for acc in accounts or []:
        code = str(acc.get("Code") or acc.get("code") or "").strip()
        if code:
            by_code[code] = acc
    rows: list[dict[str, str]] = []
    for tx in transactions:
        if not isinstance(tx, dict):
            continue
        status = str(tx.get("Status") or "").strip().upper()
        if status in {"DELETED", "VOIDED"}:
            continue
        typ = str(tx.get("Type") or "").strip()
        upper = typ.upper()
        direction = "out" if upper.startswith("SPEND") else ("in" if upper.startswith("RECEIVE") else "")
        date = _ms_json_date(tx.get("Date")) or ""
        if from_date and date and date < from_date:
            continue
        if to_date and date and date > to_date:
            continue
        contact = tx.get("Contact") if isinstance(tx.get("Contact"), dict) else {}
        bankacc = tx.get("BankAccount") if isinstance(tx.get("BankAccount"), dict) else {}
        ref = str(tx.get("Reference") or "").strip()
        sid = str(tx.get("BankTransactionID") or "").strip()
        lines = tx.get("LineItems") or []
        if not lines:
            lines = [{"LineAmount": tx.get("Total"), "AccountCode": "", "Description": ""}]
        for line in lines:
            code = str(line.get("AccountCode") or "").strip()
            acc = by_code.get(code, {})
            name = (acc.get("Name") or acc.get("name") or str(line.get("Description") or "")).strip()
            klass = str(acc.get("Class") or acc.get("class") or acc.get("Type") or "").strip().upper()
            rows.append({
                "date": date,
                "direction": direction,
                "type": typ,
                "contact_name": str(contact.get("Name") or "").strip(),
                "bank_account": str(bankacc.get("Name") or bankacc.get("Code") or "").strip(),
                "account_code": code,
                "account_name": name,
                "account_class": klass,
                "amount": money_str(parse_money(line.get("LineAmount"))),
                "reference": ref,
                "source_id": sid,
                "notes": note,
            })
    return rows


def write_csv(path: Path, fields: list[str], rows: list[dict[str, str]]) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        for row in rows:
            writer.writerow({field: row.get(field, "") for field in fields})
