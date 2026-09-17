#!/usr/bin/env python3
"""Phase 5 — Payroll/super prepare+verify skeleton for the Arc Forge Xero connector.

## Platform boundary — read before extending this module (§5 of the design doc)

The AU Payroll API (``xero-payroll-au.yaml``, verified 2026-06-10) can:
  * Create/update Employees, PayItems, PayrollCalendars, **PayRuns**, Payslips,
    Timesheets, Superfund *registration records* (fund details, not money).

The AU Payroll API CANNOT:
  * Execute super payments — no endpoint exists for creating, submitting, or
    approving auto-super batches.  The flow is UI-only: create the batch in
    Payroll → Superannuation, then a **nominated human authoriser approves via
    SMS code** (24 h validity, SuperChoice clearing house, 4–7 business days).
    Automating the SMS step would violate the connector's no-MFA-automation
    policy and almost certainly Xero's terms.
  * Lodge STP — STP filing happens when a human files the pay run in the UI;
    the API can *prepare* the pay run but cannot lodge it.

**This module implements only the PURE, testable parts**: the payday-super
compliance calendar and SG accrual maths.  The CLI skeletons in ``xero_core.py``
(``xero payroll prepare-payrun`` and ``xero payroll verify``) call these helpers
and then clearly state the human steps required.

## Payday Super (effective 1 July 2026)

From 2026-07-01, employers must pay the SG super contribution alongside each
payday (instead of quarterly).  Any org hiring from that date needs the
per-payday loop from day one.  Sole traders (Arc Forge today) have no SG
obligation to themselves; this module is dormant unless an employee is present.

Reference: ATO — <https://www.ato.gov.au/individuals-and-families/super-for-individuals-and-families/super/growing-and-keeping-track-of-your-super/payday-super>
Xero FAQ: <https://www.xero.com/au/campaign/payday-super-faqs/>

## SG rate

The SG rate changes annually.  This module defaults to ``SG_RATE_DEFAULT`` but
requires the caller to pass the current rate explicitly so the tool never
silently uses a stale value.  Verify the current rate at:
  https://www.ato.gov.au/individuals-and-families/super-for-individuals-and-families/super/growing-and-keeping-track-of-your-super/how-much-super-to-pay/super-guarantee-percentage
"""

from __future__ import annotations

import datetime
from typing import Any


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------


class PayrollError(RuntimeError):
    """User-facing payroll/super error."""


# ---------------------------------------------------------------------------
# SG rate
# ---------------------------------------------------------------------------

# DEFAULT value — verify before use.  The SG rate increases each financial year;
# this constant may be stale by the time you read it.  Always pass
# ``sg_rate=<current>`` explicitly rather than relying on this default.
#
# Historical schedule (source: ATO, verified 2026-06-10):
#   FY2022-23: 10.5%
#   FY2023-24: 11.0%
#   FY2024-25: 11.5%
#   FY2025-26: 12.0%  ← verify this is still current at ato.gov.au
#   FY2026-27+: 12.0% (legislated; confirm once ATO publishes the FY27 rate)
SG_RATE_DEFAULT: float = 0.12  # 12% — VERIFY at ato.gov.au before relying on this

SG_RATE_VERIFY_URL = (
    "https://www.ato.gov.au/individuals-and-families/super-for-individuals-and-families/"
    "super/growing-and-keeping-track-of-your-super/how-much-super-to-pay/super-guarantee-percentage"
)

PAYDAY_SUPER_CUTOVER = datetime.date(2026, 7, 1)


# ---------------------------------------------------------------------------
# Payday-super compliance calendar
# ---------------------------------------------------------------------------


def sg_due_cadence(pay_date: str | datetime.date) -> str:
    """Return the SG contribution cadence for a given pay date.

    Before 2026-07-01: SG is due quarterly (28 days after each quarter end).
    From 2026-07-01:   SG is due per-payday (alongside each pay run).

    Returns either ``"quarterly"`` or ``"per-payday"``.
    """
    if isinstance(pay_date, str):
        try:
            parsed = datetime.date.fromisoformat(pay_date.strip()[:10])
        except ValueError as exc:
            raise PayrollError(f"invalid pay_date {pay_date!r}: expected YYYY-MM-DD") from exc
    else:
        parsed = pay_date
    return "per-payday" if parsed >= PAYDAY_SUPER_CUTOVER else "quarterly"


