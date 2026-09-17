# Xero Connector

Status: `prototype-core`

Connector and plugin plan for Xero Accounting API, local user OAuth, MCP/CLI
workflows, finance-rule helpers, and minimum CDP reconciliation finalization.

## Direction

Use the official Xero MCP server as the API foundation, but wrap or fork its
auth client so local users can sign in with their own Xero account through an
Arc Forge-owned OAuth app. Users should not need their own Xero developer
credentials.

The core plugin should be valuable without browser automation. CDP/Playwright
belongs in an optional reconciliation companion that attaches to an already
logged-in browser session and only handles Xero UI gaps such as final
Reconcile-tab statement-line matching.

## Current Sources

- Official MCP: <https://github.com/XeroAPI/xero-mcp-server>
- Published package: `@xeroapi/xero-mcp-server`
- Existing prototype copy: `components/mcp/xero`
- Generic skill: `components/skills/xero`
- Lab Flow prior art: `~/repos/lab-flow/server/src/xero`

The existing Python MCP copy is useful prior art but is not the target core. It
mixes local credential assumptions and browser automation scripts with API
tools. The target core is a TypeScript official-MCP wrapper/fork with local
PKCE auth, token storage, rate governance, and CLI helpers.

## Design Docs

- [Plugin architecture](docs/plugin-architecture.md)
- [API vs CDP responsibility map](docs/api-vs-cdp-map.md)
- [Implementation plan](docs/implementation-plan.md)
- [Install and MCP config](docs/install.md)
- [OAuth, MFA, and user login](docs/oauth-mfa.md)
- [Xero API limits](docs/limits.md)
- [Workflow playbooks](docs/workflow-playbooks.md)
- [Invoice browser workflows](docs/invoice-browser-workflows.md)
- [Source migration notes](docs/source-migration-notes.md)
- [Reconciliation companion](reconciliation/README.md)

## Plugin Package

The repo-local Codex plugin scaffold lives at `plugins/xero`.

- Manifest: `plugins/xero/.codex-plugin/plugin.json`
- MCP config: `plugins/xero/.mcp.json`
- Plugin skill shim: `plugins/xero/skills/xero-plugin/SKILL.md`

The plugin package references this connector rather than copying
implementation. Validate it with:

```bash
connectors/xero/scripts/validate-xero
python3 /home/samuel/.codex-accounts/shared/skills/.system/plugin-creator/scripts/validate_plugin.py plugins/xero
```

## Current CLI Slice

The first `xero-core` slice is available at `connectors/xero/cli/xero`.

