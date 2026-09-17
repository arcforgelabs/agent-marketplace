#!/usr/bin/env python3
"""Run Xero's official MCP server with Arc Forge local OAuth tokens.

The official `@xeroapi/xero-mcp-server` package exposes the Xero API tool
surface we want, but its stock auth modes require either Custom Connection
client credentials or a pre-supplied bearer token. This launcher keeps the
official package as the tool source and patches only the compiled auth client so
each tool call can request a fresh bearer token from `connectors/xero/cli/xero`.
"""

from __future__ import annotations

import argparse
import json
import os
import queue
import re
import shutil
import subprocess
import sys
import tarfile
import tempfile
import threading
import time
from pathlib import Path
from typing import Any


MODULE_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = MODULE_ROOT.parents[1]
LOCAL_XERO_CLI = MODULE_ROOT / "cli" / "xero"
DEFAULT_PACKAGE = "@xeroapi/xero-mcp-server"
DEFAULT_VERSION = "0.0.17"
DEFAULT_CACHE_ROOT = Path.home() / ".cache" / "arc-forge-tools" / "xero-mcp"
DEFAULT_RATE_LIMIT_PATH = Path.home() / ".config" / "arc-forge-tools" / "xero" / "rate-limit-status.json"
DEFAULT_SHARED_RATE_LIMIT_PATH = Path.home() / ".config" / "arc-forge-tools" / "xero" / "rate-limit-shared.json"
DEFAULT_RATE_UNBLOCK_PATH = Path.home() / ".config" / "arc-forge-tools" / "xero" / "rate-limit-unblock.json"
PATCH_MARKER = "arc-forge-local-token-provider"
GOVERNOR_MARKER = "arc-forge-rate-governor"
SHARED_GOVERNOR_MARKER = "arc-forge-shared-rate-budget"
HEADER_OBSERVER_MARKER = "arc-forge-rate-header-observer"
DAY_BREAKER_MARKER = "arc-forge-day-limit-circuit-breaker"
RATE_PROBLEM_MARKER = "arc-forge-rate-problem-observer"
TENANT_STATUS_MARKER = "tenant_budget_scope"
TOOL_NAME_PATTERN = re.compile(r'CreateXeroTool\(\s*"([^"]+)"')
API_SURFACE_REQUIREMENTS: dict[str, dict[str, list[str]]] = {
    "contacts": {"official": ["list-contacts", "create-contact", "update-contact"], "local": ["xero reference upsert contact", "xero snapshots fetch contacts"]},
    "items": {"official": ["list-items", "create-item", "update-item"], "local": ["xero reference upsert item", "xero snapshots fetch items"]},
    "tax_rates": {"official": ["list-tax-rates"], "local": ["xero snapshots fetch tax-rates"]},
    "accounts": {"official": ["list-accounts"], "local": ["xero reference upsert account", "xero snapshots fetch accounts"]},
    "tracking_categories": {"official": ["list-tracking-categories", "create-tracking-category", "create-tracking-options", "update-tracking-category", "update-tracking-options"], "local": ["xero reference upsert tracking-category", "xero reference upsert tracking-option"]},
    "invoices_bills": {"official": ["list-invoices", "create-invoice", "update-invoice"], "local": ["xero documents create invoice", "xero documents create bill", "xero documents update invoice", "xero documents update bill"]},
    "quotes": {"official": ["list-quotes", "create-quote", "update-quote"], "local": ["xero documents create quote", "xero documents update quote"]},
    "credit_notes": {"official": ["list-credit-notes", "create-credit-note", "update-credit-note"], "local": ["xero documents create credit-note", "xero documents update credit-note"]},
    "payments": {"official": ["list-payments", "create-payment"], "local": ["xero prework create payment"]},
    "batch_payments": {"official": [], "local": ["xero prework create batch-payment"]},
    "bank_transactions": {"official": ["list-bank-transactions", "create-bank-transaction", "update-bank-transaction"], "local": ["xero prework create bank-transaction"]},
    "bank_transfers": {"official": [], "local": ["xero prework create bank-transfer"]},
    "manual_journals": {"official": ["list-manual-journals", "create-manual-journal", "update-manual-journal"], "local": ["xero prework create manual-journal"]},
    "reports": {"official": ["list-profit-and-loss", "list-report-balance-sheet", "list-trial-balance", "list-aged-receivables-by-contact", "list-aged-payables-by-contact"], "local": ["xero reports get"]},
    "attachments_history": {"official": [], "local": ["xero evidence history", "xero evidence attachments"]},
    "dedup_audit": {"official": [], "local": ["xero audit dry-run", "xero audit check-live", "xero audit record-apply"]},
    "reference_snapshots": {"official": [], "local": ["xero snapshots fetch", "xero snapshots list"]},
    "targeted_live_checks": {"official": [], "local": ["xero audit check-live"]},
}
MUTATING_TOOL_PREFIXES = (
    "create-",
    "update-",
    "delete-",
    "approve-",
    "revert-",
)
LOCAL_PREFLIGHT_ALTERNATIVES: dict[str, list[str]] = {
    "create-contact": ["xero reference upsert contact --preflight-report <report>"],
    "update-contact": ["xero reference upsert contact --preflight-report <report>"],
    "create-item": ["xero reference upsert item --preflight-report <report>"],
    "update-item": ["xero reference upsert item --preflight-report <report>"],
    "create-tracking-category": ["xero reference upsert tracking-category --preflight-report <report>"],
    "update-tracking-category": ["xero reference upsert tracking-category --preflight-report <report>"],
    "create-tracking-options": ["xero reference upsert tracking-option --preflight-report <report>"],
    "update-tracking-options": ["xero reference upsert tracking-option --preflight-report <report>"],
    "create-invoice": ["xero documents create invoice --preflight-report <report>", "xero documents create bill --preflight-report <report>"],
    "update-invoice": ["xero documents update invoice --preflight-report <report>", "xero documents update bill --preflight-report <report>"],
    "create-quote": ["xero documents create quote --preflight-report <report>"],
    "update-quote": ["xero documents update quote --preflight-report <report>"],
    "create-credit-note": ["xero documents create credit-note --preflight-report <report>"],
    "update-credit-note": ["xero documents update credit-note --preflight-report <report>"],
    "create-payment": ["xero prework create payment --preflight-report <report>"],
    "create-bank-transaction": ["xero prework create bank-transaction --preflight-report <report>"],
    "update-bank-transaction": ["xero prework create bank-transaction --preflight-report <report>"],
    "create-manual-journal": ["xero prework create manual-journal --preflight-report <report>"],
    "update-manual-journal": ["xero prework create manual-journal --preflight-report <report>"],
}


class XeroMcpLocalError(RuntimeError):
    """User-facing launcher error."""


def redact_value(value: Any) -> str:
    text = str(value)
    secretish = ("token", "authorization", "secret", "cookie", "mfa", "totp")
    lowered = text.lower()
    if any(item in lowered for item in secretish):
        return "[redacted]"
    if len(text) <= 16:
        return text
    return f"{text[:6]}...{text[-4:]}"


def parse_json_if_value(value: str, *, label: str) -> Any:
    try:
        return json.loads(value)
    except json.JSONDecodeError as exc:
        raise XeroMcpLocalError(f"{label} must be valid JSON: {exc}") from exc


def run(command: list[str], *, cwd: Path | None = None, capture: bool = False, env: dict[str, str] | None = None) -> subprocess.CompletedProcess[str]:
    result = subprocess.run(
        command,
        cwd=cwd,
        env=env,
        text=True,
        stdout=subprocess.PIPE if capture else None,
        stderr=subprocess.PIPE if capture else None,
        check=False,
    )
    if result.returncode != 0:
        detail = ""
        if capture:
            detail = "\n" + (result.stdout or "") + (result.stderr or "")
        raise XeroMcpLocalError(f"command failed ({result.returncode}): {' '.join(command)}{detail}")
    return result


def cache_root(value: str | None = None) -> Path:
    raw = value or os.environ.get("ARC_FORGE_XERO_MCP_CACHE")
    return Path(raw).expanduser().resolve() if raw else DEFAULT_CACHE_ROOT


def package_dir(root: Path, version: str) -> Path:
    return root / f"xeroapi-xero-mcp-server-{version}" / "package"


def ensure_official_package(*, root: Path, version: str, force: bool = False) -> Path:
    target = package_dir(root, version)
    index_path = target / "dist" / "index.js"
    if index_path.exists() and not force:
        patch_official_client(target / "dist" / "clients" / "xero-client.js")
        return target

    if target.parent.exists():
        shutil.rmtree(target.parent)
    target.parent.mkdir(parents=True, exist_ok=True)

    with tempfile.TemporaryDirectory() as temp_dir:
        temp = Path(temp_dir)
        result = run(["npm", "pack", f"{DEFAULT_PACKAGE}@{version}"], cwd=temp, capture=True)
        tarballs = [line.strip() for line in result.stdout.splitlines() if line.strip().endswith(".tgz")]
        if not tarballs:
            raise XeroMcpLocalError("npm pack did not report a Xero MCP tarball.")
        tarball = temp / tarballs[-1]
        with tarfile.open(tarball, "r:gz") as archive:
            archive.extractall(target.parent, filter="data")

    if not index_path.exists():
        raise XeroMcpLocalError(f"official MCP package did not contain dist/index.js: {target}")
    run(["npm", "install", "--omit=dev", "--ignore-scripts", "--no-audit", "--no-fund"], cwd=target, capture=True)
    patch_official_client(target / "dist" / "clients" / "xero-client.js")
    return target


