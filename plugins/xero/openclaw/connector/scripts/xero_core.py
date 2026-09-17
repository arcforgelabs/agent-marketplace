#!/usr/bin/env python3
"""Local Xero core CLI.

This is the first implementation slice for the Xero plugin:
- OAuth Code + PKCE login against an Arc Forge-owned Xero app.
- Local token state with redacted status output.
- Tenant discovery and active-tenant selection.
- Read-only smoke command.

The CLI does not ship a client secret and does not automate Xero login/MFA.
"""

from __future__ import annotations

import argparse
import base64
import calendar
import hashlib
import http.server
import json
import mimetypes
import os
import re
import secrets
import shutil
import socket
import stat
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import webbrowser
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path
from typing import Any

import xero_ap_policy
import xero_finance_rules
import xero_ingestion
import xero_operation_lock
import xero_payroll
import xero_exports
import xero_profiles

try:
    from cryptography.fernet import Fernet, InvalidToken
except ImportError:  # pragma: no cover - exercised only on lean Python installs.
    Fernet = None  # type: ignore[assignment]
    InvalidToken = ValueError  # type: ignore[assignment,misc]


AUTHORIZE_URL = "https://login.xero.com/identity/connect/authorize"
TOKEN_URL = "https://identity.xero.com/connect/token"
CONNECTIONS_URL = "https://api.xero.com/connections"
ACCOUNTING_API_BASE = "https://api.xero.com/api.xro/2.0"
PAYROLL_API_BASE = "https://api.xero.com/payroll.xro/1.0"
MODULE_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = MODULE_ROOT.parents[1]
SNAPSHOT_KINDS = {
    "accounts": {"endpoint": "Accounts", "record_key": "Accounts"},
    "tax-rates": {"endpoint": "TaxRates", "record_key": "TaxRates"},
    "items": {"endpoint": "Items", "record_key": "Items"},
    # Contacts MUST be paged: Xero's unpaged Contacts LIST projection omits
    # PaymentTerms, PurchasesDefaultAccountCode, Balances, etc. Paging forces the
    # full per-record detail the AP term resolver needs (paged=True below).
    "contacts": {"endpoint": "Contacts", "record_key": "Contacts", "paged": True},
    "tracking-categories": {"endpoint": "TrackingCategories", "record_key": "TrackingCategories"},
    # organisation is a single-object endpoint (NOT a paged records list).
    # The raw response is {"Organisations": [{...}]}; we store the first element
    # directly under the "organisation" key so callers can read it without
    # unwrapping the array. Fields captured: PaymentTerms, SalesTaxBasis,
    # BaseCurrency, PeriodLockDate, EndOfYearLockDate (source of truth for
    # frozen-period enforcement).
    "organisation": {"endpoint": "Organisation", "record_key": "Organisations", "singleton": True},
}
LIVE_CHECK_KINDS = {
    "invoice": {"endpoint": "Invoices", "record_key": "Invoices", "field": "Reference"},
    "bill": {"endpoint": "Invoices", "record_key": "Invoices", "field": "Reference", "type": "ACCPAY"},
    "contact": {"endpoint": "Contacts", "record_key": "Contacts", "field": "Name"},
    "item": {"endpoint": "Items", "record_key": "Items", "field": "Code"},
    "payment": {"endpoint": "Payments", "record_key": "Payments", "field": "Reference"},
    "bank-transaction": {"endpoint": "BankTransactions", "record_key": "BankTransactions", "field": "Reference"},
}
REPORT_KINDS = {
    "profit-and-loss": {
        "endpoint": "Reports/ProfitAndLoss",
        "aliases": ["profitandloss", "p-and-l", "pnl"],
        "allowed_params": [
            "fromDate",
            "toDate",
            "periods",
            "timeframe",
            "standardLayout",
            "paymentsOnly",
            "trackingCategoryID",
            "trackingOptionID",
            "trackingCategoryID2",
            "trackingOptionID2",
        ],
    },
    "balance-sheet": {
        "endpoint": "Reports/BalanceSheet",
        "aliases": ["balancesheet"],
        "allowed_params": ["date", "periods", "timeframe", "standardLayout", "paymentsOnly"],
    },
    "trial-balance": {
        "endpoint": "Reports/TrialBalance",
        "aliases": ["trialbalance"],
        "allowed_params": ["date", "paymentsOnly"],
    },
    "aged-receivables": {
        "endpoint": "Reports/AgedReceivablesByContact",
        "aliases": ["aged-receivables-by-contact", "agedreceivables", "receivables"],
        "allowed_params": ["date", "fromDate", "toDate", "contactID"],
    },
    "aged-payables": {
        "endpoint": "Reports/AgedPayablesByContact",
        "aliases": ["aged-payables-by-contact", "agedpayables", "payables"],
        "allowed_params": ["date", "fromDate", "toDate", "contactID"],
    },
}
EVIDENCE_OBJECT_KINDS = {
    "invoice": {"endpoint": "Invoices", "id_name": "InvoiceID"},
    "bill": {"endpoint": "Invoices", "id_name": "InvoiceID"},
    "credit-note": {"endpoint": "CreditNotes", "id_name": "CreditNoteID"},
    "quote": {"endpoint": "Quotes", "id_name": "QuoteID"},
    "contact": {"endpoint": "Contacts", "id_name": "ContactID"},
    "bank-transaction": {"endpoint": "BankTransactions", "id_name": "BankTransactionID"},
    "bank-transfer": {"endpoint": "BankTransfers", "id_name": "BankTransferID"},
    "manual-journal": {"endpoint": "ManualJournals", "id_name": "ManualJournalID"},
    "purchase-order": {"endpoint": "PurchaseOrders", "id_name": "PurchaseOrderID"},
}
PREWORK_KINDS = {
    "payment": {"endpoint": "Payments", "root_key": "Payments", "id_key": "PaymentID"},
    "batch-payment": {"endpoint": "BatchPayments", "root_key": "BatchPayments", "id_key": "BatchPaymentID"},
    "bank-transaction": {"endpoint": "BankTransactions", "root_key": "BankTransactions", "id_key": "BankTransactionID"},
    "bank-transfer": {"endpoint": "BankTransfers", "root_key": "BankTransfers", "id_key": "BankTransferID"},
    "manual-journal": {"endpoint": "ManualJournals", "root_key": "ManualJournals", "id_key": "ManualJournalID"},
}
DOCUMENT_KINDS = {
    "invoice": {
        "endpoint": "Invoices",
        "root_key": "Invoices",
        "id_key": "InvoiceID",
        "default_fields": {"Type": "ACCREC"},
        "reference_fields": ["InvoiceNumber", "Reference", "InvoiceID"],
    },
    "bill": {
        "endpoint": "Invoices",
        "root_key": "Invoices",
        "id_key": "InvoiceID",
        "default_fields": {"Type": "ACCPAY"},
        "reference_fields": ["InvoiceNumber", "Reference", "InvoiceID"],
    },
    "quote": {
        "endpoint": "Quotes",
        "root_key": "Quotes",
        "id_key": "QuoteID",
        "default_fields": {},
        "reference_fields": ["QuoteNumber", "Reference", "QuoteID"],
    },
    "credit-note": {
        "endpoint": "CreditNotes",
        "root_key": "CreditNotes",
        "id_key": "CreditNoteID",
        "default_fields": {},
        "reference_fields": ["CreditNoteNumber", "Reference", "CreditNoteID"],
    },
}
DOCUMENT_STATUS_VALUES = {
    "invoice": {"DRAFT", "SUBMITTED", "AUTHORISED", "DELETED", "VOIDED"},
    "bill": {"DRAFT", "SUBMITTED", "AUTHORISED", "DELETED", "VOIDED"},
    "quote": {"DRAFT", "SENT", "ACCEPTED", "DECLINED", "INVOICED", "DELETED"},
    "credit-note": {"DRAFT", "SUBMITTED", "AUTHORISED", "DELETED", "VOIDED"},
}
DOCUMENT_ACTIONS = {"online-url", "email"}
REFERENCE_KINDS = {
    "contact": {
        "endpoint": "Contacts",
        "root_key": "Contacts",
        "id_key": "ContactID",
        "default_method": "POST",
        "reference_fields": ["Name", "ContactNumber", "ContactID"],
    },
    "item": {
        "endpoint": "Items",
        "root_key": "Items",
        "id_key": "ItemID",
        "default_method": "POST",
        "reference_fields": ["Code", "Name", "ItemID"],
    },
    "account": {
        "endpoint": "Accounts",
        "root_key": "Accounts",
        "id_key": "AccountID",
        "default_method": "PUT",
        "reference_fields": ["Code", "Name", "AccountID"],
    },
    "tracking-category": {
        "endpoint": "TrackingCategories",
        "root_key": "TrackingCategories",
        "id_key": "TrackingCategoryID",
        "default_method": "POST",
        "reference_fields": ["Name", "TrackingCategoryID"],
    },
    "tracking-option": {
        "endpoint_template": "TrackingCategories/{TrackingCategoryID}/Options",
        "parent_id_field": "TrackingCategoryID",
        "root_key": "Options",
        "id_key": "TrackingOptionID",
        "default_method": "PUT",
        "reference_fields": ["Name", "Option", "TrackingOptionID"],
    },
}
DEFAULT_CALLBACK_HOST = "localhost"
DEFAULT_CALLBACK_PORT = 8765
DEFAULT_TOKEN_PATH = Path.home() / ".config" / "arc-forge-tools" / "xero" / "tokens.json"
DEFAULT_TOKEN_KEY_PATH = Path.home() / ".config" / "arc-forge-tools" / "xero" / "token-store.key"
DEFAULT_PUBLIC_OAUTH_APP_PATH = Path.home() / ".config" / "arc-forge-tools" / "xero" / "oauth-app.json"
DEFAULT_RATE_LIMIT_PATH = Path.home() / ".config" / "arc-forge-tools" / "xero" / "rate-limit-status.json"
DEFAULT_CLI_RATE_LIMIT_PATH = Path.home() / ".config" / "arc-forge-tools" / "xero" / "rate-limit-cli-status.json"
DEFAULT_SHARED_RATE_LIMIT_PATH = Path.home() / ".config" / "arc-forge-tools" / "xero" / "rate-limit-shared.json"
DEFAULT_RATE_UNBLOCK_PATH = Path.home() / ".config" / "arc-forge-tools" / "xero" / "rate-limit-unblock.json"
CLI_RATE_LIMITS = {
    "max_per_minute": 55,
    "day_limit": 5000,
    "app_minute_limit": 10000,
    "minute_window_seconds": 60,
}
# Bounded retry for Xero 429s that clear on the rolling minute window (minute /
# app-minute limits). Total attempts = 1 initial + (HTTP_RETRY_ATTEMPTS - 1)
# retries. Day-limit 429s are never retried (they will not clear within a run).
HTTP_RETRY_ATTEMPTS = int(os.environ.get("ARC_FORGE_XERO_HTTP_RETRY_ATTEMPTS") or 4)
HTTP_RETRY_MAX_DELAY_SECONDS = float(os.environ.get("ARC_FORGE_XERO_HTTP_RETRY_MAX_DELAY") or 65)
TOKEN_STORE_TYPE = "arc-forge-xero-token-store"
TOKEN_STORE_ENCRYPTION = "fernet"
DEFAULT_SCOPE = " ".join(
    [
        "openid",
        "profile",
        "email",
        "offline_access",
        "accounting.invoices",
        "accounting.invoices.read",
        "accounting.payments",
        "accounting.payments.read",
        "accounting.banktransactions",
        "accounting.banktransactions.read",
        "accounting.manualjournals",
        "accounting.manualjournals.read",
        "accounting.reports.aged.read",
        "accounting.reports.balancesheet.read",
        "accounting.reports.profitandloss.read",
        "accounting.reports.trialbalance.read",
        "accounting.budgets.read",
        "accounting.contacts",
        "accounting.contacts.read",
        "accounting.attachments",
        "accounting.attachments.read",
        "accounting.settings",
        "accounting.settings.read",
    ]
)

# Named scope bundles for `xero auth login --add <bundle>[,<bundle>]`.
# Each bundle is a set of scope strings unioned onto the currently-granted
# scopes so an operator can incrementally consent without retyping a long
# --scope string (the source of the silent %0A failure these enablers fix).
SCOPE_BUNDLES: dict[str, frozenset[str]] = {
    # The accounting scopes that make up DEFAULT_SCOPE (excludes the OIDC
    # scopes openid/profile/email/offline_access, which are always included).
    "core-accounting": frozenset(
        scope
        for scope in DEFAULT_SCOPE.split()
        if scope not in {"openid", "profile", "email", "offline_access"}
    ),
    # Journal access opt-in — ONLY for connections created BEFORE 29 April 2026
    # that still carry broad-scope journal access.  Granular-scope connections
    # (created on/after 29 April 2026) have no journals granular replacement and
    # will receive Xero `invalid_scope` / HTTP 401 if this bundle is requested.
    # Use: `xero --profile <p> auth login --add journals-broad`
    "journals-broad": frozenset(["accounting.journals.read"]),
    # Read-only Budget Manager access (powers the `xero budgets` read commands).
    # Already part of DEFAULT_SCOPE, but catalogued as a bundle so an existing
    # connection can opt in without re-requesting everything:
    # `xero --profile <p> auth login --add budgets-read`. Xero exposes budgets
    # as READ-ONLY (GET only); there is no create/update budget API.
    "budgets-read": frozenset(["accounting.budgets.read"]),
    # Read-only AU Payroll access (powers the `xero payroll` read commands).
    "payroll-read": frozenset(
        [
            "payroll.employees.read",
            "payroll.payruns.read",
            "payroll.payslip.read",
            "payroll.settings.read",
            "payroll.timesheets.read",
        ]
    ),
}

# Always-present OIDC / refresh scopes — included in every login regardless of
# bundle selection so token refresh keeps working.
BASE_OIDC_SCOPES: frozenset[str] = frozenset(["openid", "profile", "email", "offline_access"])

# Catalogue of every scope this CLI knows how to request.  resolve_scope()
# validates each requested token against this set so a malformed --scope (stray
# newline, typo) raises a legible error naming the offending token instead of
# silently sending a broken `scope=...%0A...` to Xero.
KNOWN_SCOPES: frozenset[str] = frozenset(
    BASE_OIDC_SCOPES
    | frozenset(DEFAULT_SCOPE.split())
    | SCOPE_BUNDLES["core-accounting"]
    | SCOPE_BUNDLES["payroll-read"]
    # journals-broad is opt-in (not in DEFAULT_SCOPE) but must remain catalogued
    # so resolve_scope does not reject it when requested via --add journals-broad.
    | SCOPE_BUNDLES["journals-broad"]
    # The write payroll scopes (used by the existing write gate) are valid to
    # request too; granting write implies read.
    | frozenset(["payroll.employees", "payroll.payruns", "payroll.timesheets", "payroll.settings"])
)


def normalize_scope_string(value: str) -> str:
    """Collapse ALL whitespace (newlines, tabs, space runs) to single spaces.

    Drops empty tokens.  This turns a pasted multi-line --scope string (the
    classic source of a silent ``scope=...%0A...`` failure) into a clean
    space-delimited scope string.
    """
    return " ".join(value.split())


_SCOPE_TOKEN_RE = re.compile(r"^[a-z][a-z0-9._:-]*$")


def validate_scope_tokens(tokens: list[str]) -> None:
    """Raise a clear XeroCliError if any token is malformed (wrong shape).

    Validates token SHAPE, not membership of a fixed catalogue. Xero adds scopes
    over time and vets them at the consent screen, so a closed allowlist wrongly
    rejects legitimate scopes (e.g. ``files.*``, ``assets.*``, ``payroll.payslip``)
    and can break a previously-working ``--scope``/``XERO_SCOPES`` login. Shape
    validation still catches the classic failure — a pasted scope with stray
    newlines/punctuation yielding a garbage token — while accepting any
    well-formed scope. ``KNOWN_SCOPES`` is retained for bundles/suggestions only.
    """
    malformed = [tok for tok in tokens if not _SCOPE_TOKEN_RE.match(tok)]
    if malformed:
        raise XeroCliError(
            "Malformed OAuth scope token(s): "
            + ", ".join(repr(tok) for tok in malformed)
            + ". (Check for stray newlines/punctuation in your --scope string.)"
        )


SECRET_KEYS = {
    "access_token",
    "refresh_token",
    "id_token",
    "token",
    "authorization",
    "client_secret",
}


class XeroCliError(RuntimeError):
    """User-facing Xero CLI error."""


def utc_seconds() -> int:
    return int(time.time())


def b64url(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def create_code_verifier() -> str:
    return b64url(secrets.token_bytes(64))


def create_code_challenge(verifier: str) -> str:
    return b64url(hashlib.sha256(verifier.encode("ascii")).digest())


def create_state() -> str:
    return b64url(secrets.token_bytes(32))


def token_store_path(value: str | None = None) -> Path:
    raw = value or os.environ.get("XERO_TOKEN_STORE") or os.environ.get("ARC_FORGE_XERO_TOKEN_STORE")
    if not raw:
        return DEFAULT_TOKEN_PATH
    return Path(raw).expanduser().resolve()


def rate_limit_store_path(value: str | None = None) -> Path:
    raw = value or os.environ.get("ARC_FORGE_XERO_RATE_LIMIT_STORE") or os.environ.get("XERO_RATE_LIMIT_STORE")
    if not raw:
        return DEFAULT_RATE_LIMIT_PATH
    return Path(raw).expanduser().resolve()


def cli_rate_limit_store_path(value: str | None = None) -> Path:
    raw = value or os.environ.get("ARC_FORGE_XERO_CLI_RATE_LIMIT_STORE") or os.environ.get("XERO_CLI_RATE_LIMIT_STORE")
    if not raw:
        return DEFAULT_CLI_RATE_LIMIT_PATH
    return Path(raw).expanduser().resolve()


def shared_rate_limit_store_path(value: str | None = None) -> Path:
    raw = value or os.environ.get("ARC_FORGE_XERO_SHARED_RATE_LIMIT_STORE") or os.environ.get("XERO_SHARED_RATE_LIMIT_STORE")
    if not raw:
        return DEFAULT_SHARED_RATE_LIMIT_PATH
    return Path(raw).expanduser().resolve()


def rate_unblock_store_path(value: str | None = None) -> Path:
    raw = value or os.environ.get("ARC_FORGE_XERO_DAY_LIMIT_UNBLOCK_STORE") or os.environ.get("XERO_DAY_LIMIT_UNBLOCK_STORE")
    if not raw:
        return DEFAULT_RATE_UNBLOCK_PATH
    return Path(raw).expanduser().resolve()


def plugin_manifest_path() -> Path:
    return REPO_ROOT / "plugins" / "xero" / ".codex-plugin" / "plugin.json"


def plugin_mcp_config_path() -> Path:
    return REPO_ROOT / "plugins" / "xero" / ".mcp.json"


def plugin_public_oauth_app_path() -> Path:
    return REPO_ROOT / "plugins" / "xero" / "oauth-app.json"


def connector_public_oauth_app_path() -> Path:
    return MODULE_ROOT / "config" / "oauth-app.json"


def local_mcp_wrapper_path() -> Path:
    return MODULE_ROOT / "mcp" / "xero-mcp-local"


def finance_rules_template_path() -> Path:
    return MODULE_ROOT / "finance-rules" / "templates" / "default-rules.json"


def command_path(name: str) -> str | None:
    return shutil.which(name)


def public_oauth_config_paths() -> list[Path]:
    paths: list[Path] = []
    raw = os.environ.get("ARC_FORGE_XERO_OAUTH_APP_CONFIG") or os.environ.get("XERO_OAUTH_APP_CONFIG")
    if raw:
        return [Path(raw).expanduser().resolve()]
    paths.extend(
        [
            DEFAULT_PUBLIC_OAUTH_APP_PATH,
            plugin_public_oauth_app_path(),
            connector_public_oauth_app_path(),
        ]
    )
    return paths


def write_public_oauth_app_config(client_id: str, *, path: Path | None = None, port: int = DEFAULT_CALLBACK_PORT) -> Path:
    value = client_id.strip()
    if not value:
        raise XeroCliError("--client-id must not be empty")
    target = (path or DEFAULT_PUBLIC_OAUTH_APP_PATH).expanduser().resolve()
    target.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "schema_version": 1,
        "provider": "xero",
        "app_owner": "Arc Forge",
        "client_id": value,
        "redirect_uris": [f"http://{DEFAULT_CALLBACK_HOST}:{int(port)}/callback"],
        "client_secret_required": False,
    }
    tmp_path = target.with_suffix(target.suffix + ".tmp")
    with tmp_path.open("w", encoding="utf-8") as handle:
        json.dump(payload, handle, indent=2, sort_keys=False)
        handle.write("\n")
    os.chmod(tmp_path, stat.S_IRUSR | stat.S_IWUSR)
    tmp_path.replace(target)
    os.chmod(target, stat.S_IRUSR | stat.S_IWUSR)
    return target


def load_public_client_id_from_config() -> tuple[str, str | None]:
    for path in public_oauth_config_paths():
        if not path.exists():
            continue
        try:
            payload = read_json_file_if_exists(path)
        except OSError:
            continue
        if not isinstance(payload, dict):
            continue
        client_id = str(payload.get("client_id") or payload.get("public_client_id") or "").strip()
        if client_id:
            return client_id, str(path)
    return "", None


def resolve_client_id_info(value: str | None = None) -> tuple[str, str]:
    explicit = (value or "").strip()
    if explicit:
        return explicit, "argument"
    for env_name in ("ARC_FORGE_XERO_CLIENT_ID", "XERO_OAUTH_CLIENT_ID", "XERO_CLIENT_ID"):
        env_value = str(os.environ.get(env_name) or "").strip()
        if env_value:
            return env_value, f"env:{env_name}"
    config_value, config_path = load_public_client_id_from_config()
    if config_value:
        return config_value, f"config:{config_path}"
    return "", "missing"


def resolve_client_id(value: str | None = None) -> str:
    client_id, _source = resolve_client_id_info(value)
    if not client_id:
        raise XeroCliError(
            "Missing Xero OAuth client id. Package the public Arc Forge Xero OAuth app client id "
            "in plugins/xero/oauth-app.json, run `xero auth configure-app --client-id <id>`, "
            "or set ARC_FORGE_XERO_CLIENT_ID."
        )
    return client_id


def resolve_scope(value: str | None = None) -> str:
    """Resolve the OAuth scope string, normalising whitespace and validating tokens.

    Collapses all whitespace (newlines/tabs/space-runs) to single spaces, drops
    empty tokens, then validates each token against KNOWN_SCOPES so a malformed
    --scope (e.g. a pasted string with stray newlines) raises a legible error
    naming the offending token instead of silently sending a broken scope.
    """
    raw = value or os.environ.get("XERO_SCOPES") or DEFAULT_SCOPE
    normalized = normalize_scope_string(raw)
    tokens = normalized.split()
    validate_scope_tokens(tokens)
    return normalized


def scope_list(value: str | None = None) -> list[str]:
    return [item for item in resolve_scope(value).split() if item]


def resolve_scope_with_bundles(
    *,
    scope: str | None,
    add_bundles: str | None,
    granted: str | None,
) -> str:
    """Resolve the login scope string, optionally unioning named bundles.

    Precedence:
      • If ``scope`` is given, it is the escape hatch — used verbatim (after
        normalisation + validation).
      • Else if ``add_bundles`` is given (comma-separated bundle names), union
        the currently-``granted`` scopes with the named bundle(s) + base OIDC
        scopes.
      • Else fall back to the default resolve_scope().

    Args:
        scope: Raw --scope override (escape hatch), or None.
        add_bundles: Comma-separated bundle names from --add, or None.
        granted: The currently-granted scope string (from the stored token), or None.
    """
    if scope:
        return resolve_scope(scope)
    if add_bundles:
        names = [n.strip() for n in add_bundles.split(",") if n.strip()]
        unknown_bundles = [n for n in names if n not in SCOPE_BUNDLES]
        if unknown_bundles:
            raise XeroCliError(
                "Unknown scope bundle(s): "
                + ", ".join(repr(n) for n in unknown_bundles)
                + ". Known bundles: "
                + ", ".join(sorted(SCOPE_BUNDLES))
            )
        union: set[str] = set(BASE_OIDC_SCOPES)
        # Union with ALL currently-granted scopes so we never drop existing
        # consent. Do NOT filter through a local allowlist — Xero already vetted
        # these at grant time, and filtering silently narrows consent on re-auth.
        if granted:
            union |= set(normalize_scope_string(granted).split())
        for name in names:
            union |= set(SCOPE_BUNDLES[name])
        tokens = sorted(union)
        validate_scope_tokens(tokens)
        return " ".join(tokens)
    return resolve_scope(None)


def build_app_config_report(args: argparse.Namespace) -> dict[str, Any]:
    port = int(args.port or DEFAULT_CALLBACK_PORT)
    callback = f"http://{DEFAULT_CALLBACK_HOST}:{port}/callback"
    scopes = scope_list(args.scope)
    client_id, client_id_source = resolve_client_id_info(args.client_id)
    return {
        "ok": bool(client_id) or not args.strict,
        "mode": "xero-oauth-app-config",
        "app_owner": "Arc Forge",
        "user_developer_credentials_required": False,
        "xero_app": {
            "app_type": "Mobile/Desktop or PKCE-capable public client",
            "client_id_env": "ARC_FORGE_XERO_CLIENT_ID",
            "client_id_configured": bool(client_id),
            "client_id": redact_value(client_id) if client_id else None,
            "client_id_source": client_id_source,
            "client_secret_required": False,
            "redirect_uris": [callback],
            "scope_count": len(scopes),
            "scopes": scopes,
        },
        "local_callback": {
            "host": DEFAULT_CALLBACK_HOST,
            "port": port,
            "path": "/callback",
            "url": callback,
        },
        "oauth_flow": {
            "grant": "authorization_code",
            "pkce": True,
            "offline_access_required": "offline_access" in scopes,
            "opens_user_browser": True,
            "user_completes_login_mfa_consent": True,
            "local_cli_captures_callback_only": True,
        },
        "environment": {
            "required_for_login": [] if client_id else ["ARC_FORGE_XERO_CLIENT_ID or packaged oauth-app.json"],
            "optional": ["XERO_TOKEN_STORE", "ARC_FORGE_XERO_TOKEN_STORE_MODE", "ARC_FORGE_XERO_TOKEN_KEY_FILE", "XERO_SCOPES", "ARC_FORGE_XERO_OAUTH_APP_CONFIG"],
        },
        "public_oauth_config_paths": [str(path) for path in public_oauth_config_paths()],
        "next_steps": [
            "Create or update the Arc Forge-owned Xero OAuth app with the redirect URI above if it does not already exist.",
            "Package the public client id in plugins/xero/oauth-app.json, run `xero auth configure-app --client-id <id>`, or set ARC_FORGE_XERO_CLIENT_ID.",
            "Run `xero auth login`, complete Xero login/MFA/consent in the browser, then select a tenant.",
        ],
    }


def command_auth_configure_app(args: argparse.Namespace) -> int:
    path = write_public_oauth_app_config(args.client_id, path=Path(args.path) if args.path else None, port=args.port)
    write_json(
        {
            "ok": True,
            "mode": "xero-oauth-app-config-write",
            "path": str(path),
            "client_id": redact_value(args.client_id),
            "client_secret_required": False,
            "redirect_uris": [f"http://{DEFAULT_CALLBACK_HOST}:{int(args.port)}/callback"],
            "next_steps": [
                "Run `xero auth app-config --strict` to verify the configured public client id.",
                "Run `xero auth login`, complete Xero login/MFA/consent in the browser, then select a tenant.",
            ],
        }
    )
    return 0


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


@dataclass
class TokenStore:
    path: Path

    def mode(self) -> str:
        raw = (
            os.environ.get("ARC_FORGE_XERO_TOKEN_STORE_MODE")
            or os.environ.get("XERO_TOKEN_STORE_MODE")
            or "auto"
        ).strip().lower()
        if raw not in {"auto", "encrypted", "plaintext"}:
            raise XeroCliError("Token store mode must be one of: auto, encrypted, plaintext")
        if raw == "auto":
            return "encrypted" if Fernet is not None else "plaintext"
        if raw == "encrypted" and Fernet is None:
            raise XeroCliError("Encrypted token store requires the Python `cryptography` package.")
        return raw

    def key_path(self) -> Path:
        raw = os.environ.get("ARC_FORGE_XERO_TOKEN_KEY_FILE") or os.environ.get("XERO_TOKEN_KEY_FILE")
        if raw:
            return Path(raw).expanduser().resolve()
        if self.path == DEFAULT_TOKEN_PATH:
            return DEFAULT_TOKEN_KEY_PATH
        return self.path.with_suffix(self.path.suffix + ".key")

    def encryption_available(self) -> bool:
        return Fernet is not None

    def is_encrypted_payload(self, payload: Any) -> bool:
        return (
            isinstance(payload, dict)
            and payload.get("store_type") == TOKEN_STORE_TYPE
            and payload.get("encrypted") is True
            and payload.get("algorithm") == TOKEN_STORE_ENCRYPTION
        )

    def load_raw(self) -> Any:
        if not self.path.exists():
            return {}
        try:
            with self.path.open("r", encoding="utf-8") as handle:
                return json.load(handle)
        except json.JSONDecodeError as exc:
            raise XeroCliError(f"Token store is invalid JSON: {self.path}: {exc}") from exc

    def load(self) -> dict[str, Any]:
        payload = self.load_raw()
        if self.is_encrypted_payload(payload):
            payload = self.decrypt_payload(payload)
        if not isinstance(payload, dict):
            raise XeroCliError(f"Token store root must be an object: {self.path}")
        return payload

    def save(self, payload: dict[str, Any]) -> None:
        self.save_with_backup(payload)

    def backup_path(self) -> Path:
        return self.path.with_suffix(self.path.suffix + ".bak")

    def write_payload_file(self, path: Path, payload: dict[str, Any]) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp_path = path.with_suffix(path.suffix + ".tmp")
        with tmp_path.open("w", encoding="utf-8") as handle:
            json.dump(payload, handle, indent=2, sort_keys=False)
            handle.write("\n")
        os.chmod(tmp_path, stat.S_IRUSR | stat.S_IWUSR)
        tmp_path.replace(path)
        os.chmod(path, stat.S_IRUSR | stat.S_IWUSR)

    def save_with_backup(self, payload: dict[str, Any]) -> None:
        stored_payload: dict[str, Any]
        if self.mode() == "encrypted":
            stored_payload = self.encrypt_payload(payload)
        else:
            stored_payload = payload
        if self.path.exists():
            try:
                backup_raw = self.load_raw()
                if isinstance(backup_raw, dict):
                    self.write_payload_file(self.backup_path(), backup_raw)
            except XeroCliError:
                # Do not block saving a newly valid token store because the old
                # store was already unreadable. The new write remains atomic.
                pass
        self.write_payload_file(self.path, stored_payload)

    def update(self, patch: dict[str, Any]) -> dict[str, Any]:
        payload = self.load()
        payload.update(patch)
        self.save(payload)
        return payload

    def describe(self) -> dict[str, Any]:
        raw = self.load_raw()
        encrypted = self.is_encrypted_payload(raw)
        mode = self.mode()
        return {
            "path": str(self.path),
            "mode": mode,
            "encrypted": encrypted,
            "encryption_available": self.encryption_available(),
            "algorithm": raw.get("algorithm") if isinstance(raw, dict) else None,
            "key_file": str(self.key_path()) if mode == "encrypted" or encrypted else None,
            "key_file_exists": self.key_path().exists() if mode == "encrypted" or encrypted else None,
        }

    def load_fernet(self) -> Any:
        if Fernet is None:
            raise XeroCliError("Encrypted token store requires the Python `cryptography` package.")
        key_path = self.key_path()
        key_path.parent.mkdir(parents=True, exist_ok=True)
        if key_path.exists():
            key = key_path.read_bytes().strip()
        else:
            key = Fernet.generate_key()
            tmp_path = key_path.with_suffix(key_path.suffix + ".tmp")
            tmp_path.write_bytes(key + b"\n")
            os.chmod(tmp_path, stat.S_IRUSR | stat.S_IWUSR)
            tmp_path.replace(key_path)
            os.chmod(key_path, stat.S_IRUSR | stat.S_IWUSR)
        try:
            return Fernet(key)
        except Exception as exc:  # noqa: BLE001 - normalize cryptography errors for CLI output.
            raise XeroCliError(f"Token store key is invalid: {key_path}") from exc

    def encrypt_payload(self, payload: dict[str, Any]) -> dict[str, Any]:
        fernet = self.load_fernet()
        plaintext = json.dumps(payload, separators=(",", ":"), sort_keys=False).encode("utf-8")
        ciphertext = fernet.encrypt(plaintext).decode("ascii")
        return {
            "schema_version": 1,
            "store_type": TOKEN_STORE_TYPE,
            "encrypted": True,
            "algorithm": TOKEN_STORE_ENCRYPTION,
            "key_source": "local-file",
            "ciphertext": ciphertext,
            "updated_at": utc_seconds(),
        }

    def decrypt_payload(self, payload: dict[str, Any]) -> dict[str, Any]:
        ciphertext = str(payload.get("ciphertext") or "")
        if not ciphertext:
            raise XeroCliError(f"Encrypted token store is missing ciphertext: {self.path}")
        fernet = self.load_fernet()
        try:
            raw = fernet.decrypt(ciphertext.encode("ascii")).decode("utf-8")
        except (InvalidToken, ValueError) as exc:
            raise XeroCliError(f"Encrypted token store could not be decrypted: {self.path}") from exc
        parsed = parse_json(raw)
        if not isinstance(parsed, dict):
            raise XeroCliError(f"Encrypted token store plaintext root must be an object: {self.path}")
        return parsed


def write_json(payload: Any) -> None:
    print(json.dumps(payload, indent=2, sort_keys=False))


def read_json_file_if_exists(path: Path) -> Any:
    if not path.exists():
        return None
    try:
        with path.open("r", encoding="utf-8") as handle:
            return json.load(handle)
    except json.JSONDecodeError:
        return {"ok": False, "error": "invalid_json", "path": str(path)}


def http_post_form(url: str, form: dict[str, str]) -> dict[str, Any]:
    body = urllib.parse.urlencode(form).encode("utf-8")
    request = urllib.request.Request(
        url,
        data=body,
        headers={
            "Content-Type": "application/x-www-form-urlencoded",
            "Accept": "application/json",
        },
        method="POST",
    )
    return http_json(request)


def http_get_json(url: str, headers: dict[str, str]) -> Any:
    request = urllib.request.Request(url, headers={**headers, "Accept": "application/json"}, method="GET")
    return http_json(request)


def http_send_json(method: str, url: str, headers: dict[str, str], payload: dict[str, Any]) -> Any:
    body = json.dumps(payload).encode("utf-8")
    request = urllib.request.Request(
        url,
        data=body,
        headers={**headers, "Accept": "application/json", "Content-Type": "application/json"},
        method=method,
    )
    return http_json(request)


def http_send_bytes(method: str, url: str, headers: dict[str, str], body: bytes, *, content_type: str) -> Any:
    request = urllib.request.Request(
        url,
        data=body,
        headers={**headers, "Accept": "application/json", "Content-Type": content_type},
        method=method,
    )
    return http_json(request)


def http_send_empty(method: str, url: str, headers: dict[str, str]) -> Any:
    request = urllib.request.Request(
        url,
        data=b"",
        headers={**headers, "Accept": "application/json"},
        method=method,
    )
    return http_json(request)


def is_accounting_api_url(url: str) -> bool:
    return str(url).startswith(ACCOUNTING_API_BASE + "/")