def quarterly_sg_due_date(pay_date: str | datetime.date) -> str | None:
    """Return the SG payment due date for a quarterly-regime pay date.

    Returns None if the pay date falls under per-payday super (>= 2026-07-01),
    since the due date in that regime is the pay date itself.

    Australian SG quarter end dates and payment deadlines (28 days after quarter end):
      Q1 (1 Jul – 30 Sep): due 28 Oct
      Q2 (1 Oct – 31 Dec): due 28 Jan
      Q3 (1 Jan – 31 Mar): due 28 Apr
      Q4 (1 Apr – 30 Jun): due 28 Jul
    """
    if isinstance(pay_date, str):
        try:
            parsed = datetime.date.fromisoformat(pay_date.strip()[:10])
        except ValueError as exc:
            raise PayrollError(f"invalid pay_date {pay_date!r}: expected YYYY-MM-DD") from exc
    else:
        parsed = pay_date

    if parsed >= PAYDAY_SUPER_CUTOVER:
        return None  # per-payday regime; due date = pay date

    month = parsed.month
    year = parsed.year

    # Determine quarter end and due date.
    if 1 <= month <= 3:      # Q3: Jan–Mar, due 28 Apr
        due = datetime.date(year, 4, 28)
    elif 4 <= month <= 6:    # Q4: Apr–Jun, due 28 Jul
        due = datetime.date(year, 7, 28)
    elif 7 <= month <= 9:    # Q1: Jul–Sep, due 28 Oct
        due = datetime.date(year, 10, 28)
    else:                    # Q2: Oct–Dec, due 28 Jan next year
        due = datetime.date(year + 1, 1, 28)

    return due.isoformat()


def sg_due_date(pay_date: str | datetime.date) -> str:
    """Return the SG contribution due date for a given pay date as ISO string.

    For quarterly cadence, returns the quarter-end + 28-day deadline.
    For per-payday cadence (>= 2026-07-01), returns the pay date itself.
    """
    cadence = sg_due_cadence(pay_date)
    if cadence == "per-payday":
        if isinstance(pay_date, str):
            return pay_date.strip()[:10]
        return pay_date.isoformat()
    due = quarterly_sg_due_date(pay_date)
    assert due is not None  # only None in per-payday regime, which is handled above
    return due


# ---------------------------------------------------------------------------
# SG accrual maths
# ---------------------------------------------------------------------------


def compute_sg_accrual(
    ordinary_earnings: float,
    *,
    sg_rate: float = SG_RATE_DEFAULT,
    verify_rate: bool = True,
) -> dict[str, Any]:
    """Compute the SG contribution for a given ordinary-earnings amount.

    Args:
        ordinary_earnings: Gross ordinary-time earnings for the period (pre-tax).
        sg_rate: Current SG rate as a decimal fraction (e.g. 0.12 for 12%).
            Always pass this explicitly; the default may be stale.
        verify_rate: When True (default), include a ``rate_verification_required``
            flag and the ATO URL in the output so callers cannot miss the
            requirement to verify the rate before using the result.

    Returns:
        Dict with ``sg_amount``, ``sg_rate``, ``ordinary_earnings``, and audit
        metadata.

    The result is advisory only.  A registered tax agent or payroll specialist
    must confirm the rate and the definition of ordinary-time earnings for the
    org's specific pay items.
    """
    if not isinstance(ordinary_earnings, (int, float)):
        raise PayrollError(
            f"ordinary_earnings must be a number, got {ordinary_earnings!r}"
        )
    if not isinstance(sg_rate, (int, float)) or sg_rate <= 0 or sg_rate > 1:
        raise PayrollError(
            f"sg_rate must be a positive decimal fraction (e.g. 0.12 for 12%), got {sg_rate!r}"
        )
    sg_amount = round(float(ordinary_earnings) * float(sg_rate), 2)
    result: dict[str, Any] = {
        "sg_amount": sg_amount,
        "sg_rate": sg_rate,
        "sg_rate_pct": round(sg_rate * 100, 2),
        "ordinary_earnings": round(float(ordinary_earnings), 2),
        "advisory_only": True,
        "advisory_note": (
            "SG amount is computed from ordinary-time earnings × sg_rate. "
            "A registered tax agent must confirm the rate and OTE definition."
        ),
    }
    if verify_rate:
        result["rate_verification_required"] = True
        result["rate_verify_url"] = SG_RATE_VERIFY_URL
    return result