def patch_official_client(client_path: Path) -> None:
    source = client_path.read_text(encoding="utf-8")
    patched = patch_client_source(source)
    client_path.write_text(patched, encoding="utf-8")


def patch_client_source(source: str) -> str:
    if PATCH_MARKER in source and GOVERNOR_MARKER in source and SHARED_GOVERNOR_MARKER in source and HEADER_OBSERVER_MARKER in source and DAY_BREAKER_MARKER in source and RATE_PROBLEM_MARKER in source:
        return source

    patched = source
    if 'import { execFileSync } from "node:child_process";' not in patched:
        patched = patched.replace(
            'import axios from "axios";\n',
            'import axios from "axios";\nimport { execFileSync } from "node:child_process";\n',
            1,
        )
    if 'import { mkdirSync, writeFileSync } from "node:fs";' in patched:
        patched = patched.replace(
            'import { mkdirSync, writeFileSync } from "node:fs";',
            'import { closeSync, mkdirSync, openSync, readFileSync, unlinkSync, writeFileSync } from "node:fs";',
            1,
        )
    if 'import { mkdirSync, readFileSync, writeFileSync } from "node:fs";' in patched:
        patched = patched.replace(
            'import { mkdirSync, readFileSync, writeFileSync } from "node:fs";',
            'import { closeSync, mkdirSync, openSync, readFileSync, unlinkSync, writeFileSync } from "node:fs";',
            1,
        )
    if 'import { closeSync, mkdirSync, openSync, readFileSync, unlinkSync, writeFileSync } from "node:fs";' not in patched:
        patched = patched.replace(
            'import { execFileSync } from "node:child_process";\n',
            'import { execFileSync } from "node:child_process";\nimport { closeSync, mkdirSync, openSync, readFileSync, unlinkSync, writeFileSync } from "node:fs";\nimport { dirname } from "node:path";\n',
            1,
        )
    if "const local_auth =" not in patched:
        patched = patched.replace(
            'const grant_type = "client_credentials";\nif (!bearer_token && (!client_id || !client_secret)) {\n    throw Error("Environment Variables not set - please check your .env file");\n}\n',
            'const grant_type = "client_credentials";\nconst local_auth = process.env.ARC_FORGE_XERO_USE_LOCAL_AUTH === "1";\nif (!local_auth && !bearer_token && (!client_id || !client_secret)) {\n    throw Error("Environment Variables not set - please check your .env file");\n}\n',
            1,
        )
    governor_source = """const rateGovernor = {
    // arc-forge-rate-governor
    // arc-forge-shared-rate-budget
    // arc-forge-rate-header-observer
    // arc-forge-day-limit-circuit-breaker
    // arc-forge-rate-problem-observer
    inFlight: 0,
    queue: [],
    minuteWindow: [],
    appMinuteWindow: [],
    dayKey: "",
    dayCount: 0,
    tenantId: null,
    lastOperation: null,
    lastObserved: null,
    lastObservedPressure: null,
    config: {
        maxConcurrent: Number(process.env.ARC_FORGE_XERO_MAX_CONCURRENT || "4"),
        maxPerMinute: Number(process.env.ARC_FORGE_XERO_MAX_PER_MINUTE || "55"),
        dayLimit: Number(process.env.ARC_FORGE_XERO_DAY_LIMIT || "5000"),
        appMinuteLimit: Number(process.env.ARC_FORGE_XERO_APP_MINUTE_LIMIT || "10000"),
        minuteWindowMs: 60000,
        maxRetrySleepMs: Number(process.env.ARC_FORGE_XERO_MAX_RETRY_SLEEP_MS || "60000"),
        sharedBudgetStore: process.env.ARC_FORGE_XERO_SHARED_RATE_LIMIT_STORE || "",
        dayLimitUnblockStore: process.env.ARC_FORGE_XERO_DAY_LIMIT_UNBLOCK_STORE || "",
    },
};
function pruneRateWindows(now) {
    const cutoff = now - rateGovernor.config.minuteWindowMs;
    rateGovernor.minuteWindow = rateGovernor.minuteWindow.filter((value) => value > cutoff);
    rateGovernor.appMinuteWindow = rateGovernor.appMinuteWindow.filter((value) => value > cutoff);
    const dayKey = new Date(now).toISOString().slice(0, 10);
    if (rateGovernor.dayKey !== dayKey) {
        rateGovernor.dayKey = dayKey;
        rateGovernor.dayCount = 0;
    }
}
function dayLimitResetAt(now) {
    const next = new Date(now);
    next.setUTCHours(24, 0, 0, 0);
    return next.toISOString();
}
function readDayLimitUnblock() {
    const path = rateGovernor.config.dayLimitUnblockStore;
    if (!path) {
        return null;
    }
    try {
        return JSON.parse(readFileSync(path, "utf8"));
    }
    catch (_error) {
        return null;
    }
}
function dayLimitUnblocked() {
    const payload = readDayLimitUnblock();
    return Boolean(payload?.allow_day_limit_bypass === true && payload?.day_key === rateGovernor.dayKey);
}
function dayLimitCircuitOpen(now) {
    return rateGovernor.dayCount >= rateGovernor.config.dayLimit && !dayLimitUnblocked();
}
function sharedBudgetInitialState() {
    return { schema_version: 1, source: "xero-mcp-local-shared", tenants: {}, app_minute_window: [] };
}
function sharedBudgetPath() {
    return rateGovernor.config.sharedBudgetStore;
}
function sharedBudgetTenant(state, tenantId) {
    if (!state.tenants || typeof state.tenants !== "object") {
        state.tenants = {};
    }
    let tenant = state.tenants[tenantId];
    if (!tenant || typeof tenant !== "object") {
        tenant = { tenant_id: tenantId, day_key: rateGovernor.dayKey, day_count: 0, minute_window: [], circuit_open: false };
        state.tenants[tenantId] = tenant;
    }
    if (!Array.isArray(tenant.minute_window)) {
        tenant.minute_window = [];
    }
    return tenant;
}
function pruneSharedBudgetState(state, now) {
    const cutoff = now - rateGovernor.config.minuteWindowMs;
    if (!Array.isArray(state.app_minute_window)) {
        state.app_minute_window = [];
    }
    state.app_minute_window = state.app_minute_window.map((value) => Number(value)).filter((value) => Number.isFinite(value) && value > cutoff);
    const dayKey = new Date(now).toISOString().slice(0, 10);
    for (const tenant of Object.values(state.tenants || {})) {
        if (!tenant || typeof tenant !== "object") {
            continue;
        }
        tenant.minute_window = Array.isArray(tenant.minute_window)
            ? tenant.minute_window.map((value) => Number(value)).filter((value) => Number.isFinite(value) && value > cutoff)
            : [];
        if (tenant.day_key !== dayKey) {
            tenant.day_key = dayKey;
            tenant.day_count = 0;
            tenant.circuit_open = false;
        }
    }
}
function readSharedBudgetState(path) {
    if (!path) {
        return sharedBudgetInitialState();
    }
    try {
        return JSON.parse(readFileSync(path, "utf8"));
    }
    catch (_error) {
        return sharedBudgetInitialState();
    }
}
function writeSharedBudgetState(path, state) {
    if (!path) {
        return;
    }
    mkdirSync(dirname(path), { recursive: true });
    writeFileSync(path, JSON.stringify(state, null, 2) + "\\n", { mode: 0o600 });
}
function withSharedBudgetGuard(path, fn) {
    if (!path) {
        return fn();
    }
    const guardPath = `${path}.guard`;
    mkdirSync(dirname(path), { recursive: true });
    let fd = null;
    try {
        fd = openSync(guardPath, "wx", 0o600);
        return fn();
    }
    catch (error) {
        if (error?.code === "EEXIST") {
            return { ok: false, wait_ms: 1000, reason: "shared-budget-guard-busy" };
        }
        throw error;
    }
    finally {
        if (fd !== null) {
            try {
                closeSync(fd);
            }
            catch (_error) {
            }
            try {
                unlinkSync(guardPath);
            }
            catch (_error) {
            }
        }
    }
}
function tryAcquireSharedRateBudget(now, operation) {
    const path = sharedBudgetPath();
    if (!path) {
        return { ok: true, shared: false };
    }
    const tenantId = rateGovernor.tenantId || "unknown-selected-tenant";
    return withSharedBudgetGuard(path, () => {
        const state = readSharedBudgetState(path);
        state.schema_version = 1;
        state.source = "xero-mcp-local-shared";
        state.updated_at = new Date(now).toISOString();
        pruneSharedBudgetState(state, now);
        const tenant = sharedBudgetTenant(state, tenantId);
        const tenantDayCount = Number(tenant.day_count || 0);
        if (tenant.circuit_open === true || tenantDayCount >= rateGovernor.config.dayLimit) {
            tenant.circuit_open = true;
            tenant.day_count = Math.max(tenantDayCount, rateGovernor.config.dayLimit);
            writeSharedBudgetState(path, state);
            return { ok: false, fatal: true, reason: "shared-day-limit-open" };
        }
        if (tenant.minute_window.length >= rateGovernor.config.maxPerMinute) {
            const oldest = Math.min(...tenant.minute_window);
            return { ok: false, wait_ms: Math.max(1000, rateGovernor.config.minuteWindowMs - (now - oldest)), reason: "shared-tenant-minute-exhausted" };
        }
        if (state.app_minute_window.length >= rateGovernor.config.appMinuteLimit) {
            const oldest = Math.min(...state.app_minute_window);
            return { ok: false, wait_ms: Math.max(1000, rateGovernor.config.minuteWindowMs - (now - oldest)), reason: "shared-app-minute-exhausted" };
        }
        tenant.minute_window.push(now);
        tenant.day_count = tenantDayCount + 1;
        tenant.day_key = rateGovernor.dayKey;
        state.app_minute_window.push(now);
        state.last_operation = { operation, tenant_id: tenantId };
        writeSharedBudgetState(path, state);
        return { ok: true, shared: true };
    });
}
function rateStatusPayload(operation = null) {
    const now = Date.now();
    pruneRateWindows(now);
    return {
        ok: true,
        source: "xero-mcp-local",
        updated_at: new Date(now).toISOString(),
        operation,
        in_flight: rateGovernor.inFlight,
        queued: rateGovernor.queue.length,
        minute_count: rateGovernor.minuteWindow.length,
        app_minute_count: rateGovernor.appMinuteWindow.length,
        day_key: rateGovernor.dayKey,
        day_count: rateGovernor.dayCount,
        circuit_breaker: {
            day_limit_reached: rateGovernor.dayCount >= rateGovernor.config.dayLimit,
            day_limit_open: dayLimitCircuitOpen(now),
            day_limit_unblocked: dayLimitUnblocked(),
            day_limit_reset_at: dayLimitResetAt(now),
            day_limit_unblock_store: rateGovernor.config.dayLimitUnblockStore || null,
        },
        tenant_id: rateGovernor.tenantId,
        tenant_budget_scope: rateGovernor.tenantId ? "selected-tenant" : "unknown-selected-tenant",
        last_observed: rateGovernor.lastObserved,
        last_observed_pressure: rateGovernor.lastObservedPressure,
        shared_budget_store: rateGovernor.config.sharedBudgetStore || null,
        limits: {
            max_concurrent: rateGovernor.config.maxConcurrent,
            max_per_minute: rateGovernor.config.maxPerMinute,
            day_limit: rateGovernor.config.dayLimit,
            app_minute_limit: rateGovernor.config.appMinuteLimit,
            max_retry_sleep_ms: rateGovernor.config.maxRetrySleepMs,
        },
    };
}
function writeRateStatus(operation = null) {
    const path = process.env.ARC_FORGE_XERO_RATE_LIMIT_STORE;
    // An unexpanded "${VAR:-default}" is never a real path; writing it would
    // mkdir the literal string as a directory tree.
    if (!path || path.includes("${")) {
        return;
    }
    try {
        mkdirSync(dirname(path), { recursive: true });
        writeFileSync(path, JSON.stringify(rateStatusPayload(operation), null, 2) + "\\n", { mode: 0o600 });
    }
    catch (_error) {
        // Status visibility should not make otherwise valid Xero calls fail.
    }
}
function tryStartNextRateOperation() {
    const now = Date.now();
    pruneRateWindows(now);
    if (rateGovernor.queue.length === 0) {
        writeRateStatus(rateGovernor.lastOperation);
        return;
    }
    if (dayLimitCircuitOpen(now)) {
        const error = new Error(`Xero day-limit circuit breaker is open for ${rateGovernor.dayKey}. Run xero rate unblock-day-limit only after an operator approves more calls.`);
        error.code = "ARC_FORGE_XERO_DAY_LIMIT_OPEN";
        while (rateGovernor.queue.length > 0) {
            const blocked = rateGovernor.queue.shift();
            blocked.reject(error);
        }
        writeRateStatus(rateGovernor.lastOperation);
        return;
    }
    if (rateGovernor.inFlight >= rateGovernor.config.maxConcurrent ||
        rateGovernor.minuteWindow.length >= rateGovernor.config.maxPerMinute ||
        rateGovernor.appMinuteWindow.length >= rateGovernor.config.appMinuteLimit) {
        const waitMs = Math.max(1000, rateGovernor.config.minuteWindowMs - (now - Math.min(...rateGovernor.minuteWindow, now)));
        setTimeout(tryStartNextRateOperation, waitMs);
        writeRateStatus(rateGovernor.queue[0]?.operation || rateGovernor.lastOperation);
        return;
    }
    const next = rateGovernor.queue[0];
    const shared = tryAcquireSharedRateBudget(now, next.operation);
    if (!shared.ok) {
        if (shared.fatal) {
            const error = new Error(`Xero shared rate-budget circuit is open: ${shared.reason}. Inspect xero rate status before retrying.`);
            error.code = "ARC_FORGE_XERO_SHARED_RATE_LIMIT_OPEN";
            while (rateGovernor.queue.length > 0) {
                const blocked = rateGovernor.queue.shift();
                blocked.reject(error);
            }
            writeRateStatus(rateGovernor.lastOperation);
            return;
        }
        setTimeout(tryStartNextRateOperation, Math.max(1000, shared.wait_ms || 1000));
        writeRateStatus(next.operation || rateGovernor.lastOperation);
        return;
    }
    rateGovernor.queue.shift();
    rateGovernor.inFlight += 1;
    rateGovernor.minuteWindow.push(now);
    rateGovernor.appMinuteWindow.push(now);
    rateGovernor.dayCount += 1;
    rateGovernor.lastOperation = next.operation;
    writeRateStatus(next.operation);
    next.resolve();
}
function acquireXeroRateSlot(operation) {
    return new Promise((resolve, reject) => {
        rateGovernor.queue.push({ operation, resolve, reject });
        tryStartNextRateOperation();
    });
}
function releaseXeroRateSlot(operation) {
    rateGovernor.inFlight = Math.max(0, rateGovernor.inFlight - 1);
    writeRateStatus(operation);
    setTimeout(tryStartNextRateOperation, 0);
}
function sleepRate(ms) {
    return new Promise((resolve) => setTimeout(resolve, ms));
}
function headerValue(headers, name) {
    if (!headers) {
        return null;
    }
    const lowerName = name.toLowerCase();
    if (typeof headers.get === "function") {
        return headers.get(name) || headers.get(lowerName);
    }
    for (const [key, value] of Object.entries(headers)) {
        if (key.toLowerCase() === lowerName) {
            return Array.isArray(value) ? value[0] : value;
        }
    }
    return null;
}
function parseRetryAfterMs(value) {
    if (!value) {
        return 0;
    }
    const text = String(value).trim();
    const seconds = Number(text);
    if (Number.isFinite(seconds)) {
        return Math.max(0, seconds * 1000);
    }
    const dateMs = Date.parse(text);
    if (Number.isFinite(dateMs)) {
        return Math.max(0, dateMs - Date.now());
    }
    return 0;
}
function limitedObservedHeaders(headers) {
    const names = [
        "retry-after",
        "x-rate-limit-limit",
        "x-rate-limit-remaining",
        "x-rate-limit-reset",
        "x-rate-limit-problem",
        "x-minlimit-remaining",
        "x-daylimit-remaining",
        "x-appminlimit-remaining",
    ];
    const observed = {};
    for (const name of names) {
        const value = headerValue(headers, name);
        if (value !== null && value !== undefined) {
            observed[name] = String(value);
        }
    }
    return observed;
}
function responseFromResult(result) {
    return result?.response || result?.res || result;
}
function numericHeaderValue(headers, name) {
    const value = headerValue(headers, name);
    if (value === null || value === undefined || value === "") {
        return null;
    }
    const parsed = Number(value);
    return Number.isFinite(parsed) ? parsed : null;
}
function applyObservedRatePressure(headers) {
    // arc-forge-rate-problem-observer
    const problem = headerValue(headers, "x-rate-limit-problem");
    const dayRemaining = numericHeaderValue(headers, "x-daylimit-remaining");
    const minuteRemaining = numericHeaderValue(headers, "x-minlimit-remaining");
    const appMinuteRemaining = numericHeaderValue(headers, "x-appminlimit-remaining");
    if (problem || dayRemaining !== null || minuteRemaining !== null || appMinuteRemaining !== null) {
        rateGovernor.lastObservedPressure = {
            problem: problem ? String(problem) : null,
            day_remaining: dayRemaining,
            minute_remaining: minuteRemaining,
            app_minute_remaining: appMinuteRemaining,
        };
    }
    if (String(problem || "").toLowerCase() === "daylimit" || (dayRemaining !== null && dayRemaining <= 0)) {
        rateGovernor.dayCount = Math.max(rateGovernor.dayCount, rateGovernor.config.dayLimit);
    }
}
function observeRateHeaders(operation, resultOrError) {
    const response = resultOrError?.response || responseFromResult(resultOrError);
    const headers = response?.headers || resultOrError?.headers;
    const observedHeaders = limitedObservedHeaders(headers);
    const retryAfterMs = parseRetryAfterMs(headerValue(headers, "retry-after"));
    applyObservedRatePressure(headers);
    if (Object.keys(observedHeaders).length > 0 || retryAfterMs > 0 || response?.status) {
        rateGovernor.lastObserved = {
            operation,
            observed_at: new Date().toISOString(),
            tenant_id: rateGovernor.tenantId,
            status_code: response?.status || response?.statusCode || null,
            retry_after_ms: retryAfterMs,
            rate_limit_problem: observedHeaders["x-rate-limit-problem"] || null,
            pressure: rateGovernor.lastObservedPressure || null,
            headers: observedHeaders,
        };
        writeRateStatus(operation);
    }
    return retryAfterMs;
}
function isRateLimitError(error) {
    const status = error?.response?.status || error?.status || error?.statusCode;
    return Number(status) === 429;
}
function rateLimitApi(api, label) {
    if (!api || api.__arcForgeRateLimited) {
        return api;
    }
    const proxy = new Proxy(api, {
        get(target, prop, receiver) {
            const value = Reflect.get(target, prop, receiver);
            if (typeof value !== "function") {
                return value;
            }
            return async (...args) => {
                const operation = `${label}.${String(prop)}`;
                let retryAttempted = false;
                while (true) {
                    await acquireXeroRateSlot(operation);
                    let shouldRetry = false;
                    let sleepMs = 0;
                    try {
                        const result = await value.apply(target, args);
                        observeRateHeaders(operation, result);
                        return result;
                    }
                    catch (error) {
                        const retryAfterMs = observeRateHeaders(operation, error);
                        if (!retryAttempted && isRateLimitError(error) && retryAfterMs > 0) {
                            retryAttempted = true;
                            shouldRetry = true;
                            sleepMs = Math.min(retryAfterMs, rateGovernor.config.maxRetrySleepMs);
                        }
                        else {
                            throw error;
                        }
                    }
                    finally {
                        releaseXeroRateSlot(operation);
                    }
                    if (shouldRetry) {
                        await sleepRate(sleepMs);
                        continue;
                    }
                }
            };
        },
    });
    Object.defineProperty(proxy, "__arcForgeRateLimited", { value: true });
    return proxy;
}
function installRateLimitProxies(client) {
    for (const key of [
        "accountingApi",
        "assetApi",
        "bankFeedsApi",
        "filesApi",
        "financeApi",
        "payrollAuApi",
        "payrollNzApi",
        "payrollUkApi",
        "projectApi",
    ]) {
        if (client[key]) {
            client[key] = rateLimitApi(client[key], key);
        }
    }
    writeRateStatus("installed");
}
"""
    if GOVERNOR_MARKER in patched and SHARED_GOVERNOR_MARKER not in patched:
        patched, count = re.subn(
            r"const rateGovernor = \{.*?\n\}\nclass (BearerTokenXeroClient|LocalTokenXeroClient)",
            lambda match: governor_source + f"class {match.group(1)}",
            patched,
            count=1,
            flags=re.S,
        )
        if count == 0:
            raise XeroMcpLocalError("Could not upgrade existing Xero MCP rate-governor patch.")
    if GOVERNOR_MARKER not in patched:
        patched = patched.replace(
            "class BearerTokenXeroClient extends MCPXeroClient {\n",
            governor_source + "class BearerTokenXeroClient extends MCPXeroClient {\n",
            1,
        )
    elif HEADER_OBSERVER_MARKER not in patched:
        patched = patched.replace(
            "    // arc-forge-rate-governor\n",
            "    // arc-forge-rate-governor\n    // arc-forge-rate-header-observer\n",
            1,
        )
        patched = patched.replace("    lastOperation: null,\n", "    lastOperation: null,\n    lastObserved: null,\n", 1)
        patched = patched.replace("    dayCount: 0,\n", "    dayCount: 0,\n    tenantId: null,\n", 1)
        patched = patched.replace(
            "        minuteWindowMs: 60000,\n",
            '        minuteWindowMs: 60000,\n        maxRetrySleepMs: Number(process.env.ARC_FORGE_XERO_MAX_RETRY_SLEEP_MS || "60000"),\n',
            1,
        )
        patched = patched.replace(
            "        day_count: rateGovernor.dayCount,\n",
            "        day_count: rateGovernor.dayCount,\n        tenant_id: rateGovernor.tenantId,\n        tenant_budget_scope: rateGovernor.tenantId ? \"selected-tenant\" : \"unknown-selected-tenant\",\n        last_observed: rateGovernor.lastObserved,\n",
            1,
        )
        patched = patched.replace(
            "            app_minute_limit: rateGovernor.config.appMinuteLimit,\n",
            "            app_minute_limit: rateGovernor.config.appMinuteLimit,\n            max_retry_sleep_ms: rateGovernor.config.maxRetrySleepMs,\n",
            1,
        )
        helper_source = """function sleepRate(ms) {
    return new Promise((resolve) => setTimeout(resolve, ms));
}
function headerValue(headers, name) {
    if (!headers) {
        return null;
    }
    const lowerName = name.toLowerCase();
    if (typeof headers.get === "function") {
        return headers.get(name) || headers.get(lowerName);
    }
    for (const [key, value] of Object.entries(headers)) {
        if (key.toLowerCase() === lowerName) {
            return Array.isArray(value) ? value[0] : value;
        }
    }
    return null;
}
function parseRetryAfterMs(value) {
    if (!value) {
        return 0;
    }
    const text = String(value).trim();
    const seconds = Number(text);
    if (Number.isFinite(seconds)) {
        return Math.max(0, seconds * 1000);
    }
    const dateMs = Date.parse(text);
    if (Number.isFinite(dateMs)) {
        return Math.max(0, dateMs - Date.now());
    }
    return 0;
}
function limitedObservedHeaders(headers) {
    const names = [
        "retry-after",
        "x-rate-limit-limit",
        "x-rate-limit-remaining",
        "x-rate-limit-reset",
        "x-minlimit-remaining",
        "x-daylimit-remaining",
        "x-appminlimit-remaining",
    ];
    const observed = {};
    for (const name of names) {
        const value = headerValue(headers, name);
        if (value !== null && value !== undefined) {
            observed[name] = String(value);
        }
    }
    return observed;
}
function responseFromResult(result) {
    return result?.response || result?.res || result;
}
function observeRateHeaders(operation, resultOrError) {
    const response = resultOrError?.response || responseFromResult(resultOrError);
    const headers = response?.headers || resultOrError?.headers;
    const observedHeaders = limitedObservedHeaders(headers);
    const retryAfterMs = parseRetryAfterMs(headerValue(headers, "retry-after"));
    if (Object.keys(observedHeaders).length > 0 || retryAfterMs > 0 || response?.status) {
        rateGovernor.lastObserved = {
            operation,
            observed_at: new Date().toISOString(),
            tenant_id: rateGovernor.tenantId,
            status_code: response?.status || response?.statusCode || null,
            retry_after_ms: retryAfterMs,
            headers: observedHeaders,
        };
        writeRateStatus(operation);
    }
    return retryAfterMs;
}
function isRateLimitError(error) {
    const status = error?.response?.status || error?.status || error?.statusCode;
    return Number(status) === 429;
}
"""
        patched = patched.replace("function rateLimitApi(api, label) {\n", helper_source + "function rateLimitApi(api, label) {\n", 1)
        patched = patched.replace(
            """            return async (...args) => {
                const operation = `${label}.${String(prop)}`;
                await acquireXeroRateSlot(operation);
                try {
                    return await value.apply(target, args);
                }
                finally {
                    releaseXeroRateSlot(operation);
                }
            };
""",
            """            return async (...args) => {
                const operation = `${label}.${String(prop)}`;
                let retryAttempted = false;
                while (true) {
                    await acquireXeroRateSlot(operation);
                    let shouldRetry = false;
                    let sleepMs = 0;
                    try {
                        const result = await value.apply(target, args);
                        observeRateHeaders(operation, result);
                        return result;
                    }
                    catch (error) {
                        const retryAfterMs = observeRateHeaders(operation, error);
                        if (!retryAttempted && isRateLimitError(error) && retryAfterMs > 0) {
                            retryAttempted = true;
                            shouldRetry = true;
                            sleepMs = Math.min(retryAfterMs, rateGovernor.config.maxRetrySleepMs);
                        }
                        else {
                            throw error;
                        }
                    }
                    finally {
                        releaseXeroRateSlot(operation);
                    }
                    if (shouldRetry) {
                        await sleepRate(sleepMs);
                        continue;
                    }
                }
            };
""",
            1,
        )
    if PATCH_MARKER not in patched:
        patched = patched.replace(
        """class BearerTokenXeroClient extends MCPXeroClient {
    bearerToken;
    constructor(config) {
        super();
        this.bearerToken = config.bearerToken;
    }
    async authenticate() {
        this.setTokenSet({
            access_token: this.bearerToken,
        });
        await this.updateTenants();
    }
}
export const xeroClient = bearer_token
    ? new BearerTokenXeroClient({
        bearerToken: bearer_token,
    })
    : new CustomConnectionsXeroClient({
        clientId: client_id,
        clientSecret: client_secret,
        grantType: grant_type,
    });
""",
        """class BearerTokenXeroClient extends MCPXeroClient {
    bearerToken;
    constructor(config) {
        super();
        this.bearerToken = config.bearerToken;
    }
    async authenticate() {
        this.setTokenSet({
            access_token: this.bearerToken,
        });
        await this.updateTenants();
    }
}
class LocalTokenXeroClient extends MCPXeroClient {
    // arc-forge-local-token-provider
    constructor() {
        super();
        installRateLimitProxies(this);
    }
    async authenticate() {
        const cli = process.env.ARC_FORGE_XERO_CLI;
        if (!cli) {
            throw new Error("ARC_FORGE_XERO_CLI is required for local Xero auth.");
        }
        const output = execFileSync(cli, ["auth", "token"], {
            encoding: "utf8",
            env: process.env,
            stdio: ["ignore", "pipe", "pipe"],
        });
        const token = JSON.parse(output);
        if (!token.access_token || !token.tenant_id) {
            throw new Error("Local Xero auth token response missing access_token or tenant_id.");
        }
        this.tenantId = token.tenant_id;
        rateGovernor.tenantId = token.tenant_id;
        this.setTokenSet({
            access_token: token.access_token,
            token_type: token.token_type || "Bearer",
        });
        installRateLimitProxies(this);
    }
}
export const xeroClient = local_auth
    ? new LocalTokenXeroClient()
    : bearer_token
        ? new BearerTokenXeroClient({
            bearerToken: bearer_token,
        })
        : new CustomConnectionsXeroClient({
            clientId: client_id,
            clientSecret: client_secret,
            grantType: grant_type,
        });
""",
            1,
        )
    elif "installRateLimitProxies(this);" not in patched:
        patched = patched.replace(
            """class LocalTokenXeroClient extends MCPXeroClient {
    // arc-forge-local-token-provider
""",
            """class LocalTokenXeroClient extends MCPXeroClient {
    // arc-forge-local-token-provider
    constructor() {
        super();
        installRateLimitProxies(this);
    }
""",
            1,
        )
        patched = patched.replace(
            """        this.setTokenSet({
            access_token: token.access_token,
            token_type: token.token_type || "Bearer",
        });
""",
            """        this.setTokenSet({
            access_token: token.access_token,
            token_type: token.token_type || "Bearer",
        });
        rateGovernor.tenantId = token.tenant_id;
        installRateLimitProxies(this);
""",
            1,
        )
    if GOVERNOR_MARKER in patched:
        if RATE_PROBLEM_MARKER not in patched:
            if DAY_BREAKER_MARKER in patched:
                patched = patched.replace(
                    f"    // {DAY_BREAKER_MARKER}\n",
                    f"    // {DAY_BREAKER_MARKER}\n    // {RATE_PROBLEM_MARKER}\n",
                    1,
                )
            elif HEADER_OBSERVER_MARKER in patched:
                patched = patched.replace(
                    f"    // {HEADER_OBSERVER_MARKER}\n",
                    f"    // {HEADER_OBSERVER_MARKER}\n    // {RATE_PROBLEM_MARKER}\n",
                    1,
                )
            if '"x-rate-limit-problem"' not in patched:
                patched = patched.replace(
                    '        "x-rate-limit-reset",\n',
                    '        "x-rate-limit-reset",\n        "x-rate-limit-problem",\n',
                    1,
                )
            rate_pressure_source = """function numericHeaderValue(headers, name) {
    const value = headerValue(headers, name);
    if (value === null || value === undefined || value === "") {
        return null;
    }
    const parsed = Number(value);
    return Number.isFinite(parsed) ? parsed : null;
}
function applyObservedRatePressure(headers) {
    // arc-forge-rate-problem-observer
    const problem = headerValue(headers, "x-rate-limit-problem");
    const dayRemaining = numericHeaderValue(headers, "x-daylimit-remaining");
    const minuteRemaining = numericHeaderValue(headers, "x-minlimit-remaining");
    const appMinuteRemaining = numericHeaderValue(headers, "x-appminlimit-remaining");
    if (problem || dayRemaining !== null || minuteRemaining !== null || appMinuteRemaining !== null) {
        rateGovernor.lastObservedPressure = {
            problem: problem ? String(problem) : null,
            day_remaining: dayRemaining,
            minute_remaining: minuteRemaining,
            app_minute_remaining: appMinuteRemaining,
        };
    }
    if (String(problem || "").toLowerCase() === "daylimit" || (dayRemaining !== null && dayRemaining <= 0)) {
        rateGovernor.dayCount = Math.max(rateGovernor.dayCount, rateGovernor.config.dayLimit);
    }
}
"""
            if "function numericHeaderValue" not in patched:
                patched = patched.replace("function observeRateHeaders(operation, resultOrError) {\n", rate_pressure_source + "function observeRateHeaders(operation, resultOrError) {\n", 1)
            if "applyObservedRatePressure(headers);" not in patched:
                patched = patched.replace(
                    '    const retryAfterMs = parseRetryAfterMs(headerValue(headers, "retry-after"));\n',
                    '    const retryAfterMs = parseRetryAfterMs(headerValue(headers, "retry-after"));\n    applyObservedRatePressure(headers);\n',
                    1,
                )
            if "rate_limit_problem:" not in patched:
                patched = patched.replace(
                    "            retry_after_ms: retryAfterMs,\n",
                    '            retry_after_ms: retryAfterMs,\n            rate_limit_problem: observedHeaders["x-rate-limit-problem"] || null,\n            pressure: rateGovernor.lastObservedPressure || null,\n',
                    1,
                )
        if DAY_BREAKER_MARKER not in patched:
            patched = patched.replace(
                "    // arc-forge-rate-header-observer\n",
                "    // arc-forge-rate-header-observer\n    // arc-forge-day-limit-circuit-breaker\n",
                1,
            )
            if "dayLimitUnblockStore" not in patched:
                patched = patched.replace(
                    '        maxRetrySleepMs: Number(process.env.ARC_FORGE_XERO_MAX_RETRY_SLEEP_MS || "60000"),\n',
                    '        maxRetrySleepMs: Number(process.env.ARC_FORGE_XERO_MAX_RETRY_SLEEP_MS || "60000"),\n        dayLimitUnblockStore: process.env.ARC_FORGE_XERO_DAY_LIMIT_UNBLOCK_STORE || "",\n',
                    1,
                )
            day_breaker_source = """function dayLimitResetAt(now) {
    const next = new Date(now);
    next.setUTCHours(24, 0, 0, 0);
    return next.toISOString();
}
function readDayLimitUnblock() {
    const path = rateGovernor.config.dayLimitUnblockStore;
    if (!path) {
        return null;
    }
    try {
        return JSON.parse(readFileSync(path, "utf8"));
    }
    catch (_error) {
        return null;
    }
}
function dayLimitUnblocked() {
    const payload = readDayLimitUnblock();
    return Boolean(payload?.allow_day_limit_bypass === true && payload?.day_key === rateGovernor.dayKey);
}
function dayLimitCircuitOpen(now) {
    return rateGovernor.dayCount >= rateGovernor.config.dayLimit && !dayLimitUnblocked();
}
"""
            if "function dayLimitCircuitOpen" not in patched:
                patched = patched.replace("function rateStatusPayload(operation = null) {\n", day_breaker_source + "function rateStatusPayload(operation = null) {\n", 1)
            if "circuit_breaker:" not in patched:
                patched = patched.replace(
                    "        day_count: rateGovernor.dayCount,\n",
                    "        day_count: rateGovernor.dayCount,\n        circuit_breaker: {\n            day_limit_reached: rateGovernor.dayCount >= rateGovernor.config.dayLimit,\n            day_limit_open: dayLimitCircuitOpen(now),\n            day_limit_unblocked: dayLimitUnblocked(),\n            day_limit_reset_at: dayLimitResetAt(now),\n            day_limit_unblock_store: rateGovernor.config.dayLimitUnblockStore || null,\n        },\n",
                    1,
                )
            if "ARC_FORGE_XERO_DAY_LIMIT_OPEN" not in patched:
                patched = patched.replace(
                    """    if (rateGovernor.inFlight >= rateGovernor.config.maxConcurrent ||
        rateGovernor.minuteWindow.length >= rateGovernor.config.maxPerMinute ||
        rateGovernor.appMinuteWindow.length >= rateGovernor.config.appMinuteLimit ||
        rateGovernor.dayCount >= rateGovernor.config.dayLimit) {
        const waitMs = Math.max(1000, rateGovernor.config.minuteWindowMs - (now - Math.min(...rateGovernor.minuteWindow, now)));
        setTimeout(tryStartNextRateOperation, waitMs);
        writeRateStatus(rateGovernor.queue[0]?.operation || rateGovernor.lastOperation);
        return;
    }
""",
                    """    if (dayLimitCircuitOpen(now)) {
        const error = new Error(`Xero day-limit circuit breaker is open for ${rateGovernor.dayKey}. Run xero rate unblock-day-limit only after an operator approves more calls.`);
        error.code = "ARC_FORGE_XERO_DAY_LIMIT_OPEN";
        while (rateGovernor.queue.length > 0) {
            const blocked = rateGovernor.queue.shift();
            blocked.reject(error);
        }
        writeRateStatus(rateGovernor.lastOperation);
        return;
    }
    if (rateGovernor.inFlight >= rateGovernor.config.maxConcurrent ||
        rateGovernor.minuteWindow.length >= rateGovernor.config.maxPerMinute ||
        rateGovernor.appMinuteWindow.length >= rateGovernor.config.appMinuteLimit) {
        const waitMs = Math.max(1000, rateGovernor.config.minuteWindowMs - (now - Math.min(...rateGovernor.minuteWindow, now)));
        setTimeout(tryStartNextRateOperation, waitMs);
        writeRateStatus(rateGovernor.queue[0]?.operation || rateGovernor.lastOperation);
        return;
    }
""",
                    1,
                )
            if "new Promise((resolve, reject)" not in patched:
                patched = patched.replace("new Promise((resolve) => {", "new Promise((resolve, reject) => {", 1)
                patched = patched.replace("rateGovernor.queue.push({ operation, resolve });", "rateGovernor.queue.push({ operation, resolve, reject });", 1)
        if "tenantId: null" not in patched:
            patched = patched.replace("    dayCount: 0,\n", "    dayCount: 0,\n    tenantId: null,\n", 1)
        if "lastObservedPressure: null" not in patched:
            patched = patched.replace("    lastObserved: null,\n", "    lastObserved: null,\n    lastObservedPressure: null,\n", 1)
        if "tenant_id: rateGovernor.tenantId" not in patched:
            patched = patched.replace(
                "        day_count: rateGovernor.dayCount,\n",
                "        day_count: rateGovernor.dayCount,\n        tenant_id: rateGovernor.tenantId,\n        tenant_budget_scope: rateGovernor.tenantId ? \"selected-tenant\" : \"unknown-selected-tenant\",\n",
                1,
            )
        if "last_observed_pressure: rateGovernor.lastObservedPressure" not in patched:
            patched = patched.replace(
                "        last_observed: rateGovernor.lastObserved,\n",
                "        last_observed: rateGovernor.lastObserved,\n        last_observed_pressure: rateGovernor.lastObservedPressure,\n",
                1,
            )
        if "tenant_id: rateGovernor.tenantId,\n            status_code" not in patched:
            patched = patched.replace(
                "            observed_at: new Date().toISOString(),\n",
                "            observed_at: new Date().toISOString(),\n            tenant_id: rateGovernor.tenantId,\n",
                1,
            )
        if "rateGovernor.tenantId = token.tenant_id;" not in patched:
            patched = patched.replace("        this.tenantId = token.tenant_id;\n", "        this.tenantId = token.tenant_id;\n        rateGovernor.tenantId = token.tenant_id;\n", 1)
    if PATCH_MARKER not in patched or GOVERNOR_MARKER not in patched or SHARED_GOVERNOR_MARKER not in patched or HEADER_OBSERVER_MARKER not in patched or DAY_BREAKER_MARKER not in patched or RATE_PROBLEM_MARKER not in patched:
        raise XeroMcpLocalError("failed to patch official Xero MCP client; upstream source shape changed")
    return patched


