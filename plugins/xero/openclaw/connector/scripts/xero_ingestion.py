#!/usr/bin/env python3
"""Phase 3 — Source-document ingestion helper for the Arc Forge Xero connector.

Converts a *structured sidecar* (JSON or key:value text) for a local source
document into the normalised bill-candidate payload shape consumed by:

    ``xero ap draft-bill``   (profile-pack-driven lifecycle)
    ``xero audit dry-run``   (dedup / mapping checks against snapshots)

This module is intentionally pure (no network, no auth, no Xero I/O) so it is
trivially unit-tested and usable from both the CLI and MCP layers.

## Bill-ingestion input lanes (§4.6, §8.6)

The Xero platform offers two *UI-only* document-to-draft lanes that this tool
cannot replace:

1. **Bills email address** — each Xero org has a unique inbound address; emailing
   a PDF/invoice to it creates a DRAFT bill in the Xero UI. No API control.
   (<https://central.xero.com/s/article/Upload-or-email-documents-into-Hubdoc>)

2. **Hubdoc** — Xero's document-capture product; no public API exists. Hubdoc-
   extracted drafts appear in Xero as DRAFT bills.

In both cases the DRAFT bills land in Xero *outside* the API workflow.  The
dedup sweep in ``xero audit dry-run`` treats externally created drafts as
first-class candidates (not duplicates) — they are picked up at the
coding/approval step exactly like API-created drafts.

This module handles the *third* lane: a locally stored source document (PDF,
receipt, supplier invoice) for which the operator writes a structured sidecar
that this tool parses into a candidate ready for ``ap draft-bill``.

## Sidecar format

A sidecar is a JSON file (preferred) or a plain key:value text file placed
alongside the source document.  Required fields: supplier, date, total.
Optional: reference, lines, currency, invoice_number, note.

JSON example::

    {
      "supplier": "Example Supplier Pty Ltd",
      "date": "2026-06-10",
      "total": 220.00,
      "reference": "INV-2026-0042",
      "lines": [
        {"account": "485", "tax": "INPUT", "amount": 200.00, "description": "Software subscription"}
      ],
      "currency": "AUD",
      "note": "Annual subscription renewal"
    }

Key:value text example::

    supplier: Example Supplier Pty Ltd
    date: 2026-06-10
    total: 220.00
    reference: INV-2026-0042

## Output shape (bill candidate)

The normalised candidate is a dict matching the ap draft-bill / audit-dry-run
schema.  It can be serialised to JSON and passed directly to those commands via
``--payload`` or ``--candidates``.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------


class IngestionError(RuntimeError):
    """User-facing sidecar ingestion error."""


# ---------------------------------------------------------------------------
# Sidecar parsing
# ---------------------------------------------------------------------------

# Fields accepted in a key:value text sidecar.
_TEXT_FIELD_MAP: dict[str, str] = {
    "supplier": "supplier",
    "date": "date",
    "total": "total",
    "reference": "reference",
    "currency": "currency",
    "invoice_number": "invoice_number",
    "invoicenumber": "invoice_number",
    "invoice number": "invoice_number",
    "note": "note",
}


def parse_text_sidecar(text: str) -> dict[str, Any]:
    """Parse a plain ``key: value`` text sidecar into a raw dict.

    Each non-blank line must be ``key: value``.  Unknown keys are ignored.
    Lines beginning with ``#`` are treated as comments.
    """
    raw: dict[str, Any] = {}
    for lineno, line in enumerate(text.splitlines(), start=1):
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        if ":" not in stripped:
            raise IngestionError(
                f"sidecar line {lineno}: expected 'key: value', got {stripped!r}"
            )
        key_raw, _, value = stripped.partition(":")
        key = key_raw.strip().lower()
        canonical = _TEXT_FIELD_MAP.get(key)
        if canonical:
            raw[canonical] = value.strip()
    return raw


def load_sidecar(path: str | Path) -> dict[str, Any]:
    """Load a JSON or key:value text sidecar from *path*.

    The format is auto-detected: if the file parses as JSON, JSON wins;
    otherwise it is treated as a key:value text sidecar.
    """
    resolved = Path(path).expanduser().resolve()
    if not resolved.is_file():
        raise IngestionError(f"sidecar file not found: {resolved}")
    text = resolved.read_text(encoding="utf-8")
    text = text.strip()
    if text.startswith("{"):
        try:
            raw = json.loads(text)
        except json.JSONDecodeError as exc:
            raise IngestionError(f"sidecar {resolved} is not valid JSON: {exc}") from exc
        if not isinstance(raw, dict):
            raise IngestionError("sidecar JSON must be a top-level object")
        return raw
    return parse_text_sidecar(text)


# ---------------------------------------------------------------------------
# Candidate normalisation
# ---------------------------------------------------------------------------

_ISO_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def parse_money(value: Any) -> float | None:
    """Parse a currency string or number to a float rounded to 2 dp."""
    if value is None or value == "":
        return None
    if isinstance(value, (int, float)):
        return round(float(value), 2)
    cleaned = re.sub(r"[^0-9.\-]", "", str(value))
    if not cleaned:
        return None
    try:
        return round(float(cleaned), 2)
    except ValueError:
        return None


def normalise_candidate(
    raw: dict[str, Any],
    *,
    source_file: str | Path | None = None,
) -> dict[str, Any]:
    """Validate and normalise a raw sidecar dict into a bill candidate.

    Returns a dict suitable for passing to ``xero ap draft-bill`` (via
    ``--payload``) or ``xero audit dry-run`` (via ``--candidates``).

    Required raw fields: supplier, date, total.
    Optional: reference, lines, currency, invoice_number, note.
    """
    # --- supplier ---
    supplier = str(raw.get("supplier") or "").strip()
    if not supplier:
        raise IngestionError("sidecar missing required field: supplier")

    # --- date ---
    date_raw = str(raw.get("date") or "").strip()
    if not date_raw:
        raise IngestionError("sidecar missing required field: date")
    if not _ISO_DATE_RE.match(date_raw):
        raise IngestionError(
            f"sidecar 'date' must be YYYY-MM-DD, got {date_raw!r}"
        )

    # --- total ---
    total = parse_money(raw.get("total"))
    if total is None:
        raise IngestionError(
            f"sidecar 'total' must be a number, got {raw.get('total')!r}"
        )

    # --- reference (optional) ---
    reference = str(raw.get("reference") or raw.get("invoice_number") or "").strip() or None

    # --- currency (optional; default AUD) ---
    currency = str(raw.get("currency") or "AUD").strip().upper()
    if len(currency) != 3 or not currency.isalpha():
        raise IngestionError(f"sidecar 'currency' must be a 3-letter ISO code, got {currency!r}")

    # --- lines (optional) ---
    lines: list[dict[str, Any]] = []
    raw_lines = raw.get("lines")
    if raw_lines is not None:
        if not isinstance(raw_lines, list):
            raise IngestionError("sidecar 'lines' must be an array")
        for idx, line in enumerate(raw_lines, start=1):
            if not isinstance(line, dict):
                raise IngestionError(f"sidecar lines[{idx}] must be an object")
            account = str(line.get("account") or "").strip()
            tax = str(line.get("tax") or "").strip()
            amount = parse_money(line.get("amount"))
            if amount is None:
                raise IngestionError(
                    f"sidecar lines[{idx}]: 'amount' must be a number, got {line.get('amount')!r}"
                )
            desc = str(line.get("description") or line.get("desc") or account or "").strip()
            li: dict[str, Any] = {
                "AccountCode": account,
                "LineAmount": amount,
                "Quantity": 1,
                "UnitAmount": amount,
                "Description": desc,
            }
            if tax:
                li["TaxType"] = tax
            lines.append(li)
    else:
        # No explicit lines: synthesise a single-line summary from total.
        lines = [
            {
                "AccountCode": "",
                "LineAmount": total,
                "Quantity": 1,
                "UnitAmount": total,
                "Description": f"{supplier} – {date_raw}",
            }
        ]

    # --- note (optional) ---
    note = str(raw.get("note") or "").strip() or None

    candidate: dict[str, Any] = {
        "Type": "ACCPAY",
        "Contact": {"Name": supplier},
        "Date": date_raw,
        "CurrencyCode": currency,
        "LineItems": lines,
        "Status": "DRAFT",
        "LineAmountTypes": "Exclusive",
    }
    if reference:
        candidate["Reference"] = reference
    # `_`-prefixed keys are local ingestion metadata, NOT Xero fields. They are
    # NOT auto-stripped — a caller passing this dict straight to `documents
    # create --payload` would send them to Xero. Use strip_ingestion_metadata()
    # (or `ap draft-bill`, which only reads the structured fields) before any API
    # send. See INGESTION_METADATA_KEYS.
    if note:
        candidate["_ingestion_note"] = note
    if source_file:
        candidate["_source_file"] = str(source_file)

    return candidate


# Local-only keys added by normalise_candidate; never sent to the Xero API.
INGESTION_METADATA_KEYS: frozenset[str] = frozenset({"_ingestion_note", "_source_file"})


def strip_ingestion_metadata(candidate: dict[str, Any]) -> dict[str, Any]:
    """Return a copy of *candidate* with local ingestion metadata removed.

    Removes every ``_``-prefixed key (e.g. ``_ingestion_note``, ``_source_file``)
    so the result is safe to send to Xero (e.g. via ``documents create --payload``).
    Returns a new dict; the input is not mutated.
    """
    return {k: v for k, v in candidate.items() if not k.startswith("_")}


# ---------------------------------------------------------------------------
# Public helpers
# ---------------------------------------------------------------------------


def ingest_sidecar(
    path: str | Path,
    *,
    source_file: str | Path | None = None,
) -> dict[str, Any]:
    """Load a sidecar file and return a normalised bill candidate.

    ``source_file`` is the path to the accompanying source document (PDF etc.);
    it is embedded in the candidate as ``_source_file`` for downstream use
    (e.g. building an evidence attach-batch manifest).
    """
    raw = load_sidecar(path)
    return normalise_candidate(raw, source_file=source_file or path)


def candidate_to_draft_bill_args(candidate: dict[str, Any]) -> list[str]:
    """Build the CLI argument list for ``xero ap draft-bill`` from a candidate.

    Returns a list suitable for ``subprocess.run(["xero", "ap", "draft-bill"] + args)``
    or for documenting the equivalent manual invocation.  Does NOT execute anything.

    The ``--ap-policy`` and ``--preflight-report`` flags must be added by the
    caller (they depend on the org's profile pack path).
    """
    args: list[str] = []
    contact = candidate.get("Contact") or {}
    name = contact.get("ContactID") or contact.get("Name") or ""
    if name:
        args += ["--contact-id", name]
    date = candidate.get("Date")
    if date:
        args += ["--bill-date", str(date)]
    ref = candidate.get("Reference")
    if ref:
        args += ["--reference", str(ref)]
    for li in candidate.get("LineItems") or []:
        account = str(li.get("AccountCode") or "")
        tax = str(li.get("TaxType") or "")
        amount = str(li.get("LineAmount") or li.get("UnitAmount") or "")
        desc = str(li.get("Description") or "")
        spec = f"{account}:{tax}:{amount}:{desc}" if desc else f"{account}:{tax}:{amount}"
        args += ["--line", spec]
    lat = str(candidate.get("LineAmountTypes") or "Exclusive")
    if lat != "Exclusive":
        args += ["--line-amount-types", lat]
    return args


def ui_ingestion_lanes_note() -> str:
    """Return a short note for CLI output describing the UI-only input lanes.

    These lanes produce DRAFT bills outside the API workflow; the dedup step
    treats them as first-class candidates.
    """
    return (
        "Bill-ingestion input lanes not controllable via the Xero API:\n"
        "  • Bills email address — email a PDF/invoice to the org's unique Xero address;\n"
        "    a DRAFT bill is created automatically in the Xero UI.\n"
        "  • Hubdoc — Xero's document-capture product; no public API exists.\n"
        "    Hubdoc-extracted drafts appear as DRAFT bills in Xero.\n"
        "In both cases, run `xero audit dry-run` to pick up and code the resulting drafts."
    )
