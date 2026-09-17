#!/usr/bin/env python3
"""Multi-business (profile) registry for the Arc Forge Xero connector.

A "business" (a.k.a. profile) bundles one Xero connection's local state so the
connector can operate several dedicated businesses without their auth/tenant
state colliding. The active tenant is a single global pointer inside one token
store; running two live sets of books out of one store means a forgotten
`tenants use` can post financial records to the wrong legal entity. Giving each
business its own token store removes that shared pointer entirely.

Design goals
------------
* Zero-config backwards compatibility. When no registry file exists the
  connector behaves exactly as the legacy single-business setup: the legacy
  default paths under ``~/.config/arc-forge-tools/xero/``. Nothing about the
  current Arc Forge connection moves or changes.
* Isolation where it matters, sharing where it's correct. Each business gets
  its own token store and per-tenant rate-governor files. The OAuth app
  (client id), the token-store encryption key, and the app-wide minute budget
  are the *same Xero app* for every business, so they stay shared.
* Env-based application. A profile resolves to a set of environment variables
  that ``xero_core``'s existing path resolvers already honour, so the rest of
  the CLI and the official MCP backend need no per-call plumbing — the official
  Node server shells out to ``xero auth token`` with its own ``process.env``,
  which reads ``XERO_TOKEN_STORE``.

This module is intentionally dependency-free and imports nothing from
``xero_core`` so both the CLI and the aggregator can import it without cycles.
"""

from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


# ---------------------------------------------------------------------------
# Locations
# ---------------------------------------------------------------------------

LEGACY_ROOT = Path.home() / ".config" / "arc-forge-tools" / "xero"
BUSINESSES_ROOT = LEGACY_ROOT / "businesses"
DEFAULT_REGISTRY_PATH = LEGACY_ROOT / "businesses.json"
REGISTRY_ENV = "ARC_FORGE_XERO_BUSINESS_REGISTRY"
PROFILE_ENV = "XERO_PROFILE"
REGISTRY_SCHEMA_VERSION = 1

# Slug used as both the registry key and the MCP tool-name prefix. Restricted to
# characters that are safe in MCP tool names (we join with "__").
KEY_RE = re.compile(r"^[a-z0-9][a-z0-9-]{0,30}$")

# Fields isolated per business — each business must have its own copy or the
# whole point (no shared active-tenant pointer, independent budgets) is lost.
# field -> (canonical env var, default filename within the business root)
BUSINESS_FIELDS: dict[str, tuple[str, str]] = {
    "token_store": ("XERO_TOKEN_STORE", "tokens.json"),
    "rate_limit_store": ("ARC_FORGE_XERO_RATE_LIMIT_STORE", "rate-limit-status.json"),
    "cli_rate_limit_store": ("ARC_FORGE_XERO_CLI_RATE_LIMIT_STORE", "rate-limit-cli-status.json"),
    "rate_unblock_store": ("ARC_FORGE_XERO_DAY_LIMIT_UNBLOCK_STORE", "rate-limit-unblock.json"),
    # Bookkeeping state is per-legal-entity, not per-app: an org's account/tax
    # mappings, contact/duplicate snapshots, apply-audit ledger, and the
    # heavy-workflow operation lock MUST NOT be shared, or one business's coding
    # rules and dedup history bleed into another's books. The resolvers in
    # xero_finance_rules.py / xero_operation_lock.py already honour these env
    # vars; isolating them here is what makes a second connected org safe.
    "finance_rules": ("XERO_FINANCE_RULES", "finance-rules.json"),
    "snapshot_dir": ("XERO_SNAPSHOT_DIR", "snapshots"),
    "audit_dir": ("XERO_AUDIT_DIR", "audit"),
    "operation_lock_store": ("ARC_FORGE_XERO_OPERATION_LOCK_STORE", "operation-lock.json"),
}

# Fields shared across businesses — the same Xero app backs every business, so
# the encryption key and app-wide minute budget are global. These always
# resolve to the legacy root unless explicitly overridden per entry.
# field -> (canonical env var, filename within the legacy root)
#
# Note: the OAuth app / client id is deliberately NOT a managed field. The
# connector resolves it through its own fall-through chain (env, then the
# ~/.config and repo plugin oauth-app.json files), and the client id ships in
# the repo plugin config rather than the legacy root. Pinning
# ARC_FORGE_XERO_OAUTH_APP_CONFIG to a per-profile path would defeat that chain
# and break client-id resolution, so we leave it to the global resolver.
SHARED_FIELDS: dict[str, tuple[str, str]] = {
    "token_key_file": ("ARC_FORGE_XERO_TOKEN_KEY_FILE", "token-store.key"),
    "shared_rate_limit_store": ("ARC_FORGE_XERO_SHARED_RATE_LIMIT_STORE", "rate-limit-shared.json"),
}