def rate_limit_store_path(value: str | None = None) -> Path:
    raw = value or os.environ.get("ARC_FORGE_XERO_RATE_LIMIT_STORE") or os.environ.get("XERO_RATE_LIMIT_STORE")
    return Path(raw).expanduser().resolve() if raw else DEFAULT_RATE_LIMIT_PATH


def shared_rate_limit_store_path(value: str | None = None) -> Path:
    raw = value or os.environ.get("ARC_FORGE_XERO_SHARED_RATE_LIMIT_STORE") or os.environ.get("XERO_SHARED_RATE_LIMIT_STORE")
    return Path(raw).expanduser().resolve() if raw else DEFAULT_SHARED_RATE_LIMIT_PATH


def rate_unblock_store_path(value: str | None = None) -> Path:
    raw = value or os.environ.get("ARC_FORGE_XERO_DAY_LIMIT_UNBLOCK_STORE") or os.environ.get("XERO_DAY_LIMIT_UNBLOCK_STORE")
    return Path(raw).expanduser().resolve() if raw else DEFAULT_RATE_UNBLOCK_PATH


def build_env(args: argparse.Namespace) -> dict[str, str]:
    env = {**os.environ}
    env["ARC_FORGE_XERO_USE_LOCAL_AUTH"] = "1"
    env["ARC_FORGE_XERO_CLI"] = str(Path(args.xero_cli).expanduser().resolve())
    if args.store:
        env["XERO_TOKEN_STORE"] = str(Path(args.store).expanduser().resolve())
    env["ARC_FORGE_XERO_RATE_LIMIT_STORE"] = str(rate_limit_store_path(args.rate_store))
    env["ARC_FORGE_XERO_SHARED_RATE_LIMIT_STORE"] = str(shared_rate_limit_store_path(args.shared_rate_store))
    env["ARC_FORGE_XERO_DAY_LIMIT_UNBLOCK_STORE"] = str(rate_unblock_store_path(args.unblock_store))
    # Avoid stock official auth branch accidentally seeing stale credentials.
    env.pop("XERO_CLIENT_BEARER_TOKEN", None)
    env.pop("XERO_CLIENT_SECRET", None)
    return env


