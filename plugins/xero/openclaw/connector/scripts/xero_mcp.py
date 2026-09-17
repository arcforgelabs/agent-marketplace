#!/usr/bin/env python3
"""xero: single public MCP aggregator for the Arc Forge Xero plugin.

This is the single public `xero` MCP server. Under the hood it proxies two
clearly-named backends:

  xero-official   — upstream Node API server (@xeroapi/xero-mcp-server) run
                    through the Arc Forge local OAuth token provider + rate
                    governance. Launched via connectors/xero/mcp/xero-mcp-local.
  xero-workflows  — Arc Forge Python companion server for finance-rule checks,
                    dry-run/audit, snapshots, and CDP reconciliation. Launched
                    via connectors/xero/mcp/xero-workflows-mcp.

Tool names are flat and unprefixed:
  • official tools: list-invoices, list-contacts, create-invoice, etc.
  • companion tools: xero_local_status, xero_rules, xero_snapshots, etc.

Use the `xero_backends` tool to see which tool comes from which backend, with
backend status, identity, and tool counts.
"""

from __future__ import annotations

import json
import os
import queue
import subprocess
import sys
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import xero_profiles

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

SERVER_NAME = "xero"
SERVER_VERSION = "0.1.0"
PROTOCOL_VERSION_DEFAULT = "2025-06-18"
HANDSHAKE_TIMEOUT = 120  # seconds — the official Node server may download/patch on first run

_MODULE_ROOT = Path(__file__).resolve().parents[1]  # connectors/xero

# The two backend kinds every business exposes. Per-business instances are
# built from these in _build_backends(), each with its own env overlay so the
# official Node server's `xero auth token` call reads the right token store.
BACKEND_KINDS: list[dict[str, Any]] = [
    {
        "label": "xero-official",
        "argv": [str(_MODULE_ROOT / "mcp" / "xero-mcp-local"), "run"],
        "desc": (
            "Official @xeroapi/xero-mcp-server via Arc Forge local OAuth token "
            "provider + rate governance (Node)."
        ),
    },
    {
        "label": "xero-workflows",
        "argv": [str(_MODULE_ROOT / "mcp" / "xero-workflows-mcp"), "run"],
        "desc": (
            "Arc Forge companion: finance-rule checks, dry-run/audit, snapshots, "
            "CDP reconciliation (Python)."
        ),
    },
]


@dataclass
class BusinessPlan:
    """One business to expose: its identity, tool-name prefix, and env overlay."""

    key: str
    label: str
    prefix: str
    env_overlay: dict[str, str] = field(default_factory=dict)


def _plan_businesses() -> list[BusinessPlan]:
    """Resolve which businesses to expose and how to namespace their tools.

    No registry file → a single legacy business with NO prefix and NO env
    overlay, i.e. byte-identical to the original single-business aggregator
    (the .mcp.json-provided env flows through untouched). With a registry,
    each business gets its own env overlay; two or more businesses force a
    per-business tool-name prefix so no bare/ambiguous tool can exist.
    """
    try:
        registry = xero_profiles.load_registry()
    except Exception as exc:  # malformed/duplicate/>1-legacy registry
        # A bad registry must not take down every Xero tool. Degrade to the
        # single legacy business and report loudly on stderr.
        print(
            f"[xero-aggregator] WARNING: business registry unreadable ({exc}); "
            "falling back to single legacy business",
            file=sys.stderr,
        )
        registry = None
    if registry is None or not registry.profiles:
        profiles = [xero_profiles.implicit_default_profile()]
    else:
        profiles = registry.profiles
    assigned = xero_profiles.assign_prefixes(profiles)
    single = len(assigned) == 1
    plans: list[BusinessPlan] = []
    for profile, prefix in assigned:
        # No env overlay for the lone legacy business: defer to ambient
        # .mcp.json env so behaviour stays byte-identical to the no-registry
        # default. Isolated or multiple businesses must pin their own stores.
        if registry is None or (single and profile.legacy):
            overlay: dict[str, str] = {}
        else:
            # CRITICAL: pin XERO_PROFILE alongside the path vars. The backends
            # shell out to the `xero` CLI (auth token / workflows), which runs
            # apply_profile_env(); without XERO_PROFILE it re-resolves to the
            # registry DEFAULT profile and os.environ.update() clobbers the
            # inherited per-business paths — so every call silently hits the
            # default org. Setting XERO_PROFILE makes the subprocess resolve
            # THIS business and pin the correct store/rules.
            overlay = {**profile.env(), xero_profiles.PROFILE_ENV: profile.key}
        plans.append(
            BusinessPlan(key=profile.key, label=profile.label, prefix=prefix, env_overlay=overlay)
        )
    return plans