ALL_FIELDS: dict[str, tuple[str, str]] = {**BUSINESS_FIELDS, **SHARED_FIELDS}

IMPLICIT_DEFAULT_KEY = "default"


class ProfileError(RuntimeError):
    """User-facing profile/registry error."""


# ---------------------------------------------------------------------------
# Profile model
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Profile:
    """A resolved business profile: identity plus absolute local paths."""

    key: str
    label: str
    legacy: bool
    # Excluded from eq/hash so a Profile stays hashable (a dict field is not) and
    # its identity is its key/label/legacy, not the resolved path objects.
    paths: dict[str, Path] = field(compare=False)
    # Persisted so CLI-created/hand-edited location overrides survive a reload.
    # `root` redirects a business's isolated state dir; `overrides` pins
    # individual fields. Both are empty/None for legacy and default businesses.
    root: str | None = field(default=None, compare=False)
    overrides: dict[str, str] = field(default_factory=dict, compare=False)
    # Pointer to this org's profile pack (company-profile.md + ap-policy.json +
    # finance-rules.json) in the private finances repo. The connector ships
    # templates only; packs hold business-sensitive data and live outside this
    # repo. Empty for legacy/default until a pack is linked.
    profile_pack: str | None = field(default=None, compare=False)
    # Expected Xero tenant (organisation) ID for identity pinning. When set, the
    # connector asserts the resolved token store's active tenant matches this
    # before minting a token or making an API call — so a misroute (wrong store
    # → wrong org) is refused, never silently executed. None = not pinned yet.
    tenant_id: str | None = field(default=None, compare=False)

    def env(self) -> dict[str, str]:
        """Environment overlay that pins every path resolver to this business."""
        return {ALL_FIELDS[f][0]: str(p) for f, p in self.paths.items()}

    def to_summary(self) -> dict[str, Any]:
        return {
            "key": self.key,
            "label": self.label,
            "legacy": self.legacy,
            "paths": {f: str(p) for f, p in self.paths.items()},
            "token_store_exists": self.paths["token_store"].exists(),
            "profile_pack": self.profile_pack,
            "tenant_id": self.tenant_id,
        }


def validate_key(key: str) -> str:
    if not isinstance(key, str) or not KEY_RE.match(key):
        raise ProfileError(
            f"invalid business key {key!r}: use 1-31 chars of [a-z0-9-], starting alphanumeric"
        )
    return key


def business_root(key: str, root: str | os.PathLike[str] | None = None) -> Path:
    if root:
        return Path(root).expanduser().resolve()
    return (BUSINESSES_ROOT / key).resolve()


def resolve_paths(
    *,
    key: str,
    legacy: bool,
    root: str | os.PathLike[str] | None = None,
    overrides: dict[str, str] | None = None,
) -> dict[str, Path]:
    """Resolve all field paths for a business.

    Legacy business: every field lives at the legacy root (so it reuses the
    existing tokens.json, key, oauth-app, and rate files untouched).
    Non-legacy business: business fields live under its own root; shared fields
    stay at the legacy root. Explicit ``overrides`` win over both.
    """
    overrides = overrides or {}
    biz_root = LEGACY_ROOT if legacy else business_root(key, root)
    resolved: dict[str, Path] = {}
    for fieldname, (_env, filename) in ALL_FIELDS.items():
        if fieldname in overrides and overrides[fieldname]:
            resolved[fieldname] = Path(overrides[fieldname]).expanduser().resolve()
            continue
        if fieldname in SHARED_FIELDS:
            resolved[fieldname] = (LEGACY_ROOT / filename).resolve()
        else:
            resolved[fieldname] = (biz_root / filename).resolve()
    return resolved


