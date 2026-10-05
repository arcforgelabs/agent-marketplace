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

import itertools
import json
import os
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


_READER_EOF = object()  # delivered to every waiter when child stdout closes

# Bound concurrent in-flight calls per backend child. Xero's own per-tenant
# concurrency cap is enforced by the rate governor inside the official child;
# this only keeps one runaway client from queueing unbounded work.
MAX_INFLIGHT_PER_BACKEND = int(os.environ.get("ARC_FORGE_XERO_MCP_MAX_INFLIGHT", "8"))
RESTART_BACKOFF_MIN = 1.0
RESTART_BACKOFF_MAX = 30.0


class _Waiter:
    __slots__ = ("event", "response")

    def __init__(self) -> None:
        self.event = threading.Event()
        self.response: dict[str, Any] | object | None = None


class Backend:
    """Wraps one child MCP server subprocess.

    Safe for concurrent callers: writes are serialised by one lock, a single
    reader thread routes each response to the waiter registered for its id, and
    a crashed child is restarted (with backoff) on the next request.
    """

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
        self.restarts = 0
        self._closing = False
        self._child: subprocess.Popen[str] | None = None
        self._write_lock = threading.Lock()
        self._lifecycle_lock = threading.Lock()
        self._waiters_lock = threading.Lock()
        self._waiters: dict[str, _Waiter] = {}
        self._req_counter = itertools.count(1)
        self._inflight = threading.BoundedSemaphore(MAX_INFLIGHT_PER_BACKEND)
        self._next_start_at = 0.0
        self._backoff = RESTART_BACKOFF_MIN
        self.on_tools_changed: Any = None  # callable() set by the aggregator

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def start(self) -> None:
        """Start the child process and perform the MCP handshake."""
        with self._lifecycle_lock:
            self._start_locked()

    def _start_locked(self) -> None:
        self._next_start_at = time.monotonic() + self._backoff
        try:
            child = subprocess.Popen(
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
            self._backoff = min(self._backoff * 2, RESTART_BACKOFF_MAX)
            print(f"[xero-aggregator] backend {self.label!r} start error: {exc}", file=sys.stderr)
            return
        # Each child generation gets its own waiter table, so a dying child's
        # reader can only fail its own calls, never a restarted child's.
        waiters: dict[str, _Waiter] = {}
        with self._waiters_lock:
            self._waiters = waiters
        self._child = child
        threading.Thread(target=self._reader_loop, args=(child, waiters), daemon=True).start()
        threading.Thread(target=self._stderr_loop, args=(child,), daemon=True).start()

        try:
            self._handshake()
        except Exception as exc:
            self.status = "error"
            self.error_message = f"Handshake failed: {exc}"
            self._backoff = min(self._backoff * 2, RESTART_BACKOFF_MAX)
            print(f"[xero-aggregator] backend {self.label!r} handshake error: {exc}", file=sys.stderr)
            if child.poll() is None:
                try:
                    child.terminate()
                except Exception:
                    pass
            return
        self._backoff = RESTART_BACKOFF_MIN

    def _reader_loop(self, child: subprocess.Popen[str], waiters: dict[str, _Waiter]) -> None:
        """Daemon thread: route each child stdout response to its waiter."""
        try:
            assert child.stdout
            for line in child.stdout:
                line = line.strip()
                if not line:
                    continue
                try:
                    parsed = json.loads(line)
                except json.JSONDecodeError:
                    print(f"[xero-aggregator] backend {self.label!r} non-JSON stdout line ignored", file=sys.stderr)
                    continue
                if not isinstance(parsed, dict) or "id" not in parsed:
                    continue  # notification or junk
                with self._waiters_lock:
                    waiter = waiters.pop(str(parsed.get("id")), None)
                if waiter is not None:
                    waiter.response = parsed
                    waiter.event.set()
        except Exception:
            pass
        finally:
            unexpected = self._child is child and not self._closing
            if unexpected:
                self.status = "down"
            with self._waiters_lock:
                orphans = list(waiters.values())
                waiters.clear()
            for waiter in orphans:
                waiter.response = _READER_EOF
                waiter.event.set()
            if unexpected:
                # Restart proactively: tools stay listed while down, but an
                # agent should not have to trip over a failed call first.
                threading.Thread(target=self._restart_after_backoff, daemon=True).start()

    def _restart_after_backoff(self) -> None:
        while not self._closing and not self.ensure_running():
            time.sleep(max(0.2, self._next_start_at - time.monotonic()))

    def _stderr_loop(self, child: subprocess.Popen[str]) -> None:
        """Drain child stderr so a chatty child can never block on a full pipe."""
        try:
            assert child.stderr
            for line in child.stderr:
                sys.stderr.write(f"[{self.label}] {line}")
        except Exception:
            pass

    def _handshake(self) -> None:
        """Send initialize, notifications/initialized, tools/list."""
        init_resp = self._roundtrip(
            "initialize",
            {
                "protocolVersion": PROTOCOL_VERSION_DEFAULT,
                "capabilities": {},
                "clientInfo": {"name": "xero-aggregator", "version": SERVER_VERSION},
            },
            timeout=HANDSHAKE_TIMEOUT,
        )
        info = init_resp.get("result", {}).get("serverInfo", {})
        self.child_server_info = {
            "name": str(info.get("name", self.label)),
            "version": str(info.get("version", "?")),
        }
        self._write_message({"jsonrpc": "2.0", "method": "notifications/initialized"})
        tools_resp = self._roundtrip("tools/list", {}, timeout=HANDSHAKE_TIMEOUT)
        self.tools = tools_resp.get("result", {}).get("tools", [])
        self.status = "up"
        self.error_message = ""
        print(
            f"[xero-aggregator] backend {self.label!r} up: "
            f"{self.child_server_info.get('name')} {self.child_server_info.get('version')}, "
            f"{len(self.tools)} tools",
            file=sys.stderr,
        )

    def serves_tools(self) -> bool:
        """List this backend's tools while up, and while down after a crash.

        A crashed child keeps its cached catalogue so agents see a stable tool
        list; a call made before the restart completes returns a clear error.
        """
        # `tools` is only ever set by a successful handshake, so a backend in
        # "down"/"error" with tools is one that was up before it failed.
        return bool(self.tools) and not self._closing and self.status in {"up", "down", "error"}

    def is_alive(self) -> bool:
        return self._child is not None and self._child.poll() is None

    def ensure_running(self) -> bool:
        """Restart a dead child, at most once per backoff window. True if up."""
        if self.is_alive() and self.status == "up":
            return True
        with self._lifecycle_lock:
            if self.is_alive() and self.status == "up":
                return True
            if time.monotonic() < self._next_start_at:
                return False
            if self._child is not None:
                self.restarts += 1
                print(f"[xero-aggregator] backend {self.label!r} restarting (restart #{self.restarts})", file=sys.stderr)
                self.terminate()
            previous = [t.get("name") for t in self.tools]
            self._start_locked()
            ok = self.status == "up"
        if ok and previous != [t.get("name") for t in self.tools] and self.on_tools_changed:
            self.on_tools_changed()
        return ok

    def close(self) -> None:
        """Final shutdown: stop the child and suppress any restart."""
        self._closing = True
        self.terminate()

    def terminate(self, grace: float = 3.0) -> None:
        child = self._child
        if child is None or child.poll() is not None:
            return
        try:
            child.terminate()
            child.wait(timeout=grace)
        except subprocess.TimeoutExpired:
            child.kill()
        except Exception:
            pass

    def _write_message(self, msg: dict[str, Any]) -> None:
        child = self._child
        assert child and child.stdin
        line = json.dumps(msg, separators=(",", ":")) + "\n"
        with self._write_lock:
            child.stdin.write(line)
            child.stdin.flush()

    def _roundtrip(self, method: str, params: dict[str, Any], timeout: float) -> dict[str, Any]:
        req_id = f"agg-{next(self._req_counter)}"
        waiter = _Waiter()
        with self._waiters_lock:
            waiters = self._waiters
            waiters[req_id] = waiter
        try:
            self._write_message({"jsonrpc": "2.0", "id": req_id, "method": method, "params": params})
        except Exception as exc:
            with self._waiters_lock:
                waiters.pop(req_id, None)
            raise RuntimeError(f"Backend {self.label!r} write failed: {exc}") from exc
        if not waiter.event.wait(timeout):
            with self._waiters_lock:
                waiters.pop(req_id, None)
            raise TimeoutError(f"Backend {self.label!r} did not respond within {timeout}s for id={req_id!r}")
        if waiter.response is _READER_EOF:
            raise RuntimeError(f"Backend {self.label!r} stdout closed unexpectedly")
        assert isinstance(waiter.response, dict)
        return waiter.response

    # ------------------------------------------------------------------
    # Per-call request
    # ------------------------------------------------------------------

    def request(self, method: str, params: dict[str, Any], timeout: float = 120.0) -> dict[str, Any]:
        """Send a JSON-RPC request to the child and return its response."""
        if not self.ensure_running():
            raise RuntimeError(f"Backend {self.label!r} process is not running")
        if not self._inflight.acquire(timeout=timeout):
            raise TimeoutError(f"Backend {self.label!r} is saturated ({MAX_INFLIGHT_PER_BACKEND} calls in flight)")
        try:
            return self._roundtrip(method, params, timeout)
        finally:
            self._inflight.release()


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


def _rebuild_tool_index() -> None:
    """Rebuild the public tool index — first backend wins on collision.

    Public names are prefixed per business when more than one business is
    exposed. The new dict is swapped in whole, so concurrent readers always
    see a complete index.
    """
    global _tool_index
    index: dict[str, tuple[Backend, str]] = {}
    for backend in _backends:
        if not backend.serves_tools():
            continue
        for tool in backend.tools:
            name = tool.get("name", "")
            if not name:
                continue
            public = _public_name(backend.prefix, name)
            if public in index:
                existing, _real = index[public]
                print(
                    f"[xero-aggregator] WARNING: tool {public!r} exists in both "
                    f"{existing.label!r} and {backend.label!r}; "
                    f"keeping {existing.label!r}",
                    file=sys.stderr,
                )
            else:
                index[public] = (backend, name)
    _tool_index = index


def _ensure_started() -> None:
    global _started
    with _start_lock:
        if _started:
            return
        _started = True
        print("[xero-aggregator] starting backends...", file=sys.stderr)
        for backend in _backends:
            backend.on_tools_changed = _rebuild_tool_index
            try:
                backend.start()
            except Exception as exc:
                backend.status = "error"
                backend.error_message = str(exc)
                print(f"[xero-aggregator] backend {backend.label!r} failed: {exc}", file=sys.stderr)
        _rebuild_tool_index()
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
                if b.restarts:
                    lines.append(f"    restarts: {b.restarts}")
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
        if not b.serves_tools():
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

            if not backend.ensure_running():
                return _response(
                    req_id,
                    {
                        "content": [
                            {
                                "type": "text",
                                "text": (
                                    f"Backend {backend.label!r} is down (restart pending) and cannot serve "
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
        b._closing = True
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


def serve_stdio() -> int:
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


# ---------------------------------------------------------------------------
# Streamable HTTP front (shared service mode)
# ---------------------------------------------------------------------------
#
# One long-lived aggregator serves every MCP client session over MCP
# Streamable HTTP, so a Gateway with many agent sessions runs one backend
# chain instead of one chain per session. It is a loopback-only service:
# binding is restricted to 127.0.0.1/::1 and Host/Origin are checked to stop
# DNS-rebinding from a browser. Responses are plain application/json; there is
# no server-initiated SSE stream, so GET /mcp answers 405 as the spec allows.

DEFAULT_HTTP_PORT = 8796
LOOPBACK_HOSTS = {"127.0.0.1", "::1"}
LOOPBACK_NAMES = {"127.0.0.1", "localhost", "[::1]", "::1"}
MAX_BODY_BYTES = 16 * 1024 * 1024
SESSION_IDLE_SECONDS = 24 * 3600
MAX_SESSIONS = 4096
SERVICE_NAME = "arc-forge-xero-mcp"
# Token material lives only in the connector's encrypted store. Never let a
# legacy token/secret variable from the launching environment reach a child.
TOKEN_ENV_VARS = (
    "XERO_ACCESS_TOKEN",
    "XERO_REFRESH_TOKEN",
    "XERO_ID_TOKEN",
    "XERO_CLIENT_SECRET",
    "XERO_CLIENT_BEARER_TOKEN",
    "ARC_FORGE_XERO_ACCESS_TOKEN",
    "ARC_FORGE_XERO_REFRESH_TOKEN",
)


def default_port() -> int:
    return int(os.environ.get("ARC_FORGE_XERO_MCP_PORT") or DEFAULT_HTTP_PORT)


class SessionRegistry:
    """MCP session ids for HTTP clients. Holds no request state.

    Every tool call is a stateless proxy to the shared backends, so a session
    only records its negotiated protocol version and last use. An unknown but
    well-formed id (for example after this service restarted) is adopted
    rather than rejected with 404, so live agent sessions survive a restart.
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._sessions: dict[str, dict[str, Any]] = {}

    def create(self, protocol_version: str) -> str:
        import secrets

        session_id = secrets.token_hex(16)
        with self._lock:
            self._prune_locked()
            self._sessions[session_id] = {"protocol": protocol_version, "last_seen": time.monotonic()}
        return session_id

    def touch(self, session_id: str) -> bool:
        """Record use of a session; False if the id is malformed."""
        if not (8 <= len(session_id) <= 128) or not all(33 <= ord(c) <= 126 for c in session_id):
            return False
        with self._lock:
            entry = self._sessions.get(session_id)
            if entry is None:
                self._prune_locked()
                entry = self._sessions[session_id] = {"protocol": PROTOCOL_VERSION_DEFAULT, "adopted": True}
            entry["last_seen"] = time.monotonic()
        return True

    def delete(self, session_id: str) -> bool:
        with self._lock:
            return self._sessions.pop(session_id, None) is not None

    def count(self) -> int:
        with self._lock:
            return len(self._sessions)

    def _prune_locked(self) -> None:
        cutoff = time.monotonic() - SESSION_IDLE_SECONDS
        for key in [k for k, v in self._sessions.items() if v["last_seen"] < cutoff]:
            del self._sessions[key]
        while len(self._sessions) >= MAX_SESSIONS:
            oldest = min(self._sessions, key=lambda k: self._sessions[k]["last_seen"])
            del self._sessions[oldest]


_sessions = SessionRegistry()
_service_started_at = time.monotonic()


def health_payload() -> dict[str, Any]:
    backends = [
        {
            "label": b.label,
            "business": b.business_key,
            "status": b.status,
            "tools": len(b.tools),
            "restarts": b.restarts,
            "pid": b._child.pid if b.is_alive() and b._child else None,
            **({"error": b.error_message} if b.status == "error" else {}),
        }
        for b in _backends
    ]
    if not _started or any(b.status == "idle" for b in _backends):
        status = "starting"
    elif all(b.status == "up" for b in _backends):
        status = "ok"
    else:
        status = "degraded"
    return {
        "status": status,
        "server": SERVER_NAME,
        "version": SERVER_VERSION,
        "pid": os.getpid(),
        "uptime_s": int(time.monotonic() - _service_started_at),
        "sessions": _sessions.count(),
        "tools": len(_tool_index) + 1,
        "connector_root": str(_MODULE_ROOT),
        "backends": backends,
    }


def _host_allowed(value: str | None) -> bool:
    if not value:
        return False
    host = value.strip().lower()
    if host.startswith("["):
        host = host[: host.find("]") + 1]
    elif ":" in host:
        host = host.rsplit(":", 1)[0]
    return host in LOOPBACK_NAMES


def _origin_allowed(value: str | None) -> bool:
    if not value:
        return True  # non-browser clients send no Origin
    from urllib.parse import urlsplit

    try:
        host = urlsplit(value).hostname
    except ValueError:
        return False
    return host in {"127.0.0.1", "localhost", "::1"}


def _make_handler() -> type:
    from http.server import BaseHTTPRequestHandler

    class McpHttpHandler(BaseHTTPRequestHandler):
        server_version = f"{SERVER_NAME}/{SERVER_VERSION}"
        protocol_version = "HTTP/1.1"

        def log_message(self, format: str, *args: Any) -> None:  # noqa: A002 - stdlib signature
            return  # request lines can carry session ids; keep logs quiet

        def _send(self, status: int, payload: Any = None, headers: dict[str, str] | None = None) -> None:
            body = b"" if payload is None else json.dumps(payload, separators=(",", ":")).encode()
            self.send_response(status)
            if payload is not None:
                self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            for key, value in (headers or {}).items():
                self.send_header(key, value)
            self.end_headers()
            if body:
                self.wfile.write(body)

        def _guard(self) -> bool:
            if not _host_allowed(self.headers.get("Host")) or not _origin_allowed(self.headers.get("Origin")):
                self._send(403, {"error": "forbidden host or origin"})
                return False
            return True

        def do_GET(self) -> None:  # noqa: N802 - stdlib naming
            if not self._guard():
                return
            path = self.path.split("?", 1)[0]
            if path in ("/healthz", "/health"):
                payload = health_payload()
                self._send(200 if payload["status"] == "ok" else 503, payload)
            elif path == "/mcp":
                self._send(405, {"error": "no server-initiated stream; use POST"}, {"Allow": "POST, DELETE"})
            else:
                self._send(404, {"error": "not found"})

        def do_DELETE(self) -> None:  # noqa: N802
            if not self._guard():
                return
            if self.path.split("?", 1)[0] != "/mcp":
                self._send(404, {"error": "not found"})
                return
            session_id = self.headers.get("Mcp-Session-Id") or ""
            self._send(200 if _sessions.delete(session_id) else 404)

        def do_POST(self) -> None:  # noqa: N802
            if not self._guard():
                return
            if self.path.split("?", 1)[0] != "/mcp":
                self._send(404, {"error": "not found"})
                return
            try:
                length = int(self.headers.get("Content-Length") or "0")
            except ValueError:
                length = -1
            if length <= 0 or length > MAX_BODY_BYTES:
                self._send(413 if length > MAX_BODY_BYTES else 400, _response(None, error={"code": -32600, "message": "Invalid request body"}))
                return
            try:
                message = json.loads(self.rfile.read(length))
            except (json.JSONDecodeError, UnicodeDecodeError) as exc:
                self._send(400, _response(None, error={"code": -32700, "message": f"Parse error: {exc}"}))
                return
            batch = isinstance(message, list)
            messages = message if batch else [message]
            if not messages or not all(isinstance(m, dict) for m in messages):
                self._send(400, _response(None, error={"code": -32600, "message": "Invalid request"}))
                return

            headers: dict[str, str] = {}
            is_init = any(m.get("method") == "initialize" for m in messages)
            if is_init:
                if len(messages) != 1:
                    self._send(400, _response(None, error={"code": -32600, "message": "initialize must not be batched"}))
                    return
                proto = str((messages[0].get("params") or {}).get("protocolVersion") or PROTOCOL_VERSION_DEFAULT)
                headers["Mcp-Session-Id"] = _sessions.create(proto)
            else:
                session_id = self.headers.get("Mcp-Session-Id") or ""
                if not session_id or not _sessions.touch(session_id):
                    self._send(400, _response(None, error={"code": -32000, "message": "Bad Request: missing or invalid Mcp-Session-Id"}))
                    return

            replies = []
            for item in messages:
                try:
                    reply = _handle(item)
                except Exception as exc:  # _handle already traps; belt and braces
                    reply = _response(item.get("id"), error={"code": -32603, "message": f"Internal error: {exc}"})
                if reply is not None:
                    replies.append(reply)
            if not replies:
                self._send(202, None, headers)
            else:
                self._send(200, replies if batch else replies[0], headers)

    return McpHttpHandler


def build_http_server(host: str, port: int) -> Any:
    """Bind the loopback MCP HTTP server (port 0 picks a free port)."""
    from http.server import ThreadingHTTPServer
    import socket

    if host not in LOOPBACK_HOSTS:
        raise ValueError(f"refusing to bind {host!r}: loopback only (127.0.0.1 or ::1)")

    class Server(ThreadingHTTPServer):
        daemon_threads = True
        allow_reuse_address = True
        # The stdlib default backlog of 5 resets connections when many agent
        # sessions connect at once (e.g. right after a Gateway restart).
        request_queue_size = 128
        address_family = socket.AF_INET6 if ":" in host else socket.AF_INET

        def handle_error(self, request: Any, client_address: Any) -> None:
            # Clients drop idle keep-alive sockets when they exit; that is not
            # a server fault and should not fill the journal with tracebacks.
            if isinstance(sys.exc_info()[1], (ConnectionResetError, BrokenPipeError)):
                return
            super().handle_error(request, client_address)

    return Server((host, port), _make_handler())


def _watch_parent(httpd: Any) -> None:
    """Stop serving when the launching process dies (gateway-owned mode)."""
    parent = os.getppid()
    while os.getppid() == parent:
        time.sleep(2)
    print("[xero-aggregator] parent process exited; shutting down", file=sys.stderr)
    httpd.shutdown()


def serve_http(host: str, port: int, exit_with_parent: bool = False) -> int:
    import signal

    for name in TOKEN_ENV_VARS:
        os.environ.pop(name, None)
    try:
        httpd = build_http_server(host, port)
    except ValueError as exc:
        print(f"[xero-aggregator] {exc}", file=sys.stderr)
        return 2
    except OSError as exc:
        print(f"[xero-aggregator] cannot bind {host}:{port}: {exc}", file=sys.stderr)
        return 3
    bound_port = httpd.server_address[1]
    print(f"[xero-aggregator] {SERVER_NAME} v{SERVER_VERSION} serving MCP on http://{host}:{bound_port}/mcp", file=sys.stderr, flush=True)

    def _stop(_signum: int, _frame: Any) -> None:
        threading.Thread(target=httpd.shutdown, daemon=True).start()

    signal.signal(signal.SIGTERM, _stop)
    signal.signal(signal.SIGINT, _stop)
    # Start backends in the background: /healthz answers "starting" at once
    # and /mcp requests wait on the start lock until the chain is ready.
    threading.Thread(target=_ensure_started, daemon=True).start()
    if exit_with_parent:
        threading.Thread(target=_watch_parent, args=(httpd,), daemon=True).start()
    try:
        httpd.serve_forever(poll_interval=0.5)
    finally:
        httpd.server_close()
        print("[xero-aggregator] HTTP service stopping; terminating backends", file=sys.stderr)
        _terminate_backends()
    return 0


def check_health(url: str, timeout: float) -> int:
    import urllib.error
    import urllib.request

    try:
        with urllib.request.urlopen(url, timeout=timeout) as resp:  # noqa: S310 - loopback URL
            payload = json.loads(resp.read() or b"{}")
            code = resp.status
    except urllib.error.HTTPError as exc:
        payload = json.loads(exc.read() or b"{}")
        code = exc.code
    except (urllib.error.URLError, OSError, ValueError) as exc:
        print(json.dumps({"status": "down", "url": url, "error": str(exc)}, indent=2))
        return 1
    print(json.dumps(payload, indent=2))
    return 0 if code == 200 and payload.get("status") == "ok" else 1


# ---------------------------------------------------------------------------
# systemd user unit
# ---------------------------------------------------------------------------


def unit_path() -> Path:
    base = Path(os.environ.get("XDG_CONFIG_HOME") or Path.home() / ".config")
    return base / "systemd" / "user" / f"{SERVICE_NAME}.service"


def render_unit(port: int) -> str:
    import shutil

    # systemd user units start with a minimal PATH. Pin the directories that
    # hold the node/npm/python the operator installed with, so the official
    # Node child resolves the same runtime as an interactive shell.
    path_dirs: list[str] = []
    for exe in ("node", "npm", "python3"):
        found = shutil.which(exe)
        if found:
            parent = str(Path(found).parent)
            if parent not in path_dirs:
                path_dirs.append(parent)
    for default in ("/usr/local/bin", "/usr/bin", "/bin"):
        if default not in path_dirs:
            path_dirs.append(default)
    script = Path(__file__).resolve()
    return "\n".join(
        [
            "[Unit]",
            "Description=Arc Forge Xero shared MCP server (loopback streamable HTTP)",
            "After=network-online.target",
            "Wants=network-online.target",
            "",
            "[Service]",
            "Type=simple",
            f"ExecStart={sys.executable} {script} serve --host 127.0.0.1 --port {port}",
            f"Environment=PATH={':'.join(path_dirs)}",
            "Environment=PYTHONUNBUFFERED=1",
            f"UnsetEnvironment={' '.join(TOKEN_ENV_VARS)}",
            "Restart=on-failure",
            "RestartSec=5",
            "TimeoutStopSec=15",
            "MemoryMax=768M",
            "NoNewPrivileges=yes",
            "",
            "[Install]",
            "WantedBy=default.target",
            "",
        ]
    )


def command_service(action: str, port: int, start: bool) -> int:
    path = unit_path()
    systemctl = ["systemctl", "--user"]
    if action == "print":
        sys.stdout.write(render_unit(port))
        return 0
    if action == "install":
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(render_unit(port))
        print(f"wrote {path}", file=sys.stderr)
        subprocess.run([*systemctl, "daemon-reload"], check=True)
        if start:
            subprocess.run([*systemctl, "enable", "--now", f"{SERVICE_NAME}.service"], check=True)
            subprocess.run([*systemctl, "restart", f"{SERVICE_NAME}.service"], check=True)
        return 0
    if action == "uninstall":
        subprocess.run([*systemctl, "disable", "--now", f"{SERVICE_NAME}.service"], check=False)
        if path.exists():
            path.unlink()
        subprocess.run([*systemctl, "daemon-reload"], check=False)
        return 0
    raise ValueError(action)


def main(argv: list[str] | None = None) -> int:
    import argparse

    parser = argparse.ArgumentParser(prog="xero-mcp", description="Arc Forge Xero MCP aggregator.")
    sub = parser.add_subparsers(dest="command")
    sub.add_parser("run", help="Serve MCP over stdio (default; one chain per client)")
    serve = sub.add_parser("serve", help="Serve MCP over loopback streamable HTTP (one shared chain)")
    serve.add_argument("--host", default="127.0.0.1")
    serve.add_argument("--port", type=int, default=default_port())
    serve.add_argument("--exit-with-parent", action="store_true", help="stop when the launching process exits (used by the OpenClaw plugin)")
    health = sub.add_parser("health", help="Check a running shared service; exit 0 only when every backend is up")
    health.add_argument("--port", type=int, default=default_port())
    health.add_argument("--timeout", type=float, default=5.0)
    service = sub.add_parser("service", help="Manage the systemd user unit for the shared service")
    service.add_argument("action", choices=["print", "install", "uninstall"])
    service.add_argument("--port", type=int, default=default_port())
    service.add_argument("--no-start", action="store_true", help="install the unit without enabling or starting it")
    args = parser.parse_args(argv)

    if args.command == "serve":
        return serve_http(args.host, args.port, exit_with_parent=args.exit_with_parent)
    if args.command == "health":
        return check_health(f"http://127.0.0.1:{args.port}/healthz", args.timeout)
    if args.command == "service":
        return command_service(args.action, args.port, start=not args.no_start)
    return serve_stdio()


if __name__ == "__main__":
    raise SystemExit(main())
