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

## OpenClaw surfaces

- Native MCP server: `xero`
- Read-only local tool: `xero_status`
- Read-only Gateway bindings: `xero.status`, `xero.oauth.contract`,
  `xero.tenants.local`
- CLI command: `openclaw xero ...`

The package is OpenClaw-only. It does not publish Codex, Claude, Cursor, or
ClawHub catalog metadata.
