#!/usr/bin/env python3
"""Unentered-bill inbox: DRAFT ACCPAY review, original attachments, local coding.

Email-to-bills and published Hubdoc drafts land as Accounting DRAFT ACCPAY
invoices with the supplier file stapled. This module lists that inbox, extracts
what it can from the original attachment, and resolves finance-rules mappings.

Xero OCR fields are untrusted. Hubdoc items not yet published to Xero are
invisible (no public Hubdoc API). Learning stays in local finance-rules — there
is no API to train Xero's extractor.
"""

from __future__ import annotations

import re
import shutil
import subprocess
import zlib
from pathlib import Path
from typing import Any

import xero_finance_rules


CAVEATS = [
    "Xero OCR fields are untrusted; confirm supplier, dates, totals, and lines from the original file.",
    "Hubdoc documents that have not been published to Xero are not in this inbox (no public Hubdoc API).",
    "Xero Files dump is a separate API and is not this inbox.",
    "Learning is local finance-rules mappings, not Xero OCR.",
    "Org-specific approvers, default codes, and known suppliers belong in that org's local bill runbook.",
]

INBOX_STATUSES = ("DRAFT", "SUBMITTED")
DEFAULT_INBOX_STATUSES = ("DRAFT",)
DEFAULT_MAX_RENDER_PAGES = 4
JPEG_SOI = b"\xff\xd8\xff"
JPEG_EOI = b"\xff\xd9"
STREAM_RE = re.compile(rb"stream\r?\n(.*?)\r?\nendstream", re.DOTALL)
TJ_RE = re.compile(r"\((?:\\.|[^\\)])*\)\s*Tj")
PDF_ESCAPE_RE = re.compile(r"\\([nrtbf()\\]|[0-7]{1,3})")


class BillInboxError(RuntimeError):
    """User-facing bill-inbox error."""


def inbox_where(statuses: list[str] | tuple[str, ...] | None = None) -> str:
    """Xero `where` clause for supplier bills in the unentered inbox."""
    wanted = [status.strip().upper() for status in (statuses or DEFAULT_INBOX_STATUSES) if str(status).strip()]
    if not wanted:
        wanted = list(DEFAULT_INBOX_STATUSES)
    unknown = [status for status in wanted if status not in INBOX_STATUSES]
    if unknown:
        raise BillInboxError(
            f"Unsupported inbox status {unknown}; supported: {', '.join(INBOX_STATUSES)}"
        )
    status_clause = " OR ".join(f'Status=="{status}"' for status in wanted)
    if len(wanted) == 1:
        return f'Type=="ACCPAY" AND {status_clause}'
    return f'Type=="ACCPAY" AND ({status_clause})'