def profile_from_entry(entry: dict[str, Any]) -> Profile:
    if not isinstance(entry, dict):
        raise ProfileError(f"registry entry is not an object: {entry!r}")
    key = validate_key(str(entry.get("key", "")))
    label = str(entry.get("label") or key)
    legacy = bool(entry.get("legacy", False))
    root = entry.get("root")
    overrides = entry.get("paths") or {}
    if not isinstance(overrides, dict):
        raise ProfileError(f"business {key!r}: 'paths' must be an object")
    profile_pack = entry.get("profile_pack")
    if profile_pack is not None and not isinstance(profile_pack, str):
        raise ProfileError(f"business {key!r}: 'profile_pack' must be a string path")
    tenant_id = entry.get("tenant_id")
    if tenant_id is not None and not isinstance(tenant_id, str):
        raise ProfileError(f"business {key!r}: 'tenant_id' must be a string")
    paths = resolve_paths(key=key, legacy=legacy, root=root, overrides=overrides)
    return Profile(
        key=key,
        label=label,
        legacy=legacy,
        paths=paths,
        root=str(root) if root else None,
        overrides=dict(overrides),
        profile_pack=profile_pack or None,
        tenant_id=str(tenant_id) if tenant_id else None,
    )


def implicit_default_profile() -> Profile:
    """The profile used when no registry exists: the legacy single business."""
    return Profile(
        key=IMPLICIT_DEFAULT_KEY,
        label="Default (legacy)",
        legacy=True,
        paths=resolve_paths(key=IMPLICIT_DEFAULT_KEY, legacy=True),
    )


# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------


@dataclass
class Registry:
    path: Path
    profiles: list[Profile] = field(default_factory=list)

    def get(self, key: str) -> Profile | None:
        for profile in self.profiles:
            if profile.key == key:
                return profile
        return None

    def legacy_profile(self) -> Profile | None:
        for profile in self.profiles:
            if profile.legacy:
                return profile
        return None

    def default_profile(self) -> Profile | None:
        """Profile to use when no --profile/XERO_PROFILE is given.

        Prefers the legacy entry; if exactly one business is registered, that
        one; otherwise None (ambiguous — caller must choose).
        """
        legacy = self.legacy_profile()
        if legacy is not None:
            return legacy
        if len(self.profiles) == 1:
            return self.profiles[0]
        return None


def registry_path(value: str | os.PathLike[str] | None = None) -> Path:
    raw = value or os.environ.get(REGISTRY_ENV)
    if raw:
        return Path(raw).expanduser().resolve()
    return DEFAULT_REGISTRY_PATH


