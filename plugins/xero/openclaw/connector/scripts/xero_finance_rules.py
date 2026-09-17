#!/usr/bin/env python3
"""Reusable Xero finance-rule helpers.

This module is intentionally generic. It provides rule loading, naming parsers,
mapping resolution, snapshot-based duplicate checks, and dry-run reports without
shipping private account codes, customer names, or bookkeeping policy defaults.
"""

from __future__ import annotations

import json
import os
import re
import stat
import time
import secrets
from dataclasses import dataclass
from pathlib import Path
from typing import Any


DEFAULT_RULES_PATH = Path.home() / ".config" / "arc-forge-tools" / "xero" / "finance-rules.json"
DEFAULT_SNAPSHOT_DIR = Path.home() / ".config" / "arc-forge-tools" / "xero" / "snapshots"
DEFAULT_AUDIT_DIR = Path.home() / ".config" / "arc-forge-tools" / "xero" / "audit"
RULES_TEMPLATE_PATH = Path(__file__).resolve().parents[1] / "finance-rules" / "templates" / "default-rules.json"
DEFAULT_MAX_APPLY_BATCH_SIZE = 25
SUPPORTED_MAPPING_KINDS = {"account", "tax", "item", "contact"}
SUPPORTED_REVIEW_RULES = {
    "duplicate_candidate",
    "missing_attachment",
    "missing_reference",
    "negative_total",
    "non_draft_document_status",
    "unmapped_account",
    "unmapped_contact",
    "unmapped_item",
    "unmapped_tax",
}
DOCUMENT_STATUS_KEYS = {
    "invoice": "invoice_status",
    "bill": "bill_status",
    "quote": "quote_status",
    "credit_note": "credit_note_status",
}
SECRET_KEYS = {"access_token", "refresh_token", "id_token", "token", "authorization", "client_secret", "cookie", "mfa", "totp"}


class FinanceRulesError(RuntimeError):
    """User-facing finance-rule error."""


@dataclass
class RulesValidation:
    errors: list[dict[str, str]]
    warnings: list[dict[str, str]]

    @property
    def ok(self) -> bool:
        return not self.errors


def utc_seconds() -> int:
    return int(time.time())


def rules_path(value: str | None = None) -> Path:
    raw = value or os.environ.get("XERO_FINANCE_RULES") or os.environ.get("ARC_FORGE_XERO_FINANCE_RULES")
    return Path(raw).expanduser().resolve() if raw else DEFAULT_RULES_PATH


def snapshot_dir(value: str | None = None) -> Path:
    raw = value or os.environ.get("XERO_SNAPSHOT_DIR") or os.environ.get("ARC_FORGE_XERO_SNAPSHOT_DIR")
    return Path(raw).expanduser().resolve() if raw else DEFAULT_SNAPSHOT_DIR


def audit_dir(value: str | None = None) -> Path:
    raw = value or os.environ.get("XERO_AUDIT_DIR") or os.environ.get("ARC_FORGE_XERO_AUDIT_DIR")
    return Path(raw).expanduser().resolve() if raw else DEFAULT_AUDIT_DIR


def normalize_key(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "").strip().lower())


def compact_key(value: Any) -> str:
    return re.sub(r"[^a-z0-9]+", "", normalize_key(value))


def parse_money(value: Any) -> float | None:
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


def load_json_file(path: Path) -> Any:
    try:
        with path.open("r", encoding="utf-8") as handle:
            return json.load(handle)
    except json.JSONDecodeError as exc:
        raise FinanceRulesError(f"Invalid JSON: {path}: {exc}") from exc