def mapping_name(supplier: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", (supplier or "").strip().lower()).strip("-")
    return slug or "supplier"


def safe_filename(name: str) -> str:
    base = Path(str(name or "")).name.strip()
    if not base or base in {".", ".."}:
        raise BillInboxError("Attachment filename is required.")
    if "/" in base or "\\" in base:
        raise BillInboxError("Attachment filename must not contain path separators.")
    return base


def default_review_dir(invoice_id: str) -> Path:
    ident = (invoice_id or "").strip()
    if not ident:
        raise BillInboxError("Invoice id is required.")
    return Path.home() / ".config" / "arc-forge-tools" / "xero" / "bill-inbox" / ident


def contact_name(obj: dict[str, Any]) -> str:
    contact = obj.get("Contact") if isinstance(obj.get("Contact"), dict) else {}
    return str(contact.get("Name") or "").strip()


def contact_id(obj: dict[str, Any]) -> str:
    contact = obj.get("Contact") if isinstance(obj.get("Contact"), dict) else {}
    return str(contact.get("ContactID") or "").strip()


def summarize_line(line: dict[str, Any]) -> dict[str, Any]:
    return {
        "description": line.get("Description"),
        "quantity": line.get("Quantity"),
        "unit_amount": line.get("UnitAmount"),
        "line_amount": line.get("LineAmount"),
        "account_code": line.get("AccountCode"),
        "tax_type": line.get("TaxType"),
        "item_code": line.get("ItemCode"),
    }


def summarize_bill(obj: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(obj, dict):
        raise BillInboxError("Bill record must be an object.")
    lines = [summarize_line(line) for line in obj.get("LineItems") or [] if isinstance(line, dict)]
    return {
        "invoice_id": obj.get("InvoiceID"),
        "type": obj.get("Type"),
        "status": obj.get("Status"),
        "contact_name": contact_name(obj) or None,
        "contact_id": contact_id(obj) or None,
        "date": _iso_date(obj.get("DateString") or obj.get("Date")),
        "due_date": _iso_date(obj.get("DueDateString") or obj.get("DueDate")),
        "invoice_number": obj.get("InvoiceNumber") or None,
        "reference": obj.get("Reference") or None,
        "line_amount_types": obj.get("LineAmountTypes"),
        "sub_total": obj.get("SubTotal"),
        "total_tax": obj.get("TotalTax"),
        "total": obj.get("Total"),
        "amount_due": obj.get("AmountDue"),
        "has_attachments": bool(obj.get("HasAttachments")),
        "updated_date_utc": obj.get("UpdatedDateUTC"),
        "lines": lines,
        "xero_ocr_untrusted": True,
    }


def suggest_coding(supplier: str, rules: dict[str, Any], *, extra_values: list[str] | None = None) -> dict[str, Any]:
    """Resolve contact/account/tax mappings for a supplier name and related labels."""
    values = [supplier, *(extra_values or [])]
    values = [value.strip() for value in values if str(value or "").strip()]
    contact = _first_mapping("contact", values, rules)
    account = _first_mapping("account", values, rules)
    tax = _first_mapping("tax", values, rules)
    target = account.get("target") if isinstance(account.get("target"), dict) else {}
    tax_from_account = str(target.get("tax_type") or target.get("TaxType") or "").strip()
    account_code = str(target.get("account_code") or target.get("AccountCode") or target.get("code") or "").strip()
    if not tax.get("matched") and tax_from_account:
        tax = {
            "matched": True,
            "kind": "tax",
            "strategy": "account-target",
            "source": account.get("source"),
            "rule": account.get("rule"),
            "target": {"tax_type": tax_from_account},
        }
    suggested_line = None
    if account_code:
        suggested_line = {
            "account_code": account_code,
            "tax_type": tax_from_account or ((tax.get("target") or {}).get("tax_type") if isinstance(tax.get("target"), dict) else None),
            "description": supplier or None,
        }
    return {
        "supplier": supplier or None,
        "contact": contact,
        "account": account,
        "tax": tax,
        "suggested_line": suggested_line,
        "unmapped": not bool(account.get("matched")),
    }


def learn_account_mapping(
    rules_path: Path,
    *,
    supplier: str,
    account_code: str,
    tax_type: str | None = None,
    contact_name_value: str | None = None,
    note: str | None = None,
    source: str = "bill-inbox",
) -> dict[str, Any]:
    """Persist a reviewed supplier → account/tax mapping. This is the learning layer."""
    supplier = (supplier or "").strip()
    account_code = (account_code or "").strip()
    if not supplier:
        raise BillInboxError("learn requires --supplier.")
    if not account_code:
        raise BillInboxError("learn requires --account-code.")
    name = mapping_name(supplier)
    target: dict[str, Any] = {"account_code": account_code}
    if tax_type and str(tax_type).strip():
        target["tax_type"] = str(tax_type).strip()
    results = [
        xero_finance_rules.upsert_mapping(
            rules_path,
            kind="account",
            name=name,
            aliases=[supplier],
            patterns=[],
            target=target,
            source=source,
            note=note,
        )
    ]
    if contact_name_value and str(contact_name_value).strip():
        results.append(
            xero_finance_rules.upsert_mapping(
                rules_path,
                kind="contact",
                name=name,
                aliases=[supplier, str(contact_name_value).strip()],
                patterns=[],
                target={"name": str(contact_name_value).strip()},
                source=source,
                note=note,
            )
        )
    if tax_type and str(tax_type).strip():
        results.append(
            xero_finance_rules.upsert_mapping(
                rules_path,
                kind="tax",
                name=name,
                aliases=[supplier],
                patterns=[],
                target={"tax_type": str(tax_type).strip()},
                source=source,
                note=note,
            )
        )
    return {
        "ok": True,
        "mode": "bill-learn",
        "supplier": supplier,
        "account_code": account_code,
        "tax_type": str(tax_type).strip() if tax_type else None,
        "rules": str(rules_path),
        "upserts": results,
        "note": "Stored in local finance-rules. Xero OCR is unchanged.",
    }


def extract_attachment(path: Path, out_dir: Path, *, max_pages: int = DEFAULT_MAX_RENDER_PAGES) -> dict[str, Any]:
    """Extract text and page images from a downloaded supplier file."""
    path = Path(path)
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    suffix = path.suffix.lower()
    mime = _guess_mime(path)
    result: dict[str, Any] = {
        "path": str(path),
        "filename": path.name,
        "mime_type": mime,
        "byte_count": path.stat().st_size if path.is_file() else 0,
        "extracted_text": None,
        "page_images": [],
        "extract_method": None,
        "extract_error": None,
    }
    if not path.is_file():
        result["extract_error"] = "file missing"
        return result
    if suffix in {".jpg", ".jpeg", ".png", ".webp", ".gif", ".bmp"} or mime.startswith("image/"):
        result["page_images"] = [str(path)]
        result["extract_method"] = "image-attachment"
        return result
    if suffix != ".pdf" and mime != "application/pdf":
        result["extract_method"] = "binary"
        return result
    text, method = _pdf_text(path)
    images, image_method = _pdf_images(path, out_dir, max_pages=max_pages)
    result["extracted_text"] = text
    result["page_images"] = [str(image) for image in images]
    result["extract_method"] = "+".join(item for item in (method, image_method) if item) or "pdf"
    if not text and not images:
        result["extract_error"] = (
            "No text or page images extracted. Install poppler-utils (pdftotext/pdftoppm) "
            "for scanned PDFs, or open the downloaded file."
        )
    return result


def next_steps(invoice_id: str, *, has_attachments: bool, unmapped: bool) -> list[str]:
    steps = [
        "Treat Xero contact/date/total/lines as untrusted OCR. Confirm them from extracted_text or page_images.",
    ]
    if not has_attachments:
        steps.append(
            "No supplier file is stapled on this DRAFT. Hubdoc unpublished items cannot be pulled. "
            "Ask the operator for the PDF or wait until Xero/Hubdoc publishes it onto the bill."
        )
    if unmapped:
        steps.append(
            "No local finance-rules account mapping for this supplier. Propose GL codes, then "
            "`xero bills learn --supplier ... --account-code ... --tax-type ...` after confirmation."
        )
    else:
        steps.append("Local mapping exists. Still confirm against the PDF before updating the DRAFT.")
    steps.append(
        f"To recode after confirmation: `xero documents update bill --identifier {invoice_id}` "
        "(dry-run first, then --apply with a preflight report). Do not AUTHORISE without an attachment."
    )
    steps.append(
        "If this organisation has a local bill runbook, follow it for approver, default codes, "
        "and known suppliers, then update that runbook after a confirmed learn."
    )
    return steps


def _first_mapping(kind: str, values: list[str], rules: dict[str, Any]) -> dict[str, Any]:
    last: dict[str, Any] = {"matched": False, "kind": kind, "source": values[0] if values else None, "target": None}
    for value in values:
        result = xero_finance_rules.resolve_mapping(kind, value, rules)
        last = result
        if result.get("matched"):
            return result
    return last


def _iso_date(value: Any) -> str | None:
    if isinstance(value, str) and len(value) >= 10 and value[:4].isdigit():
        return value[:10]
    if isinstance(value, str):
        match = re.search(r"/Date\((-?\d+)", value)
        if match:
            import time

            return time.strftime("%Y-%m-%d", time.gmtime(int(match.group(1)) / 1000))
    return None


def _guess_mime(path: Path) -> str:
    suffix = path.suffix.lower()
    return {
        ".pdf": "application/pdf",
        ".jpg": "image/jpeg",
        ".jpeg": "image/jpeg",
        ".png": "image/png",
        ".webp": "image/webp",
        ".gif": "image/gif",
        ".bmp": "image/bmp",
        ".tif": "image/tiff",
        ".tiff": "image/tiff",
    }.get(suffix, "application/octet-stream")


def _pdf_text(path: Path) -> tuple[str | None, str | None]:
    pdftotext = shutil.which("pdftotext")
    if pdftotext:
        try:
            completed = subprocess.run(
                [pdftotext, "-layout", "-enc", "UTF-8", str(path), "-"],
                check=False,
                capture_output=True,
                timeout=30,
            )
        except (OSError, subprocess.TimeoutExpired):
            completed = None
        if completed is not None and completed.returncode == 0:
            text = completed.stdout.decode("utf-8", errors="replace").strip()
            if text:
                return text, "pdftotext"
    raw = path.read_bytes()
    harvested: list[str] = []
    for body in STREAM_RE.findall(raw):
        payload = _maybe_inflate(body)
        harvested.extend(_tj_strings(payload))
    harvested.extend(_tj_strings(raw))
    # Preserve order, drop empties and duplicates that come from scanning both
    # inflated streams and the raw file.
    seen: set[str] = set()
    ordered: list[str] = []
    for item in harvested:
        if item and item not in seen:
            seen.add(item)
            ordered.append(item)
    if ordered:
        return "\n".join(ordered), "pdf-tj"
    return None, None


def _pdf_images(path: Path, out_dir: Path, *, max_pages: int) -> tuple[list[Path], str | None]:
    pdftoppm = shutil.which("pdftoppm")
    if pdftoppm:
        prefix = out_dir / "page"
        try:
            completed = subprocess.run(
                [pdftoppm, "-png", "-f", "1", "-l", str(max(1, max_pages)), str(path), str(prefix)],
                check=False,
                capture_output=True,
                timeout=60,
            )
        except (OSError, subprocess.TimeoutExpired):
            completed = None
        if completed is not None and completed.returncode == 0:
            images = sorted(out_dir.glob("page*.png"))[:max_pages]
            if images:
                return images, "pdftoppm"
    jpegs = _extract_embedded_jpegs(path.read_bytes(), out_dir, limit=max_pages)
    if jpegs:
        return jpegs, "embedded-jpeg"
    return [], None


def _extract_embedded_jpegs(data: bytes, out_dir: Path, *, limit: int) -> list[Path]:
    images: list[Path] = []
    start = 0
    while len(images) < limit:
        soi = data.find(JPEG_SOI, start)
        if soi < 0:
            break
        eoi = data.find(JPEG_EOI, soi + 3)
        if eoi < 0:
            break
        blob = data[soi : eoi + 2]
        if len(blob) >= 32:
            dest = out_dir / f"embedded-{len(images) + 1}.jpg"
            dest.write_bytes(blob)
            images.append(dest)
        start = eoi + 2
    return images


def _maybe_inflate(body: bytes) -> bytes:
    for wbits in (zlib.MAX_WBITS, -zlib.MAX_WBITS):
        try:
            return zlib.decompress(body, wbits)
        except zlib.error:
            continue
    return body


def _tj_strings(payload: bytes) -> list[str]:
    try:
        text = payload.decode("latin-1")
    except Exception:
        return []
    found: list[str] = []
    for match in TJ_RE.finditer(text):
        inner = match.group(0)
        inner = inner.rsplit("Tj", 1)[0].strip()
        if inner.startswith("(") and inner.endswith(")"):
            inner = inner[1:-1]
        decoded = _unescape_pdf(inner).strip()
        if decoded:
            found.append(decoded)
    return found


def _unescape_pdf(value: str) -> str:
    mapping = {"n": "\n", "r": "\r", "t": "\t", "b": "\b", "f": "\f", "(": "(", ")": ")", "\\": "\\"}

    def repl(match: re.Match[str]) -> str:
        token = match.group(1)
        if token in mapping:
            return mapping[token]
        try:
            return chr(int(token, 8))
        except ValueError:
            return token

    return PDF_ESCAPE_RE.sub(repl, value)
