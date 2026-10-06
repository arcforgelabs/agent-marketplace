"""One Xero connection per agent.

The connector holds exactly one token store (default
``~/.config/arc-forge-tools/xero/tokens.json``, overridable with
``XERO_TOKEN_STORE`` or ``--store``) and acts only on that store's pinned
organisation. There is no business registry and no per-call choice of
connection: an agent that can pick a connection can pick the wrong one.

The retired multi-business layout (``businesses.json`` plus ``XERO_PROFILE``)
is refused rather than interpreted, so a leftover registry can never quietly
decide which books an agent writes to.

Dependency-free so the CLI and the MCP aggregator can both import it.
"""

from __future__ import annotations

import os
from pathlib import Path

CONFIG_ROOT = Path.home() / ".config" / "arc-forge-tools" / "xero"
RETIRED_REGISTRY = CONFIG_ROOT / "businesses.json"
RETIRED_REGISTRY_ENV = "ARC_FORGE_XERO_BUSINESS_REGISTRY"
RETIRED_PROFILE_ENV = "XERO_PROFILE"


class SingleConnectionError(RuntimeError):
    """The installation carries retired multi-business state."""


def retired_state() -> list[str]:
    """Describe any retired multi-business state that is still present."""
    found: list[str] = []
    candidates = [RETIRED_REGISTRY]
    override = os.environ.get(RETIRED_REGISTRY_ENV)
    if override:
        candidates.append(Path(override).expanduser())
    for path in candidates:
        if path.exists():
            found.append(f"business registry {path}")
    if os.environ.get(RETIRED_PROFILE_ENV):
        found.append(f"{RETIRED_PROFILE_ENV} environment variable")
    return found


def assert_single_connection() -> None:
    """Refuse to run while retired multi-business state is present."""
    found = retired_state()
    if not found:
        return
    raise SingleConnectionError(
        "Refusing to run: found " + " and ".join(found) + ". "
        "This connector supports one Xero connection per agent and will not choose between businesses. "
        f"Keep the one connection at the default token store ({CONFIG_ROOT / 'tokens.json'}), "
        f"move any other business's files off this host, delete the registry, and unset {RETIRED_PROFILE_ENV}."
    )