def load_registry(path: str | os.PathLike[str] | None = None) -> Registry | None:
    """Load the business registry, or return None if no registry file exists."""
    resolved = registry_path(path)
    if not resolved.exists():
        return None
    try:
        raw = json.loads(resolved.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ProfileError(f"could not read business registry {resolved}: {exc}") from exc
    entries = raw.get("businesses") if isinstance(raw, dict) else None
    if not isinstance(entries, list):
        raise ProfileError(f"business registry {resolved} must contain a 'businesses' array")
    profiles = [profile_from_entry(entry) for entry in entries]
    keys = [p.key for p in profiles]
    dupes = {k for k in keys if keys.count(k) > 1}
    if dupes:
        raise ProfileError(f"duplicate business keys in registry: {sorted(dupes)}")
    legacy_count = sum(1 for p in profiles if p.legacy)
    if legacy_count > 1:
        raise ProfileError("at most one business may be marked 'legacy'")
    return Registry(path=resolved, profiles=profiles)


def save_registry(registry: Registry) -> Path:
    payload = {
        "version": REGISTRY_SCHEMA_VERSION,
        "businesses": [
            {
                "key": p.key,
                "label": p.label,
                **({"legacy": True} if p.legacy else {}),
                **({"root": p.root} if p.root and not p.legacy else {}),
                **({"paths": p.overrides} if p.overrides else {}),
                **({"profile_pack": p.profile_pack} if p.profile_pack else {}),
                **({"tenant_id": p.tenant_id} if p.tenant_id else {}),
            }
            for p in registry.profiles
        ],
    }
    registry.path.parent.mkdir(parents=True, exist_ok=True)
    registry.path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    return registry.path


def upsert_business(
    *,
    key: str,
    label: str | None = None,
    legacy: bool = False,
    root: str | None = None,
    profile_pack: str | None = None,
    tenant_id: str | None = None,
    path: str | os.PathLike[str] | None = None,
) -> tuple[Registry, Profile]:
    """Create or update a business entry and persist the registry.

    Creates the registry file (and the business directory for non-legacy
    businesses) if needed. Never touches token files of other businesses.
    """
    validate_key(key)
    resolved_path = registry_path(path)
    registry = load_registry(resolved_path) or Registry(path=resolved_path, profiles=[])
    if legacy:
        existing_legacy = registry.legacy_profile()
        if existing_legacy is not None and existing_legacy.key != key:
            raise ProfileError(
                f"business {existing_legacy.key!r} is already the legacy default; "
                "only one legacy business is allowed"
            )
    # Updating an existing entry must preserve its location overrides when the
    # caller doesn't re-specify them, or the authenticated token store under a
    # custom --root would be silently orphaned on a later relabel.
    existing = registry.get(key)
    if legacy:
        # Legacy businesses map to the legacy paths; drop any root/overrides.
        effective_root: str | None = None
        effective_overrides: dict[str, str] = {}
    else:
        effective_root = root if root is not None else (existing.root if existing else None)
        effective_overrides = dict(existing.overrides) if existing else {}
    effective_label = label or (existing.label if existing else None) or key
    # Preserve a linked pack across relabels/updates unless the caller resets it.
    effective_pack = profile_pack if profile_pack is not None else (existing.profile_pack if existing else None)
    # Preserve the pinned tenant across relabels/updates unless re-specified.
    effective_tenant = tenant_id if tenant_id is not None else (existing.tenant_id if existing else None)
    profile = Profile(
        key=key,
        label=effective_label,
        legacy=legacy,
        paths=resolve_paths(
            key=key, legacy=legacy, root=effective_root, overrides=effective_overrides
        ),
        root=str(effective_root) if effective_root else None,
        overrides=effective_overrides,
        profile_pack=effective_pack or None,
        tenant_id=effective_tenant or None,
    )
    registry.profiles = [p for p in registry.profiles if p.key != key] + [profile]
    save_registry(registry)
    if not legacy:
        business_root(key, effective_root).mkdir(parents=True, exist_ok=True)
    return registry, profile


def remove_business(
    key: str, *, path: str | os.PathLike[str] | None = None
) -> tuple[Registry, Profile]:
    """Remove a business entry. Does NOT delete its token files on disk."""
    resolved_path = registry_path(path)
    registry = load_registry(resolved_path)
    if registry is None:
        raise ProfileError("no business registry exists")
    profile = registry.get(key)
    if profile is None:
        raise ProfileError(f"no business named {key!r} in registry")
    registry.profiles = [p for p in registry.profiles if p.key != key]
    save_registry(registry)
    return registry, profile


# ---------------------------------------------------------------------------
# Active-profile resolution (used by the CLI)
# ---------------------------------------------------------------------------


def active_profile_key(explicit: str | None = None) -> str | None:
    if explicit:
        return explicit
    env_value = os.environ.get(PROFILE_ENV)
    return env_value or None


def resolve_active_profile(
    explicit: str | None = None, *, path: str | os.PathLike[str] | None = None
) -> Profile:
    """Resolve the profile to operate on, honouring --profile then XERO_PROFILE.

    With no registry and no explicit non-default key, returns the implicit
    legacy default so existing single-business behaviour is preserved.
    """
    key = active_profile_key(explicit)
    registry = load_registry(path)
    if registry is None:
        if key and key != IMPLICIT_DEFAULT_KEY:
            raise ProfileError(
                f"no business registry exists, so profile {key!r} is unknown; "
                "run `xero profiles add` first"
            )
        return implicit_default_profile()
    if key is None:
        default = registry.default_profile()
        if default is None:
            raise ProfileError(
                "multiple businesses are registered and none is the legacy default; "
                "pass --profile <key> (see `xero profiles list`)"
            )
        return default
    profile = registry.get(key)
    if profile is None:
        known = ", ".join(p.key for p in registry.profiles) or "(none)"
        raise ProfileError(f"unknown business {key!r}; registered: {known}")
    return profile


# ---------------------------------------------------------------------------
# Aggregator helpers (used by xero_mcp.py)
# ---------------------------------------------------------------------------


def plan_businesses(path: str | os.PathLike[str] | None = None) -> list[Profile]:
    """The businesses the aggregator should expose.

    No registry → a single implicit legacy default (today's behaviour).
    """
    registry = load_registry(path)
    if registry is None or not registry.profiles:
        return [implicit_default_profile()]
    return registry.profiles


def assign_prefixes(profiles: list[Profile]) -> list[tuple[Profile, str]]:
    """Decide each business's tool-name prefix.

    Safety rule: with two or more businesses every tool is prefixed with the
    business key, so no bare (ambiguous) tool name like ``create-invoice`` can
    exist. With a single business, names stay bare for backwards compatibility.
    """
    if len(profiles) <= 1:
        return [(profiles[0], "")] if profiles else []
    return [(profile, profile.key) for profile in profiles]
