# Xero Plugin Implementation Plan

Last updated: 2026-06-06.

## Phase 1: `xero-core`

Goal: local install works with only a user's Xero account.

Deliverables:

- `[prototype]` CLI command: `xero auth login`.
- `[prototype]` Local OAuth Code + PKCE flow with localhost callback.
- `[prototype]` Local token store with refresh-token rotation plumbing.
- `[prototype]` Tenant discovery and active-tenant selection.
- `[prototype]` CLI command: `xero auth status`.
- `[prototype]` CLI command: `xero auth migrate-store`.
- `[prototype]` CLI command: `xero auth token` for trusted local MCP wrapper
  processes.
- `[prototype]` CLI command: `xero tenants list` and `xero tenants use`.
- `[prototype]` Read-only smoke command using Organisation.
- `[prototype]` Read-only smoke command using Accounts.
- `[prototype]` Encrypted-at-rest token file with local key-file backend and
  plaintext migration.
- `[planned]` OS keychain or hardware-backed token key backend.

Validation:

- Offline tests prove `xero auth login` builds the PKCE authorize request,
  captures the localhost callback result, exchanges the code, stores returned
  tokens, fetches connected tenants, and selects the first tenant.
- Auth flow succeeds against a demo or test tenant.
- Refresh can be forced and persists the rotated token.
- `xero auth token` refreshes expired access tokens for the MCP wrapper,
  persists rotated refresh tokens, and writes the pre-rotation backup.
- Token values never appear in logs.
- Token store reports `token_store_encrypted: true` when encryption support is
  available.
- Tenant selector survives process restart.

Current implementation:

- CLI wrapper: `connectors/xero/cli/xero`.
- Core module: `connectors/xero/scripts/xero_core.py`.
- Tests: `connectors/xero/tests/test_xero_core.py`.

## Phase 2: `xero-mcp`

Goal: official Xero MCP API surface runs through the local token provider.

Deliverables:

- `[prototype]` Runtime patcher/launcher for `@xeroapi/xero-mcp-server`.
- `[prototype]` Replace custom-connection-only startup with local token provider support.
- `[prototype]` Preserve official tool definitions and handlers by patching
  only `dist/clients/xero-client.js`.
- `[prototype]` Add package entrypoint for Codex/Claude Desktop/Cursor MCP configs.
- `[prototype]` Add `xero-mcp-local status` no-network diagnostic tool.
- `[prototype]` Add `xero-mcp-local surface` package inventory and API category
  coverage check.
- `[prototype]` Add `xero-mcp-local protocol-smoke` stdio initialize/tools-list
  check without invoking Xero API tools.
- `[prototype]` Add `xero-workflows-mcp` companion server for local
  dry-run/audit/pre-work/reference/CDP workflow tools that are intentionally
  outside the official package.
- `[planned]` Decide whether to keep runtime patching or maintain a source fork
  once upstream auth extension points are clearer.

Validation:

- MCP starts with no `XERO_CLIENT_ID`/`XERO_CLIENT_SECRET` supplied by the user.
- Read tools work against selected tenant.
- Full official tool list remains available for MVP.
- Surface inventory reports no missing required categories across official MCP
  tools plus local CLI companion helpers.
- Protocol smoke starts the patched MCP server and lists expected official tools
  before live OAuth/API validation.
- Print-config and plugin `.mcp.json` tests prove MCP server commands resolve to
  repo-local wrappers and runtime env does not require Xero developer
  credentials or pre-supplied bearer tokens.
- Companion MCP self-test lists local workflow tools and can run dry-run helper
  calls without Xero auth.
- Errors are sanitized and do not stringify request headers or bearer tokens.

Current implementation:

- Launcher: `connectors/xero/mcp/xero-mcp-local`.
- Patcher: `connectors/xero/scripts/xero_mcp_local.py`.
- Local token bridge: `connectors/xero/cli/xero auth token`.
- Surface inventory: `connectors/xero/mcp/xero-mcp-local surface`.
- Protocol smoke: `connectors/xero/mcp/xero-mcp-local protocol-smoke --strict`.
- Companion workflow MCP: `connectors/xero/mcp/xero-workflows-mcp`.

## Phase 3: `xero-governor`

Goal: prevent predictable Xero limit exhaustion.

Deliverables:

- `[prototype]` In-process pre-dispatch governor injected into the official MCP
  client wrapper.
- `[prototype]` Conservative concurrency, rolling minute, daily, and app-wide
  budgets with environment overrides.
- `[prototype]` CLI status output: `xero rate status`.
- `[prototype]` JSON-backed FIFO lease lock: `xero lock acquire`,
  `xero lock release`, and `xero lock status`.