# ---------------------------------------------------------------------------
# Payroll scopes checker (read-only — no OAuth, no network)
# ---------------------------------------------------------------------------

# AU Payroll API scopes required for pay-run operations.  These are NOT in the
# DEFAULT_SCOPE in xero_core.py (deliberate — adding them requires the human to
# re-consent in the browser; do not add them there without explicit approval).
REQUIRED_PAYROLL_SCOPES: frozenset[str] = frozenset(
    [
        "payroll.employees",
        "payroll.payruns",
        "payroll.timesheets",
        "payroll.settings",
    ]
)


# Read-only payroll scopes — a subset of the write scopes above.
# Xero issues these as separate OAuth scope strings when the operator
# requests read-only payroll consent.  A token that has the WRITE scope
# (e.g. ``payroll.employees``) implicitly has read access too; the gate
# below accepts either.
#
# Scope string references (Xero OAuth 2.0 scopes, verified via the Xero
# developer documentation at https://developer.xero.com/documentation/
# guides/oauth2/scopes/ and the AU Payroll OpenAPI spec fetched 2026-06-10):
#   payroll.employees.read  — read Employee records
#   payroll.payruns.read    — read PayRuns and Payslips
#   (payslips are sub-resources of PayRuns and share the payruns scope)
REQUIRED_PAYROLL_READ_SCOPES: frozenset[str] = frozenset(
    [
        "payroll.employees.read",
        "payroll.payruns.read",
    ]
)


def check_payroll_read_scopes(
    granted_scopes: str | list[str],
    required: "frozenset[str] | set[str] | None" = None,
) -> dict[str, Any]:
    """Check whether the required payroll READ scopes have been granted.

    Accepts either the dedicated read scopes (``payroll.employees.read``,
    ``payroll.payruns.read``) OR the corresponding write scopes
    (``payroll.employees``, ``payroll.payruns``), since granting write implies
    read access.

    Args:
        granted_scopes: Space-separated scope string or a list of scope strings.

    Returns:
        Dict with ``scopes_ok``, ``missing``, ``granted``, and instructions
        for requesting consent if scopes are missing.

    This is a pure string-set comparison — no network call.
    """
    if isinstance(granted_scopes, str):
        granted = frozenset(granted_scopes.split())
    else:
        granted = frozenset(granted_scopes)

    # Which read scopes this check requires (per-command; default = the full set).
    req = frozenset(required) if required is not None else REQUIRED_PAYROLL_READ_SCOPES
    # Each read scope is satisfied by its read variant OR its write variant.
    _READ_TO_WRITE: dict[str, str] = {
        "payroll.employees.read": "payroll.employees",
        "payroll.payruns.read": "payroll.payruns",
        "payroll.payslip.read": "payroll.payslip",
        "payroll.settings.read": "payroll.settings",
        "payroll.timesheets.read": "payroll.timesheets",
    }
    missing = frozenset(
        read_scope
        for read_scope in req
        if read_scope not in granted and _READ_TO_WRITE.get(read_scope, read_scope) not in granted
    )
    satisfied = req - missing
    return {
        "scopes_ok": not missing,
        "missing": sorted(missing),
        "granted": sorted(satisfied),
        "required": sorted(req),
        "note": (
            "Write scopes (payroll.employees, payroll.payruns) are accepted in place of "
            "the read-only variants."
        ),
        "consent_instructions": (
            "Payroll read scopes are not granted. To enable payroll read commands:\n"
            "  1. Re-run `xero auth login` with payroll.employees.read and\n"
            "     payroll.payruns.read (or their write equivalents) added to the\n"
            "     Xero OAuth app's allowed scopes.\n"
            "  2. Complete the Xero browser login + consent flow.\n"
            "  NOTE: Do not add payroll scopes to DEFAULT_SCOPE in xero_core.py without\n"
            "        human review — the change requires all connected orgs to re-consent."
        )
        if missing
        else None,
    }