def command_prepare(args: argparse.Namespace) -> int:
    root = cache_root(args.cache)
    target = ensure_official_package(root=root, version=args.version, force=args.force)
    print(json.dumps({"ok": True, "package_dir": str(target), "version": args.version}, indent=2))
    return 0


def command_run(args: argparse.Namespace) -> int:
    root = cache_root(args.cache)
    target = ensure_official_package(root=root, version=args.version, force=args.force)
    env = build_env(args)
    return subprocess.run(["node", str(target / "dist" / "index.js")], env=env, cwd=REPO_ROOT, check=False).returncode


def command_print_config(args: argparse.Namespace) -> int:
    root = cache_root(args.cache)
    target = package_dir(root, args.version)
    aggregator_config = {
        "command": str(MODULE_ROOT / "mcp" / "xero-mcp"),
        "args": ["run"],
    }
    if args.harness in {"claude-desktop", "cursor"}:
        config: dict[str, Any] = {"mcpServers": {"xero": aggregator_config}}
    elif args.harness == "codex":
        config = {
            "toml": "\n".join(
                [
                    "[mcp_servers.xero]",
                    f'command = "{aggregator_config["command"]}"',
                    'args = ["run"]',
                ]
            )
        }
    else:
        config = {"xero": aggregator_config}
    payload = {
        "harness": args.harness,
        "xero_mcp": config,
        "prepare_command": [str(MODULE_ROOT / "mcp" / "xero-mcp-local"), "prepare"],
        "package_dir_after_prepare": str(target),
    }
    print(json.dumps(payload, indent=2))
    return 0


