#!/usr/bin/env python3
"""xero-workflows: Arc Forge companion MCP for the Xero plugin.

The official Xero MCP wrapper (xero-official) remains the source for official
Xero API tools. This companion (xero-workflows) exposes repo-local workflow
helpers that are intentionally not in the official package: dry-run-first
document/reference/pre-work helpers, finance-rule checks, snapshots, audit
checks, and CDP-gated reconciliation.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from typing import Any


MODULE_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = MODULE_ROOT.parents[1]
XERO_CLI = MODULE_ROOT / "cli" / "xero"
XERO_RECONCILE = MODULE_ROOT / "reconciliation" / "xero-reconcile"
SERVER_NAME = "xero-workflows"
SERVER_VERSION = "0.1.0"


class XeroPluginMcpError(RuntimeError):
    """User-facing MCP companion error."""


def enum_schema(values: list[str]) -> dict[str, Any]:
    return {"type": "string", "enum": values}


def object_schema(properties: dict[str, Any], *, required: list[str] | None = None) -> dict[str, Any]:
    return {"type": "object", "properties": properties, "required": required or [], "additionalProperties": False}


TOOLS: list[dict[str, Any]] = [
    {
        "name": "xero_local_status",
        "description": "Run local Xero plugin status checks such as doctor, auth, rate, or lock status.",
        "inputSchema": object_schema(
            {
                "check": enum_schema(["doctor", "doctor-strict", "auth-status", "rate-status", "lock-status"]),
                "verbose": {"type": "boolean", "default": False},
            },
            required=["check"],
        ),
        "annotations": {"readOnlyHint": True, "openWorldHint": False},
    },
    {
        "name": "xero_rules",
        "description": "Validate finance rules, parse source names, resolve mapping rules, or persist reviewed mapping decisions.",
        "inputSchema": object_schema(
            {
                "action": enum_schema(["validate", "parse-name", "map", "upsert-mapping"]),
                "value": {"type": "string"},
                "kind": enum_schema(["account", "contact", "item", "tax"]),
                "name": {"type": "string"},
                "aliases": {"type": "array", "items": {"type": "string"}},
                "patterns": {"type": "array", "items": {"type": "string"}},
                "target": {"type": "object"},
                "source": {"type": "string"},
                "note": {"type": "string"},
                "rules": {"type": "string"},
            },
            required=["action"],
        ),
        "annotations": {"readOnlyHint": False, "openWorldHint": False},
    },
    {
        "name": "xero_snapshots",
        "description": "Fetch or list local Xero reference-data snapshots for dedup and mapping checks.",
        "inputSchema": object_schema(
            {
                "action": enum_schema(["fetch", "list"]),
                "kind": enum_schema(["accounts", "contacts", "items", "tax-rates", "tracking-categories"]),
                "where": {"type": "string"},
                "tenant_id": {"type": "string"},
                "snapshots": {"type": "string"},
            },
            required=["action"],
        ),
        "annotations": {"readOnlyHint": True, "openWorldHint": True},
    },
    {
        "name": "xero_audit_dry_run",
        "description": "Check candidate Xero mutations against rules and local snapshots before any write.",
        "inputSchema": object_schema(
            {
                "candidates": {"type": ["array", "object"]},
                "rules": {"type": "string"},
                "snapshots": {"type": "string"},
                "max_batch_size": {"type": "integer", "minimum": 1, "maximum": 100, "default": 25},
            },
            required=["candidates"],
        ),
        "annotations": {"readOnlyHint": True, "openWorldHint": False},
    },
    {
        "name": "xero_audit_check_live",
        "description": "Run a targeted read-only Xero check before mutation; avoids broad invoice/contact sweeps.",
        "inputSchema": object_schema(
            {
                "kind": enum_schema(["bank-transaction", "bill", "contact", "invoice", "item", "payment"]),
                "value": {"type": "string"},
                "field": {"type": "string"},
                "tenant_id": {"type": "string"},
                "limit": {"type": "integer", "minimum": 1, "maximum": 50, "default": 5},
            },
            required=["kind", "value"],
        ),
        "annotations": {"readOnlyHint": True, "openWorldHint": True},
    },
    {
        "name": "xero_documents_create",
        "description": "Dry-run or create an invoice, bill, quote, or credit note; apply requires preflight evidence or override.",
        "inputSchema": object_schema(
            {
                "kind": enum_schema(["bill", "credit-note", "invoice", "quote"]),
                "payload": {"type": ["array", "object"]},
                "apply": {"type": "boolean", "default": False},
                "tenant_id": {"type": "string"},
                "actor": {"type": "string"},
                "audit_dir": {"type": "string"},
                "preflight_report": {"type": "string"},
                "confirm_apply_without_preflight": {"type": "boolean", "default": False},
            },
            required=["kind", "payload"],
        ),
        "annotations": {"readOnlyHint": False, "destructiveHint": True, "openWorldHint": True},
    },
    {
        "name": "xero_documents_update",
        "description": "Dry-run or update document payload/status; apply requires preflight evidence or override.",
        "inputSchema": object_schema(
            {
                "kind": enum_schema(["bill", "credit-note", "invoice", "quote"]),
                "identifier": {"type": "string"},
                "payload": {"type": ["array", "object"]},
                "status": {"type": "string"},
                "apply": {"type": "boolean", "default": False},
                "tenant_id": {"type": "string"},
                "actor": {"type": "string"},
                "audit_dir": {"type": "string"},
                "preflight_report": {"type": "string"},
                "confirm_apply_without_preflight": {"type": "boolean", "default": False},
            },
            required=["kind"],
        ),
        "annotations": {"readOnlyHint": False, "destructiveHint": True, "openWorldHint": True},
    },
    {
        "name": "xero_documents_action",
        "description": "Dry-run or run a sales-invoice action; apply requires preflight evidence or override.",
        "inputSchema": object_schema(
            {
                "kind": enum_schema(["invoice"]),
                "action": enum_schema(["email", "online-url"]),
                "identifier": {"type": "string"},
                "apply": {"type": "boolean", "default": False},
                "tenant_id": {"type": "string"},
                "actor": {"type": "string"},
                "audit_dir": {"type": "string"},
                "preflight_report": {"type": "string"},
                "confirm_apply_without_preflight": {"type": "boolean", "default": False},
            },
            required=["kind", "action", "identifier"],
        ),
        "annotations": {"readOnlyHint": False, "destructiveHint": True, "openWorldHint": True},
    },
    {
        "name": "xero_reference_upsert",
        "description": "Dry-run or upsert Xero reference data; apply requires preflight evidence or override.",
        "inputSchema": object_schema(
            {
                "kind": enum_schema(["account", "contact", "item", "tracking-category", "tracking-option"]),
                "payload": {"type": ["array", "object"]},
                "method": enum_schema(["POST", "PUT"]),
                "apply": {"type": "boolean", "default": False},
                "tenant_id": {"type": "string"},
                "actor": {"type": "string"},
                "audit_dir": {"type": "string"},
                "preflight_report": {"type": "string"},
                "confirm_apply_without_preflight": {"type": "boolean", "default": False},
            },
            required=["kind", "payload"],
        ),
        "annotations": {"readOnlyHint": False, "destructiveHint": True, "openWorldHint": True},
    },
    {
        "name": "xero_prework_create",
        "description": "Dry-run or create reconciliation API pre-work; apply requires preflight evidence or override.",
        "inputSchema": object_schema(
            {
                "kind": enum_schema(["bank-transaction", "bank-transfer", "batch-payment", "manual-journal", "payment"]),
                "payload": {"type": ["array", "object"]},
                "apply": {"type": "boolean", "default": False},
                "tenant_id": {"type": "string"},
                "actor": {"type": "string"},
                "audit_dir": {"type": "string"},
                "preflight_report": {"type": "string"},
                "confirm_apply_without_preflight": {"type": "boolean", "default": False},
            },
            required=["kind", "payload"],
        ),
        "annotations": {"readOnlyHint": False, "destructiveHint": True, "openWorldHint": True},
    },
    {
        "name": "xero_payroll_pay_runs",
        "description": (
            "Read-only: list AU Payroll pay runs for an org. "
            "Returns pay-run records and a gross_total convenience sum. "
            "Requires payroll.payruns.read (or payroll.payruns write) scope."
        ),
        "inputSchema": object_schema(
            {
                "tenant_id": {"type": "string", "description": "Xero tenant (org) UUID — required for Model C per-call org selection"},
                "from_date": {"type": "string", "description": "Filter by PaymentDate >= this date (YYYY-MM-DD); translated to a Xero `where` clause"},
                "to_date": {"type": "string", "description": "Filter by PaymentDate <= this date (YYYY-MM-DD); translated to a Xero `where` clause"},
                "where": {"type": "string", "description": "Raw Xero `where` filter (escape hatch; overrides from_date/to_date)"},
                "page": {"type": "integer", "minimum": 1, "description": "1-based page number (up to 100 pay runs per page)"},
            },
            required=["tenant_id"],
        ),
        "annotations": {"readOnlyHint": True, "openWorldHint": True},
    },
    {
        "name": "xero_payroll_timesheets",
        "description": (
            "Read-only: list AU Payroll timesheets for an org, filterable by date range "
            "(from_date/to_date), employee, or status. Unlike the upstream list-timesheets "
            "tool (oldest 100, no filter), this targets any pay period via a where clause and "
            "defaults to most-recent-first. Returns timesheet records and an hours_total "
            "convenience sum. Requires payroll.timesheets.read (or payroll.timesheets write) scope."
        ),
        "inputSchema": object_schema(
            {
                "tenant_id": {"type": "string", "description": "Xero tenant (org) UUID — required for Model C per-call org selection"},
                "from_date": {"type": "string", "description": "Filter by StartDate >= this date (YYYY-MM-DD); translated to a Xero `where` clause"},
                "to_date": {"type": "string", "description": "Filter by EndDate <= this date (YYYY-MM-DD); translated to a Xero `where` clause"},
                "employee_id": {"type": "string", "description": "Filter by EmployeeID UUID"},
                "status": {"type": "string", "description": "Filter by Status (e.g. APPROVED, DRAFT, PROCESSED)"},
                "where": {"type": "string", "description": "Raw Xero `where` filter (escape hatch; overrides the other filters)"},
                "page": {"type": "integer", "minimum": 1, "description": "1-based page number (up to 100 timesheets per page)"},
                "order": {"type": "string", "description": "Xero `order` clause (default: 'StartDate DESC' when no filter)"},
            },
            required=["tenant_id"],
        ),
        "annotations": {"readOnlyHint": True, "openWorldHint": True},
    },
    {
        "name": "xero_payroll_payslip",
        "description": (
            "Read-only: list payslips for a pay run, or fetch a single payslip by ID. "
            "Returns payslip records and gross_total/gross_earnings convenience fields. "
            "Requires payroll.payruns.read (or payroll.payruns write) scope."
        ),
        "inputSchema": object_schema(
            {
                "tenant_id": {"type": "string", "description": "Xero tenant (org) UUID — required for Model C per-call org selection"},
                "pay_run_id": {"type": "string", "description": "PayRunID UUID — list all payslips for this pay run"},
                "payslip_id": {"type": "string", "description": "PayslipID UUID — fetch this single payslip (use instead of pay_run_id)"},
            },
            required=["tenant_id"],
        ),
        "annotations": {"readOnlyHint": True, "openWorldHint": True},
    },
    {
        "name": "xero_payroll_employee_pay_template",
        "description": (
            "Read-only: fetch an employee's pay template (ordinary earnings definition). "
            "Returns EarningsLines and an ordinary_earnings_rate convenience field. "
            "Requires payroll.employees.read (or payroll.employees write) scope."
        ),
        "inputSchema": object_schema(
            {
                "tenant_id": {"type": "string", "description": "Xero tenant (org) UUID — required for Model C per-call org selection"},
                "employee_id": {"type": "string", "description": "EmployeeID UUID"},
            },
            required=["tenant_id", "employee_id"],
        ),
        "annotations": {"readOnlyHint": True, "openWorldHint": True},
    },
    {
        "name": "xero_budgets_list",
        "description": (
            "Read-only: list Xero budgets (Budget Manager) — BudgetID, Type, Description, "
            "UpdatedDateUTC. The list endpoint returns summaries only (no period lines); use "
            "xero_budgets_get to fetch per-period BudgetLines for a specific budget. ids filters to "
            "specific BudgetIDs. Xero exposes budgets as GET-only (there is NO create/update budget "
            "API — budgets are edited in the Budget Manager UI). Requires accounting.budgets.read "
            "(opt in on an existing connection: `xero auth login --add budgets-read`)."
        ),
        "inputSchema": object_schema(
            {
                "tenant_id": {"type": "string", "description": "Xero tenant (org) UUID — overrides active tenant"},
                "ids": {"type": "string", "description": "Comma-separated BudgetIDs to filter the list"},
            },
        ),
        "annotations": {"readOnlyHint": True, "openWorldHint": True},
    },
    {
        "name": "xero_budgets_get",
        "description": (
            "Read-only: fetch one Xero budget by BudgetID with its per-account, per-period budget "
            "lines (BudgetLines + BudgetBalances) and any tracking. Optional date_from/date_to bound "
            "the returned periods. Pair with xero_export_pnl_tracking actuals for budget-vs-actual by "
            "department/account. Requires accounting.budgets.read scope."
        ),
        "inputSchema": object_schema(
            {
                "budget_id": {"type": "string", "description": "BudgetID UUID"},
                "tenant_id": {"type": "string", "description": "Xero tenant (org) UUID — overrides active tenant"},
                "date_from": {"type": "string", "description": "Period start (YYYY-MM-DD)"},
                "date_to": {"type": "string", "description": "Period end (YYYY-MM-DD)"},
            },
            required=["budget_id"],
        ),
        "annotations": {"readOnlyHint": True, "openWorldHint": True},
    },
    {
        "name": "xero_export_pnl_tracking",
        "description": (
            "Read-only, file-producing: write a normalized Profit & Loss-by-tracking-category CSV "
            "(one row per account/tracking option) for a period, with a per-segment income/cost/net "
            "reconciliation against Xero's own P&L. Replaces the CDP/browser P&L export. Uses the "
            "official Accounting Reports API (trackingCategoryID); requires accounting.reports.profitandloss.read."
        ),
        "inputSchema": object_schema(
            {
                "from_date": {"type": "string", "description": "Period start YYYY-MM-DD"},
                "to_date": {"type": "string", "description": "Period end YYYY-MM-DD"},
                "tracking_category_id": {"type": "string", "description": "Tracking category UUID to split columns by"},
                "out_path": {"type": "string", "description": "Absolute output CSV path"},
                "tracking_option_id": {"type": "string", "description": "Optional single tracking option to restrict to"},
                "segment_map": {"type": "object", "description": 'Optional rename map, e.g. {"Woodside":"Woodside Surgery"}'},
                "untracked_label": {"type": "string", "description": "Label for the untracked column (default: Unassigned)"},
                "source_report": {"type": "string", "description": "Value for the source_report column"},
                "note": {"type": "string"},
                "exported_at": {"type": "string", "description": "exported_at value (default: today)"},
                "reconcile_tolerance": {"type": "number", "default": 0.02},
                "allow_reconcile_mismatch": {"type": "boolean", "default": False},
                "tenant_id": {"type": "string"},
            },
            required=["from_date", "to_date", "tracking_category_id", "out_path"],
        ),
        "annotations": {"readOnlyHint": True, "openWorldHint": True},
    },
    {
        "name": "xero_export_account_transactions",
        "description": (
            "Read-only, file-producing: write normalized account-transaction rows for a period from the "
            "Xero general-ledger /Journals endpoint, signed by P&L direction (revenue positive, costs "
            "negative). This is the reconciling, non-CDP source for Account Transactions. "
            "Requires the accounting.journals.read scope, which is ONLY available on Xero connections "
            "created before 29 April 2026 (broad-scope). Granular-scope connections (created on/after "
            "29 April 2026) cannot use this endpoint — Xero returns invalid_scope / HTTP 401. "
            "Eligible operators (pre-29-Apr-2026 connection) can opt in with: "
            "`xero --profile <p> auth login --add journals-broad`."
        ),
        "inputSchema": object_schema(
            {
                "from_date": {"type": "string", "description": "Period start YYYY-MM-DD"},
                "to_date": {"type": "string", "description": "Period end YYYY-MM-DD"},
                "out_path": {"type": "string", "description": "Absolute output CSV path"},
                "tracking_category_id": {"type": "string", "description": "Tracking category UUID whose option becomes tracking_category"},
                "account_ids": {"type": "array", "items": {"type": "string"}, "description": "Restrict to these account UUIDs"},
                "segment_map": {"type": "object", "description": 'Optional rename map, e.g. {"Woodside":"Woodside Surgery"}'},
                "untracked_label": {"type": "string", "description": "Label for lines with no matching tracking option (default: Unassigned)"},
                "source_report": {"type": "string"},
                "note": {"type": "string"},
                "exported_at": {"type": "string"},
                "all_accounts": {"type": "boolean", "default": False, "description": "Include balance-sheet accounts too (default: P&L only)"},
                "tenant_id": {"type": "string"},
            },
            required=["from_date", "to_date", "out_path"],
        ),
        "annotations": {"readOnlyHint": True, "openWorldHint": True},
    },
    {
        "name": "xero_export_payments",
        "description": (
            "Read-only, file-producing: write normalized payment rows from the Xero /Payments endpoint "
            "(amount positive; source_type ACCREC = cash in, ACCPAY = cash out). This is the payment-timing "
            "source for 30-day cash collection. DELETED payments are excluded by default. from_date/to_date "
            "are optional — omit both to export all payments. Uses accounting.banktransactions/payments read "
            "scope (granular-safe); does not require the journals scope. account_name is blank (the list "
            "endpoint does not return bank-account names) — fine for cash timing."
        ),
        "inputSchema": object_schema(
            {
                "out_path": {"type": "string", "description": "Absolute output CSV path"},
                "from_date": {"type": "string", "description": "Optional period start YYYY-MM-DD (omit for all)"},
                "to_date": {"type": "string", "description": "Optional period end YYYY-MM-DD (omit for all)"},
                "source_report": {"type": "string"},
                "note": {"type": "string"},
                "exported_at": {"type": "string"},
                "include_deleted": {"type": "boolean", "default": False, "description": "Include DELETED payments (default: live only)"},
                "tenant_id": {"type": "string"},
            },
            required=["out_path"],
        ),
        "annotations": {"readOnlyHint": True, "openWorldHint": True},
    },
    {
        "name": "xero_export_aged_receivables",
        "description": (
            "Read-only, file-producing: write outstanding receivables aged at a date, built from "
            "/Invoices (Type=ACCREC, AUTHORISED, AmountDue>0). The full amount_due lands in the single "
            "aged bucket (current / one_month / two_months / three_months_or_more) matching days overdue. "
            "tracking_category is blank by design (invoice tracking is line-level). Granular-safe scope."
        ),
        "inputSchema": object_schema(
            {
                "out_path": {"type": "string", "description": "Absolute output CSV path"},
                "as_at_date": {"type": "string", "description": "Aging reference date YYYY-MM-DD (default: today)"},
                "source_report": {"type": "string"},
                "note": {"type": "string"},
                "exported_at": {"type": "string"},
                "tenant_id": {"type": "string"},
            },
            required=["out_path"],
        ),
        "annotations": {"readOnlyHint": True, "openWorldHint": True},
    },
    {
        "name": "xero_export_aged_payables",
        "description": (
            "Read-only, file-producing: write outstanding payables aged at a date, built from "
            "/Invoices (Type=ACCPAY, AUTHORISED, AmountDue>0). The full amount_due lands in the single "
            "aged bucket (current / one_month / two_months / three_months_or_more) matching days overdue. "
            "tracking_category is blank by design (bill tracking is line-level). Granular-safe scope."
        ),
        "inputSchema": object_schema(
            {
                "out_path": {"type": "string", "description": "Absolute output CSV path"},
                "as_at_date": {"type": "string", "description": "Aging reference date YYYY-MM-DD (default: today)"},
                "source_report": {"type": "string"},
                "note": {"type": "string"},
                "exported_at": {"type": "string"},
                "tenant_id": {"type": "string"},
            },
            required=["out_path"],
        ),
        "annotations": {"readOnlyHint": True, "openWorldHint": True},
    },
    {
        "name": "xero_reconcile_cdp",
        "description": "Use an explicit already-authenticated CDP session to inspect/capture/dry-run/apply Reconcile-tab actions.",
        "inputSchema": object_schema(
            {
                "action": enum_schema(["inspect", "capture-lines", "dry-run", "apply"]),
                "cdp_endpoint": {"type": "string"},
                "target_id": {"type": "string"},
                "expected": {"type": ["array", "object"]},
                "statement_lines": {"type": ["array", "object"]},
                "plan": {"type": ["array", "object"]},
                "confirm_apply": {"type": "boolean", "default": False},
                "timeout": {"type": "integer", "minimum": 1, "maximum": 60, "default": 10},
            },
            required=["action", "cdp_endpoint"],
        ),
        "annotations": {"readOnlyHint": False, "destructiveHint": True, "openWorldHint": False},
    },
]


def utc_seconds() -> int:
    return int(time.time())


def tool_catalog() -> list[dict[str, Any]]:
    return TOOLS


def write_json_temp(temp: Path, name: str, payload: Any) -> Path:
    path = temp / name
    path.write_text(json.dumps(payload, indent=2, sort_keys=False) + "\n", encoding="utf-8")
    os.chmod(path, 0o600)
    return path


def add_optional(command: list[str], flag: str, value: Any) -> None:
    if value is not None and value != "":
        command.extend([flag, str(value)])


def run_command(command: list[str]) -> dict[str, Any]:
    result = subprocess.run(
        command,
        cwd=REPO_ROOT,
        env=os.environ.copy(),
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    parsed = None
    if result.stdout.strip():
        try:
            parsed = json.loads(result.stdout)
        except json.JSONDecodeError:
            parsed = None
    return {
        "ok": result.returncode == 0,
        "returncode": result.returncode,
        "command": command,
        "stdout_json": parsed,
        "stdout": None if parsed is not None else result.stdout.strip(),
        "stderr": result.stderr.strip(),
    }


def xero_cli_base(args: argparse.Namespace | None = None) -> list[str]:
    path = getattr(args, "xero_cli", None) if args is not None else None
    return [str(Path(path).expanduser().resolve() if path else XERO_CLI)]


def xero_reconcile_base(args: argparse.Namespace | None = None) -> list[str]:
    path = getattr(args, "xero_reconcile", None) if args is not None else None
    return [str(Path(path).expanduser().resolve() if path else XERO_RECONCILE)]


def build_cli_command(name: str, arguments: dict[str, Any], temp: Path, args: argparse.Namespace | None = None) -> list[str]:
    if name == "xero_local_status":
        check = arguments["check"]
        if check == "doctor":
            command = xero_cli_base(args) + ["doctor"]
        elif check == "doctor-strict":
            command = xero_cli_base(args) + ["doctor", "--strict"]
        elif check == "auth-status":
            command = xero_cli_base(args) + ["auth", "status"]
            if arguments.get("verbose"):
                command.append("--verbose")
        elif check == "rate-status":
            command = xero_cli_base(args) + ["rate", "status"]
        elif check == "lock-status":
            command = xero_cli_base(args) + ["lock", "status"]
        else:
            raise XeroPluginMcpError(f"Unsupported status check: {check}")
        return command

    if name == "xero_rules":
        action = arguments["action"]
        command = xero_cli_base(args) + ["rules", action]
        if action == "parse-name":
            add_optional(command, "", arguments.get("value"))
        elif action == "map":
            if not arguments.get("kind") or not arguments.get("value"):
                raise XeroPluginMcpError("xero_rules map requires kind and value.")
            command.extend([str(arguments["kind"]), str(arguments["value"])])
        elif action == "upsert-mapping":
            if not arguments.get("kind") or not arguments.get("name") or arguments.get("target") is None:
                raise XeroPluginMcpError("xero_rules upsert-mapping requires kind, name, and target.")
            target = write_json_temp(temp, "mapping-target.json", arguments["target"])
            command.extend([str(arguments["kind"]), "--name", str(arguments["name"]), "--target-file", str(target)])
            for alias in arguments.get("aliases") or []:
                command.extend(["--alias", str(alias)])
            for pattern in arguments.get("patterns") or []:
                command.extend(["--pattern", str(pattern)])
            add_optional(command, "--source", arguments.get("source"))
            add_optional(command, "--note", arguments.get("note"))
        add_optional(command, "--rules", arguments.get("rules"))
        return [item for item in command if item != ""]

    if name == "xero_snapshots":
        action = arguments["action"]
        if action == "list":
            command = xero_cli_base(args) + ["snapshots", "list"]
            add_optional(command, "--snapshots", arguments.get("snapshots"))
            return command
        if action != "fetch":
            raise XeroPluginMcpError(f"Unsupported snapshots action: {action}")
        if not arguments.get("kind"):
            raise XeroPluginMcpError("xero_snapshots fetch requires kind.")
        command = xero_cli_base(args) + ["snapshots", "fetch", str(arguments["kind"])]
        add_optional(command, "--where", arguments.get("where"))
        add_optional(command, "--tenant-id", arguments.get("tenant_id"))
        add_optional(command, "--snapshots", arguments.get("snapshots"))
        return command

    if name == "xero_audit_dry_run":
        candidates = write_json_temp(temp, "candidates.json", arguments["candidates"])
        command = xero_cli_base(args) + ["audit", "dry-run", "--candidates", str(candidates)]
        add_optional(command, "--rules", arguments.get("rules"))
        add_optional(command, "--snapshots", arguments.get("snapshots"))
        add_optional(command, "--max-batch-size", arguments.get("max_batch_size"))
        return command

    if name == "xero_audit_check_live":
        command = xero_cli_base(args) + ["audit", "check-live", str(arguments["kind"]), str(arguments["value"])]
        add_optional(command, "--field", arguments.get("field"))
        add_optional(command, "--tenant-id", arguments.get("tenant_id"))
        add_optional(command, "--limit", arguments.get("limit"))
        return command

    if name == "xero_documents_create":
        payload = write_json_temp(temp, "document-create.json", arguments["payload"])
        command = xero_cli_base(args) + ["documents", "create", str(arguments["kind"]), "--payload", str(payload)]
        if arguments.get("apply"):
            command.append("--apply")
        add_optional(command, "--preflight-report", arguments.get("preflight_report"))
        if arguments.get("confirm_apply_without_preflight"):
            command.append("--confirm-apply-without-preflight")
        add_optional(command, "--tenant-id", arguments.get("tenant_id"))
        add_optional(command, "--actor", arguments.get("actor"))
        add_optional(command, "--audit-dir", arguments.get("audit_dir"))
        return command

    if name == "xero_documents_update":
        command = xero_cli_base(args) + ["documents", "update", str(arguments["kind"])]
        add_optional(command, "--identifier", arguments.get("identifier"))
        if arguments.get("payload") is not None:
            payload = write_json_temp(temp, "document-update.json", arguments["payload"])
            command.extend(["--payload", str(payload)])
        add_optional(command, "--status", arguments.get("status"))
        if arguments.get("apply"):
            command.append("--apply")
        add_optional(command, "--preflight-report", arguments.get("preflight_report"))
        if arguments.get("confirm_apply_without_preflight"):
            command.append("--confirm-apply-without-preflight")
        add_optional(command, "--tenant-id", arguments.get("tenant_id"))
        add_optional(command, "--actor", arguments.get("actor"))
        add_optional(command, "--audit-dir", arguments.get("audit_dir"))
        return command

    if name == "xero_documents_action":
        command = xero_cli_base(args) + ["documents", "action", str(arguments["kind"]), str(arguments["action"])]
        add_optional(command, "--identifier", arguments.get("identifier"))
        if arguments.get("apply"):
            command.append("--apply")
        add_optional(command, "--preflight-report", arguments.get("preflight_report"))
        if arguments.get("confirm_apply_without_preflight"):
            command.append("--confirm-apply-without-preflight")
        add_optional(command, "--tenant-id", arguments.get("tenant_id"))
        add_optional(command, "--actor", arguments.get("actor"))
        add_optional(command, "--audit-dir", arguments.get("audit_dir"))
        return command

    if name == "xero_reference_upsert":
        payload = write_json_temp(temp, "reference-upsert.json", arguments["payload"])
        command = xero_cli_base(args) + ["reference", "upsert", str(arguments["kind"]), "--payload", str(payload)]
        add_optional(command, "--method", arguments.get("method"))
        if arguments.get("apply"):
            command.append("--apply")
        add_optional(command, "--preflight-report", arguments.get("preflight_report"))
        if arguments.get("confirm_apply_without_preflight"):
            command.append("--confirm-apply-without-preflight")
        add_optional(command, "--tenant-id", arguments.get("tenant_id"))
        add_optional(command, "--actor", arguments.get("actor"))
        add_optional(command, "--audit-dir", arguments.get("audit_dir"))
        return command

    if name == "xero_prework_create":
        payload = write_json_temp(temp, "prework-create.json", arguments["payload"])
        command = xero_cli_base(args) + ["prework", "create", str(arguments["kind"]), "--payload", str(payload)]
        if arguments.get("apply"):
            command.append("--apply")
        add_optional(command, "--preflight-report", arguments.get("preflight_report"))
        if arguments.get("confirm_apply_without_preflight"):
            command.append("--confirm-apply-without-preflight")
        add_optional(command, "--tenant-id", arguments.get("tenant_id"))
        add_optional(command, "--actor", arguments.get("actor"))
        add_optional(command, "--audit-dir", arguments.get("audit_dir"))
        return command

    if name == "xero_payroll_pay_runs":
        if not arguments.get("tenant_id"):
            raise XeroPluginMcpError("xero_payroll_pay_runs requires tenant_id.")
        command = xero_cli_base(args) + ["payroll", "list-pay-runs"]
        add_optional(command, "--tenant-id", arguments.get("tenant_id"))
        add_optional(command, "--from", arguments.get("from_date"))
        add_optional(command, "--to", arguments.get("to_date"))
        add_optional(command, "--where", arguments.get("where"))
        add_optional(command, "--page", arguments.get("page"))
        return command

    if name == "xero_payroll_timesheets":
        if not arguments.get("tenant_id"):
            raise XeroPluginMcpError("xero_payroll_timesheets requires tenant_id.")
        command = xero_cli_base(args) + ["payroll", "list-timesheets"]
        add_optional(command, "--tenant-id", arguments.get("tenant_id"))
        add_optional(command, "--from", arguments.get("from_date"))
        add_optional(command, "--to", arguments.get("to_date"))
        add_optional(command, "--employee", arguments.get("employee_id"))
        add_optional(command, "--status", arguments.get("status"))
        add_optional(command, "--where", arguments.get("where"))
        add_optional(command, "--page", arguments.get("page"))
        add_optional(command, "--order", arguments.get("order"))
        return command

    if name == "xero_payroll_payslip":
        if not arguments.get("tenant_id"):
            raise XeroPluginMcpError("xero_payroll_payslip requires tenant_id.")
        if not arguments.get("pay_run_id") and not arguments.get("payslip_id"):
            raise XeroPluginMcpError("xero_payroll_payslip requires either pay_run_id or payslip_id.")
        if arguments.get("payslip_id"):
            command = xero_cli_base(args) + ["payroll", "get-payslip", "--payslip-id", str(arguments["payslip_id"])]
        else:
            command = xero_cli_base(args) + ["payroll", "list-payslips", "--pay-run-id", str(arguments["pay_run_id"])]
        add_optional(command, "--tenant-id", arguments.get("tenant_id"))
        return command

    if name == "xero_payroll_employee_pay_template":
        if not arguments.get("tenant_id"):
            raise XeroPluginMcpError("xero_payroll_employee_pay_template requires tenant_id.")
        if not arguments.get("employee_id"):
            raise XeroPluginMcpError("xero_payroll_employee_pay_template requires employee_id.")
        command = xero_cli_base(args) + ["payroll", "employee-pay-template", "--employee-id", str(arguments["employee_id"])]
        add_optional(command, "--tenant-id", arguments.get("tenant_id"))
        return command

    if name == "xero_budgets_list":
        command = xero_cli_base(args) + ["budgets", "list"]
        add_optional(command, "--tenant-id", arguments.get("tenant_id"))
        add_optional(command, "--ids", arguments.get("ids"))
        return command

    if name == "xero_budgets_get":
        if not arguments.get("budget_id"):
            raise XeroPluginMcpError("xero_budgets_get requires budget_id.")
        command = xero_cli_base(args) + ["budgets", "get", str(arguments["budget_id"])]
        add_optional(command, "--tenant-id", arguments.get("tenant_id"))
        add_optional(command, "--date-from", arguments.get("date_from"))
        add_optional(command, "--date-to", arguments.get("date_to"))
        return command

    if name == "xero_export_pnl_tracking":
        for required_key in ("from_date", "to_date", "tracking_category_id", "out_path"):
            if not arguments.get(required_key):
                raise XeroPluginMcpError(f"xero_export_pnl_tracking requires {required_key}.")
        command = xero_cli_base(args) + [
            "reports",
            "export-pnl-tracking",
            "--from-date",
            str(arguments["from_date"]),
            "--to-date",
            str(arguments["to_date"]),
            "--tracking-category-id",
            str(arguments["tracking_category_id"]),
            "--out",
            str(arguments["out_path"]),
        ]
        add_optional(command, "--tracking-option-id", arguments.get("tracking_option_id"))
        if arguments.get("segment_map") is not None:
            command.extend(["--segment-map", json.dumps(arguments["segment_map"])])
        add_optional(command, "--untracked-label", arguments.get("untracked_label"))
        add_optional(command, "--source-report", arguments.get("source_report"))
        add_optional(command, "--note", arguments.get("note"))
        add_optional(command, "--exported-at", arguments.get("exported_at"))
        add_optional(command, "--reconcile-tolerance", arguments.get("reconcile_tolerance"))
        if arguments.get("allow_reconcile_mismatch"):
            command.append("--allow-reconcile-mismatch")
        add_optional(command, "--tenant-id", arguments.get("tenant_id"))
        return command

    if name == "xero_export_account_transactions":
        for required_key in ("from_date", "to_date", "out_path"):
            if not arguments.get(required_key):
                raise XeroPluginMcpError(f"xero_export_account_transactions requires {required_key}.")
        command = xero_cli_base(args) + [
            "journals",
            "export",
            "--from-date",
            str(arguments["from_date"]),
            "--to-date",
            str(arguments["to_date"]),
            "--out",
            str(arguments["out_path"]),
        ]
        add_optional(command, "--tracking-category-id", arguments.get("tracking_category_id"))
        for account_id in arguments.get("account_ids") or []:
            command.extend(["--account-id", str(account_id)])
        if arguments.get("segment_map") is not None:
            command.extend(["--segment-map", json.dumps(arguments["segment_map"])])
        add_optional(command, "--untracked-label", arguments.get("untracked_label"))
        add_optional(command, "--source-report", arguments.get("source_report"))
        add_optional(command, "--note", arguments.get("note"))
        add_optional(command, "--exported-at", arguments.get("exported_at"))
        if arguments.get("all_accounts"):
            command.append("--all-accounts")
        add_optional(command, "--tenant-id", arguments.get("tenant_id"))
        return command

    if name == "xero_export_payments":
        if not arguments.get("out_path"):
            raise XeroPluginMcpError("xero_export_payments requires out_path.")
        command = xero_cli_base(args) + [
            "payments",
            "export",
            "--out",
            str(arguments["out_path"]),
        ]
        add_optional(command, "--from-date", arguments.get("from_date"))
        add_optional(command, "--to-date", arguments.get("to_date"))
        add_optional(command, "--source-report", arguments.get("source_report"))
        add_optional(command, "--note", arguments.get("note"))
        add_optional(command, "--exported-at", arguments.get("exported_at"))
        if arguments.get("include_deleted"):
            command.append("--include-deleted")
        add_optional(command, "--tenant-id", arguments.get("tenant_id"))
        return command

    if name in ("xero_export_aged_receivables", "xero_export_aged_payables"):
        if not arguments.get("out_path"):
            raise XeroPluginMcpError(f"{name} requires out_path.")
        noun = "receivables" if name.endswith("receivables") else "payables"
        command = xero_cli_base(args) + [noun, "export", "--out", str(arguments["out_path"])]
        add_optional(command, "--as-at-date", arguments.get("as_at_date"))
        add_optional(command, "--source-report", arguments.get("source_report"))
        add_optional(command, "--note", arguments.get("note"))
        add_optional(command, "--exported-at", arguments.get("exported_at"))
        add_optional(command, "--tenant-id", arguments.get("tenant_id"))
        return command

    if name == "xero_reconcile_cdp":
        action = arguments["action"]
        command = xero_reconcile_base(args) + [action, "--cdp-endpoint", str(arguments["cdp_endpoint"])]
        # Only capture-lines and apply accept --target-id/--timeout; inspect and
        # dry-run reject unknown args (argparse exit 2), so gate per action.
        if action in ("capture-lines", "apply"):
            add_optional(command, "--target-id", arguments.get("target_id"))
            add_optional(command, "--timeout", arguments.get("timeout"))
        if action == "dry-run":
            if arguments.get("expected") is None or arguments.get("statement_lines") is None:
                raise XeroPluginMcpError("xero_reconcile_cdp dry-run requires expected and statement_lines.")
            command.extend(["--expected", str(write_json_temp(temp, "expected.json", arguments["expected"]))])
            command.extend(["--statement-lines", str(write_json_temp(temp, "statement-lines.json", arguments["statement_lines"]))])
        elif action == "apply":
            if arguments.get("plan") is None:
                raise XeroPluginMcpError("xero_reconcile_cdp apply requires plan.")
            command.extend(["--plan", str(write_json_temp(temp, "apply-plan.json", arguments["plan"]))])
            if arguments.get("confirm_apply"):
                command.append("--confirm-apply")
        return command

    raise XeroPluginMcpError(f"Unknown tool: {name}")


def call_tool(name: str, arguments: dict[str, Any], args: argparse.Namespace | None = None) -> dict[str, Any]:
    with tempfile.TemporaryDirectory(prefix="xero-workflows-mcp-") as temp_dir:
        temp = Path(temp_dir)
        command = build_cli_command(name, arguments, temp, args)
        result = run_command(command)
    return {
        "content": [{"type": "text", "text": json.dumps(result, indent=2, sort_keys=False)}],
        "isError": not result["ok"],
    }


def response(request_id: Any, result: Any = None, error: dict[str, Any] | None = None) -> dict[str, Any]:
    payload: dict[str, Any] = {"jsonrpc": "2.0", "id": request_id}
    if error is not None:
        payload["error"] = error
    else:
        payload["result"] = result
    return payload


def handle_request(message: dict[str, Any], args: argparse.Namespace | None = None) -> dict[str, Any] | None:
    method = message.get("method")
    request_id = message.get("id")
    if request_id is None:
        return None
    try:
        if method == "initialize":
            return response(
                request_id,
                {
                    "protocolVersion": message.get("params", {}).get("protocolVersion", "2024-11-05"),
                    "capabilities": {"tools": {}},
                    "serverInfo": {"name": SERVER_NAME, "version": SERVER_VERSION},
                },
            )
        if method == "ping":
            return response(request_id, {})
        if method == "tools/list":
            return response(request_id, {"tools": tool_catalog()})
        if method == "tools/call":
            params = message.get("params") or {}
            name = params.get("name")
            arguments = params.get("arguments") or {}
            if not isinstance(name, str) or not isinstance(arguments, dict):
                raise XeroPluginMcpError("tools/call requires string name and object arguments.")
            return response(request_id, call_tool(name, arguments, args))
        return response(request_id, error={"code": -32601, "message": f"Method not found: {method}"})
    except Exception as exc:
        return response(request_id, error={"code": -32000, "message": str(exc)})


def serve_stdio(args: argparse.Namespace) -> int:
    for raw in sys.stdin:
        if not raw.strip():
            continue
        try:
            message = json.loads(raw)
        except json.JSONDecodeError as exc:
            print(json.dumps(response(None, error={"code": -32700, "message": str(exc)})), flush=True)
            continue
        if not isinstance(message, dict):
            print(json.dumps(response(None, error={"code": -32600, "message": "Invalid request"})), flush=True)
            continue
        reply = handle_request(message, args)
        if reply is not None:
            print(json.dumps(reply, separators=(",", ":")), flush=True)
    return 0


def command_list_tools(_args: argparse.Namespace) -> int:
    print(json.dumps({"ok": True, "tool_count": len(tool_catalog()), "tools": tool_catalog()}, indent=2))
    return 0


def command_self_test(args: argparse.Namespace) -> int:
    init = handle_request({"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {"protocolVersion": "2024-11-05"}}, args)
    tools = handle_request({"jsonrpc": "2.0", "id": 2, "method": "tools/list"}, args)
    if not init or not tools:
        raise XeroPluginMcpError("self-test failed to build MCP responses.")
    tool_names = [item["name"] for item in tools["result"]["tools"]]
    required = {
        "xero_prework_create",
        "xero_audit_dry_run",
        "xero_reconcile_cdp",
        "xero_reference_upsert",
        "xero_budgets_list",
        "xero_budgets_get",
        "xero_export_pnl_tracking",
        "xero_export_account_transactions",
        "xero_export_payments",
        "xero_export_aged_receivables",
        "xero_export_aged_payables",
    }
    missing = sorted(required.difference(tool_names))
    if missing:
        raise XeroPluginMcpError(f"self-test missing tools: {', '.join(missing)}")
    print(json.dumps({"ok": True, "tool_count": len(tool_names), "required_present": sorted(required)}, indent=2))
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="xero-workflows-mcp", description="Arc Forge xero-workflows companion MCP server")
    parser.add_argument("--xero-cli", default=str(XERO_CLI), help="Path to local xero CLI")
    parser.add_argument("--xero-reconcile", default=str(XERO_RECONCILE), help="Path to local reconciliation CLI")
    sub = parser.add_subparsers(dest="command", required=True)
    run_cmd = sub.add_parser("run", help="Run MCP companion server over stdio")
    run_cmd.set_defaults(func=serve_stdio)
    list_tools = sub.add_parser("list-tools", help="Print companion MCP tool catalog")
    list_tools.set_defaults(func=command_list_tools)
    self_test = sub.add_parser("self-test", help="Run no-network companion MCP self-test")
    self_test.set_defaults(func=command_self_test)
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return int(args.func(args))
    except XeroPluginMcpError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