```bash
connectors/xero/cli/xero doctor
connectors/xero/scripts/validate-xero
connectors/xero/cli/xero doctor --strict
connectors/xero/cli/xero-smoke
connectors/xero/cli/xero-smoke --live-api
connectors/xero/cli/xero auth status
connectors/xero/cli/xero auth app-config
connectors/xero/cli/xero auth login
connectors/xero/cli/xero auth migrate-store
connectors/xero/cli/xero auth token
connectors/xero/cli/xero tenants list
connectors/xero/cli/xero tenants use <tenant-id>
connectors/xero/cli/xero rate status
connectors/xero/cli/xero lock status
connectors/xero/cli/xero lock acquire --holder catalog-refresh --wait
connectors/xero/cli/xero lock release <lease-id>
connectors/xero/cli/xero rules init
connectors/xero/cli/xero rules validate
connectors/xero/cli/xero rules parse-name "INV-1001 Example"
connectors/xero/cli/xero rules map contact "Example Customer"
connectors/xero/cli/xero rules upsert-mapping contact --name example-contact --alias "Example Customer" --target-json '{"name":"Example Customer Pty Ltd"}'
connectors/xero/cli/xero snapshots fetch accounts
connectors/xero/cli/xero snapshots list
connectors/xero/cli/xero reports get profit-and-loss --from-date 2026-01-01 --to-date 2026-01-31
connectors/xero/cli/xero reports get balance-sheet --date 2026-01-31
connectors/xero/cli/xero evidence history get invoice <invoice-id>
connectors/xero/cli/xero evidence history add-note invoice <invoice-id> --details "Reviewed source evidence"
connectors/xero/cli/xero evidence attachments list invoice <invoice-id>
connectors/xero/cli/xero evidence attachments upload invoice <invoice-id> --file ./receipt.pdf
connectors/xero/cli/xero documents create invoice --payload ./invoice.json
connectors/xero/cli/xero documents create invoice --payload ./invoice.json --apply --preflight-report ./invoice-dry-run.json
connectors/xero/cli/xero documents create bill --payload ./bill.json --apply --preflight-report ./bill-dry-run.json
connectors/xero/cli/xero documents create quote --payload ./quote.json --apply --preflight-report ./quote-dry-run.json
connectors/xero/cli/xero documents create credit-note --payload ./credit-note.json --apply --preflight-report ./credit-note-dry-run.json
connectors/xero/cli/xero documents update invoice --identifier INV-123 --status VOIDED
connectors/xero/cli/xero documents update quote --identifier <quote-id> --status SENT --apply --preflight-report ./quote-sent-dry-run.json
connectors/xero/cli/xero documents action invoice online-url --identifier <invoice-id>
connectors/xero/cli/xero documents action invoice email --identifier <invoice-id> --apply --preflight-report ./invoice-email-dry-run.json
connectors/xero/cli/xero reference upsert contact --payload ./contact.json
connectors/xero/cli/xero reference upsert item --payload ./item.json --apply --preflight-report ./item-dry-run.json
connectors/xero/cli/xero reference upsert account --payload ./account.json --method PUT --apply --preflight-report ./account-dry-run.json
connectors/xero/cli/xero reference upsert tracking-category --payload ./tracking-category.json --apply --preflight-report ./tracking-category-dry-run.json
connectors/xero/cli/xero prework create payment --payload ./payment.json
connectors/xero/cli/xero prework create payment --payload ./payment.json --apply --preflight-report ./payment-prework.json
connectors/xero/cli/xero prework create batch-payment --payload ./batch-payment.json --apply --preflight-report ./batch-payment-prework.json
connectors/xero/cli/xero audit dry-run --candidates ./candidates.json
connectors/xero/cli/xero audit check-live invoice INV-1001
connectors/xero/cli/xero audit record-apply --event ./apply-event.json
connectors/xero/cli/xero audit list-apply
connectors/xero/cli/xero smoke organisation
connectors/xero/cli/xero smoke accounts
```

`auth login` uses OAuth Code + PKCE with the public client ID for the
Arc Forge-owned Xero OAuth app. The client ID can be packaged in
`plugins/xero/oauth-app.json`, written to local user config at
`~/.config/arc-forge-tools/xero/oauth-app.json`, or supplied with
`ARC_FORGE_XERO_CLIENT_ID`. It stores local token state at
`~/.config/arc-forge-tools/xero/tokens.json` by default, or at
`XERO_TOKEN_STORE` when set. The store defaults to an encrypted JSON envelope
when Python `cryptography` is available; the token file and local key file are
written with `0600` permissions and status output redacts token fields.

`doctor` is a no-network readiness check for the local plugin install. It
reports base install state, OAuth/token/tenant state, local finance-rules
state, plugin manifest state, and the last rate-limit snapshot. Use
`doctor --strict` when a harness should fail fast unless the local MCP is ready
to run against an authenticated tenant.
`xero-smoke` writes one report across local readiness, MCP wrapper checks,
optional live read-only API smoke, and optional CDP reconciliation capture.

`auth token` intentionally emits a live bearer token for trusted local wrapper
processes. Do not paste that output into prompts, logs, tickets, or shell
history.