- `[prototype]` Response-header observation for safe Xero limit headers.
- `[prototype]` Bounded one-shot Retry-After handling for HTTP 429 responses.
- `[prototype]` DayLimit circuit breaker with explicit
  `xero rate unblock-day-limit` workflow.
- `[prototype]` Cross-process MCP/CLI shared budget file for tenant minute,
  tenant daily, and app-wide minute accounting across multiple local processes.

Validation:

- `[prototype]` Patch tests assert the official MCP client receives the
  governor wrapper and existing local-token-only or older-governor caches are
  upgraded.
- `[prototype]` CLI tests assert missing and existing governor snapshots render.
- `[prototype]` CLI tests assert day-limit unblock writes an explicit
  0600 local override file.
- `[prototype]` CLI tests assert operation-lock acquire, queue, release, status,
  and expired-lease cleanup.
- `[prototype]` CLI governor tests assert non-Accounting API calls do not
  consume budget, tenant minute exhaustion blocks before dispatch, app-wide
  minute exhaustion blocks before dispatch, Xero DayLimit pressure opens the
  local circuit, and included CLI status is redacted.
- `[prototype]` Unit tests prove the shared MCP/CLI budget blocks tenant minute
  and app-wide minute exhaustion before dispatch.
- `[planned]` Unit tests for deeper SDK queue behavior and runtime Retry-After
  delay calculation.
- `[planned]` Manual smoke shows remaining-limit headers are recorded when
  present.
- `[prototype]` Large batch dry-run emits bounded `batch_plan` chunks and
  estimated apply API call counts instead of allowing unbounded candidate lists.

## Phase 4: `xero-audit`

Goal: extract Lab Flow's useful audit and dedup patterns into generic helpers.

Deliverables:

- `[prototype]` Rule file format for source-to-Xero mappings.
- `[prototype]` Generic bookkeeping convention template for draft-first document
  defaults, evidence expectations, API-prework-before-CDP reconciliation, and
  review rules that can be extended in private local rules.
- `[prototype]` Reference/contact/item parser and mapping CLI helpers.
- `[prototype]` Snapshot-backed dedup checks for invoice, bill, payment, and
  bank transaction candidates.
- `[prototype]` Dry-run report format with duplicate matches, resolved
  mappings, missing mappings, review-only mapping suggestions, and
  targeted-check hints.
- `[prototype]` Local snapshot fetch/list commands for stable reference data:
  accounts, tax rates, items, contacts, and tracking categories.
- `[prototype]` Dry-run-first reference/master-data upserts for contacts, items,
  accounts, tracking categories, and tracking options:
  `xero reference upsert`.
- `[prototype]` Targeted live-reference reads for write-grade verification:
  `xero audit check-live`.
- `[prototype]` Read-only report helpers for profit and loss, balance sheet,
  trial balance, aged receivables, and aged payables: `xero reports get`.
- `[prototype]` Evidence helpers for allowlisted Xero object history notes and
  attachments: `xero evidence history` and `xero evidence attachments`.
- `[prototype]` Guarded API pre-work creates for payments, bank transactions,
  batch payments, bank transfers, bank transactions, and manual journals:
  `xero prework create`.
- `[prototype]` Apply report format and local append-only ledger:
  `xero audit record-apply` and `xero audit list-apply`.
- `[prototype]` Dry-run-first write helpers for invoices, bills, quotes, and
  credit notes: `xero documents create`.
- `[prototype]` Dry-run-first update/status helpers for invoices, bills, quotes,
  and credit notes: `xero documents update`.
- `[prototype]` Dry-run-first sales-invoice action helpers for online invoice
  URL retrieval and triggering Xero invoice email: `xero documents action
  invoice`.
- `[prototype]` Apply-capable document, reference, and API pre-work helpers
  require `--preflight-report` from a matching dry-run/audit report by default,
  with an explicit `--confirm-apply-without-preflight` operator override.
- `[planned]` Broader typed helpers for other specialized document actions.

Validation:

- `[prototype]` Fixture tests cover naming parser, mapping resolution, duplicate
  block, missing-mapping review output, review-only mapping suggestions, and
  snapshot listing.
- `[prototype]` Fixture tests cover convention-driven dry-run review for
  non-draft document status, missing reference, and negative total.
- `[prototype]` Dedup tests cover ambiguous exact matches and non-exact
  near-misses that should not block.
- `[prototype]` Tests prove targeted live-check query construction without broad
  sweep filters.
- `[prototype]` Tests prove reference upsert dry-run wrapping and apply
  endpoint/ledger behavior without live network access, including nested
  tracking-option endpoints.
- `[prototype]` Tests prove report endpoint/query construction without live
  network access.
- `[prototype]` Tests prove evidence history-note and attachment-upload endpoint
  construction without live network access.
- `[prototype]` Tests prove API pre-work dry-run and apply endpoint/ledger
  behavior without live network access, including batch payments.