def _public_name(prefix: str, name: str) -> str:
    return f"{prefix}__{name}" if prefix else name

# ---------------------------------------------------------------------------
# Backend
# ---------------------------------------------------------------------------


_READER_EOF_SENTINEL = object()  # placed in rx_queue when child stdout closes


class Backend:
    """Wraps one child MCP server subprocess."""

    def __init__(
        self,
        label: str,
        argv: list[str],
        desc: str,
        *,
        business_key: str = xero_profiles.IMPLICIT_DEFAULT_KEY,
        business_label: str = "Default (legacy)",
        prefix: str = "",
        env_overlay: dict[str, str] | None = None,
    ) -> None:
        self.label = label
        self.argv = argv
        self.desc = desc
        self.business_key = business_key
        self.business_label = business_label
        self.prefix = prefix
        self.env_overlay = env_overlay or {}
        self.status: str = "idle"  # idle | up | error | down
        self.error_message: str = ""
        self.tools: list[dict[str, Any]] = []
        self.child_server_info: dict[str, str] = {}
        self._child: subprocess.Popen[str] | None = None
        self._lock = threading.Lock()
        self._req_counter = 0
        # Single persistent reader thread state
        self._rx_queue: queue.Queue[str | object] = queue.Queue()
        self._pending: dict[object, dict[str, Any]] = {}  # id -> parsed response stash

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def start(self) -> None:
        """Start the child process and perform the MCP handshake."""
        try:
            self._child = subprocess.Popen(
                self.argv,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                bufsize=1,
                env={**os.environ.copy(), **self.env_overlay},
            )
        except Exception as exc:
            self.status = "error"
            self.error_message = f"Failed to start process: {exc}"
            print(f"[xero-aggregator] backend {self.label!r} start error: {exc}", file=sys.stderr)
            return

        # Launch one persistent reader daemon thread that drains child stdout.
        reader = threading.Thread(target=self._reader_loop, daemon=True)
        reader.start()

        try:
            self._handshake()
        except Exception as exc:
            self.status = "error"
            self.error_message = f"Handshake failed: {exc}"
            print(f"[xero-aggregator] backend {self.label!r} handshake error: {exc}", file=sys.stderr)
            if self._child.poll() is None:
                try:
                    self._child.terminate()
                except Exception:
                    pass

    def _reader_loop(self) -> None:
        """Daemon thread: drain child stdout and push every line to _rx_queue."""
        try:
            assert self._child and self._child.stdout
            for line in self._child.stdout:
                self._rx_queue.put(line)
        except Exception:
            pass
        finally:
            self._rx_queue.put(_READER_EOF_SENTINEL)

    def _read_response(self, target_id: object, timeout: float) -> dict[str, Any]:
        """Pull lines from _rx_queue until we find the response for target_id.

        Out-of-order id responses are stashed in _pending for future calls.
        Notifications (no 'id') and non-JSON lines are logged and skipped.
        """
        # Fast path: already buffered.
        if target_id in self._pending:
            return self._pending.pop(target_id)

        deadline = time.monotonic() + timeout
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise TimeoutError(
                    f"Backend {self.label!r} did not respond within {timeout}s for id={target_id!r}"
                )
            try:
                item = self._rx_queue.get(timeout=min(remaining, 5.0))
            except queue.Empty:
                continue

            if item is _READER_EOF_SENTINEL:
                # Put it back so subsequent calls also see EOF.
                self._rx_queue.put(_READER_EOF_SENTINEL)
                raise RuntimeError(f"Backend {self.label!r} stdout closed unexpectedly")

            line = str(item).strip()
            if not line:
                continue
            try:
                parsed = json.loads(line)
            except json.JSONDecodeError:
                print(f"[xero-aggregator] backend {self.label!r} non-JSON stdout: {line!r}", file=sys.stderr)
                continue
            if not isinstance(parsed, dict):
                continue

            msg_id = parsed.get("id")
            if "id" not in parsed:
                # Notification — skip silently (no id field at all).
                continue
            if msg_id == target_id:
                return parsed
            # Out-of-order response for a different pending request — stash it.
            self._pending[msg_id] = parsed

    def _handshake(self) -> None:
        """Send initialize, notifications/initialized, tools/list."""
        # initialize
        init_msg = {
            "jsonrpc": "2.0",
            "id": "__init__",
            "method": "initialize",
            "params": {
                "protocolVersion": PROTOCOL_VERSION_DEFAULT,
                "capabilities": {},
                "clientInfo": {"name": "xero-aggregator", "version": SERVER_VERSION},
            },
        }
        self._write_message(init_msg)
        init_resp = self._read_response("__init__", timeout=HANDSHAKE_TIMEOUT)
        result = init_resp.get("result", {})
        info = result.get("serverInfo", {})
        self.child_server_info = {
            "name": str(info.get("name", self.label)),
            "version": str(info.get("version", "?")),
        }

        # notifications/initialized (no response expected)
        self._write_message({"jsonrpc": "2.0", "method": "notifications/initialized"})

        # tools/list
        tools_msg = {"jsonrpc": "2.0", "id": "__tools__", "method": "tools/list", "params": {}}
        self._write_message(tools_msg)
        tools_resp = self._read_response("__tools__", timeout=HANDSHAKE_TIMEOUT)
        self.tools = tools_resp.get("result", {}).get("tools", [])
        self.status = "up"
        print(
            f"[xero-aggregator] backend {self.label!r} up: "
            f"{self.child_server_info.get('name')} {self.child_server_info.get('version')}, "
            f"{len(self.tools)} tools",
            file=sys.stderr,
        )

    def is_alive(self) -> bool:
        return self._child is not None and self._child.poll() is None

    def _write_message(self, msg: dict[str, Any]) -> None:
        assert self._child and self._child.stdin
        line = json.dumps(msg, separators=(",", ":")) + "\n"
        self._child.stdin.write(line)
        self._child.stdin.flush()

    # ------------------------------------------------------------------
    # Per-call request
    # ------------------------------------------------------------------

    def request(self, method: str, params: dict[str, Any], timeout: float = 120.0) -> dict[str, Any]:
        """Send a JSON-RPC request to the child and return its response."""
        if not self.is_alive():
            self.status = "down"
            raise RuntimeError(f"Backend {self.label!r} process is not running")
        with self._lock:
            self._req_counter += 1
            req_id = f"agg-{self._req_counter}"
            self._write_message({"jsonrpc": "2.0", "id": req_id, "method": method, "params": params})
            return self._read_response(req_id, timeout=timeout)