The first `xero-audit` slice is local-only. `rules init` creates a private
finance-rules file under `~/.config/arc-forge-tools/xero/finance-rules.json`.
The committed template is generic and intentionally contains no private account
codes, contacts, or tax decisions. `audit dry-run` checks candidate writes
against those rules and optional local snapshots before any live Xero mutation.
When a candidate has unmapped inputs, the report includes review-only
`mapping_suggestions` with `rules upsert-mapping` command templates.
`rules upsert-mapping` records a reviewed local alias or pattern decision so
future dry-runs resolve the same source convention without hand-editing JSON.
`snapshots fetch` is read-only and limited to stable reference data:
`accounts`, `tax-rates`, `items`, `contacts`, and `tracking-categories`.
`audit check-live` performs targeted read-only API checks by reference, name, or
code so write flows do not need broad invoice/contact sweeps before mutation.
`audit record-apply` writes a local redacted apply report and append-only ledger
entry for created, updated, skipped, or failed outcomes from future write flows.
`documents create` is the dry-run-first CLI write helper for invoices, bills,
quotes, and credit notes. It accepts Xero-shaped JSON, adds only safe document
type defaults for sales invoices and bills, and writes the same redacted apply
report ledger when `--apply --preflight-report <dry-run-or-audit-report>` is
used. Bare `--apply` is rejected unless the operator supplies the explicit
`--confirm-apply-without-preflight` override.
`documents update` applies the same guardrail to document lifecycle changes and
payload updates. It supports status updates such as invoice `AUTHORISED`,
`VOIDED`, or `DELETED` and quote `SENT`, `ACCEPTED`, `DECLINED`, or `DELETED`.
`documents action invoice` covers specialized sales-invoice actions: retrieving
the online invoice URL and triggering Xero's invoice email. Both are dry-run
first and write the redacted apply-report ledger when `--apply` is used.
`reference upsert` provides dry-run-first create/update helpers for contacts,
items, accounts, tracking categories, and tracking options. Tax-rate mutation
is intentionally not included in the generic helper; use snapshots to read tax
rates and encode tax policy in private finance rules.

`lock acquire` is a local FIFO lease gate for heavy workflows such as catalog
refreshes and future batch writes. It stores state at
`~/.config/arc-forge-tools/xero/operation-lock.json`, or at
`ARC_FORGE_XERO_OPERATION_LOCK_STORE` when set.

## Current MCP Bridge

The official API bridge is available at `connectors/xero/mcp/xero-mcp-local`.
It downloads Xero's official MCP package into a runtime cache, installs runtime
dependencies there, patches only the compiled official auth client to call the
local `xero auth token` provider, and runs the patched official MCP over stdio.

```bash
connectors/xero/mcp/xero-mcp-local prepare
connectors/xero/mcp/xero-mcp-local status
connectors/xero/mcp/xero-mcp-local surface
connectors/xero/mcp/xero-mcp-local protocol-smoke --strict
connectors/xero/mcp/xero-mcp-local print-config --harness claude-desktop
connectors/xero/mcp/xero-mcp-local print-config --harness cursor
connectors/xero/mcp/xero-mcp-local print-config --harness codex
connectors/xero/mcp/xero-mcp-local run
```

This preserves the official MCP tool surface while replacing the stock Custom
Connection/pre-supplied-bearer startup path with the local user OAuth token
provider.

The bridge also injects a pre-dispatch governor around Xero SDK API objects. It
keeps an in-process queue for per-process concurrency and uses a shared JSON
budget file for cross-process tenant minute, tenant daily, and app-wide minute
accounting. It defaults to conservative headroom for Xero's tenant limits and
writes an operator-visible snapshot to
`~/.config/arc-forge-tools/xero/rate-limit-status.json`, or to
`ARC_FORGE_XERO_RATE_LIMIT_STORE` when set. The snapshot also records safe Xero
remaining-limit headers when responses expose them and tracks bounded
`Retry-After` handling for 429 responses.

The shared MCP/CLI budget store defaults to
`~/.config/arc-forge-tools/xero/rate-limit-shared.json`, or to
`ARC_FORGE_XERO_SHARED_RATE_LIMIT_STORE` when set. Direct CLI Accounting API
helpers reserve from this same file before live calls and also write a separate
CLI status snapshot visible with `xero rate status --include-cli`.

