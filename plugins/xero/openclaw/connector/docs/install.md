# Xero Plugin Install

## Shared callback (public package 0.3+)

The package includes the public client ID. Approved installations run
`xero auth login --print-url`, receiving a short connect.arcforge.au link.
An operator provisions `~/.config/arc-forge-tools/xero/connect-credential`
(mode 0600). This private installation credential is not a Xero client secret.
No inbound callback port, tunnel, or customer-specific URI is needed.
Link lifetime: ten minutes; a new attempt replaces the old link.
Verify token exchange and `xero smoke organisation` before reporting success.
Explicit `--redirect-uri` retains the direct callback mode documented below.


This connector is designed for local single-user operation. Users need their own
Xero account and access to a Xero organisation; they should not need their own
Xero developer app credentials.

## Prerequisites

- `python3`
- Python `cryptography` package for encrypted token storage
- `node`
- `npm`
- The Arc Forge Xero OAuth public client ID, either packaged in
  `plugins/xero/oauth-app.json`, written to
  `~/.config/arc-forge-tools/xero/oauth-app.json`, or supplied in
  `ARC_FORGE_XERO_CLIENT_ID`

No browser automation dependency is required for the core MCP.

## First Run

For the repo-local Codex plugin package, use the installer:

```bash
plugins/xero/scripts/install-xero-plugin --target codex
```

If the public client ID is not packaged yet, an operator can write it to local
config during install:

```bash
plugins/xero/scripts/install-xero-plugin --target codex --client-id <public-client-id>
```

To package the public client ID into the plugin for release builds, use:

```bash
plugins/xero/scripts/install-xero-plugin --target codex --client-id <public-client-id> --package-client-id
connectors/xero/scripts/validate-xero --release
```

The direct CLI equivalent is:

```bash
connectors/xero/cli/xero auth configure-app --client-id <public-client-id>
connectors/xero/cli/xero auth app-config --strict
```

To write only the local public-client-id config without preparing the MCP cache
or running smoke checks:

```bash
plugins/xero/scripts/install-xero-plugin --target codex --client-id <public-client-id> --client-id-only
```

For a no-change preview:

```bash
plugins/xero/scripts/install-xero-plugin --target codex --dry-run
```

The installer prepares the official MCP cache, validates the plugin package,
prints the MCP config snippet for the selected harness, and runs local
no-network readiness checks. It does not start OAuth or automate browser login.

Manual equivalent:

```bash
connectors/xero/cli/xero doctor
connectors/xero/cli/xero auth configure-app --client-id <public-client-id>
connectors/xero/cli/xero auth app-config
connectors/xero/scripts/validate-xero
connectors/xero/mcp/xero-mcp-local prepare
connectors/xero/mcp/xero-mcp-local status
connectors/xero/mcp/xero-mcp-local protocol-smoke --strict
connectors/xero/mcp/xero-workflows-mcp self-test
connectors/xero/cli/xero auth login
connectors/xero/cli/xero tenants list --refresh
connectors/xero/cli/xero tenants use <tenant-id>
connectors/xero/cli/xero doctor --strict
connectors/xero/cli/xero smoke organisation
connectors/xero/cli/xero smoke accounts
connectors/xero/cli/xero-smoke --live-api
connectors/xero/scripts/validate-xero --live-api
```

`auth login` opens the browser. The user signs in to Xero, completes MFA, chooses
the organisation, and grants consent. The CLI captures only the localhost OAuth
callback and writes local token state.

Token writes are atomic and keep a local `0600` backup of the previous token
store at `tokens.json.bak`. `xero auth status` reports whether that backup
exists without printing token material.

`auth app-config` is a no-network check for the Arc Forge-owned Xero app setup.
It prints the public-client source, localhost redirect URI, default scopes, and
confirms that no client secret is required for the PKCE flow. Client-id lookup
order is command argument, environment, local user config, plugin packaged
config, then connector packaged config.

## MCP Config

Print a config snippet for the target harness:

```bash
connectors/xero/mcp/xero-mcp-local status
connectors/xero/mcp/xero-mcp-local surface
connectors/xero/mcp/xero-mcp-local protocol-smoke --strict
connectors/xero/mcp/xero-workflows-mcp self-test
connectors/xero/mcp/xero-mcp-local print-config --harness claude-desktop
connectors/xero/mcp/xero-mcp-local print-config --harness cursor
connectors/xero/mcp/xero-mcp-local print-config --harness codex
connectors/xero/mcp/xero-mcp-local print-config --harness generic
```

Then place the returned snippet in the harness's MCP config location.

The single public `xero` MCP server is an aggregator that proxies two backends:

- `xero-official`: the patched official Xero MCP package.
- `xero-workflows`: local finance-rule, audit, document action, API
  pre-work, and CDP-reconciliation helper tools that delegate to
  `connectors/xero/cli/xero` and `connectors/xero/reconciliation/xero-reconcile`.

The runtime MCP config points at repo-local wrapper commands and local token/rate
state. It should not include `XERO_CLIENT_ID`, `XERO_CLIENT_SECRET`,
`XERO_CLIENT_BEARER_TOKEN`, or `ARC_FORGE_XERO_CLIENT_ID`; the public OAuth
client ID is needed for setup/login only, not for launching the MCP server after
tokens are stored.

The MCP server command is:

```bash
connectors/xero/mcp/xero-mcp-local run
```

The wrapper downloads Xero's official MCP package into
`~/.cache/arc-forge-tools/xero-mcp`, patches only the official auth client, and
runs the patched MCP over stdio.

`xero-mcp-local status` is a no-network readiness check. It verifies the local
cache, patch markers, local CLI path, Node/npm availability, and rate-status
store without refreshing OAuth or calling Xero.