def read_json_if_present(path: Path) -> dict[str, Any] | None:
    if not path.exists():
        return None
    try:
        loaded = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return loaded if isinstance(loaded, dict) else None


def inspect_cached_package(args: argparse.Namespace) -> dict[str, Any]:
    root = cache_root(args.cache)
    target = package_dir(root, args.version)
    index_path = target / "dist" / "index.js"
    client_path = target / "dist" / "clients" / "xero-client.js"
    client_source = ""
    if client_path.exists():
        client_source = client_path.read_text(encoding="utf-8", errors="replace")
    patch = {
        "local_token_provider": PATCH_MARKER in client_source,
        "rate_governor": GOVERNOR_MARKER in client_source,
        "shared_rate_budget": SHARED_GOVERNOR_MARKER in client_source,
        "header_observer": HEADER_OBSERVER_MARKER in client_source,
        "day_limit_circuit_breaker": DAY_BREAKER_MARKER in client_source,
        "rate_problem_observer": RATE_PROBLEM_MARKER in client_source,
        "tenant_status": TENANT_STATUS_MARKER in client_source and "tenant_id: rateGovernor.tenantId" in client_source,
    }
    local_cli = Path(args.xero_cli).expanduser().resolve()
    rate_store = rate_limit_store_path(args.rate_store)
    shared_rate_store = shared_rate_limit_store_path(args.shared_rate_store)
    checks = {
        "node": bool(shutil.which("node")),
        "npm": bool(shutil.which("npm")),
        "local_cli_exists": local_cli.exists(),
        "local_cli_executable": os.access(local_cli, os.X_OK),
        "package_present": target.exists(),
        "index_js": index_path.exists(),
        "client_js": client_path.exists(),
        "patch_complete": all(patch.values()),
    }
    next_steps: list[str] = []
    if not checks["node"] or not checks["npm"]:
        next_steps.append("Install Node.js and npm before preparing or running the official MCP bridge.")
    if not checks["local_cli_exists"] or not checks["local_cli_executable"]:
        next_steps.append(f"Make the local Xero CLI executable: {local_cli}")
    if not checks["package_present"] or not checks["index_js"] or not checks["client_js"] or not checks["patch_complete"]:
        next_steps.append(f"Run {MODULE_ROOT / 'mcp' / 'xero-mcp-local'} prepare")
    if args.store and not Path(args.store).expanduser().exists():
        next_steps.append(f"Run {LOCAL_XERO_CLI} auth login to create the configured token store.")
    return {
        "ok": all(checks.values()),
        "version": args.version,
        "cache": str(root),
        "package_dir": str(target),
        "checks": checks,
        "patch": patch,
        "local_cli": {
            "path": str(local_cli),
            "exists": checks["local_cli_exists"],
            "executable": checks["local_cli_executable"],
        },
        "rate_status": {
            "path": str(rate_store),
            "exists": rate_store.exists(),
            "payload": read_json_if_present(rate_store),
        },
        "shared_rate_budget": {
            "path": str(shared_rate_store),
            "exists": shared_rate_store.exists(),
            "payload": read_json_if_present(shared_rate_store),
        },
        "tools": {
            "node": shutil.which("node"),
            "npm": shutil.which("npm"),
        },
        "wrapper_sets_local_auth": True,
        "next_steps": next_steps,
    }