# ---------------------------------------------------------------------------
# Aggregator state (module-level singletons)
# ---------------------------------------------------------------------------

def _build_backends() -> list[Backend]:
    backends: list[Backend] = []
    for plan in _plan_businesses():
        for kind in BACKEND_KINDS:
            backends.append(
                Backend(
                    label=kind["label"],
                    argv=kind["argv"],
                    desc=kind["desc"],
                    business_key=plan.key,
                    business_label=plan.label,
                    prefix=plan.prefix,
                    env_overlay=plan.env_overlay,
                )
            )
    return backends


_backends: list[Backend] = _build_backends()
_tool_index: dict[str, tuple[Backend, str]] = {}  # public tool name -> (backend, real name)
_started = False
_start_lock = threading.Lock()


def _ensure_started() -> None:
    global _started
    with _start_lock:
        if _started:
            return
        _started = True
        print("[xero-aggregator] starting backends...", file=sys.stderr)
        for backend in _backends:
            try:
                backend.start()
            except Exception as exc:
                backend.status = "error"
                backend.error_message = str(exc)
                print(f"[xero-aggregator] backend {backend.label!r} failed: {exc}", file=sys.stderr)

        # Build tool index — first backend wins on collision. Public names are
        # prefixed per business when more than one business is exposed.
        for backend in _backends:
            if backend.status != "up":
                continue
            for tool in backend.tools:
                name = tool.get("name", "")
                if not name:
                    continue
                public = _public_name(backend.prefix, name)
                if public in _tool_index:
                    existing, _real = _tool_index[public]
                    print(
                        f"[xero-aggregator] WARNING: tool {public!r} exists in both "
                        f"{existing.label!r} and {backend.label!r}; "
                        f"keeping {existing.label!r}",
                        file=sys.stderr,
                    )
                else:
                    _tool_index[public] = (backend, name)
        print(
            f"[xero-aggregator] ready: {len(_tool_index)} tools from "
            f"{sum(1 for b in _backends if b.status == 'up')} backends",
            file=sys.stderr,
        )