def check_payroll_scopes(granted_scopes: str | list[str]) -> dict[str, Any]:
    """Check whether the required payroll scopes have been granted.

    Args:
        granted_scopes: Space-separated scope string or a list of scope strings.

    Returns:
        Dict with ``scopes_ok``, ``missing``, ``granted``, and instructions
        for requesting consent if scopes are missing.

    This is a pure string-set comparison — no network call.
    """
    if isinstance(granted_scopes, str):
        granted = frozenset(granted_scopes.split())
    else:
        granted = frozenset(granted_scopes)

    missing = REQUIRED_PAYROLL_SCOPES - granted
    return {
        "scopes_ok": not missing,
        "missing": sorted(missing),
        "granted": sorted(granted & REQUIRED_PAYROLL_SCOPES),
        "required": sorted(REQUIRED_PAYROLL_SCOPES),
        "consent_instructions": (
            "Payroll scopes are not granted. To enable payroll commands:\n"
            "  1. Re-run `xero auth login` with the additional scopes added to the\n"
            "     Xero OAuth app's allowed scopes.\n"
            "  2. Complete the Xero browser login + consent flow.\n"
            "  NOTE: Do not add payroll scopes to DEFAULT_SCOPE in xero_core.py without\n"
            "        human review — the change requires all connected orgs to re-consent."
        )
        if missing
        else None,
    }


# ---------------------------------------------------------------------------
# Pay-run preflight summary (pure — no network)
# ---------------------------------------------------------------------------


def payrun_preflight_summary(
    *,
    pay_date: str,
    employees: list[dict[str, Any]],
    sg_rate: float = SG_RATE_DEFAULT,
) -> dict[str, Any]:
    """Compute a dry-run summary for a pay run (no network, no mutation).

    Args:
        pay_date: Pay date as YYYY-MM-DD.
        employees: List of employee pay-period records, each with at minimum:
            ``employee_id``, ``name``, ``ordinary_earnings``.
            Optional: ``super_fund_usi``.
        sg_rate: Current SG rate (decimal fraction).

    Returns:
        A read-only summary dict with per-employee SG accruals, total payroll,
        total SG, the SG cadence, and the SG due date.
    """
    cadence = sg_due_cadence(pay_date)
    due_date = sg_due_date(pay_date)

    employee_rows: list[dict[str, Any]] = []
    total_gross = 0.0
    total_sg = 0.0

    for emp in employees:
        emp_id = str(emp.get("employee_id") or "").strip()
        name = str(emp.get("name") or emp_id or "").strip()
        earnings_raw = emp.get("ordinary_earnings")
        if earnings_raw is None:
            raise PayrollError(
                f"employee {name!r}: 'ordinary_earnings' is required"
            )
        try:
            earnings = round(float(earnings_raw), 2)
        except (TypeError, ValueError) as exc:
            raise PayrollError(
                f"employee {name!r}: 'ordinary_earnings' must be a number"
            ) from exc

        sg_info = compute_sg_accrual(earnings, sg_rate=sg_rate, verify_rate=False)
        total_gross += earnings
        total_sg += sg_info["sg_amount"]

        employee_rows.append(
            {
                "employee_id": emp_id,
                "name": name,
                "ordinary_earnings": earnings,
                "sg_amount": sg_info["sg_amount"],
                "super_fund_usi": emp.get("super_fund_usi"),
            }
        )

    return {
        "ok": True,
        "mode": "dry-run",
        "pay_date": pay_date,
        "sg_cadence": cadence,
        "sg_due_date": due_date,
        "sg_rate": sg_rate,
        "sg_rate_pct": round(sg_rate * 100, 2),
        "employee_count": len(employee_rows),
        "total_gross_ordinary_earnings": round(total_gross, 2),
        "total_sg_accrual": round(total_sg, 2),
        "employees": employee_rows,
        "rate_verification_required": True,
        "rate_verify_url": SG_RATE_VERIFY_URL,
        "honesty_notice": (
            "IMPORTANT — platform limits:\n"
            "  • This is a read-only dry-run. No pay run has been created or filed.\n"
            "  • STP lodgment: a human must file the pay run in the Xero UI.\n"
            "  • Super payment: a human must approve the auto-super batch in the Xero UI\n"
            "    (SMS authorisation required; SuperChoice clearing house; 4–7 business days).\n"
            "  • The API cannot execute super payments, auto-super batches, or STP lodgment.\n"
            "  • Sole-trader orgs (no employees) have no SG obligation."
        ),
    }