def command_status(args: argparse.Namespace) -> int:
    payload = inspect_cached_package(args)
    print(json.dumps(payload, indent=2))
    return 0 if payload["ok"] or not args.strict else 1


def extract_official_tool_names(target: Path) -> list[str]:
    tools_dir = target / "dist" / "tools"
    if not tools_dir.exists():
        return []
    names: set[str] = set()
    for path in tools_dir.rglob("*.js"):
        if path.name == "index.js":
            continue
        try:
            source = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        names.update(TOOL_NAME_PATTERN.findall(source))
    return sorted(names)


def classify_surface(official_tools: list[str]) -> dict[str, Any]:
    tool_set = set(official_tools)
    categories: dict[str, Any] = {}
    for category, requirement in API_SURFACE_REQUIREMENTS.items():
        official_expected = requirement["official"]
        local_expected = requirement["local"]
        official_present = [name for name in official_expected if name in tool_set]
        categories[category] = {
            "ok": bool(official_present or local_expected),
            "official_expected": official_expected,
            "official_present": official_present,
            "official_missing": [name for name in official_expected if name not in tool_set],
            "local_companion": local_expected,
            "covered_by": ["official-mcp"] if official_present else [] + (["local-cli"] if local_expected else []),
        }
        if official_present and local_expected:
            categories[category]["covered_by"] = ["official-mcp", "local-cli"]
    return categories


