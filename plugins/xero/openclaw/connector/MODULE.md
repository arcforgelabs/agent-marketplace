# Xero Connector

Status: `prototype-core`

Last updated: 2026-06-07.

## Intent

Provide a reusable Xero plugin across MCP, CLI, and agent harnesses. The core
plugin should let users authorize their own Xero account without creating a
developer app, then expose Xero's official MCP/API surface with local token
refresh, rate-limit guardrails, finance-rule helpers, and optional CDP
reconciliation finalization.

## Users

- Local finance operator using Codex, Claude Desktop, Cursor, or CLI.
- Developer building finance-ops workflows on top of Xero.
- Agent performing full-power Xero API reads/writes for an authenticated local
  operator.

## Inputs

- Xero OAuth authorization through the Arc Forge-owned app.
- Local refresh-token state and active tenant selection.
- Accounting object requests for contacts, invoices, accounts, bank transactions, expenses, and reports.
- Finance-rule files for naming conventions, mappings, dedup, and audit output.
- Optional user-provided logged-in browser/CDP endpoint for reconciliation.
- Official Xero docs for current behavior.

## Outputs

- Xero API reads and writes through MCP/CLI.
- Local auth status, tenant status, and rate-limit status.
- Dry-run and apply audit reports.
- MCP tool surface.
- Optional CDP reconciliation actions against an already authenticated browser
  session.

## Included Assets

- Components: `components/skills/xero`, `components/mcp/xero`.
- Plugin package: `plugins/xero`.
- Local CLI/MCP wrapper: `connectors/xero/cli`, `connectors/xero/mcp`.
- Finance rules: `connectors/xero/finance-rules`.
- Reconciliation companion: `connectors/xero/reconciliation`.
- Docs: plugin architecture, API/CDP map, implementation plan, source migration
  notes, and official documentation freshness manifest.
- Prototype MCP: copied Python source at `components/mcp/xero`.

## Harness Compatibility

| Harness | Status | Notes |
| --- | --- | --- |
| Codex | `prototype` | Repo-local plugin package with MCP + CLI + optional CDP finalizer exists. |
| Claude Desktop | `prototype` | `xero-mcp-local print-config --harness claude-desktop` emits local wrapper config. |
| Cursor | `prototype` | `xero-mcp-local print-config --harness cursor` emits local wrapper config. |
| OpenClaw | `prototype` | Reusable CLI/MCP surfaces exist; live tenant proof remains pending. |
| Claude Code | `prototype-source` | Existing Python MCP source was built for Claude Code and remains prior art. |

## Boundaries

Generic Xero connector code must not include one business's private account
mappings, tax treatment decisions, customer bookkeeping rules, or local secret
item names as defaults. Reusable rule schemas belong in the plugin; private
rules belong in deployment config or a private finance-ops package.

Never print access tokens, refresh tokens, `BW_SESSION`, client secrets, MFA
codes, cookies, browser profile data, or authorization headers.

The core Xero plugin must not package login automation, MFA retrieval,
credential entry, or Cloudflare/security-control bypass behavior. It may attach
to a CDP endpoint only after the user has already authenticated the browser.

For MVP, do not prune the official Xero MCP tool surface. Document and
rate-govern full-power operations instead.

## Proof Status

- `[validated]` Source MCP server exists at `components/mcp/xero` with Python FastMCP implementation.
- `[validated]` Generic Xero skill component exists at `components/skills/xero`.
- `[validated]` Official Xero MCP server exists at `XeroAPI/xero-mcp-server`
  and is published as `@xeroapi/xero-mcp-server`.
- `[prototype]` Local PKCE CLI exists at `connectors/xero/cli/xero`; its token
  store writes an encrypted JSON envelope by default when Python `cryptography`
  is available and migrates legacy plaintext on save. Offline tests cover PKCE
  authorization URL construction, localhost callback handling, token exchange,
  tenant fetch, active-tenant selection, and token persistence.
- `[prototype]` Read-only Organisation and Accounts smoke commands exist for
  live tenant validation.
