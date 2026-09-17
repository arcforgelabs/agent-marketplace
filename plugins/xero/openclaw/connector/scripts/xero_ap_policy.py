#!/usr/bin/env python3
"""Accounts-payable policy engine for the Arc Forge Xero connector (Phase 2+).

An org's AP behaviour — approval thresholds, default tax treatment, and the BAS
frozen-period boundary — is data, not code. It lives in the org's *profile pack*
(``ap-policy.json``) in the private finances repo; the connector ships only a
template. This module loads and validates that policy and derives the two things
the bill lifecycle needs deterministically:

* the **due date** for a bill, from Xero-native payment terms (contact → org
  default → built-in net-14), because the Accounting API does NOT default DueDate
  from a contact's terms automatically; and
* the **approval decision** for a bill amount (auto-approve below a threshold,
  else route to a named human), plus whether evidence is required.

Schema version 2 (current): payment terms are sourced from Xero itself —
supplier contact PaymentTerms → org-default PaymentTerms → built-in net-14.
The ``payment_terms`` block is deprecated; it still loads with a warning so
existing v1 policy files keep working during transition.

Frozen-period enforcement uses Xero's PeriodLockDate/EndOfYearLockDate (from the
org snapshot) as the source of truth; ``frozen_before`` in the policy is a
fallback for orgs with no lock date configured.

Pure and dependency-free (stdlib only) so it is trivially unit-tested without a
live Xero connection.
"""

from __future__ import annotations

import calendar
import datetime
import json
import sys
import warnings
from pathlib import Path
from typing import Any


class APPolicyError(RuntimeError):
    """User-facing AP-policy error."""


# Xero PaymentTerms.Type values we support, mirrored so a pack's terms map
# cleanly onto a Contact's PaymentTerms if pushed there later.
TERM_TYPES = {
    "DAYSAFTERBILLDATE",     # net N days from the bill date
    "DAYSAFTERBILLMONTH",    # N days after the end of the bill's month
    "OFCURRENTMONTH",        # the Nth day of the bill's month
    "OFFOLLOWINGMONTH",      # the Nth day of the month after the bill's month
}

DEFAULT_TERMS = {"type": "DAYSAFTERBILLDATE", "day": 14}


def parse_iso_date(value: str) -> datetime.date:
    raw = str(value or "").strip()[:10]
    try:
        return datetime.date.fromisoformat(raw)
    except ValueError as exc:
        raise APPolicyError(f"invalid ISO date {value!r}: expected YYYY-MM-DD") from exc


def _clamp_day(year: int, month: int, day: int) -> datetime.date:
    last = calendar.monthrange(year, month)[1]
    return datetime.date(year, month, min(max(1, day), last))


def compute_due_date(bill_date: str, terms: dict[str, Any]) -> str:
    """Return the ISO due date for a bill given Xero-style payment terms."""
    if not isinstance(terms, dict):
        raise APPolicyError("payment terms must be an object with 'type' and 'day'")
    term_type = str(terms.get("type") or "").strip().upper()
    if term_type not in TERM_TYPES:
        raise APPolicyError(f"unsupported payment term type {term_type!r}; allowed: {', '.join(sorted(TERM_TYPES))}")
    try:
        day = int(terms.get("day"))
    except (TypeError, ValueError) as exc:
        raise APPolicyError(f"payment term 'day' must be an integer, got {terms.get('day')!r}") from exc
    if day < 0:
        raise APPolicyError("payment term 'day' must not be negative")
    base = parse_iso_date(bill_date)
    if term_type == "DAYSAFTERBILLDATE":
        return (base + datetime.timedelta(days=day)).isoformat()
    if term_type == "DAYSAFTERBILLMONTH":
        last = _clamp_day(base.year, base.month, 31)  # end of bill month
        return (last + datetime.timedelta(days=day)).isoformat()
    if term_type == "OFCURRENTMONTH":
        return _clamp_day(base.year, base.month, day).isoformat()
    # OFFOLLOWINGMONTH
    year = base.year + (1 if base.month == 12 else 0)
    month = 1 if base.month == 12 else base.month + 1
    return _clamp_day(year, month, day).isoformat()