def classify_mutation_safety(official_tools: list[str]) -> dict[str, Any]:
    mutating = [name for name in official_tools if name.startswith(MUTATING_TOOL_PREFIXES)]
    items = []
    for name in mutating:
        alternatives = LOCAL_PREFLIGHT_ALTERNATIVES.get(name, [])
        items.append(
            {
                "tool": name,
                "requires_operator_preflight_route": True,
                "local_preflight_alternatives": alternatives,
                "covered_by_local_preflight_helper": bool(alternatives),
            }
        )
    uncovered = [item["tool"] for item in items if not item["covered_by_local_preflight_helper"]]
    return {
        "ok": True,
        "mutating_tool_count": len(items),
        "covered_by_local_preflight_count": len(items) - len(uncovered),
        "uncovered_mutating_tools": uncovered,
        "items": items,
        "policy": {
            "official_mcp_full_power": True,
            "recommended_write_route": "Use xero-workflows or CLI helpers with dry-run/audit preflight reports for accounting mutations.",
            "reason": "Official MCP write tools preserve Xero API power but do not enforce local finance-rule preflight by themselves.",
        },
    }


def build_surface_report(args: argparse.Namespace) -> dict[str, Any]:
    root = cache_root(args.cache)
    target = package_dir(root, args.version)
    official_tools = extract_official_tool_names(target)
    categories = classify_surface(official_tools)
    missing = [name for name, item in categories.items() if not item["ok"]]
    official_only_gaps = [
        name
        for name, item in categories.items()
        if not item["official_present"] and item["local_companion"]
    ]
    return {
        "ok": target.exists() and not missing,
        "version": args.version,
        "package_dir": str(target),
        "package_present": target.exists(),
        "official_tool_count": len(official_tools),
        "official_tools": official_tools,
        "required_category_count": len(categories),
        "missing_categories": missing,
        "official_only_gaps_covered_by_local_cli": official_only_gaps,
        "mutation_safety": classify_mutation_safety(official_tools),
        "categories": categories,
        "notes": [
            "This is a local package inventory; it does not start MCP or call Xero.",
            "Local CLI companion coverage includes dry-run/audit/snapshot/pre-work helpers that are intentionally outside the official MCP package.",
        ],
    }


def command_surface(args: argparse.Namespace) -> int:
    payload = build_surface_report(args)
    print(json.dumps(payload, indent=2))
    return 0 if payload["ok"] or not args.strict else 1


def mcp_request(request_id: int, method: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
    payload: dict[str, Any] = {"jsonrpc": "2.0", "id": request_id, "method": method}
    if params is not None:
        payload["params"] = params
    return payload


def mcp_initialized_notification() -> dict[str, Any]:
    return {"jsonrpc": "2.0", "method": "notifications/initialized", "params": {}}


def extract_protocol_tool_names(response: dict[str, Any]) -> list[str]:
    tools = response.get("result", {}).get("tools", [])
    if not isinstance(tools, list):
        return []
    names = [item.get("name") for item in tools if isinstance(item, dict) and isinstance(item.get("name"), str)]
    return sorted(names)


def extract_protocol_tool_lookup(response: dict[str, Any]) -> dict[str, dict[str, Any]]:
    tools = response.get("result", {}).get("tools", [])
    if not isinstance(tools, list):
        return {}
    return {
        item["name"]: item
        for item in tools
        if isinstance(item, dict) and isinstance(item.get("name"), str)
    }


def protocol_required_tools() -> list[str]:
    names: set[str] = set()
    for requirement in API_SURFACE_REQUIREMENTS.values():
        names.update(requirement["official"])
    return sorted(names)


def stop_mcp_process(process: subprocess.Popen[str]) -> None:
    if process.stdin is not None:
        try:
            process.stdin.close()
        except OSError:
            pass
    if process.poll() is None:
        process.terminate()
        try:
            process.wait(timeout=2)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=2)


def start_pipe_reader(name: str, stream: Any, events: "queue.Queue[tuple[str, str | None]]") -> threading.Thread:
    def reader() -> None:
        try:
            for line in stream:
                events.put((name, line.rstrip("\n")))
        finally:
            events.put((name, None))

    thread = threading.Thread(target=reader, daemon=True)
    thread.start()
    return thread


def write_mcp_message(process: subprocess.Popen[str], payload: dict[str, Any]) -> None:
    if process.stdin is None:
        raise XeroMcpLocalError("MCP subprocess stdin is unavailable.")
    process.stdin.write(json.dumps(payload, separators=(",", ":")) + "\n")
    process.stdin.flush()


def wait_for_mcp_response(
    process: subprocess.Popen[str],
    events: "queue.Queue[tuple[str, str | None]]",
    request_id: int,
    *,
    deadline: float,
    transcript: list[dict[str, Any]],
    stderr_lines: list[str],
) -> dict[str, Any]:
    while time.monotonic() < deadline:
        if process.poll() is not None and events.empty():
            raise XeroMcpLocalError(f"MCP subprocess exited before response id {request_id} (code {process.returncode}).")
        try:
            source, line = events.get(timeout=min(0.25, max(0.01, deadline - time.monotonic())))
        except queue.Empty:
            continue
        if line is None:
            continue
        if source == "stderr":
            stderr_lines.append(line)
            continue
        try:
            message = json.loads(line)
        except json.JSONDecodeError:
            transcript.append({"stream": "stdout", "json": False, "line": line[:500]})
            continue
        transcript.append({"stream": "stdout", "json": True, "id": message.get("id"), "method": message.get("method")})
        if message.get("id") == request_id:
            if "error" in message:
                raise XeroMcpLocalError(f"MCP response id {request_id} returned error: {message['error']}")
            return message
    raise XeroMcpLocalError(f"timed out waiting for MCP response id {request_id}")


def run_protocol_smoke(args: argparse.Namespace) -> dict[str, Any]:
    root = cache_root(args.cache)
    target = ensure_official_package(root=root, version=args.version, force=args.force)
    process = subprocess.Popen(
        ["node", str(target / "dist" / "index.js")],
        cwd=REPO_ROOT,
        env=build_env(args),
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        bufsize=1,
    )
    events: "queue.Queue[tuple[str, str | None]]" = queue.Queue()
    if process.stdout is not None:
        start_pipe_reader("stdout", process.stdout, events)
    if process.stderr is not None:
        start_pipe_reader("stderr", process.stderr, events)

    transcript: list[dict[str, Any]] = []
    stderr_lines: list[str] = []
    deadline = time.monotonic() + args.timeout
    try:
        write_mcp_message(
            process,
            mcp_request(
                1,
                "initialize",
                {
                    "protocolVersion": "2024-11-05",
                    "capabilities": {},
                    "clientInfo": {"name": "xero-mcp-local-smoke", "version": "0.1.0"},
                },
            ),
        )
        initialize = wait_for_mcp_response(process, events, 1, deadline=deadline, transcript=transcript, stderr_lines=stderr_lines)
        write_mcp_message(process, mcp_initialized_notification())
        write_mcp_message(process, mcp_request(2, "tools/list", {}))
        tools_response = wait_for_mcp_response(process, events, 2, deadline=deadline, transcript=transcript, stderr_lines=stderr_lines)
    finally:
        stop_mcp_process(process)

    tool_names = extract_protocol_tool_names(tools_response)
    required = protocol_required_tools()
    missing_required = [name for name in required if name not in set(tool_names)]
    payload: dict[str, Any] = {
        "ok": bool(tool_names) and not missing_required,
        "mode": "mcp-protocol-smoke",
        "version": args.version,
        "package_dir": str(target),
        "initialized": "result" in initialize,
        "tool_count": len(tool_names),
        "missing_required_protocol_tools": missing_required,
        "required_protocol_tool_count": len(required),
        "stderr_tail": stderr_lines[-10:],
        "transcript": transcript[-10:],
        "notes": [
            "This starts the patched official MCP server and performs initialize plus tools/list only.",
            "It does not invoke any Xero API tool and does not require a Xero OAuth token unless upstream changes authentication to happen at startup.",
        ],
    }
    if args.include_tools:
        payload["tools"] = tool_names
    return payload


