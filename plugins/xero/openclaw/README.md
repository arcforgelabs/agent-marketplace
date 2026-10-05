# Xero for OpenClaw

Unofficial OpenClaw integration maintained by Arc Forge Labs; not affiliated
with or endorsed by Xero Limited.

This package bundles the reusable Xero connector and a thin native OpenClaw
adapter. It supports cashflow, profit and loss, aged receivables/payables,
tenant checks, and dry-run finance workflows. Writes require an explicit
preflight/audit report and operator confirmation.

## OAuth setup

The public Arc Forge Xero PKCE client ID is bundled as configuration, not a
secret. Approved installations use the shared HTTPS callback at
`https://connect.arcforge.au/xero/callback`. No customer callback registration,
SSH tunnel, or Cloudflare Access exception is needed for this mode.

An operator provisions an installation credential at
`~/.config/arc-forge-tools/xero/connect-credential` (mode `0600`), or points
`ARC_FORGE_XERO_CONNECT_CREDENTIAL_FILE` at a private credential file. This
credential authorizes our handoff service; it is **not** a Xero client secret
and must never be bundled or pasted into chat.
Operators issue and enrol it with the gateway procedure in
`services/xero-connect/README.md` ("Issuing an installation approval").

```sh
xero auth app-config
xero auth login --print-url
xero tenants list --refresh
xero tenants use <tenant-id>
xero smoke organisation
```

The CLI prints a short **Connect Xero** link. Preserve it exactly. The user
checks the installation name, clicks Continue, and completes Xero login/MFA.
Keep the CLI process alive until it saves the tokens. A link expires after ten
minutes; creating another replaces the previous attempt. A received code is
retained for at most two minutes and can be retrieved once. Failed/interrupted
attempts require a fresh login; existing tokens are not cleared.

PKCE verifiers and Xero tokens stay on the installation. The service holds only
the temporary authorization result; outbound polling retrieves it. The browser
says authorization was received, not that token exchange already succeeded.
Only successful token exchange plus an organisation API check proves connection.

Existing direct callbacks remain supported with an explicit `--redirect-uri`
(or `ARC_FORGE_XERO_REDIRECT_URI`). Do not migrate an existing grant merely to
adopt the shared callback. Direct callbacks must already be registered with Xero.

Tokens remain in the connector's local protected store. Do not put tokens,
tenant IDs, installation credentials, or populated profiles in this package.

## Shared MCP server (0.4+)

The `xero` MCP server is one shared streamable-HTTP server at
`http://127.0.0.1:8796/mcp`. It is not a stdio process per agent session.
Every session on the Gateway shares one backend chain: the official Xero Node
server and the workflows companion, per business. Stdio MCP runtimes are
session-scoped in OpenClaw and stay alive until the session is reset, so the
old per-session chain grew with the number of sessions.

The plugin owns the server. At Gateway start a background service probes
`/healthz`. If nothing healthy answers, it starts one server, restarts it if
it crashes, and stops it with the Gateway. Because the plugin starts it, the
server always runs the current plugin version after `openclaw plugins update`
and a Gateway restart. If an operator already runs the systemd unit
(`xero-mcp service install`), the plugin stands down. Set
`plugins.entries.arcforgelabs-xero.config.sharedServiceAutoStart` to `false`
to require an external server.

The server binds loopback only and checks `Host`/`Origin`. Tokens never
reach it through the environment; they stay in the encrypted local store.

```sh
openclaw mcp status --verbose          # xero: streamable-http, 127.0.0.1:8796
xero-mcp health                        # exit 0 when every backend is up
```

`xero_status` reports the same health under `sharedService`. As a safety net
for any remaining stdio MCP servers, set `mcp.sessionIdleTtlMs` (for example
`600000`, 10 minutes). Apply plugin installs and updates with a Gateway restart.

## Tool policy

`xero_status` is read-only and joins the `coding`, `messaging` and `full`
profiles. `xero_evidence_attachments` and `xero_evidence_audit` can write files
on the Gateway host, so they are opt-in. A host with a restrictive
`tools.allow` list grants the plugin by id rather than listing every tool:

```sh
openclaw config set tools.alsoAllow --strict-json '["arcforgelabs-xero"]'
```

Merge `arcforgelabs-xero` into an existing `alsoAllow` array; do not replace
unrelated entries. `tools.sandbox.tools` is a separate gate. The Xero API tools
come from the `xero` MCP server and follow the normal MCP tool policy. Verify
with `xero_status` in a fresh session.

## OpenClaw surfaces

- Native MCP server: `xero` (shared streamable HTTP, loopback)
- Read-only local tool: `xero_status`
- Read-only Gateway bindings: `xero.status`, `xero.oauth.contract`,
  `xero.tenants.local`
- CLI command: `openclaw xero ...`

The package is OpenClaw-only. It does not publish Codex, Claude, or
ClawHub catalog metadata.