# ---------------------------------------------------------------------------
# Aggregator-owned tool: xero_backends
# ---------------------------------------------------------------------------

XERO_BACKENDS_TOOL: dict[str, Any] = {
    "name": "xero_backends",
    "description": (
        "List the Xero MCP backends behind this server (official API vs workflows "
        "companion), their status, identity, and which tools each provides."
    ),
    "inputSchema": {"type": "object", "properties": {}, "additionalProperties": False},
    "annotations": {"readOnlyHint": True, "openWorldHint": False},
}


def _ordered_businesses() -> list[tuple[str, str, str]]:
    """Unique (key, label, prefix) tuples in backend declaration order."""
    seen: set[str] = set()
    out: list[tuple[str, str, str]] = []
    for b in _backends:
        if b.business_key in seen:
            continue
        seen.add(b.business_key)
        out.append((b.business_key, b.business_label, b.prefix))
    return out


def _call_xero_backends() -> dict[str, Any]:
    businesses = _ordered_businesses()
    multi = len(businesses) > 1
    header = (
        f"xero aggregator v{SERVER_VERSION} — {len(businesses)} business(es), "
        f"{len(_backends)} backends"
    )
    lines: list[str] = [header]
    if multi:
        lines.append("Tools are prefixed per business: <business>__<tool>.")
    else:
        lines.append("Single business: tool names are unprefixed.")
    lines.append("")
    for key, label, prefix in businesses:
        tag = f"{prefix}__" if prefix else "(no prefix)"
        lines.append(f"Business: {label}  [{key}]  tool prefix: {tag}")
        for b in _backends:
            if b.business_key != key:
                continue
            lines.append(f"  Backend: {b.label}")
            lines.append(f"    desc:    {b.desc}")
            lines.append(f"    status:  {b.status}")
            if b.status == "up":
                lines.append(
                    f"    server:  {b.child_server_info.get('name')} {b.child_server_info.get('version')}"
                )
                lines.append(f"    tools ({len(b.tools)}):")
                for t in b.tools:
                    lines.append(f"      - {_public_name(b.prefix, t.get('name', '?'))}")
            elif b.status == "error":
                lines.append(f"    error:   {b.error_message}")
            elif b.status == "down":
                lines.append("    (process has exited)")
        lines.append("")
    text = "\n".join(lines)
    return {"content": [{"type": "text", "text": text}], "isError": False}


# ---------------------------------------------------------------------------
# JSON-RPC helpers
# ---------------------------------------------------------------------------

def _response(req_id: Any, result: Any = None, error: dict[str, Any] | None = None) -> dict[str, Any]:
    payload: dict[str, Any] = {"jsonrpc": "2.0", "id": req_id}
    if error is not None:
        payload["error"] = error
    else:
        payload["result"] = result
    return payload


def _merged_tools() -> list[dict[str, Any]]:
    """Return flat merged tool list: all backends + xero_backends.

    When tools are prefixed (multi-business), each tool is emitted under its
    public name and its description is tagged with the business label so the
    target entity is unmistakable in a tool listing.
    """
    seen: set[str] = set()
    tools: list[dict[str, Any]] = []
    for b in _backends:
        if b.status != "up":
            continue
        for t in b.tools:
            name = t.get("name", "")
            if not name:
                continue
            public = _public_name(b.prefix, name)
            if public in seen:
                continue
            seen.add(public)
            if b.prefix:
                tool = dict(t)
                tool["name"] = public
                desc = tool.get("description", "")
                tool["description"] = f"[{b.business_label}] {desc}".rstrip()
                tools.append(tool)
            else:
                tools.append(t)
    # Always append aggregator-owned tool last
    tools.append(XERO_BACKENDS_TOOL)
    return tools


# ---------------------------------------------------------------------------
# Request handler
# ---------------------------------------------------------------------------