def command_protocol_smoke(args: argparse.Namespace) -> int:
    payload = run_protocol_smoke(args)
    print(json.dumps(payload, indent=2))
    return 0 if payload["ok"] or not args.strict else 1


def summarize_tool_call_response(response: dict[str, Any]) -> dict[str, Any]:
    result = response.get("result") if isinstance(response.get("result"), dict) else {}
    content = result.get("content") if isinstance(result.get("content"), list) else []
    text_items = [item.get("text") for item in content if isinstance(item, dict) and isinstance(item.get("text"), str)]
    return {
        "is_error": bool(result.get("isError")),
        "content_count": len(content),
        "text_item_count": len(text_items),
        "first_text_preview": redact_value(text_items[0])[:300] if text_items else None,
    }


def run_live_tool_smoke(args: argparse.Namespace) -> dict[str, Any]:
    root = cache_root(args.cache)
    target = ensure_official_package(root=root, version=args.version, force=args.force)
    process = subprocess.Popen(
        ["node", str(target / "dist" / "index.js")],
        cwd=REPO_ROOT,
        env=build_env(args),
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        bufsize=1,
    )
    events: "queue.Queue[tuple[str, str | None]]" = queue.Queue()
    if process.stdout is not None:
        start_pipe_reader("stdout", process.stdout, events)
    if process.stderr is not None:
        start_pipe_reader("stderr", process.stderr, events)

    transcript: list[dict[str, Any]] = []
    stderr_lines: list[str] = []
    deadline = time.monotonic() + args.timeout
    tool_name = args.tool
    arguments = parse_json_if_value(args.arguments, label="--arguments") if args.arguments else {}
    if not isinstance(arguments, dict):
        raise XeroMcpLocalError("--arguments must be a JSON object")

    try:
        write_mcp_message(
            process,
            mcp_request(
                1,
                "initialize",
                {
                    "protocolVersion": "2024-11-05",
                    "capabilities": {},
                    "clientInfo": {"name": "xero-mcp-local-live-smoke", "version": "0.1.0"},
                },
            ),
        )
        initialize = wait_for_mcp_response(process, events, 1, deadline=deadline, transcript=transcript, stderr_lines=stderr_lines)
        write_mcp_message(process, mcp_initialized_notification())
        write_mcp_message(process, mcp_request(2, "tools/list", {}))
        tools_response = wait_for_mcp_response(process, events, 2, deadline=deadline, transcript=transcript, stderr_lines=stderr_lines)
        tool_lookup = extract_protocol_tool_lookup(tools_response)
        if tool_name not in tool_lookup:
            raise XeroMcpLocalError(f"MCP tool is not available: {tool_name}")
        write_mcp_message(process, mcp_request(3, "tools/call", {"name": tool_name, "arguments": arguments}))
        call_response = wait_for_mcp_response(process, events, 3, deadline=deadline, transcript=transcript, stderr_lines=stderr_lines)
    finally:
        stop_mcp_process(process)

    call_summary = summarize_tool_call_response(call_response)
    payload = {
        "ok": bool(initialize.get("result")) and not call_summary["is_error"] and call_summary["content_count"] > 0,
        "mode": "mcp-live-tool-smoke",
        "version": args.version,
        "package_dir": str(target),
        "tool": tool_name,
        "initialized": "result" in initialize,
        "tool_available": True,
        "call": call_summary,
        "stderr_tail": stderr_lines[-10:],
        "transcript": transcript[-10:],
        "live_api": True,
        "notes": [
            "This starts the patched official MCP server and invokes one read-only MCP tool.",
            "It requires a configured local OAuth token store and active tenant, and it consumes Xero API budget.",
        ],
    }
    return payload


def command_live_smoke(args: argparse.Namespace) -> int:
    payload = run_live_tool_smoke(args)
    print(json.dumps(payload, indent=2))
    return 0 if payload["ok"] or not args.strict else 1


def command_self_test(_args: argparse.Namespace) -> int:
    sample = """import axios from "axios";
import dotenv from "dotenv";
const client_id = process.env.XERO_CLIENT_ID;
const client_secret = process.env.XERO_CLIENT_SECRET;
const bearer_token = process.env.XERO_CLIENT_BEARER_TOKEN;
const grant_type = "client_credentials";
if (!bearer_token && (!client_id || !client_secret)) {
    throw Error("Environment Variables not set - please check your .env file");
}
class BearerTokenXeroClient extends MCPXeroClient {
    bearerToken;
    constructor(config) {
        super();
        this.bearerToken = config.bearerToken;
    }
    async authenticate() {
        this.setTokenSet({
            access_token: this.bearerToken,
        });
        await this.updateTenants();
    }
}
export const xeroClient = bearer_token
    ? new BearerTokenXeroClient({
        bearerToken: bearer_token,
    })
    : new CustomConnectionsXeroClient({
        clientId: client_id,
        clientSecret: client_secret,
        grantType: grant_type,
    });
"""
    patched = patch_client_source(sample)
    assert PATCH_MARKER in patched
    assert GOVERNOR_MARKER in patched
    assert SHARED_GOVERNOR_MARKER in patched
    assert HEADER_OBSERVER_MARKER in patched
    assert DAY_BREAKER_MARKER in patched
    assert RATE_PROBLEM_MARKER in patched
    assert 'execFileSync(cli, ["auth", "token"]' in patched
    assert "installRateLimitProxies" in patched
    assert "parseRetryAfterMs" in patched
    assert "observeRateHeaders" in patched
    assert "retry_after_ms" in patched
    assert "x-rate-limit-problem" in patched
    assert "applyObservedRatePressure" in patched
    assert "tryAcquireSharedRateBudget" in patched
    assert "ARC_FORGE_XERO_SHARED_RATE_LIMIT_STORE" in patched
    assert "ARC_FORGE_XERO_DAY_LIMIT_OPEN" in patched
    assert "local_auth" in patched
    print("xero mcp local self-test passed.")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="xero-mcp-local", description="Run official Xero MCP with local Arc Forge OAuth tokens")
    parser.add_argument("--version", default=DEFAULT_VERSION, help="Official @xeroapi/xero-mcp-server version")
    parser.add_argument("--cache", help="Runtime cache directory")
    parser.add_argument("--xero-cli", default=str(LOCAL_XERO_CLI), help="Path to local xero CLI")
    parser.add_argument("--store", help="Override XERO_TOKEN_STORE for local auth")
    parser.add_argument("--rate-store", help="Override rate-limit status store path")
    parser.add_argument("--shared-rate-store", help="Override shared MCP rate-budget store path")
    parser.add_argument("--unblock-store", help="Override day-limit unblock store path")
    parser.add_argument("--force", action="store_true", help="Re-download and re-patch official package")
    sub = parser.add_subparsers(dest="command", required=True)

    prepare = sub.add_parser("prepare", help="Download/cache and patch official MCP package")
    prepare.set_defaults(func=command_prepare)
    run_cmd = sub.add_parser("run", help="Run patched official MCP over stdio")
    run_cmd.set_defaults(func=command_run)
    config = sub.add_parser("print-config", help="Print MCP config snippet")
    config.add_argument("--harness", choices=["generic", "claude-desktop", "cursor", "codex"], default="generic")
    config.set_defaults(func=command_print_config)
    status = sub.add_parser("status", help="Inspect local MCP package/cache readiness without network")
    status.add_argument("--strict", action="store_true", help="Exit non-zero unless the cached package is ready to run")
    status.set_defaults(func=command_status)
    surface = sub.add_parser("surface", help="Inventory official MCP tools and local companion API coverage")
    surface.add_argument("--strict", action="store_true", help="Exit non-zero unless every required API category has official or local companion coverage")
    surface.set_defaults(func=command_surface)
    protocol_smoke = sub.add_parser("protocol-smoke", help="Start MCP over stdio and list tools without invoking Xero APIs")
    protocol_smoke.add_argument("--strict", action="store_true", help="Exit non-zero unless all expected official protocol tools are listed")
    protocol_smoke.add_argument("--timeout", type=float, default=15.0, help="Seconds to wait for MCP initialize and tools/list")
    protocol_smoke.add_argument("--include-tools", action="store_true", help="Include full tool name list in JSON output")
    protocol_smoke.set_defaults(func=command_protocol_smoke)
    live_smoke = sub.add_parser("live-smoke", help="Invoke one read-only MCP tool using local OAuth state")
    live_smoke.add_argument("--strict", action="store_true", help="Exit non-zero unless the live MCP tool call succeeds")
    live_smoke.add_argument("--timeout", type=float, default=30.0, help="Seconds to wait for MCP initialize, tools/list, and tools/call")
    live_smoke.add_argument("--tool", default="list-organisation-details", help="Read-only MCP tool to invoke")
    live_smoke.add_argument("--arguments", help="JSON object of tool arguments")
    live_smoke.set_defaults(func=command_live_smoke)
    self_test = sub.add_parser("self-test", help="Run patcher self-test")
    self_test.set_defaults(func=command_self_test)
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return int(args.func(args))
    except (XeroMcpLocalError, AssertionError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