# ---------------------------------------------------------------------------
# AU Payroll API read functions (network — callers supply auth payload)
# ---------------------------------------------------------------------------
# These functions use the AU Payroll REST API at:
#   https://api.xero.com/payroll.xro/1.0
#
# Resource paths (verified against the official Xero OpenAPI spec
# xero-payroll-au.yaml, re-verified 2026-06-11):
#   PayRuns list   → GET /PayRuns        (root key "PayRuns"; params: where, order, page;
#                                          header If-Modified-Since; NO fromDate/toDate)
#   PayRun detail  → GET /PayRuns/{PayRunID}   (root key "PayRuns"[0]; embeds a "Payslips"
#                                          summary array — there is NO /PayRuns/{id}/Payslips
#                                          sub-endpoint)
#   Single Payslip → GET /Payslip/{PayslipID}  (SINGULAR path; root key "Payslip" object;
#                                          has top-level "Wages" gross + "EarningsLines")
#   PayTemplate    → GET /Employees/{EmployeeID}  (root key "Employees"[0]; "PayTemplate"
#                                          is a NESTED field — NOT a /PayTemplate sub-path)
#
# Callers pass a token ``payload`` dict and a ``tenant_id``; these functions
# do NOT refresh tokens or touch the token store — that is the caller's job.
# They reuse ``http_get_json`` and ``accounting_headers`` from xero_core (which
# simply builds Bearer + xero-tenant-id headers; the name is a historical
# artefact and works for any Xero API, not just accounting).


def _payroll_url(path: str) -> str:
    """Build a full AU Payroll API URL for the given resource path (no leading slash needed)."""
    # Import lazily to avoid a circular import; xero_payroll is imported by xero_core.
    import importlib
    xero_core = importlib.import_module("xero_core")
    return f"{xero_core.PAYROLL_API_BASE}/{path.lstrip('/')}"


def _payroll_get(payload: dict[str, Any], tenant_id: str, path: str, params: dict[str, str] | None = None) -> Any:
    """Issue an authenticated GET to the AU Payroll API and return the parsed JSON."""
    import importlib
    import urllib.parse
    xero_core = importlib.import_module("xero_core")
    url = _payroll_url(path)
    if params:
        url = url + "?" + urllib.parse.urlencode(params)
    headers = xero_core.accounting_headers(payload, tenant_id)
    return xero_core.http_get_json(url, headers)


def read_pay_runs(
    payload: dict[str, Any],
    tenant_id: str,
    where: str | None = None,
    page: int | None = None,
    order: str | None = None,
) -> dict[str, Any]:
    """Fetch AU Payroll pay runs for an org.

    GET /PayRuns supports ONLY the ``where``, ``order`` and ``page`` query
    parameters (and an ``If-Modified-Since`` header, not exposed here) — there
    are NO ``fromDate``/``toDate`` range params on this endpoint (verified
    against xero-payroll-au.yaml 2026-06-11).  To filter by a date range, pass a
    ``where`` clause using Xero's DateTime syntax on a PayRun date field, e.g.::

        where="PayRunPeriodEndDate >= DateTime(2026, 01, 01)"

    or page through (100 PayRuns per page) and filter client-side by
    ``PaymentDate``.  This function does NOT silently send unsupported params.

    Args:
        payload: Auth token dict (must contain ``access_token``).
        tenant_id: Xero tenant (org) UUID.
        where: Optional Xero ``where`` filter string (passed through verbatim).
        page: Optional 1-based page number (Xero returns up to 100 per page).
        order: Optional Xero ``order`` clause.

    Returns:
        Parsed API response dict.  Key ``PayRuns`` is a list of pay-run records.
        A ``gross_total`` key is added: sum of each run's ``Wages`` summary
        where available (computed as a convenience; the list endpoint has no
        top-level gross).
    """
    params: dict[str, str] = {}
    if where:
        params["where"] = where
    if order:
        params["order"] = order
    if page is not None:
        params["page"] = str(page)

    response = _payroll_get(payload, tenant_id, "PayRuns", params or None)
    pay_runs: list[dict[str, Any]] = response.get("PayRuns") if isinstance(response, dict) else []
    if not isinstance(pay_runs, list):
        pay_runs = []

    gross_total = 0.0
    for run in pay_runs:
        wages = run.get("Wages")
        if isinstance(wages, (int, float)):
            gross_total += float(wages)

    return {
        **response,
        "PayRuns": pay_runs,
        "gross_total": round(gross_total, 2),
    }