- `[prototype]` Tests prove document create dry-run defaults and bill apply
  endpoint/ledger behavior without live network access.
- `[prototype]` Tests prove document status update dry-run and quote update
  endpoint/ledger behavior without live network access.
- `[prototype]` Tests prove invoice online-url and email action endpoints,
  empty email POST behavior, and apply ledger reporting without live network
  access.
- `[prototype]` Tests prove bare apply is rejected without preflight evidence,
  and matching dry-run preflight reports allow apply without live network access.
- `[prototype]` Tests prove apply reports redact secret-like fields and list
  ledger summaries.
- `[planned]` Live targeted-check smoke tests against an authenticated tenant
  prove no full invoice sweep is needed before draft writes.
- Dry-run report can explain each proposed write without touching Xero.

## Phase 5: `xero-reconciliation`

Goal: keep browser automation limited to Reconcile tab gaps.

Deliverables:

- `[prototype]` CDP-gated companion CLI that accepts only an explicit already
  authenticated browser endpoint.
- `[prototype]` Dry-run/preflight report shape for expected API-created objects.
- `[prototype]` Inspect the supplied CDP endpoint's target list and identify
  Xero/Reconcile candidate tabs without reading page storage or DOM.
- `[prototype]` Capture visible text from an already-open page target and parse
  statement-line candidates without clicking or reading cookies/storage.
- `[prototype]` Parse saved visible statement-line text/JSON snapshots and match
  them against expected API-created records in dry-run reports.
- `[prototype]` Generate review-only suggested apply plans for exact
  reference+amount matches; apply still requires an explicit plan and
  `--confirm-apply`.
- `[prototype]` Discover pending bank-account Reconcile tab line candidates
  from visible text.
- `[prototype]` Explicit-plan apply command for row-scoped
  `accept-suggestion`/`match-existing`/`open-match-dialog` clicks, gated by
  `--confirm-apply`.
- `[prototype]` Multi-step match action language for transaction search,
  selection, and confirmation when a row-local button is not enough.
- `[planned]` Refine selectors against live Xero markup for higher-quality row
  segmentation.
- `[planned]` Live proof of the multi-step match action language against Xero
  Reconcile-tab markup.
- `[prototype]` Installation/boundary docs for Claude Desktop/Codex/Cursor local
  browser use.

Validation:

- `[prototype]` Script refuses to run without explicit CDP endpoint.
- `[prototype]` Script does not request or store login credentials.
- `[prototype]` Dry-run/preflight report redacts CDP query strings and records
  expected matches without connecting.
- `[prototype]` Inspection tests prove CDP target URLs and debugger URLs are
  redacted and no session query strings are written.
- `[prototype]` Dry-run can match expected records against saved statement-line
  snapshots.
- `[prototype]` Capture command can enumerate pending live DOM statement-line
  candidates from visible text without browser storage/cookie access.
- `[prototype]` Apply command requires explicit endpoint, explicit action plan,
  `--confirm-apply`, and writes a redacted audit report.
- `[planned]` Apply can reconcile a controlled known match in a test/demo tenant.

## Phase 6: `xero-plugin`

Goal: package the core and optional reconciliation companion for local agents.

Deliverables:

- `[prototype]` Codex plugin manifest and skill docs.
- `[prototype]` MCP config templates via `xero-mcp-local print-config` for
  generic JSON, Claude Desktop, Cursor, and Codex.
- `[prototype]` Plugin install script via `plugins/xero/scripts/install-xero-plugin`.
- `[prototype]` Docs for OAuth/MFA/user login, Xero scopes, rate limits,
  workflow playbooks, and install/MCP config.
- `[prototype]` Docs for safe local CDP usage in the reconciliation extension.
- `[prototype]` Migration notes from existing Python MCP source.

Validation:

- Fresh install can authenticate and run read-only smoke.
- `[prototype]` No-network validation proves all supported harness config
  snippets resolve to repo-local wrapper commands without developer credentials.
- `[planned]` MCP works in at least one live target harness after user OAuth.
- Optional reconciliation dependency can be installed separately.
- `[prototype]` Docs clearly separate API core from CDP finalizer.

## First Code Slice

The first implementation slice should be small but end-to-end:

1. `[done]` Add `connectors/xero/cli/xero` with `auth login`, `auth status`, and
   `tenants list`.
2. `[done]` Add a local token-store abstraction with file backend and redaction tests.
3. `[done]` Add a local MCP bridge that can return a valid bearer token and
   selected tenant ID.
4. `[done]` Patch or wrap official MCP startup to use that wrapper.
5. `[done]` Add a read-only `xero smoke organisation` command.
6. `[done]` Add a read-only `xero smoke accounts` command.

This proves the defining MVP requirement: users install the tool, sign in with
Xero, and run the MCP without their own developer credentials.
