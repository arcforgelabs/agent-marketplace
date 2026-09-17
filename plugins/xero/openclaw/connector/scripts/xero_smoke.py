#!/usr/bin/env python3
"""End-to-end Xero plugin smoke runner.

The runner is explicit about boundaries:
- Local checks do not require a Xero login.
- Live API checks run only with --live-api and use the local OAuth token store.
- CDP checks run only with a user-provided already-authenticated endpoint.
"""

from __future__ import annotations

import argparse
import json
import os
import stat
import subprocess
import sys
import time
from pathlib import Path
from typing import Any


MODULE_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = MODULE_ROOT.parents[1]
XERO_CLI = MODULE_ROOT / "cli" / "xero"
XERO_MCP = MODULE_ROOT / "mcp" / "xero-mcp-local"
XERO_PLUGIN_MCP = MODULE_ROOT / "mcp" / "xero-workflows-mcp"
XERO_RECONCILE = MODULE_ROOT / "reconciliation" / "xero-reconcile"
DEFAULT_SMOKE_DIR = Path.home() / ".config" / "arc-forge-tools" / "xero" / "smoke"
PLUGIN_VALIDATOR = Path("/home/samuel/.codex-accounts/shared/skills/.system/plugin-creator/scripts/validate_plugin.py")
XERO_PLUGIN = REPO_ROOT / "plugins" / "xero"


class SmokeError(RuntimeError):
    """User-facing smoke runner error."""


def utc_seconds() -> int:
    return int(time.time())


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


def smoke_dir(value: str | None = None) -> Path:
    raw = value or os.environ.get("ARC_FORGE_XERO_SMOKE_DIR") or os.environ.get("XERO_SMOKE_DIR")
    return Path(raw).expanduser().resolve() if raw else DEFAULT_SMOKE_DIR


def parse_json(raw: str) -> Any:
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return None


def run_command(name: str, command: list[str], *, required: bool = True, env: dict[str, str] | None = None) -> dict[str, Any]:
    started = utc_seconds()
    result = subprocess.run(
        command,
        cwd=REPO_ROOT,
        env=env or os.environ.copy(),
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    parsed_stdout = parse_json(result.stdout.strip()) if result.stdout.strip() else None
    step = {
        "name": name,
        "command": command,
        "required": required,
        "ok": result.returncode == 0,
        "returncode": result.returncode,
        "started_at": started,
        "finished_at": utc_seconds(),
        "stdout_json": parsed_stdout,
        "stdout": None if parsed_stdout is not None else result.stdout.strip(),
        "stderr": result.stderr.strip(),
    }
    return step


def add_step(report: dict[str, Any], name: str, command: list[str], *, required: bool = True) -> None:
    step = run_command(name, command, required=required)
    report["steps"].append(step)


def build_smoke_report(args: argparse.Namespace) -> dict[str, Any]:
    report: dict[str, Any] = {
        "ok": True,
        "mode": "xero-smoke",
        "generated_at": utc_seconds(),
        "live_api": bool(args.live_api),
        "cdp": bool(args.cdp_endpoint),
        "login_automation": False,
        "credential_collection": False,
        "steps": [],
    }

    add_step(report, "doctor", [str(XERO_CLI), "doctor"], required=True)
    add_step(report, "mcp_self_test", [str(XERO_MCP), "self-test"], required=True)
    add_step(report, "plugin_mcp_self_test", [str(XERO_PLUGIN_MCP), "self-test"], required=True)
    add_step(report, "mcp_print_config_generic", [str(XERO_MCP), "print-config", "--harness", "generic"], required=True)
    if PLUGIN_VALIDATOR.exists() and XERO_PLUGIN.exists():
        add_step(report, "plugin_validate", ["python3", str(PLUGIN_VALIDATOR), str(XERO_PLUGIN)], required=True)

    if args.prepare:
        add_step(report, "mcp_prepare", [str(XERO_MCP), "prepare"], required=True)
        add_step(report, "mcp_protocol_smoke", [str(XERO_MCP), "protocol-smoke", "--strict"], required=True)

    if args.live_api:
        add_step(report, "doctor_strict", [str(XERO_CLI), "doctor", "--strict"], required=True)
        add_step(report, "auth_status", [str(XERO_CLI), "auth", "status"], required=True)
        add_step(report, "tenants_refresh", [str(XERO_CLI), "tenants", "list", "--refresh"], required=True)
        add_step(report, "smoke_organisation", [str(XERO_CLI), "smoke", "organisation"], required=True)
        add_step(report, "smoke_accounts", [str(XERO_CLI), "smoke", "accounts", "--limit", str(args.accounts_limit)], required=True)
        add_step(report, "mcp_live_organisation", [str(XERO_MCP), "live-smoke", "--strict"], required=True)

    if args.cdp_endpoint:
        capture_out = smoke_dir(args.out_dir) / f"reconcile_capture_{utc_seconds()}.json"
        inspect_command = [str(XERO_RECONCILE), "inspect", "--cdp-endpoint", args.cdp_endpoint]
        capture_command = [
            str(XERO_RECONCILE),
            "capture-lines",
            "--cdp-endpoint",
            args.cdp_endpoint,
            "--out",
            str(capture_out),
        ]
        if args.target_id:
            capture_command.extend(["--target-id", args.target_id])
        add_step(report, "reconcile_inspect", inspect_command, required=True)
        add_step(report, "reconcile_capture_lines", capture_command, required=True)
        if args.expected:
            dry_run_out = smoke_dir(args.out_dir) / f"reconcile_dry_run_{utc_seconds()}.json"
            add_step(
                report,
                "reconcile_dry_run",
                [
                    str(XERO_RECONCILE),
                    "dry-run",
                    "--cdp-endpoint",
                    args.cdp_endpoint,
                    "--expected",
                    args.expected,
                    "--statement-lines",
                    str(capture_out),
                    "--out",
                    str(dry_run_out),
                ],
                required=True,
            )

    failed_required = [step for step in report["steps"] if step["required"] and not step["ok"]]
    report["ok"] = not failed_required
    report["summary"] = {
        "step_count": len(report["steps"]),
        "failed_required": len(failed_required),
        "failed": [step["name"] for step in failed_required],
    }
    return report


def command_run(args: argparse.Namespace) -> int:
    report = build_smoke_report(args)
    out_path = Path(args.out).expanduser().resolve() if args.out else smoke_dir(args.out_dir) / f"xero_smoke_{utc_seconds()}.json"
    write_json_file(out_path, report)
    write_json({"ok": report["ok"], "report": str(out_path), "summary": report["summary"]})
    return 0 if report["ok"] else 1


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="xero-smoke", description="Run local and optional live Xero plugin smoke checks")
    parser.add_argument("--live-api", action="store_true", help="Run live read-only Xero API smoke checks using local OAuth state")
    parser.add_argument("--prepare", action="store_true", help="Run MCP package prepare; may download npm package")
    parser.add_argument("--accounts-limit", type=int, default=5, help="Maximum accounts returned by live accounts smoke")
    parser.add_argument("--cdp-endpoint", help="User-provided already-authenticated CDP endpoint for reconciliation smoke")
    parser.add_argument("--target-id", help="Specific CDP page target id from xero-reconcile inspect")
    parser.add_argument("--expected", help="Expected reconciliation JSON for optional CDP dry-run matching")
    parser.add_argument("--out", help="Write smoke report to this JSON file")
    parser.add_argument("--out-dir", help="Override smoke artifact directory")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return command_run(args)
    except SmokeError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