def write_json_file(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_suffix(path.suffix + ".tmp")
    with tmp_path.open("w", encoding="utf-8") as handle:
        json.dump(payload, handle, indent=2, sort_keys=False)
        handle.write("\n")
    os.chmod(tmp_path, stat.S_IRUSR | stat.S_IWUSR)
    tmp_path.replace(path)
    os.chmod(path, stat.S_IRUSR | stat.S_IWUSR)


def append_jsonl(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(payload, sort_keys=False) + "\n")
    os.chmod(path, stat.S_IRUSR | stat.S_IWUSR)


def redact_value(value: Any) -> Any:
    if not isinstance(value, str):
        return value
    if len(value) <= 8:
        return "***"
    return f"{value[:4]}...{value[-4:]}"


def redact_payload(payload: Any) -> Any:
    if isinstance(payload, dict):
        redacted: dict[str, Any] = {}
        for key, value in payload.items():
            if key.lower() in SECRET_KEYS:
                redacted[key] = redact_value(value)
            else:
                redacted[key] = redact_payload(value)
        return redacted
    if isinstance(payload, list):
        return [redact_payload(item) for item in payload]
    return payload


def default_rules_template() -> dict[str, Any]:
    if RULES_TEMPLATE_PATH.exists():
        payload = load_json_file(RULES_TEMPLATE_PATH)
        if isinstance(payload, dict):
            return payload
    return {
        "schema_version": 1,
        "name": "local-xero-finance-rules",
        "parsers": [],
        "mappings": {"account": [], "tax": [], "item": [], "contact": []},
        "dedup": {
            "invoice": {"match_fields": ["reference", "contact", "total"]},
            "bill": {"match_fields": ["reference", "contact", "total"]},
            "payment": {"match_fields": ["reference", "amount", "date"]},
            "bank_transaction": {"match_fields": ["reference", "amount", "date"]},
        },
        "conventions": {
            "document_defaults": {
                "invoice_status": "DRAFT",
                "bill_status": "DRAFT",
                "quote_status": "DRAFT",
                "credit_note_status": "DRAFT",
            },
            "review_required": [
                "duplicate_candidate",
                "missing_reference",
                "negative_total",
                "non_draft_document_status",
                "unmapped_account",
                "unmapped_contact",
                "unmapped_item",
                "unmapped_tax",
            ],
            "evidence": {"attach_before_authorise": True, "history_note_on_apply": True},
            "reconciliation": {"api_prework_first": True, "cdp_apply_requires_explicit_plan": True},
        },
    }


def load_rules(path: Path) -> dict[str, Any]:
    if not path.exists():
        raise FinanceRulesError(f"Finance rules file does not exist: {path}. Run `xero rules init` first.")
    payload = load_json_file(path)
    if not isinstance(payload, dict):
        raise FinanceRulesError(f"Finance rules root must be an object: {path}")
    return payload


def validate_rules(rules: dict[str, Any]) -> RulesValidation:
    errors: list[dict[str, str]] = []
    warnings: list[dict[str, str]] = []
    if rules.get("schema_version") != 1:
        errors.append({"path": "schema_version", "message": "schema_version must be 1."})

    parsers = rules.get("parsers", [])
    if not isinstance(parsers, list):
        errors.append({"path": "parsers", "message": "parsers must be an array."})
    else:
        for index, parser in enumerate(parsers):
            path = f"parsers[{index}]"
            if not isinstance(parser, dict):
                errors.append({"path": path, "message": "parser must be an object."})
                continue
            if not str(parser.get("name") or "").strip():
                errors.append({"path": f"{path}.name", "message": "parser name is required."})
            pattern = str(parser.get("pattern") or "")
            if not pattern:
                errors.append({"path": f"{path}.pattern", "message": "parser pattern is required."})
            else:
                try:
                    re.compile(pattern)
                except re.error as exc:
                    errors.append({"path": f"{path}.pattern", "message": f"invalid regex: {exc}"})

    mappings = rules.get("mappings", {})
    if not isinstance(mappings, dict):
        errors.append({"path": "mappings", "message": "mappings must be an object."})
    else:
        for kind, entries in mappings.items():
            if kind not in SUPPORTED_MAPPING_KINDS:
                warnings.append({"path": f"mappings.{kind}", "message": "unknown mapping kind will be ignored by generic helpers."})
            if not isinstance(entries, list):
                errors.append({"path": f"mappings.{kind}", "message": "mapping entries must be an array."})
                continue
            for index, entry in enumerate(entries):
                path = f"mappings.{kind}[{index}]"
                if not isinstance(entry, dict):
                    errors.append({"path": path, "message": "mapping entry must be an object."})
                    continue
                if not isinstance(entry.get("target"), dict):
                    errors.append({"path": f"{path}.target", "message": "target object is required."})
                aliases = entry.get("aliases", [])
                patterns = entry.get("patterns", [])
                if aliases and not isinstance(aliases, list):
                    errors.append({"path": f"{path}.aliases", "message": "aliases must be an array."})
                if patterns and not isinstance(patterns, list):
                    errors.append({"path": f"{path}.patterns", "message": "patterns must be an array."})
                for pattern_index, pattern in enumerate(patterns if isinstance(patterns, list) else []):
                    try:
                        re.compile(str(pattern))
                    except re.error as exc:
                        errors.append({"path": f"{path}.patterns[{pattern_index}]", "message": f"invalid regex: {exc}"})

    dedup = rules.get("dedup", {})
    if dedup and not isinstance(dedup, dict):
        errors.append({"path": "dedup", "message": "dedup must be an object."})
    elif isinstance(dedup, dict):
        for kind, rule in dedup.items():
            path = f"dedup.{kind}"
            if not isinstance(rule, dict):
                errors.append({"path": path, "message": "dedup rule must be an object."})
                continue
            fields = rule.get("match_fields", [])
            if fields and not isinstance(fields, list):
                errors.append({"path": f"{path}.match_fields", "message": "match_fields must be an array."})

    conventions = rules.get("conventions", {})
    if conventions and not isinstance(conventions, dict):
        errors.append({"path": "conventions", "message": "conventions must be an object."})
    elif isinstance(conventions, dict):
        document_defaults = conventions.get("document_defaults", {})
        if document_defaults and not isinstance(document_defaults, dict):
            errors.append({"path": "conventions.document_defaults", "message": "document_defaults must be an object."})
        elif isinstance(document_defaults, dict):
            for key, value in document_defaults.items():
                if key not in set(DOCUMENT_STATUS_KEYS.values()):
                    warnings.append({"path": f"conventions.document_defaults.{key}", "message": "unknown document default will be ignored by generic helpers."})
                if not isinstance(value, str) or not value.strip():
                    errors.append({"path": f"conventions.document_defaults.{key}", "message": "document status default must be a non-empty string."})
        review_required = conventions.get("review_required", [])
        if review_required and not isinstance(review_required, list):
            errors.append({"path": "conventions.review_required", "message": "review_required must be an array."})
        elif isinstance(review_required, list):
            for index, rule in enumerate(review_required):
                if not isinstance(rule, str) or not rule.strip():
                    errors.append({"path": f"conventions.review_required[{index}]", "message": "review rule must be a non-empty string."})
                    continue
                if rule not in SUPPORTED_REVIEW_RULES:
                    warnings.append({"path": f"conventions.review_required[{index}]", "message": "unknown review rule will be ignored by generic helpers."})
        for section_name in ("evidence", "reconciliation"):
            section = conventions.get(section_name, {})
            if section and not isinstance(section, dict):
                errors.append({"path": f"conventions.{section_name}", "message": f"{section_name} must be an object."})
    return RulesValidation(errors=errors, warnings=warnings)


def init_rules(path: Path, *, force: bool = False) -> dict[str, Any]:
    if path.exists() and not force:
        raise FinanceRulesError(f"Finance rules file already exists: {path}. Use --force to overwrite.")
    payload = default_rules_template()
    write_json_file(path, payload)
    return payload


def unique_text_values(values: list[Any]) -> list[str]:
    seen: set[str] = set()
    output: list[str] = []
    for value in values:
        text = str(value or "").strip()
        if not text:
            continue
        key = normalize_key(text)
        if key in seen:
            continue
        seen.add(key)
        output.append(text)
    return output


def mapping_entry_matches(entry: dict[str, Any], name: str, aliases: list[str], patterns: list[str]) -> bool:
    entry_name = normalize_key(entry.get("name"))
    if name and entry_name == normalize_key(name):
        return True
    entry_aliases = entry.get("aliases", []) if isinstance(entry.get("aliases"), list) else []
    alias_keys = {normalize_key(alias) for alias in entry_aliases}
    if alias_keys.intersection({normalize_key(alias) for alias in aliases}):
        return True
    entry_patterns = entry.get("patterns", []) if isinstance(entry.get("patterns"), list) else []
    pattern_keys = {str(pattern) for pattern in entry_patterns}
    return bool(pattern_keys.intersection({str(pattern) for pattern in patterns}))


def upsert_mapping(
    path: Path,
    *,
    kind: str,
    name: str,
    aliases: list[str] | None,
    patterns: list[str] | None,
    target: dict[str, Any],
    source: str = "operator",
    note: str | None = None,
) -> dict[str, Any]:
    if kind not in SUPPORTED_MAPPING_KINDS:
        raise FinanceRulesError(f"Unsupported mapping kind: {kind}")
    if not name.strip():
        raise FinanceRulesError("Mapping name is required.")
    if not isinstance(target, dict) or not target:
        raise FinanceRulesError("Mapping target must be a non-empty object.")
    merged_aliases = unique_text_values(aliases or [])
    merged_patterns = unique_text_values(patterns or [])
    if not merged_aliases and not merged_patterns:
        raise FinanceRulesError("Mapping requires at least one alias or pattern.")

    rules = load_rules(path)
    mappings = rules.setdefault("mappings", {})
    if not isinstance(mappings, dict):
        raise FinanceRulesError("Finance rules mappings must be an object before upsert.")
    entries = mappings.setdefault(kind, [])
    if not isinstance(entries, list):
        raise FinanceRulesError(f"Finance rules mappings.{kind} must be an array before upsert.")

    now = utc_seconds()
    selected_index: int | None = None
    for index, entry in enumerate(entries):
        if isinstance(entry, dict) and mapping_entry_matches(entry, name, merged_aliases, merged_patterns):
            selected_index = index
            break

    mode = "created"
    if selected_index is None:
        entry = {
            "name": name.strip(),
            "aliases": merged_aliases,
            "patterns": merged_patterns,
            "target": target,
            "source": source.strip() or "operator",
            "created_at": now,
            "updated_at": now,
        }
        if note:
            entry["note"] = note.strip()
        entries.append(entry)
        selected_index = len(entries) - 1
    else:
        mode = "updated"
        entry = entries[selected_index]
        existing_aliases = entry.get("aliases", []) if isinstance(entry.get("aliases"), list) else []
        existing_patterns = entry.get("patterns", []) if isinstance(entry.get("patterns"), list) else []
        entry.update(
            {
                "name": str(entry.get("name") or name).strip(),
                "aliases": unique_text_values([*existing_aliases, *merged_aliases]),
                "patterns": unique_text_values([*existing_patterns, *merged_patterns]),
                "target": target,
                "source": source.strip() or entry.get("source") or "operator",
                "updated_at": now,
            }
        )
        if note:
            entry["note"] = note.strip()

    validation = validate_rules(rules)
    if not validation.ok:
        messages = "; ".join(f"{item['path']}: {item['message']}" for item in validation.errors)
        raise FinanceRulesError(f"Updated finance rules would be invalid: {messages}")

    write_json_file(path, rules)
    selected = entries[selected_index]
    return {
        "ok": True,
        "mode": mode,
        "rules": str(path),
        "kind": kind,
        "index": selected_index,
        "mapping": selected,
        "warnings": validation.warnings,
    }


def parse_name(value: str, rules: dict[str, Any]) -> dict[str, Any]:
    for parser in rules.get("parsers", []) if isinstance(rules.get("parsers"), list) else []:
        if not isinstance(parser, dict):
            continue
        pattern = str(parser.get("pattern") or "")
        if not pattern:
            continue
        match = re.search(pattern, value)
        if not match:
            continue
        groups = {key: item for key, item in match.groupdict().items() if item is not None}
        return {
            "matched": True,
            "parser": parser.get("name"),
            "fields": groups,
            "normalized": {key: normalize_key(item) for key, item in groups.items()},
        }
    return {"matched": False, "parser": None, "fields": {}, "normalized": {}}


def resolve_mapping(kind: str, value: str, rules: dict[str, Any]) -> dict[str, Any]:
    if kind not in SUPPORTED_MAPPING_KINDS:
        raise FinanceRulesError(f"Unsupported mapping kind: {kind}")
    wanted = normalize_key(value)
    wanted_compact = compact_key(value)
    entries = rules.get("mappings", {}).get(kind, []) if isinstance(rules.get("mappings"), dict) else []
    for entry in entries if isinstance(entries, list) else []:
        if not isinstance(entry, dict):
            continue
        target = entry.get("target") if isinstance(entry.get("target"), dict) else {}
        for alias in entry.get("aliases", []) if isinstance(entry.get("aliases"), list) else []:
            if normalize_key(alias) == wanted or compact_key(alias) == wanted_compact:
                return {"matched": True, "kind": kind, "strategy": "alias", "source": value, "rule": entry.get("name"), "target": target}
        for pattern in entry.get("patterns", []) if isinstance(entry.get("patterns"), list) else []:
            if re.search(str(pattern), value, re.IGNORECASE):
                return {"matched": True, "kind": kind, "strategy": "pattern", "source": value, "rule": entry.get("name"), "target": target}
    return {"matched": False, "kind": kind, "source": value, "target": None}


def load_snapshot_records(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    payload = load_json_file(path)
    if isinstance(payload, list):
        records = payload
    elif isinstance(payload, dict):
        for key in ("records", "items", "invoices", "bills", "payments", "bank_transactions"):
            if isinstance(payload.get(key), list):
                records = payload[key]
                break
        else:
            records = []
    else:
        records = []
    return [item for item in records if isinstance(item, dict)]


def candidate_type(candidate: dict[str, Any]) -> str:
    return normalize_key(candidate.get("type") or candidate.get("object_type") or "invoice").replace(" ", "_")


def snapshot_file_for_type(root: Path, object_type: str) -> Path:
    aliases = {
        "invoice": "invoices.json",
        "bill": "bills.json",
        "payment": "payments.json",
        "bank_transaction": "bank_transactions.json",
    }
    return root / aliases.get(object_type, f"{object_type}s.json")


def first_value(payload: dict[str, Any], *keys: str) -> Any:
    for key in keys:
        if key in payload and payload[key] not in (None, ""):
            return payload[key]
        upper = key[:1].upper() + key[1:]
        if upper in payload and payload[upper] not in (None, ""):
            return payload[upper]
    return None


def record_reference(record: dict[str, Any]) -> str:
    return normalize_key(first_value(record, "reference", "invoiceNumber", "invoice_number", "Reference", "InvoiceNumber"))


def record_contact(record: dict[str, Any]) -> str:
    contact = first_value(record, "contact", "contactName", "contact_name", "Contact")
    if isinstance(contact, dict):
        contact = first_value(contact, "name", "Name")
    return normalize_key(contact)


def record_date(record: dict[str, Any]) -> str:
    return normalize_key(first_value(record, "date", "invoiceDate", "invoice_date", "Date"))


def record_amount(record: dict[str, Any]) -> float | None:
    return parse_money(first_value(record, "total", "amount", "Total", "Amount"))


def find_duplicate_matches(candidate: dict[str, Any], records: list[dict[str, Any]], fields: list[str]) -> list[dict[str, Any]]:
    matches: list[dict[str, Any]] = []
    candidate_values = {
        "reference": record_reference(candidate),
        "contact": record_contact(candidate),
        "date": record_date(candidate),
        "total": record_amount(candidate),
        "amount": record_amount(candidate),
    }
    for record in records:
        record_values = {
            "reference": record_reference(record),
            "contact": record_contact(record),
            "date": record_date(record),
            "total": record_amount(record),
            "amount": record_amount(record),
        }
        compared: dict[str, Any] = {}
        matched_all = True
        for field in fields:
            left = candidate_values.get(field)
            right = record_values.get(field)
            compared[field] = {"candidate": left, "snapshot": right}
            if left in (None, "") or right in (None, "") or left != right:
                matched_all = False
                break
        if matched_all:
            matches.append(
                {
                    "id": first_value(record, "id", "invoiceID", "InvoiceID", "paymentID", "PaymentID", "bankTransactionID", "BankTransactionID"),
                    "reference": first_value(record, "reference", "Reference", "invoiceNumber", "InvoiceNumber"),
                    "compared": compared,
                }
            )
    return matches


def candidate_mapping_inputs(candidate: dict[str, Any]) -> dict[str, str]:
    inputs: dict[str, str] = {}
    for kind, keys in {
        "contact": ("contact", "contactName", "contact_name"),
        "account": ("account", "accountCode", "account_code", "accountName", "account_name"),
        "tax": ("tax", "taxType", "tax_type", "taxRate", "tax_rate"),
        "item": ("item", "itemCode", "item_code", "description"),
    }.items():
        value = first_value(candidate, *keys)
        if value not in (None, ""):
            inputs[kind] = str(value)
    return inputs


def mapping_target_template(kind: str) -> dict[str, str]:
    templates = {
        "account": {"code": "<reviewed Xero account code>"},
        "contact": {"name": "<reviewed Xero contact name>"},
        "item": {"code": "<reviewed Xero item code>"},
        "tax": {"tax_type": "<reviewed Xero tax type>"},
    }
    return templates.get(kind, {"value": "<reviewed Xero target>"})


def mapping_suggestion_name(kind: str, source: Any) -> str:
    seed = compact_key(source)[:48] or "mapping"
    return f"{kind}-{seed}"


def build_mapping_suggestions(missing_mappings: list[dict[str, Any]]) -> list[dict[str, Any]]:
    suggestions: dict[tuple[str, str], dict[str, Any]] = {}
    for missing in missing_mappings:
        kind = str(missing.get("kind") or "").strip()
        source = str(missing.get("source") or "").strip()
        if kind not in SUPPORTED_MAPPING_KINDS or not source:
            continue
        key = (kind, normalize_key(source))
        name = mapping_suggestion_name(kind, source)
        target_template = mapping_target_template(kind)
        suggestion = suggestions.setdefault(
            key,
            {
                "id": f"{kind}:{compact_key(source) or 'mapping'}",
                "kind": kind,
                "source": source,
                "name": name,
                "aliases": [source],
                "patterns": [],
                "target_template": target_template,
                "requires_review": True,
                "candidate_indexes": [],
                "candidate_references": [],
                "upsert_command": [
                    "connectors/xero/cli/xero",
                    "rules",
                    "upsert-mapping",
                    kind,
                    "--name",
                    name,
                    "--alias",
                    source,
                    "--target-json",
                    json.dumps(target_template, separators=(",", ":")),
                ],
            },
        )
        candidate_index = missing.get("candidate_index")
        if isinstance(candidate_index, int) and candidate_index not in suggestion["candidate_indexes"]:
            suggestion["candidate_indexes"].append(candidate_index)
        candidate_reference = missing.get("candidate_reference")
        if candidate_reference and candidate_reference not in suggestion["candidate_references"]:
            suggestion["candidate_references"].append(candidate_reference)
    return sorted(suggestions.values(), key=lambda item: (item["kind"], item["source"].lower()))


def review_rules(rules: dict[str, Any]) -> set[str]:
    conventions = rules.get("conventions", {}) if isinstance(rules.get("conventions"), dict) else {}
    values = conventions.get("review_required", []) if isinstance(conventions.get("review_required"), list) else []
    return {str(value) for value in values if isinstance(value, str)}


def candidate_status(candidate: dict[str, Any]) -> str:
    return normalize_key(first_value(candidate, "status", "Status") or "").upper()


def convention_review_issues(candidate: dict[str, Any], object_type: str, rules: dict[str, Any]) -> list[dict[str, Any]]:
    required = review_rules(rules)
    issues: list[dict[str, Any]] = []
    conventions = rules.get("conventions", {}) if isinstance(rules.get("conventions"), dict) else {}
    defaults = conventions.get("document_defaults", {}) if isinstance(conventions.get("document_defaults"), dict) else {}
    reference = record_reference(candidate)
    amount = record_amount(candidate)
    if "missing_reference" in required and not reference:
        issues.append({"message": "candidate is missing a reference required by finance conventions", "rule": "missing_reference"})
    if "negative_total" in required and amount is not None and amount < 0:
        issues.append({"message": "candidate has a negative total requiring review", "rule": "negative_total", "amount": amount})
    if "non_draft_document_status" in required and object_type in DOCUMENT_STATUS_KEYS:
        expected = normalize_key(defaults.get(DOCUMENT_STATUS_KEYS[object_type]) or "DRAFT").upper()
        actual = candidate_status(candidate)
        if actual and expected and actual != expected:
            issues.append(
                {
                    "message": "candidate document status differs from draft-first convention",
                    "rule": "non_draft_document_status",
                    "status": actual,
                    "expected_status": expected,
                }
            )
    return issues


def build_batch_plan(results: list[dict[str, Any]], *, max_batch_size: int = DEFAULT_MAX_APPLY_BATCH_SIZE) -> dict[str, Any]:
    size = max(1, int(max_batch_size or DEFAULT_MAX_APPLY_BATCH_SIZE))
    ready_by_type: dict[str, list[dict[str, Any]]] = {}
    for result in results:
        if not isinstance(result, dict) or result.get("status") != "ready":
            continue
        object_type = str(result.get("type") or "unknown")
        ready_by_type.setdefault(object_type, []).append(result)

    groups: list[dict[str, Any]] = []
    total_batches = 0
    for object_type in sorted(ready_by_type):
        items = ready_by_type[object_type]
        batches: list[dict[str, Any]] = []
        for offset in range(0, len(items), size):
            chunk = items[offset : offset + size]
            batch_number = len(batches) + 1
            batches.append(
                {
                    "batch_id": f"{object_type}-{batch_number}",
                    "candidate_indexes": [int(item["index"]) for item in chunk if isinstance(item.get("index"), int)],
                    "references": [item.get("reference") for item in chunk if item.get("reference")],
                    "candidate_count": len(chunk),
                    "max_batch_size": size,
                    "requires_preflight_report": True,
                }
            )
        total_batches += len(batches)
        groups.append({"type": object_type, "ready_count": len(items), "batch_count": len(batches), "batches": batches})

    return {
        "ok": True,
        "max_batch_size": size,
        "ready_count": sum(len(items) for items in ready_by_type.values()),
        "batch_count": total_batches,
        "estimated_apply_api_calls": total_batches,
        "groups": groups,
        "rate_limit_notes": [
            "Apply batches are bounded before mutation; do not dispatch unbounded candidate lists.",
            "Run targeted live checks for each ready candidate or reviewed batch before apply.",
            "Each apply batch must keep the dry-run/audit report as preflight evidence.",
        ],
    }


def build_dry_run_report(
    candidates: list[dict[str, Any]],
    rules: dict[str, Any],
    snapshots: Path,
    *,
    max_batch_size: int = DEFAULT_MAX_APPLY_BATCH_SIZE,
) -> dict[str, Any]:
    validation = validate_rules(rules)
    if not validation.ok:
        raise FinanceRulesError("Finance rules failed validation; run `xero rules validate`.")
    results: list[dict[str, Any]] = []
    summary = {"candidate_count": len(candidates), "ready": 0, "review": 0, "blocked_duplicate": 0}
    dedup_rules = rules.get("dedup", {}) if isinstance(rules.get("dedup"), dict) else {}
    missing_mapping_events: list[dict[str, Any]] = []
    for index, candidate in enumerate(candidates):
        if not isinstance(candidate, dict):
            results.append({"index": index, "status": "review", "issues": [{"message": "candidate must be an object"}]})
            summary["review"] += 1
            continue
        object_type = candidate_type(candidate)
        fields = dedup_rules.get(object_type, {}).get("match_fields", ["reference"]) if isinstance(dedup_rules.get(object_type), dict) else ["reference"]
        records = load_snapshot_records(snapshot_file_for_type(snapshots, object_type))
        duplicates = find_duplicate_matches(candidate, records, [str(field) for field in fields])
        mappings = {
            kind: resolve_mapping(kind, value, rules)
            for kind, value in candidate_mapping_inputs(candidate).items()
            if kind in SUPPORTED_MAPPING_KINDS
        }
        missing_mappings = [
            {"kind": kind, "source": result.get("source")}
            for kind, result in mappings.items()
            if not result.get("matched") and f"unmapped_{kind}" in review_rules(rules)
        ]
        convention_issues = convention_review_issues(candidate, object_type, rules)
        targeted_checks = []
        reference = record_reference(candidate)
        for missing_mapping in missing_mappings:
            missing_mapping_events.append(
                {
                    **missing_mapping,
                    "candidate_index": index,
                    "candidate_type": object_type,
                    "candidate_reference": reference or None,
                }
            )
        if reference:
            targeted_checks.append({"kind": object_type, "method": "reference", "value": reference})
        status = "ready"
        issues: list[dict[str, Any]] = []
        if duplicates:
            status = "blocked_duplicate"
            issues.append({"message": "candidate matches existing snapshot record", "matches": duplicates})
        elif missing_mappings or convention_issues:
            status = "review"
            if missing_mappings:
                issues.append({"message": "candidate has unmapped finance-rule inputs", "missing_mappings": missing_mappings})
            issues.extend(convention_issues)
        summary[status] += 1
        results.append(
            {
                "index": index,
                "type": object_type,
                "reference": reference or None,
                "status": status,
                "duplicate_matches": duplicates,
                "duplicate_match_count": len(duplicates),
                "duplicate_ambiguous": len(duplicates) > 1,
                "mappings": mappings,
                "mapping_suggestion_refs": [
                    f"{missing['kind']}:{compact_key(missing.get('source')) or 'mapping'}" for missing in missing_mappings
                ],
                "targeted_checks": targeted_checks,
                "issues": issues,
            }
        )
    return {
        "ok": True,
        "generated_at": utc_seconds(),
        "snapshot_dir": str(snapshots),
        "summary": summary,
        "batch_plan": build_batch_plan(results, max_batch_size=max_batch_size),
        "mapping_suggestions": build_mapping_suggestions(missing_mapping_events),
        "candidates": results,
    }


def load_candidates(path: Path) -> list[dict[str, Any]]:
    payload = load_json_file(path)
    if isinstance(payload, list):
        return [item for item in payload if isinstance(item, dict)]
    if isinstance(payload, dict) and isinstance(payload.get("candidates"), list):
        return [item for item in payload["candidates"] if isinstance(item, dict)]
    raise FinanceRulesError("Candidate file must be a JSON array or an object with a candidates array.")


def normalize_apply_event(event: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(event, dict):
        raise FinanceRulesError("Apply event must be an object.")
    object_type = normalize_key(event.get("type") or event.get("object_type") or event.get("kind")).replace(" ", "_")
    action = normalize_key(event.get("action") or "unknown").replace(" ", "_")
    status = normalize_key(event.get("status") or "unknown").replace(" ", "_")
    if not object_type:
        raise FinanceRulesError("Apply event requires type/object_type/kind.")
    if not action:
        raise FinanceRulesError("Apply event requires action.")
    if not status:
        raise FinanceRulesError("Apply event requires status.")
    return {
        "type": object_type,
        "action": action,
        "status": status,
        "reference": first_value(event, "reference", "invoiceNumber", "invoice_number"),
        "xero_id": first_value(event, "xero_id", "xeroId", "invoiceID", "InvoiceID", "paymentID", "PaymentID", "bankTransactionID", "BankTransactionID"),
        "source_id": first_value(event, "source_id", "sourceId", "sourceRowId", "source_row_id"),
        "dry_run_id": first_value(event, "dry_run_id", "dryRunId"),
        "details": redact_payload(event.get("details") if isinstance(event.get("details"), dict) else {}),
    }


def build_apply_report(event: dict[str, Any], *, actor: str = "local-cli") -> dict[str, Any]:
    normalized = normalize_apply_event(event)
    report_id = f"apply_{int(time.time())}_{secrets.token_hex(6)}"
    return {
        "schema_version": 1,
        "report_id": report_id,
        "generated_at": utc_seconds(),
        "actor": actor,
        "result": normalized,
    }


def write_apply_report(root: Path, event: dict[str, Any], *, actor: str = "local-cli") -> dict[str, Any]:
    report = build_apply_report(event, actor=actor)
    day = time.strftime("%Y-%m-%d", time.gmtime(int(report["generated_at"])))
    report_path = root / "reports" / day / f"{report['report_id']}.json"
    write_json_file(report_path, report)
    ledger_entry = {
        "report_id": report["report_id"],
        "generated_at": report["generated_at"],
        "actor": report["actor"],
        **report["result"],
        "report_path": str(report_path),
    }
    append_jsonl(root / "apply-ledger.jsonl", ledger_entry)
    return {"ok": True, "audit_dir": str(root), "report": str(report_path), "entry": ledger_entry}


def list_apply_reports(root: Path, *, limit: int = 20) -> dict[str, Any]:
    ledger_path = root / "apply-ledger.jsonl"
    entries: list[dict[str, Any]] = []
    if ledger_path.exists():
        with ledger_path.open("r", encoding="utf-8") as handle:
            for line in handle:
                line = line.strip()
                if not line:
                    continue
                try:
                    payload = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if isinstance(payload, dict):
                    entries.append(payload)
    selected = entries[-max(0, limit) :] if limit else entries
    summary: dict[str, int] = {}
    for entry in entries:
        key = str(entry.get("status") or "unknown")
        summary[key] = summary.get(key, 0) + 1
    return {
        "ok": True,
        "audit_dir": str(root),
        "ledger": str(ledger_path),
        "total_count": len(entries),
        "summary": summary,
        "entries": selected,
    }