def load_ap_policy(path: str | Path) -> dict[str, Any]:
    resolved = Path(path).expanduser().resolve()
    if not resolved.is_file():
        raise APPolicyError(f"ap-policy file not found: {resolved}")
    try:
        data = json.loads(resolved.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise APPolicyError(f"ap-policy {resolved} is not valid JSON: {exc}") from exc
    if not isinstance(data, dict):
        raise APPolicyError("ap-policy must be a JSON object")
    validate_ap_policy(data)
    return data


def validate_ap_policy(policy: dict[str, Any]) -> None:
    """Validate the policy dict in place.

    Schema v2: ``payment_terms`` is deprecated — Xero contact/org terms are the
    source of truth. A v1 file with ``payment_terms`` still loads but emits a
    deprecation warning to stderr. ``approval``, ``tax_defaults``, and
    ``frozen_before`` (fallback) are unchanged.
    """
    terms = policy.get("payment_terms")
    if terms is not None:
        # Deprecated in schema v2 — warn but do NOT error (backward compat).
        warnings.warn(
            "ap-policy: 'payment_terms' is deprecated in schema v2. "
            "Payment terms are now sourced from Xero contact/org settings. "
            "Remove this block and set schema_version to 2 to suppress this warning.",
            DeprecationWarning,
            stacklevel=3,
        )
        print(
            "WARNING: ap-policy 'payment_terms' is deprecated (schema v2); "
            "Xero contact/org terms are now the source of truth. "
            "Remove this block and set schema_version to 2.",
            file=sys.stderr,
        )
        if not isinstance(terms, dict):
            raise APPolicyError("payment_terms must be an object")
        default = terms.get("default")
        if default is not None:
            compute_due_date("2000-01-01", default)  # validates type/day
        by_supplier = terms.get("by_supplier", {})
        if by_supplier and not isinstance(by_supplier, dict):
            raise APPolicyError("payment_terms.by_supplier must be an object")
        for supplier, supplier_terms in (by_supplier or {}).items():
            try:
                compute_due_date("2000-01-01", supplier_terms)
            except APPolicyError as exc:
                raise APPolicyError(f"payment_terms.by_supplier[{supplier!r}]: {exc}") from exc
    approval = policy.get("approval")
    if approval is not None:
        if not isinstance(approval, dict):
            raise APPolicyError("approval must be an object")
        threshold = approval.get("auto_approve_below")
        if threshold is not None and not isinstance(threshold, (int, float)):
            raise APPolicyError("approval.auto_approve_below must be a number")
    frozen = policy.get("frozen_before")
    if frozen is not None:
        parse_iso_date(frozen)


def _xero_payment_terms_to_terms(raw: dict[str, Any] | None) -> dict[str, Any] | None:
    """Map a Xero PaymentTerms payload to our ``{type, day}`` terms, or None.

    Accepts either the full ``{"Bills": {"Day": N, "Type": "..."}}`` shape or a
    bare ``{"Day": N, "Type": "..."}``. Returns None (so the caller falls through
    to the next precedence tier) when the payload is absent, the Type is not a
    supported TERM_TYPE, the Day is missing, or the Day is non-numeric.
    """
    if not isinstance(raw, dict):
        return None
    bills = raw.get("Bills") if isinstance(raw.get("Bills"), dict) else raw
    day = bills.get("Day")
    term_type = str(bills.get("Type") or "").strip().upper()
    if term_type not in TERM_TYPES or day is None:
        return None
    try:
        day_int = int(day)
    except (TypeError, ValueError):
        return None  # malformed snapshot data → fall through to next tier
    return {"type": term_type, "day": day_int}


def resolve_terms(
    policy: dict[str, Any],
    supplier: str | None = None,
    *,
    contact_terms: dict[str, Any] | None = None,
    org_default_terms: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Resolve payment terms: contact → org-default → policy fallback → built-in net-14.

    Precedence (highest to lowest):
    1. ``contact_terms`` — the supplier's Xero contact PaymentTerms (bills side),
       as fetched from the full Contacts API. Pass in from the live command layer;
       do NOT fetch here (this function is pure).
    2. ``org_default_terms`` — the org-level PaymentTerms.Bills from the
       Organisation endpoint. Pass in from the live command layer.
    3. Legacy ``payment_terms.by_supplier[supplier]`` in the policy — deprecated
       v1 fallback, kept so existing policy files keep working.
    4. Legacy ``payment_terms.default`` in the policy — deprecated v1 fallback.
    5. Built-in net-14 (``DEFAULT_TERMS``).

    PURE FUNCTION — all data is passed in; no I/O here.
    """
    # 1. Contact-level Xero terms (caller supplies the contact's PaymentTerms).
    contact_resolved = _xero_payment_terms_to_terms(contact_terms)
    if contact_resolved is not None:
        return contact_resolved

    # 2. Org-level default PaymentTerms (caller supplies).
    org_resolved = _xero_payment_terms_to_terms(org_default_terms)
    if org_resolved is not None:
        return org_resolved

    # 3-4. Legacy policy payment_terms block (deprecated v1 fallback).
    terms = policy.get("payment_terms") if isinstance(policy.get("payment_terms"), dict) else {}
    by_supplier = terms.get("by_supplier") if isinstance(terms.get("by_supplier"), dict) else {}
    if supplier and supplier in by_supplier:
        return by_supplier[supplier]
    if isinstance(terms.get("default"), dict):
        return terms["default"]

    # 5. Built-in net-14.
    return dict(DEFAULT_TERMS)


def approval_decision(policy: dict[str, Any], amount: float) -> dict[str, Any]:
    """Decide whether a bill auto-approves or needs a named human approver."""
    approval = policy.get("approval") if isinstance(policy.get("approval"), dict) else {}
    threshold = approval.get("auto_approve_below")
    require_attachment = bool(approval.get("require_attachment", True))
    approver = approval.get("approver")
    try:
        magnitude = abs(float(amount))
    except (TypeError, ValueError):
        magnitude = None
    auto = bool(threshold is not None and magnitude is not None and magnitude < float(threshold))
    return {
        "auto_approve": auto,
        "threshold": threshold,
        "approver": approver,
        "require_attachment": require_attachment,
        "amount": amount,
    }


def effective_frozen_before(
    policy: dict[str, Any],
    lock_date: str | None = None,
) -> str | None:
    """Return the effective EXCLUSIVE frozen-before boundary, or None if not set.

    The returned value is always an exclusive upper bound: a date is frozen iff
    ``date < boundary``. Callers therefore use a single ``<`` comparison
    regardless of source.

    The boundary is the **most-locking** of the two candidate bounds — the guard
    must never silently loosen when both signals are present:
    1. ``lock_date`` — Xero PeriodLockDate / EndOfYearLockDate (caller resolves
       which to use). Xero lock dates are **INCLUSIVE**: transactions dated ON OR
       BEFORE the lock date are locked. To express that as an exclusive bound the
       candidate is ``lock_date + 1 day`` (so ``date < lock+1`` ⇔ ``date <= lock``).
    2. ``policy['frozen_before']`` — already **EXCLUSIVE** by definition
       ("frozen *before* X"), so its candidate is the value as-is.

    Returns ``max(candidates)`` (the later boundary freezes more). If only one is
    set, returns it. If neither, returns None.

    Pure function: do NOT fetch here; pass the lock date in from the live layer.
    The guard NEVER silently disappears: if neither is set, returns None so
    callers treat the period as unfrozen consistently.
    """
    candidates: list[str] = []
    if lock_date and str(lock_date).strip():
        lock = parse_iso_date(str(lock_date).strip()[:10])
        # Inclusive lock date → exclusive bound is the day after.
        candidates.append((lock + datetime.timedelta(days=1)).isoformat())
    fallback = policy.get("frozen_before")
    if fallback and str(fallback).strip():
        candidates.append(str(fallback).strip()[:10])  # already exclusive
    if not candidates:
        return None
    # ISO YYYY-MM-DD sorts lexicographically == chronologically; later == more-locking.
    return max(candidates)


def is_frozen(
    policy: dict[str, Any],
    bill_date: str,
    *,
    lock_date: str | None = None,
) -> bool:
    """True if the bill date falls in a BAS-lodged (frozen) period.

    Uses the Xero lock date (``lock_date`` arg) as the authoritative source;
    falls back to ``policy['frozen_before']`` ONLY when no lock date is set.
    Returns False (not frozen) when neither is configured.

    Semantics (handled in effective_frozen_before): a Xero lock date is
    INCLUSIVE (a bill dated ON the lock date IS frozen); a policy frozen_before
    is EXCLUSIVE (a bill dated ON it is NOT frozen).

    PURE FUNCTION — pass the effective lock date in from the live layer.
    """
    boundary = effective_frozen_before(policy, lock_date=lock_date)
    if not boundary:
        return False
    return parse_iso_date(bill_date) < parse_iso_date(boundary)
