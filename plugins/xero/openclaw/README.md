# Xero for OpenClaw

Unofficial OpenClaw integration maintained by Arc Forge Labs; not affiliated
with or endorsed by Xero Limited.

This package bundles the reusable Xero connector and a thin native OpenClaw
adapter. It supports cashflow, profit and loss, aged receivables/payables,
tenant checks, and dry-run finance workflows. Writes require an explicit
preflight/audit report and operator confirmation.

## OAuth setup

Xero uses a public OAuth Authorization Code + PKCE client. There is no client
secret or OpenClaw SecretRef configuration field. Configure the public app
placeholder as needed, then authenticate locally:

```sh
xero auth app-config
xero auth login
xero tenants list --refresh
xero tenants use <tenant-id>
```

Tokens remain in the connector's local protected store. Do not put tokens,
tenant IDs, or populated organisation profiles in this package.

## OpenClaw surfaces

- Native MCP server: `xero`
- Read-only local tool: `xero_status`
- Read-only Gateway bindings: `xero.status`, `xero.oauth.contract`,
  `xero.tenants.local`
- CLI command: `openclaw xero ...`

The package is OpenClaw-only. It does not publish Codex, Claude, Cursor, or
ClawHub catalog metadata.
