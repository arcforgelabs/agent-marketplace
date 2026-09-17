#!/usr/bin/env python3
"""CDP-only Xero reconciliation companion scaffold.

This module deliberately does not launch a browser, automate login, retrieve
MFA, or bypass browser security checks. It only accepts an explicit
already-authenticated CDP endpoint and produces bounded dry-run/preflight
artifacts for the future Reconcile-tab finalizer.
"""

from __future__ import annotations

import argparse
import asyncio
import html
import importlib.util
import json
import os
import re
import shutil
import stat
import subprocess
import sys
import time
import urllib.parse
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any


DEFAULT_RECON_DIR = Path.home() / ".config" / "arc-forge-tools" / "xero" / "reconciliation"
SUPPORTED_ENDPOINT_SCHEMES = {"http", "https", "ws", "wss"}
MONEY_PATTERN = re.compile(r"(?<![A-Za-z0-9])(?:[$£€])?\s*-?\d{1,3}(?:,\d{3})*(?:\.\d{2})|-?\d+\.\d{2}")
ROW_SCOPED_APPLY_ACTIONS = {"accept-suggestion", "match-existing", "open-match-dialog"}
DIALOG_APPLY_ACTIONS = {"search-transaction", "select-transaction", "confirm-match"}
APPLY_ACTIONS = ROW_SCOPED_APPLY_ACTIONS | DIALOG_APPLY_ACTIONS
RECONCILE_PLAN_ACTIONS = {"create", "transfer", "match", "accept-suggestion"}
APPLY_ENGINE = Path(__file__).resolve().parents[1] / "reconciliation" / "apply-engine" / "xero-reconcile-apply.js"


class ReconciliationError(RuntimeError):
    """User-facing reconciliation error."""


def utc_seconds() -> int:
    return int(time.time())


def optional_dependency_status() -> dict[str, Any]:
    websocket_available = importlib.util.find_spec("websockets") is not None
    return {
        "websockets": websocket_available,
        "live_cdp_capture": websocket_available,
        "live_cdp_apply": websocket_available,
        "install_hint": None if websocket_available else "Install Python package `websockets` for live CDP capture/apply.",
    }


def node_playwright_available() -> bool:
    node = os.environ.get("NODE") or shutil.which("node")
    if not node:
        return False
    script = """
const path = require('path');
const candidates = [
  process.env.PLAYWRIGHT_MODULE,
  'playwright',
  path.join(process.env.HOME || '', 'repos', 'openclaw', 'node_modules', 'playwright')
].filter(Boolean);
for (const candidate of candidates) {
  try { require(candidate); process.exit(0); } catch {}
}
process.exit(1);
"""
    try:
        return subprocess.run([node, "-e", script], capture_output=True, text=True, timeout=5).returncode == 0
    except Exception:
        return False


def recon_dir(value: str | None = None) -> Path:
    raw = value or os.environ.get("ARC_FORGE_XERO_RECON_DIR") or os.environ.get("XERO_RECON_DIR")
    return Path(raw).expanduser().resolve() if raw else DEFAULT_RECON_DIR


def write_json(payload: Any) -> None:
    print(json.dumps(payload, indent=2, sort_keys=False))