`xero-mcp-local surface` inventories the prepared official MCP package and maps
its tool names against the plugin's required API categories. It also records
which categories are intentionally covered by local CLI companion commands, such
as batch-payment pre-work, bank transfers, attachments/history, dedup/audit,
reference snapshots, and targeted live checks. The report also includes
`mutation_safety`, which lists official mutating MCP tools and the local
preflight-enforced CLI/MCP helper routes that should be used for audited
accounting writes.

`xero-mcp-local protocol-smoke --strict` starts the patched official MCP over
stdio, performs MCP `initialize` plus `tools/list`, and exits without invoking
any Xero API tool. Use it after `prepare` to prove the server boots and exposes
the expected official tool names before doing live OAuth/API validation.

The plugin workflow companion is available at
`connectors/xero/mcp/xero-workflows-mcp`. It exposes local dry-run/audit/pre-work
and CDP reconciliation helper tools as MCP tools while delegating execution to
the trusted local CLI:

```bash
connectors/xero/mcp/xero-workflows-mcp self-test
connectors/xero/mcp/xero-workflows-mcp list-tools
connectors/xero/mcp/xero-workflows-mcp run
```

The public `xero` MCP is a single aggregator (`connectors/xero/mcp/xero-mcp`)
that proxies two backends:

- `xero-official`: official Xero MCP tool surface with local OAuth tokens.
- `xero-workflows`: local plugin workflow tools such as
  `xero_prework_create`, `xero_audit_dry_run`, `xero_reference_upsert`,
  `xero_documents_action`, and `xero_reconcile_cdp`.

Use the `xero_backends` MCP tool to inspect backend status and which tool
comes from which backend.

## Optional Reconciliation Companion

The first reconciliation companion scaffold is available at
`connectors/xero/reconciliation/xero-reconcile`.

```bash
connectors/xero/reconciliation/xero-reconcile status
connectors/xero/reconciliation/xero-reconcile inspect --cdp-endpoint ws://127.0.0.1:9222/devtools/browser/<id>
connectors/xero/reconciliation/xero-reconcile capture-lines --cdp-endpoint ws://127.0.0.1:9222/devtools/browser/<id>
connectors/xero/reconciliation/xero-reconcile dry-run --cdp-endpoint ws://127.0.0.1:9222/devtools/browser/<id>
connectors/xero/reconciliation/xero-reconcile apply --cdp-endpoint ws://127.0.0.1:9222/devtools/browser/<id> --plan ./apply-plan.json --confirm-apply
```

It refuses to run without an explicit user-provided CDP endpoint and does not
launch a browser, log in, collect MFA, or store browser session material.
`inspect` reads only the DevTools target list and redacts page URL query strings
before writing output.
`capture-lines` reads visible page text only from an already-open target and
parses statement-line candidates without accessing cookies or browser storage.
`apply` is gated by an explicit JSON plan plus `--confirm-apply`; the current
action language covers row-scoped suggestion/match clicks and multi-step match
dialog actions, but live selector proof against Xero markup is still pending.

Official docs:

- Xero developer docs: <https://developer.xero.com/documentation/>
- Accounting API overview: <https://developer.xero.com/documentation/api/accounting/overview>
- OAuth 2.0 overview: <https://developer.xero.com/documentation/guides/oauth2/overview/>
- OAuth standard auth flow: <https://developer.xero.com/documentation/guides/oauth2/auth-flow/>
- OAuth PKCE flow: <https://developer.xero.com/documentation/guides/oauth2/pkce-flow/>
- OAuth 2.0 FAQ: <https://developer.xero.com/faq/oauth2>
- Bank feeds API overview: <https://developer.xero.com/documentation/api/bankfeeds/overview>
- Limits FAQ: <https://developer.xero.com/faq/limits>
- Xero AI Toolkit: <https://developer.xero.com/ai>
- Xero Central: <https://central.xero.com/>
- Developer pricing and policy: <https://developer.xero.com/pricing>