def _handle(message: dict[str, Any]) -> dict[str, Any] | None:
    method = message.get("method")
    req_id = message.get("id")  # None for notifications

    # Notifications: absorb silently
    if req_id is None:
        return None

    try:
        if method == "initialize":
            _ensure_started()
            client_proto = message.get("params", {}).get("protocolVersion", PROTOCOL_VERSION_DEFAULT)
            return _response(
                req_id,
                {
                    "protocolVersion": client_proto,
                    "capabilities": {"tools": {}},
                    "serverInfo": {"name": SERVER_NAME, "version": SERVER_VERSION},
                },
            )

        if method == "ping":
            return _response(req_id, {})

        if method == "tools/list":
            _ensure_started()
            return _response(req_id, {"tools": _merged_tools()})

        if method == "tools/call":
            _ensure_started()
            params = message.get("params") or {}
            tool_name = params.get("name", "")
            arguments = params.get("arguments") or {}

            if tool_name == "xero_backends":
                return _response(req_id, _call_xero_backends())

            entry = _tool_index.get(tool_name)
            if entry is None:
                return _response(
                    req_id,
                    error={"code": -32601, "message": f"Tool not found: {tool_name!r}"},
                )
            backend, real_name = entry
            # Forward under the backend's real (unprefixed) tool name.
            if real_name != tool_name:
                params = {**params, "name": real_name}

            if not backend.is_alive():
                backend.status = "down"
                return _response(
                    req_id,
                    {
                        "content": [
                            {
                                "type": "text",
                                "text": (
                                    f"Backend {backend.label!r} is down and cannot serve "
                                    f"tool {tool_name!r}."
                                ),
                            }
                        ],
                        "isError": True,
                    },
                )

            try:
                child_resp = backend.request("tools/call", params, timeout=120.0)
            except Exception as exc:
                return _response(
                    req_id,
                    {
                        "content": [
                            {
                                "type": "text",
                                "text": (
                                    f"Backend {backend.label!r} error calling {tool_name!r}: {exc}"
                                ),
                            }
                        ],
                        "isError": True,
                    },
                )
            # Forward the child's result verbatim
            if "error" in child_resp:
                return _response(req_id, error=child_resp["error"])
            return _response(req_id, child_resp.get("result", {}))

        # Unknown method
        return _response(req_id, error={"code": -32601, "message": f"Method not found: {method}"})

    except Exception as exc:
        print(f"[xero-aggregator] handler exception for method={method!r}: {exc}", file=sys.stderr)
        return _response(req_id, error={"code": -32603, "message": f"Internal error: {exc}"})


# ---------------------------------------------------------------------------
# Main stdio loop
# ---------------------------------------------------------------------------

def _terminate_backends() -> None:
    """Gracefully terminate all child processes."""
    for b in _backends:
        child = b._child
        if child is None or child.poll() is not None:
            continue
        try:
            child.terminate()
        except Exception:
            pass
    # Give a short grace period then kill
    deadline = time.monotonic() + 3.0
    for b in _backends:
        child = b._child
        if child is None:
            continue
        remaining = max(0.0, deadline - time.monotonic())
        try:
            child.wait(timeout=remaining)
        except subprocess.TimeoutExpired:
            try:
                child.kill()
            except Exception:
                pass


def main() -> int:
    print(f"[xero-aggregator] {SERVER_NAME} v{SERVER_VERSION} starting on stdio", file=sys.stderr)
    try:
        for raw in sys.stdin:
            raw = raw.strip()
            if not raw:
                continue
            try:
                message = json.loads(raw)
            except json.JSONDecodeError as exc:
                out = _response(None, error={"code": -32700, "message": f"Parse error: {exc}"})
                print(json.dumps(out, separators=(",", ":")), flush=True)
                continue
            if not isinstance(message, dict):
                out = _response(None, error={"code": -32600, "message": "Invalid request"})
                print(json.dumps(out, separators=(",", ":")), flush=True)
                continue
            try:
                reply = _handle(message)
            except Exception as exc:
                req_id = message.get("id")
                reply = _response(req_id, error={"code": -32603, "message": f"Internal error: {exc}"})
            if reply is not None:
                print(json.dumps(reply, separators=(",", ":")), flush=True)
    finally:
        print("[xero-aggregator] stdin closed; terminating backends", file=sys.stderr)
        _terminate_backends()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
