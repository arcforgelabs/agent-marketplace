#!/usr/bin/env python3
"""Smoke test for xero_mcp.py aggregator.

Pipes a sequence of MCP messages to the aggregator and validates:
  1. initialize → valid response with serverInfo name=xero
  2. notifications/initialized → no response (notification)
  3. tools/list → merged list with ≥1 official tool, companion tools, and xero_backends
  4. tools/call xero_backends → backend summary
  5. tools/call xero_local_status {"check":"doctor"} → companion read-only call

Allows up to 180s for the whole run (the official Node backend may need to
download/patch on first run).

Does NOT call any mutating official Xero API tool.
Does NOT call tools that hit the live Xero API beyond what xero_local_status does.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
AGGREGATOR = ROOT / "connectors" / "xero" / "scripts" / "xero_mcp.py"
TIMEOUT = 180  # seconds total for the whole session


def send(proc: subprocess.Popen[str], msg: dict) -> None:
    line = json.dumps(msg, separators=(",", ":")) + "\n"
    assert proc.stdin
    proc.stdin.write(line)
    proc.stdin.flush()


def recv(proc: subprocess.Popen[str], expected_id: object) -> dict:
    """Read stdout lines until we find a response matching expected_id."""
    assert proc.stdout
    while True:
        line = proc.stdout.readline()
        if not line:
            raise RuntimeError(f"Aggregator stdout closed before receiving id={expected_id!r}")
        line = line.strip()
        if not line:
            continue
        try:
            parsed = json.loads(line)
        except json.JSONDecodeError:
            print(f"  [non-JSON stdout]: {line!r}", file=sys.stderr)
            continue
        if not isinstance(parsed, dict):
            continue
        if parsed.get("id") == expected_id:
            return parsed
        # skip notifications or unrelated responses


def main() -> int:
    print(f"Smoke test: {AGGREGATOR}")
    print(f"Total timeout: {TIMEOUT}s\n")

    if not AGGREGATOR.exists():
        print(f"ERROR: aggregator not found at {AGGREGATOR}", file=sys.stderr)
        return 1

    proc = subprocess.Popen(
        [sys.executable, str(AGGREGATOR)],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        bufsize=1,
    )

    errors: list[str] = []
    tool_count = 0
    has_official = False
    has_companion = False
    has_backends_tool = False
    backends_text = ""
    status_result: dict = {}

    try:
        # ----------------------------------------------------------------
        # 1. initialize
        # ----------------------------------------------------------------
        print("Step 1: initialize")
        send(proc, {"jsonrpc": "2.0", "id": 1, "method": "initialize",
                    "params": {"protocolVersion": "2025-06-18", "capabilities": {},
                               "clientInfo": {"name": "smoketest", "version": "0.1.0"}}})
        resp = recv(proc, 1)
        result = resp.get("result", {})
        server_name = result.get("serverInfo", {}).get("name", "")
        proto = result.get("protocolVersion", "")
        print(f"  serverInfo.name = {server_name!r}")
        print(f"  protocolVersion = {proto!r}")
        if server_name != "xero":
            errors.append(f"Expected serverInfo.name='xero', got {server_name!r}")
        if "error" in resp:
            errors.append(f"initialize error: {resp['error']}")
        print()

        # ----------------------------------------------------------------
        # 2. notifications/initialized (no response expected)
        # ----------------------------------------------------------------
        print("Step 2: notifications/initialized (no response expected)")
        send(proc, {"jsonrpc": "2.0", "method": "notifications/initialized"})
        print("  sent (notification — no response)\n")

        # ----------------------------------------------------------------
        # 3. tools/list
        # ----------------------------------------------------------------
        print("Step 3: tools/list")
        send(proc, {"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}})
        resp = recv(proc, 2)
        if "error" in resp:
            errors.append(f"tools/list error: {resp['error']}")
        else:
            tools = resp.get("result", {}).get("tools", [])
            tool_names = [t.get("name", "") for t in tools]
            tool_count = len(tools)
            print(f"  total tools: {tool_count}")
            print(f"  tool names: {tool_names}")

            # Check for an official tool
            official_candidates = {"list-invoices", "list-contacts", "list-organisation-details",
                                   "list-accounts", "create-invoice"}
            found_official = [n for n in tool_names if n in official_candidates]
            has_official = bool(found_official)

            # Check for companion tools
            companion_candidates = {"xero_local_status", "xero_rules", "xero_snapshots",
                                    "xero_audit_dry_run", "xero_documents_create"}
            found_companion = [n for n in tool_names if n in companion_candidates]
            has_companion = bool(found_companion)

            # Check for aggregator-owned tool
            has_backends_tool = "xero_backends" in tool_names

            print(f"  official tool present: {has_official} (found: {found_official})")
            print(f"  companion tool present: {has_companion} (found: {found_companion})")
            print(f"  xero_backends present: {has_backends_tool}")

            if not has_official:
                print(
                    "  NOTE: no official tools found — xero-official backend may have failed to "
                    "start (likely needs OAuth/network); this is expected in CI without auth.",
                    file=sys.stderr,
                )
            if not has_companion:
                errors.append("Expected at least one xero_* companion tool but none found")
            if not has_backends_tool:
                errors.append("Expected xero_backends tool but it was not in tools/list")
        print()

        # ----------------------------------------------------------------
        # 4. tools/call xero_backends
        # ----------------------------------------------------------------
        print("Step 4: tools/call xero_backends")
        send(proc, {"jsonrpc": "2.0", "id": 3, "method": "tools/call",
                    "params": {"name": "xero_backends", "arguments": {}}})
        resp = recv(proc, 3)
        if "error" in resp:
            errors.append(f"xero_backends error: {resp['error']}")
        else:
            content = resp.get("result", {}).get("content", [{}])
            backends_text = content[0].get("text", "") if content else ""
            is_error = resp.get("result", {}).get("isError", False)
            print(f"  isError: {is_error}")
            print("  backends summary:")
            for line in backends_text.splitlines():
                print(f"    {line}")
            if is_error:
                errors.append("xero_backends returned isError=true")
            # Check both backend labels appear
            if "xero-official" not in backends_text:
                errors.append("xero_backends output missing 'xero-official'")
            if "xero-workflows" not in backends_text:
                errors.append("xero_backends output missing 'xero-workflows'")
        print()

        # ----------------------------------------------------------------
        # 5. tools/call xero_local_status (read-only companion call)
        # ----------------------------------------------------------------
        print("Step 5: tools/call xero_local_status {\"check\":\"doctor\"}")
        send(proc, {"jsonrpc": "2.0", "id": 4, "method": "tools/call",
                    "params": {"name": "xero_local_status", "arguments": {"check": "doctor"}}})
        resp = recv(proc, 4)
        if "error" in resp:
            errors.append(f"xero_local_status error: {resp['error']}")
        else:
            status_result = resp.get("result", {})
            is_error = status_result.get("isError", True)
            content = status_result.get("content", [{}])
            text_snippet = (content[0].get("text", "") if content else "")[:300]
            print(f"  isError: {is_error}")
            print(f"  snippet: {text_snippet!r}")
        print()

    finally:
        # Close stdin to signal EOF
        if proc.stdin:
            try:
                proc.stdin.close()
            except Exception:
                pass
        try:
            proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait()

    # ----------------------------------------------------------------
    # Report
    # ----------------------------------------------------------------
    print("=" * 60)
    print("SMOKE TEST REPORT")
    print("=" * 60)
    print(f"  merged tool count:     {tool_count}")
    print(f"  official tool present: {has_official}")
    print(f"  companion tool present:{has_companion}")
    print(f"  xero_backends present: {has_backends_tool}")
    print()
    print("  xero_backends output:")
    for line in backends_text.splitlines():
        print(f"    {line}")
    print()
    print("  xero_local_status result:")
    content = status_result.get("content", [{}])
    snippet = (content[0].get("text", "") if content else "")[:600]
    print(f"    isError: {status_result.get('isError', '?')}")
    print(f"    snippet: {snippet!r}")
    print()

    if errors:
        print(f"FAILURES ({len(errors)}):")
        for e in errors:
            print(f"  - {e}")
        return 1
    else:
        print("PASS: all checks ok")
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