def read_payslips(
    payload: dict[str, Any],
    tenant_id: str,
    pay_run_id: str,
) -> dict[str, Any]:
    """Fetch the payslip SUMMARY list for a given pay run.

    There is NO ``/PayRuns/{id}/Payslips`` sub-endpoint.  The payslip summaries
    (PayslipID, employee names, and summary totals such as ``Wages``, ``Tax``,
    ``Super``, ``NetPay``) are EMBEDDED in ``GET /PayRuns/{PayRunID}`` under the
    PayRun object's ``Payslips`` array (verified against xero-payroll-au.yaml
    2026-06-11).

    This returns those embedded summaries.  Per-line earnings detail (the
    EarningsLines used to derive gross at line granularity) requires a follow-up
    ``read_payslip(payslip_id)`` per payslip.

    Args:
        payload: Auth token dict.
        tenant_id: Xero tenant UUID.
        pay_run_id: The PayRunID UUID.

    Returns:
        Parsed API response dict.  Key ``Payslips`` is the embedded summary
        list.  ``gross_total`` is the sum of each summary's ``Wages`` field
        (the pay-run-level gross; line-item gross comes from ``read_payslip``).
    """
    response = _payroll_get(payload, tenant_id, f"PayRuns/{pay_run_id}")
    pay_runs: list[dict[str, Any]] = response.get("PayRuns") if isinstance(response, dict) else []
    if not isinstance(pay_runs, list):
        pay_runs = []
    pay_run = pay_runs[0] if pay_runs else {}
    payslips = pay_run.get("Payslips") or []
    if not isinstance(payslips, list):
        payslips = []

    gross_total = 0.0
    for ps in payslips:
        wages = ps.get("Wages") if isinstance(ps, dict) else None
        if isinstance(wages, (int, float)):
            gross_total += float(wages)

    return {
        **response,
        "PayRunID": pay_run.get("PayRunID"),
        "Payslips": payslips,
        "gross_total": round(gross_total, 2),
    }


def read_timesheets(
    payload: dict[str, Any],
    tenant_id: str,
    where: str | None = None,
    page: int | None = None,
    order: str | None = None,
) -> dict[str, Any]:
    """Fetch AU Payroll timesheets for an org.

    GET /Timesheets supports ONLY the ``where``, ``order`` and ``page`` query
    parameters (and an ``If-Modified-Since`` header, not exposed here) —
    verified against xero-payroll-au.yaml (``getTimesheets``, 2026-06-16).
    There are NO fromDate/toDate range params.  To target a pay period, pass a
    ``where`` clause on ``StartDate``/``EndDate`` using Xero's DateTime syntax,
    e.g.::

        where="StartDate >= DateTime(2026, 06, 01) && EndDate <= DateTime(2026, 06, 30)"

    or filter on ``Status`` / ``EmployeeID``.  Up to 100 timesheets return per
    page; page through for more.

    IMPORTANT: the endpoint's default order is oldest-first, so WITHOUT a filter
    or ``order`` the most recent timesheets are NOT on page 1.  The CLI
    (``payroll list-timesheets``) defaults ``order`` to ``StartDate DESC`` when
    no filter is given; callers of this helper directly should do the same to
    avoid the upstream ``list-timesheets`` tool's "oldest 100" trap.

    Args:
        payload: Auth token dict (must contain ``access_token``).
        tenant_id: Xero tenant (org) UUID.
        where: Optional Xero ``where`` filter string (passed through verbatim).
        page: Optional 1-based page number (Xero returns up to 100 per page).
        order: Optional Xero ``order`` clause.

    Returns:
        Parsed API response dict.  Key ``Timesheets`` is a list of timesheet
        records.  A ``hours_total`` convenience key sums each timesheet's
        ``Hours`` field where available.
    """
    params: dict[str, str] = {}
    if where:
        params["where"] = where
    if order:
        params["order"] = order
    if page is not None:
        params["page"] = str(page)

    response = _payroll_get(payload, tenant_id, "Timesheets", params or None)
    timesheets: list[dict[str, Any]] = response.get("Timesheets") if isinstance(response, dict) else []
    if not isinstance(timesheets, list):
        timesheets = []

    hours_total = 0.0
    for ts in timesheets:
        hours = ts.get("Hours") if isinstance(ts, dict) else None
        if isinstance(hours, (int, float)):
            hours_total += float(hours)

    return {
        **response,
        "Timesheets": timesheets,
        "hours_total": round(hours_total, 2),
    }


