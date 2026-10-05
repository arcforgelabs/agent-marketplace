"""Version facts for the Arc Forge Xero connector, each from one source.

The release version is the published plugin package's `version`
(`@arcforgelabs/openclaw-xero`). It follows the Arc Forge/OpenClaw scheme
`YYYY.M.PATCH`: PATCH counts releases within the month, `-beta.N` marks a
prerelease and `-N` a repackage of the same code. Servers, health checks and
smoke clients report this value; nothing else in the connector carries its own
version number.

The official Xero MCP server is a separate upstream package pinned here. Its
own `serverInfo.version` is whatever upstream reports and is shown as such.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

PACKAGE_NAME = "@arcforgelabs/openclaw-xero"
OFFICIAL_PACKAGE = "@xeroapi/xero-mcp-server"
OFFICIAL_PACKAGE_VERSION = "0.0.17"

RELEASE_VERSION_PATTERN = re.compile(r"^\d{4}\.(?:[1-9]|1[0-2])\.[1-9]\d*(?:-(?:beta\.)?[1-9]\d*)?$")

_MODULE_ROOT = Path(__file__).resolve().parents[1]  # connectors/xero, or <plugin>/connector


def _package_json_candidates() -> tuple[Path, ...]:
    return (
        _MODULE_ROOT.parent / "package.json",  # installed plugin: <plugin>/connector
        _MODULE_ROOT.parents[1] / "plugins" / "xero" / "package.json",  # repository checkout
    )


def release_version() -> str:
    """The plugin package version, or `0.0.0-unversioned` outside any package."""
    for candidate in _package_json_candidates():
        try:
            payload = json.loads(candidate.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if isinstance(payload, dict) and payload.get("name") == PACKAGE_NAME and payload.get("version"):
            return str(payload["version"])
    return "0.0.0-unversioned"


def official_package_spec() -> str:
    return f"{OFFICIAL_PACKAGE}@{OFFICIAL_PACKAGE_VERSION}"
