#!/usr/bin/env python3
"""JSON-backed operation lock for heavy Xero workflows."""

from __future__ import annotations

import json
import os
import secrets
import stat
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator


DEFAULT_LOCK_PATH = Path.home() / ".config" / "arc-forge-tools" / "xero" / "operation-lock.json"
DEFAULT_LEASE_TTL_SECONDS = 15 * 60
DEFAULT_WAIT_TIMEOUT_SECONDS = 120
GUARD_STALE_SECONDS = 30


class OperationLockError(RuntimeError):
    """User-facing operation lock error."""


def utc_seconds() -> int:
    return int(time.time())


def lock_store_path(value: str | None = None) -> Path:
    raw = value or os.environ.get("ARC_FORGE_XERO_OPERATION_LOCK_STORE") or os.environ.get("XERO_OPERATION_LOCK_STORE")
    return Path(raw).expanduser().resolve() if raw else DEFAULT_LOCK_PATH


def new_id(prefix: str) -> str:
    return f"{prefix}_{secrets.token_hex(12)}"


def load_state(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {"schema_version": 1, "current": None, "queue": []}
    try:
        with path.open("r", encoding="utf-8") as handle:
            payload = json.load(handle)
    except json.JSONDecodeError as exc:
        raise OperationLockError(f"Operation lock state is invalid JSON: {path}: {exc}") from exc
    if not isinstance(payload, dict):
        raise OperationLockError(f"Operation lock state root must be an object: {path}")
    payload.setdefault("schema_version", 1)
    payload.setdefault("current", None)
    payload.setdefault("queue", [])
    if not isinstance(payload["queue"], list):
        payload["queue"] = []
    return payload


def save_state(path: Path, state: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_suffix(path.suffix + ".tmp")
    with tmp_path.open("w", encoding="utf-8") as handle:
        json.dump(state, handle, indent=2, sort_keys=False)
        handle.write("\n")
    os.chmod(tmp_path, stat.S_IRUSR | stat.S_IWUSR)
    tmp_path.replace(path)
    os.chmod(path, stat.S_IRUSR | stat.S_IWUSR)


def prune_state(state: dict[str, Any], *, now: int | None = None) -> None:
    now = utc_seconds() if now is None else now
    current = state.get("current")
    if isinstance(current, dict) and int(current.get("expires_at") or 0) <= now:
        state["current"] = None
    queue = []
    for item in state.get("queue", []):
        if not isinstance(item, dict):
            continue
        timeout_at = int(item.get("timeout_at") or 0)
        if timeout_at and timeout_at <= now:
            continue
        queue.append(item)
    state["queue"] = queue


@contextmanager
def state_guard(path: Path, *, timeout_seconds: float = 5) -> Iterator[None]:
    guard_path = path.with_suffix(path.suffix + ".guard")
    path.parent.mkdir(parents=True, exist_ok=True)
    deadline = time.monotonic() + timeout_seconds
    while True:
        try:
            fd = os.open(str(guard_path), os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                handle.write(json.dumps({"pid": os.getpid(), "created_at": utc_seconds()}) + "\n")
            break
        except FileExistsError:
            try:
                age = utc_seconds() - int(guard_path.stat().st_mtime)
            except OSError:
                age = 0
            if age > GUARD_STALE_SECONDS:
                try:
                    guard_path.unlink()
                    continue
                except FileNotFoundError:
                    continue
            if time.monotonic() >= deadline:
                raise OperationLockError(f"Timed out waiting for operation lock guard: {guard_path}")
            time.sleep(0.05)
    try:
        yield
    finally:
        try:
            guard_path.unlink()
        except FileNotFoundError:
            pass


def acquire_lock(
    path: Path,
    *,
    holder: str,
    wait: bool = False,
    timeout_seconds: int = DEFAULT_WAIT_TIMEOUT_SECONDS,
    ttl_seconds: int = DEFAULT_LEASE_TTL_SECONDS,
    poll_seconds: float = 0.25,
) -> dict[str, Any]:
    request_id = new_id("request")
    deadline = time.monotonic() + max(0, timeout_seconds)
    enqueued = False

    while True:
        with state_guard(path):
            state = load_state(path)
            now = utc_seconds()
            prune_state(state, now=now)
            queue = state["queue"]
            current = state.get("current")
            if not current and (not queue or queue[0].get("request_id") == request_id):
                if queue and queue[0].get("request_id") == request_id:
                    queue.pop(0)
                lease = {
                    "lease_id": new_id("lease"),
                    "holder": holder,
                    "request_id": request_id,
                    "acquired_at": now,
                    "expires_at": now + max(1, ttl_seconds),
                }
                state["current"] = lease
                save_state(path, state)
                return {"ok": True, "acquired": True, "operation_lock_store": str(path), **lease, "queue_length": len(queue)}

            if not enqueued:
                queue.append(
                    {
                        "request_id": request_id,
                        "holder": holder,
                        "enqueued_at": now,
                        "timeout_at": now + max(1, timeout_seconds),
                    }
                )
                enqueued = True
                save_state(path, state)
                if not wait:
                    return {
                        "ok": False,
                        "acquired": False,
                        "queued": True,
                        "operation_lock_store": str(path),
                        "request_id": request_id,
                        "held_by": current.get("holder") if isinstance(current, dict) else None,
                        "queue_length": len(queue),
                    }
            else:
                save_state(path, state)

        if not wait or time.monotonic() >= deadline:
            with state_guard(path):
                state = load_state(path)
                state["queue"] = [item for item in state.get("queue", []) if item.get("request_id") != request_id]
                save_state(path, state)
            raise OperationLockError(f"Timed out waiting for Xero operation lock (holder={holder}).")
        time.sleep(poll_seconds)


def release_lock(path: Path, lease_id: str) -> dict[str, Any]:
    with state_guard(path):
        state = load_state(path)
        prune_state(state)
        current = state.get("current")
        if not isinstance(current, dict) or current.get("lease_id") != lease_id:
            return {"ok": False, "released": False, "operation_lock_store": str(path), "message": "Lease is not current."}
        state["current"] = None
        save_state(path, state)
    return {"ok": True, "released": True, "operation_lock_store": str(path), "lease_id": lease_id}


def lock_status(path: Path) -> dict[str, Any]:
    with state_guard(path):
        state = load_state(path)
        prune_state(state)
        save_state(path, state)
    current = state.get("current") if isinstance(state.get("current"), dict) else None
    return {
        "ok": True,
        "operation_lock_store": str(path),
        "held": current is not None,
        "current": current,
        "queue_length": len(state.get("queue", [])),
        "queue": state.get("queue", []),
    }