def read_payslip(
    payload: dict[str, Any],
    tenant_id: str,
    payslip_id: str,
) -> dict[str, Any]:
    """Fetch a single payslip by ID.

    Args:
        payload: Auth token dict.
        tenant_id: Xero tenant UUID.
        payslip_id: The PayslipID UUID.

    Returns:
        Parsed API response dict with the payslip record under the ``Payslip``
        key (the AU spec returns a SINGULAR ``Payslip`` object at
        ``GET /Payslip/{PayslipID}``, NOT a ``Payslips`` array).  A convenience
        key ``gross_earnings`` surfaces the payslip's gross: the payslip's
        top-level ``Wages`` field if present, else the sum of the
        ``EarningsLines`` (RatePerUnit*NumberOfUnits or FixedAmount).
    """
    response = _payroll_get(payload, tenant_id, f"Payslip/{payslip_id}")
    record = response.get("Payslip") if isinstance(response, dict) else None
    if not isinstance(record, dict):
        record = {}

    wages = record.get("Wages")
    if isinstance(wages, (int, float)):
        gross = float(wages)
    else:
        gross = _payslip_gross(record)

    return {
        **response,
        "Payslip": record,
        "gross_earnings": round(gross, 2),
    }


def read_employee_pay_template(
    payload: dict[str, Any],
    tenant_id: str,
    employee_id: str,
) -> dict[str, Any]:
    """Fetch the pay template (ordinary earnings definition) for an employee.

    Args:
        payload: Auth token dict.
        tenant_id: Xero tenant UUID.
        employee_id: The EmployeeID UUID.

    Returns:
        Parsed API response dict.  The ``PayTemplate`` is a NESTED field on the
        employee (``GET /Employees/{EmployeeID}`` → root ``Employees``[0] →
        ``PayTemplate`` → ``EarningsLines``), NOT a ``/PayTemplate`` sub-path.
        Convenience keys: ``PayTemplate`` (the extracted template object) and
        ``ordinary_earnings_rate`` (the first earnings line's ``RatePerUnit``).
    """
    response = _payroll_get(payload, tenant_id, f"Employees/{employee_id}")
    employees: list[dict[str, Any]] = response.get("Employees") if isinstance(response, dict) else []
    if not isinstance(employees, list):
        employees = []
    employee = employees[0] if employees else {}
    template = employee.get("PayTemplate") or {}
    if not isinstance(template, dict):
        template = {}
    earnings_lines = template.get("EarningsLines") or []
    ordinary_rate: float | None = None
    if isinstance(earnings_lines, list) and earnings_lines:
        first = earnings_lines[0]
        rpu = first.get("RatePerUnit") if isinstance(first, dict) else None
        if rpu is not None:
            try:
                ordinary_rate = round(float(rpu), 4)
            except (TypeError, ValueError):
                ordinary_rate = None
    return {
        **response,
        "PayTemplate": template,
        "ordinary_earnings_rate": ordinary_rate,
    }


def _payslip_gross(payslip: dict[str, Any]) -> float:
    """Sum the EarningsLines of a payslip record into a gross figure.

    Prefer the payslip's top-level ``Wages`` field (the API's own gross
    summary); ``read_payslip`` does that before calling this.  This helper is
    the line-by-line fallback.

    AU Payroll EarningsLine shapes (xero-payroll-au.yaml, verified 2026-06-11):
      - rate-based lines: ``RatePerUnit`` * ``NumberOfUnits``
      - fixed lines:      ``FixedAmount`` (e.g. CalculationType FIXEDAMOUNT)
    Note: AU EarningsLines do NOT carry a generic ``Amount`` field (that lives
    on deduction/leave lines); we read FixedAmount and rate*units only.
    """
    total = 0.0
    earnings_lines = payslip.get("EarningsLines") or []
    if not isinstance(earnings_lines, list):
        return total
    for line in earnings_lines:
        if not isinstance(line, dict):
            continue
        fixed = line.get("FixedAmount")
        if fixed:  # truthy only: a 0/None FixedAmount falls through to rate*units
            try:
                total += float(fixed)
                continue
            except (TypeError, ValueError):
                pass
        rate = line.get("RatePerUnit")
        units = line.get("NumberOfUnits")
        if rate is not None and units is not None:
            try:
                total += float(rate) * float(units)
            except (TypeError, ValueError):
                pass
    return total