- `[prototype]` Official MCP runtime patcher/launcher exists at
  `connectors/xero/mcp/xero-mcp-local`.
- `[prototype]` Official MCP pre-dispatch governor, shared JSON minute/day
  budget store, safe rate-header observation, bounded one-shot Retry-After
  handling, and `xero rate status` exist. JSON-backed FIFO operation lock
  commands exist. Offline tests cover direct CLI Accounting API budget
  accounting, minute/app exhaustion, DayLimit pressure, and redacted status
  output. Live tenant header smoke and live multi-process contention proof are
  still planned.
- `[prototype]` Generic finance-rules template, parser/mapping helpers,
  snapshot duplicate checks, and `xero audit dry-run` exist.
  Read-only reference snapshot fetch/list commands and targeted live-check
  commands exist. `xero reports get` covers profit and loss, balance sheet,
  trial balance, aged receivables, and aged payables. `xero evidence` covers
  allowlisted history notes and attachments. `xero prework create` provides
  dry-run-first API pre-work for payments, bank transactions, bank transfers,
  and manual journals with redacted apply-report ledger entries. Live tenant
  smoke and broader live write flows are still planned.
- `[prototype]` Install docs, OAuth/MFA docs, limits docs, workflow playbooks,
  harness-specific MCP config snippets for generic JSON, Claude Desktop,
  Cursor, and Codex, and a dated official-docs freshness manifest exist.
- `[prototype]` Repo-local Codex plugin scaffold exists at `plugins/xero` with
  `.codex-plugin/plugin.json`, `.mcp.json`, and plugin skill shim.
- `[prototype]` CDP reconciliation companion exists and refuses to run
  without an explicit user-provided endpoint. It can inspect targets, capture
  visible statement-line text, dry-run expected matches, and execute
  explicit-plan row-scoped apply clicks plus explicit match-dialog
  search/select/confirm actions gated by `--confirm-apply`. Live Xero selector
  proof remains planned.

## Smoke Test

After the core MVP implementation, install fresh, run `xero auth login`, select
a tenant, start the MCP, and run read-only organisation/accounts smoke checks
without touching live bookkeeping data.

Current local non-live validation:

```bash
connectors/xero/scripts/validate-xero
python3 connectors/xero/tests/test_xero_core.py
scripts/forge-tools module validate connectors/xero
scripts/forge-tools run xero doctor
scripts/forge-tools run xero auth app-config
connectors/xero/cli/xero rate unblock-day-limit --holder validator --reason local-validator --day-key 2026-06-06 --unblock-store /tmp/xero-rate-unblock-validator.json
connectors/xero/cli/xero-smoke
scripts/forge-tools run xero auth status
scripts/forge-tools run xero rate status --include-cli
scripts/forge-tools run xero lock status
scripts/forge-tools run xero rules validate --rules connectors/xero/finance-rules/templates/default-rules.json
connectors/xero/mcp/xero-mcp-local self-test
connectors/xero/mcp/xero-workflows-mcp self-test
connectors/xero/mcp/xero-mcp-local status
connectors/xero/mcp/xero-mcp-local surface --strict
connectors/xero/mcp/xero-mcp-local protocol-smoke --strict
connectors/xero/mcp/xero-mcp-local print-config --harness claude-desktop
plugins/xero/scripts/install-xero-plugin --target generic --dry-run
connectors/xero/reconciliation/xero-reconcile apply --help
connectors/xero/mcp/xero-mcp-local --cache "$(mktemp -d)" prepare
python3 /home/samuel/.codex-accounts/shared/skills/.system/plugin-creator/scripts/validate_plugin.py plugins/xero
connectors/xero/reconciliation/xero-reconcile status
```

## Open Questions

- `[question]` Should the encrypted local file token store later grow an OS
  keychain or hardware-backed key backend?
- `[question]` Should the official MCP wrapper remain a runtime patcher or move
  to a maintained source fork once live validation stabilizes?
- `[question]` Which live tenant and demo records should be used for the first
  read-only OAuth/MCP smoke and controlled Reconcile-tab proof?