def write_json_file(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_suffix(path.suffix + ".tmp")
    with tmp_path.open("w", encoding="utf-8") as handle:
        json.dump(payload, handle, indent=2, sort_keys=False)
        handle.write("\n")
    os.chmod(tmp_path, stat.S_IRUSR | stat.S_IWUSR)
    tmp_path.replace(path)
    os.chmod(path, stat.S_IRUSR | stat.S_IWUSR)


def load_json_file(path: Path) -> Any:
    try:
        with path.open("r", encoding="utf-8") as handle:
            return json.load(handle)
    except json.JSONDecodeError as exc:
        raise ReconciliationError(f"Invalid JSON: {path}: {exc}") from exc


def validate_cdp_endpoint(value: str | None) -> str:
    endpoint = str(value or "").strip()
    if not endpoint:
        raise ReconciliationError("A user-provided already-authenticated CDP endpoint is required. Pass --cdp-endpoint.")
    parsed = urllib.parse.urlparse(endpoint)
    if parsed.scheme not in SUPPORTED_ENDPOINT_SCHEMES or not parsed.netloc:
        raise ReconciliationError("CDP endpoint must be an http(s) or ws(s) URL.")
    return endpoint


def redact_endpoint(endpoint: str) -> str:
    parsed = urllib.parse.urlparse(endpoint)
    netloc = parsed.hostname or ""
    if parsed.port:
        netloc = f"{netloc}:{parsed.port}"
    return urllib.parse.urlunparse((parsed.scheme, netloc, parsed.path, "", "", ""))


def redact_browser_url(value: str | None) -> str | None:
    if not value:
        return None
    parsed = urllib.parse.urlparse(value)
    if not parsed.scheme or not parsed.netloc:
        return value.split("?", 1)[0].split("#", 1)[0]
    return urllib.parse.urlunparse((parsed.scheme, parsed.netloc, parsed.path, "", "", ""))


def redact_report_value(value: Any, *, endpoint: str | None = None) -> Any:
    if isinstance(value, dict):
        return {key: redact_report_value(item, endpoint=endpoint) for key, item in value.items()}
    if isinstance(value, list):
        return [redact_report_value(item, endpoint=endpoint) for item in value]
    if not isinstance(value, str):
        return value
    redacted = value
    if endpoint:
        redacted = redacted.replace(endpoint, redact_endpoint(endpoint))

    def _redact_url(match: re.Match[str]) -> str:
        return str(redact_browser_url(match.group(0)) or "")

    return re.sub(r"\b(?:https?|wss?)://[^\s'\"<>]+", _redact_url, redacted)


def cdp_http_base(endpoint: str) -> str:
    parsed = urllib.parse.urlparse(validate_cdp_endpoint(endpoint))
    scheme = {"ws": "http", "wss": "https"}.get(parsed.scheme, parsed.scheme)
    return urllib.parse.urlunparse((scheme, parsed.netloc, "", "", "", ""))


def cdp_json_url(endpoint: str, path: str) -> str:
    path = "/" + path.strip("/")
    return cdp_http_base(endpoint).rstrip("/") + path


def http_get_json(url: str) -> Any:
    request = urllib.request.Request(url, headers={"Accept": "application/json"}, method="GET")
    try:
        with urllib.request.urlopen(request, timeout=5) as response:
            raw = response.read().decode("utf-8")
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise ReconciliationError(f"CDP HTTP {exc.code}: {redact_browser_url(url)}: {detail[:200]}") from exc
    except urllib.error.URLError as exc:
        raise ReconciliationError(f"CDP request failed: {redact_browser_url(url)}: {exc}") from exc
    try:
        return json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ReconciliationError(f"CDP response was not JSON: {redact_browser_url(url)}") from exc


def fetch_cdp_targets(endpoint: str) -> list[dict[str, Any]]:
    payload = http_get_json(cdp_json_url(endpoint, "/json/list"))
    if not isinstance(payload, list):
        raise ReconciliationError("CDP /json/list response was not a list.")
    return [item for item in payload if isinstance(item, dict)]


def is_xero_target(target: dict[str, Any]) -> bool:
    url = str(target.get("url") or "").lower()
    title = str(target.get("title") or "").lower()
    return "xero.com" in url or "xero" in title


def is_reconcile_candidate(target: dict[str, Any]) -> bool:
    haystack = " ".join([str(target.get("url") or ""), str(target.get("title") or "")]).lower()
    return is_xero_target(target) and any(term in haystack for term in ("reconcile", "reconciliation", "cash coding", "bank account"))


def summarize_cdp_target(target: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": target.get("id"),
        "type": target.get("type"),
        "title": target.get("title"),
        "url": redact_browser_url(str(target.get("url") or "")),
        "xero": is_xero_target(target),
        "reconcile_candidate": is_reconcile_candidate(target),
    }


def build_inspect_report(*, endpoint: str, targets: list[dict[str, Any]]) -> dict[str, Any]:
    pages = [summarize_cdp_target(item) for item in targets]
    xero_pages = [item for item in pages if item["xero"]]
    reconcile_candidates = [item for item in pages if item["reconcile_candidate"]]
    return {
        "ok": True,
        "mode": "cdp-inspect",
        "generated_at": utc_seconds(),
        "cdp_endpoint": redact_endpoint(endpoint),
        "connected": True,
        "login_automation": False,
        "credential_collection": False,
        "target_count": len(pages),
        "xero_target_count": len(xero_pages),
        "reconcile_candidate_count": len(reconcile_candidates),
        "targets": pages,
        "xero_targets": xero_pages,
        "reconcile_candidates": reconcile_candidates,
    }


def target_websocket_url(endpoint: str, *, target_id: str | None = None) -> tuple[str, dict[str, Any] | None]:
    parsed = urllib.parse.urlparse(validate_cdp_endpoint(endpoint))
    if parsed.scheme in {"ws", "wss"} and "/devtools/page/" in parsed.path:
        return endpoint, None
    targets = fetch_cdp_targets(endpoint)
    candidates = [item for item in targets if item.get("webSocketDebuggerUrl")]
    if target_id:
        candidates = [item for item in candidates if str(item.get("id") or "") == target_id]
        if not candidates:
            raise ReconciliationError(f"CDP target id not found or has no debugger URL: {target_id}")
    else:
        reconcile = [item for item in candidates if is_reconcile_candidate(item)]
        xero = [item for item in candidates if is_xero_target(item)]
        pages = [item for item in candidates if item.get("type") == "page"]
        candidates = reconcile or xero or pages
    if not candidates:
        raise ReconciliationError("No page target with a debugger URL was found. Open the Xero Reconcile tab in the supplied browser session.")
    target = candidates[0]
    return str(target["webSocketDebuggerUrl"]), target


async def cdp_evaluate(expression: str, websocket_url: str, *, timeout_seconds: int = 10) -> Any:
    try:
        import websockets
    except ImportError as exc:  # pragma: no cover - depends on optional local package.
        raise ReconciliationError("Live CDP capture requires the Python `websockets` package.") from exc
    request_id = 1
    payload = {
        "id": request_id,
        "method": "Runtime.evaluate",
        "params": {
            "expression": expression,
            "returnByValue": True,
            "awaitPromise": True,
        },
    }
    try:
        async with websockets.connect(websocket_url, open_timeout=timeout_seconds) as websocket:
            await websocket.send(json.dumps(payload))
            deadline = time.monotonic() + timeout_seconds
            while time.monotonic() < deadline:
                raw = await asyncio.wait_for(websocket.recv(), timeout=max(0.1, deadline - time.monotonic()))
                message = json.loads(raw)
                if message.get("id") != request_id:
                    continue
                if message.get("error"):
                    raise ReconciliationError(f"CDP evaluation failed: {message['error']}")
                return message.get("result", {}).get("result", {}).get("value")
    except ReconciliationError:
        raise
    except Exception as exc:  # noqa: BLE001 - normalize websocket/runtime errors for CLI output.
        raise ReconciliationError(f"CDP websocket evaluation failed: {type(exc).__name__}: {exc}") from exc
    raise ReconciliationError("Timed out waiting for CDP evaluation result.")


def capture_visible_text(websocket_url: str, *, timeout_seconds: int = 10) -> dict[str, Any]:
    """Return structured capture data from the live Reconcile page.

    Keys:
    - ``modern_lines``: list of per-line objects read by ``data-testid`` from
      the live React MFE statement-line containers. Preferred capture path when
      present. Each object has keys ``posted_date``, ``notes``,
      ``analysis_code``, ``amount_spent``, ``amount_received``. The header /
      template row is excluded by requiring at least one of ``amount-spent`` or
      ``amount-received`` to be present in the container.
    - ``selector_text``: the existing selector-based text blob (double-newline
      joined) — drives the modern (non-ExtJS) UI degradation path.
    - ``grid_innertext``: raw ``innerText`` of the best candidate grid
      container — the blob fallback when no structured rows are available.
    - ``grid_rows``: a list of per-row cell-string arrays read in DOM column
      order, INCLUDING empty strings for empty cells. This preserves the
      ``date | description | reference | spent | received`` column positions so
      the Python side can map a money value to spent (negative) vs received
      (positive) unambiguously. Empty when the grid is not the classic ExtJS
      structure.
    - ``selector_row_count``: number of distinct selector-text blocks found.
    """
    expression = """
(() => {
  // Modern React MFE capture: read statement lines by data-testid.
  // Each [class*="statement-line"] container that has an amount-spent OR
  // amount-received child is a real line; containers without either are the
  // header / template row and are skipped.
  const fieldText = (container, testid) => {
    const el = container.querySelector('[data-testid="' + testid + '"]');
    return el ? (el.innerText || el.textContent || '').replace(/\\s+/g, ' ').trim() : '';
  };
  const modernLines = [];
  const lineContainers = Array.from(document.querySelectorAll('[class*="statement-line"]')).slice(0, 200);
  for (const container of lineContainers) {
    const amountSpent    = fieldText(container, 'amount-spent');
    const amountReceived = fieldText(container, 'amount-received');
    // Skip header/template: neither amount field is present as a child element.
    if (!container.querySelector('[data-testid="amount-spent"]') &&
        !container.querySelector('[data-testid="amount-received"]')) {
      continue;
    }
    modernLines.push({
      statement_line_id: container.getAttribute('data-statementlineid') || (container.closest('[data-statementlineid]') ? container.closest('[data-statementlineid]').getAttribute('data-statementlineid') : '') || '',
      posted_date:   fieldText(container, 'posted-date'),
      notes:         fieldText(container, 'notes'),
      analysis_code: fieldText(container, 'analysis-code'),
      amount_spent:  amountSpent,
      amount_received: amountReceived
    });
  }
  const selectors = [
    '[data-automationid*="statement" i]',
    '[data-testid*="statement" i]',
    '[class*="statement" i]',
    '[class*="reconcile" i]',
    'main',
    'body'
  ];
  const parts = [];
  let selectorRowCount = 0;
  for (const selector of selectors) {
    const found = Array.from(document.querySelectorAll(selector)).slice(0, 50);
    for (const element of found) {
      const text = (element.innerText || '').trim();
      if (text && !parts.includes(text)) {
        parts.push(text);
        selectorRowCount++;
      }
    }
    if (parts.length) {
      break;
    }
  }
  // Classic ExtJS BankRec grid fallback: capture the raw innerText of the
  // best candidate grid container so the Python side can parse it directly.
  const gridSelectors = [
    '.x-grid-body',
    '.x-grid-view',
    '[id*="gridview"]',
    '[class*="grid-body"]',
    '[class*="BankRec"]',
    'table.x-grid-table',
    'table'
  ];
  let gridInnertext = '';
  for (const gs of gridSelectors) {
    const el = document.querySelector(gs);
    if (el) {
      gridInnertext = (el.innerText || '').trim();
      if (gridInnertext) break;
    }
  }
  // Column-structured row capture: iterate grid ROWS and read each row's CELLS
  // in DOM column order, emitting '' for empty cells so spent/received column
  // positions are preserved instead of collapsing.
  const rowSelectors = [
    'tr.x-grid-row',
    '.x-grid-row',
    '[class*="grid-row"]',
    'table.x-grid-table tr',
    'tr'
  ];
  const cellSelectors = [
    'td.x-grid-cell',
    '.x-grid-cell',
    '[class*="grid-cell"]',
    'td',
    'th'
  ];
  const cellText = (cell) => {
    const inner = cell.querySelector('.x-grid-cell-inner');
    const value = ((inner || cell).innerText || (inner || cell).textContent || '');
    return value.replace(/\\s+/g, ' ').trim();
  };
  let gridRows = [];
  for (const rs of rowSelectors) {
    const rowEls = Array.from(document.querySelectorAll(rs)).slice(0, 1500);
    if (!rowEls.length) continue;
    const collected = [];
    for (const rowEl of rowEls) {
      let cells = [];
      for (const cs of cellSelectors) {
        const found = Array.from(rowEl.querySelectorAll(cs));
        if (found.length) { cells = found; break; }
      }
      if (!cells.length) continue;
      collected.push(cells.map(cellText));
    }
    // Require at least one row with 2+ cells to consider this a real grid.
    if (collected.some((row) => row.length >= 2)) {
      gridRows = collected;
      break;
    }
  }
  // BankRec header balances: "<amt> Statement Balance" / "<amt> Balance in Xero"
  // (parenthesised = negative). When fully reconciled Xero hides the second
  // figure and shows the Reconciled badge instead.
  const bodyText = (document.body.innerText || '').replace(/\\s+/g, ' ');
  const balMatch = bodyText.match(/(\\(?-?[\\d,]+\\.\\d\\d\\)?) Statement Balance/);
  const xeroMatch = bodyText.match(/(\\(?-?[\\d,]+\\.\\d\\d\\)?) Balance in Xero/);
  const reconciledBadge = / Statement Balance Reconciled /.test(' ' + bodyText + ' ');
  return {
    modern_lines: modernLines,
    selector_text: parts.join('\\n\\n'),
    grid_innertext: gridInnertext,
    grid_rows: gridRows,
    selector_row_count: selectorRowCount,
    statement_balance: balMatch ? balMatch[1] : null,
    xero_balance: xeroMatch ? xeroMatch[1] : null,
    reconciled_badge: reconciledBadge
  };
})()
"""
    value = asyncio.run(cdp_evaluate(expression, websocket_url, timeout_seconds=timeout_seconds))
    if isinstance(value, dict):
        value.setdefault("modern_lines", [])
        value.setdefault("grid_rows", [])
        return value
    # Older CDP environments may return a plain string (scalar value coercion).
    return {"modern_lines": [], "selector_text": str(value or ""), "grid_innertext": "", "grid_rows": [], "selector_row_count": 0}


def parse_modern_lines(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Parse modern React MFE statement-line objects into statement-line records.

    ``rows`` is a list of plain objects produced by the ``modern_lines`` path in
    ``capture_visible_text``.  Each object has string fields ``posted_date``,
    ``notes``, ``analysis_code``, ``amount_spent``, and ``amount_received``
    (empty string when the field is unpopulated on that line).

    Sign rules — unambiguous, no column-order inference needed:
    - ``amount_received`` populated, ``amount_spent`` empty
      → ``amount = +received``, ``sign_confidence: "high"``.
    - ``amount_spent`` populated, ``amount_received`` empty
      → ``amount = -spent``, ``sign_confidence: "high"``.
    - both populated (transfer-style)
      → ``amount = received - spent``, ``sign_confidence: "high"``.
    - neither populated (unexpected header / template leakage)
      → ``amount = None``.

    ``text`` is a normalized join of ``posted_date``, ``notes``, and
    ``analysis_code``.  ``amount`` is the only monetary key — ``spent`` and
    ``received`` are never surfaced in the record.

    Records use the shared contract: ``index``, ``text``, ``amount`` (signed),
    ``source``, ``sign_confidence``.
    """
    records: list[dict[str, Any]] = []
    for raw in rows:
        spent_str = re.sub(r"\s+", " ", html.unescape(str(raw.get("amount_spent") or "")).strip())
        received_str = re.sub(r"\s+", " ", html.unescape(str(raw.get("amount_received") or "")).strip())
        spent = parse_money(spent_str)
        received = parse_money(received_str)

        amount: float | None
        if received is not None and spent is not None:
            # Both populated (transfer-style): received minus spent.
            amount = round(abs(received) - abs(spent), 2)
        elif received is not None:
            amount = abs(received)
        elif spent is not None:
            amount = -abs(spent)
        else:
            amount = None

        date_part = re.sub(r"\s+", " ", html.unescape(str(raw.get("posted_date") or "")).strip())
        notes_part = re.sub(r"\s+", " ", html.unescape(str(raw.get("notes") or "")).strip())
        code_part = re.sub(r"\s+", " ", html.unescape(str(raw.get("analysis_code") or "")).strip())
        text_parts = [part for part in (date_part, notes_part, code_part) if part]
        text = re.sub(r"\s+", " ", " ".join(text_parts)).strip()

        records.append({
            "index": len(records) + 1,
            "statement_line_id": re.sub(r"\s+", " ", html.unescape(str(raw.get("statement_line_id") or "")).strip()) or None,
            "text": text,
            "amount": amount,
            "source": "modern-testid",
            "sign_confidence": "high",
        })
    return records


def build_capture_report(*, endpoint: str, target: dict[str, Any] | None, capture: dict[str, Any] | str) -> dict[str, Any]:
    """Build the capture report from the structured CDP capture result.

    The ``capture`` dict has keys ``modern_lines``, ``selector_text``,
    ``grid_innertext``, ``grid_rows``, and ``selector_row_count`` (as returned
    by ``capture_visible_text``).

    Path precedence (most reliable first):
    1. ``modern_lines`` (React MFE, ``data-testid``-keyed) ->
       ``parse_modern_lines``: ``amount-spent`` / ``amount-received`` are
       dedicated named fields so the sign is unambiguous without any column
       inference (``sign_confidence: "high"``). Preferred whenever it yields
       ≥ 1 line.
    2. ``grid_rows`` (column-structured ExtJS) -> ``parse_grid_rows``:
       spent/received resolved by column INDEX. Used as a fallback for orgs /
       tabs that still serve the classic grid.
    3. ``grid_innertext`` blob -> ``parse_grid_innertext``: used only when no
       structured rows are available. Single-money rows are magnitude-only and
       flagged ``sign_confidence: "low"`` rather than silently signed.
    4. selector text -> ``extract_statement_lines_from_text``: the original
       modern-UI degradation path.

    The structured/blob grid paths engage when the selector path is sparse
    (< 2 usable rows) OR when structured rows clearly carry more lines. The
    ``capture_method`` key records which path was used.
    """
    if isinstance(capture, str):
        capture = {"selector_text": capture}
    elif not isinstance(capture, dict):
        capture = {}

    modern_lines_raw = capture.get("modern_lines") if isinstance(capture.get("modern_lines"), list) else []
    selector_text = str(capture.get("selector_text") or "")
    grid_innertext = str(capture.get("grid_innertext") or "")
    grid_rows = capture.get("grid_rows") if isinstance(capture.get("grid_rows"), list) else []
    selector_row_count = int(capture.get("selector_row_count") or 0)

    # Modern test-id path: preferred when present (≥1 line with an amount or
    # even amount=None — we check for ≥1 parsed record regardless of amount).
    modern_lines: list[dict[str, Any]] = []
    if modern_lines_raw:
        modern_lines = parse_modern_lines(modern_lines_raw)

    selector_lines = extract_statement_lines_from_text(selector_text)

    structured_lines: list[dict[str, Any]] = []
    if grid_rows:
        parsed_structured = parse_grid_rows(grid_rows)
        # Keep only rows that resolved to an amount; ignore header/blank rows.
        structured_lines = [line for line in parsed_structured if line.get("amount") is not None]

    blob_lines: list[dict[str, Any]] = []
    if grid_innertext:
        blob_lines = parse_grid_innertext(grid_innertext)

    selector_sparse = selector_row_count < 2

    # Prefer the modern test-id path whenever it yielded at least one line.
    if modern_lines:
        lines = modern_lines
        capture_method = "modern-testid"
    # Fall back to the column-structured classic-grid path.
    elif structured_lines and (selector_sparse or len(structured_lines) > len(selector_lines)):
        lines = structured_lines
        capture_method = "grid-rows"
    elif blob_lines and selector_sparse and len(blob_lines) > len(selector_lines):
        lines = blob_lines
        capture_method = "grid-innertext-fallback"
    else:
        lines = selector_lines
        capture_method = "selector"

    low_confidence_count = sum(1 for line in lines if line.get("sign_confidence") == "low")

    return {
        "ok": True,
        "mode": "cdp-capture-lines",
        "generated_at": utc_seconds(),
        "cdp_endpoint": redact_endpoint(endpoint),
        "connected": True,
        "login_automation": False,
        "credential_collection": False,
        "target": summarize_cdp_target(target) if target else None,
        "statement_line_count": len(lines),
        "statement_lines": lines,
        "capture_scope": "visible_text_only",
        "capture_method": capture_method,
        "low_sign_confidence_count": low_confidence_count,
        "statement_balance": capture.get("statement_balance"),
        "xero_balance": capture.get("xero_balance"),
        "reconciled_badge": bool(capture.get("reconciled_badge")),
        "storage_access": False,
        "cookies_access": False,
    }


def _resolve_json_arg(value: str) -> Any:
    """Return parsed JSON from *value*, treating it as inline JSON if it is not
    an existing filesystem path.

    Precedence:
    1. If ``value`` names an existing file, load and return its contents.
    2. Otherwise, attempt to parse ``value`` as a JSON literal directly.
    3. If neither succeeds, raise ``ReconciliationError`` with a clear message.

    This lets callers pass either ``--expected /path/to/file.json`` or
    ``--expected '[{"amount":100.00}]'`` without ambiguity.
    """
    candidate_path = Path(value).expanduser()
    if candidate_path.is_file():
        return load_json_file(candidate_path.resolve())
    # Not an existing file — try parsing as inline JSON.
    try:
        return json.loads(value)
    except json.JSONDecodeError:
        raise ReconciliationError(
            f"--expected / --statement-lines value is neither an existing file path nor valid inline JSON: {value!r}. "
            "Expected a file path or a JSON array of objects, each with an 'amount' key (not 'spent'/'received')."
        )


def load_expected(path: str | None) -> list[dict[str, Any]]:
    if not path:
        return []
    payload = _resolve_json_arg(path)
    if isinstance(payload, list):
        return [item for item in payload if isinstance(item, dict)]
    if isinstance(payload, dict) and isinstance(payload.get("expected"), list):
        return [item for item in payload["expected"] if isinstance(item, dict)]
    if isinstance(payload, dict) and isinstance(payload.get("candidates"), list):
        return [item for item in payload["candidates"] if isinstance(item, dict)]
    raise ReconciliationError(
        "Expected value must be a JSON array or an object with 'expected'/'candidates' array. "
        "Each item should have an 'amount' key (not 'spent'/'received')."
    )


def load_apply_plan(path: str | None) -> list[dict[str, Any]]:
    if not path:
        raise ReconciliationError("Reconciliation apply requires --plan with explicit action records.")
    payload = load_json_file(Path(path).expanduser().resolve())
    if isinstance(payload, list):
        rows = payload
    elif isinstance(payload, dict) and isinstance(payload.get("actions"), list):
        rows = payload["actions"]
    elif isinstance(payload, dict) and isinstance(payload.get("plan"), list):
        rows = payload["plan"]
    else:
        raise ReconciliationError("Apply plan must be a JSON array or an object with actions/plan array.")
    actions: list[dict[str, Any]] = []
    for index, item in enumerate(rows, start=1):
        if not isinstance(item, dict):
            raise ReconciliationError(f"Apply plan action {index} must be an object.")
        action = str(item.get("action") or "").strip()
        if action not in APPLY_ACTIONS:
            raise ReconciliationError(f"Apply plan action {index} has unsupported action: {action!r}.")
        line_text = re.sub(r"\s+", " ", str(item.get("line_text") or item.get("statement_line") or "").strip())
        reference = re.sub(r"\s+", " ", str(item.get("reference") or item.get("expected_reference") or "").strip())
        amount = parse_money(item.get("amount") if "amount" in item else item.get("expected_amount"))
        action_record = {
            "index": item.get("index") or index,
            "action": action,
            "line_text": line_text,
            "reference": reference,
            "amount": amount,
            "button_text": re.sub(r"\s+", " ", str(item.get("button_text") or item.get("action_anchor") or "").strip()) or None,
        }
        if action in ROW_SCOPED_APPLY_ACTIONS:
            if not line_text and not reference:
                raise ReconciliationError(f"Apply plan action {index} needs line_text/statement_line or reference.")
            if not line_text and reference and amount is None:
                raise ReconciliationError(f"Apply plan action {index} needs an amount when matching by reference only.")
        if action == "search-transaction":
            search_text = re.sub(r"\s+", " ", str(item.get("search_text") or item.get("query") or item.get("transaction_text") or "").strip())
            if not search_text:
                raise ReconciliationError(f"Apply plan action {index} needs search_text/query.")
            action_record.update(
                {
                    "search_text": search_text,
                    "input_label": re.sub(r"\s+", " ", str(item.get("input_label") or item.get("input_placeholder") or "").strip()) or None,
                    "dialog_text": re.sub(r"\s+", " ", str(item.get("dialog_text") or "").strip()) or None,
                }
            )
        elif action == "select-transaction":
            transaction_text = re.sub(r"\s+", " ", str(item.get("transaction_text") or item.get("match_text") or item.get("reference") or "").strip())
            if not transaction_text:
                raise ReconciliationError(f"Apply plan action {index} needs transaction_text/match_text/reference.")
            action_record.update(
                {
                    "transaction_text": transaction_text,
                    "dialog_text": re.sub(r"\s+", " ", str(item.get("dialog_text") or "").strip()) or None,
                }
            )
        elif action == "confirm-match":
            if not action_record["button_text"]:
                raise ReconciliationError(f"Apply plan action {index} needs button_text/action_anchor.")
            action_record.update(
                {
                    "dialog_text": re.sub(r"\s+", " ", str(item.get("dialog_text") or "").strip()) or None,
                }
            )
        actions.append(action_record)
    return actions


def _normalize_plan_choice(value: Any, *, default_query: str = "") -> dict[str, Any] | None:
    if value is None or value == "":
        return None
    if isinstance(value, str):
        normalized = re.sub(r"\s+", " ", value.strip())
        return {"query": default_query or normalized, "display": normalized}
    if not isinstance(value, dict):
        raise ReconciliationError("Plan account/contact/tax choices must be strings or objects.")
    display = re.sub(
        r"\s+",
        " ",
        str(value.get("display") or value.get("name") or value.get("label") or value.get("value") or "").strip(),
    )
    query = re.sub(r"\s+", " ", str(value.get("query") or value.get("code") or display or default_query).strip())
    identifier = re.sub(r"\s+", " ", str(value.get("id") or value.get("xero_id") or value.get("account_id") or value.get("tax_id") or "").strip())
    if not query and not display and not identifier:
        return None
    result: dict[str, Any] = {"query": query or display or identifier}
    if display:
        result["display"] = display
    if identifier:
        result["id"] = identifier
    type_text = re.sub(r"\s+", " ", str(value.get("type_text") or "").strip())
    if type_text:
        # Optional fuller search string typed into the completer so Xero's
        # server-side search narrows to one option row on first render.
        result["type_text"] = type_text
    return result


def load_reconciliation_plan(path: str | None) -> list[dict[str, Any]]:
    """Load the simple reconciliation-intent plan consumed by the Playwright engine.

    Accepted shapes:
    - JSON array of line records.
    - Object with ``lines`` or ``plan`` array.

    This is deliberately not a selector/action DSL.  Each line states the
    accounting intent for one BankRec row; the Node Playwright engine owns Xero
    widget mechanics and hidden-field verification.
    """
    if not path:
        raise ReconciliationError("Reconciliation apply requires --plan with reviewed line intents.")
    payload = load_json_file(Path(path).expanduser().resolve())
    if isinstance(payload, list):
        rows = payload
    elif isinstance(payload, dict) and isinstance(payload.get("lines"), list):
        rows = payload["lines"]
    elif isinstance(payload, dict) and isinstance(payload.get("plan"), list):
        rows = payload["plan"]
    else:
        raise ReconciliationError("Plan must be a JSON array or an object with lines/plan array.")

    plan: list[dict[str, Any]] = []
    for index, item in enumerate(rows, start=1):
        if not isinstance(item, dict):
            raise ReconciliationError(f"Plan line {index} must be an object.")
        action = str(item.get("action") or "").strip().lower().replace("_", "-")
        if action not in RECONCILE_PLAN_ACTIONS:
            raise ReconciliationError(f"Plan line {index} has unsupported action: {action!r}.")
        if action == "accept-suggestion":
            action = "match"
        statement_line_id = re.sub(
            r"\s+",
            " ",
            str(item.get("statement_line_id") or item.get("statementLineId") or item.get("line_id") or "").strip(),
        )
        if not statement_line_id:
            raise ReconciliationError(f"Plan line {index} needs statement_line_id.")
        amount = parse_money(item.get("amount") if "amount" in item else item.get("expected_amount"))
        if amount is None:
            raise ReconciliationError(f"Plan line {index} needs signed amount for the one-row guard.")

        account = _normalize_plan_choice(item.get("account") or item.get("account_code"))
        tax = _normalize_plan_choice(item.get("tax") or item.get("tax_code") or item.get("tax_rate"))
        contact = _normalize_plan_choice(item.get("contact") or item.get("contact_name"))
        transfer_account = _normalize_plan_choice(
            item.get("transfer_account") or item.get("target_bank_account") or item.get("bank_account")
        )
        description = re.sub(r"\s+", " ", str(item.get("description") or item.get("notes") or "").strip())
        reference = re.sub(r"\s+", " ", str(item.get("reference") or "").strip())
        match_text = re.sub(
            r"\s+",
            " ",
            str(item.get("match_text") or item.get("transaction_text") or item.get("expected_match") or "").strip(),
        )

        if action == "create" and account is None:
            raise ReconciliationError(f"Plan line {index} create action needs account/account_code.")
        if action == "transfer" and transfer_account is None:
            raise ReconciliationError(f"Plan line {index} transfer action needs transfer_account/target_bank_account.")
        if action == "match" and not (match_text or reference):
            raise ReconciliationError(f"Plan line {index} match action needs match_text/transaction_text/expected_match or reference.")

        record: dict[str, Any] = {
            "index": item.get("index") or index,
            "statement_line_id": statement_line_id,
            "action": action,
            "amount": amount,
        }
        for key, value in (
            ("account", account),
            ("tax", tax),
            ("contact", contact),
            ("transfer_account", transfer_account),
        ):
            if value is not None:
                record[key] = value
        if description:
            record["description"] = description
        if reference:
            record["reference"] = reference
        if match_text:
            record["match_text"] = match_text
        if item.get("notes"):
            record["notes"] = re.sub(r"\s+", " ", str(item["notes"]).strip())
        plan.append(record)
    return plan


def normalize_text(value: Any) -> str:
    return re.sub(r"\s+", " ", html.unescape(str(value or "")).strip()).lower()


def parse_money(value: Any) -> float | None:
    if value is None or value == "":
        return None
    if isinstance(value, (int, float)):
        return round(float(value), 2)
    text = str(value).replace(",", "")
    match = MONEY_PATTERN.search(text)
    if not match:
        return None
    cleaned = re.sub(r"[^0-9.\-]", "", match.group(0).replace(",", ""))
    if not cleaned:
        return None
    try:
        return round(float(cleaned), 2)
    except ValueError:
        return None


def parse_balance_text(text: Any) -> float | None:
    """Parse a BankRec header balance like ``1,234.56`` or ``(6.53)`` (negative)."""
    if text is None:
        return None
    raw = str(text).strip()
    if not raw:
        return None
    negative = raw.startswith("(") and raw.endswith(")")
    raw = raw.strip("()").replace(",", "")
    try:
        value = float(raw)
    except ValueError:
        return None
    return -value if negative else value


def statement_line_from_text(text: str, index: int) -> dict[str, Any]:
    normalized = re.sub(r"\s+", " ", text.strip())
    return {
        "index": index,
        "text": normalized,
        "amount": parse_money(normalized),
    }


def extract_statement_lines_from_text(raw: str) -> list[dict[str, Any]]:
    cleaned = html.unescape(raw).replace("\r\n", "\n").replace("\r", "\n")
    blocks = [block.strip() for block in re.split(r"\n\s*\n+", cleaned) if block.strip()]
    if len(blocks) <= 1:
        blocks = [line.strip() for line in cleaned.splitlines() if line.strip()]
    return [statement_line_from_text(block, index + 1) for index, block in enumerate(blocks)]


def parse_grid_rows(rows: list[list[Any]]) -> list[dict[str, Any]]:
    """Parse column-structured BankRec grid rows into statement-line records.

    ``rows`` is a list of per-row cell-string arrays read in DOM column order,
    INCLUDING empty strings for empty cells (as produced by
    ``capture_visible_text``'s structured ``grid_rows``).

    Classic Xero BankRec column order is:
        date | description | reference | spent | received

    Because empty cells are preserved positionally, a money value can be mapped
    to spent vs received unambiguously:
    - a value in the SPENT column  -> money leaving the account  -> NEGATIVE amount
    - a value in the RECEIVED column -> money into the account     -> POSITIVE amount

    Column detection is positional and resilient to extra leading columns: the
    two right-most non-empty-capable money columns are treated as
    ``[spent, received]``. When a row carries a single money value, its column
    INDEX (penultimate vs last) decides the sign — this is the whole point of
    capturing blanks. These records are emitted with ``sign_confidence: "high"``.

    Records use the shared contract: ``index``, ``text``, ``amount`` (signed,
    NOT ``spent``/``received``), ``source``, ``sign_confidence``.
    """
    records: list[dict[str, Any]] = []
    for raw_cells in rows:
        cells = [re.sub(r"\s+", " ", html.unescape(str(cell or "")).strip()) for cell in raw_cells]
        if not cells:
            continue
        # The last two columns are spent, received (in that order).
        if len(cells) >= 2:
            spent_cell, received_cell = cells[-2], cells[-1]
            description_cells = cells[:-2]
        else:
            spent_cell, received_cell = "", cells[-1]
            description_cells = []

        spent = parse_money(spent_cell)
        received = parse_money(received_cell)

        amount: float | None
        sign_confidence = "high"
        if received is not None and spent is not None:
            # Both populated (e.g. a transfer-style row): net received minus spent.
            amount = round(abs(received) - abs(spent), 2)
        elif received is not None:
            amount = abs(received)
        elif spent is not None:
            amount = -abs(spent)
        else:
            # No money in either money column. Structure is present but this row
            # carries no resolvable amount (header/blank row).
            amount = None
            sign_confidence = "high"

        text = " ".join(part for part in description_cells if part)
        if not text:
            text = " ".join(part for part in cells if part)
        records.append({
            "index": len(records) + 1,
            "text": re.sub(r"\s+", " ", text),
            "amount": amount,
            "source": "grid-rows",
            "sign_confidence": sign_confidence,
        })
    return records


def parse_grid_innertext(raw: str) -> list[dict[str, Any]]:
    """Parse statement lines from an ExtJS BankRec grid's collapsed innerText.

    This is the BLOB fallback used only when no column-structured rows are
    available (see ``parse_grid_rows`` for the preferred, unambiguous path).

    The classic Xero BankRec grid renders each statement line with columns:
        date | description | reference | spent | received
    but when read as a single ``innerText`` blob, empty money cells collapse, so
    a row that is EITHER spent OR received yields a single money token whose
    column of origin is unknown.

    Sign honesty contract: this function MUST NOT emit a confidently-wrong
    signed amount. When a row carries exactly one money token and the column is
    therefore unknown, the record carries the magnitude (absolute value) and is
    flagged ``sign_confidence: "low"`` so downstream can match on magnitude
    rather than trust a guessed sign. Rows where two money tokens are present
    (spent + received both visible) are resolved positionally as
    ``[spent, received]`` and flagged ``sign_confidence: "high"``.

    Records use the shared contract: ``index``, ``text``, ``amount`` (NOT
    ``spent``/``received``), ``source``, ``sign_confidence``.
    """
    cleaned = html.unescape(raw).replace("\r\n", "\n").replace("\r", "\n")
    lines = [line for line in cleaned.splitlines() if line.strip()]
    records: list[dict[str, Any]] = []
    for raw_line in lines:
        # Split on two-or-more spaces or a tab, keeping token order.
        tokens = [t.strip() for t in re.split(r"\t| {2,}", raw_line) if t.strip()]
        money_tokens: list[float] = []
        description_tokens: list[str] = []
        for token in tokens:
            parsed = parse_money(token)
            if parsed is not None:
                money_tokens.append(parsed)
            else:
                description_tokens.append(token)

        amount: float | None
        if len(money_tokens) >= 2:
            # Two money values present -> positional [spent, received].
            spent_value, received_value = money_tokens[-2], money_tokens[-1]
            amount = round(abs(received_value) - abs(spent_value), 2)
            sign_confidence = "high"
        elif len(money_tokens) == 1:
            # Single money token, unknown column -> magnitude only, low confidence.
            amount = abs(money_tokens[0])
            sign_confidence = "low"
        else:
            amount = None
            sign_confidence = "high"

        text = " ".join(description_tokens) if description_tokens else raw_line.strip()
        records.append({
            "index": len(records) + 1,
            "text": re.sub(r"\s+", " ", text),
            "amount": amount,
            "source": "grid-innertext-fallback",
            "sign_confidence": sign_confidence,
        })
    return records


def normalize_statement_line(item: dict[str, Any], index: int) -> dict[str, Any]:
    text = item.get("text") or item.get("statement_line") or item.get("description") or item.get("narration") or ""
    amount = item.get("amount")
    if amount is None:
        amount = item.get("expected_amount")
    parsed_amount = parse_money(amount)
    if parsed_amount is None:
        parsed_amount = parse_money(text)
    normalized = {
        "index": item.get("index") or index,
        "text": re.sub(r"\s+", " ", str(text).strip()),
        "amount": parsed_amount,
        "source": item.get("source") or "snapshot",
    }
    statement_line_id = str(item.get("statement_line_id") or item.get("statementLineId") or item.get("line_id") or "").strip()
    if statement_line_id:
        normalized["statement_line_id"] = statement_line_id
    return normalized


def load_statement_lines(path: str | None = None, text_path: str | None = None) -> list[dict[str, Any]]:
    if path and text_path:
        raise ReconciliationError("Use only one of --statement-lines or --statement-text.")
    if not path and not text_path:
        return []
    if text_path:
        raw = Path(text_path).expanduser().resolve().read_text(encoding="utf-8")
        return extract_statement_lines_from_text(raw)
    payload = _resolve_json_arg(str(path))
    if isinstance(payload, list):
        rows = [item for item in payload if isinstance(item, dict)]
    elif isinstance(payload, dict) and isinstance(payload.get("statement_lines"), list):
        rows = [item for item in payload["statement_lines"] if isinstance(item, dict)]
    elif isinstance(payload, dict) and isinstance(payload.get("lines"), list):
        rows = [item for item in payload["lines"] if isinstance(item, dict)]
    else:
        raise ReconciliationError(
            "Statement-lines value must be a JSON array or an object with 'statement_lines'/'lines' array. "
            "Each item must use 'amount' (not 'spent'/'received') for the monetary value."
        )
    return [normalize_statement_line(item, index + 1) for index, item in enumerate(rows)]


def expected_reference(expected: dict[str, Any]) -> str:
    for key in ("expected_reference", "reference", "invoice_number", "invoiceNumber", "xero_id", "xeroId"):
        value = str(expected.get(key) or "").strip()
        if value:
            return value
    return ""


def expected_amount(expected: dict[str, Any]) -> float | None:
    for key in ("expected_amount", "amount", "total", "Total"):
        parsed = parse_money(expected.get(key))
        if parsed is not None:
            return parsed
    return None


def match_expected_to_statement_lines(expected: list[dict[str, Any]], statement_lines: list[dict[str, Any]]) -> list[dict[str, Any]]:
    matches = []
    for item in expected:
        reference = expected_reference(item)
        amount = expected_amount(item)
        candidates = []
        for line in statement_lines:
            text = normalize_text(line.get("text"))
            reference_match = bool(reference) and normalize_text(reference) in text
            amount_match = amount is not None and line.get("amount") is not None and abs(float(line["amount"]) - amount) < 0.01
            if reference_match or amount_match:
                confidence = 0
                reasons = []
                if reference_match:
                    confidence += 70
                    reasons.append("reference")
                if amount_match:
                    confidence += 30
                    reasons.append("amount")
                candidates.append(
                    {
                        "line_index": line.get("index"),
                        "statement_line_id": line.get("statement_line_id"),
                        "line_text": line.get("text"),
                        "line_amount": line.get("amount"),
                        "confidence": confidence,
                        "reasons": reasons,
                    }
                )
        candidates.sort(key=lambda candidate: int(candidate["confidence"]), reverse=True)
        status = "matched" if candidates and candidates[0]["confidence"] >= 100 else "review" if candidates else "missing"
        matches.append(
            {
                "expected_reference": reference or None,
                "expected_amount": amount,
                "status": status,
                "best_match": candidates[0] if candidates else None,
                "candidate_count": len(candidates),
                "candidates": candidates[:5],
            }
        )
    return matches


def expected_transaction_text(expected: dict[str, Any]) -> str:
    for key in ("transaction_text", "match_text", "expected_reference", "reference", "invoice_number", "invoiceNumber", "xero_id", "xeroId"):
        value = re.sub(r"\s+", " ", str(expected.get(key) or "").strip())
        if value:
            return value
    return ""


def build_suggested_apply_plan(expected: list[dict[str, Any]], matches: list[dict[str, Any]]) -> list[dict[str, Any]]:
    actions: list[dict[str, Any]] = []
    for item, match in zip(expected, matches):
        if match.get("status") != "matched":
            continue
        best = match.get("best_match") if isinstance(match.get("best_match"), dict) else None
        if not best:
            continue
        reasons = set(best.get("reasons") if isinstance(best.get("reasons"), list) else [])
        if not {"reference", "amount"}.issubset(reasons):
            continue
        line_text = re.sub(r"\s+", " ", str(best.get("line_text") or "").strip())
        statement_line_id = re.sub(r"\s+", " ", str(best.get("statement_line_id") or "").strip())
        reference = expected_reference(item)
        amount = expected_amount(item)
        transaction_text = expected_transaction_text(item)
        if not statement_line_id or not transaction_text:
            continue
        if item.get("match_already_visible") is not True:
            continue
        action = {
            "source": "dry-run-suggestion",
            "requires_review": True,
            "expected_reference": reference or None,
            "line_index": best.get("line_index"),
            "statement_line_id": statement_line_id,
            "action": "match",
            "amount": amount,
            "match_text": transaction_text,
        }
        if reference:
            action["reference"] = reference
        if line_text:
            action["line_text"] = line_text
        actions.append(action)
    return actions


def build_dry_run_report(
    *,
    endpoint: str,
    expected: list[dict[str, Any]],
    bank_account: str | None = None,
    statement_lines: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    lines = statement_lines or []
    matches = match_expected_to_statement_lines(expected, lines) if lines else []
    suggested_apply_plan = build_suggested_apply_plan(expected, matches) if matches else []
    return {
        "ok": True,
        "mode": "dry-run-preflight",
        "generated_at": utc_seconds(),
        "cdp_endpoint": redact_endpoint(endpoint),
        "connected": False,
        "requires_user_authenticated_browser": True,
        "login_automation": False,
        "credential_collection": False,
        "bank_account": bank_account,
        "expected_count": len(expected),
        "expected": expected,
        "statement_line_count": len(lines),
        "statement_lines": lines,
        "matches": matches,
        "suggested_apply_plan": suggested_apply_plan,
        "suggested_apply_plan_summary": {
            "action_count": len(suggested_apply_plan),
            "candidate_count": len({item.get("line_index") for item in suggested_apply_plan if item.get("line_index") is not None}),
            "requires_review": bool(suggested_apply_plan),
            "apply_requires_confirm_apply": True,
        },
        "match_summary": {
            "matched": sum(1 for item in matches if item["status"] == "matched"),
            "review": sum(1 for item in matches if item["status"] == "review"),
            "missing": sum(1 for item in matches if item["status"] == "missing"),
        },
        "planned_browser_scope": [
            "inspect imported Reconcile tab statement lines",
            "compare visible statement lines to expected API-created records",
            "draft explicit apply plans for operator review",
            "accept Xero suggestions only when they match expected records",
            "match statement lines to existing transactions/payments/transfers",
            "record skipped/escalated items without guessing",
        ],
        "not_implemented_yet": [
            "refined live DOM statement-line enumeration",
            "multi-step match dialog orchestration",
        ],
    }


# ---------------------------------------------------------------------------
# UI detection: JS probe expression (read-only DOM signals, no mutations)
# ---------------------------------------------------------------------------

# Pure DOM reads — no clicks, no event dispatches, no mutations.
# Returns a plain object (SIGNALS dict) serialisable to JSON via returnByValue.
#
# Signals keyed exactly as documented in bankrec-ui-map.md §2:
#   has_modern_amount_testid  — any [data-testid="amount-spent"] or [data-testid="amount-received"]
#   grid_row_count            — count of .x-grid-row elements
#   okay_button_count         — count of a.okayButton elements
#   has_create_tab            — any a.t2 present (Create tab)
#   has_transfer_tab          — any a.t3 present (Transfer tab)
#   has_match_tab             — any a.t1 present (Match tab)
#   has_paid_account_input    — any input[id^="paidAccount"] present
#   empty_banner_text         — text of a banner/h2/p containing "great job" or
#                               "reconciled all" or "no transactions imported"
_DETECT_UI_EXPR: str = """
(() => {
  const hasEl = (sel) => document.querySelector(sel) !== null;
  const countEl = (sel) => document.querySelectorAll(sel).length;
  // Empty-state banner: scan common containers for the known phrases.
  const bannerCandidates = Array.from(
    document.querySelectorAll('h1,h2,h3,p,[class*="empty"],[class*="banner"],[class*="message"],[class*="reconcil"]')
  );
  let emptyBannerText = '';
  const emptyPhrases = ['great job', 'reconciled all', 'no transactions imported'];
  for (const el of bannerCandidates) {
    const text = (el.innerText || el.textContent || '').replace(/\\s+/g, ' ').trim().toLowerCase();
    if (emptyPhrases.some((phrase) => text.includes(phrase))) {
      emptyBannerText = text;
      break;
    }
  }
  return {
    has_modern_amount_testid: (
      hasEl('[data-testid="amount-spent"]') || hasEl('[data-testid="amount-received"]')
    ),
    grid_row_count: countEl('tr.x-grid-row, .x-grid-row'),
    okay_button_count: countEl('a.okayButton'),
    has_create_tab: hasEl('a.t2'),
    has_transfer_tab: hasEl('a.t3'),
    has_match_tab: hasEl('a.t1'),
    has_paid_account_input: hasEl('input[id^="paidAccount"]'),
    empty_banner_text: emptyBannerText,
  };
})()
"""


# ---------------------------------------------------------------------------
# Classifier: classify_reconcile_ui
# ---------------------------------------------------------------------------

# Classic-apply field map template.  <HASH> is a literal placeholder — callers
# must substitute the real hash (statement_line_id with dashes stripped) before
# use.  Keeping it as a template here means the doc-specified selector strings
# are expressed exactly once and are independently testable.
#
# NOTE on tax / GST: bankrec-ui-map.md §4 marks the visible sibling as
# "*(visible sibling likely `paidGSTCode<HASH>_value`; confirm on Create-tab
# expand)*" — i.e. the backing hidden field `paidGSTCode<HASH>` is confirmed;
# the visible autocompleter id suffix `_value` is inferred but NOT live-verified.
# The template uses `paidGSTCode<HASH>_value` for the visible input and flags
# this with `"confirmed": false` so callers know it needs verification.
_CLASSIC_APPLY_FIELD_MAP_TEMPLATE: dict[str, Any] = {
    "row_selector_template": "#sl<HASH>",
    "tabs": {
        "match":    "a.t1",
        "create":   "a.t2",
        "transfer": "a.t3",
    },
    "create_fields": {
        "contact_visible":     "input#paidTo<HASH>_value",
        "contact_hidden_id":   "paidToID<HASH>",
        "contact_hidden":      "paidTo<HASH>",
        "account_visible":     "input#paidAccount<HASH>_value",
        "account_hidden":      "paidAccount<HASH>",
        "tax_visible":         "input#paidGSTCode<HASH>_value",
        "tax_visible_confirmed": False,   # doc §4: visible sibling unconfirmed
        "tax_hidden":          "paidGSTCode<HASH>",
        "description":         "input#paidDesc<HASH>",
        "reference":           "input#reference<HASH>_value",
    },
    "transfer_fields": {
        "account_visible":  "input#transferAccount<HASH>_value",
        "account_hidden":   "transferAccount<HASH>",
    },
    "confirm": "a.okayButton",
    "confirm_full": "a.xbtn.skip.okayButton.exclude",
    "notes": (
        "ExtJS autocompleters (account, tax, contact): type to trigger dropdown "
        "then SELECT the option — setting .value alone does NOT populate the hidden id. "
        "Description and reference are plain text inputs."
    ),
}


_EMPTY_BANNER_PHRASES = ("great job", "reconciled all", "no transactions imported")


def classify_reconcile_ui(signals: dict[str, Any]) -> dict[str, Any]:
    """Classify the live Xero BankRec UI from read-only DOM signals.

    Parameters
    ----------
    signals:
        Dict returned by evaluating ``_DETECT_UI_EXPR`` via CDP (or a fixture
        with the same keys for offline testing).

    Returns
    -------
    dict with keys:
      read_variant:  "modern" | "classic" | "empty" | "unknown"
      apply_variant: "classic" | "unknown" | "none"
      row_selector:  CSS selector template (uses "<HASH>" placeholder) or None
      field_map:     classic apply field map dict (template) or None

    Classification rules (bankrec-ui-map.md §2):
    - read_variant "modern"  — has_modern_amount_testid is truthy
    - read_variant "classic" — grid_row_count > 0, no modern testid
    - read_variant "empty"   — empty_banner_text matches a known phrase
    - read_variant "unknown" — none of the above

    - apply_variant "classic" — has_create_tab AND has_transfer_tab AND
                                has_match_tab AND has_paid_account_input AND
                                okay_button_count > 0
    - apply_variant "none"    — read_variant is "empty"
    - apply_variant "unknown" — otherwise (triggers refuse-apply policy)
    """
    has_modern = bool(signals.get("has_modern_amount_testid"))
    grid_count = int(signals.get("grid_row_count") or 0)
    okay_count = int(signals.get("okay_button_count") or 0)
    has_create = bool(signals.get("has_create_tab"))
    has_transfer = bool(signals.get("has_transfer_tab"))
    has_match = bool(signals.get("has_match_tab"))
    has_paid_account = bool(signals.get("has_paid_account_input"))
    banner = str(signals.get("empty_banner_text") or "").lower()

    # --- READ variant ---
    if has_modern:
        read_variant = "modern"
    elif grid_count > 0:
        read_variant = "classic"
    elif any(phrase in banner for phrase in _EMPTY_BANNER_PHRASES):
        read_variant = "empty"
    else:
        read_variant = "unknown"

    # --- APPLY variant ---
    classic_apply = (
        has_create and has_transfer and has_match and has_paid_account and okay_count > 0
    )
    if classic_apply:
        apply_variant = "classic"
    elif read_variant == "empty":
        apply_variant = "none"
    else:
        apply_variant = "unknown"

    # --- row_selector and field_map ---
    if apply_variant == "classic":
        row_selector = "#sl<HASH>"
        field_map = _CLASSIC_APPLY_FIELD_MAP_TEMPLATE
    else:
        row_selector = None
        field_map = None

    return {
        "read_variant": read_variant,
        "apply_variant": apply_variant,
        "row_selector": row_selector,
        "field_map": field_map,
    }


# ---------------------------------------------------------------------------
# Apply-plan selector builder: build_apply_actions
# ---------------------------------------------------------------------------

def _hash_from_id(statement_line_id: str) -> str:
    """Derive the ExtJS <HASH> from a statement line id (dashes stripped)."""
    return statement_line_id.replace("-", "")


def build_apply_actions(
    *,
    statement_line_id: str,
    action: str,
    account: str | None = None,
    tax_code: str | None = None,
    contact: str | None = None,
    description: str | None = None,
    transfer_account: str | None = None,
    ui: dict[str, Any],
) -> list[dict[str, Any]]:
    """Build an ordered list of apply-action dicts for a single BankRec line.

    Returns DATA ONLY — no execution, no browser calls, no DOM mutations.
    The caller is responsible for human-reviewed execution of each step.

    Parameters
    ----------
    statement_line_id:
        Dashed GUID from ``data-statementlineid`` (e.g.
        "a1b2c3d4-e5f6-7890-abcd-ef1234567890"). Dashes are stripped to
        derive <HASH>.
    action:
        One of "create", "transfer", "match".
    account:
        Xero account name/code for the Create or (optional) Match tab.
    tax_code:
        GST/tax code for the Create tab.
    contact:
        Contact name for the Create tab.
    description:
        Free-text description for the Create tab.
    transfer_account:
        Account for the Transfer tab.
    ui:
        The dict returned by ``classify_reconcile_ui``.  If
        ``ui["apply_variant"] != "classic"``, a single refuse step is returned
        and NO selectors are emitted (clean-update rule, doc §2).

    Returns
    -------
    Ordered list of step dicts.  Each dict has at minimum a ``"step"`` key.
    Possible step types:
      "refuse"           — apply_variant is not "classic"; human apply required.
      "click-tab"        — click a mode tab anchor.
      "fill-autocomplete"— type into an ExtJS autocompleter; human must select
                           the dropdown result to set the hidden id field.
      "fill-text"        — set a plain text input value directly.
      "confirm"          — click a.okayButton; carries a mandatory one-row guard.
    """
    if ui.get("apply_variant") != "classic":
        return [
            {
                "step": "refuse",
                "reason": (
                    "unrecognized apply UI — capture only, human apply"
                ),
            }
        ]

    if action not in {"create", "transfer", "match"}:
        return [
            {
                "step": "refuse",
                "reason": f"unknown action {action!r}; must be 'create', 'transfer', or 'match'",
            }
        ]

    h = _hash_from_id(statement_line_id)
    row = f"#sl{h}"
    steps: list[dict[str, Any]] = []

    # Step 1: click the correct mode tab.
    tab_map = {"create": "a.t2", "transfer": "a.t3", "match": "a.t1"}
    tab_selector = f"{row} {tab_map[action]}"
    steps.append({"step": "click-tab", "selector": tab_selector})

    if action == "create":
        # Contact (Who) — ExtJS autocompleter.
        if contact is not None:
            steps.append({
                "step": "fill-autocomplete",
                "selector": f"{row} input#paidTo{h}_value",
                "value": contact,
                "note": (
                    "ExtJS autocompleter — type then select dropdown option "
                    "to set hidden id fields paidToID<HASH> and paidTo<HASH>"
                ),
            })
        # Account (What) — ExtJS autocompleter.
        if account is not None:
            steps.append({
                "step": "fill-autocomplete",
                "selector": f"{row} input#paidAccount{h}_value",
                "value": account,
                "note": (
                    "ExtJS autocompleter — type then select dropdown option "
                    "to set hidden field paidAccount<HASH>"
                ),
            })
        # Tax / GST code — ExtJS autocompleter (visible input unconfirmed per doc §4).
        if tax_code is not None:
            steps.append({
                "step": "fill-autocomplete",
                "selector": f"{row} input#paidGSTCode{h}_value",
                "value": tax_code,
                "note": (
                    "ExtJS autocompleter — sets hidden paidGSTCode<HASH>. "
                    "WARNING: visible input id suffix '_value' is inferred "
                    "from doc §4 but UNCONFIRMED (not live-verified on "
                    "Create-tab expand); confirm selector before use."
                ),
            })
        # Description — plain text input.
        if description is not None:
            steps.append({
                "step": "fill-text",
                "selector": f"{row} input#paidDesc{h}",
                "value": description,
            })

    elif action == "transfer":
        # Transfer account — ExtJS autocompleter.
        if transfer_account is not None:
            steps.append({
                "step": "fill-autocomplete",
                "selector": f"{row} input#transferAccount{h}_value",
                "value": transfer_account,
                "note": (
                    "ExtJS autocompleter — type then select dropdown option "
                    "to set hidden field transferAccount<HASH>"
                ),
            })

    # action == "match": no fields to fill; just click tab then confirm.

    # Final step: confirm (a.okayButton).  Always carries the one-row guard.
    steps.append({
        "step": "confirm",
        "selector": f"{row} a.okayButton",
        "guard": (
            "exactly one row matches statement_line_id + amount before click"
        ),
    })

    return steps


def js_literal(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False)


def build_apply_expression(actions: list[dict[str, Any]]) -> str:
    return f"""
(() => {{
  const actions = {js_literal(actions)};
  const normalize = (value) => String(value || '').replace(/\\s+/g, ' ').trim().toLowerCase();
  const includesNeedle = (haystack, needle) => !needle || normalize(haystack).includes(normalize(needle));
  const visibleText = (element) => (element.innerText || element.textContent || element.value || element.getAttribute('aria-label') || element.getAttribute('title') || '').trim();
  const rowSelectors = [
    '[data-automationid*="reconcile" i]',
    '[data-testid*="reconcile" i]',
    '[class*="reconcile" i]',
    '[class*="statement" i]',
    'tr',
    'li',
    'section',
    'article',
    'div'
  ];
  // Modern role-based selectors first; classic ExtJS BankRec anchors (no role attr) as fallbacks.
  const buttonSelectors = [
    'button',
    'a[role="button"]',
    '[role="button"]',
    'input[type="button"]',
    'input[type="submit"]',
    'a.okayButton',
    'a.xbtn',
    'a.x-btn'
  ];
  const inputSelectors = ['input:not([type="hidden"])', 'textarea', '[contenteditable="true"]'];
  const defaultLabels = {{
    'accept-suggestion': ['accept', 'ok', 'reconcile', 'confirm'],
    'match-existing': ['match', 'find & match', 'find and match', 'ok', 'reconcile', 'confirm'],
    'open-match-dialog': ['match', 'find & match', 'find and match'],
    'confirm-match': ['reconcile', 'confirm', 'ok', 'match']
  }};
  const amountNeedle = (amount) => {{
    if (amount === null || amount === undefined) return '';
    const value = Number(amount);
    if (!Number.isFinite(value)) return '';
    return Math.abs(value).toFixed(2);
  }};
  const rows = [];
  for (const selector of rowSelectors) {{
    for (const element of Array.from(document.querySelectorAll(selector)).slice(0, 1500)) {{
      const text = (element.innerText || element.textContent || '').trim();
      if (text && text.length < 4000) rows.push({{ element, text }});
    }}
  }}
  const uniqueRows = [];
  const seen = new Set();
  for (const row of rows) {{
    const key = row.text.slice(0, 500);
    if (!seen.has(key)) {{
      seen.add(key);
      uniqueRows.push(row);
    }}
  }}
  const actionLabels = (action) => action.button_text ? [normalize(action.button_text)] : (defaultLabels[action.action] || []);
  const findControl = (scope, labels, selectors) => {{
    const controls = [];
    for (const selector of selectors) controls.push(...Array.from(scope.querySelectorAll(selector)));
    return controls.find((element) => {{
      const text = normalize(visibleText(element));
      return labels.some((label) => text === label || text.includes(label));
    }});
  }};
  const findScopedRoot = (dialogText) => {{
    if (!dialogText) return document;
    return uniqueRows.find((candidate) => includesNeedle(candidate.text, dialogText))?.element || document;
  }};
  const setInputValue = (element, value) => {{
    if (element.isContentEditable) {{
      element.textContent = value;
    }} else {{
      element.focus();
      element.value = value;
    }}
    element.dispatchEvent(new InputEvent('input', {{ bubbles: true, inputType: 'insertText', data: value }}));
    element.dispatchEvent(new Event('change', {{ bubbles: true }}));
  }};
  const rowMatchesAction = (candidate, action) => {{
    const amount = amountNeedle(action.amount);
    return includesNeedle(candidate.text, action.line_text) &&
      includesNeedle(candidate.text, action.reference) &&
      includesNeedle(candidate.text, amount);
  }};
  const clickRowScopedAction = (action) => {{
    const row = uniqueRows.find((candidate) => rowMatchesAction(candidate, action));
    if (!row) return {{ index: action.index, action: action.action, clicked: false, reason: 'row-not-found' }};
    const control = findControl(row.element, actionLabels(action), buttonSelectors);
    if (!control) {{
      return {{
        index: action.index,
        action: action.action,
        clicked: false,
        reason: 'button-not-found',
        row_text_excerpt: row.text.slice(0, 240)
      }};
    }}
    control.click();
    return {{
      index: action.index,
      action: action.action,
      clicked: true,
      reason: 'clicked',
      button_text: visibleText(control).slice(0, 80),
      row_text_excerpt: row.text.slice(0, 240)
    }};
  }};
  const searchTransaction = (action) => {{
    const root = findScopedRoot(action.dialog_text);
    const inputs = Array.from(root.querySelectorAll(inputSelectors.join(',')));
    const input = inputs.find((element) => {{
      const descriptor = normalize([
        element.getAttribute('aria-label'),
        element.getAttribute('placeholder'),
        element.getAttribute('name'),
        element.getAttribute('id'),
        visibleText(element)
      ].filter(Boolean).join(' '));
      return !action.input_label || descriptor.includes(normalize(action.input_label));
    }});
    if (!input) return {{ index: action.index, action: action.action, clicked: false, reason: 'input-not-found' }};
    setInputValue(input, action.search_text);
    return {{
      index: action.index,
      action: action.action,
      clicked: true,
      reason: 'search-entered',
      search_text: action.search_text
    }};
  }};
  const selectTransaction = (action) => {{
    const root = findScopedRoot(action.dialog_text);
    const amount = amountNeedle(action.amount);
    const rows = uniqueRows.filter((candidate) => root === document || root.contains(candidate.element));
    const row = rows.find((candidate) =>
      includesNeedle(candidate.text, action.transaction_text) &&
      includesNeedle(candidate.text, action.reference) &&
      includesNeedle(candidate.text, amount)
    );
    if (!row) return {{ index: action.index, action: action.action, clicked: false, reason: 'transaction-not-found' }};
    const checkbox = row.element.querySelector('input[type="checkbox"], [role="checkbox"]');
    const target = checkbox || findControl(row.element, ['select', 'add', 'match'], buttonSelectors) || row.element;
    target.click();
    return {{
      index: action.index,
      action: action.action,
      clicked: true,
      reason: 'selected',
      row_text_excerpt: row.text.slice(0, 240)
    }};
  }};
  const confirmMatch = (action) => {{
    const root = findScopedRoot(action.dialog_text);
    const control = findControl(root, actionLabels(action), buttonSelectors);
    if (!control) return {{ index: action.index, action: action.action, clicked: false, reason: 'confirm-button-not-found' }};
    control.click();
    return {{
      index: action.index,
      action: action.action,
      clicked: true,
      reason: 'confirmed',
      button_text: visibleText(control).slice(0, 80)
    }};
  }};
  const results = [];
  for (const action of actions) {{
    if (['accept-suggestion', 'match-existing', 'open-match-dialog'].includes(action.action)) {{
      results.push(clickRowScopedAction(action));
    }} else if (action.action === 'search-transaction') {{
      results.push(searchTransaction(action));
    }} else if (action.action === 'select-transaction') {{
      results.push(selectTransaction(action));
    }} else if (action.action === 'confirm-match') {{
      results.push(confirmMatch(action));
    }} else {{
      results.push({{ index: action.index, action: action.action, clicked: false, reason: 'unsupported-action' }});
    }}
  }}
  return {{
    ok: true,
    action_count: actions.length,
    clicked_count: results.filter((item) => item.clicked).length,
    results
  }};
}})()
"""


def execute_apply_plan(
    *,
    endpoint: str,
    target_id: str | None,
    actions: list[dict[str, Any]],
    timeout_seconds: int,
) -> tuple[dict[str, Any], dict[str, Any] | None]:
    websocket_url, target = target_websocket_url(endpoint, target_id=target_id)
    result = asyncio.run(cdp_evaluate(build_apply_expression(actions), websocket_url, timeout_seconds=timeout_seconds))
    if not isinstance(result, dict):
        raise ReconciliationError("CDP apply result was not a JSON object.")
    return result, target


def run_playwright_apply_engine(
    *,
    endpoint: str,
    target_id: str | None,
    plan: list[dict[str, Any]],
    confirm_apply: bool,
    timeout_seconds: int,
    apply_batch: bool = False,
    max_apply_lines: int | None = None,
) -> dict[str, Any]:
    node = os.environ.get("NODE") or shutil.which("node")
    if not node:
        raise ReconciliationError("Node.js is required for the Playwright reconciliation apply engine.")
    if not APPLY_ENGINE.is_file():
        raise ReconciliationError(f"Playwright apply engine not found: {APPLY_ENGINE}")

    command = [
        node,
        str(APPLY_ENGINE),
        "--stdin",
        "--timeout",
        str(timeout_seconds),
    ]
    if target_id:
        command.extend(["--target-id", target_id])
    if confirm_apply:
        command.append("--apply")
    if apply_batch:
        command.append("--apply-batch")
    if max_apply_lines is not None:
        command.extend(["--max-apply-lines", str(int(max_apply_lines))])

    process_timeout = max(timeout_seconds + 60, (timeout_seconds * max(1, len(plan)) * 6) + 30)
    try:
        stdin_payload = json.dumps({"cdp_endpoint": endpoint, "lines": plan}, separators=(",", ":"))
        completed = subprocess.run(command, input=stdin_payload, capture_output=True, text=True, timeout=process_timeout)
    except subprocess.TimeoutExpired as exc:
        raise ReconciliationError(f"Playwright apply engine timed out after {process_timeout}s.") from exc
    stdout = completed.stdout.strip()
    stderr = completed.stderr.strip()
    if not stdout:
        detail = f": {stderr[:500]}" if stderr else ""
        raise ReconciliationError(f"Playwright apply engine produced no JSON output{detail}")
    try:
        payload = json.loads(stdout)
    except json.JSONDecodeError as exc:
        detail = f" stderr={stderr[:500]!r}" if stderr else ""
        raise ReconciliationError(f"Playwright apply engine output was not JSON: {stdout[:500]!r}{detail}") from exc
    if completed.returncode != 0:
        message = payload.get("error") if isinstance(payload, dict) else None
        if isinstance(payload, dict):
            payload.setdefault("ok", False)
            payload["engine_exit_code"] = completed.returncode
            if stderr:
                payload["engine_stderr"] = stderr[:1000]
            if message:
                payload["error"] = message
            return payload
        raise ReconciliationError(message or f"Playwright apply engine failed with exit {completed.returncode}.")
    if not isinstance(payload, dict):
        raise ReconciliationError("Playwright apply engine result was not a JSON object.")
    return payload


def build_apply_report(
    *,
    endpoint: str,
    target: dict[str, Any] | None,
    actions: list[dict[str, Any]],
    result: dict[str, Any],
) -> dict[str, Any]:
    results = result.get("results") if isinstance(result.get("results"), list) else []
    clicked_count = sum(1 for item in results if isinstance(item, dict) and item.get("clicked") is True)
    action_summary: dict[str, int] = {}
    for action in actions:
        name = str(action.get("action") or "unknown")
        action_summary[name] = action_summary.get(name, 0) + 1
    return {
        "ok": clicked_count == len(actions),
        "mode": "cdp-apply",
        "generated_at": utc_seconds(),
        "cdp_endpoint": redact_endpoint(endpoint),
        "connected": True,
        "requires_user_authenticated_browser": True,
        "login_automation": False,
        "credential_collection": False,
        "storage_access": False,
        "cookies_access": False,
        "target": summarize_cdp_target(target) if target else None,
        "actions": actions,
        "result": result,
        "summary": {
            "action_count": len(actions),
            "clicked": clicked_count,
            "not_clicked": len(actions) - clicked_count,
            "actions_by_type": action_summary,
        },
    }


def command_status(args: argparse.Namespace) -> int:
    optional_dependencies = optional_dependency_status()
    node_available = bool(os.environ.get("NODE") or shutil.which("node"))
    playwright_available = node_playwright_available()
    payload = {
        "ok": True,
        "reconciliation_dir": str(recon_dir(args.recon_dir)),
        "requires_cdp_endpoint": True,
        "login_automation": False,
        "credential_collection": False,
        "core_install_required": False,
        "optional_dependencies": {
            **optional_dependencies,
            "node": node_available,
            "playwright": playwright_available,
            "playwright_apply_engine": APPLY_ENGINE.is_file(),
        },
        "live_cdp_ready": optional_dependencies["live_cdp_capture"] and node_available and playwright_available and APPLY_ENGINE.is_file(),
        "implemented": [
            "cdp-target-inspect",
            "cdp-visible-text-capture",
            "dry-run-preflight",
            "dry-run-suggested-apply-plan",
            "simple-reconciliation-plan-validation",
            "playwright-widget-apply-engine",
        ],
        "apply_actions": sorted(RECONCILE_PLAN_ACTIONS),
        "planned": ["validate transfer widget against live Xero", "validate tax widget against live Xero"],
    }
    write_json(payload)
    return 0


def command_inspect(args: argparse.Namespace) -> int:
    endpoint = validate_cdp_endpoint(args.cdp_endpoint)
    targets = fetch_cdp_targets(endpoint)
    report = build_inspect_report(endpoint=endpoint, targets=targets)
    if args.out:
        out_path = Path(args.out).expanduser().resolve()
        write_json_file(out_path, report)
        write_json(
            {
                "ok": True,
                "report": str(out_path),
                "summary": {
                    "target_count": report["target_count"],
                    "xero_target_count": report["xero_target_count"],
                    "reconcile_candidate_count": report["reconcile_candidate_count"],
                },
            }
        )
    else:
        write_json(report)
    return 0


def command_capture_lines(args: argparse.Namespace) -> int:
    endpoint = validate_cdp_endpoint(args.cdp_endpoint)
    websocket_url, target = target_websocket_url(endpoint, target_id=args.target_id)
    capture = capture_visible_text(websocket_url, timeout_seconds=args.timeout)
    report = build_capture_report(endpoint=endpoint, target=target, capture=capture)
    if args.out:
        out_path = Path(args.out).expanduser().resolve()
    else:
        out_path = recon_dir(args.recon_dir) / "captures" / f"reconcile_capture_{utc_seconds()}.json"
    write_json_file(out_path, report)
    write_json(
        {
            "ok": True,
            "report": str(out_path),
            "summary": {
                "statement_line_count": report["statement_line_count"],
                "target": report["target"],
                "connected": True,
            },
        }
    )
    return 0


def command_dry_run(args: argparse.Namespace) -> int:
    endpoint = validate_cdp_endpoint(args.cdp_endpoint)
    expected = load_expected(args.expected)
    statement_lines = load_statement_lines(args.statement_lines, args.statement_text)
    report = build_dry_run_report(endpoint=endpoint, expected=expected, bank_account=args.bank_account, statement_lines=statement_lines)
    if args.out:
        out_path = Path(args.out).expanduser().resolve()
    else:
        out_path = recon_dir(args.recon_dir) / "dry-runs" / f"reconcile_dry_run_{utc_seconds()}.json"
    write_json_file(out_path, report)
    write_json(
        {
            "ok": True,
            "report": str(out_path),
            "summary": {
                "expected_count": len(expected),
                "statement_line_count": len(statement_lines),
                "connected": False,
                "matches": report["match_summary"],
                "suggested_apply_plan": report["suggested_apply_plan_summary"],
            },
        }
    )
    return 0


def command_verify(args: argparse.Namespace) -> int:
    """Read-only post-apply check: remaining statement-line ids + header balances."""
    endpoint = validate_cdp_endpoint(args.cdp_endpoint)
    websocket_url, target = target_websocket_url(endpoint, target_id=args.target_id)
    expression = r"""
(() => {
  const ids = Array.from(document.querySelectorAll('[data-statementlineid]'))
    .map((el) => el.getAttribute('data-statementlineid'))
    .filter(Boolean);
  const bodyText = (document.body.innerText || '').replace(/\s+/g, ' ');
  const balMatch = bodyText.match(/(\(?-?[\d,]+\.\d\d\)?) Statement Balance/);
  const xeroMatch = bodyText.match(/(\(?-?[\d,]+\.\d\d\)?) Balance in Xero/);
  const reconciledBadge = / Statement Balance Reconciled /.test(' ' + bodyText + ' ');
  return {
    ids,
    statement_balance: balMatch ? balMatch[1] : null,
    xero_balance: xeroMatch ? xeroMatch[1] : null,
    reconciled_badge: reconciledBadge
  };
})()
"""
    value = asyncio.run(cdp_evaluate(expression, websocket_url, timeout_seconds=args.timeout))
    if not isinstance(value, dict):
        raise ReconciliationError("CDP verify result was not a JSON object.")
    present_ids = [str(item) for item in (value.get("ids") or [])]
    requested = [str(item) for item in (args.statement_line_id or [])]
    line_checks = [{"statement_line_id": line_id, "gone": line_id not in present_ids} for line_id in requested]
    statement_balance = parse_balance_text(value.get("statement_balance"))
    xero_balance = parse_balance_text(value.get("xero_balance"))
    if statement_balance is not None and xero_balance is not None:
        balanced = abs(statement_balance - xero_balance) < 0.005
    else:
        # Fully reconciled accounts hide the Xero figure and show the badge.
        balanced = bool(value.get("reconciled_badge"))
    report = {
        "ok": all(check["gone"] for check in line_checks),
        "mode": "cdp-verify",
        "generated_at": utc_seconds(),
        "cdp_endpoint": redact_endpoint(endpoint),
        "connected": True,
        "login_automation": False,
        "credential_collection": False,
        "target": summarize_cdp_target(target) if target else None,
        "remaining_line_count": len(present_ids),
        "remaining_line_ids": present_ids,
        "line_checks": line_checks,
        "statement_balance": statement_balance,
        "xero_balance": xero_balance,
        "reconciled_badge": bool(value.get("reconciled_badge")),
        "balanced": balanced,
    }
    if args.out:
        write_json_file(Path(args.out).expanduser().resolve(), report)
    write_json(report)
    return 0 if report["ok"] else 2


def command_apply(args: argparse.Namespace) -> int:
    endpoint = validate_cdp_endpoint(args.cdp_endpoint)
    plan = load_reconciliation_plan(args.plan)
    apply_batch = getattr(args, "apply_batch", False)
    max_apply_lines = getattr(args, "max_apply_lines", None)
    if args.confirm_apply and len(plan) != 1 and not apply_batch:
        raise ReconciliationError(
            "Confirmed reconciliation apply is limited to exactly one line per invocation "
            "(pass --apply-batch to apply a reviewed multi-line plan)."
        )
    result = run_playwright_apply_engine(
        endpoint=endpoint,
        target_id=args.target_id,
        plan=plan,
        confirm_apply=args.confirm_apply,
        timeout_seconds=args.timeout,
        apply_batch=apply_batch,
        max_apply_lines=max_apply_lines,
    )
    safe_result = redact_report_value(result, endpoint=endpoint)
    report = {
        "ok": bool(safe_result.get("ok")) if isinstance(safe_result, dict) else False,
        "mode": "playwright-apply" if args.confirm_apply else "playwright-dry-run",
        "generated_at": utc_seconds(),
        "cdp_endpoint": redact_endpoint(endpoint),
        "connected": True,
        "requires_user_authenticated_browser": True,
        "login_automation": False,
        "credential_collection": False,
        "storage_access": False,
        "cookies_access": False,
        "plan": plan,
        "result": safe_result,
        "summary": (safe_result.get("summary") or {}) if isinstance(safe_result, dict) else {},
    }
    if args.out:
        out_path = Path(args.out).expanduser().resolve()
    else:
        out_path = recon_dir(args.recon_dir) / "apply" / f"reconcile_apply_{utc_seconds()}.json"
    write_json_file(out_path, report)
    write_json(
        {
            "ok": report["ok"],
            "report": str(out_path),
            "summary": report["summary"],
            "dry_run": not args.confirm_apply,
        }
    )
    return 0 if report["ok"] else 2


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="xero-reconcile", description="CDP-only Xero reconciliation companion")
    sub = parser.add_subparsers(dest="command", required=True)

    status = sub.add_parser("status", help="Show reconciliation companion capabilities and safety boundary")
    status.add_argument("--recon-dir", help="Override reconciliation artifact directory")
    status.set_defaults(func=command_status)

    inspect = sub.add_parser("inspect", help="Inspect user-provided CDP target list for Xero/Reconcile tabs")
    inspect.add_argument("--cdp-endpoint", required=True, help="User-provided already-authenticated browser CDP endpoint")
    inspect.add_argument("--out", help="Write inspection report to this JSON file")
    inspect.set_defaults(func=command_inspect)

    capture = sub.add_parser("capture-lines", help="Read visible text from an already-open Xero Reconcile page and parse statement-line candidates")
    capture.add_argument("--cdp-endpoint", required=True, help="User-provided already-authenticated browser CDP endpoint")
    capture.add_argument("--target-id", help="Specific CDP page target id from `xero-reconcile inspect`")
    capture.add_argument("--timeout", type=int, default=10, help="CDP websocket timeout in seconds")
    capture.add_argument("--out", help="Write capture report to this JSON file")
    capture.add_argument("--recon-dir", help="Override reconciliation artifact directory")
    capture.set_defaults(func=command_capture_lines)

    dry_run = sub.add_parser("dry-run", help="Create a bounded reconciliation preflight report")
    dry_run.add_argument("--cdp-endpoint", required=True, help="User-provided already-authenticated browser CDP endpoint")
    dry_run.add_argument("--expected", help="JSON array or object with expected/candidates array")
    dry_run.add_argument("--statement-lines", help="JSON array or object with visible statement_lines/lines from a Reconcile snapshot")
    dry_run.add_argument("--statement-text", help="Plain-text visible Reconcile-tab snapshot to parse into statement-line candidates")
    dry_run.add_argument("--bank-account", help="Optional Xero bank account label for operator context")
    dry_run.add_argument("--out", help="Write report to this JSON file")
    dry_run.add_argument("--recon-dir", help="Override reconciliation artifact directory")
    dry_run.set_defaults(func=command_dry_run)

    verify = sub.add_parser("verify", help="Read-only check of the open Reconcile tab: remaining statement lines and header balances")
    verify.add_argument("--cdp-endpoint", required=True, help="User-provided already-authenticated browser CDP endpoint")
    verify.add_argument("--target-id", help="Specific CDP page target id from `xero-reconcile inspect`")
    verify.add_argument("--statement-line-id", action="append", help="Assert this statement line id is GONE from the queue (repeatable)")
    verify.add_argument("--timeout", type=int, default=15, help="CDP websocket timeout in seconds")
    verify.add_argument("--out", help="Write verify report to this JSON file")
    verify.set_defaults(func=command_verify)

    apply = sub.add_parser("apply", help="Run the Playwright BankRec apply engine against reviewed line intents")
    apply.add_argument("--cdp-endpoint", required=True, help="User-provided already-authenticated browser CDP endpoint")
    apply.add_argument("--target-id", help="Specific CDP page target id from `xero-reconcile inspect`")
    apply.add_argument("--plan", required=True, help="JSON array/object of reviewed reconciliation line intents")
    apply.add_argument("--confirm-apply", action="store_true", help="Allow the engine to click row-scoped OK after hidden-field guards pass; omitted means fill/verify dry-run only")
    apply.add_argument("--apply-batch", action="store_true", help="With --confirm-apply: allow a reviewed multi-line plan in one browser session (per-line guards still apply; one failed line does not abandon the rest)")
    apply.add_argument("--max-apply-lines", type=int, default=None, help="Safety cap for --apply-batch (engine default 25)")
    apply.add_argument("--timeout", type=int, default=30, help="Playwright operation timeout in seconds")
    apply.add_argument("--out", help="Write apply audit report to this JSON file")
    apply.add_argument("--recon-dir", help="Override reconciliation artifact directory")
    apply.set_defaults(func=command_apply)
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return int(args.func(args))
    except ReconciliationError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