`xero-mcp-local surface` is also no-network. It inventories the prepared
official MCP package and checks the required Xero API categories against
official MCP tools plus local CLI companion helpers.

`xero-mcp-local protocol-smoke --strict` starts the patched official MCP server
over stdio, completes MCP `initialize` and `tools/list`, then exits. It does not
invoke a Xero API tool, so it should not consume Xero API rate limit budget.

`xero-workflows-mcp self-test` validates the local companion MCP tool catalog
without contacting Xero.

## Codex Plugin Package

The repo-local Codex plugin package lives at:

```text
plugins/xero
```

Validate the plugin manifest with:

```bash
python3 /home/samuel/.codex-accounts/shared/skills/.system/plugin-creator/scripts/validate_plugin.py plugins/xero
```

The plugin references the same local MCP wrapper and does not copy connector
implementation.

## Local State

Default runtime paths:

- Tokens: `~/.config/arc-forge-tools/xero/tokens.json`
- Token encryption key: `~/.config/arc-forge-tools/xero/token-store.key`
- Rate status: `~/.config/arc-forge-tools/xero/rate-limit-status.json`
- Shared MCP/CLI rate budget: `~/.config/arc-forge-tools/xero/rate-limit-shared.json`
- Direct CLI rate status: `~/.config/arc-forge-tools/xero/rate-limit-cli-status.json`
- Operation lock: `~/.config/arc-forge-tools/xero/operation-lock.json`
- Finance rules: `~/.config/arc-forge-tools/xero/finance-rules.json`
- Snapshots: `~/.config/arc-forge-tools/xero/snapshots/`
- Audit reports: `~/.config/arc-forge-tools/xero/audit/`

Do not commit any of those runtime files.

The token store defaults to encrypted-at-rest mode when Python `cryptography` is
available. Existing plaintext token files are readable and migrate to encrypted
format on the next write. Use `connectors/xero/cli/xero auth status` to confirm
`token_store_encrypted: true`.

## Status Checks

```bash
connectors/xero/cli/xero doctor
connectors/xero/scripts/validate-xero
connectors/xero/cli/xero doctor --strict
connectors/xero/cli/xero-smoke
connectors/xero/cli/xero auth status
connectors/xero/cli/xero auth app-config
connectors/xero/cli/xero auth migrate-store
connectors/xero/cli/xero rate status
connectors/xero/cli/xero rate status --include-cli
connectors/xero/cli/xero lock status
connectors/xero/cli/xero rules validate
connectors/xero/cli/xero audit list-apply
```

`doctor` does not call Xero. It checks local runtime dependencies, plugin files,
MCP wrapper availability, token-store encryption, OAuth app setup, OAuth token
presence, active tenant selection, finance-rules initialization, and local
rate-limit status.

`validate-xero` runs the no-network connector gate: unit tests, installer
syntax, doctor, OAuth app-config, rate/lock status, finance-rule template
validation, MCP wrapper checks, MCP protocol smoke, plugin validation,
reconciliation status, architecture coverage, and official-doc freshness. It
does not start OAuth, automate browser login, or call Xero APIs. Its top-level
`readiness` object separates local package readiness from auth/tenant readiness,
and its `architecture_coverage` object proves the core, MCP, governor,
finance-rules, API map, reconciliation, plugin, and official-doc surfaces are
present.
Before OAuth is configured, the nested `doctor` payload can report
`auth_ok: false`; that is expected for the no-network gate as long as required
local commands and package checks pass.

Use `connectors/xero/scripts/validate-xero --release` for a distributable plugin
gate. It keeps the normal no-network checks and additionally requires
`plugins/xero/oauth-app.json` to contain the Arc Forge public Xero OAuth client
ID with no client secret. This is the proof that installed users only need their
own Xero account, not their own developer app credentials.

## Live Validation

Use `validate-xero --live-api` after the user has completed `xero auth login`
and selected a tenant. It runs the no-network connector gate first, then
delegates to `xero-smoke --live-api` for live read-only CLI and MCP proof. It
never starts OAuth or login itself.

```bash
connectors/xero/scripts/validate-xero --live-api
```

For an already-authenticated browser with a Xero Reconcile tab open:

```bash
connectors/xero/scripts/validate-xero \
  --live-api \
  --cdp-endpoint ws://127.0.0.1:9222/devtools/browser/<id> \
  --expected ./expected-reconciliation.json
```

Use `xero-smoke` directly only when you want just the smoke artifact without the
full validator envelope:

```bash
connectors/xero/cli/xero-smoke --live-api
```

For an already-authenticated browser with a Xero Reconcile tab open:

```bash
connectors/xero/cli/xero-smoke \
  --live-api \
  --cdp-endpoint ws://127.0.0.1:9222/devtools/browser/<id> \
  --expected ./expected-reconciliation.json
```

The report is written under
`~/.config/arc-forge-tools/xero/smoke/` by default and includes local readiness,
MCP wrapper checks, live read-only CLI API smoke results, a live read-only MCP
tool call through `xero-mcp-local live-smoke`, and optional CDP
inspection/capture artifacts. The MCP live smoke invokes
`list-organisation-details` by default, so it proves the patched official MCP
server can obtain a fresh access token from the local token provider and use the
selected tenant.

## Reconciliation Extension

The core install does not package login automation, MFA handling, Cloudflare
bypass, or browser-session acquisition. The future reconciliation extension may
attach to a user-provided already-authenticated CDP session for Reconcile-tab
finalization only. Live CDP capture/apply uses the optional Python
`websockets` package; `xero-reconcile status` reports whether that dependency is
available. Snapshot-based dry-run reports do not require it.