def is_xero_api_url(url: str) -> bool:
    """Return True for any Xero API URL that should be rate-governed.

    Covers both the Accounting API (api.xro/2.0) and the AU Payroll API
    (payroll.xro/1.0).  All other URLs (e.g. token, connections) are exempt.
    """
    s = str(url)
    return s.startswith(ACCOUNTING_API_BASE + "/") or s.startswith(PAYROLL_API_BASE + "/")


def request_tenant_id(request: urllib.request.Request) -> str:
    value = request.get_header("xero-tenant-id") or request.get_header("Xero-tenant-id") or request.get_header("Xero-Tenant-Id")
    return str(value or "unknown-selected-tenant")


def current_day_key() -> str:
    return time.strftime("%Y-%m-%d", time.gmtime())


def load_cli_rate_state(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {"schema_version": 1, "source": "xero-cli", "tenants": {}, "app_minute_window": []}
    try:
        with path.open("r", encoding="utf-8") as handle:
            payload = json.load(handle)
    except json.JSONDecodeError as exc:
        raise XeroCliError(f"CLI rate-limit state is invalid JSON: {path}: {exc}") from exc
    if not isinstance(payload, dict):
        raise XeroCliError(f"CLI rate-limit state root must be an object: {path}")
    payload.setdefault("schema_version", 1)
    payload.setdefault("source", "xero-cli")
    payload.setdefault("tenants", {})
    payload.setdefault("app_minute_window", [])
    if not isinstance(payload["tenants"], dict):
        payload["tenants"] = {}
    if not isinstance(payload["app_minute_window"], list):
        payload["app_minute_window"] = []
    return payload


def save_cli_rate_state(path: Path, state: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_suffix(path.suffix + ".tmp")
    with tmp_path.open("w", encoding="utf-8") as handle:
        json.dump(state, handle, indent=2, sort_keys=False)
        handle.write("\n")
    os.chmod(tmp_path, stat.S_IRUSR | stat.S_IWUSR)
    tmp_path.replace(path)
    os.chmod(path, stat.S_IRUSR | stat.S_IWUSR)


def load_shared_rate_state(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {"schema_version": 1, "source": "xero-mcp-local-shared", "tenants": {}, "app_minute_window": []}
    try:
        with path.open("r", encoding="utf-8") as handle:
            payload = json.load(handle)
    except json.JSONDecodeError as exc:
        raise XeroCliError(f"Shared rate-limit state is invalid JSON: {path}: {exc}") from exc
    if not isinstance(payload, dict):
        raise XeroCliError(f"Shared rate-limit state root must be an object: {path}")
    payload.setdefault("schema_version", 1)
    payload.setdefault("source", "xero-mcp-local-shared")
    payload.setdefault("tenants", {})
    payload.setdefault("app_minute_window", [])
    if not isinstance(payload["tenants"], dict):
        payload["tenants"] = {}
    if not isinstance(payload["app_minute_window"], list):
        payload["app_minute_window"] = []
    return payload


def save_shared_rate_state(path: Path, state: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_suffix(path.suffix + ".tmp")
    with tmp_path.open("w", encoding="utf-8") as handle:
        json.dump(state, handle, indent=2, sort_keys=False)
        handle.write("\n")
    os.chmod(tmp_path, stat.S_IRUSR | stat.S_IWUSR)
    tmp_path.replace(path)
    os.chmod(path, stat.S_IRUSR | stat.S_IWUSR)


def numeric_window_values(values: Any, *, newer_than: int) -> list[int]:
    output: list[int] = []
    for value in values if isinstance(values, list) else []:
        try:
            parsed = int(float(value))
        except (TypeError, ValueError):
            continue
        if parsed > newer_than:
            output.append(parsed)
    return output


def prune_cli_rate_windows(state: dict[str, Any], *, now: int) -> None:
    cutoff = now - int(CLI_RATE_LIMITS["minute_window_seconds"])
    state["app_minute_window"] = [int(value) for value in state.get("app_minute_window", []) if int(value) > cutoff]
    day_key = current_day_key()
    for tenant in state.get("tenants", {}).values():
        if not isinstance(tenant, dict):
            continue
        tenant["minute_window"] = [int(value) for value in tenant.get("minute_window", []) if int(value) > cutoff]
        if tenant.get("day_key") != day_key:
            tenant["day_key"] = day_key
            tenant["day_count"] = 0
            tenant["circuit_open"] = False


def prune_shared_rate_windows(state: dict[str, Any], *, now_ms: int) -> None:
    cutoff = now_ms - int(CLI_RATE_LIMITS["minute_window_seconds"]) * 1000
    state["app_minute_window"] = numeric_window_values(state.get("app_minute_window", []), newer_than=cutoff)
    day_key = current_day_key()
    for tenant in state.get("tenants", {}).values():
        if not isinstance(tenant, dict):
            continue
        tenant["minute_window"] = numeric_window_values(tenant.get("minute_window", []), newer_than=cutoff)
        if tenant.get("day_key") != day_key:
            tenant["day_key"] = day_key
            tenant["day_count"] = 0
            tenant["circuit_open"] = False


def ensure_cli_rate_tenant(state: dict[str, Any], tenant_id: str) -> dict[str, Any]:
    tenants = state.setdefault("tenants", {})
    tenant = tenants.get(tenant_id)
    if not isinstance(tenant, dict):
        tenant = {
            "tenant_id": tenant_id,
            "day_key": current_day_key(),
            "day_count": 0,
            "minute_window": [],
            "circuit_open": False,
            "last_observed": None,
        }
        tenants[tenant_id] = tenant
    tenant.setdefault("minute_window", [])
    tenant.setdefault("day_count", 0)
    tenant.setdefault("day_key", current_day_key())
    tenant.setdefault("circuit_open", False)
    return tenant


def ensure_shared_rate_tenant(state: dict[str, Any], tenant_id: str) -> dict[str, Any]:
    tenants = state.setdefault("tenants", {})
    tenant = tenants.get(tenant_id)
    if not isinstance(tenant, dict):
        tenant = {
            "tenant_id": tenant_id,
            "day_key": current_day_key(),
            "day_count": 0,
            "minute_window": [],
            "circuit_open": False,
            "last_observed": None,
        }
        tenants[tenant_id] = tenant
    tenant.setdefault("tenant_id", tenant_id)
    tenant.setdefault("day_key", current_day_key())
    tenant.setdefault("day_count", 0)
    tenant.setdefault("minute_window", [])
    tenant.setdefault("circuit_open", False)
    return tenant


def header_lookup(headers: Any, name: str) -> str | None:
    if not headers:
        return None
    if hasattr(headers, "get"):
        value = headers.get(name) or headers.get(name.lower())
        return str(value) if value is not None else None
    lower = name.lower()
    for key, value in dict(headers).items():
        if str(key).lower() == lower:
            return str(value)
    return None


def int_header(headers: Any, name: str) -> int | None:
    value = header_lookup(headers, name)
    if value is None or value == "":
        return None
    try:
        return int(float(value))
    except ValueError:
        return None


def acquire_shared_rate_budget(request: urllib.request.Request) -> None:
    if not is_xero_api_url(request.full_url):
        return
    path = shared_rate_limit_store_path()
    tenant_id = request_tenant_id(request)
    now_ms = int(time.time() * 1000)
    with xero_operation_lock.state_guard(path):
        state = load_shared_rate_state(path)
        state["schema_version"] = 1
        state["source"] = "xero-mcp-local-shared"
        state["updated_at"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(now_ms / 1000))
        prune_shared_rate_windows(state, now_ms=now_ms)
        tenant = ensure_shared_rate_tenant(state, tenant_id)
        tenant_day_count = int(tenant.get("day_count") or 0)
        if tenant.get("circuit_open") or tenant_day_count >= int(CLI_RATE_LIMITS["day_limit"]):
            tenant["circuit_open"] = True
            tenant["day_count"] = max(tenant_day_count, int(CLI_RATE_LIMITS["day_limit"]))
            save_shared_rate_state(path, state)
            raise XeroCliError(f"Xero shared day-limit circuit is open for tenant {tenant_id}; inspect `xero rate status --include-cli`.")
        if len(tenant.get("minute_window", [])) >= int(CLI_RATE_LIMITS["max_per_minute"]):
            save_shared_rate_state(path, state)
            raise XeroCliError(f"Xero shared tenant minute budget is exhausted for tenant {tenant_id}; retry after the rolling minute window clears.")
        if len(state.get("app_minute_window", [])) >= int(CLI_RATE_LIMITS["app_minute_limit"]):
            save_shared_rate_state(path, state)
            raise XeroCliError("Xero shared app-wide minute budget is exhausted; retry after the rolling minute window clears.")
        tenant["minute_window"].append(now_ms)
        tenant["day_count"] = tenant_day_count + 1
        tenant["day_key"] = current_day_key()
        state["app_minute_window"].append(now_ms)
        state["last_operation"] = {"source": "xero-cli", "method": request.get_method(), "url": request.full_url, "tenant_id": tenant_id}
        save_shared_rate_state(path, state)


def observe_shared_rate_headers(request: urllib.request.Request, headers: Any, status_code: int | None = None) -> None:
    if not is_xero_api_url(request.full_url):
        return
    path = shared_rate_limit_store_path()
    tenant_id = request_tenant_id(request)
    now_ms = int(time.time() * 1000)
    observed = {
        "observed_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(now_ms / 1000)),
        "source": "xero-cli",
        "tenant_id": tenant_id,
        "status_code": status_code,
        "x-rate-limit-problem": header_lookup(headers, "x-rate-limit-problem"),
        "x-daylimit-remaining": int_header(headers, "x-daylimit-remaining"),
        "x-minlimit-remaining": int_header(headers, "x-minlimit-remaining"),
        "x-appminlimit-remaining": int_header(headers, "x-appminlimit-remaining"),
        "retry-after": header_lookup(headers, "retry-after"),
    }
    with xero_operation_lock.state_guard(path):
        state = load_shared_rate_state(path)
        state["updated_at"] = observed["observed_at"]
        prune_shared_rate_windows(state, now_ms=now_ms)
        tenant = ensure_shared_rate_tenant(state, tenant_id)
        tenant["last_observed"] = observed
        problem = str(observed.get("x-rate-limit-problem") or "").lower()
        day_remaining = observed.get("x-daylimit-remaining")
        if problem == "daylimit" or (isinstance(day_remaining, int) and day_remaining <= 0):
            tenant["circuit_open"] = True
            tenant["day_count"] = max(int(tenant.get("day_count") or 0), int(CLI_RATE_LIMITS["day_limit"]))
        save_shared_rate_state(path, state)


def acquire_cli_rate_slot(request: urllib.request.Request) -> None:
    if not is_xero_api_url(request.full_url):
        return
    acquire_shared_rate_budget(request)
    path = cli_rate_limit_store_path()
    tenant_id = request_tenant_id(request)
    now = utc_seconds()
    with xero_operation_lock.state_guard(path):
        state = load_cli_rate_state(path)
        prune_cli_rate_windows(state, now=now)
        tenant = ensure_cli_rate_tenant(state, tenant_id)
        if tenant.get("circuit_open") or int(tenant.get("day_count") or 0) >= int(CLI_RATE_LIMITS["day_limit"]):
            save_cli_rate_state(path, state)
            raise XeroCliError(f"Xero CLI day-limit circuit is open for tenant {tenant_id}; inspect `xero rate status --include-cli`.")
        if len(tenant.get("minute_window", [])) >= int(CLI_RATE_LIMITS["max_per_minute"]):
            save_cli_rate_state(path, state)
            raise XeroCliError(f"Xero CLI minute budget is exhausted for tenant {tenant_id}; retry after the rolling minute window clears.")
        if len(state.get("app_minute_window", [])) >= int(CLI_RATE_LIMITS["app_minute_limit"]):
            save_cli_rate_state(path, state)
            raise XeroCliError("Xero CLI app-wide minute budget is exhausted; retry after the rolling minute window clears.")
        tenant["minute_window"].append(now)
        tenant["day_count"] = int(tenant.get("day_count") or 0) + 1
        state["app_minute_window"].append(now)
        state["updated_at"] = now
        state["last_operation"] = {"method": request.get_method(), "url": request.full_url, "tenant_id": tenant_id}
        save_cli_rate_state(path, state)


def observe_cli_rate_headers(request: urllib.request.Request, headers: Any, status_code: int | None = None) -> None:
    if not is_xero_api_url(request.full_url):
        return
    observe_shared_rate_headers(request, headers, status_code)
    path = cli_rate_limit_store_path()
    tenant_id = request_tenant_id(request)
    now = utc_seconds()
    observed = {
        "observed_at": now,
        "tenant_id": tenant_id,
        "status_code": status_code,
        "x-rate-limit-problem": header_lookup(headers, "x-rate-limit-problem"),
        "x-daylimit-remaining": int_header(headers, "x-daylimit-remaining"),
        "x-minlimit-remaining": int_header(headers, "x-minlimit-remaining"),
        "x-appminlimit-remaining": int_header(headers, "x-appminlimit-remaining"),
        "retry-after": header_lookup(headers, "retry-after"),
    }
    with xero_operation_lock.state_guard(path):
        state = load_cli_rate_state(path)
        prune_cli_rate_windows(state, now=now)
        tenant = ensure_cli_rate_tenant(state, tenant_id)
        tenant["last_observed"] = observed
        problem = str(observed.get("x-rate-limit-problem") or "").lower()
        day_remaining = observed.get("x-daylimit-remaining")
        if problem == "daylimit" or (isinstance(day_remaining, int) and day_remaining <= 0):
            tenant["circuit_open"] = True
            tenant["day_count"] = max(int(tenant.get("day_count") or 0), int(CLI_RATE_LIMITS["day_limit"]))
        state["updated_at"] = now
        save_cli_rate_state(path, state)


def http_get_bytes(url: str, headers: dict[str, str]) -> tuple[bytes, dict[str, str]]:
    request = urllib.request.Request(url, headers={**headers, "Accept": "*/*"}, method="GET")
    acquire_cli_rate_slot(request)
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            response_headers = dict(response.headers.items())
            observe_cli_rate_headers(request, response_headers, getattr(response, "status", None))
            return response.read(), response_headers
    except urllib.error.HTTPError as exc:
        observe_cli_rate_headers(request, exc.headers, exc.code)
        raw = exc.read().decode("utf-8", errors="replace")
        detail = parse_json(raw) or raw
        raise XeroCliError(f"Xero HTTP {exc.code}: {detail}") from exc
    except urllib.error.URLError as exc:
        raise XeroCliError(f"Xero request failed: {exc}") from exc


def rate_limit_retry_delay(exc: urllib.error.HTTPError, attempt: int) -> float | None:
    """Seconds to wait before retrying a 429, or None to not retry.

    A Xero 429 means the request was rejected *before* processing, so retrying is
    safe even for POSTs. Minute/app-minute limits clear on the rolling window and
    are retried (honouring Retry-After, else exponential backoff); the daily limit
    will not clear within a run, so we fail fast and let the operator act.
    """
    if exc.code != 429:
        return None
    problem = str(header_lookup(exc.headers, "x-rate-limit-problem") or "").lower()
    if problem in {"daylimit", "daily"}:
        return None
    retry_after = header_lookup(exc.headers, "retry-after")
    try:
        delay = float(retry_after) if retry_after else 0.0
    except (TypeError, ValueError):
        delay = 0.0
    if delay <= 0:
        delay = float(2 ** attempt)
    return min(delay, HTTP_RETRY_MAX_DELAY_SECONDS)


def http_json(request: urllib.request.Request) -> Any:
    # Acquire the local rate budget ONCE per logical request. A 429 retry honours
    # the server's Retry-After for the *same* logical request, so re-acquiring per
    # attempt would double-count the day/minute budget and could prematurely open
    # the local day-limit circuit. The slot is taken before the loop; retries reuse it.
    acquire_cli_rate_slot(request)
    attempt = 0
    while True:
        try:
            with urllib.request.urlopen(request, timeout=30) as response:
                raw = response.read().decode("utf-8")
                observe_cli_rate_headers(request, response.headers, getattr(response, "status", None))
            return parse_json(raw) or {}
        except urllib.error.HTTPError as exc:
            observe_cli_rate_headers(request, exc.headers, exc.code)
            delay = rate_limit_retry_delay(exc, attempt)
            if delay is not None and attempt + 1 < HTTP_RETRY_ATTEMPTS:
                attempt += 1
                print(
                    f"[xero] 429 rate limit on {request.get_method()} {request.full_url} — "
                    f"retry {attempt}/{HTTP_RETRY_ATTEMPTS - 1} after {delay:g}s",
                    file=sys.stderr,
                )
                time.sleep(delay)
                continue
            raw = exc.read().decode("utf-8", errors="replace")
            detail = parse_json(raw) or raw
            raise XeroCliError(f"Xero HTTP {exc.code}: {detail}") from exc
        except urllib.error.URLError as exc:
            raise XeroCliError(f"Xero request failed: {exc}") from exc


def parse_json(raw: str) -> Any:
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return None


def find_open_port(preferred_port: int) -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        try:
            sock.bind((DEFAULT_CALLBACK_HOST, preferred_port))
            return preferred_port
        except OSError:
            sock.bind((DEFAULT_CALLBACK_HOST, 0))
            return int(sock.getsockname()[1])


class OAuthCallbackHandler(http.server.BaseHTTPRequestHandler):
    server: "OAuthCallbackServer"

    def log_message(self, _format: str, *_args: Any) -> None:
        return

    def do_GET(self) -> None:  # noqa: N802 - stdlib API
        parsed = urllib.parse.urlparse(self.path)
        params = urllib.parse.parse_qs(parsed.query)
        self.server.callback_path = parsed.path
        self.server.callback_params = {key: values[0] for key, values in params.items() if values}
        message = "Xero authorization captured. You can close this tab."
        self.send_response(200)
        self.send_header("Content-Type", "text/plain; charset=utf-8")
        self.end_headers()
        self.wfile.write(message.encode("utf-8"))


class OAuthCallbackServer(http.server.HTTPServer):
    callback_path: str | None
    callback_params: dict[str, str] | None

    def __init__(self, server_address: tuple[str, int]):
        super().__init__(server_address, OAuthCallbackHandler)
        self.callback_path = None
        self.callback_params = None


def wait_for_callback(port: int, timeout_seconds: int) -> dict[str, str]:
    server = OAuthCallbackServer((DEFAULT_CALLBACK_HOST, port))
    server.timeout = 1
    deadline = time.monotonic() + timeout_seconds
    try:
        while time.monotonic() < deadline:
            server.handle_request()
            if server.callback_params is not None:
                return server.callback_params
    finally:
        server.server_close()
    raise XeroCliError("Timed out waiting for Xero OAuth callback.")


def exchange_authorization_code(*, client_id: str, code: str, redirect_uri: str, code_verifier: str) -> dict[str, Any]:
    return http_post_form(
        TOKEN_URL,
        {
            "grant_type": "authorization_code",
            "client_id": client_id,
            "code": code,
            "redirect_uri": redirect_uri,
            "code_verifier": code_verifier,
        },
    )


def refresh_tokens(payload: dict[str, Any], *, client_id: str | None = None) -> dict[str, Any]:
    refresh_token = str(payload.get("refresh_token") or "").strip()
    if not refresh_token:
        raise XeroCliError("No refresh token is stored. Run `xero auth login` first.")
    resolved_client_id = resolve_client_id(client_id or str(payload.get("client_id") or ""))
    return http_post_form(
        TOKEN_URL,
        {
            "grant_type": "refresh_token",
            "client_id": resolved_client_id,
            "refresh_token": refresh_token,
        },
    )


def token_expiry(token_payload: dict[str, Any]) -> int:
    expires_in = int(token_payload.get("expires_in") or 1800)
    return utc_seconds() + max(5, expires_in - 60)


def merge_token_response(existing: dict[str, Any], token_response: dict[str, Any], *, client_id: str) -> dict[str, Any]:
    merged = dict(existing)
    for key in ("access_token", "refresh_token", "id_token", "token_type", "scope"):
        if token_response.get(key):
            merged[key] = token_response[key]
    merged["client_id"] = client_id
    merged["expires_at"] = token_expiry(token_response)
    merged["updated_at"] = utc_seconds()
    return merged


def ensure_access_token(store: TokenStore) -> dict[str, Any]:
    with xero_operation_lock.state_guard(store.path):
        payload = store.load()
        access_token = str(payload.get("access_token") or "")
        expires_at = int(payload.get("expires_at") or 0)
        if access_token and utc_seconds() < expires_at:
            return payload
        token_response = refresh_tokens(payload)
        merged = merge_token_response(payload, token_response, client_id=str(payload.get("client_id") or ""))
        store.save(merged)
        return merged


def fetch_connections(access_token: str) -> list[dict[str, Any]]:
    payload = http_get_json(CONNECTIONS_URL, {"Authorization": f"Bearer {access_token}"})
    if not isinstance(payload, list):
        raise XeroCliError("Xero connections response was not a list.")
    return [item for item in payload if isinstance(item, dict)]


def command_auth_login(args: argparse.Namespace) -> int:
    client_id = resolve_client_id(args.client_id)
    add_bundles = getattr(args, "add", None)
    granted = None
    if add_bundles:
        try:
            granted = str(TokenStore(token_store_path(args.store)).load().get("scope") or "")
        except (XeroCliError, OSError):
            granted = ""
    scope = resolve_scope_with_bundles(scope=args.scope, add_bundles=add_bundles, granted=granted)
    port = find_open_port(args.port)
    redirect_uri = f"http://{DEFAULT_CALLBACK_HOST}:{port}/callback"
    state = create_state()
    code_verifier = create_code_verifier()
    code_challenge = create_code_challenge(code_verifier)
    query = urllib.parse.urlencode(
        {
            "response_type": "code",
            "client_id": client_id,
            "redirect_uri": redirect_uri,
            "scope": scope,
            "state": state,
            "code_challenge": code_challenge,
            "code_challenge_method": "S256",
        }
    )
    authorize_url = f"{AUTHORIZE_URL}?{query}"

    print("Opening Xero authorization in your browser.")
    print(f"Redirect URI: {redirect_uri}")
    if args.print_url:
        print(authorize_url)
    else:
        webbrowser.open(authorize_url)

    params = wait_for_callback(port, args.timeout)
    if params.get("state") != state:
        raise XeroCliError("OAuth state mismatch. Aborting.")
    if params.get("error"):
        raise XeroCliError(f"Xero authorization failed: {params.get('error')}: {params.get('error_description', '')}")
    code = params.get("code")
    if not code:
        raise XeroCliError("Xero callback did not include an authorization code.")

    token_response = exchange_authorization_code(
        client_id=client_id,
        code=code,
        redirect_uri=redirect_uri,
        code_verifier=code_verifier,
    )
    store = TokenStore(token_store_path(args.store))
    payload = merge_token_response(store.load(), token_response, client_id=client_id)
    connections = fetch_connections(str(payload.get("access_token") or ""))
    payload["tenants"] = connections
    if connections and not payload.get("active_tenant_id"):
        payload["active_tenant_id"] = connections[0].get("tenantId")
    store.save(payload)
    store_info = store.describe()
    write_json(
        {
            "ok": True,
            "token_store": str(store.path),
            "token_store_encrypted": store_info["encrypted"],
            "token_store_mode": store_info["mode"],
            "tenant_count": len(connections),
            "active_tenant_id": payload.get("active_tenant_id"),
        }
    )
    return 0


def command_auth_app_config(args: argparse.Namespace) -> int:
    payload = build_app_config_report(args)
    write_json(payload)
    return 0 if payload["ok"] else 1


def command_auth_status(args: argparse.Namespace) -> int:
    store = TokenStore(token_store_path(args.store))
    payload = store.load()
    store_info = store.describe()
    exists = bool(payload)
    expires_at = int(payload.get("expires_at") or 0) if exists else 0
    status = {
        "ok": exists,
        "token_store": str(store.path),
        "token_store_backup": str(store.backup_path()),
        "token_store_backup_exists": store.backup_path().exists(),
        "token_store_encrypted": store_info["encrypted"],
        "token_store_mode": store_info["mode"],
        "token_store_key_file_exists": store_info["key_file_exists"],
        "has_refresh_token": bool(payload.get("refresh_token")),
        "has_access_token": bool(payload.get("access_token")),
        "access_token_valid": bool(payload.get("access_token")) and utc_seconds() < expires_at,
        "expires_at": expires_at or None,
        "active_tenant_id": payload.get("active_tenant_id"),
        "tenant_count": len(payload.get("tenants") or []),
    }
    if args.verbose:
        status["stored"] = redact_payload(payload)
    write_json(status)
    return 0


def command_auth_refresh(args: argparse.Namespace) -> int:
    store = TokenStore(token_store_path(args.store))
    payload = store.load()
    token_response = refresh_tokens(payload, client_id=args.client_id)
    merged = merge_token_response(payload, token_response, client_id=str(payload.get("client_id") or args.client_id or ""))
    store.save(merged)
    store_info = store.describe()
    write_json(
        {
            "ok": True,
            "token_store": str(store.path),
            "token_store_backup": str(store.backup_path()),
            "token_store_backup_exists": store.backup_path().exists(),
            "token_store_encrypted": store_info["encrypted"],
            "token_store_mode": store_info["mode"],
            "expires_at": merged.get("expires_at"),
        }
    )
    return 0


def command_auth_migrate_store(args: argparse.Namespace) -> int:
    store = TokenStore(token_store_path(args.store))
    before = store.describe()
    payload = store.load()
    store.save(payload)
    after = store.describe()
    write_json(
        {
            "ok": True,
            "token_store": str(store.path),
            "before_encrypted": before["encrypted"],
            "after_encrypted": after["encrypted"],
            "token_store_mode": after["mode"],
            "token_store_key_file_exists": after["key_file_exists"],
        }
    )
    return 0


def command_auth_token(args: argparse.Namespace) -> int:
    store = TokenStore(token_store_path(args.store))
    payload = ensure_access_token(store)
    tenant_id = args.tenant_id or str(payload.get("active_tenant_id") or "")
    if not tenant_id:
        raise XeroCliError("No active tenant selected. Run `xero tenants list --refresh` then `xero tenants use <tenant-id>`.")
    assert_pinned_tenant(tenant_id)
    access_token = str(payload.get("access_token") or "")
    if not access_token:
        raise XeroCliError("No access token is available after refresh.")
    write_json(
        {
            "access_token": access_token,
            "token_type": payload.get("token_type") or "Bearer",
            "tenant_id": tenant_id,
            "expires_at": payload.get("expires_at"),
        }
    )
    return 0


def command_tenants_list(args: argparse.Namespace) -> int:
    store = TokenStore(token_store_path(args.store))
    payload = ensure_access_token(store) if args.refresh else store.load()
    tenants = payload.get("tenants")
    if args.refresh or not isinstance(tenants, list):
        payload = ensure_access_token(store)
        tenants = fetch_connections(str(payload.get("access_token") or ""))
        payload["tenants"] = tenants
        if tenants and not payload.get("active_tenant_id"):
            payload["active_tenant_id"] = tenants[0].get("tenantId")
        store.save(payload)
    write_json(
        {
            "active_tenant_id": payload.get("active_tenant_id"),
            "tenants": tenants or [],
        }
    )
    return 0


def command_tenants_use(args: argparse.Namespace) -> int:
    store = TokenStore(token_store_path(args.store))
    payload = store.load()
    tenants = payload.get("tenants") if isinstance(payload.get("tenants"), list) else []
    tenant_id = args.tenant_id.strip()
    if tenants and not any(item.get("tenantId") == tenant_id for item in tenants if isinstance(item, dict)):
        raise XeroCliError(f"Tenant is not in the stored connection list: {tenant_id}")
    payload["active_tenant_id"] = tenant_id
    store.save(payload)
    write_json({"ok": True, "active_tenant_id": tenant_id})
    return 0


def _profile_token_summary(profile: xero_profiles.Profile) -> dict[str, Any]:
    """Best-effort read of a business's token store for `profiles` output.

    Pins the profile's env (notably the token-store key path) for the read.
    Without this an additional business — encrypted under the shared key but
    stored at a non-default path — would resolve a non-existent business-local
    key, causing `load_fernet` to write a stray key file and fail decryption.
    The env is always restored so callers iterating several profiles are unaffected.
    """
    summary: dict[str, Any] = {"token_store_exists": profile.paths["token_store"].exists()}
    if not summary["token_store_exists"]:
        return summary
    saved = {key: os.environ.get(key) for key in profile.env()}
    os.environ.update(profile.env())
    try:
        payload = TokenStore(profile.paths["token_store"]).load()
    except Exception as exc:  # pragma: no cover - corrupt/locked store
        summary["error"] = str(exc)
        return summary
    finally:
        for key, value in saved.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value
    tenants = payload.get("tenants") if isinstance(payload.get("tenants"), list) else []
    summary["active_tenant_id"] = payload.get("active_tenant_id")
    summary["tenant_count"] = len(tenants)
    summary["tenant_names"] = [
        t.get("tenantName") for t in tenants if isinstance(t, dict) and t.get("tenantName")
    ]
    return summary


def command_profiles_list(args: argparse.Namespace) -> int:
    registry = xero_profiles.load_registry()
    if registry is None:
        profile = xero_profiles.implicit_default_profile()
        write_json(
            {
                "registry": None,
                "note": "No business registry; operating the single legacy default business.",
                "businesses": [{**profile.to_summary(), **_profile_token_summary(profile)}],
            }
        )
        return 0
    active = None
    try:
        active = xero_profiles.resolve_active_profile(getattr(args, "profile", None)).key
    except xero_profiles.ProfileError:
        active = None
    write_json(
        {
            "registry": str(registry.path),
            "active": active,
            "businesses": [
                {
                    **p.to_summary(),
                    "active": p.key == active,
                    **_profile_token_summary(p),
                }
                for p in registry.profiles
            ],
        }
    )
    return 0


def command_profiles_show(args: argparse.Namespace) -> int:
    profile = xero_profiles.resolve_active_profile(getattr(args, "profile", None))
    write_json(
        {
            **profile.to_summary(),
            "env": profile.env(),
            **_profile_token_summary(profile),
        }
    )
    return 0


def command_profiles_add(args: argparse.Namespace) -> int:
    _registry, profile = xero_profiles.upsert_business(
        key=args.key,
        label=args.label,
        legacy=args.legacy,
        root=args.root,
        profile_pack=args.profile_pack,
    )
    write_json({"ok": True, "business": profile.to_summary()})
    return 0


def command_profiles_remove(args: argparse.Namespace) -> int:
    _registry, profile = xero_profiles.remove_business(args.key)
    write_json(
        {
            "ok": True,
            "removed": profile.key,
            "note": "Registry entry removed; token files on disk were left untouched.",
            "token_store": str(profile.paths["token_store"]),
        }
    )
    return 0


def command_profiles_pin_tenant(args: argparse.Namespace) -> int:
    """Record the business's current active tenant as its expected (pinned) org.

    Future token mints / API calls for this profile then assert the active
    tenant matches — a misroute to another org is refused (see assert_pinned_tenant).
    """
    profile = xero_profiles.resolve_active_profile(getattr(args, "profile", None))
    registry = xero_profiles.load_registry()
    if registry is None or registry.get(profile.key) is None:
        raise XeroCliError(
            "pin-tenant requires a registered business; run `xero profiles add` first."
        )
    pin = args.tenant_id
    if not pin:
        summary = _profile_token_summary(profile)  # reads store with key pinned
        pin = summary.get("active_tenant_id")
    if not pin:
        raise XeroCliError(
            f"Business {profile.key!r} has no active tenant to pin. Connect it and run "
            f"`xero --profile {profile.key} tenants use <tenant-id>` first."
        )
    xero_profiles.upsert_business(key=profile.key, legacy=profile.legacy, tenant_id=str(pin))
    write_json(
        {
            "ok": True,
            "key": profile.key,
            "pinned_tenant_id": pin,
            "note": "Future operations on this profile assert the active tenant matches this id.",
        }
    )
    return 0


def command_smoke_organisation(args: argparse.Namespace) -> int:
    store = TokenStore(token_store_path(args.store))
    payload = ensure_access_token(store)
    tenant_id = args.tenant_id or str(payload.get("active_tenant_id") or "")
    if not tenant_id:
        raise XeroCliError("No active tenant selected. Run `xero tenants list --refresh` then `xero tenants use <tenant-id>`.")
    response = http_get_json(
        f"{ACCOUNTING_API_BASE}/Organisation",
        {
            "Authorization": f"Bearer {payload.get('access_token')}",
            "xero-tenant-id": tenant_id,
        },
    )
    organisations = response.get("Organisations") if isinstance(response, dict) else None
    write_json({"ok": True, "tenant_id": tenant_id, "organisations": organisations or []})
    return 0


def command_smoke_accounts(args: argparse.Namespace) -> int:
    store = TokenStore(token_store_path(args.store))
    payload = ensure_access_token(store)
    tenant_id = args.tenant_id or str(payload.get("active_tenant_id") or "")
    if not tenant_id:
        raise XeroCliError("No active tenant selected. Run `xero tenants list --refresh` then `xero tenants use <tenant-id>`.")
    response = http_get_json(
        f"{ACCOUNTING_API_BASE}/Accounts",
        {
            "Authorization": f"Bearer {payload.get('access_token')}",
            "xero-tenant-id": tenant_id,
        },
    )
    accounts = response.get("Accounts") if isinstance(response, dict) else None
    if not isinstance(accounts, list):
        accounts = []
    write_json(
        {
            "ok": True,
            "tenant_id": tenant_id,
            "account_count": len(accounts),
            "accounts": accounts[: args.limit],
            "truncated": len(accounts) > args.limit,
        }
    )
    return 0


def command_rate_status(args: argparse.Namespace) -> int:
    path = rate_limit_store_path(args.rate_store)
    cli_path = cli_rate_limit_store_path(args.cli_rate_store)
    shared_path = shared_rate_limit_store_path(args.shared_rate_store)
    if not path.exists():
        payload = {
            "ok": False,
            "rate_limit_store": str(path),
            "shared_rate_limit_store": str(shared_path),
            "shared_rate_limit": redact_payload(read_json_file_if_exists(shared_path)),
            "message": "No rate-limit status has been written yet. Start the MCP wrapper and make a Xero API call.",
        }
        if args.include_cli:
            payload["cli_rate_limit_store"] = str(cli_path)
            payload["cli_rate_limit"] = redact_payload(read_json_file_if_exists(cli_path))
        write_json(payload)
        return 0
    try:
        with path.open("r", encoding="utf-8") as handle:
            payload = json.load(handle)
    except json.JSONDecodeError as exc:
        raise XeroCliError(f"Rate-limit status store is invalid JSON: {path}: {exc}") from exc
    if not isinstance(payload, dict):
        raise XeroCliError(f"Rate-limit status root must be an object: {path}")
    payload = redact_payload(payload)
    payload.setdefault("ok", True)
    payload["rate_limit_store"] = str(path)
    payload["shared_rate_limit_store"] = str(shared_path)
    payload["shared_rate_limit"] = redact_payload(read_json_file_if_exists(shared_path))
    if args.include_cli:
        payload["cli_rate_limit_store"] = str(cli_path)
        payload["cli_rate_limit"] = redact_payload(read_json_file_if_exists(cli_path))
    write_json(payload)
    return 0


def command_rate_unblock_day_limit(args: argparse.Namespace) -> int:
    path = rate_unblock_store_path(args.unblock_store)
    day_key = args.day_key or time.strftime("%Y-%m-%d", time.gmtime())
    payload = {
        "schema_version": 1,
        "source": "xero-cli",
        "allow_day_limit_bypass": True,
        "day_key": day_key,
        "holder": args.holder,
        "reason": args.reason,
        "created_at": utc_seconds(),
        "message": "This file lets the local MCP governor bypass the in-process day-limit circuit breaker for the specified UTC day.",
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_suffix(path.suffix + ".tmp")
    with tmp_path.open("w", encoding="utf-8") as handle:
        json.dump(payload, handle, indent=2, sort_keys=False)
        handle.write("\n")
    os.chmod(tmp_path, stat.S_IRUSR | stat.S_IWUSR)
    tmp_path.replace(path)
    os.chmod(path, stat.S_IRUSR | stat.S_IWUSR)
    payload["unblock_store"] = str(path)
    write_json(payload)
    return 0


def doctor_check(name: str, ok: bool, severity: str, message: str, **extra: Any) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "name": name,
        "ok": ok,
        "severity": severity,
        "message": message,
    }
    payload.update(extra)
    return payload


def build_doctor_report(args: argparse.Namespace) -> dict[str, Any]:
    checks: list[dict[str, Any]] = []
    next_steps: list[str] = []

    python_path = command_path("python3") or sys.executable
    checks.append(doctor_check("python3", bool(python_path), "required", python_path or "python3 not found"))

    for name in ("node", "npm"):
        found = command_path(name)
        checks.append(doctor_check(name, bool(found), "required", found or f"{name} not found on PATH"))
        if not found:
            next_steps.append(f"Install `{name}` so the official Xero MCP package can run.")

    if Fernet is None:
        checks.append(
            doctor_check(
                "token_store_encryption_support",
                False,
                "required",
                "Python `cryptography` is not installed; encrypted token storage is unavailable.",
            )
        )
        next_steps.append("Install Python `cryptography` before storing Xero OAuth tokens.")
    else:
        checks.append(
            doctor_check(
                "token_store_encryption_support",
                True,
                "required",
                "Python `cryptography` is available.",
            )
        )

    wrapper = local_mcp_wrapper_path()
    checks.append(
        doctor_check(
            "mcp_wrapper",
            wrapper.is_file() and os.access(wrapper, os.X_OK),
            "required",
            str(wrapper),
            executable=os.access(wrapper, os.X_OK) if wrapper.exists() else False,
        )
    )
    if not wrapper.exists():
        next_steps.append("Restore or install the local MCP wrapper at connectors/xero/mcp/xero-mcp-local.")

    manifest = plugin_manifest_path()
    manifest_ok = False
    manifest_name = None
    if manifest.is_file():
        try:
            manifest_payload = parse_json(manifest.read_text(encoding="utf-8"))
            manifest_ok = isinstance(manifest_payload, dict) and manifest_payload.get("name") == "xero"
            manifest_name = manifest_payload.get("name") if isinstance(manifest_payload, dict) else None
        except OSError:
            manifest_ok = False
    checks.append(
        doctor_check(
            "plugin_manifest",
            manifest_ok,
            "required",
            str(manifest),
            plugin_name=manifest_name,
        )
    )
    if not manifest_ok:
        next_steps.append("Validate the repo-local plugin manifest under plugins/xero.")

    mcp_config = plugin_mcp_config_path()
    checks.append(doctor_check("plugin_mcp_config", mcp_config.is_file(), "required", str(mcp_config)))

    template = finance_rules_template_path()
    checks.append(doctor_check("finance_rules_template", template.is_file(), "required", str(template)))

    rules_path = xero_finance_rules.rules_path(args.rules)
    checks.append(
        doctor_check(
            "finance_rules",
            rules_path.is_file(),
            "recommended",
            str(rules_path) if rules_path.exists() else f"Not initialized: {rules_path}",
        )
    )
    if not rules_path.exists():
        next_steps.append("Run `xero rules init` and fill in private account/contact/tax mappings for your organisation.")

    client_id, client_id_source = resolve_client_id_info(args.client_id)
    checks.append(
        doctor_check(
            "xero_client_id",
            bool(client_id),
            "auth",
            f"Configured from {client_id_source}." if client_id else "Missing public Arc Forge Xero OAuth client id.",
            source=client_id_source,
            public_config_paths=[str(path) for path in public_oauth_config_paths()],
        )
    )
    if not client_id:
        next_steps.append("Package the public OAuth client id in plugins/xero/oauth-app.json, run `xero auth configure-app --client-id <id>`, or set `ARC_FORGE_XERO_CLIENT_ID` before `xero auth login`.")

    store = TokenStore(token_store_path(args.store))
    token_payload: dict[str, Any] = {}
    store_error = None
    try:
        token_payload = store.load()
        store_info = store.describe()
    except XeroCliError as exc:
        store_info = {"path": str(store.path), "encrypted": False, "mode": None, "key_file_exists": None}
        store_error = str(exc)
    token_exists = store.path.exists() and store_error is None and bool(token_payload)
    checks.append(
        doctor_check(
            "token_store",
            token_exists,
            "auth",
            str(store.path) if token_exists else store_error or f"No token store yet: {store.path}",
            backup=str(store.backup_path()),
            backup_exists=store.backup_path().exists(),
        )
    )
    checks.append(
        doctor_check(
            "token_store_encrypted",
            bool(store_info.get("encrypted")),
            "auth",
            "Encrypted token store." if store_info.get("encrypted") else "Token store is not encrypted yet.",
            mode=store_info.get("mode"),
            key_file_exists=store_info.get("key_file_exists"),
        )
    )
    if store_error:
        next_steps.append("Fix or remove the invalid local Xero token store, then run `xero auth login` again.")
    elif not token_exists:
        next_steps.append("Run `xero auth login`, complete Xero MFA/consent in the browser, then rerun `xero doctor`.")
    elif not store_info.get("encrypted"):
        next_steps.append("Run `xero auth migrate-store` to rewrite the local token store using encrypted mode.")

    has_refresh = bool(token_payload.get("refresh_token"))
    has_access = bool(token_payload.get("access_token"))
    expires_at = int(token_payload.get("expires_at") or 0) if token_payload else 0
    checks.append(doctor_check("refresh_token", has_refresh, "auth", "Present." if has_refresh else "Missing refresh token."))
    checks.append(
        doctor_check(
            "access_token",
            has_access,
            "auth",
            "Present." if has_access else "Missing access token.",
            valid=has_access and utc_seconds() < expires_at,
            expires_at=expires_at or None,
        )
    )

    tenants = token_payload.get("tenants")
    tenant_count = len(tenants) if isinstance(tenants, list) else 0
    active_tenant = str(token_payload.get("active_tenant_id") or "")
    checks.append(
        doctor_check(
            "active_tenant",
            bool(active_tenant),
            "auth",
            active_tenant or "No active tenant selected.",
            tenant_count=tenant_count,
        )
    )
    if token_exists and not active_tenant:
        next_steps.append("Run `xero tenants list --refresh` and `xero tenants use <tenant-id>`.")

    rate_path = rate_limit_store_path(args.rate_store)
    checks.append(
        doctor_check(
            "rate_limit_status",
            rate_path.is_file(),
            "recommended",
            str(rate_path) if rate_path.exists() else "No rate-limit snapshot has been written yet.",
        )
    )

    required_ok = all(item["ok"] for item in checks if item["severity"] == "required")
    auth_ok = all(item["ok"] for item in checks if item["severity"] == "auth")
    warnings = [item for item in checks if item["severity"] == "recommended" and not item["ok"]]
    failures = [item for item in checks if item["severity"] in {"required", "auth"} and not item["ok"]]
    return {
        "ok": required_ok and auth_ok,
        "base_ok": required_ok,
        "auth_ok": auth_ok,
        "token_store": str(store.path),
        "checks": checks,
        "summary": {
            "failed_required_or_auth": len(failures),
            "warnings": len(warnings),
        },
        "next_steps": list(dict.fromkeys(next_steps)),
    }


def command_doctor(args: argparse.Namespace) -> int:
    report = build_doctor_report(args)
    write_json(report)
    return 0 if report["ok"] or not args.strict else 1


def command_rules_init(args: argparse.Namespace) -> int:
    path = xero_finance_rules.rules_path(args.rules)
    payload = xero_finance_rules.init_rules(path, force=args.force)
    write_json({"ok": True, "rules": str(path), "schema_version": payload.get("schema_version")})
    return 0


def command_rules_validate(args: argparse.Namespace) -> int:
    path = xero_finance_rules.rules_path(args.rules)
    rules = xero_finance_rules.load_rules(path)
    result = xero_finance_rules.validate_rules(rules)
    write_json({"ok": result.ok, "rules": str(path), "errors": result.errors, "warnings": result.warnings})
    return 0 if result.ok else 1


def command_rules_parse_name(args: argparse.Namespace) -> int:
    rules = xero_finance_rules.load_rules(xero_finance_rules.rules_path(args.rules))
    write_json(xero_finance_rules.parse_name(args.value, rules))
    return 0


def command_rules_map(args: argparse.Namespace) -> int:
    rules = xero_finance_rules.load_rules(xero_finance_rules.rules_path(args.rules))
    write_json(xero_finance_rules.resolve_mapping(args.kind, args.value, rules))
    return 0


def load_target_payload(args: argparse.Namespace) -> dict[str, Any]:
    if bool(args.target_json) == bool(args.target_file):
        raise XeroCliError("Provide exactly one of --target-json or --target-file.")
    if args.target_file:
        payload = xero_finance_rules.load_json_file(Path(args.target_file).expanduser().resolve())
    else:
        try:
            payload = json.loads(args.target_json)
        except json.JSONDecodeError as exc:
            raise XeroCliError(f"Invalid --target-json: {exc}") from exc
    if not isinstance(payload, dict):
        raise XeroCliError("Mapping target must be a JSON object.")
    return payload


def command_rules_upsert_mapping(args: argparse.Namespace) -> int:
    path = xero_finance_rules.rules_path(args.rules)
    target = load_target_payload(args)
    result = xero_finance_rules.upsert_mapping(
        path,
        kind=args.kind,
        name=args.name,
        aliases=args.alias or [],
        patterns=args.pattern or [],
        target=target,
        source=args.source,
        note=args.note,
    )
    write_json(result)
    return 0


def command_audit_dry_run(args: argparse.Namespace) -> int:
    rules = xero_finance_rules.load_rules(xero_finance_rules.rules_path(args.rules))
    candidates = xero_finance_rules.load_candidates(Path(args.candidates).expanduser().resolve())
    report = xero_finance_rules.build_dry_run_report(
        candidates,
        rules,
        xero_finance_rules.snapshot_dir(args.snapshots),
        max_batch_size=args.max_batch_size,
    )
    if args.out:
        out_path = Path(args.out).expanduser().resolve()
        xero_finance_rules.write_json_file(out_path, report)
        write_json({"ok": True, "report": str(out_path), "summary": report.get("summary")})
    else:
        write_json(report)
    return 0


def xero_where_string(value: str) -> str:
    return str(value).replace("\\", "\\\\").replace('"', '\\"')


def live_check_query(kind: str, value: str, *, field: str | None = None) -> str:
    if kind not in LIVE_CHECK_KINDS:
        raise XeroCliError(f"Unsupported live check kind: {kind}")
    config = LIVE_CHECK_KINDS[kind]
    resolved_field = field or str(config["field"])
    clauses = [f'{resolved_field}=="{xero_where_string(value)}"']
    if config.get("type"):
        clauses.insert(0, f'Type=="{config["type"]}"')
    return "&&".join(clauses)


def normalize_report_kind(kind: str) -> str:
    value = kind.strip().lower()
    if value in REPORT_KINDS:
        return value
    for name, config in REPORT_KINDS.items():
        if value in config.get("aliases", []):
            return name
    raise XeroCliError(f"Unsupported report kind: {kind}")


def report_query_params(args: argparse.Namespace, config: dict[str, Any]) -> dict[str, str]:
    raw = {
        "date": args.date,
        "fromDate": args.from_date,
        "toDate": args.to_date,
        "periods": str(args.periods) if args.periods is not None else None,
        "timeframe": args.timeframe,
        "standardLayout": "true" if args.standard_layout else None,
        "paymentsOnly": "true" if args.payments_only else None,
        "contactID": args.contact_id,
        "trackingCategoryID": getattr(args, "tracking_category_id", None),
        "trackingOptionID": getattr(args, "tracking_option_id", None),
        "trackingCategoryID2": getattr(args, "tracking_category_id2", None),
        "trackingOptionID2": getattr(args, "tracking_option_id2", None),
    }
    allowed = set(config["allowed_params"])
    return {key: value for key, value in raw.items() if key in allowed and value}


def accounting_headers(payload: dict[str, Any], tenant_id: str) -> dict[str, str]:
    return {
        "Authorization": f"Bearer {payload.get('access_token')}",
        "xero-tenant-id": tenant_id,
    }


def resolve_active_auth(args: argparse.Namespace) -> tuple[dict[str, Any], str]:
    store = TokenStore(token_store_path(args.store))
    payload = ensure_access_token(store)
    tenant_id = args.tenant_id or str(payload.get("active_tenant_id") or "")
    if not tenant_id:
        raise XeroCliError("No active tenant selected. Run `xero tenants list --refresh` then `xero tenants use <tenant-id>`.")
    assert_pinned_tenant(tenant_id)
    return payload, tenant_id


def command_reports_get(args: argparse.Namespace) -> int:
    kind = normalize_report_kind(args.kind)
    config = REPORT_KINDS[kind]
    payload, tenant_id = resolve_active_auth(args)
    query = report_query_params(args, config)
    suffix = "?" + urllib.parse.urlencode(query) if query else ""
    endpoint = str(config["endpoint"])
    response = http_get_json(
        f"{ACCOUNTING_API_BASE}/{endpoint}{suffix}",
        accounting_headers(payload, tenant_id),
    )
    reports = response.get("Reports") if isinstance(response, dict) else None
    if not isinstance(reports, list):
        reports = []
    write_json(
        {
            "ok": True,
            "kind": kind,
            "endpoint": endpoint,
            "tenant_id": tenant_id,
            "params": query,
            "report_count": len(reports),
            "reports": reports,
        }
    )
    return 0


def _budget_query_params(args: argparse.Namespace) -> dict[str, str]:
    """Optional Xero Budgets query params. DateFrom/DateTo bound the returned
    budget periods; IDs filters the list to specific BudgetIDs."""
    raw = {
        "DateFrom": getattr(args, "date_from", None),
        "DateTo": getattr(args, "date_to", None),
        "IDs": getattr(args, "ids", None),
    }
    return {key: value for key, value in raw.items() if value}


def command_budgets_list(args: argparse.Namespace) -> int:
    """List budgets (BudgetID, Type, Description, UpdatedDateUTC). Read-only.

    Xero exposes Budgets as GET-only; there is no create/update budget endpoint
    (budgets are edited in the Budget Manager UI). Requires accounting.budgets.read.
    """
    payload, tenant_id = resolve_active_auth(args)
    query = _budget_query_params(args)
    suffix = "?" + urllib.parse.urlencode(query) if query else ""
    response = http_get_json(
        f"{ACCOUNTING_API_BASE}/Budgets{suffix}",
        accounting_headers(payload, tenant_id),
    )
    budgets = response.get("Budgets") if isinstance(response, dict) else None
    if not isinstance(budgets, list):
        budgets = []
    write_json(
        {
            "ok": True,
            "tenant_id": tenant_id,
            "params": query,
            "budget_count": len(budgets),
            "budgets": budgets,
        }
    )
    return 0


def command_budgets_get(args: argparse.Namespace) -> int:
    """Fetch one budget with its per-account, per-period budget lines. Read-only.

    DateFrom/DateTo bound the returned periods. Requires accounting.budgets.read.
    """
    budget_id = str(args.budget_id).strip()
    if not budget_id:
        raise XeroCliError("budgets get requires a BudgetID.")
    payload, tenant_id = resolve_active_auth(args)
    query = _budget_query_params(args)
    suffix = "?" + urllib.parse.urlencode(query) if query else ""
    response = http_get_json(
        f"{ACCOUNTING_API_BASE}/Budgets/{urllib.parse.quote(budget_id, safe='')}{suffix}",
        accounting_headers(payload, tenant_id),
    )
    budgets = response.get("Budgets") if isinstance(response, dict) else None
    budget = budgets[0] if isinstance(budgets, list) and budgets else None
    write_json(
        {
            "ok": True,
            "tenant_id": tenant_id,
            "budget_id": budget_id,
            "params": query,
            "budget": budget,
        }
    )
    return 0


def fetch_all_accounts(payload: dict[str, Any], tenant_id: str) -> list[dict[str, Any]]:
    """GET the full chart of accounts (not paged — Accounts returns all at once)."""
    response = http_get_json(
        f"{ACCOUNTING_API_BASE}/Accounts", accounting_headers(payload, tenant_id)
    )
    accounts = response.get("Accounts") if isinstance(response, dict) else None
    return accounts if isinstance(accounts, list) else []


def fetch_journals(
    payload: dict[str, Any],
    tenant_id: str,
    *,
    to_date: str | None = None,
    max_pages: int = 500,
) -> list[dict[str, Any]]:
    """Page the general-ledger /Journals endpoint (100/page, ordered by JournalNumber).

    Xero has no server-side date filter on Journals and orders by JournalNumber
    (entry order), NOT by JournalDate. A journal backdated into the export window
    but entered later carries a higher JournalNumber and lands on a later page.
    Therefore the entire history up to the last journal must be scanned — a
    date-based early-stop would silently drop in-window backdated journals.

    We page until an empty or short page (natural end of history) or until
    ``max_pages`` is reached (cap-hit triggers a warning). The ``to_date``
    parameter is kept for API-compatibility but is no longer used for early
    termination. Precise date filtering happens in xero_exports.normalize_journals.

    ``max_pages`` defaults to 500 (50 000 journals), enough for several years of
    typical SME history with headroom. Raise it via the CLI if needed.
    """
    headers = accounting_headers(payload, tenant_id)
    collected: list[dict[str, Any]] = []
    offset = 0
    for _ in range(max_pages):
        url = f"{ACCOUNTING_API_BASE}/Journals?offset={offset}"
        response = http_get_json(url, headers)
        batch = response.get("Journals") if isinstance(response, dict) else None
        if not isinstance(batch, list) or not batch:
            break
        collected.extend(batch)
        offset = max(int(j.get("JournalNumber") or 0) for j in batch)
        if len(batch) < 100:
            break
    else:
        print(
            f"[xero] WARNING: hit Journals page cap ({max_pages}); export may be truncated",
            file=sys.stderr,
        )
    return collected


def _parse_segment_map(value: str | None) -> dict[str, str]:
    if not value:
        return {}
    try:
        parsed = json.loads(value)
    except json.JSONDecodeError as exc:
        raise XeroCliError(f"--segment-map must be a JSON object: {exc}") from exc
    if not isinstance(parsed, dict):
        raise XeroCliError("--segment-map must be a JSON object mapping option name → label.")
    return {str(k): str(v) for k, v in parsed.items()}


def _today_iso() -> str:
    return time.strftime("%Y-%m-%d", time.gmtime())


def command_reports_export_pnl_tracking(args: argparse.Namespace) -> int:
    if not args.from_date or not args.to_date:
        raise XeroCliError("export-pnl-tracking requires --from-date and --to-date.")
    if not args.tracking_category_id:
        raise XeroCliError("export-pnl-tracking requires --tracking-category-id.")
    payload, tenant_id = resolve_active_auth(args)
    query = {
        "fromDate": args.from_date,
        "toDate": args.to_date,
        "trackingCategoryID": args.tracking_category_id,
    }
    if getattr(args, "tracking_option_id", None):
        query["trackingOptionID"] = args.tracking_option_id
    suffix = "?" + urllib.parse.urlencode(query)
    response = http_get_json(
        f"{ACCOUNTING_API_BASE}/Reports/ProfitAndLoss{suffix}",
        accounting_headers(payload, tenant_id),
    )
    reports = response.get("Reports") if isinstance(response, dict) else None
    if not isinstance(reports, list) or not reports:
        raise XeroCliError("ProfitAndLoss returned no report; check the date range and tracking category.")
    accounts = fetch_all_accounts(payload, tenant_id)
    exported_at = args.exported_at or _today_iso()
    rows, reconciliation = xero_exports.flatten_pnl_tracking(
        reports[0],
        accounts,
        period_start=args.from_date,
        period_end=args.to_date,
        segment_map=_parse_segment_map(args.segment_map),
        untracked_label=args.untracked_label,
        source_report=args.source_report,
        exported_at=exported_at,
        note=args.note or "",
        skip_zero=not args.include_zero,
    )
    tolerance = Decimal(str(args.reconcile_tolerance))
    breaches = xero_exports.reconciliation_breaches(reconciliation, tolerance)
    out_path = Path(args.out).expanduser().resolve()
    if breaches and not args.allow_reconcile_mismatch:
        write_json({
            "ok": False,
            "error": "reconciliation_failed",
            "tolerance": str(tolerance),
            "breaches": breaches,
            "reconciliation": reconciliation,
            "out": str(out_path),
            "written": False,
        })
        return 1
    xero_exports.write_csv(out_path, xero_exports.PNL_TRACKING_FIELDS, rows)
    write_json({
        "ok": True,
        "out": str(out_path),
        "tenant_id": tenant_id,
        "period": {"from": args.from_date, "to": args.to_date},
        "row_count": len(rows),
        "reconciliation": reconciliation,
        "reconcile_tolerance": str(tolerance),
        "reconcile_breaches": breaches,
    })
    return 0


def command_journals_export(args: argparse.Namespace) -> int:
    if not args.from_date or not args.to_date:
        raise XeroCliError("journals export requires --from-date and --to-date.")
    payload, tenant_id = resolve_active_auth(args)
    journals = fetch_journals(payload, tenant_id, to_date=args.to_date)
    accounts = fetch_all_accounts(payload, tenant_id)
    exported_at = args.exported_at or _today_iso()
    rows, reconciliation = xero_exports.normalize_journals(
        journals,
        accounts,
        from_date=args.from_date,
        to_date=args.to_date,
        category_id=args.tracking_category_id or "",
        account_ids=set(args.account_id or []),
        segment_map=_parse_segment_map(args.segment_map),
        untracked_label=args.untracked_label,
        source_report=args.source_report,
        exported_at=exported_at,
        note=args.note or "",
        pnl_only=not args.all_accounts,
    )
    out_path = Path(args.out).expanduser().resolve()
    xero_exports.write_csv(out_path, xero_exports.ACCOUNT_TRANSACTION_FIELDS, rows)
    reconciliation_note = (
        "RECONCILIATION REQUIRED: caller must reconcile reconciliation.by_account_segment "
        "net totals against the P&L-by-tracking export per account/segment within $0.02 "
        "before trusting this file. The comparison is SIGN-AWARE because the two exports "
        "use different conventions: this export signs revenue positive and costs negative, "
        "while the P&L-by-tracking export keeps Xero's positive-amount convention for both. "
        "So: for REVENUE accounts, journals net_amount == P&L amount; for cost accounts "
        "(account_class DIRECTCOSTS/EXPENSE), journals net_amount == -(P&L amount) — negate "
        "the P&L cost amount before comparing. This export does not self-verify."
    )
    print(
        f"[xero] WARNING: {reconciliation_note}",
        file=sys.stderr,
    )
    write_json({
        "ok": True,
        "out": str(out_path),
        "tenant_id": tenant_id,
        "period": {"from": args.from_date, "to": args.to_date},
        "journals_fetched": len(journals),
        "row_count": len(rows),
        "reconciliation_required": True,
        "reconciliation_note": reconciliation_note,
        "reconciliation": reconciliation,
    })
    return 0


def fetch_payments(
    payload: dict[str, Any],
    tenant_id: str,
    *,
    from_date: str = "",
    to_date: str = "",
) -> list[dict[str, Any]]:
    """Page the /Payments endpoint (100/page), optionally date-windowed on the
    payment Date. Read-only."""
    headers = accounting_headers(payload, tenant_id)
    where_parts: list[str] = []
    for op, value in (("Date>=", from_date), ("Date<=", to_date)):
        value = (value or "").strip()
        if not value:
            continue
        year, month, day = (int(part) for part in value.split("-"))
        where_parts.append(f"{op}DateTime({year},{month},{day})")
    where = "&&".join(where_parts)
    return paged_accounting_get("Payments", "Payments", headers, where=where)


def command_payments_export(args: argparse.Namespace) -> int:
    payload, tenant_id = resolve_active_auth(args)
    payments = fetch_payments(
        payload, tenant_id, from_date=args.from_date or "", to_date=args.to_date or ""
    )
    exported_at = args.exported_at or _today_iso()
    rows = xero_exports.normalize_payments(
        payments,
        from_date=args.from_date or "",
        to_date=args.to_date or "",
        source_report=args.source_report or "Xero payments export",
        exported_at=exported_at,
        note=args.note or "",
        include_deleted=bool(getattr(args, "include_deleted", False)),
    )
    out_path = Path(args.out).expanduser().resolve()
    xero_exports.write_csv(out_path, xero_exports.PAYMENT_FIELDS, rows)
    write_json({
        "ok": True,
        "out": str(out_path),
        "tenant_id": tenant_id,
        "period": {"from": args.from_date, "to": args.to_date},
        "payments_fetched": len(payments),
        "row_count": len(rows),
    })
    return 0


def fetch_bank_transactions(
    payload: dict[str, Any], tenant_id: str, *, from_date: str = "", to_date: str = ""
) -> list[dict[str, Any]]:
    """Page /BankTransactions (Spend/Receive Money — actual cash), 100/page,
    optionally date-windowed. Read-only."""
    headers = accounting_headers(payload, tenant_id)
    where_parts: list[str] = []
    for op, value in (("Date>=", from_date), ("Date<=", to_date)):
        value = (value or "").strip()
        if not value:
            continue
        year, month, day = (int(part) for part in value.split("-"))
        where_parts.append(f"{op}DateTime({year},{month},{day})")
    where = "&&".join(where_parts)
    return paged_accounting_get("BankTransactions", "BankTransactions", headers, where=where)


def command_banktransactions_export(args: argparse.Namespace) -> int:
    payload, tenant_id = resolve_active_auth(args)
    txns = fetch_bank_transactions(
        payload, tenant_id, from_date=args.from_date or "", to_date=args.to_date or ""
    )
    accounts = fetch_all_accounts(payload, tenant_id)
    exported_at = args.exported_at or _today_iso()
    rows = xero_exports.normalize_bank_transactions(
        txns, accounts, exported_at=exported_at, note=args.note or "",
        from_date=args.from_date or "", to_date=args.to_date or "",
    )
    out_path = Path(args.out).expanduser().resolve()
    xero_exports.write_csv(out_path, xero_exports.BANK_TRANSACTION_FIELDS, rows)
    write_json({
        "ok": True,
        "out": str(out_path),
        "tenant_id": tenant_id,
        "period": {"from": args.from_date, "to": args.to_date},
        "transactions_fetched": len(txns),
        "line_rows": len(rows),
    })
    return 0


def fetch_outstanding_invoices(
    payload: dict[str, Any], tenant_id: str, *, invoice_type: str
) -> list[dict[str, Any]]:
    """Page approved, unpaid invoices/bills of the given type (ACCREC or ACCPAY)
    with AmountDue > 0. Read-only; summary records (no line items)."""
    headers = accounting_headers(payload, tenant_id)
    where = f'Type=="{invoice_type}"&&Status=="AUTHORISED"&&AmountDue>0'
    return paged_accounting_get("Invoices", "Invoices", headers, where=where)


def _command_aged_export(args: argparse.Namespace, *, kind: str) -> int:
    invoice_type = "ACCREC" if kind == "receivable" else "ACCPAY"
    payload, tenant_id = resolve_active_auth(args)
    invoices = fetch_outstanding_invoices(payload, tenant_id, invoice_type=invoice_type)
    as_at = args.as_at_date or _today_iso()
    exported_at = args.exported_at or _today_iso()
    default_report = (
        "Xero outstanding receivables (built from /Invoices)"
        if kind == "receivable"
        else "Xero outstanding payables (built from /Invoices)"
    )
    rows = xero_exports.normalize_aged_invoices(
        invoices,
        as_at_date=as_at,
        kind=kind,
        source_report=args.source_report or default_report,
        exported_at=exported_at,
        note=args.note or "",
    )
    fields = (
        xero_exports.AGED_RECEIVABLE_FIELDS
        if kind == "receivable"
        else xero_exports.AGED_PAYABLE_FIELDS
    )
    out_path = Path(args.out).expanduser().resolve()
    xero_exports.write_csv(out_path, fields, rows)
    total = sum((xero_exports.parse_money(row["amount_due"]) for row in rows), xero_exports.parse_money("0"))
    buckets = {key: xero_exports.parse_money("0") for key in ("current", "one_month", "two_months", "three_months_or_more")}
    for row in rows:
        for key in buckets:
            buckets[key] += xero_exports.parse_money(row[key])
    write_json({
        "ok": True,
        "out": str(out_path),
        "tenant_id": tenant_id,
        "kind": kind,
        "as_at_date": as_at,
        "invoices_fetched": len(invoices),
        "row_count": len(rows),
        "total_amount_due": xero_exports.money_str(total),
        "bucket_totals": {key: xero_exports.money_str(value) for key, value in buckets.items()},
    })
    return 0


def command_aged_receivables_export(args: argparse.Namespace) -> int:
    return _command_aged_export(args, kind="receivable")


def command_aged_payables_export(args: argparse.Namespace) -> int:
    return _command_aged_export(args, kind="payable")


def evidence_config(kind: str) -> dict[str, str]:
    value = kind.strip().lower()
    if value not in EVIDENCE_OBJECT_KINDS:
        raise XeroCliError(f"Unsupported evidence object kind: {kind}")
    return EVIDENCE_OBJECT_KINDS[value]


def evidence_base_path(kind: str, object_id: str) -> str:
    config = evidence_config(kind)
    object_id = object_id.strip()
    if not object_id:
        raise XeroCliError("Object id is required.")
    return f"{config['endpoint']}/{urllib.parse.quote(object_id, safe='')}"


def evidence_filename(value: str | None, file_path: Path | None = None) -> str:
    name = (value or "").strip()
    if not name and file_path is not None:
        name = file_path.name
    if not name:
        raise XeroCliError("Attachment filename is required.")
    if "/" in name or "\\" in name:
        raise XeroCliError("Attachment filename must not contain path separators.")
    return name


def command_evidence_history_get(args: argparse.Namespace) -> int:
    payload, tenant_id = resolve_active_auth(args)
    endpoint = f"{evidence_base_path(args.kind, args.object_id)}/History"
    response = http_get_json(f"{ACCOUNTING_API_BASE}/{endpoint}", accounting_headers(payload, tenant_id))
    records = response.get("HistoryRecords") if isinstance(response, dict) else None
    if not isinstance(records, list):
        records = []
    write_json(
        {
            "ok": True,
            "kind": args.kind,
            "object_id": args.object_id,
            "tenant_id": tenant_id,
            "history_count": len(records),
            "history": records,
        }
    )
    return 0


def command_evidence_history_add_note(args: argparse.Namespace) -> int:
    payload, tenant_id = resolve_active_auth(args)
    details = args.details.strip()
    if not details:
        raise XeroCliError("History note details must not be empty.")
    endpoint = f"{evidence_base_path(args.kind, args.object_id)}/History"
    request_payload = {"HistoryRecords": [{"Details": details}]}
    response = http_send_json("PUT", f"{ACCOUNTING_API_BASE}/{endpoint}", accounting_headers(payload, tenant_id), request_payload)
    write_json(
        {
            "ok": True,
            "kind": args.kind,
            "object_id": args.object_id,
            "tenant_id": tenant_id,
            "response": redact_payload(response),
        }
    )
    return 0


def command_evidence_attachments_list(args: argparse.Namespace) -> int:
    payload, tenant_id = resolve_active_auth(args)
    endpoint = f"{evidence_base_path(args.kind, args.object_id)}/Attachments"
    response = http_get_json(f"{ACCOUNTING_API_BASE}/{endpoint}", accounting_headers(payload, tenant_id))
    attachments = response.get("Attachments") if isinstance(response, dict) else None
    if not isinstance(attachments, list):
        attachments = []
    write_json(
        {
            "ok": True,
            "kind": args.kind,
            "object_id": args.object_id,
            "tenant_id": tenant_id,
            "attachment_count": len(attachments),
            "attachments": attachments,
        }
    )
    return 0


def command_evidence_attachments_upload(args: argparse.Namespace) -> int:
    payload, tenant_id = resolve_active_auth(args)
    file_path = Path(args.file).expanduser().resolve()
    if not file_path.is_file():
        raise XeroCliError(f"Attachment file does not exist: {file_path}")
    filename = evidence_filename(args.filename, file_path)
    content_type = args.content_type or mimetypes.guess_type(filename)[0] or "application/octet-stream"
    endpoint = f"{evidence_base_path(args.kind, args.object_id)}/Attachments/{urllib.parse.quote(filename, safe='')}"
    body = file_path.read_bytes()
    response = http_send_bytes("POST", f"{ACCOUNTING_API_BASE}/{endpoint}", accounting_headers(payload, tenant_id), body, content_type=content_type)
    write_json(
        {
            "ok": True,
            "kind": args.kind,
            "object_id": args.object_id,
            "tenant_id": tenant_id,
            "filename": filename,
            "content_type": content_type,
            "byte_count": len(body),
            "response": redact_payload(response),
        }
    )
    return 0


def command_evidence_attachments_download(args: argparse.Namespace) -> int:
    payload, tenant_id = resolve_active_auth(args)
    filename = evidence_filename(args.filename)
    endpoint = f"{evidence_base_path(args.kind, args.object_id)}/Attachments/{urllib.parse.quote(filename, safe='')}"
    body, headers = http_get_bytes(f"{ACCOUNTING_API_BASE}/{endpoint}", accounting_headers(payload, tenant_id))
    out_path = Path(args.out).expanduser().resolve()
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_bytes(body)
    write_json(
        {
            "ok": True,
            "kind": args.kind,
            "object_id": args.object_id,
            "tenant_id": tenant_id,
            "filename": filename,
            "out": str(out_path),
            "byte_count": len(body),
            "content_type": headers.get("Content-Type") or headers.get("content-type"),
        }
    )
    return 0


# ---------------------------------------------------------------------------
# Evidence audit + backfill (attachments-everywhere — Phase 1)
# ---------------------------------------------------------------------------

# Max per Xero attachment + per-object cap (verified against the Files/
# Attachments docs, 2026-06-10). Enforced client-side so a backfill fails in
# dry-run rather than mid-batch.
MAX_ATTACHMENT_BYTES = 10 * 1024 * 1024
MAX_ATTACHMENTS_PER_OBJECT = 10

# Object kinds the evidence sweep can page over (endpoint -> response root key).
EVIDENCE_AUDIT_KINDS: dict[str, dict[str, str]] = {
    "bill": {"endpoint": "Invoices", "root": "Invoices", "where": 'Type=="ACCPAY"'},
    "invoice": {"endpoint": "Invoices", "root": "Invoices", "where": 'Type=="ACCREC"'},
    "bank-transaction": {"endpoint": "BankTransactions", "root": "BankTransactions", "where": ""},
}


def xero_iso_date_from_value(value: Any) -> str | None:
    """Convert a single Xero date value to YYYY-MM-DD.

    Handles both wire formats Xero emits:
      * MS-JSON: ``/Date(1745971200000+0000)/`` (Organisation lock dates, etc.)
      * ISO/date-string: ``2026-06-30`` or ``2026-06-30T00:00:00``

    Returns None for empty/unparseable input. Used for scalar date fields such as
    ``PeriodLockDate`` that are NOT wrapped in a dict (cf. xero_object_iso_date).
    """
    if not isinstance(value, str):
        return None
    raw = value.strip()
    if not raw:
        return None
    # MS-JSON epoch-millis format first (its leading chars are not ISO digits).
    # Accept an optional leading '-' (pre-epoch) and an optional ±HHMM offset.
    match = re.search(r"/Date\((-?\d+)(?:([+-])(\d{2})(\d{2}))?\)", raw)
    if match:
        millis = int(match.group(1))
        if match.group(2):  # apply the ±HHMM timezone offset to the epoch
            sign = 1 if match.group(2) == "+" else -1
            offset_ms = sign * (int(match.group(3)) * 60 + int(match.group(4))) * 60 * 1000
            millis += offset_ms
        return time.strftime("%Y-%m-%d", time.gmtime(millis / 1000))
    # Already ISO-ish: leading YYYY then a date.
    if len(raw) >= 10 and raw[:4].isdigit():
        return raw[:10]
    return None


def xero_object_iso_date(obj: dict[str, Any]) -> str | None:
    """Return an object's date as YYYY-MM-DD from DateString or /Date(ms)/."""
    date_string = obj.get("DateString") or obj.get("Date") if isinstance(obj, dict) else None
    if isinstance(date_string, str) and len(date_string) >= 10 and date_string[:4].isdigit():
        return date_string[:10]
    raw = obj.get("Date") if isinstance(obj, dict) else None
    if isinstance(raw, str):
        match = re.search(r"/Date\((\d+)", raw)
        if match:
            return time.strftime("%Y-%m-%d", time.gmtime(int(match.group(1)) / 1000))
    return None


def paged_accounting_get(
    endpoint: str, root_key: str, headers: dict[str, str], *, where: str = "", max_pages: int = 50
) -> list[dict[str, Any]]:
    """Page through a where-filtered Accounting endpoint (100 records/page).

    Stops at ``max_pages``. If the final fetched page is still full (==100), the
    result set was likely truncated by the cap — warns on stderr so a missed
    record (e.g. a supplier whose PaymentTerms never get captured) isn't silent.
    """
    items: list[dict[str, Any]] = []
    page = 1
    truncated = False
    while page <= max_pages:
        url = f"{ACCOUNTING_API_BASE}/{endpoint}?page={page}"
        if where:
            url += "&where=" + urllib.parse.quote(where)
        response = http_get_json(url, headers)
        batch = response.get(root_key) if isinstance(response, dict) else None
        if not isinstance(batch, list) or not batch:
            break
        items.extend(batch)
        if len(batch) < 100:
            break
        if page == max_pages:
            # Last allowed page came back full → there are almost certainly more.
            truncated = True
            break
        page += 1
    if truncated:
        print(
            f"WARNING: {endpoint} paged GET hit the {max_pages}-page cap "
            f"(~{len(items)} records) with a full final page — results are likely "
            "TRUNCATED. Some records were not fetched; narrow with a where-filter "
            "or raise max_pages so no record is silently dropped.",
            file=sys.stderr,
        )
    return items


def command_evidence_audit(args: argparse.Namespace) -> int:
    """Read-only compliance sweep: which records lack a stapled source document.

    Pages the requested object kinds, splits HasAttachments=false records into
    frozen (dated before --frozen-before; attach for records, never re-code) vs
    current (must be fixed before the next BAS). No mutation.

    Frozen-period boundary precedence:
    1. --frozen-before CLI arg (explicit operator override)
    2. Xero PeriodLockDate / EndOfYearLockDate (org snapshot → live GET fallback)
    3. ap-policy.frozen_before (via --ap-policy), if supplied
    4. Not set → loud stderr warning; all records land in missing_current
    """
    payload, tenant_id = resolve_active_auth(args)
    headers = accounting_headers(payload, tenant_id)
    kinds = args.kinds or ["bill", "bank-transaction"]
    # Resolve the frozen-before boundary: CLI → Xero lock (snapshot/live) → policy.
    # The boundary is always an EXCLUSIVE upper bound (frozen iff date < boundary);
    # the Xero lock date's inclusive semantics are converted to +1 day inside
    # effective_frozen_before so the single `iso < frozen_before` compare is correct.
    cli_frozen = (args.frozen_before or "").strip() or None
    snapshots_root = getattr(args, "snapshots", None)
    # Optional ap-policy fallback (criterion 3 names evidence audit as a caller).
    policy: dict[str, Any] = {}
    ap_policy_path = getattr(args, "ap_policy", None)
    if ap_policy_path:
        policy = xero_ap_policy.load_ap_policy(ap_policy_path)
    if cli_frozen:
        # Explicit operator override is already exclusive; skip any lock-date GET.
        frozen_before = cli_frozen
        frozen_before_source = "cli-arg"
    else:
        # Auth is already in hand here, so prefer the LIVE lock date over a
        # possibly-stale snapshot (a BAS lodged since the snapshot would have
        # advanced Xero's lock). Falls back to the snapshot if the live GET fails.
        _org, xero_lock, lock_source = resolve_org_and_lock_date(
            snapshots_root, live_auth=(payload, tenant_id), prefer_live=True
        )
        if xero_lock:
            frozen_before = xero_ap_policy.effective_frozen_before(policy, lock_date=xero_lock)
            # Label the actual winning signal: when policy.frozen_before is later
            # than the lock date it produces the max boundary, so don't hardcode
            # "xero-lock-date". When the lock date wins, keep the more specific
            # provenance (org-snapshot / live-organisation) from lock_source.
            winner = frozen_boundary_source(policy, xero_lock, frozen_before)
            if winner == "ap-policy":
                frozen_before_source = "ap-policy"
            else:
                # lock wins (or ties) → prefer the specific lock provenance.
                frozen_before_source = lock_source or winner or "xero-lock-date"
        else:
            # No Xero lock date → fall back to ap-policy.frozen_before (exclusive).
            frozen_before = xero_ap_policy.effective_frozen_before(policy, lock_date=None)
            frozen_before_source = "ap-policy" if frozen_before else None
    warn_if_no_frozen_guard(frozen_before, context="evidence audit")
    report_kinds: dict[str, Any] = {}
    missing_current: list[dict[str, Any]] = []
    missing_frozen: list[dict[str, Any]] = []
    total = 0
    total_missing = 0
    for kind in kinds:
        config = EVIDENCE_AUDIT_KINDS.get(kind)
        if config is None:
            raise XeroCliError(f"evidence audit does not support kind {kind!r}; supported: {', '.join(sorted(EVIDENCE_AUDIT_KINDS))}")
        objects = paged_accounting_get(config["endpoint"], config["root"], headers, where=config["where"])
        id_name = EVIDENCE_OBJECT_KINDS[kind]["id_name"]
        kind_missing = 0
        for obj in objects:
            total += 1
            if obj.get("HasAttachments") is True:
                continue
            # Voided/deleted records carry no evidence obligation.
            if str(obj.get("Status") or "").upper() in {"VOIDED", "DELETED"}:
                continue
            iso = xero_object_iso_date(obj)
            record = {
                "kind": kind,
                "object_id": obj.get(id_name),
                "date": iso,
                "contact": (obj.get("Contact") or {}).get("Name") if isinstance(obj.get("Contact"), dict) else None,
                "reference": obj.get("InvoiceNumber") or obj.get("Reference"),
                "total": obj.get("Total"),
                "status": obj.get("Status"),
            }
            kind_missing += 1
            total_missing += 1
            if frozen_before and iso and iso < frozen_before:
                missing_frozen.append(record)
            else:
                missing_current.append(record)
        report_kinds[kind] = {"scanned": len(objects), "missing_attachment": kind_missing}
    report = {
        "ok": True,
        "mode": "evidence-audit",
        "generated_at": utc_seconds(),
        "tenant_id": tenant_id,
        "frozen_before": frozen_before,
        "frozen_before_source": frozen_before_source,
        "scanned_total": total,
        "missing_total": total_missing,
        "by_kind": report_kinds,
        "missing_current": missing_current,
        "missing_frozen": missing_frozen,
    }
    if args.out:
        out_path = Path(args.out).expanduser().resolve()
        xero_finance_rules.write_json_file(out_path, report)
        write_json({"ok": True, "mode": "evidence-audit", "report": str(out_path), "missing_total": total_missing, "scanned_total": total})
    else:
        write_json(report)
    return 0


def load_attachment_manifest(path: str) -> list[dict[str, Any]]:
    raw = xero_finance_rules.load_json_file(Path(path).expanduser().resolve())
    rows = raw.get("attachments") if isinstance(raw, dict) else raw
    if not isinstance(rows, list):
        raise XeroCliError("Attachment manifest must be a JSON array or an object with an 'attachments' array.")
    entries: list[dict[str, Any]] = []
    for index, row in enumerate(rows, start=1):
        if not isinstance(row, dict):
            raise XeroCliError(f"manifest entry {index} must be an object")
        kind = str(row.get("kind") or "").strip().lower()
        if kind not in EVIDENCE_OBJECT_KINDS:
            raise XeroCliError(f"manifest entry {index}: unsupported kind {kind!r}")
        if not row.get("file"):
            raise XeroCliError(f"manifest entry {index}: 'file' is required")
        object_id = str(row.get("object_id") or "").strip()
        match = row.get("match") if isinstance(row.get("match"), dict) else None
        if not object_id and not match:
            raise XeroCliError(f"manifest entry {index}: needs 'object_id' or a 'match' object")
        entries.append({
            "index": index,
            "kind": kind,
            "file": str(row["file"]),
            "object_id": object_id or None,
            "match": match,
            "filename": (str(row.get("filename")).strip() if row.get("filename") else None),
            "note": (str(row.get("note")).strip() if row.get("note") else None),
            "content_type": (str(row.get("content_type")).strip() if row.get("content_type") else None),
        })
    return entries


def resolve_manifest_object_id(entry: dict[str, Any], headers: dict[str, str]) -> str:
    """Resolve a manifest entry's target object id (direct, or by date/amount/contact)."""
    if entry.get("object_id"):
        return str(entry["object_id"])
    match = entry["match"]
    kind = entry["kind"]
    audit_kind = kind if kind in EVIDENCE_AUDIT_KINDS else None
    if audit_kind is None:
        raise XeroCliError(f"manifest entry {entry['index']}: 'match' resolution unsupported for kind {kind!r}; supply object_id")
    config = EVIDENCE_AUDIT_KINDS[audit_kind]
    id_name = EVIDENCE_OBJECT_KINDS[kind]["id_name"]
    want_date = str(match.get("date") or "").strip()[:10] or None
    want_amount = xero_finance_rules.parse_money(match.get("amount")) if match.get("amount") is not None else None
    want_contact = str(match.get("contact") or "").strip().lower() or None
    candidates: list[str] = []
    for obj in paged_accounting_get(config["endpoint"], config["root"], headers, where=config["where"]):
        if want_date and xero_object_iso_date(obj) != want_date:
            continue
        if want_amount is not None:
            total = xero_finance_rules.parse_money(obj.get("Total"))
            if total is None or abs(abs(total) - abs(want_amount)) > 0.005:
                continue
        if want_contact:
            name = (obj.get("Contact") or {}).get("Name") if isinstance(obj.get("Contact"), dict) else None
            if not name or want_contact not in str(name).lower():
                continue
        oid = obj.get(id_name)
        if oid:
            candidates.append(str(oid))
    if len(candidates) == 1:
        return candidates[0]
    if not candidates:
        raise XeroCliError(f"manifest entry {entry['index']}: no {kind} matched {match!r}")
    raise XeroCliError(f"manifest entry {entry['index']}: {len(candidates)} {kind}s matched {match!r} — add object_id to disambiguate")


def command_evidence_attach_batch(args: argparse.Namespace) -> int:
    """Manifest-driven backfill: staple source docs to records, with a dry-run gate.

    Dry-run (default) validates files (existence, <=10MB), resolves targets, and
    skips already-attached files. --apply uploads + adds a history note under
    the operation lock and writes an apply-ledger event per attachment.
    """
    entries = load_attachment_manifest(args.manifest)
    payload, tenant_id = resolve_active_auth(args)
    headers = accounting_headers(payload, tenant_id)
    planned: list[dict[str, Any]] = []
    missing_files: list[dict[str, Any]] = []
    for entry in entries:
        file_path = Path(entry["file"]).expanduser().resolve()
        if not file_path.is_file():
            if getattr(args, "skip_missing_files", False):
                missing_files.append({"index": entry["index"], "kind": entry["kind"], "file": str(file_path)})
                continue
            raise XeroCliError(f"manifest entry {entry['index']}: file does not exist: {file_path} (drop the document in, or pass --skip-missing-files to backfill incrementally)")
        size = file_path.stat().st_size
        if size > MAX_ATTACHMENT_BYTES:
            raise XeroCliError(f"manifest entry {entry['index']}: {file_path.name} is {size} bytes (>{MAX_ATTACHMENT_BYTES} limit)")
        filename = evidence_filename(entry.get("filename"), file_path)
        object_id = resolve_manifest_object_id(entry, headers)
        base = evidence_base_path(entry["kind"], object_id)
        existing = http_get_json(f"{ACCOUNTING_API_BASE}/{base}/Attachments", headers)
        existing_list = existing.get("Attachments") if isinstance(existing, dict) else None
        existing_names = {str(a.get("FileName")) for a in existing_list} if isinstance(existing_list, list) else set()
        if len(existing_names) >= MAX_ATTACHMENTS_PER_OBJECT:
            raise XeroCliError(f"manifest entry {entry['index']}: {entry['kind']} {object_id} already has {len(existing_names)} attachments (max {MAX_ATTACHMENTS_PER_OBJECT})")
        planned.append({
            "index": entry["index"],
            "kind": entry["kind"],
            "object_id": object_id,
            "file": str(file_path),
            "filename": filename,
            "byte_count": size,
            "content_type": entry.get("content_type") or mimetypes.guess_type(filename)[0] or "application/octet-stream",
            "note": entry.get("note"),
            "already_attached": filename in existing_names,
        })
    to_upload = [p for p in planned if not p["already_attached"]]
    if not args.apply:
        write_json({
            "ok": True,
            "mode": "dry-run",
            "tenant_id": tenant_id,
            "planned_count": len(planned),
            "upload_count": len(to_upload),
            "skipped_already_attached": len(planned) - len(to_upload),
            "skipped_missing_files": missing_files,
            "planned": planned,
            "message": "No upload made. Re-run with --apply to staple these documents.",
        })
        return 0
    results: list[dict[str, Any]] = []
    audit_root = xero_finance_rules.audit_dir(args.audit_dir)
    lock_path = xero_operation_lock.lock_store_path(None)
    lease = xero_operation_lock.acquire_lock(lock_path, holder="evidence-attach-batch", wait=True)
    if not lease.get("acquired"):
        raise XeroCliError("Could not acquire the Xero operation lock for the attachment batch.")
    try:
        for plan in to_upload:
            body = Path(plan["file"]).read_bytes()
            endpoint = f"{evidence_base_path(plan['kind'], plan['object_id'])}/Attachments/{urllib.parse.quote(plan['filename'], safe='')}"
            response = http_send_bytes("POST", f"{ACCOUNTING_API_BASE}/{endpoint}", headers, body, content_type=plan["content_type"])
            note = plan.get("note") or f"Source document {plan['filename']} attached via evidence attach-batch."
            try:
                http_send_json("PUT", f"{ACCOUNTING_API_BASE}/{evidence_base_path(plan['kind'], plan['object_id'])}/History", headers, {"HistoryRecords": [{"Details": note}]})
                note_ok = True
            except XeroCliError:
                note_ok = False  # History notes are best-effort on some object kinds.
            event = {
                "type": plan["kind"],
                "action": "api_attachment_upload",
                "status": "attached",
                "xero_id": plan["object_id"],
                "tenant_id": tenant_id,
                "details": {"filename": plan["filename"], "byte_count": plan["byte_count"], "history_note": note_ok},
            }
            apply_result = xero_finance_rules.write_apply_report(audit_root, event, actor=args.actor)
            results.append({**plan, "uploaded": True, "history_note": note_ok, "report": apply_result.get("report")})
    finally:
        xero_operation_lock.release_lock(lock_path, lease["lease_id"])
    write_json({
        "ok": True,
        "mode": "apply",
        "tenant_id": tenant_id,
        "uploaded_count": len(results),
        "skipped_already_attached": len(planned) - len(to_upload),
        "skipped_missing_files": missing_files,
        "results": results,
    })
    return 0


def prework_config(kind: str) -> dict[str, str]:
    value = kind.strip().lower()
    if value not in PREWORK_KINDS:
        raise XeroCliError(f"Unsupported pre-work kind: {kind}")
    return PREWORK_KINDS[value]


def load_prework_payload(path: str) -> Any:
    payload = xero_finance_rules.load_json_file(Path(path).expanduser().resolve())
    if not isinstance(payload, (dict, list)):
        raise XeroCliError("Pre-work payload must be a JSON object, array, or already wrapped Xero request object.")
    return payload


def wrap_prework_payload(kind: str, payload: Any) -> dict[str, Any]:
    config = prework_config(kind)
    root_key = config["root_key"]
    if isinstance(payload, dict) and isinstance(payload.get(root_key), list):
        return payload
    if isinstance(payload, list):
        return {root_key: payload}
    if isinstance(payload, dict):
        return {root_key: [payload]}
    raise XeroCliError("Pre-work payload must be a JSON object or array.")


def first_prework_result(kind: str, response: Any) -> dict[str, Any]:
    if not isinstance(response, dict):
        return {}
    root_key = prework_config(kind)["root_key"]
    records = response.get(root_key)
    if isinstance(records, list) and records and isinstance(records[0], dict):
        return records[0]
    return {}


def document_config(kind: str) -> dict[str, Any]:
    value = kind.strip().lower()
    if value not in DOCUMENT_KINDS:
        raise XeroCliError(f"Unsupported document kind: {kind}")
    return DOCUMENT_KINDS[value]


def load_document_payload(path: str) -> Any:
    payload = xero_finance_rules.load_json_file(Path(path).expanduser().resolve())
    if not isinstance(payload, (dict, list)):
        raise XeroCliError("Document payload must be a JSON object, array, or already wrapped Xero request object.")
    return payload


def apply_document_defaults(records: list[Any], defaults: dict[str, Any]) -> list[Any]:
    output = []
    for record in records:
        if not isinstance(record, dict):
            raise XeroCliError("Document records must be JSON objects.")
        merged = dict(record)
        for key, value in defaults.items():
            merged.setdefault(key, value)
        output.append(merged)
    return output


def wrap_document_payload(kind: str, payload: Any) -> dict[str, Any]:
    config = document_config(kind)
    root_key = str(config["root_key"])
    defaults = config.get("default_fields") if isinstance(config.get("default_fields"), dict) else {}
    if isinstance(payload, dict) and isinstance(payload.get(root_key), list):
        wrapped = dict(payload)
        wrapped[root_key] = apply_document_defaults(list(payload[root_key]), defaults)
        return wrapped
    if isinstance(payload, list):
        return {root_key: apply_document_defaults(payload, defaults)}
    if isinstance(payload, dict):
        return {root_key: apply_document_defaults([payload], defaults)}
    raise XeroCliError("Document payload must be a JSON object or array.")


def wrap_document_update_payload(kind: str, payload: Any) -> dict[str, Any]:
    config = document_config(kind)
    root_key = str(config["root_key"])
    if isinstance(payload, dict) and isinstance(payload.get(root_key), list):
        return payload
    if isinstance(payload, list):
        return {root_key: payload}
    if isinstance(payload, dict):
        return {root_key: [payload]}
    raise XeroCliError("Document update payload must be a JSON object or array.")


def first_document_result(kind: str, response: Any) -> dict[str, Any]:
    if not isinstance(response, dict):
        return {}
    root_key = str(document_config(kind)["root_key"])
    records = response.get(root_key)
    if isinstance(records, list) and records and isinstance(records[0], dict):
        return records[0]
    return {}


def document_reference(kind: str, record: dict[str, Any]) -> Any:
    config = document_config(kind)
    for field in config.get("reference_fields", []):
        if record.get(field):
            return record[field]
    return None


def summarize_document_batch(kind: str, request_payload: Any, response: Any) -> dict[str, Any]:
    """Per-element outcome for a (possibly multi-record) document create.

    With ``?SummarizeErrors=false`` Xero returns HTTP 200 and echoes one element
    per requested record (in order), each carrying ``StatusAttributeString``
    ("OK"/"ERROR") and any per-element ``ValidationErrors``. This maps each
    requested record to its result so a partial batch success is visible per
    record (created ID vs validation errors) instead of only the first element.

    ``response=None`` produces a dry-run summary (planned records, no outcomes).
    """
    config = document_config(kind)
    root_key = str(config["root_key"])
    id_key = str(config["id_key"])
    requested = request_payload.get(root_key) if isinstance(request_payload, dict) else None
    requested = requested if isinstance(requested, list) else []
    returned = response.get(root_key) if isinstance(response, dict) else None
    returned = returned if isinstance(returned, list) else []

    results: list[dict[str, Any]] = []
    succeeded = 0
    failed = 0
    for idx, req in enumerate(requested):
        req_record = req if isinstance(req, dict) else {}
        if response is None:
            results.append({
                "index": idx,
                "reference": document_reference(kind, req_record),
                "planned": True,
            })
            continue
        ret = returned[idx] if idx < len(returned) and isinstance(returned[idx], dict) else {}
        verrs = ret.get("ValidationErrors") if isinstance(ret.get("ValidationErrors"), list) else []
        xero_id = ret.get(id_key)
        status_attr = str(ret.get("StatusAttributeString") or "").upper()
        ok = bool(xero_id) and not verrs and status_attr != "ERROR"
        if ok:
            succeeded += 1
        else:
            failed += 1
        results.append({
            "index": idx,
            "reference": document_reference(kind, ret) or document_reference(kind, req_record),
            "status": "OK" if ok else "ERROR",
            "xero_id": xero_id,
            "validation_errors": verrs,
        })

    summary: dict[str, Any] = {"root_key": root_key, "total": len(requested), "results": results}
    if response is not None:
        summary["succeeded"] = succeeded
        summary["failed"] = failed
    return summary


def mutation_preflight_summary(*, kind: str, endpoint: str, payload: Any | None = None) -> dict[str, Any]:
    return {
        "required_for_apply": True,
        "accepted_reports": ["this dry-run report", "xero audit dry-run report"],
        "apply_flags": ["--preflight-report <path>"],
        "override_flag": "--confirm-apply-without-preflight",
        "kind": kind,
        "endpoint": endpoint,
        "payload_fingerprint": payload_fingerprint(payload) if payload is not None else None,
    }


def payload_fingerprint(payload: Any) -> str:
    encoded = json.dumps(redact_payload(payload), sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def validate_mutation_preflight(args: argparse.Namespace, *, kind: str, endpoint: str, payload: Any | None = None) -> dict[str, Any]:
    preflight_path = getattr(args, "preflight_report", None)
    override = bool(getattr(args, "confirm_apply_without_preflight", False))
    if not preflight_path:
        if override:
            return {
                "ok": True,
                "source": "operator-override",
                "warning": "Apply continued without a dry-run/audit preflight report because --confirm-apply-without-preflight was supplied.",
            }
        raise XeroCliError(
            "Apply requires --preflight-report from the matching dry-run/audit step. "
            "Use --confirm-apply-without-preflight only for an explicit operator override."
        )

    path = Path(preflight_path).expanduser().resolve()
    report = xero_finance_rules.load_json_file(path)
    if not isinstance(report, dict):
        raise XeroCliError(f"Preflight report root must be a JSON object: {path}")
    if report.get("ok") is False:
        raise XeroCliError(f"Preflight report is not ok: {path}")

    mode = str(report.get("mode") or "")
    summary = report.get("summary") if isinstance(report.get("summary"), dict) else {}
    dry_run_kind = str(report.get("kind") or "")
    dry_run_endpoint = str(report.get("endpoint") or "")
    dry_run_payload = report.get("payload")
    ready = summary.get("ready")
    review = int(summary.get("review") or 0) if str(summary.get("review") or "0").isdigit() else 0
    blocked = int(summary.get("blocked_duplicate") or 0) if str(summary.get("blocked_duplicate") or "0").isdigit() else 0

    if mode == "dry-run":
        if dry_run_kind and dry_run_kind != kind:
            raise XeroCliError(f"Preflight report kind mismatch: expected {kind}, got {dry_run_kind}.")
        if dry_run_endpoint and dry_run_endpoint != endpoint:
            raise XeroCliError(f"Preflight report endpoint mismatch: expected {endpoint}, got {dry_run_endpoint}.")
        if dry_run_payload is not None and payload is not None:
            expected = payload_fingerprint(payload)
            actual = payload_fingerprint(dry_run_payload)
            if actual != expected:
                raise XeroCliError("Preflight report payload does not match the payload being applied.")
        return {
            "ok": True,
            "source": "dry-run-report",
            "path": str(path),
            "kind": dry_run_kind or kind,
            "endpoint": dry_run_endpoint or endpoint,
        }

    if "candidate_count" in summary:
        if blocked or review:
            raise XeroCliError(f"Preflight audit report is not clean: review={review}, blocked_duplicate={blocked}.")
        if ready in (None, 0):
            raise XeroCliError("Preflight audit report has no ready candidates.")
        return {
            "ok": True,
            "source": "audit-dry-run-report",
            "path": str(path),
            "summary": summary,
        }

    raise XeroCliError(f"Unsupported preflight report shape: {path}")


def document_status_value(kind: str, value: str) -> str:
    status = value.strip().upper()
    allowed = DOCUMENT_STATUS_VALUES.get(kind, set())
    if not status or status not in allowed:
        raise XeroCliError(f"Unsupported {kind} status: {value}. Allowed: {', '.join(sorted(allowed))}")
    return status


def looks_like_uuid(value: str) -> bool:
    return bool(re.fullmatch(r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}", value.strip()))


def document_identifier_record(kind: str, identifier: str, status: str) -> dict[str, Any]:
    config = document_config(kind)
    ident = identifier.strip()
    if not ident:
        raise XeroCliError("--identifier is required when using --status without --payload.")
    record = {"Status": status}
    if kind in {"invoice", "bill"}:
        if looks_like_uuid(ident):
            record["InvoiceID"] = ident
        else:
            record["InvoiceNumber"] = ident
    else:
        record[str(config["id_key"])] = ident
    return record


def document_update_payload(args: argparse.Namespace) -> dict[str, Any]:
    if bool(args.payload) == bool(args.status):
        raise XeroCliError("Use exactly one of --payload or --status for document update.")
    if args.payload:
        payload = wrap_document_update_payload(args.kind, load_document_payload(args.payload))
    else:
        status = document_status_value(args.kind, args.status)
        payload = wrap_document_update_payload(args.kind, document_identifier_record(args.kind, args.identifier or "", status))
    if args.identifier and args.payload:
        config = document_config(args.kind)
        records = payload.get(config["root_key"])
        if isinstance(records, list) and len(records) == 1 and isinstance(records[0], dict):
            record = records[0]
            if args.kind in {"invoice", "bill"}:
                key = "InvoiceID" if looks_like_uuid(args.identifier) else "InvoiceNumber"
                record.setdefault(key, args.identifier)
            else:
                record.setdefault(str(config["id_key"]), args.identifier)
    return payload


def document_update_url(kind: str, identifier: str | None) -> str:
    endpoint = str(document_config(kind)["endpoint"])
    if kind in {"invoice", "bill"} and identifier:
        return f"{ACCOUNTING_API_BASE}/{endpoint}/{urllib.parse.quote(identifier.strip(), safe='')}"
    return f"{ACCOUNTING_API_BASE}/{endpoint}"


def command_documents_create(args: argparse.Namespace) -> int:
    config = document_config(args.kind)
    request_payload = wrap_document_payload(args.kind, load_document_payload(args.payload))
    endpoint = str(config["endpoint"])
    url = f"{ACCOUNTING_API_BASE}/{endpoint}"
    if args.summarize_errors is False:
        url += "?SummarizeErrors=false"
    if not args.apply:
        result = {
            "ok": True,
            "mode": "dry-run",
            "kind": args.kind,
            "endpoint": endpoint,
            "would_apply": False,
            "payload": redact_payload(request_payload),
            "batch": summarize_document_batch(args.kind, request_payload, None),
            "preflight": mutation_preflight_summary(kind=args.kind, endpoint=endpoint, payload=request_payload),
            "message": "No Xero mutation was made. Re-run with --apply after audit checks pass.",
        }
        if args.out:
            out_path = Path(args.out).expanduser().resolve()
            xero_finance_rules.write_json_file(out_path, result)
            write_json({"ok": True, "mode": "dry-run", "report": str(out_path), "kind": args.kind})
        else:
            write_json(result)
        return 0

    preflight = validate_mutation_preflight(args, kind=args.kind, endpoint=endpoint, payload=request_payload)
    payload, tenant_id = resolve_active_auth(args)
    response = http_send_json("POST", url, accounting_headers(payload, tenant_id), request_payload)
    first = first_document_result(args.kind, response)
    batch = summarize_document_batch(args.kind, request_payload, response)
    # Multi-record batches can partially succeed under SummarizeErrors=false. Report
    # per-element outcomes and fail closed (no apply-ledger) if any record failed, so
    # a partial success surfaces every created ID and validation error here rather
    # than only in the Xero UI. Single-record stays on the original guard contract.
    if batch["total"] > 1 and batch.get("failed"):
        write_json({
            "ok": False,
            "mode": "apply",
            "kind": args.kind,
            "endpoint": endpoint,
            "tenant_id": tenant_id,
            "batch": batch,
            "response": redact_payload(response),
            "preflight": preflight,
            "message": (
                f"{batch['failed']} of {batch['total']} {args.kind} records were rejected by Xero "
                f"(SummarizeErrors=false). {batch['succeeded']} were created and DO exist in Xero. "
                "No apply-ledger entry was written; reconcile the created records and fix the failed ones."
            ),
        })
        return 1
    _guard_document_apply(response, id_value=first.get(config["id_key"]), kind=args.kind, endpoint=endpoint, first_elem=first)
    event = {
        "type": args.kind,
        "action": "api_document_create",
        "status": first.get("Status") or "created",
        "reference": document_reference(args.kind, first),
        "xero_id": first.get(config["id_key"]),
        "tenant_id": tenant_id,
        "details": {
            "endpoint": endpoint,
            "request": redact_payload(request_payload),
            "response": redact_payload(response),
        },
    }
    apply_result = xero_finance_rules.write_apply_report(xero_finance_rules.audit_dir(args.audit_dir), event, actor=args.actor)
    write_json(
        {
            "ok": True,
            "mode": "apply",
            "kind": args.kind,
            "endpoint": endpoint,
            "tenant_id": tenant_id,
            "xero_id": event["xero_id"],
            "reference": event["reference"],
            "batch": batch,
            "response": redact_payload(response),
            "preflight": preflight,
            "apply_report": apply_result,
        }
    )
    return 0


# ---------------------------------------------------------------------------
# Accounts-payable bill lifecycle (Phase 2) — profile-pack-driven drafting
# ---------------------------------------------------------------------------


def parse_bill_line(spec: str) -> dict[str, Any]:
    """Parse a --line "ACCOUNT:TAX:AMOUNT:DESCRIPTION" into a Xero LineItem."""
    parts = str(spec).split(":", 3)
    if len(parts) < 3:
        raise XeroCliError(f"--line must be ACCOUNT:TAX:AMOUNT[:DESCRIPTION], got {spec!r}")
    account, tax, amount_raw = parts[0].strip(), parts[1].strip(), parts[2].strip()
    description = parts[3].strip() if len(parts) == 4 else ""
    amount = xero_finance_rules.parse_money(amount_raw)
    if amount is None:
        raise XeroCliError(f"--line amount must be numeric, got {amount_raw!r}")
    if not account:
        raise XeroCliError(f"--line needs an account code: {spec!r}")
    line: dict[str, Any] = {"Description": description or account, "AccountCode": account, "LineAmount": amount, "Quantity": 1, "UnitAmount": amount}
    if tax:
        line["TaxType"] = tax
    return line


def resolve_org_and_lock_date(
    snapshots_root: str | None,
    *,
    live_auth: tuple[dict[str, Any], str] | None = None,
    live_auth_resolver: "callable | None" = None,
    prefer_live: bool = False,
) -> tuple[dict[str, Any], str | None, str | None]:
    """Resolve the organisation object + its Xero lock date.

    Returns ``(org, lock_date_iso_or_None, source_or_None)`` where source is
    "org-snapshot", "live-organisation", or None.

    Auth may be supplied eagerly (``live_auth=(payload, tenant_id)``) or LAZILY
    via ``live_auth_resolver`` — a zero-arg callable returning ``(payload,
    tenant_id)`` or None.

    Resolution order:
    * ``prefer_live=True`` (e.g. evidence audit, where auth is already in hand):
      use the LIVE lock date when auth is available, falling back to the snapshot
      only if the live GET yields nothing. This avoids drafting against a stale
      snapshot lock when a live call is free.
    * default (e.g. draft-bill dry-run hot path): use the snapshot lock when
      present (no network call); only fetch live as a FALLBACK when the snapshot
      has no lock. When the snapshot lock is used, warn on stderr if it is older
      than ORG_SNAPSHOT_STALE_SECONDS (visibility only — behaviour unchanged, to
      respect rate limits).
    """
    org = load_org_snapshot(snapshots_root)
    snapshot_lock = org_lock_date(org)

    def _live_auth() -> tuple[dict[str, Any], str] | None:
        auth = live_auth
        if auth is None and live_auth_resolver is not None:
            try:
                return live_auth_resolver()
            except (XeroCliError, urllib.error.URLError, urllib.error.HTTPError):
                return None
        return auth

    def _try_live() -> tuple[dict[str, Any], str | None] | None:
        auth = _live_auth()
        if auth is None:
            return None
        try:
            live_org = fetch_org_live(auth[0], auth[1])
        except (XeroCliError, urllib.error.URLError, urllib.error.HTTPError):
            return None
        return (live_org, org_lock_date(live_org)) if live_org else None

    if prefer_live:
        live = _try_live()
        if live is not None:
            live_org, live_lock = live
            if live_lock:
                return live_org, live_lock, "live-organisation"
            # Live answered but no lock set — prefer it over a stale snapshot.
            return live_org, None, None
        # Live unavailable/failed → fall back to the snapshot.
        if snapshot_lock:
            _warn_if_stale_org_snapshot(snapshots_root)
            return org, snapshot_lock, "org-snapshot"
        return org, None, None

    # Default: snapshot-first (hot path; avoid network when snapshot answers).
    if snapshot_lock:
        _warn_if_stale_org_snapshot(snapshots_root)
        return org, snapshot_lock, "org-snapshot"
    live = _try_live()
    if live is not None:
        live_org, live_lock = live
        if live_lock:
            return live_org, live_lock, "live-organisation"
        # Keep the live org payload (for org-default terms) even with no lock.
        return live_org, None, None
    return org, None, None


def _warn_if_stale_org_snapshot(snapshots_root: str | None) -> None:
    """Warn on stderr when the org snapshot's lock date may be stale."""
    fetched = org_snapshot_fetched_at(snapshots_root)
    if fetched is None:
        return
    age_seconds = utc_seconds() - fetched
    if age_seconds > ORG_SNAPSHOT_STALE_SECONDS:
        age_days = age_seconds // 86400
        print(
            f"WARNING: org snapshot is {age_days} days old (fetched_at={fetched}); "
            "the frozen-guard lock date may be stale — a BAS lodged since then would "
            "have advanced Xero's lock date. Refresh with "
            "`xero snapshots fetch organisation`.",
            file=sys.stderr,
        )


def frozen_boundary_source(
    policy: dict[str, Any],
    lock_date: str | None,
    effective_boundary: str | None,
) -> str | None:
    """Name which signal produced the effective (most-locking) frozen boundary.

    Returns "xero-lock-date", "ap-policy", "xero-lock-date+ap-policy" (when both
    are present and tie), or None when no boundary is set. Mirrors the
    max-of-both logic in xero_ap_policy.effective_frozen_before.
    """
    if not effective_boundary:
        return None
    lock_bound = xero_ap_policy.effective_frozen_before({}, lock_date=lock_date) if lock_date else None
    policy_bound = (
        str(policy.get("frozen_before")).strip()[:10]
        if policy.get("frozen_before") and str(policy.get("frozen_before")).strip()
        else None
    )
    from_lock = lock_bound == effective_boundary
    from_policy = policy_bound == effective_boundary
    if from_lock and from_policy:
        return "xero-lock-date+ap-policy"
    if from_lock:
        return "xero-lock-date"
    if from_policy:
        return "ap-policy"
    return None


def warn_if_no_frozen_guard(boundary: str | None, *, context: str) -> None:
    """Print a loud stderr warning when NO frozen-period guard is active.

    The guard must never silently disappear: when neither the Xero lock date nor
    ap-policy.frozen_before yields a boundary, the caller will not refuse any bill
    date, so the operator must be told explicitly.
    """
    if boundary:
        return
    print(
        f"WARNING [{context}]: no frozen-period boundary is set — neither a Xero "
        "lock date (PeriodLockDate/EndOfYearLockDate, snapshot or live) nor "
        "ap-policy.frozen_before. NO frozen-period guard is active; bills dated "
        "inside an already-lodged BAS period will NOT be refused. Set a lock date "
        "in Xero or frozen_before in ap-policy.json.",
        file=sys.stderr,
    )


def command_ap_draft_bill(args: argparse.Namespace) -> int:
    """Draft an ACCPAY bill with pack-derived due date + approval routing.

    Reuses the documents safety chassis (preflight + audit ledger). Creates the
    bill as DRAFT; authorisation is a separate, attachment-gated step. Refuses
    frozen-period bill dates unless --confirm-frozen-period.
    """
    policy = xero_ap_policy.load_ap_policy(args.ap_policy)
    bill_date = (args.bill_date or time.strftime("%Y-%m-%d", time.gmtime())).strip()
    supplier = (args.supplier or "").strip() or None
    # Resolve the Xero lock date: org snapshot → live GET /Organisation fallback →
    # ap-policy.frozen_before fallback (in effective_frozen_before). Live auth is
    # resolved eagerly so the frozen guard can use the live lock date even on a
    # dry-run; if auth isn't available we degrade to snapshot/policy only.
    snapshots_root = getattr(args, "snapshots", None)
    # Lazily resolve live auth: only refresh/GET if the org snapshot lacks the
    # lock date (the live fallback). The result is memoised so the apply path
    # reuses it without a second token operation.
    _auth_cache: dict[str, tuple[dict[str, Any], str] | None] = {}

    def _resolve_auth() -> tuple[dict[str, Any], str] | None:
        if "v" not in _auth_cache:
            try:
                _auth_cache["v"] = resolve_active_auth(args)
            except XeroCliError:
                _auth_cache["v"] = None
        return _auth_cache["v"]

    org, xero_lock_date, _lock_source = resolve_org_and_lock_date(
        snapshots_root, live_auth_resolver=_resolve_auth
    )
    effective_boundary = xero_ap_policy.effective_frozen_before(policy, lock_date=xero_lock_date)
    warn_if_no_frozen_guard(effective_boundary, context="ap draft-bill")
    if xero_ap_policy.is_frozen(policy, bill_date, lock_date=xero_lock_date) and not args.confirm_frozen_period:
        # The effective boundary is the most-locking of the Xero lock date (+1, inclusive)
        # and the policy frozen_before; name whichever signals are present.
        sources = []
        if xero_lock_date:
            sources.append(f"Xero lock date {xero_lock_date}")
        if policy.get("frozen_before"):
            sources.append(f"ap-policy frozen_before {policy.get('frozen_before')}")
        boundary_source = " + ".join(sources) if sources else "frozen-period boundary"
        raise XeroCliError(
            f"bill date {bill_date} is before the frozen-period boundary "
            f"({effective_boundary}; most-locking of: {boundary_source}); "
            "refusing. Use --confirm-frozen-period only with agent sign-off."
        )
    # Resolve payment terms: contact Xero terms → org default → policy fallback → net-14.
    contact_rec = find_contact_in_snapshot(snapshots_root, args.contact_id) if args.contact_id else {}
    ct = contact_payment_terms(contact_rec)
    org_pt = org_default_payment_terms(org)
    terms = xero_ap_policy.resolve_terms(policy, supplier, contact_terms=ct, org_default_terms=org_pt)
    due_date = xero_ap_policy.compute_due_date(bill_date, terms)
    lines = [parse_bill_line(spec) for spec in (args.line or [])]
    if not lines:
        raise XeroCliError("at least one --line ACCOUNT:TAX:AMOUNT[:DESCRIPTION] is required")
    total = round(sum(float(li["LineAmount"]) for li in lines), 2)
    approval = xero_ap_policy.approval_decision(policy, total)
    bill = {
        "Type": "ACCPAY",
        "Contact": {"ContactID": args.contact_id} if looks_like_uuid(args.contact_id) else {"Name": args.contact_id},
        "Date": bill_date,
        "DueDate": due_date,
        "LineItems": lines,
        "Status": "DRAFT",
        "LineAmountTypes": args.line_amount_types,
    }
    if args.reference:
        bill["Reference"] = args.reference
    request_payload = {"Invoices": [bill]}
    ap_context = {
        "bill_date": bill_date,
        "due_date": due_date,
        "terms": terms,
        "supplier": supplier,
        "total": total,
        "approval": approval,
        "frozen_period": xero_ap_policy.is_frozen(policy, bill_date, lock_date=xero_lock_date),
        "frozen_boundary": effective_boundary,
        "frozen_boundary_source": frozen_boundary_source(policy, xero_lock_date, effective_boundary),
    }
    endpoint = "Invoices"
    if not args.apply:
        result = {
            "ok": True,
            "mode": "dry-run",
            "kind": "bill",
            "ap_context": ap_context,
            "payload": redact_payload(request_payload),
            "preflight": mutation_preflight_summary(kind="bill", endpoint=endpoint, payload=request_payload),
            "message": "No Xero mutation was made. Re-run with --apply (with a preflight report) to create the DRAFT bill.",
        }
        if args.out:
            out_path = Path(args.out).expanduser().resolve()
            xero_finance_rules.write_json_file(out_path, result)
            write_json({"ok": True, "mode": "dry-run", "report": str(out_path), "kind": "bill", "due_date": due_date})
        else:
            write_json(result)
        return 0
    preflight = validate_mutation_preflight(args, kind="bill", endpoint=endpoint, payload=request_payload)
    # Reuse any auth memoised by the lock-date live fallback; else resolve now
    # (apply requires valid auth regardless).
    auth = _resolve_auth()
    payload, tenant_id = auth if auth is not None else resolve_active_auth(args)
    url = f"{ACCOUNTING_API_BASE}/{endpoint}?SummarizeErrors=false"
    response = http_send_json("POST", url, accounting_headers(payload, tenant_id), request_payload)
    first = first_document_result("bill", response)
    _guard_document_apply(response, id_value=first.get("InvoiceID"), kind="bill", endpoint=endpoint, first_elem=first)
    event = {
        "type": "bill",
        "action": "api_ap_draft_bill",
        "status": first.get("Status") or "DRAFT",
        "reference": document_reference("bill", first) or args.reference,
        "xero_id": first.get("InvoiceID"),
        "tenant_id": tenant_id,
        "details": {"ap_context": ap_context, "request": redact_payload(request_payload), "response": redact_payload(response)},
    }
    apply_result = xero_finance_rules.write_apply_report(xero_finance_rules.audit_dir(args.audit_dir), event, actor=args.actor)
    write_json({
        "ok": True,
        "mode": "apply",
        "kind": "bill",
        "tenant_id": tenant_id,
        "xero_id": event["xero_id"],
        "reference": event["reference"],
        "status": event["status"],
        "ap_context": ap_context,
        "response": redact_payload(response),
        "preflight": preflight,
        "apply_report": apply_result,
    })
    return 0


def command_documents_update(args: argparse.Namespace) -> int:
    config = document_config(args.kind)
    request_payload = document_update_payload(args)
    endpoint = str(config["endpoint"])
    url = document_update_url(args.kind, args.identifier)
    if args.summarize_errors is False:
        url += "?SummarizeErrors=false"
    if not args.apply:
        result = {
            "ok": True,
            "mode": "dry-run",
            "kind": args.kind,
            "endpoint": endpoint,
            "identifier": args.identifier,
            "would_apply": False,
            "payload": redact_payload(request_payload),
            "preflight": mutation_preflight_summary(kind=args.kind, endpoint=endpoint, payload=request_payload),
            "message": "No Xero mutation was made. Re-run with --apply after audit checks pass.",
        }
        if args.out:
            out_path = Path(args.out).expanduser().resolve()
            xero_finance_rules.write_json_file(out_path, result)
            write_json({"ok": True, "mode": "dry-run", "report": str(out_path), "kind": args.kind})
        else:
            write_json(result)
        return 0

    preflight = validate_mutation_preflight(args, kind=args.kind, endpoint=endpoint, payload=request_payload)
    payload, tenant_id = resolve_active_auth(args)
    evidence_gate = enforce_attach_before_authorise(
        args, kind=args.kind, request_payload=request_payload,
        headers=accounting_headers(payload, tenant_id),
    )
    response = http_send_json("POST", url, accounting_headers(payload, tenant_id), request_payload)
    first = first_document_result(args.kind, response)
    _guard_document_apply(response, id_value=first.get(config["id_key"]), kind=args.kind, endpoint=endpoint, first_elem=first)
    event = {
        "type": args.kind,
        "action": "api_document_update",
        "status": first.get("Status") or (args.status.strip().upper() if args.status else "updated"),
        "reference": document_reference(args.kind, first) or args.identifier,
        "xero_id": first.get(config["id_key"]),
        "tenant_id": tenant_id,
        "details": {
            "endpoint": endpoint,
            "identifier": args.identifier,
            "request": redact_payload(request_payload),
            "response": redact_payload(response),
        },
    }
    apply_result = xero_finance_rules.write_apply_report(xero_finance_rules.audit_dir(args.audit_dir), event, actor=args.actor)
    write_json(
        {
            "ok": True,
            "mode": "apply",
            "kind": args.kind,
            "endpoint": endpoint,
            "identifier": args.identifier,
            "tenant_id": tenant_id,
            "xero_id": event["xero_id"],
            "reference": event["reference"],
            "status": event["status"],
            "response": redact_payload(response),
            "preflight": preflight,
            "evidence_gate": evidence_gate,
            "apply_report": apply_result,
        }
    )
    return 0


def document_status_from_payload(kind: str, request_payload: dict[str, Any]) -> str | None:
    """Extract the target Status from a wrapped document-update payload."""
    try:
        root_key = str(document_config(kind)["root_key"])
    except XeroCliError:
        return None
    records = request_payload.get(root_key) if isinstance(request_payload, dict) else None
    if isinstance(records, list) and records and isinstance(records[0], dict):
        status = records[0].get("Status")
        return str(status).strip().upper() if status else None
    return None


def enforce_attach_before_authorise(
    args: argparse.Namespace, *, kind: str, request_payload: dict[str, Any], headers: dict[str, str]
) -> dict[str, Any]:
    """Refuse to authorise a bill/invoice that has no stapled source document.

    Honours the org's finance-rules `conventions.evidence.attach_before_authorise`
    (default on). Only fires on AUTHORISED transitions for bill/invoice kinds.
    Override with --confirm-without-evidence; the override is recorded in the
    apply ledger so the human authority is auditable.
    """
    if kind not in {"bill", "invoice"}:
        return {"checked": False, "reason": "kind-not-gated"}
    if document_status_from_payload(kind, request_payload) != "AUTHORISED":
        return {"checked": False, "reason": "not-authorising"}
    try:
        rules = xero_finance_rules.load_rules(xero_finance_rules.rules_path(getattr(args, "rules", None)))
        convention = bool((((rules.get("conventions") or {}).get("evidence") or {}).get("attach_before_authorise", True)))
    except Exception:
        convention = True
    if not convention:
        return {"checked": False, "reason": "convention-disabled"}
    identifier = (args.identifier or "").strip()
    if not identifier:
        return {"checked": False, "reason": "no-identifier"}
    endpoint = f"{EVIDENCE_OBJECT_KINDS[kind]['endpoint']}/{urllib.parse.quote(identifier, safe='')}"
    try:
        live = http_get_json(f"{ACCOUNTING_API_BASE}/{endpoint}", headers)
        records = live.get("Invoices") if isinstance(live, dict) else None
        has_attachment = bool(records[0].get("HasAttachments")) if isinstance(records, list) and records else False
    except XeroCliError:
        has_attachment = False
    if has_attachment:
        return {"checked": True, "has_attachment": True, "enforced": True}
    if getattr(args, "confirm_without_evidence", False):
        return {"checked": True, "has_attachment": False, "overridden": True}
    raise XeroCliError(
        f"Refusing to authorise {kind} {identifier}: no source document attached "
        "(convention attach_before_authorise). Attach the tax invoice/receipt first "
        "(xero evidence attachments upload …), or override with --confirm-without-evidence."
    )


def document_action_endpoint(action: str, identifier: str) -> tuple[str, str, str]:
    ident = identifier.strip()
    if not ident:
        raise XeroCliError("--identifier is required for document actions.")
    if action not in DOCUMENT_ACTIONS:
        raise XeroCliError(f"Unsupported invoice action: {action}. Allowed: {', '.join(sorted(DOCUMENT_ACTIONS))}")
    suffix = "OnlineInvoice" if action == "online-url" else "Email"
    endpoint = f"Invoices/{urllib.parse.quote(ident, safe='')}/{suffix}"
    method = "GET" if action == "online-url" else "POST"
    return method, endpoint, f"{ACCOUNTING_API_BASE}/{endpoint}"


def command_documents_action(args: argparse.Namespace) -> int:
    if args.kind != "invoice":
        raise XeroCliError("Document actions currently support sales invoices only.")
    method, endpoint, url = document_action_endpoint(args.action, args.identifier)
    if not args.apply:
        result = {
            "ok": True,
            "mode": "dry-run",
            "kind": args.kind,
            "action": args.action,
            "identifier": args.identifier,
            "method": method,
            "endpoint": endpoint,
            "would_apply": False,
            "preflight": mutation_preflight_summary(kind=args.kind, endpoint=endpoint),
            "message": "No Xero action was made. Re-run with --apply after audit checks pass.",
        }
        if args.out:
            out_path = Path(args.out).expanduser().resolve()
            xero_finance_rules.write_json_file(out_path, result)
            write_json({"ok": True, "mode": "dry-run", "report": str(out_path), "kind": args.kind, "action": args.action})
        else:
            write_json(result)
        return 0

    preflight = validate_mutation_preflight(args, kind=args.kind, endpoint=endpoint)
    payload, tenant_id = resolve_active_auth(args)
    headers = accounting_headers(payload, tenant_id)
    response = http_get_json(url, headers) if method == "GET" else http_send_empty(method, url, headers)
    event = {
        "type": args.kind,
        "action": f"api_document_{args.action.replace('-', '_')}",
        "status": "completed",
        "reference": args.identifier,
        "xero_id": args.identifier,
        "tenant_id": tenant_id,
        "details": {
            "endpoint": endpoint,
            "method": method,
            "response": redact_payload(response),
        },
    }
    apply_result = xero_finance_rules.write_apply_report(xero_finance_rules.audit_dir(args.audit_dir), event, actor=args.actor)
    write_json(
        {
            "ok": True,
            "mode": "apply",
            "kind": args.kind,
            "action": args.action,
            "identifier": args.identifier,
            "method": method,
            "endpoint": endpoint,
            "tenant_id": tenant_id,
            "response": redact_payload(response),
            "preflight": preflight,
            "apply_report": apply_result,
        }
    )
    return 0


def reference_config(kind: str) -> dict[str, Any]:
    value = kind.strip().lower()
    if value not in REFERENCE_KINDS:
        raise XeroCliError(f"Unsupported reference kind: {kind}")
    return REFERENCE_KINDS[value]


def load_reference_payload(path: str) -> Any:
    payload = xero_finance_rules.load_json_file(Path(path).expanduser().resolve())
    if not isinstance(payload, (dict, list)):
        raise XeroCliError("Reference payload must be a JSON object, array, or already wrapped Xero request object.")
    return payload


def wrap_reference_payload(kind: str, payload: Any) -> dict[str, Any]:
    config = reference_config(kind)
    root_key = str(config["root_key"])
    if isinstance(payload, dict) and isinstance(payload.get(root_key), list):
        return payload
    if isinstance(payload, list):
        return {root_key: payload}
    if isinstance(payload, dict):
        return {root_key: [payload]}
    raise XeroCliError("Reference payload must be a JSON object or array.")


def reference_parent_id(kind: str, wrapped_payload: dict[str, Any]) -> str | None:
    config = reference_config(kind)
    parent_field = config.get("parent_id_field")
    if not parent_field:
        return None
    field = str(parent_field)
    candidates: list[Any] = []
    if wrapped_payload.get(field):
        candidates.append(wrapped_payload.get(field))
    records = wrapped_payload.get(str(config["root_key"]))
    if isinstance(records, list):
        for record in records:
            if isinstance(record, dict) and record.get(field):
                candidates.append(record.get(field))
    unique = {str(value).strip() for value in candidates if str(value).strip()}
    if len(unique) != 1:
        raise XeroCliError(f"{kind} payload must include exactly one {field}.")
    return next(iter(unique))


def reference_request_payload(kind: str, wrapped_payload: dict[str, Any]) -> dict[str, Any]:
    config = reference_config(kind)
    parent_field = config.get("parent_id_field")
    if not parent_field:
        return wrapped_payload
    field = str(parent_field)
    root_key = str(config["root_key"])
    records = wrapped_payload.get(root_key)
    if not isinstance(records, list):
        raise XeroCliError(f"{kind} payload must include a {root_key} list.")
    sanitized: list[Any] = []
    for record in records:
        if not isinstance(record, dict):
            raise XeroCliError(f"{kind} records must be JSON objects.")
        cleaned = dict(record)
        cleaned.pop(field, None)
        sanitized.append(cleaned)
    return {root_key: sanitized}


def reference_endpoint(kind: str, wrapped_payload: dict[str, Any]) -> str:
    config = reference_config(kind)
    if config.get("endpoint_template"):
        parent = reference_parent_id(kind, wrapped_payload)
        template = str(config["endpoint_template"])
        parent_field = str(config["parent_id_field"])
        return template.replace("{" + parent_field + "}", urllib.parse.quote(str(parent), safe=""))
    return str(config["endpoint"])


def first_reference_result(kind: str, response: Any) -> dict[str, Any]:
    if not isinstance(response, dict):
        return {}
    root_key = str(reference_config(kind)["root_key"])
    records = response.get(root_key)
    if isinstance(records, list) and records and isinstance(records[0], dict):
        return records[0]
    return {}


def reference_value(kind: str, record: dict[str, Any]) -> Any:
    config = reference_config(kind)
    for field in config.get("reference_fields", []):
        if record.get(field):
            return record[field]
    return None


def reference_method(kind: str, value: str | None = None) -> str:
    method = (value or str(reference_config(kind)["default_method"])).strip().upper()
    if method not in {"POST", "PUT"}:
        raise XeroCliError("Reference upsert method must be POST or PUT.")
    return method


def command_reference_upsert(args: argparse.Namespace) -> int:
    config = reference_config(args.kind)
    method = reference_method(args.kind, args.method)
    wrapped_payload = wrap_reference_payload(args.kind, load_reference_payload(args.payload))
    request_payload = reference_request_payload(args.kind, wrapped_payload)
    endpoint = reference_endpoint(args.kind, wrapped_payload)
    url = f"{ACCOUNTING_API_BASE}/{endpoint}"
    if args.summarize_errors is False:
        url += "?SummarizeErrors=false"
    if not args.apply:
        result = {
            "ok": True,
            "mode": "dry-run",
            "kind": args.kind,
            "method": method,
            "endpoint": endpoint,
            "would_apply": False,
            "payload": redact_payload(request_payload),
            "preflight": mutation_preflight_summary(kind=args.kind, endpoint=endpoint, payload=request_payload),
            "message": "No Xero mutation was made. Re-run with --apply after audit checks pass.",
        }
        if args.out:
            out_path = Path(args.out).expanduser().resolve()
            xero_finance_rules.write_json_file(out_path, result)
            write_json({"ok": True, "mode": "dry-run", "report": str(out_path), "kind": args.kind})
        else:
            write_json(result)
        return 0

    preflight = validate_mutation_preflight(args, kind=args.kind, endpoint=endpoint, payload=request_payload)
    payload, tenant_id = resolve_active_auth(args)
    response = http_send_json(method, url, accounting_headers(payload, tenant_id), request_payload)
    first = first_reference_result(args.kind, response)
    _guard_document_apply(response, id_value=first.get(config["id_key"]), kind=args.kind, endpoint=endpoint, first_elem=first)
    event = {
        "type": args.kind,
        "action": "api_reference_upsert",
        "status": first.get("Status") or first.get("ContactStatus") or "upserted",
        "reference": reference_value(args.kind, first),
        "xero_id": first.get(config["id_key"]),
        "tenant_id": tenant_id,
        "details": {
            "method": method,
            "endpoint": endpoint,
            "request": redact_payload(request_payload),
            "response": redact_payload(response),
        },
    }
    apply_result = xero_finance_rules.write_apply_report(xero_finance_rules.audit_dir(args.audit_dir), event, actor=args.actor)
    write_json(
        {
            "ok": True,
            "mode": "apply",
            "kind": args.kind,
            "method": method,
            "endpoint": endpoint,
            "tenant_id": tenant_id,
            "xero_id": event["xero_id"],
            "reference": event["reference"],
            "response": redact_payload(response),
            "preflight": preflight,
            "apply_report": apply_result,
        }
    )
    return 0


def command_prework_create(args: argparse.Namespace) -> int:
    config = prework_config(args.kind)
    request_payload = wrap_prework_payload(args.kind, load_prework_payload(args.payload))
    endpoint = config["endpoint"]
    url = f"{ACCOUNTING_API_BASE}/{endpoint}"
    if args.summarize_errors is False:
        url += "?SummarizeErrors=false"
    if not args.apply:
        result = {
            "ok": True,
            "mode": "dry-run",
            "kind": args.kind,
            "endpoint": endpoint,
            "would_apply": False,
            "payload": redact_payload(request_payload),
            "preflight": mutation_preflight_summary(kind=args.kind, endpoint=endpoint, payload=request_payload),
            "message": "No Xero mutation was made. Re-run with --apply after audit checks pass.",
        }
        if args.out:
            out_path = Path(args.out).expanduser().resolve()
            xero_finance_rules.write_json_file(out_path, result)
            write_json({"ok": True, "mode": "dry-run", "report": str(out_path), "kind": args.kind})
        else:
            write_json(result)
        return 0

    preflight = validate_mutation_preflight(args, kind=args.kind, endpoint=endpoint, payload=request_payload)
    payload, tenant_id = resolve_active_auth(args)
    response = http_send_json("POST", url, accounting_headers(payload, tenant_id), request_payload)
    first = first_prework_result(args.kind, response)
    _guard_document_apply(response, id_value=first.get(config["id_key"]), kind=args.kind, endpoint=endpoint, first_elem=first)
    event = {
        "type": args.kind,
        "action": "api_prework_create",
        "status": first.get("Status") or "created",
        "reference": first.get("Reference") or first.get("Narration") or first.get("PaymentID") or first.get("BatchPaymentID") or first.get("BankTransactionID") or first.get("BankTransferID") or first.get("ManualJournalID"),
        "xero_id": first.get(config["id_key"]),
        "tenant_id": tenant_id,
        "details": {
            "endpoint": endpoint,
            "request": redact_payload(request_payload),
            "response": redact_payload(response),
        },
    }
    apply_result = xero_finance_rules.write_apply_report(xero_finance_rules.audit_dir(args.audit_dir), event, actor=args.actor)
    write_json(
        {
            "ok": True,
            "mode": "apply",
            "kind": args.kind,
            "endpoint": endpoint,
            "tenant_id": tenant_id,
            "xero_id": event["xero_id"],
            "response": redact_payload(response),
            "preflight": preflight,
            "apply_report": apply_result,
        }
    )
    return 0


def command_audit_check_live(args: argparse.Namespace) -> int:
    config = LIVE_CHECK_KINDS[args.kind]
    store = TokenStore(token_store_path(args.store))
    payload = ensure_access_token(store)
    tenant_id = args.tenant_id or str(payload.get("active_tenant_id") or "")
    if not tenant_id:
        raise XeroCliError("No active tenant selected. Run `xero tenants list --refresh` then `xero tenants use <tenant-id>`.")
    where = live_check_query(args.kind, args.value, field=args.field)
    endpoint = str(config["endpoint"])
    response = http_get_json(
        f"{ACCOUNTING_API_BASE}/{endpoint}?" + urllib.parse.urlencode({"where": where}),
        {
            "Authorization": f"Bearer {payload.get('access_token')}",
            "xero-tenant-id": tenant_id,
        },
    )
    records = response.get(config["record_key"]) if isinstance(response, dict) else None
    if not isinstance(records, list):
        records = []
    write_json(
        {
            "ok": True,
            "kind": args.kind,
            "endpoint": endpoint,
            "where": where,
            "tenant_id": tenant_id,
            "found": len(records) > 0,
            "match_count": len(records),
            "records": records[: args.limit],
            "truncated": len(records) > args.limit,
        }
    )
    return 0


def command_audit_record_apply(args: argparse.Namespace) -> int:
    event = xero_finance_rules.load_json_file(Path(args.event).expanduser().resolve())
    if not isinstance(event, dict):
        raise xero_finance_rules.FinanceRulesError("Apply event file must contain a JSON object.")
    payload = xero_finance_rules.write_apply_report(
        xero_finance_rules.audit_dir(args.audit_dir),
        event,
        actor=args.actor,
    )
    write_json(payload)
    return 0


def command_audit_list_apply(args: argparse.Namespace) -> int:
    payload = xero_finance_rules.list_apply_reports(
        xero_finance_rules.audit_dir(args.audit_dir),
        limit=args.limit,
    )
    write_json(payload)
    return 0


def snapshot_file_path(root: str | None, kind: str) -> Path:
    return xero_finance_rules.snapshot_dir(root) / f"{kind.replace('-', '_')}.json"


def command_snapshots_fetch(args: argparse.Namespace) -> int:
    config = SNAPSHOT_KINDS[args.kind]
    store = TokenStore(token_store_path(args.store))
    payload = ensure_access_token(store)
    tenant_id = args.tenant_id or str(payload.get("active_tenant_id") or "")
    if not tenant_id:
        raise XeroCliError("No active tenant selected. Run `xero tenants list --refresh` then `xero tenants use <tenant-id>`.")
    endpoint = config["endpoint"]
    headers = {
        "Authorization": f"Bearer {payload.get('access_token')}",
        "xero-tenant-id": tenant_id,
    }
    is_singleton = bool(config.get("singleton"))
    if is_singleton:
        # The Organisation endpoint returns a single object under
        # Organisations:[{...}], NOT a paged records list. Extract the first
        # element and store it under "organisation" for direct field access.
        query = "?" + urllib.parse.urlencode({"where": args.where}) if args.where else ""
        response = http_get_json(f"{ACCOUNTING_API_BASE}/{endpoint}{query}", headers)
        raw_list = response.get(config["record_key"]) if isinstance(response, dict) else None
        organisation = raw_list[0] if isinstance(raw_list, list) and raw_list else {}
        output = {
            "schema_version": 1,
            "kind": args.kind,
            "source": "xero-api",
            "tenant_id": tenant_id,
            "fetched_at": utc_seconds(),
            "organisation": organisation,
        }
        path = snapshot_file_path(args.snapshots, args.kind)
        xero_finance_rules.write_json_file(path, output)
        write_json({"ok": True, "kind": args.kind, "snapshot": str(path), "organisation": organisation})
        return 0
    if config.get("paged"):
        # Paged GET returns full per-record detail (e.g. Contacts PaymentTerms +
        # PurchasesDefaultAccountCode, which the unpaged LIST projection omits).
        records = paged_accounting_get(
            endpoint, config["record_key"], headers, where=(args.where or "")
        )
    else:
        query = "?" + urllib.parse.urlencode({"where": args.where}) if args.where else ""
        response = http_get_json(f"{ACCOUNTING_API_BASE}/{endpoint}{query}", headers)
        records = response.get(config["record_key"]) if isinstance(response, dict) else None
    if not isinstance(records, list):
        records = []
    output = {
        "schema_version": 1,
        "kind": args.kind,
        "source": "xero-api",
        "tenant_id": tenant_id,
        "fetched_at": utc_seconds(),
        "record_count": len(records),
        "records": records,
    }
    path = snapshot_file_path(args.snapshots, args.kind)
    xero_finance_rules.write_json_file(path, output)
    write_json({"ok": True, "kind": args.kind, "snapshot": str(path), "record_count": len(records)})
    return 0


def load_org_snapshot(snapshots_root: str | None = None) -> dict[str, Any]:
    """Load the organisation snapshot and return the raw organisation object.

    Returns an empty dict when the snapshot file is absent or unreadable — the
    caller falls back gracefully (no lock date → use policy frozen_before).
    """
    path = snapshot_file_path(snapshots_root, "organisation")
    if not path.is_file():
        return {}
    try:
        data = xero_finance_rules.load_json_file(path)
    except xero_finance_rules.FinanceRulesError:
        return {}
    if not isinstance(data, dict):
        return {}
    return data.get("organisation") if isinstance(data.get("organisation"), dict) else {}


def org_snapshot_fetched_at(snapshots_root: str | None = None) -> int | None:
    """Return the organisation snapshot's ``fetched_at`` epoch seconds, or None.

    Pure/testable: reads only the local snapshot file. Used to warn when the
    snapshot's lock date may be stale (a BAS lodged after the snapshot was taken
    advances Xero's lock date, but the snapshot would not reflect it).
    """
    path = snapshot_file_path(snapshots_root, "organisation")
    if not path.is_file():
        return None
    try:
        data = xero_finance_rules.load_json_file(path)
    except xero_finance_rules.FinanceRulesError:
        return None
    if not isinstance(data, dict):
        return None
    fetched = data.get("fetched_at")
    return int(fetched) if isinstance(fetched, (int, float)) else None


# A snapshot lock date older than this is warned about as possibly-stale.
ORG_SNAPSHOT_STALE_SECONDS = 7 * 86400


def fetch_org_live(payload: dict[str, Any], tenant_id: str) -> dict[str, Any]:
    """Live GET /Organisation → the raw organisation object (or {} on miss).

    The live fallback for the lock date when no organisation snapshot exists.
    Read-only; uses the already-resolved auth payload + tenant.
    """
    response = http_get_json(
        f"{ACCOUNTING_API_BASE}/Organisation",
        accounting_headers(payload, tenant_id),
    )
    raw_list = response.get("Organisations") if isinstance(response, dict) else None
    return raw_list[0] if isinstance(raw_list, list) and raw_list else {}


def org_lock_date(org: dict[str, Any]) -> str | None:
    """Extract the effective Xero lock date from an organisation snapshot object.

    Considers BOTH ``PeriodLockDate`` (the BAS/GST period lock) and
    ``EndOfYearLockDate`` (the financial-year lock) and returns the LATER of the
    two — whichever locks more of the ledger is the binding boundary. Xero emits
    these as MS-JSON (``/Date(ms+offset)/``) or ISO; both are normalised to
    YYYY-MM-DD. Returns None when neither is set, so the frozen-period guard
    falls back to ap-policy.frozen_before.

    A .NET unset sentinel (``0001-01-01`` / ``/Date(-62135596800000+0000)/``)
    parses to a real date but means "no lock"; any date before ~1990 is treated
    as unset so it neither freezes anything nor suppresses the fallback/warning.
    """
    candidates: list[str] = []
    for field in ("PeriodLockDate", "EndOfYearLockDate"):
        iso = xero_iso_date_from_value(org.get(field))
        # Reject .NET DateTime.MinValue-style sentinels (and any absurd past date).
        if iso and iso >= "1990-01-01":
            candidates.append(iso)
    if not candidates:
        return None
    # ISO YYYY-MM-DD strings sort lexicographically == chronologically.
    return max(candidates)


def org_default_payment_terms(org: dict[str, Any]) -> dict[str, Any] | None:
    """Extract the org-level default PaymentTerms from an organisation snapshot.

    Xero shape: ``{"PaymentTerms": {"Bills": {"Day": N, "Type": "..."}, ...}}``.
    Returns the raw PaymentTerms dict (with Bills/Sales sub-keys) or None.
    """
    pt = org.get("PaymentTerms")
    return pt if isinstance(pt, dict) else None


def contact_payment_terms(contact: dict[str, Any]) -> dict[str, Any] | None:
    """Extract the PaymentTerms from a full Contacts API record.

    The full GET returns ``{"PaymentTerms": {"Bills": {"Day": N, "Type": "..."}}}``
    when configured; the summary/list projection omits it. Returns None when absent.
    """
    pt = contact.get("PaymentTerms")
    return pt if isinstance(pt, dict) else None


def find_contact_in_snapshot(
    snapshots_root: str | None,
    contact_id_or_name: str,
) -> dict[str, Any]:
    """Find a contact in the contacts snapshot by ContactID or Name.

    Returns an empty dict when not found (caller uses org default / built-in).
    The contacts snapshot must be fetched with the full GET (not summary) to
    include PaymentTerms and PurchasesDefaultAccountCode.
    """
    path = snapshot_file_path(snapshots_root, "contacts")
    if not path.is_file():
        return {}
    try:
        data = xero_finance_rules.load_json_file(path)
    except xero_finance_rules.FinanceRulesError:
        return {}
    if not isinstance(data, dict):
        return {}
    records = data.get("records")
    if not isinstance(records, list):
        return {}
    needle = (contact_id_or_name or "").strip().lower()
    for rec in records:
        if not isinstance(rec, dict):
            continue
        if str(rec.get("ContactID") or "").lower() == needle:
            return rec
        if str(rec.get("Name") or "").strip().lower() == needle:
            return rec
    return {}


def command_snapshots_list(args: argparse.Namespace) -> int:
    root = xero_finance_rules.snapshot_dir(args.snapshots)
    items = []
    for path in sorted(root.glob("*.json")) if root.exists() else []:
        try:
            payload = xero_finance_rules.load_json_file(path)
        except xero_finance_rules.FinanceRulesError:
            items.append({"path": str(path), "ok": False, "error": "invalid JSON"})
            continue
        records = []
        if isinstance(payload, dict):
            for key in ("records", "items", "invoices", "bills", "payments", "bank_transactions"):
                if isinstance(payload.get(key), list):
                    records = payload[key]
                    break
        elif isinstance(payload, list):
            records = payload
        items.append(
            {
                "path": str(path),
                "ok": True,
                "kind": payload.get("kind") if isinstance(payload, dict) else path.stem,
                "source": payload.get("source") if isinstance(payload, dict) else None,
                "fetched_at": payload.get("fetched_at") if isinstance(payload, dict) else None,
                "record_count": len(records),
            }
        )
    write_json({"ok": True, "snapshot_dir": str(root), "snapshots": items})
    return 0


def command_lock_acquire(args: argparse.Namespace) -> int:
    path = xero_operation_lock.lock_store_path(args.lock_store)
    payload = xero_operation_lock.acquire_lock(
        path,
        holder=args.holder,
        wait=args.wait,
        timeout_seconds=args.timeout,
        ttl_seconds=args.ttl,
    )
    write_json(payload)
    return 0 if payload.get("acquired") else 1


def command_lock_release(args: argparse.Namespace) -> int:
    path = xero_operation_lock.lock_store_path(args.lock_store)
    payload = xero_operation_lock.release_lock(path, args.lease_id)
    write_json(payload)
    return 0 if payload.get("released") else 1


def command_lock_status(args: argparse.Namespace) -> int:
    path = xero_operation_lock.lock_store_path(args.lock_store)
    write_json(xero_operation_lock.lock_status(path))
    return 0


# ---------------------------------------------------------------------------
# Phase 3 — Ingestion: sidecar parse (xero ap ingest-sidecar)
# ---------------------------------------------------------------------------


def command_ap_ingest_sidecar(args: argparse.Namespace) -> int:
    """Parse a structured sidecar into a normalised bill candidate (pure, no network).

    With ``--out`` the file is written in ``{"candidates": [candidate], ...}`` shape
    so it can be passed directly to ``xero audit dry-run --candidates <file>`` for
    dedup/mapping checks. ``ap draft-bill`` does not take a payload file: build it
    from the candidate's structured fields (``--contact-id``, ``--bill-date``,
    ``--line ACCOUNT:TAX:AMOUNT[:DESCRIPTION]``) — see candidate_to_draft_bill_args.

    This command does NOT create anything in Xero. It is a pure local transform.

    Bill-ingestion input lanes NOT controlled by this tool (UI-only):
      • Bills email address — email a PDF to the org's unique Xero address; a
        DRAFT bill is created in the UI. No API control.
      • Hubdoc — no public API; Hubdoc-extracted drafts appear as DRAFT bills.
    In both cases run ``xero audit dry-run`` to pick up and code the resulting drafts.
    """
    candidate = xero_ingestion.ingest_sidecar(
        args.sidecar,
        source_file=args.source_file or args.sidecar,
    )
    draft_bill_args = xero_ingestion.candidate_to_draft_bill_args(candidate)
    result = {
        "ok": True,
        "mode": "ingest-sidecar",
        "sidecar": args.sidecar,
        "source_file": args.source_file or args.sidecar,
        # `candidates` (array) so an --out file is directly consumable by
        # `xero audit dry-run --candidates` (load_candidates accepts this shape).
        "candidates": [candidate],
        "candidate": candidate,  # kept for human readability of stdout
        "ap_draft_bill_args": draft_bill_args,
        "ingestion_lanes_note": xero_ingestion.ui_ingestion_lanes_note(),
        "next_steps": [
            "Review the candidate payload above.",
            "Run `xero audit dry-run --candidates <file>` to check for duplicates and mapping issues.",
            "Run `xero ap draft-bill --ap-policy <pack>/ap-policy.json` with the ap_draft_bill_args "
            "above (resolve account/tax codes first) to create the DRAFT bill.",
        ],
    }
    if args.out:
        out_path = Path(args.out).expanduser().resolve()
        xero_finance_rules.write_json_file(out_path, result)
        write_json({"ok": True, "mode": "ingest-sidecar", "report": str(out_path)})
    else:
        write_json(result)
    return 0


# ---------------------------------------------------------------------------
# Phase 3 — Batch payments (xero ap batch-pay)
# ---------------------------------------------------------------------------

# Xero BatchPayment platform constraints (verified 2026-06-10, §8.4 of design doc):
#   • Base currency only — multi-currency bills fall back to single payments.
#   • ACCPAY (bills) only — cannot mix ACCREC invoices.
#   • No credit notes, prepayments, or overpayments in the batch.
#   • Creates one AUTHORISED BatchPayment per bank movement (one statement line).
#   • HONESTY: the API records payments; it does NOT move money or emit an ABA file.
#     ABA download / direct bank payment is a UI-only human action.
#   Reference: https://developer.xero.com/documentation/api/accounting/batchpayments
_BATCH_PAY_HONESTY_NOTICE = (
    "HONESTY NOTICE — Recorded-payment boundary:\n"
    "  The Xero Accounting API *records* a payment and marks bills as PAID.\n"
    "  It does NOT initiate a bank transfer or emit an ABA file.\n"
    "  The real money movement is a HUMAN action: pay via online banking or\n"
    "  download an ABA file from the Xero UI (Pay multiple bills → Download).\n"
    "  A recorded payment with no matching statement line within {days} days\n"
    "  triggers a reconciliation alert (see `xero evidence audit`)."
)
_BATCH_PAY_UNMATCHED_ALERT_DAYS = 5  # flag if no statement-line match within N days


def extract_validation_errors(response: Any) -> list[dict[str, Any]]:
    """Collect ValidationErrors from a SummarizeErrors=false Xero response.

    With ?SummarizeErrors=false Xero returns HTTP 200 even when elements fail
    validation, surfacing the failures as per-element ``ValidationErrors`` (and a
    ``HasValidationErrors`` flag). Recurses into every nested dict/list so errors
    at any depth are caught — e.g. ``BatchPayments[0].Payments[j].ValidationErrors``
    — not just the top level and first array level.
    """
    errors: list[dict[str, Any]] = []

    def _walk(node: Any) -> None:
        if isinstance(node, dict):
            for key, value in node.items():
                if key == "ValidationErrors" and isinstance(value, list):
                    errors.extend(e for e in value if isinstance(e, dict))
                else:
                    _walk(value)
        elif isinstance(node, list):
            for item in node:
                _walk(item)

    _walk(response)
    return errors


def _guard_document_apply(
    response: Any,
    *,
    id_value: Any,
    kind: str,
    endpoint: str,
    first_elem: dict[str, Any] | None = None,
) -> None:
    """Fail closed on SummarizeErrors=false HTTP-200 responses that embed errors.

    With ``?SummarizeErrors=false`` Xero returns HTTP 200 even when the element
    is REJECTED, embedding failures as per-element ``ValidationErrors``/
    ``HasValidationErrors``. A missing created-object ID is also treated as a
    failure signal.  Raises ``XeroCliError`` — BEFORE any apply-ledger write or
    success report — when any of those conditions are detected.

    Reuses ``extract_validation_errors`` so all depths are covered.  Called by
    ``command_documents_create``, ``command_ap_draft_bill``,
    ``command_documents_update``, ``command_reference_upsert``, and
    ``command_prework_create``; mirrors the fail-closed stance of
    ``command_ap_batch_pay``.

    ``first_elem`` is the already-extracted first result record (from the
    caller's ``first_*_result`` helper); when provided it is used for the
    ``HasValidationErrors`` check. When ``None`` it falls back to a heuristic
    scan of the response for the first list-of-dicts.
    """
    validation_errors = extract_validation_errors(response)
    # Check HasValidationErrors on the first element. Prefer the caller-supplied
    # record; otherwise heuristically scan the response for the first list-of-dicts.
    if first_elem is None:
        first_elem = {}
        if isinstance(response, dict):
            for _key, _val in response.items():
                if isinstance(_val, list) and _val and isinstance(_val[0], dict):
                    first_elem = _val[0]
                    break
    has_errors = bool(
        validation_errors
        or first_elem.get("HasValidationErrors")
        or not id_value
    )
    if has_errors:
        raise XeroCliError(
            f"Xero reported validation errors / no usable {kind} ID for the {kind} {endpoint} mutation; "
            "failing closed. No apply-ledger entry was written. "
            "NOTE: with SummarizeErrors=false a multi-record payload can partially succeed — "
            "some records may have been applied in Xero even though this command failed closed. "
            "Verify in the Xero UI and correct any issues before re-running. "
            f"Validation errors: {json.dumps(validation_errors) if validation_errors else 'none returned (missing ID or HasValidationErrors)'}."
        )


def _preflight_batch_payment_payload(
    raw_payments: list[dict[str, Any]],
    *,
    bank_account_id: str,
    payment_date: str,
    reference: str | None,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """Validate + assemble a BatchPayments payload from a list of bill-payment specs.

    Each spec must have: ``invoice_id`` (ACCPAY bill InvoiceID) and ``amount``.
    Optional: ``currency_rate`` (for future FX; currently rejected for non-base).

    Enforced constraints (§8.4):
      • All bills must be ACCPAY (checked client-side via kind field if supplied).
      • No ACCREC invoices, credit notes, prepayments, or overpayments.
      • No per-payment currency_rate (base-currency only).

    Returns (wrapped_payload, validated_items).
    """
    if not raw_payments:
        raise XeroCliError("batch-pay requires at least one payment item")

    validated: list[dict[str, Any]] = []
    seen_invoice_ids: set[str] = set()
    for idx, item in enumerate(raw_payments, start=1):
        if not isinstance(item, dict):
            raise XeroCliError(f"batch-pay payment item {idx} must be an object")
        invoice_id = str(item.get("invoice_id") or item.get("InvoiceID") or "").strip()
        if not invoice_id:
            raise XeroCliError(f"batch-pay item {idx}: 'invoice_id' is required")
        if not looks_like_uuid(invoice_id):
            raise XeroCliError(
                f"batch-pay item {idx}: 'invoice_id' must be a UUID, got {invoice_id!r}. "
                "Run `xero audit check-live bill <reference>` to find the InvoiceID."
            )
        # A bill appearing twice in one batch would be double-paid. Reject it.
        norm_id = invoice_id.lower()
        if norm_id in seen_invoice_ids:
            raise XeroCliError(
                f"batch-pay item {idx}: duplicate invoice_id {invoice_id!r} in the batch — "
                "a bill must appear at most once or it would be double-paid."
            )
        seen_invoice_ids.add(norm_id)
        amount = xero_finance_rules.parse_money(item.get("amount") or item.get("Amount"))
        if amount is None or amount <= 0:
            raise XeroCliError(
                f"batch-pay item {idx}: 'amount' must be a positive number, got {item.get('amount')!r}"
            )
        # Reject explicit currency_rate (base-currency constraint).
        if item.get("currency_rate") is not None or item.get("CurrencyRate") is not None:
            raise XeroCliError(
                f"batch-pay item {idx}: 'currency_rate' is not permitted — BatchPayments "
                "only support base-currency bills. Multi-currency suppliers require single payments."
            )
        # Reject explicit type if it isn't ACCPAY.
        kind = str(item.get("type") or item.get("Type") or "ACCPAY").strip().upper()
        if kind and kind != "ACCPAY":
            raise XeroCliError(
                f"batch-pay item {idx}: only ACCPAY (bill) payments are allowed in a batch; "
                f"got Type={kind!r}. Xero does not allow mixing ACCREC invoices."
            )
        validated.append(
            {
                "Invoice": {"InvoiceID": invoice_id},
                "Amount": amount,
            }
        )

    total = round(sum(v["Amount"] for v in validated), 2)
    batch: dict[str, Any] = {
        "Account": {"AccountID": bank_account_id},
        "Date": payment_date,
        "Payments": validated,
    }
    if reference:
        batch["Reference"] = reference

    wrapped = {"BatchPayments": [batch]}
    return wrapped, validated


def command_ap_batch_pay(args: argparse.Namespace) -> int:
    """Record a batch payment against a reviewed set of ACCPAY bills.

    IMPORTANT — Recorded-payment honesty (§4.4, §8.4 of design doc):

    The Xero Accounting API *records* the payment and marks bills as PAID.
    It does NOT initiate a bank transfer or emit an ABA file. The real money
    movement is a human action: pay via online banking or download an ABA file
    from the Xero UI (Accounts → Bills to Pay → Pay multiple bills → Download).

    Platform constraints enforced in preflight (verified 2026-06-10):
      • Base currency only — multi-currency falls back to single payments.
      • ACCPAY bills only — ACCREC invoices cannot be mixed.
      • No credit notes, prepayments, or overpayments.

    Dry-run by default. --apply gated on a preflight report.
    Operation lock held for the duration of the apply step.

    Recorded-payment alert: a recorded payment with no matching statement line
    within {days} days is flagged as a reconciliation warning.
    """.format(
        days=_BATCH_PAY_UNMATCHED_ALERT_DAYS
    )
    payments_raw = xero_finance_rules.load_json_file(
        Path(args.payments).expanduser().resolve()
    )
    if isinstance(payments_raw, dict) and isinstance(payments_raw.get("payments"), list):
        payments_raw = payments_raw["payments"]
    if not isinstance(payments_raw, list):
        raise XeroCliError("batch-pay --payments must be a JSON array or an object with a 'payments' array")

    payment_date = (args.payment_date or time.strftime("%Y-%m-%d", time.gmtime())).strip()
    bank_account_id = args.bank_account_id.strip()
    if not looks_like_uuid(bank_account_id):
        raise XeroCliError(
            f"--bank-account-id must be a UUID, got {bank_account_id!r}. "
            "Run `xero audit check-live bank-transaction` or check the accounts snapshot."
        )

    request_payload, validated_items = _preflight_batch_payment_payload(
        payments_raw,
        bank_account_id=bank_account_id,
        payment_date=payment_date,
        reference=args.reference or None,
    )
    total_amount = round(sum(v["Amount"] for v in validated_items), 2)
    endpoint = "BatchPayments"
    honesty_notice = _BATCH_PAY_HONESTY_NOTICE.format(days=_BATCH_PAY_UNMATCHED_ALERT_DAYS)

    if not args.apply:
        result = {
            "ok": True,
            "mode": "dry-run",
            "kind": "batch-payment",
            "endpoint": endpoint,
            "payment_date": payment_date,
            "bank_account_id": bank_account_id,
            "bill_count": len(validated_items),
            "total_amount": total_amount,
            "reference": args.reference or None,
            "payload": redact_payload(request_payload),
            "preflight": mutation_preflight_summary(
                kind="batch-payment", endpoint=endpoint, payload=request_payload
            ),
            "honesty_notice": honesty_notice,
            "recorded_payment_alert_days": _BATCH_PAY_UNMATCHED_ALERT_DAYS,
            "message": (
                "No Xero mutation was made. Re-run with --apply (with a preflight report) "
                "to record this batch payment. Ensure the real bank transfer has been "
                "authorised first."
            ),
            "constraints_enforced": [
                "Base currency only (no CurrencyRate per item)",
                "ACCPAY bills only (no ACCREC, credit notes, prepayments, overpayments)",
            ],
        }
        if getattr(args, "out", None):
            out_path = Path(args.out).expanduser().resolve()
            xero_finance_rules.write_json_file(out_path, result)
            write_json({"ok": True, "mode": "dry-run", "report": str(out_path), "kind": "batch-payment"})
        else:
            write_json(result)
        return 0

    preflight = validate_mutation_preflight(
        args, kind="batch-payment", endpoint=endpoint, payload=request_payload
    )
    payload, tenant_id = resolve_active_auth(args)
    headers = accounting_headers(payload, tenant_id)
    url = f"{ACCOUNTING_API_BASE}/{endpoint}?SummarizeErrors=false"

    audit_root = xero_finance_rules.audit_dir(args.audit_dir)
    lock_path = xero_operation_lock.lock_store_path(None)
    lease = xero_operation_lock.acquire_lock(lock_path, holder="ap-batch-pay", wait=True)
    if not lease.get("acquired"):
        raise XeroCliError("Could not acquire the Xero operation lock for batch payment.")

    try:
        response = http_send_json("POST", url, headers, request_payload)
        batch_results = (
            response.get("BatchPayments") if isinstance(response, dict) else None
        ) or []
        first_batch = batch_results[0] if batch_results and isinstance(batch_results[0], dict) else {}
        batch_id = first_batch.get("BatchPaymentID")
        # SummarizeErrors=false makes Xero return HTTP 200 even when the batch is
        # rejected, embedding per-element ValidationErrors. NEVER record a ledger
        # entry for a batch we cannot prove was applied: a missing BatchPaymentID
        # or any validation error means we fail closed. Raise inside the try so
        # the operation lock still releases in the finally; no apply-ledger write.
        batch_status = str(first_batch.get("Status") or "").strip().upper()
        validation_errors = extract_validation_errors(response)
        if not batch_id or first_batch.get("HasValidationErrors") or validation_errors or batch_status == "REJECTED":
            # Xero may return a BatchPaymentID alongside errors/REJECTED; we cannot
            # assert "nothing was recorded" in that case, so word it as fail-closed
            # and point the human to verify in the UI.
            raise XeroCliError(
                "Xero reported validation errors / no usable BatchPaymentID for the batch payment; "
                "treated as NOT recorded (failing closed). No apply-ledger entry was written. "
                f"Verify in the Xero UI (batch id, if any: {batch_id or 'none returned'}). "
                f"Errors: {json.dumps(validation_errors) if validation_errors else 'see response'}. "
                "Fix the payments and re-run."
            )
        event = {
            "type": "batch-payment",
            "action": "api_ap_batch_pay",
            "status": batch_status or "recorded",
            "reference": first_batch.get("Reference") or args.reference,
            "xero_id": batch_id,
            "tenant_id": tenant_id,
            "details": {
                "endpoint": endpoint,
                "bill_count": len(validated_items),
                "total_amount": total_amount,
                "payment_date": payment_date,
                "bank_account_id": bank_account_id,
                "request": redact_payload(request_payload),
                "response": redact_payload(response),
            },
        }
        apply_result = xero_finance_rules.write_apply_report(audit_root, event, actor=args.actor)
    finally:
        xero_operation_lock.release_lock(lock_path, lease["lease_id"])

    write_json(
        {
            "ok": True,
            "mode": "apply",
            "kind": "batch-payment",
            "endpoint": endpoint,
            "tenant_id": tenant_id,
            "batch_payment_id": batch_id,
            "status": event["status"],
            "bill_count": len(validated_items),
            "total_amount": total_amount,
            "payment_date": payment_date,
            "reference": args.reference or None,
            "honesty_notice": honesty_notice,
            "recorded_payment_alert_days": _BATCH_PAY_UNMATCHED_ALERT_DAYS,
            "response": redact_payload(response),
            "preflight": preflight,
            "apply_report": apply_result,
            "next_steps": [
                "Verify the real bank transfer has cleared.",
                f"Run `xero evidence audit` within {_BATCH_PAY_UNMATCHED_ALERT_DAYS} days to "
                "confirm the statement line matches this recorded payment.",
                "Run `xero reconcile` to clear the matching statement line via CDP.",
            ],
        }
    )
    return 0


def build_unmatched_payment_alerts(
    payments: list[dict[str, Any]],
    *,
    alert_days: int,
    now_ts: float | None = None,
) -> dict[str, Any]:
    """Pure helper: flag ACCPAY payments that are aged AND not yet reconciled.

    The Payments resource carries a read-only ``IsReconciled`` boolean
    (Xero Accounting API — Payments; mirrored on BankTransactions/BatchPayments
    in the OpenAPI spec). When that flag is present and True the payment HAS a
    matching, reconciled statement line, so it is skipped — this is what makes
    the control "unmatched" rather than merely "aged". When the field is absent
    from a payload we fall back to flagging by age and mark the alert
    ``reconciliation_status: "unknown"`` so the output never implies a check it
    could not perform.

    ACCPAY filtering is client-side (the Payments where-clause does not reliably
    support a nested ``Invoice.Type`` filter). Dates are interpreted in UTC via
    ``calendar.timegm`` so the comparison matches ``time.time()`` (UTC) without
    local-timezone skew.

    Returns a dict ``{"alerts": [...], "skipped_undateable": [...]}``. Undateable
    candidate payments (no/unparseable date) are NOT silently dropped — they are
    surfaced under ``skipped_undateable`` so an operator can investigate, rather
    than the control swallowing them.
    """
    now = time.time() if now_ts is None else now_ts
    cutoff_ts = now - (alert_days * 86400)
    alerts: list[dict[str, Any]] = []
    skipped_undateable: list[dict[str, Any]] = []
    for pmt in payments:
        # Keep ACCPAY filtering client-side; ACCREC/credit-note payments carry
        # no AP statement-line obligation here.
        invoice = pmt.get("Invoice") if isinstance(pmt.get("Invoice"), dict) else {}
        if str(invoice.get("Type") or "").strip().upper() != "ACCPAY":
            continue
        # If Xero says the payment is reconciled, it already has a matching
        # statement line — not "unmatched". Skip it. Only None means "unknown".
        is_reconciled = pmt.get("IsReconciled")
        if is_reconciled is True:
            continue
        date_str = xero_object_iso_date(pmt)
        pmt_ts: int | None = None
        if date_str:
            # xero_object_iso_date can return a 10-char string whose tail is not a
            # valid month/day (its gate only checks the leading 4 digits), so guard
            # strptime against ValueError rather than crashing the whole sweep.
            try:
                pmt_ts = calendar.timegm(time.strptime(date_str, "%Y-%m-%d"))
            except ValueError:
                pmt_ts = None
        if pmt_ts is None:
            skipped_undateable.append(
                {
                    "payment_id": pmt.get("PaymentID"),
                    "amount": pmt.get("Amount"),
                    "date": date_str,
                    "reference": pmt.get("Reference"),
                    "invoice_id": invoice.get("InvoiceID"),
                    "reason": "no parsable payment date — verify manually in Xero",
                }
            )
            continue
        if pmt_ts >= cutoff_ts:
            continue  # recent, not yet alertable
        recon_status = "unreconciled" if is_reconciled is False else "unknown"
        if recon_status == "unknown":
            alert_msg = (
                f"Recorded payment is >{alert_days} days old and Xero did not return an "
                "IsReconciled flag for it — verify a matching statement line was cleared "
                "via the CDP reconcile engine."
            )
        else:
            alert_msg = (
                f"Recorded payment is >{alert_days} days old and is NOT reconciled in Xero "
                "(no matching statement line) — investigate the bank movement or clear it "
                "via the CDP reconcile engine."
            )
        alerts.append(
            {
                "payment_id": pmt.get("PaymentID"),
                "amount": pmt.get("Amount"),
                "date": date_str,
                "reference": pmt.get("Reference"),
                "invoice_id": invoice.get("InvoiceID"),
                "days_old": int((now - pmt_ts) / 86400),
                "reconciliation_status": recon_status,
                "alert": alert_msg,
            }
        )
    return {"alerts": alerts, "skipped_undateable": skipped_undateable}


def command_ap_check_unmatched_payments(args: argparse.Namespace) -> int:
    """Read-only alert: aged ACCPAY payments not reconciled to a statement line.

    Pages the Payments endpoint for AUTHORISED ACCPAY payments older than
    --alert-days that Xero reports as not reconciled (``IsReconciled`` false, or
    unknown if the field is absent). A reconciled payment already has a matching
    statement line and is excluded. Read-only; no mutation.
    """
    payload, tenant_id = resolve_active_auth(args)
    headers = accounting_headers(payload, tenant_id)
    alert_days = int(args.alert_days or _BATCH_PAY_UNMATCHED_ALERT_DAYS)

    # Fetch AUTHORISED, not-yet-reconciled payments. ACCPAY is filtered
    # client-side. The `&&` operator is the connector's where-clause convention
    # (see live_check_query); we avoid the unverified nested `Invoice.Type`
    # server-side filter on the Payments endpoint.
    payments = paged_accounting_get(
        "Payments",
        "Payments",
        headers,
        where='Status=="AUTHORISED"&&IsReconciled==false',
    )

    alert_result = build_unmatched_payment_alerts(payments, alert_days=alert_days)
    alerts = alert_result["alerts"]
    skipped_undateable = alert_result["skipped_undateable"]

    write_json(
        {
            "ok": True,
            "mode": "aged-unreconciled-payment-alert",
            "tenant_id": tenant_id,
            "alert_days": alert_days,
            "total_payments_scanned": len(payments),
            "unmatched_alert_count": len(alerts),
            "skipped_undateable_count": len(skipped_undateable),
            "alerts": alerts,
            "skipped_undateable": skipped_undateable,
            "honesty_notice": (
                "Read-only check. Flags AUTHORISED ACCPAY payments older than the threshold "
                "that Xero reports as not reconciled (IsReconciled==false). A reconciled "
                "payment already has a matching statement line and is excluded. Payments with "
                "no parsable date are surfaced under skipped_undateable, not dropped. Definitive "
                "statement-line matching is confirmed by the CDP reconcile engine."
            ),
        }
    )
    return 0


# ---------------------------------------------------------------------------
# Phase 4 — Multi-org onboarding (xero org onboard / org validate)
# ---------------------------------------------------------------------------

# Country compliance modules registry.
# Each entry maps a country code → a callable(policy, live_accounts, live_tax_rates)
# that returns a list of compliance issues (dicts with 'rule', 'severity', 'message').
# AU is implemented; other countries are additive (wire a thin module here when needed).
#
# The AU module enforces:
#   1. Legal AU tax type set — codes not in this list are flagged as unknown.
#   2. Frozen-period guard — bill dates before frozen_before are rejected (ap-policy).
#      The guard is already in xero_ap_policy.is_frozen(); we surface it here too.
#
# Reference: accounting skill — Australian GST/BAS tax types.
# Standard Xero AU GST tax types. Source: Xero TaxType enum / AU GST setup
# (developer.xero.com Types — TaxType, AU column). ZERORATED is a UK/global type,
# NOT an AU Xero tax type, so it is deliberately excluded.
_AU_LEGAL_TAX_TYPES: frozenset[str] = frozenset(
    [
        "OUTPUT",          # GST on income (sales)
        "INPUT",           # GST on expenses
        "CAPEXINPUT",      # GST on capital expenses (imports/capital purchases)
        "INPUTTAXED",      # Input-taxed (e.g. residential rent, financial supplies)
        "EXEMPTOUTPUT",    # GST-free income / sales
        "EXEMPTEXPENSES",  # GST-free expenses (e.g. overseas SaaS)
        "EXEMPTCAPITAL",   # GST-free capital
        "EXEMPTEXPORT",    # Export sales (GST free)
        "BASEXCLUDED",     # Items outside the BAS
        "GSTONIMPORTS",    # GST on imports
        "NONE",            # No tax
    ]
)


def _compliance_check_au(
    policy: dict[str, Any],
    live_accounts: list[dict[str, Any]],
    live_tax_rates: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """AU compliance checks: legal tax-type set + frozen-period guard."""
    issues: list[dict[str, Any]] = []

    # Check live tax types against the AU legal set.
    live_tax_type_codes = {
        str(tr.get("TaxType") or "").strip().upper()
        for tr in live_tax_rates
        if isinstance(tr, dict) and tr.get("TaxType")
    }
    unknown = live_tax_type_codes - _AU_LEGAL_TAX_TYPES - {""}
    for code in sorted(unknown):
        issues.append(
            {
                "rule": "unknown_au_tax_type",
                "severity": "warning",
                "message": (
                    f"Tax type {code!r} is not in the standard AU GST tax-type set. "
                    "Confirm it is a valid Xero AU tax type for this org's GST registration."
                ),
                "code": code,
            }
        )

    # Frozen-period guard surface (the hard enforcement is in ap draft-bill).
    frozen_before = policy.get("frozen_before")
    if frozen_before:
        issues.append(
            {
                "rule": "frozen_period_guard",
                "severity": "info",
                "message": (
                    f"BAS frozen period: bills dated before {frozen_before} are blocked by the "
                    "AP policy (xero ap draft-bill --confirm-frozen-period to override). "
                    "Verify this matches your most recently lodged BAS period."
                ),
                "frozen_before": frozen_before,
            }
        )

    return issues


_COMPLIANCE_MODULES: dict[str, Any] = {
    "AU": _compliance_check_au,
}


def _run_compliance_checks(
    country: str,
    policy: dict[str, Any],
    live_accounts: list[dict[str, Any]],
    live_tax_rates: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Run the compliance module for a country (additive; unknown → empty list)."""
    fn = _COMPLIANCE_MODULES.get(str(country).strip().upper())
    if fn is None:
        return [
            {
                "rule": "no_compliance_module",
                "severity": "info",
                "message": (
                    f"No compliance module registered for country {country!r}. "
                    "AU is implemented; other countries are additive — wire a thin module "
                    "in xero_core._COMPLIANCE_MODULES when needed."
                ),
                "country": country,
            }
        ]
    return fn(policy, live_accounts, live_tax_rates)


def command_org_onboard(args: argparse.Namespace) -> int:
    """Orchestrate multi-org onboarding as a plan + scaffold (dry-run only).

    This command:
      (a) Adds the business to the profiles registry (``xero profiles add``).
      (b) Prints the exact ``xero auth login`` + ``xero snapshots fetch`` commands
          the human must run to complete auth + snapshot.
      (c) Scaffolds the profile-pack directory from the connector templates into
          the target path — company-profile.md stub, ap-policy.json, finance-rules.json
          skeleton, and evidence/inbox/ directory.
      (d) Reports which files were created vs skipped (idempotent: re-running
          does NOT clobber an existing filled pack).

    This command is IDEMPOTENT. Re-running it will scaffold only missing files.

    IMPORTANT: This command does NOT perform OAuth. After running this command,
    the human must:
      1. Run ``xero auth login`` (opens browser for Xero login + MFA + consent).
      2. Run ``xero tenants list --refresh`` and ``xero tenants use <tenant-id>``.
      3. Run the snapshot commands printed by this command.
      4. Fill in the scaffolded profile pack files with the org's real data.
    """
    key = args.key.strip()
    xero_profiles.validate_key(key)
    label = (args.label or key).strip()
    pack_path = Path(args.pack_path).expanduser().resolve()

    # Scaffold the pack FIRST, then write the registry entry. If a scaffold step
    # raises, we have not left a half-onboarded registry entry behind.
    # --- (c) Scaffold the pack directory ---
    templates_dir = MODULE_ROOT / "profile-pack" / "templates"
    finance_rules_template = MODULE_ROOT / "finance-rules" / "templates" / "default-rules.json"

    scaffolded: list[str] = []
    skipped: list[str] = []

    def _scaffold_file(dest: Path, template: Path | None = None, content: str | None = None) -> None:
        if dest.exists():
            skipped.append(str(dest))
            return
        dest.parent.mkdir(parents=True, exist_ok=True)
        if template and template.exists():
            dest.write_bytes(template.read_bytes())
        elif content:
            dest.write_text(content, encoding="utf-8")
        else:
            dest.write_text("{}\n", encoding="utf-8")
        scaffolded.append(str(dest))

    # company-profile.md stub
    company_profile_stub = (
        "---\n"
        f"# {label} — company profile\n"
        "# Fill in the fields below. This file is the human/agent compliance surface.\n"
        "# See connectors/xero/profile-pack/README.md for schema.\n"
        "country: AU\n"
        "entity_type: company  # company | sole_trader | partnership | trust\n"
        "business_type: saas   # saas | consulting | retail | ...\n"
        "size: small_business  # small_business | medium | large\n"
        "gst_basis: accruals   # accruals | cash\n"
        "bas_cycle: quarterly  # quarterly | monthly\n"
        "psi_posture: review   # review | psi | non_psi\n"
        "---\n"
        f"\n# {label}\n\n"
        "TODO: Complete this profile. Consult the accounting skill for guidance.\n"
    )
    _scaffold_file(pack_path / "company-profile.md", content=company_profile_stub)

    # ap-policy.json from the template
    _scaffold_file(
        pack_path / "ap-policy.json",
        template=templates_dir / "ap-policy.template.json",
    )

    # finance-rules.json skeleton
    _scaffold_file(pack_path / "finance-rules.json", template=finance_rules_template)

    # evidence/inbox/
    inbox = pack_path / "evidence" / "inbox"
    inbox.mkdir(parents=True, exist_ok=True)
    readme = inbox / "README.md"
    if not readme.exists():
        readme.write_text(
            "# Evidence inbox\n\n"
            "Drop source documents (PDF tax invoices, receipts) here.\n"
            "Run `xero evidence attach-batch --manifest <manifest.json>` to staple them.\n",
            encoding="utf-8",
        )
        scaffolded.append(str(readme))
    else:
        skipped.append(str(readme))

    # --- (a) Add to registry (after a successful scaffold) ---
    _registry, profile = xero_profiles.upsert_business(
        key=key,
        label=label,
        profile_pack=str(pack_path),
    )

    # --- (b) Print the commands the human must run ---
    human_steps = [
        f"xero --profile {key} auth login",
        f"xero --profile {key} tenants list --refresh",
        f"xero --profile {key} tenants use <paste-tenant-id-from-above>",
        f"xero --profile {key} snapshots fetch accounts",
        f"xero --profile {key} snapshots fetch contacts",
        f"xero --profile {key} snapshots fetch tax-rates",
        f"xero --profile {key} snapshots fetch items",
        f"xero --profile {key} snapshots fetch tracking-categories",
        f"xero --profile {key} org validate --pack-path {pack_path}",
    ]

    write_json(
        {
            "ok": True,
            "mode": "org-onboard",
            "key": key,
            "label": label,
            "pack_path": str(pack_path),
            "profile_paths": {f: str(p) for f, p in profile.paths.items()},
            "scaffolded": scaffolded,
            "skipped_existing": skipped,
            "idempotent": True,
            "human_steps_required": human_steps,
            "message": (
                "Registry updated and pack scaffolded. "
                "IMPORTANT: Run the human_steps_required commands above to complete onboarding. "
                "This command did NOT perform OAuth — the human must complete browser login."
            ),
        }
    )
    return 0


def command_org_validate(args: argparse.Namespace) -> int:
    """Validate a profile pack's account codes + tax types against live org snapshots.

    Reads the pack's finance-rules.json and ap-policy.json, then checks every
    account code and tax type referenced in the mappings against the org's live
    accounts and tax-rates snapshots (if present).  Unknown codes are reported.

    Also runs the per-country compliance module (AU: legal tax-type set + frozen
    period guard).

    Read-only. No mutation.
    """
    pack_path = Path(args.pack_path).expanduser().resolve()
    if not pack_path.is_dir():
        raise XeroCliError(f"pack-path does not exist or is not a directory: {pack_path}")

    # Load pack files.
    ap_policy_path = pack_path / "ap-policy.json"
    finance_rules_path = pack_path / "finance-rules.json"

    snapshot_warnings: list[str] = []

    policy: dict[str, Any] = {}
    if ap_policy_path.is_file():
        try:
            policy = xero_ap_policy.load_ap_policy(ap_policy_path)
        except xero_ap_policy.APPolicyError as exc:
            raise XeroCliError(f"ap-policy.json error: {exc}") from exc

    rules: dict[str, Any] = {}
    if finance_rules_path.is_file():
        rules = xero_finance_rules.load_rules(finance_rules_path)

    # A pack with no validatable content must not report a clean pass — there
    # was nothing to check. Treat it as a warning so the operator knows.
    if not ap_policy_path.is_file() and not finance_rules_path.is_file():
        snapshot_warnings.append(
            f"No ap-policy.json or finance-rules.json found in {pack_path}: nothing to validate. "
            "Run `xero org onboard` to scaffold the pack, then fill it in."
        )

    # Load snapshots (optional — warn if absent OR present-but-empty).
    snap_dir = xero_finance_rules.snapshot_dir(args.snapshots)
    accounts_snap = snap_dir / "accounts.json"
    tax_snap = snap_dir / "tax_rates.json"

    live_accounts: list[dict[str, Any]] = []
    live_tax_rates: list[dict[str, Any]] = []

    # Snapshots are written by command_snapshots_fetch as
    # {"schema_version":..., "records":[...]} — records live under "records".
    if accounts_snap.is_file():
        raw = xero_finance_rules.load_json_file(accounts_snap)
        live_accounts = raw.get("records") if isinstance(raw, dict) else []
        if not isinstance(live_accounts, list):
            live_accounts = []
        if not live_accounts:
            # Present but empty: account-code checks would silently pass. Warn
            # rather than report a vacuous clean pass.
            snapshot_warnings.append(
                f"Accounts snapshot {accounts_snap} has zero records: account-code validation "
                "was skipped. Re-run `xero snapshots fetch accounts`."
            )
    else:
        snapshot_warnings.append(
            f"Accounts snapshot not found: {accounts_snap}. "
            "Run `xero snapshots fetch accounts` to enable account-code validation."
        )

    if tax_snap.is_file():
        raw = xero_finance_rules.load_json_file(tax_snap)
        live_tax_rates = raw.get("records") if isinstance(raw, dict) else []
        if not isinstance(live_tax_rates, list):
            live_tax_rates = []
        if not live_tax_rates:
            snapshot_warnings.append(
                f"Tax-rates snapshot {tax_snap} has zero records: tax-type validation "
                "was skipped. Re-run `xero snapshots fetch tax-rates`."
            )
    else:
        snapshot_warnings.append(
            f"Tax-rates snapshot not found: {tax_snap}. "
            "Run `xero snapshots fetch tax-rates` to enable tax-type validation."
        )

    # Build sets of known codes from snapshots.
    known_account_codes: frozenset[str] = frozenset(
        str(a.get("Code") or "").strip() for a in live_accounts if a.get("Code")
    )
    known_tax_types: frozenset[str] = frozenset(
        str(tr.get("TaxType") or "").strip().upper()
        for tr in live_tax_rates
        if tr.get("TaxType")
    )

    # Collect all codes referenced in finance-rules mappings. Track how many
    # codes/tax-types were ACTUALLY checked (i.e. compared against a non-empty
    # known set) so a pack with empty mappings cannot report a vacuous pass.
    issues: list[dict[str, Any]] = []
    codes_checked = 0
    tax_types_checked = 0
    mappings = rules.get("mappings") if isinstance(rules.get("mappings"), dict) else {}
    for mapping_kind, entries in mappings.items():
        if not isinstance(entries, list):
            continue
        for entry in entries:
            target = entry.get("target") if isinstance(entry, dict) else None
            if not isinstance(target, dict):
                continue
            code = str(target.get("AccountCode") or "").strip()
            if code and known_account_codes:
                codes_checked += 1
                if code not in known_account_codes:
                    issues.append(
                        {
                            "rule": "unknown_account_code",
                            "severity": "error",
                            "message": f"Account code {code!r} in finance-rules ({mapping_kind} mapping) is not in the org's accounts snapshot.",
                            "code": code,
                            "mapping_kind": mapping_kind,
                        }
                    )
            tax = str(target.get("TaxType") or "").strip().upper()
            if tax and known_tax_types:
                tax_types_checked += 1
                if tax not in known_tax_types:
                    issues.append(
                        {
                            "rule": "unknown_tax_type",
                            "severity": "error",
                            "message": f"Tax type {tax!r} in finance-rules ({mapping_kind} mapping) is not in the org's tax-rates snapshot.",
                            "tax_type": tax,
                            "mapping_kind": mapping_kind,
                        }
                    )

    # Check ap-policy tax_defaults against known types.
    tax_defaults = policy.get("tax_defaults") if isinstance(policy.get("tax_defaults"), dict) else {}
    for tax_label, tax_code in tax_defaults.items():
        if str(tax_label).startswith("_"):
            continue  # `_note`/`_*` are comment keys, not tax codes
        code = str(tax_code or "").strip().upper()
        if code and known_tax_types:
            tax_types_checked += 1
            if code not in known_tax_types:
                issues.append(
                    {
                        "rule": "unknown_tax_type_in_policy",
                        "severity": "error",
                        "message": f"ap-policy tax_defaults[{tax_label!r}]={code!r} is not in the org's tax-rates snapshot.",
                        "tax_type": code,
                        "policy_key": tax_label,
                    }
                )

    # A present, filled pack with healthy snapshots can still check nothing if its
    # mappings/tax_defaults are empty (e.g. freshly scaffolded). Warn so this does
    # not read as a real clean pass.
    if codes_checked == 0 and tax_types_checked == 0:
        snapshot_warnings.append(
            f"No account codes or tax types were validated for pack {pack_path} "
            "(empty finance-rules mappings / ap-policy tax_defaults, or empty snapshots) — "
            "fill in the pack's mappings, then re-run."
        )

    # Run per-country compliance module.
    country = "AU"  # default; future: read from company-profile.md front-matter
    company_profile_path = pack_path / "company-profile.md"
    if company_profile_path.is_file():
        raw_text = company_profile_path.read_text(encoding="utf-8")
        for line in raw_text.splitlines():
            if line.startswith("country:"):
                country = line.split(":", 1)[1].strip().upper()
                break

    compliance_issues = _run_compliance_checks(country, policy, live_accounts, live_tax_rates)

    all_issues = issues + compliance_issues
    errors = [i for i in all_issues if i.get("severity") == "error"]
    warnings = [i for i in all_issues if i.get("severity") == "warning"]

    write_json(
        {
            "ok": not errors,
            "mode": "org-validate",
            "pack_path": str(pack_path),
            "country": country,
            "snapshot_dir": str(snap_dir),
            "snapshot_warnings": snapshot_warnings,
            "codes_checked": codes_checked,
            "tax_types_checked": tax_types_checked,
            "issue_count": len(all_issues),
            "error_count": len(errors),
            "warning_count": len(warnings),
            "issues": all_issues,
            "summary": (
                f"{len(errors)} error(s) found — fix before using this pack for mutations."
                if errors
                else (
                    "Pack validation passed BUT some checks were skipped (see snapshot_warnings) — "
                    "this is not a full clean pass."
                    if snapshot_warnings
                    else "Pack validation passed — no unknown codes or types detected."
                )
            ),
        }
    )
    return 0 if not errors else 1


# ---------------------------------------------------------------------------
# Phase 5 — Payroll skeleton (xero payroll prepare-payrun / verify)
# ---------------------------------------------------------------------------


def _check_payroll_scope_gate(args: argparse.Namespace) -> dict[str, Any] | None:
    """Return a scope-gate dict if payroll scopes are absent, else None.

    Reads the granted scopes from the token store (without refreshing) so we can
    give a clear diagnostic before attempting any payroll API call.
    """
    try:
        store = TokenStore(token_store_path(args.store))
        token_payload = store.load()
        granted_raw = str(token_payload.get("scope") or "")
    except (XeroCliError, OSError):
        granted_raw = ""

    check = xero_payroll.check_payroll_scopes(granted_raw)
    if not check["scopes_ok"]:
        return check
    return None


def _check_payroll_read_scope_gate(
    args: argparse.Namespace, need: "frozenset[str] | set[str]"
) -> dict[str, Any] | None:
    """Return a scope-gate dict if the required payroll READ scope(s) are absent.

    ``need`` is the per-command set of read scopes required (each satisfied by its
    read OR write variant). Per-command granularity avoids over-blocking (e.g.
    list-pay-runs needs only payroll.payruns.read, not employees) and under-blocking
    (get-payslip needs payroll.payslip.read, which a payruns-only token lacks).
    """
    try:
        store = TokenStore(token_store_path(args.store))
        token_payload = store.load()
        granted_raw = str(token_payload.get("scope") or "")
    except (XeroCliError, OSError):
        granted_raw = ""

    check = xero_payroll.check_payroll_read_scopes(granted_raw, required=need)
    if not check["scopes_ok"]:
        return check
    return None


def _payrun_date_where(from_date: str | None, to_date: str | None) -> str | None:
    """Build a Xero ``where`` clause filtering PayRun PaymentDate by a range.

    The AU Payroll GET /PayRuns endpoint has NO fromDate/toDate params; it only
    accepts ``where``.  We translate operator-friendly --from/--to into a
    ``where`` on PaymentDate using Xero's DateTime(YYYY,MM,DD) syntax.  NOTE:
    the AU Payroll spec does not explicitly document date-filter syntax for
    ``where``; if the org's payslips don't filter as expected, drop --from/--to
    and page through, or pass a raw --where clause.
    """
    clauses: list[str] = []
    for raw, op in ((from_date, ">="), (to_date, "<=")):
        if not raw:
            continue
        parts = raw.strip()[:10].split("-")
        if len(parts) != 3:
            raise XeroCliError(f"date {raw!r} must be YYYY-MM-DD")
        y, m, d = parts
        try:
            clauses.append(f"PaymentDate {op} DateTime({int(y)}, {int(m)}, {int(d)})")
        except ValueError as exc:
            raise XeroCliError(f"date {raw!r} must be YYYY-MM-DD") from exc
    if not clauses:
        return None
    return " && ".join(clauses)


def command_payroll_list_pay_runs(args: argparse.Namespace) -> int:
    """Read-only: list pay runs from the Xero AU Payroll API."""
    scope_check = _check_payroll_read_scope_gate(args, {"payroll.payruns.read"})
    if scope_check:
        write_json({"ok": False, "mode": "payroll-list-pay-runs", "scope_gate": scope_check})
        return 1
    payload, tenant_id = resolve_active_auth(args)
    # Prefer an explicit raw --where; otherwise build one from --from/--to.
    where = getattr(args, "where", None) or _payrun_date_where(
        getattr(args, "from_date", None), getattr(args, "to_date", None)
    )
    result = xero_payroll.read_pay_runs(
        payload,
        tenant_id,
        where=where,
        page=getattr(args, "page", None),
        order=getattr(args, "order", None),
    )
    write_json({"ok": True, "mode": "payroll-list-pay-runs", "tenant_id": tenant_id, "where": where, **result})
    return 0


def _timesheet_where(
    from_date: str | None,
    to_date: str | None,
    employee_id: str | None,
    status: str | None,
) -> str | None:
    """Build a Xero ``where`` clause for GET /Timesheets.

    ``--from`` filters ``StartDate >=`` and ``--to`` filters ``EndDate <=`` so a
    pay period fully inside the window is returned.  Optional ``EmployeeID`` and
    ``Status`` equality clauses are AND-ed in.  GET /Timesheets has no
    fromDate/toDate params — only ``where`` (verified against xero-payroll-au.yaml
    ``getTimesheets``, 2026-06-16).
    """
    clauses: list[str] = []
    for raw, field, op in ((from_date, "StartDate", ">="), (to_date, "EndDate", "<=")):
        if not raw:
            continue
        parts = raw.strip()[:10].split("-")
        if len(parts) != 3:
            raise XeroCliError(f"date {raw!r} must be YYYY-MM-DD")
        y, m, d = parts
        try:
            clauses.append(f"{field} {op} DateTime({int(y)}, {int(m)}, {int(d)})")
        except ValueError as exc:
            raise XeroCliError(f"date {raw!r} must be YYYY-MM-DD") from exc
    if employee_id:
        clauses.append(f'EmployeeID == Guid("{employee_id}")')
    if status:
        clauses.append(f'Status == "{status}"')
    if not clauses:
        return None
    return " && ".join(clauses)


def command_payroll_list_timesheets(args: argparse.Namespace) -> int:
    """Read-only: list timesheets from the Xero AU Payroll API (filterable).

    Unlike the upstream ``list-timesheets`` MCP tool (which sends no params and
    returns the oldest 100), this targets any pay period via a ``where`` clause
    and, when no filter is given, defaults ``order`` to ``StartDate DESC`` so the
    most recent timesheets come back first.
    """
    scope_check = _check_payroll_read_scope_gate(args, {"payroll.timesheets.read"})
    if scope_check:
        write_json({"ok": False, "mode": "payroll-list-timesheets", "scope_gate": scope_check})
        return 1
    payload, tenant_id = resolve_active_auth(args)
    # Prefer an explicit raw --where; otherwise build one from the filters.
    where = getattr(args, "where", None) or _timesheet_where(
        getattr(args, "from_date", None),
        getattr(args, "to_date", None),
        getattr(args, "employee_id", None),
        getattr(args, "status", None),
    )
    order = getattr(args, "order", None)
    # Without any filter, default to most-recent-first so page 1 isn't the oldest 100.
    if order is None and where is None:
        order = "StartDate DESC"
    result = xero_payroll.read_timesheets(
        payload,
        tenant_id,
        where=where,
        page=getattr(args, "page", None),
        order=order,
    )
    write_json(
        {
            "ok": True,
            "mode": "payroll-list-timesheets",
            "tenant_id": tenant_id,
            "where": where,
            "order": order,
            **result,
        }
    )
    return 0


def command_payroll_list_payslips(args: argparse.Namespace) -> int:
    """Read-only: list payslips for a pay run from the Xero AU Payroll API."""
    scope_check = _check_payroll_read_scope_gate(args, {"payroll.payruns.read"})
    if scope_check:
        write_json({"ok": False, "mode": "payroll-list-payslips", "scope_gate": scope_check})
        return 1
    payload, tenant_id = resolve_active_auth(args)
    result = xero_payroll.read_payslips(payload, tenant_id, args.pay_run_id)
    write_json({"ok": True, "mode": "payroll-list-payslips", "tenant_id": tenant_id, **result})
    return 0


def command_payroll_get_payslip(args: argparse.Namespace) -> int:
    """Read-only: fetch a single payslip from the Xero AU Payroll API."""
    scope_check = _check_payroll_read_scope_gate(args, {"payroll.payslip.read"})
    if scope_check:
        write_json({"ok": False, "mode": "payroll-get-payslip", "scope_gate": scope_check})
        return 1
    payload, tenant_id = resolve_active_auth(args)
    result = xero_payroll.read_payslip(payload, tenant_id, args.payslip_id)
    write_json({"ok": True, "mode": "payroll-get-payslip", "tenant_id": tenant_id, **result})
    return 0


def command_payroll_employee_pay_template(args: argparse.Namespace) -> int:
    """Read-only: fetch an employee's pay template from the Xero AU Payroll API."""
    scope_check = _check_payroll_read_scope_gate(args, {"payroll.employees.read"})
    if scope_check:
        write_json({"ok": False, "mode": "payroll-employee-pay-template", "scope_gate": scope_check})
        return 1
    payload, tenant_id = resolve_active_auth(args)
    result = xero_payroll.read_employee_pay_template(payload, tenant_id, args.employee_id)
    write_json({"ok": True, "mode": "payroll-employee-pay-template", "tenant_id": tenant_id, **result})
    return 0


def command_payroll_prepare_payrun(args: argparse.Namespace) -> int:
    """Dry-run: assemble and verify pay-run data (read-only skeleton).

    PLATFORM LIMITS — read before extending this command (§5 of design doc):

    This command is a READ-ONLY DRY-RUN SKELETON.  It computes:
      • SG contribution due cadence (quarterly vs per-payday from 2026-07-01).
      • SG accrual per employee from ordinary-time earnings.
      • A pay-run summary for human review.

    It does NOT:
      • Create a pay run in Xero (payroll scopes are not yet granted).
      • Lodge STP — a human must file the pay run in the Xero UI.
      • Execute or initiate super payments — UI-only, SMS-code authorisation,
        SuperChoice clearing house (4–7 business days).

    Sole-trader orgs (Arc Forge today): no SG obligation; this command is dormant
    until an employee exists.

    After reviewing the output, the human:
      1. Files the pay run in Xero UI (STP lodgment).
      2. Authorises the auto-super batch in Payroll → Superannuation (SMS code).
      3. Runs `xero payroll verify` to confirm payslip/SG data matches.
    """
    # Scope gate — payroll scopes not yet granted.
    scope_check = _check_payroll_scope_gate(args)
    if scope_check and not getattr(args, "ignore_scope_check", False):
        write_json(
            {
                "ok": False,
                "mode": "payroll-prepare-payrun",
                "scope_gate": scope_check,
                "message": (
                    "Payroll scopes are not granted. This command cannot call the Xero "
                    "Payroll API until the human re-consents with payroll scopes. "
                    "See scope_gate.consent_instructions above."
                ),
                "platform_limits": [
                    "STP lodgment: human must file in Xero UI.",
                    "Super payment: human must authorise in Xero UI (SMS code).",
                    "The API cannot execute super payments or auto-super batches.",
                ],
            }
        )
        return 1

    # Load employee pay-period data from --employees file.
    employees_raw = xero_finance_rules.load_json_file(
        Path(args.employees).expanduser().resolve()
    )
    if isinstance(employees_raw, dict) and isinstance(employees_raw.get("employees"), list):
        employees_raw = employees_raw["employees"]
    if not isinstance(employees_raw, list):
        raise XeroCliError(
            "--employees must be a JSON array or an object with an 'employees' array. "
            "Each entry needs employee_id, name, and ordinary_earnings."
        )

    pay_date = (args.pay_date or time.strftime("%Y-%m-%d", time.gmtime())).strip()
    sg_rate_raw = args.sg_rate
    if sg_rate_raw is None:
        sg_rate = xero_payroll.SG_RATE_DEFAULT
        rate_source = "default (VERIFY at ato.gov.au)"
    else:
        try:
            sg_rate = float(sg_rate_raw)
        except (TypeError, ValueError) as exc:
            raise XeroCliError(f"--sg-rate must be a decimal fraction (e.g. 0.12 for 12%), got {sg_rate_raw!r}") from exc
        rate_source = "operator-supplied"

    try:
        summary = xero_payroll.payrun_preflight_summary(
            pay_date=pay_date,
            employees=employees_raw,
            sg_rate=sg_rate,
        )
    except xero_payroll.PayrollError as exc:
        raise XeroCliError(str(exc)) from exc

    summary["sg_rate_source"] = rate_source
    summary["platform_limits"] = [
        "STP lodgment: human must file in Xero UI.",
        "Super payment: human must authorise in Xero UI with SMS code (SuperChoice clearing house, 4-7 business days).",
        "The API cannot execute super payments, auto-super batches, or STP lodgment.",
        "Sole-trader orgs (no employees) have no SG obligation.",
    ]
    summary["required_payroll_scopes"] = sorted(xero_payroll.REQUIRED_PAYROLL_SCOPES)
    summary["scope_grant_instructions"] = (
        "To enable full payroll API access, re-run `xero auth login` after adding "
        "payroll.employees, payroll.payruns, payroll.timesheets, payroll.settings "
        "to the OAuth app's allowed scopes. Human consent required in the browser."
    )

    if args.out:
        out_path = Path(args.out).expanduser().resolve()
        xero_finance_rules.write_json_file(out_path, summary)
        write_json(
            {
                "ok": True,
                "mode": "payroll-prepare-payrun",
                "report": str(out_path),
                "pay_date": pay_date,
                "employee_count": summary["employee_count"],
                "total_sg_accrual": summary["total_sg_accrual"],
            }
        )
    else:
        write_json(summary)
    return 0


def command_payroll_verify(args: argparse.Namespace) -> int:
    """Read-only: verify pay-run data against the recorded payslips/SG lines (skeleton).

    PLATFORM LIMITS:

    This command is a READ-ONLY SKELETON.  When payroll scopes are granted it
    will fetch payslip and superfund data via the AU Payroll API and check that
    SG accruals match the prepare-payrun summary.  Currently it reports the
    scope-gate and the human steps required.

    The tool verifies; it does NOT lodge STP or execute super payments.
    Both are human actions in the Xero UI.
    """
    scope_check = _check_payroll_scope_gate(args)

    write_json(
        {
            "ok": scope_check is None,
            "mode": "payroll-verify",
            "scope_gate": scope_check,
            "platform_limits": [
                "STP lodgment: human must file in Xero UI.",
                "Super payment: human must authorise in Xero UI (SMS code, SuperChoice, 4-7 business days).",
                "The API cannot execute super payments, auto-super batches, or STP lodgment.",
            ],
            "verify_steps": [
                "Review payslips in Xero UI: Payroll → Pay Runs → <pay run> → Payslips.",
                "Confirm SG amounts in Payroll → Superannuation.",
                "After super-batch authorisation, reconcile the bank movement via `xero reconcile`.",
                "Run `xero evidence audit` to confirm the bank-transaction attachment obligation.",
            ],
            "required_payroll_scopes": sorted(xero_payroll.REQUIRED_PAYROLL_SCOPES),
            "scope_grant_instructions": (
                "To enable payroll API reads, re-run `xero auth login` with payroll scopes. "
                "Human browser consent required."
            )
            if scope_check
            else None,
            "message": (
                "Payroll verify skeleton — payroll scopes not yet granted; see human steps above."
                if scope_check
                else "Payroll scopes are present. Full payroll-verify implementation pending Phase 5 completion."
            ),
        }
    )
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="xero", description="Arc Forge local Xero plugin CLI")
    parser.add_argument("--store", help="Override token store path")
    parser.add_argument(
        "-p",
        "--profile",
        help="Operate on a registered business (see `xero profiles`); defaults to XERO_PROFILE",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    profiles = sub.add_parser("profiles", help="Manage Xero business profiles (multi-business isolation)")
    profiles_sub = profiles.add_subparsers(dest="profiles_command", required=True)
    profiles_list = profiles_sub.add_parser("list", help="List registered businesses and their token-store state")
    profiles_list.set_defaults(func=command_profiles_list)
    profiles_show = profiles_sub.add_parser("show", help="Show resolved paths and token state for one business")
    profiles_show.set_defaults(func=command_profiles_show)
    profiles_add = profiles_sub.add_parser("add", help="Create or update a business entry in the registry")
    profiles_add.add_argument("--key", required=True, help="Short slug [a-z0-9-]; also the MCP tool-name prefix")
    profiles_add.add_argument("--label", help="Human-readable business name")
    profiles_add.add_argument("--legacy", action="store_true", help="Map this business to the existing legacy default paths")
    profiles_add.add_argument("--root", help="Override the directory holding this business's isolated state")
    profiles_add.add_argument("--profile-pack", help="Path to this org's profile pack (company-profile.md + ap-policy.json + finance-rules.json) in the private finances repo")
    profiles_add.set_defaults(func=command_profiles_add)
    profiles_remove = profiles_sub.add_parser("remove", help="Remove a business entry (leaves its token files on disk)")
    profiles_remove.add_argument("--key", required=True, help="Business slug to remove")
    profiles_remove.set_defaults(func=command_profiles_remove)
    profiles_pin = profiles_sub.add_parser("pin-tenant", help="Pin the business's expected Xero tenant for identity assertions")
    profiles_pin.add_argument("--tenant-id", help="Tenant id to pin; defaults to the store's current active tenant")
    profiles_pin.set_defaults(func=command_profiles_pin_tenant)

    doctor = sub.add_parser("doctor", help="Check local Xero plugin readiness without calling Xero")
    doctor.add_argument("--client-id", help="Xero OAuth public client id override for readiness checks")
    doctor.add_argument("--rate-store", help="Override rate-limit status store path")
    doctor.add_argument("--rules", help="Override finance-rules path")
    doctor.add_argument("--strict", action="store_true", help="Exit non-zero unless base install and auth state are ready")
    doctor.set_defaults(func=command_doctor)

    auth = sub.add_parser("auth", help="Authenticate and inspect local Xero auth state")
    auth_sub = auth.add_subparsers(dest="auth_command", required=True)
    app_config = auth_sub.add_parser("app-config", help="Print Arc Forge Xero OAuth app setup requirements")
    app_config.add_argument("--client-id", help="Arc Forge Xero OAuth public client id")
    app_config.add_argument("--scope", help="OAuth scope override")
    app_config.add_argument("--port", type=int, default=DEFAULT_CALLBACK_PORT, help="Preferred localhost callback port")
    app_config.add_argument("--strict", action="store_true", help="Exit non-zero unless a public client id is configured")
    app_config.set_defaults(func=command_auth_app_config)

    configure_app = auth_sub.add_parser("configure-app", help="Write the public Xero OAuth app client id to local config")
    configure_app.add_argument("--client-id", required=True, help="Arc Forge Xero OAuth public client id")
    configure_app.add_argument("--path", help="Override public OAuth app config path")
    configure_app.add_argument("--port", type=int, default=DEFAULT_CALLBACK_PORT, help="Localhost callback port encoded in the config")
    configure_app.set_defaults(func=command_auth_configure_app)

    login = auth_sub.add_parser("login", help="Start Xero OAuth PKCE login")
    login.add_argument("--client-id", help="Arc Forge Xero OAuth public client id")
    login.add_argument("--scope", help="OAuth scope override (escape hatch; whitespace-normalised and validated)")
    login.add_argument(
        "--add",
        help=(
            "Comma-separated named scope bundle(s) to UNION onto the currently-granted scopes, "
            "then re-consent. Bundles: " + ", ".join(sorted(SCOPE_BUNDLES)) + ". "
            "Ignored if --scope is given."
        ),
    )
    login.add_argument("--port", type=int, default=DEFAULT_CALLBACK_PORT, help="Preferred localhost callback port")
    login.add_argument("--timeout", type=int, default=300, help="Callback timeout in seconds")
    login.add_argument("--print-url", action="store_true", help="Print authorize URL instead of opening browser")
    login.set_defaults(func=command_auth_login)

    status = auth_sub.add_parser("status", help="Show local auth status")
    status.add_argument("--verbose", action="store_true", help="Include redacted stored payload")
    status.set_defaults(func=command_auth_status)

    refresh = auth_sub.add_parser("refresh", help="Refresh access token and persist rotated refresh token")
    refresh.add_argument("--client-id", help="Arc Forge Xero OAuth public client id")
    refresh.set_defaults(func=command_auth_refresh)

    migrate_store = auth_sub.add_parser("migrate-store", help="Rewrite the local token store using the configured storage mode")
    migrate_store.set_defaults(func=command_auth_migrate_store)

    token = auth_sub.add_parser("token", help="Emit a fresh bearer token for trusted local MCP wrapper processes")
    token.add_argument("--tenant-id", help="Override active tenant id")
    token.set_defaults(func=command_auth_token)

    tenants = sub.add_parser("tenants", help="List and select Xero tenants")
    tenants_sub = tenants.add_subparsers(dest="tenants_command", required=True)
    tenants_list = tenants_sub.add_parser("list", help="List connected tenants")
    tenants_list.add_argument("--refresh", action="store_true", help="Refresh access token and fetch live connections")
    tenants_list.set_defaults(func=command_tenants_list)
    tenants_use = tenants_sub.add_parser("use", help="Set active tenant")
    tenants_use.add_argument("tenant_id")
    tenants_use.set_defaults(func=command_tenants_use)

    smoke = sub.add_parser("smoke", help="Read-only Xero smoke checks")
    smoke_sub = smoke.add_subparsers(dest="smoke_command", required=True)
    organisation = smoke_sub.add_parser("organisation", help="Read organisation details")
    organisation.add_argument("--tenant-id", help="Override active tenant id")
    organisation.set_defaults(func=command_smoke_organisation)
    accounts = smoke_sub.add_parser("accounts", help="Read a capped chart-of-accounts sample")
    accounts.add_argument("--tenant-id", help="Override active tenant id")
    accounts.add_argument("--limit", type=int, default=10, help="Maximum accounts to include in output")
    accounts.set_defaults(func=command_smoke_accounts)

    rate = sub.add_parser("rate", help="Inspect local Xero rate-limit governor state")
    rate_sub = rate.add_subparsers(dest="rate_command", required=True)
    rate_status = rate_sub.add_parser("status", help="Show last governor snapshot")
    rate_status.add_argument("--rate-store", help="Override rate-limit status store path")
    rate_status.add_argument("--include-cli", action="store_true", help="Include direct CLI Accounting API rate-governor state")
    rate_status.add_argument("--cli-rate-store", help="Override direct CLI rate-limit status store path")
    rate_status.add_argument("--shared-rate-store", help="Override shared MCP/CLI rate-budget store path")
    rate_status.set_defaults(func=command_rate_status)
    rate_unblock = rate_sub.add_parser("unblock-day-limit", help="Explicitly unblock the local day-limit circuit breaker for one UTC day")
    rate_unblock.add_argument("--holder", required=True, help="Operator or workflow making the override")
    rate_unblock.add_argument("--reason", required=True, help="Reason for the explicit override")
    rate_unblock.add_argument("--day-key", help="UTC day key to unblock, defaults to today in YYYY-MM-DD")
    rate_unblock.add_argument("--unblock-store", help="Override day-limit unblock store path")
    rate_unblock.set_defaults(func=command_rate_unblock_day_limit)

    reports = sub.add_parser("reports", help="Fetch read-only Xero reports")
    reports_sub = reports.add_subparsers(dest="reports_command", required=True)
    reports_get = reports_sub.add_parser("get", help="Fetch a supported Xero Accounting API report")
    reports_get.add_argument("kind", help="Report kind")
    reports_get.add_argument("--tenant-id", help="Override active tenant id")
    reports_get.add_argument("--date", help="Report date, where supported")
    reports_get.add_argument("--from-date", help="Report start date, where supported")
    reports_get.add_argument("--to-date", help="Report end date, where supported")
    reports_get.add_argument("--periods", type=int, help="Number of periods, where supported")
    reports_get.add_argument("--timeframe", help="Report timeframe, where supported")
    reports_get.add_argument("--standard-layout", action="store_true", help="Request standard layout where supported")
    reports_get.add_argument("--payments-only", action="store_true", help="Request cash/payments-only basis where supported")
    reports_get.add_argument("--contact-id", help="Contact ID for aged reports")
    reports_get.add_argument(
        "--tracking-category-id",
        help="P&L only: split columns by this tracking category (returns one column per option)",
    )
    reports_get.add_argument(
        "--tracking-option-id",
        help="P&L only: filter to a single tracking option within --tracking-category-id",
    )
    reports_get.add_argument(
        "--tracking-category-id2",
        help="P&L only: second tracking-category dimension (Xero trackingCategoryID2)",
    )
    reports_get.add_argument(
        "--tracking-option-id2",
        help="P&L only: filter to a single option within --tracking-category-id2",
    )
    reports_get.set_defaults(func=command_reports_get)

    reports_export = reports_sub.add_parser(
        "export-pnl-tracking",
        help="Write a normalized P&L-by-tracking-category CSV (one row per account/option) with reconciliation",
    )
    reports_export.add_argument("--tenant-id", help="Override active tenant id")
    reports_export.add_argument("--from-date", required=True, help="Period start (YYYY-MM-DD)")
    reports_export.add_argument("--to-date", required=True, help="Period end (YYYY-MM-DD)")
    reports_export.add_argument(
        "--tracking-category-id", required=True, help="Tracking category UUID to split columns by"
    )
    reports_export.add_argument(
        "--tracking-option-id", help="Optional: restrict to a single tracking option within the category"
    )
    reports_export.add_argument("--out", required=True, help="Output CSV path")
    reports_export.add_argument(
        "--segment-map",
        help='Optional JSON object renaming tracking options, e.g. {"Woodside":"Woodside Surgery"}',
    )
    reports_export.add_argument(
        "--untracked-label",
        default="Unassigned",
        help="Label for the untracked/Unassigned column (default: Unassigned)",
    )
    reports_export.add_argument(
        "--source-report",
        default="Xero ProfitAndLoss (tracking)",
        help="Value written to the source_report column",
    )
    reports_export.add_argument("--note", help="Value written to the notes column")
    reports_export.add_argument("--exported-at", help="exported_at value (default: today, UTC)")
    reports_export.add_argument(
        "--include-zero", action="store_true", help="Emit rows for zero-amount account/option cells"
    )
    reports_export.add_argument(
        "--reconcile-tolerance",
        type=float,
        default=0.02,
        help="Max allowed |net_computed - net_reported| per segment before the export fails (default: 0.02)",
    )
    reports_export.add_argument(
        "--allow-reconcile-mismatch",
        action="store_true",
        help="Write the file even when a segment net breaches the reconcile tolerance",
    )
    reports_export.set_defaults(func=command_reports_export_pnl_tracking)

    budgets = sub.add_parser("budgets", help="Fetch read-only Xero budgets (Budget Manager)")
    budgets_sub = budgets.add_subparsers(dest="budgets_command", required=True)
    budgets_list = budgets_sub.add_parser(
        "list", help="List budgets (BudgetID, Type, Description, UpdatedDateUTC)"
    )
    budgets_list.add_argument("--tenant-id", help="Override active tenant id")
    budgets_list.add_argument("--ids", help="Comma-separated BudgetIDs to filter the list")
    budgets_list.set_defaults(func=command_budgets_list)
    budgets_get = budgets_sub.add_parser(
        "get", help="Fetch one budget with its per-account, per-period budget lines"
    )
    budgets_get.add_argument("budget_id", help="BudgetID UUID")
    budgets_get.add_argument("--tenant-id", help="Override active tenant id")
    budgets_get.add_argument("--date-from", help="Period start (YYYY-MM-DD)")
    budgets_get.add_argument("--date-to", help="Period end (YYYY-MM-DD)")
    budgets_get.set_defaults(func=command_budgets_get)

    journals = sub.add_parser("journals", help="Export general-ledger journals as account transactions")
    journals_sub = journals.add_subparsers(dest="journals_command", required=True)
    journals_export = journals_sub.add_parser(
        "export",
        help="Write normalized account-transaction rows from /Journals (revenue +, costs −)",
    )
    journals_export.add_argument("--tenant-id", help="Override active tenant id")
    journals_export.add_argument("--from-date", required=True, help="Period start (YYYY-MM-DD)")
    journals_export.add_argument("--to-date", required=True, help="Period end (YYYY-MM-DD)")
    journals_export.add_argument("--out", required=True, help="Output CSV path")
    journals_export.add_argument(
        "--tracking-category-id", help="Tracking category UUID whose option becomes tracking_category"
    )
    journals_export.add_argument(
        "--account-id", action="append", help="Restrict to these account UUIDs (repeatable)"
    )
    journals_export.add_argument(
        "--segment-map",
        help='Optional JSON object renaming tracking options, e.g. {"Woodside":"Woodside Surgery"}',
    )
    journals_export.add_argument(
        "--untracked-label",
        default="Unassigned",
        help="Label for journal lines with no matching tracking option (default: Unassigned)",
    )
    journals_export.add_argument(
        "--source-report",
        default="Xero Journals (general ledger)",
        help="Value written to the source_report column",
    )
    journals_export.add_argument("--note", help="Value written to the notes column")
    journals_export.add_argument("--exported-at", help="exported_at value (default: today, UTC)")
    journals_export.add_argument(
        "--all-accounts",
        action="store_true",
        help="Include balance-sheet accounts too (default: Profit & Loss accounts only)",
    )
    journals_export.set_defaults(func=command_journals_export)

    payments = sub.add_parser("payments", help="Export invoice/bill payments (cash in/out) as account-transaction timing rows")
    payments_sub = payments.add_subparsers(dest="payments_command", required=True)
    payments_export = payments_sub.add_parser(
        "export",
        help="Write normalized payment rows from /Payments (amount positive; ACCREC = cash in, ACCPAY = cash out)",
    )
    payments_export.add_argument("--tenant-id", help="Override active tenant id")
    payments_export.add_argument("--from-date", help="Optional period start (YYYY-MM-DD); omit for all payments")
    payments_export.add_argument("--to-date", help="Optional period end (YYYY-MM-DD); omit for all payments")
    payments_export.add_argument("--out", required=True, help="Output CSV path")
    payments_export.add_argument(
        "--source-report",
        default="Xero payments export",
        help="Value written to the source_report column",
    )
    payments_export.add_argument("--note", help="Value written to the notes column")
    payments_export.add_argument("--exported-at", help="exported_at value (default: today, UTC)")
    payments_export.add_argument(
        "--include-deleted",
        action="store_true",
        help="Include DELETED payments (default: AUTHORISED/live payments only)",
    )
    payments_export.set_defaults(func=command_payments_export)

    banktx = sub.add_parser("banktransactions", help="Export actual bank cash movements (Spend/Receive Money) by category")
    banktx_sub = banktx.add_subparsers(dest="banktransactions_command", required=True)
    banktx_export = banktx_sub.add_parser(
        "export",
        help="Write actual cash in/out from /BankTransactions, one row per line item (direction in/out, account = cash category)",
    )
    banktx_export.add_argument("--tenant-id", help="Override active tenant id")
    banktx_export.add_argument("--from-date", help="Optional period start (YYYY-MM-DD)")
    banktx_export.add_argument("--to-date", help="Optional period end (YYYY-MM-DD)")
    banktx_export.add_argument("--out", required=True, help="Output CSV path")
    banktx_export.add_argument("--note", help="Value written to the notes column")
    banktx_export.add_argument("--exported-at", help="exported_at value (default: today, UTC)")
    banktx_export.set_defaults(func=command_banktransactions_export)

    for _noun, _help, _func, _number_help in (
        (
            "receivables",
            "Export outstanding receivables (aged, built from /Invoices ACCREC)",
            command_aged_receivables_export,
            "invoice",
        ),
        (
            "payables",
            "Export outstanding payables (aged, built from /Invoices ACCPAY)",
            command_aged_payables_export,
            "bill",
        ),
    ):
        _parser = sub.add_parser(_noun, help=_help)
        _parser_sub = _parser.add_subparsers(dest=f"{_noun}_command", required=True)
        _export = _parser_sub.add_parser(
            "export",
            help=f"Write aged {_noun} rows (full amount in the matching aged bucket)",
        )
        _export.add_argument("--tenant-id", help="Override active tenant id")
        _export.add_argument("--out", required=True, help="Output CSV path")
        _export.add_argument("--as-at-date", help="Aging reference date YYYY-MM-DD (default: today)")
        _export.add_argument("--source-report", help="Value written to the source_report column")
        _export.add_argument("--note", help="Value written to the notes column")
        _export.add_argument("--exported-at", help="exported_at value (default: today, UTC)")
        _export.set_defaults(func=_func)

    evidence = sub.add_parser("evidence", help="Manage Xero history notes and attachments for supported records")
    evidence_sub = evidence.add_subparsers(dest="evidence_command", required=True)
    evidence_history = evidence_sub.add_parser("history", help="Read or add Xero history notes")
    evidence_history_sub = evidence_history.add_subparsers(dest="evidence_history_command", required=True)
    history_get = evidence_history_sub.add_parser("get", help="Get history records for a supported Xero object")
    history_get.add_argument("kind", choices=sorted(EVIDENCE_OBJECT_KINDS))
    history_get.add_argument("object_id")
    history_get.add_argument("--tenant-id", help="Override active tenant id")
    history_get.set_defaults(func=command_evidence_history_get)
    history_note = evidence_history_sub.add_parser("add-note", help="Add a history note to a supported Xero object")
    history_note.add_argument("kind", choices=sorted(EVIDENCE_OBJECT_KINDS))
    history_note.add_argument("object_id")
    history_note.add_argument("--details", required=True, help="Note details to add to Xero history")
    history_note.add_argument("--tenant-id", help="Override active tenant id")
    history_note.set_defaults(func=command_evidence_history_add_note)

    evidence_attachments = evidence_sub.add_parser("attachments", help="List, upload, or download Xero attachments")
    evidence_attachments_sub = evidence_attachments.add_subparsers(dest="evidence_attachments_command", required=True)
    attachments_list = evidence_attachments_sub.add_parser("list", help="List attachments for a supported Xero object")
    attachments_list.add_argument("kind", choices=sorted(EVIDENCE_OBJECT_KINDS))
    attachments_list.add_argument("object_id")
    attachments_list.add_argument("--tenant-id", help="Override active tenant id")
    attachments_list.set_defaults(func=command_evidence_attachments_list)
    attachments_upload = evidence_attachments_sub.add_parser("upload", help="Upload an attachment to a supported Xero object")
    attachments_upload.add_argument("kind", choices=sorted(EVIDENCE_OBJECT_KINDS))
    attachments_upload.add_argument("object_id")
    attachments_upload.add_argument("--file", required=True, help="Local file to upload")
    attachments_upload.add_argument("--filename", help="Attachment filename in Xero; defaults to local basename")
    attachments_upload.add_argument("--content-type", help="MIME type override")
    attachments_upload.add_argument("--tenant-id", help="Override active tenant id")
    attachments_upload.set_defaults(func=command_evidence_attachments_upload)
    attachments_download = evidence_attachments_sub.add_parser("download", help="Download an attachment from a supported Xero object")
    attachments_download.add_argument("kind", choices=sorted(EVIDENCE_OBJECT_KINDS))
    attachments_download.add_argument("object_id")
    attachments_download.add_argument("filename")
    attachments_download.add_argument("--out", required=True, help="Local output path")
    attachments_download.add_argument("--tenant-id", help="Override active tenant id")
    attachments_download.set_defaults(func=command_evidence_attachments_download)

    evidence_audit = evidence_sub.add_parser("audit", help="Read-only sweep: which records lack a stapled source document")
    evidence_audit.add_argument("--kinds", nargs="+", choices=sorted(EVIDENCE_AUDIT_KINDS), help="Object kinds to scan (default: bill bank-transaction)")
    evidence_audit.add_argument("--frozen-before", help="ISO date override; records before it are flagged frozen. Falls back to Xero lock date (snapshot/live), then ap-policy.frozen_before.")
    evidence_audit.add_argument("--ap-policy", help="Path to ap-policy.json; its frozen_before is the final fallback when no Xero lock date is set")
    evidence_audit.add_argument("--snapshots", help="Override snapshot directory (for organisation snapshot used to resolve Xero lock date)")
    evidence_audit.add_argument("--tenant-id", help="Override active tenant id")
    evidence_audit.add_argument("--out", help="Write the compliance report to a JSON file")
    evidence_audit.set_defaults(func=command_evidence_audit)

    evidence_attach_batch = evidence_sub.add_parser("attach-batch", help="Backfill source documents onto records from a manifest (dry-run unless --apply)")
    evidence_attach_batch.add_argument("--manifest", required=True, help="JSON manifest: [{file, kind, object_id|match:{date,amount,contact}, note?}]")
    evidence_attach_batch.add_argument("--apply", action="store_true", help="Upload + history-note under the operation lock; omitted means validate-only")
    evidence_attach_batch.add_argument("--skip-missing-files", action="store_true", help="Skip manifest entries whose file isn't present yet (backfill incrementally as documents arrive)")
    evidence_attach_batch.add_argument("--tenant-id", help="Override active tenant id")
    evidence_attach_batch.add_argument("--audit-dir", help="Override local audit directory for apply reports")
    evidence_attach_batch.add_argument("--actor", default="local-cli", help="Actor label for apply reports")
    evidence_attach_batch.set_defaults(func=command_evidence_attach_batch)

    documents = sub.add_parser("documents", help="Dry-run or create core Xero accounting documents")
    documents_sub = documents.add_subparsers(dest="documents_command", required=True)
    documents_create = documents_sub.add_parser("create", help="Dry-run or create an allowlisted invoice, bill, quote, or credit note")
    documents_create.add_argument("kind", choices=sorted(DOCUMENT_KINDS))
    documents_create.add_argument("--payload", required=True, help="JSON object, array, or wrapped Xero request payload")
    documents_create.add_argument("--apply", action="store_true", help="Actually send the request to Xero")
    documents_create.add_argument("--preflight-report", help="Dry-run or audit report proving preflight checks before --apply")
    documents_create.add_argument("--confirm-apply-without-preflight", action="store_true", help="Explicit operator override for --apply without a preflight report")
    documents_create.add_argument("--tenant-id", help="Override active tenant id")
    documents_create.add_argument("--audit-dir", help="Override local audit directory for apply reports")
    documents_create.add_argument("--actor", default="local-cli", help="Actor label for apply report")
    documents_create.add_argument("--out", help="Write dry-run report to JSON file")
    documents_create.add_argument(
        "--summarize-errors",
        action=argparse.BooleanOptionalAction,
        default=False,
        help="Use Xero's summarized validation errors; default false for batch diagnostics",
    )
    documents_create.set_defaults(func=command_documents_create)

    documents_update = documents_sub.add_parser("update", help="Dry-run or update an allowlisted invoice, bill, quote, or credit note")
    documents_update.add_argument("kind", choices=sorted(DOCUMENT_KINDS))
    documents_update.add_argument("--identifier", help="Document identifier; required for --status updates and used in invoice/bill update URL")
    documents_update.add_argument("--payload", help="JSON object, array, or wrapped Xero update payload")
    documents_update.add_argument("--status", help="Status update to apply, e.g. AUTHORISED, VOIDED, DELETED")
    documents_update.add_argument("--apply", action="store_true", help="Actually send the update request to Xero")
    documents_update.add_argument("--preflight-report", help="Dry-run or audit report proving preflight checks before --apply")
    documents_update.add_argument("--confirm-apply-without-preflight", action="store_true", help="Explicit operator override for --apply without a preflight report")
    documents_update.add_argument("--tenant-id", help="Override active tenant id")
    documents_update.add_argument("--audit-dir", help="Override local audit directory for apply reports")
    documents_update.add_argument("--actor", default="local-cli", help="Actor label for apply report")
    documents_update.add_argument("--out", help="Write dry-run report to JSON file")
    documents_update.add_argument("--rules", help="Finance-rules file (for the attach_before_authorise convention)")
    documents_update.add_argument("--confirm-without-evidence", action="store_true", help="Override the attach-before-authorise gate (recorded in the apply ledger)")
    documents_update.add_argument(
        "--summarize-errors",
        action=argparse.BooleanOptionalAction,
        default=False,
        help="Use Xero's summarized validation errors; default false for batch diagnostics",
    )
    documents_update.set_defaults(func=command_documents_update)
    documents_action = documents_sub.add_parser("action", help="Dry-run or run a specialized invoice action such as email or online-url")
    documents_action.add_argument("kind", choices=["invoice"])
    documents_action.add_argument("action", choices=sorted(DOCUMENT_ACTIONS))
    documents_action.add_argument("--identifier", required=True, help="InvoiceID or invoice number for the action endpoint")
    documents_action.add_argument("--apply", action="store_true", help="Actually run the invoice action in Xero")
    documents_action.add_argument("--preflight-report", help="Dry-run or audit report proving preflight checks before --apply")
    documents_action.add_argument("--confirm-apply-without-preflight", action="store_true", help="Explicit operator override for --apply without a preflight report")
    documents_action.add_argument("--tenant-id", help="Override active tenant id")
    documents_action.add_argument("--audit-dir", help="Override local audit directory for apply reports")
    documents_action.add_argument("--actor", default="local-cli", help="Actor label for apply report")
    documents_action.add_argument("--out", help="Write dry-run report to JSON file")
    documents_action.set_defaults(func=command_documents_action)

    ap = sub.add_parser("ap", help="Accounts-payable bill lifecycle (profile-pack-driven)")
    ap_sub = ap.add_subparsers(dest="ap_command", required=True)
    ap_draft = ap_sub.add_parser("draft-bill", help="Draft an ACCPAY bill with pack-derived due date + approval routing")
    ap_draft.add_argument("--ap-policy", required=True, help="Path to the org's ap-policy.json (profile pack)")
    ap_draft.add_argument("--contact-id", required=True, help="Supplier ContactID (or exact contact Name)")
    ap_draft.add_argument("--supplier", help="Supplier name for per-supplier term lookup (defaults to none → org default terms)")
    ap_draft.add_argument("--bill-date", help="Bill date YYYY-MM-DD (default: today UTC)")
    ap_draft.add_argument("--reference", help="Bill reference")
    ap_draft.add_argument("--line", action="append", help="Line item ACCOUNT:TAX:AMOUNT[:DESCRIPTION] (repeatable)")
    ap_draft.add_argument("--line-amount-types", default="Exclusive", choices=["Exclusive", "Inclusive", "NoTax"], help="How LineAmount is interpreted (default Exclusive)")
    ap_draft.add_argument("--confirm-frozen-period", action="store_true", help="Allow a bill dated in a BAS-lodged frozen period (agent sign-off only)")
    ap_draft.add_argument("--apply", action="store_true", help="Create the DRAFT bill in Xero (requires a preflight report)")
    ap_draft.add_argument("--preflight-report", help="Dry-run or audit report proving preflight checks before --apply")
    ap_draft.add_argument("--confirm-apply-without-preflight", action="store_true", help="Explicit operator override for --apply without a preflight report")
    ap_draft.add_argument("--tenant-id", help="Override active tenant id")
    ap_draft.add_argument("--audit-dir", help="Override local audit directory for apply reports")
    ap_draft.add_argument("--actor", default="local-cli", help="Actor label for apply report")
    ap_draft.add_argument("--out", help="Write dry-run report to JSON file")
    ap_draft.add_argument("--snapshots", help="Override snapshot directory (for org + contacts snapshots used to resolve terms/lock date)")
    ap_draft.set_defaults(func=command_ap_draft_bill)

    # Phase 3 — ap ingest-sidecar
    ap_ingest = ap_sub.add_parser(
        "ingest-sidecar",
        help="Parse a structured sidecar (JSON or key:value text) into a normalised bill candidate (pure, no network)",
    )
    ap_ingest.add_argument("sidecar", help="Path to the sidecar file (JSON or key:value text)")
    ap_ingest.add_argument(
        "--source-file",
        help="Path to the accompanying source document (PDF, receipt); embedded in the candidate as _source_file",
    )
    ap_ingest.add_argument("--out", help="Write the candidate to a JSON file")
    ap_ingest.set_defaults(func=command_ap_ingest_sidecar)

    # Phase 3 — ap batch-pay
    ap_batch_pay = ap_sub.add_parser(
        "batch-pay",
        help=(
            "Record a batch payment against reviewed ACCPAY bills (one bank movement ↔ one BatchPayment). "
            "HONESTY: records payments; does NOT move money or emit an ABA file. Dry-run by default."
        ),
    )
    ap_batch_pay.add_argument(
        "--payments",
        required=True,
        help=(
            "JSON array (or object with 'payments' array) of bill-payment specs. "
            "Each entry: {invoice_id: <UUID>, amount: <number>}."
        ),
    )
    ap_batch_pay.add_argument(
        "--bank-account-id",
        required=True,
        help="Xero AccountID UUID of the bank account the payment is drawn from",
    )
    ap_batch_pay.add_argument("--payment-date", help="Payment date YYYY-MM-DD (default: today UTC)")
    ap_batch_pay.add_argument("--reference", help="Batch payment reference / narration")
    ap_batch_pay.add_argument(
        "--apply",
        action="store_true",
        help=(
            "Record the batch payment in Xero under the operation lock. "
            "Requires --preflight-report. Ensure the real bank transfer has been authorised first."
        ),
    )
    ap_batch_pay.add_argument("--preflight-report", help="Dry-run report proving preflight checks before --apply")
    ap_batch_pay.add_argument(
        "--confirm-apply-without-preflight",
        action="store_true",
        help="Explicit operator override for --apply without a preflight report",
    )
    ap_batch_pay.add_argument("--tenant-id", help="Override active tenant id")
    ap_batch_pay.add_argument("--audit-dir", help="Override local audit directory for apply reports")
    ap_batch_pay.add_argument("--actor", default="local-cli", help="Actor label for apply report")
    ap_batch_pay.add_argument("--out", help="Write the dry-run report to a JSON file (use as --preflight-report for --apply)")
    ap_batch_pay.set_defaults(func=command_ap_batch_pay)

    # Phase 3 — ap check-unmatched-payments
    ap_unmatched = ap_sub.add_parser(
        "check-unmatched-payments",
        help=(
            f"Read-only alert: recorded ACCPAY payments with no matching statement line "
            f"within --alert-days days (default {_BATCH_PAY_UNMATCHED_ALERT_DAYS}). No mutation."
        ),
    )
    ap_unmatched.add_argument(
        "--alert-days",
        type=int,
        default=_BATCH_PAY_UNMATCHED_ALERT_DAYS,
        help="Flag recorded payments older than this many days (default %(default)s)",
    )
    ap_unmatched.add_argument("--tenant-id", help="Override active tenant id")
    ap_unmatched.set_defaults(func=command_ap_check_unmatched_payments)

    # Phase 4 — org onboard + validate
    org = sub.add_parser("org", help="Multi-org onboarding and profile-pack validation")
    org_sub = org.add_subparsers(dest="org_command", required=True)

    org_onboard = org_sub.add_parser(
        "onboard",
        help=(
            "Orchestrate multi-org onboarding: register the business, scaffold the profile pack, "
            "and print the auth + snapshot commands the human must run. Idempotent."
        ),
    )
    org_onboard.add_argument("--key", required=True, help="Business slug [a-z0-9-] for the registry and MCP prefix")
    org_onboard.add_argument("--label", help="Human-readable business name")
    org_onboard.add_argument(
        "--pack-path",
        required=True,
        help=(
            "Target directory for the profile pack (company-profile.md, ap-policy.json, finance-rules.json, evidence/). "
            "In the private finances repo, e.g. ~/repos/arc-forge-finances/accounting/orgs/<key>/"
        ),
    )
    org_onboard.set_defaults(func=command_org_onboard)

    org_validate = org_sub.add_parser(
        "validate",
        help=(
            "Validate a profile pack's account codes + tax types against live org snapshots, "
            "and run the per-country compliance module (AU: legal tax-type set + frozen-period guard). "
            "Read-only."
        ),
    )
    org_validate.add_argument(
        "--pack-path",
        required=True,
        help="Path to the profile-pack directory (must contain finance-rules.json and/or ap-policy.json)",
    )
    org_validate.add_argument("--snapshots", help="Override snapshot directory (default: per-profile XERO_SNAPSHOT_DIR)")
    org_validate.set_defaults(func=command_org_validate)

    # Phase 5 — payroll prepare-payrun + verify (skeleton)
    payroll = sub.add_parser(
        "payroll",
        help=(
            "Payroll/super prepare+verify skeleton. "
            "PLATFORM LIMITS: STP lodgment and super payment execution are UI-only human actions. "
            "The API cannot execute super payments or auto-super batches."
        ),
    )
    payroll_sub = payroll.add_subparsers(dest="payroll_command", required=True)

    payroll_prepare = payroll_sub.add_parser(
        "prepare-payrun",
        help=(
            "Dry-run: compute SG cadence, per-employee SG accruals, and a pay-run summary. "
            "Does NOT create a pay run or lodge STP. Read-only."
        ),
    )
    payroll_prepare.add_argument(
        "--employees",
        required=True,
        help=(
            "JSON array (or object with 'employees' array) of employee pay-period records. "
            "Each entry: {employee_id, name, ordinary_earnings, super_fund_usi?}."
        ),
    )
    payroll_prepare.add_argument("--pay-date", help="Pay date YYYY-MM-DD (default: today UTC)")
    payroll_prepare.add_argument(
        "--sg-rate",
        type=float,
        help=(
            "SG rate as a decimal fraction (e.g. 0.12 for 12%%). "
            "Always verify the current rate at ato.gov.au before use. "
            f"Default: {xero_payroll.SG_RATE_DEFAULT} (may be stale)."
        ),
    )
    payroll_prepare.add_argument("--out", help="Write the dry-run summary to a JSON file")
    payroll_prepare.add_argument("--ignore-scope-check", action="store_true", help="Continue even if payroll scopes are not detected")
    payroll_prepare.set_defaults(func=command_payroll_prepare_payrun)

    payroll_verify = payroll_sub.add_parser(
        "verify",
        help=(
            "Read-only skeleton: verify pay-run data against payslips/SG lines and report human steps. "
            "Does NOT lodge STP or execute super payments."
        ),
    )
    payroll_verify.add_argument("--tenant-id", help="Override active tenant id")
    payroll_verify.set_defaults(func=command_payroll_verify)

    payroll_list_pay_runs = payroll_sub.add_parser(
        "list-pay-runs",
        help="Read-only: list pay runs from the AU Payroll API. Requires payroll.payruns.read scope.",
    )
    payroll_list_pay_runs.add_argument(
        "--from",
        dest="from_date",
        help="Filter by PaymentDate >= this date (YYYY-MM-DD); translated to a Xero `where` clause",
    )
    payroll_list_pay_runs.add_argument(
        "--to",
        dest="to_date",
        help="Filter by PaymentDate <= this date (YYYY-MM-DD); translated to a Xero `where` clause",
    )
    payroll_list_pay_runs.add_argument(
        "--where",
        help="Raw Xero `where` filter (escape hatch; overrides --from/--to). The AU Payroll API has no fromDate/toDate params.",
    )
    payroll_list_pay_runs.add_argument("--page", type=int, help="1-based page number (Xero returns up to 100 pay runs per page)")
    payroll_list_pay_runs.add_argument("--order", help="Xero `order` clause")
    payroll_list_pay_runs.add_argument("--tenant-id", help="Override active tenant id")
    payroll_list_pay_runs.set_defaults(func=command_payroll_list_pay_runs)

    payroll_list_timesheets = payroll_sub.add_parser(
        "list-timesheets",
        help=(
            "Read-only: list timesheets from the AU Payroll API, filterable by date range, "
            "employee, or status (defaults to most-recent-first). Requires payroll.timesheets.read scope."
        ),
    )
    payroll_list_timesheets.add_argument(
        "--from",
        dest="from_date",
        help="Filter by StartDate >= this date (YYYY-MM-DD); translated to a Xero `where` clause",
    )
    payroll_list_timesheets.add_argument(
        "--to",
        dest="to_date",
        help="Filter by EndDate <= this date (YYYY-MM-DD); translated to a Xero `where` clause",
    )
    payroll_list_timesheets.add_argument("--employee", dest="employee_id", help="Filter by EmployeeID UUID")
    payroll_list_timesheets.add_argument("--status", help="Filter by Status (e.g. APPROVED, DRAFT, PROCESSED)")
    payroll_list_timesheets.add_argument(
        "--where",
        help="Raw Xero `where` filter (escape hatch; overrides --from/--to/--employee/--status).",
    )
    payroll_list_timesheets.add_argument("--page", type=int, help="1-based page number (Xero returns up to 100 timesheets per page)")
    payroll_list_timesheets.add_argument("--order", help="Xero `order` clause (default: 'StartDate DESC' when no filter)")
    payroll_list_timesheets.add_argument("--tenant-id", help="Override active tenant id")
    payroll_list_timesheets.set_defaults(func=command_payroll_list_timesheets)

    payroll_list_payslips = payroll_sub.add_parser(
        "list-payslips",
        help="Read-only: list payslips for a pay run. Requires payroll.payruns.read scope.",
    )
    payroll_list_payslips.add_argument("--pay-run-id", required=True, help="PayRunID UUID")
    payroll_list_payslips.add_argument("--tenant-id", help="Override active tenant id")
    payroll_list_payslips.set_defaults(func=command_payroll_list_payslips)

    payroll_get_payslip = payroll_sub.add_parser(
        "get-payslip",
        help="Read-only: fetch a single payslip by ID. Requires payroll.payruns.read scope.",
    )
    payroll_get_payslip.add_argument("--payslip-id", required=True, help="PayslipID UUID")
    payroll_get_payslip.add_argument("--tenant-id", help="Override active tenant id")
    payroll_get_payslip.set_defaults(func=command_payroll_get_payslip)

    payroll_employee_pay_template = payroll_sub.add_parser(
        "employee-pay-template",
        help="Read-only: fetch an employee's pay template. Requires payroll.employees.read scope.",
    )
    payroll_employee_pay_template.add_argument("--employee-id", required=True, help="EmployeeID UUID")
    payroll_employee_pay_template.add_argument("--tenant-id", help="Override active tenant id")
    payroll_employee_pay_template.set_defaults(func=command_payroll_employee_pay_template)

    reference = sub.add_parser("reference", help="Dry-run or upsert Xero reference/master data")
    reference_sub = reference.add_subparsers(dest="reference_command", required=True)
    reference_upsert = reference_sub.add_parser("upsert", help="Dry-run or upsert a contact, item, account, tracking category, or tracking option")
    reference_upsert.add_argument("kind", choices=sorted(REFERENCE_KINDS))
    reference_upsert.add_argument("--payload", required=True, help="JSON object, array, or wrapped Xero request payload")
    reference_upsert.add_argument("--method", choices=["POST", "PUT", "post", "put"], help="Override Xero request method; defaults by kind")
    reference_upsert.add_argument("--apply", action="store_true", help="Actually send the request to Xero")
    reference_upsert.add_argument("--preflight-report", help="Dry-run or audit report proving preflight checks before --apply")
    reference_upsert.add_argument("--confirm-apply-without-preflight", action="store_true", help="Explicit operator override for --apply without a preflight report")
    reference_upsert.add_argument("--tenant-id", help="Override active tenant id")
    reference_upsert.add_argument("--audit-dir", help="Override local audit directory for apply reports")
    reference_upsert.add_argument("--actor", default="local-cli", help="Actor label for apply report")
    reference_upsert.add_argument("--out", help="Write dry-run report to JSON file")
    reference_upsert.add_argument(
        "--summarize-errors",
        action=argparse.BooleanOptionalAction,
        default=False,
        help="Use Xero's summarized validation errors; default false for batch diagnostics",
    )
    reference_upsert.set_defaults(func=command_reference_upsert)

    prework = sub.add_parser("prework", help="Prepare accounting-side records for later reconciliation")
    prework_sub = prework.add_subparsers(dest="prework_command", required=True)
    prework_create = prework_sub.add_parser("create", help="Dry-run or create an allowlisted API pre-work object")
    prework_create.add_argument("kind", choices=sorted(PREWORK_KINDS))
    prework_create.add_argument("--payload", required=True, help="JSON object, array, or wrapped Xero request payload")
    prework_create.add_argument("--apply", action="store_true", help="Actually send the request to Xero")
    prework_create.add_argument("--preflight-report", help="Dry-run or audit report proving preflight checks before --apply")
    prework_create.add_argument("--confirm-apply-without-preflight", action="store_true", help="Explicit operator override for --apply without a preflight report")
    prework_create.add_argument("--tenant-id", help="Override active tenant id")
    prework_create.add_argument("--audit-dir", help="Override local audit directory for apply reports")
    prework_create.add_argument("--actor", default="local-cli", help="Actor label for apply report")
    prework_create.add_argument("--out", help="Write dry-run report to JSON file")
    prework_create.add_argument(
        "--summarize-errors",
        action=argparse.BooleanOptionalAction,
        default=False,
        help="Use Xero's summarized validation errors; default false for batch diagnostics",
    )
    prework_create.set_defaults(func=command_prework_create)

    rules = sub.add_parser("rules", help="Manage local Xero finance rules")
    rules_sub = rules.add_subparsers(dest="rules_command", required=True)
    rules_init = rules_sub.add_parser("init", help="Create a local finance-rules file from the generic template")
    rules_init.add_argument("--rules", help="Override finance-rules path")
    rules_init.add_argument("--force", action="store_true", help="Overwrite an existing rules file")
    rules_init.set_defaults(func=command_rules_init)
    rules_validate = rules_sub.add_parser("validate", help="Validate finance-rules JSON")
    rules_validate.add_argument("--rules", help="Override finance-rules path")
    rules_validate.set_defaults(func=command_rules_validate)
    parse_name = rules_sub.add_parser("parse-name", help="Run configured naming parsers against a value")
    parse_name.add_argument("value")
    parse_name.add_argument("--rules", help="Override finance-rules path")
    parse_name.set_defaults(func=command_rules_parse_name)
    map_cmd = rules_sub.add_parser("map", help="Resolve account, tax, item, or contact mapping for a value")
    map_cmd.add_argument("kind", choices=sorted(xero_finance_rules.SUPPORTED_MAPPING_KINDS))
    map_cmd.add_argument("value")
    map_cmd.add_argument("--rules", help="Override finance-rules path")
    map_cmd.set_defaults(func=command_rules_map)
    upsert_mapping = rules_sub.add_parser("upsert-mapping", help="Create or update a private mapping rule after operator review")
    upsert_mapping.add_argument("kind", choices=sorted(xero_finance_rules.SUPPORTED_MAPPING_KINDS))
    upsert_mapping.add_argument("--name", required=True, help="Stable local mapping rule name")
    upsert_mapping.add_argument("--alias", action="append", help="Exact source alias to resolve; repeatable")
    upsert_mapping.add_argument("--pattern", action="append", help="Regex source pattern to resolve; repeatable")
    upsert_mapping.add_argument("--target-json", help="Target mapping object as JSON")
    upsert_mapping.add_argument("--target-file", help="Target mapping object loaded from JSON file")
    upsert_mapping.add_argument("--source", default="operator", help="Decision source label")
    upsert_mapping.add_argument("--note", help="Optional local operator note")
    upsert_mapping.add_argument("--rules", help="Override finance-rules path")
    upsert_mapping.set_defaults(func=command_rules_upsert_mapping)

    audit = sub.add_parser("audit", help="Run local Xero audit and proof-report helpers")
    audit_sub = audit.add_subparsers(dest="audit_command", required=True)
    dry_run = audit_sub.add_parser("dry-run", help="Check candidate mutations against rules and local snapshots")
    dry_run.add_argument("--candidates", required=True, help="JSON array or object with candidates array")
    dry_run.add_argument("--rules", help="Override finance-rules path")
    dry_run.add_argument("--snapshots", help="Override snapshot directory")
    dry_run.add_argument("--out", help="Write report to a JSON file instead of stdout")
    dry_run.add_argument(
        "--max-batch-size",
        type=int,
        default=xero_finance_rules.DEFAULT_MAX_APPLY_BATCH_SIZE,
        help="Maximum ready candidates per proposed apply batch in the dry-run report",
    )
    dry_run.set_defaults(func=command_audit_dry_run)
    check_live = audit_sub.add_parser("check-live", help="Run a targeted read-only live Xero check before mutation")
    check_live.add_argument("kind", choices=sorted(LIVE_CHECK_KINDS))
    check_live.add_argument("value", help="Reference, name, or code to check")
    check_live.add_argument("--field", help="Override Xero where field for advanced targeted checks")
    check_live.add_argument("--tenant-id", help="Override active tenant id")
    check_live.add_argument("--limit", type=int, default=5, help="Maximum matching records to return")
    check_live.set_defaults(func=command_audit_check_live)
    record_apply = audit_sub.add_parser("record-apply", help="Write a local apply/audit report from a JSON event")
    record_apply.add_argument("--event", required=True, help="JSON object describing created/updated/skipped result")
    record_apply.add_argument("--audit-dir", help="Override local audit directory")
    record_apply.add_argument("--actor", default="local-cli", help="Actor label to write into the report")
    record_apply.set_defaults(func=command_audit_record_apply)
    list_apply = audit_sub.add_parser("list-apply", help="List local apply/audit ledger entries")
    list_apply.add_argument("--audit-dir", help="Override local audit directory")
    list_apply.add_argument("--limit", type=int, default=20, help="Maximum entries to return")
    list_apply.set_defaults(func=command_audit_list_apply)

    snapshots = sub.add_parser("snapshots", help="Fetch and inspect local Xero reference snapshots")
    snapshots_sub = snapshots.add_subparsers(dest="snapshots_command", required=True)
    snapshots_fetch = snapshots_sub.add_parser("fetch", help="Fetch a read-only reference snapshot from Xero")
    snapshots_fetch.add_argument("kind", choices=sorted(SNAPSHOT_KINDS))
    snapshots_fetch.add_argument("--tenant-id", help="Override active tenant id")
    snapshots_fetch.add_argument("--where", help="Optional Xero Accounting API where filter")
    snapshots_fetch.add_argument("--snapshots", help="Override snapshot directory")
    snapshots_fetch.set_defaults(func=command_snapshots_fetch)
    snapshots_list = snapshots_sub.add_parser("list", help="List local snapshot files and record counts")
    snapshots_list.add_argument("--snapshots", help="Override snapshot directory")
    snapshots_list.set_defaults(func=command_snapshots_list)

    lock = sub.add_parser("lock", help="Coordinate heavy Xero operations with a local FIFO lease lock")
    lock_sub = lock.add_subparsers(dest="lock_command", required=True)
    lock_acquire = lock_sub.add_parser("acquire", help="Acquire or queue for the heavy-operation lock")
    lock_acquire.add_argument("--holder", required=True, help="Human-readable operation holder")
    lock_acquire.add_argument("--wait", action="store_true", help="Wait until this request reaches the head of the queue")
    lock_acquire.add_argument("--timeout", type=int, default=xero_operation_lock.DEFAULT_WAIT_TIMEOUT_SECONDS, help="Wait/queue timeout in seconds")
    lock_acquire.add_argument("--ttl", type=int, default=xero_operation_lock.DEFAULT_LEASE_TTL_SECONDS, help="Lease TTL in seconds")
    lock_acquire.add_argument("--lock-store", help="Override operation lock state path")
    lock_acquire.set_defaults(func=command_lock_acquire)
    lock_release = lock_sub.add_parser("release", help="Release the current heavy-operation lease")
    lock_release.add_argument("lease_id")
    lock_release.add_argument("--lock-store", help="Override operation lock state path")
    lock_release.set_defaults(func=command_lock_release)
    lock_status = lock_sub.add_parser("status", help="Show heavy-operation lock status")
    lock_status.add_argument("--lock-store", help="Override operation lock state path")
    lock_status.set_defaults(func=command_lock_status)

    return parser


def apply_profile_env(args: argparse.Namespace) -> None:
    """Pin path-resolving env vars to the business this command targets.

    No registry → env is left untouched, so single-business and pre-existing-env
    behaviour is byte-identical to before the feature. With a registry, resolve
    the target the same way the rest of the module does — explicit
    --profile/XERO_PROFILE, else the registry default (legacy or sole business) —
    and pin its env so the CLI and the MCP aggregator always agree on which
    isolated store a command hits. An ambiguous registry (>=2 businesses, none
    default) raises ProfileError rather than silently using the legacy store.

    The `profiles` command group resolves profiles itself (and `list` spans
    several) so it is exempt. An explicit --store still wins, because
    token_store_path() checks the --store value before the environment.
    """
    if getattr(args, "command", None) == "profiles":
        return
    requested = xero_profiles.active_profile_key(getattr(args, "profile", None))
    if xero_profiles.load_registry() is None:
        # No registry: leave env untouched, but never silently swallow an
        # explicit --profile/XERO_PROFILE — resolve it so an unknown business
        # raises rather than running against the legacy store unnoticed.
        if requested and requested != xero_profiles.IMPLICIT_DEFAULT_KEY:
            xero_profiles.resolve_active_profile(requested)  # raises ProfileError
        return
    profile = xero_profiles.resolve_active_profile(getattr(args, "profile", None))
    os.environ.update(profile.env())
    # Record the resolved key so downstream tenant-identity pinning works the
    # same whether the profile came from --profile or XERO_PROFILE.
    os.environ[xero_profiles.PROFILE_ENV] = profile.key


def assert_pinned_tenant(tenant_id: str) -> None:
    """Defence-in-depth: refuse if the active tenant != the profile's pinned tenant.

    When the active profile (XERO_PROFILE) records an expected Xero tenant id,
    every token mint / API call asserts the resolved store's active tenant
    matches it. A misroute (wrong store -> wrong org) is then refused outright
    rather than silently executing against the wrong organisation. No pin
    recorded -> no assertion (opt-in hardening; legacy/unpinned unaffected).
    """
    requested = xero_profiles.active_profile_key()
    if not requested or requested == xero_profiles.IMPLICIT_DEFAULT_KEY:
        return
    try:
        profile = xero_profiles.resolve_active_profile(requested)
    except xero_profiles.ProfileError:
        return
    if profile.tenant_id and tenant_id and profile.tenant_id != tenant_id:
        raise XeroCliError(
            f"Tenant identity mismatch for profile {profile.key!r}: token store active "
            f"tenant {tenant_id} does not match the pinned tenant {profile.tenant_id}. "
            "Refusing the operation — this indicates a cross-org misroute. If the pin is "
            f"wrong, run `xero --profile {profile.key} profiles pin-tenant`."
        )


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        apply_profile_env(args)
        return int(args.func(args))
    except (
        XeroCliError,
        xero_ap_policy.APPolicyError,
        xero_profiles.ProfileError,
        xero_finance_rules.FinanceRulesError,
        xero_operation_lock.OperationLockError,
    ) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
