# Xero Plugin Architecture

Last updated: 2026-06-06.

## Intent

Build a reusable Xero plugin that gives an installed local agent a full-power
Xero MCP/CLI surface without requiring each user to create a Xero developer app.
The core plugin uses Xero's public API for deterministic accounting operations.
Browser/CDP automation is reserved for Xero UI workflows that the public API
does not expose, especially final bank-statement-line reconciliation.

## Product Shape

The plugin has two layers:

- `xero-core`: the default installable MCP/CLI, backed by an Arc Forge-owned
  Xero OAuth app and local user authorization.
- `xero-reconciliation`: an optional companion that connects to a
  user-provided, already authenticated browser/CDP session to finish UI-only
  reconciliation work.

This is not a multi-tenant SaaS. Each installation runs locally for the current
operator and stores only that operator's Xero token state on their own machine.
Other users can install the same plugin and authorize their own Xero account.

## Target Layout

```text
xero-plugin/
  core/
    oauth-pkce/
    token-store/
    tenant-selection/
    rate-governor/
    official-mcp-wrapper/
    cli/

  finance-rules/
    parsers/
    dedup/
    mappings/
    audits/
    dry-runs/

  reconciliation/
    api-prework/
    cdp-finalizer/
    workflows/

  docs/
    auth.md
    limits.md
    bookkeeping-conventions.md
    reconciliation.md
    workflow-playbooks.md
```

In this repo, the first implementation should land as:

- `connectors/xero/docs/`: architecture and workflow contracts.
- `connectors/xero/src/` or `components/mcp/xero-official-wrapper/`: reusable
  TypeScript implementation around Xero's official MCP server.
- `connectors/xero/cli/`: auth, token, tenant, smoke, and diagnostic commands.
- `connectors/xero/reconciliation/`: CDP finalizer scripts and docs.
- `components/skills/xero/`: generic skill guidance that points at these
  tools without embedding private bookkeeping defaults.

## Core MVP Flow

The core MVP must not require users to bring developer credentials.

1. Arc Forge registers and owns a Xero OAuth app.
2. User installs the plugin.
3. User runs `xero auth login`.
4. The CLI starts a local callback listener and opens Xero's consent URL.
5. User logs into Xero, completes MFA through Xero, and selects a tenant.
6. Xero redirects to the local callback with an authorization code.
7. The CLI exchanges the code with PKCE and requests `offline_access`.
8. The CLI stores the refresh token locally and records connected tenants.
9. The MCP refreshes access tokens automatically and rotates refresh tokens on
   every successful refresh.
10. The MCP uses the selected tenant ID on every Xero API request.

The official `@xeroapi/xero-mcp-server` is still the API foundation, but raw
official MCP is not enough for this flow because it currently expects a Custom
Connection client ID/secret or a pre-supplied bearer token. A bearer token is
short lived, so the plugin needs a local token provider or a fork/wrapper of the
official client.

## Authentication Boundary

Use Xero OAuth Code + PKCE for installed local users. Do not ship a client
secret in the local package. Request `offline_access` so the local token store
can refresh without requiring login every 30 minutes.

Token storage requirements:

- Store access tokens only as cache state.
- Store refresh tokens encrypted or through the host OS keychain where
  available.
- Persist every rotated refresh token before returning success from a refresh.
- Never print access tokens, refresh tokens, authorization headers, cookies,
  MFA codes, or browser session data.
- Support multiple tenants and an explicit active-tenant selector.
- For several dedicated businesses, isolate each into its own token store via
  the profile registry rather than sharing one active-tenant pointer. See
  [`multi-business.md`](multi-business.md).

Custom Connections remain useful for local development and advanced operators,
but they are not the default product path because they require developer
credentials and a Xero Custom Connection subscription.

## API Layer

The API/MCP layer owns deterministic work:

- Contacts, items, tax rates, accounts, tracking categories and options.
- Invoices, bills, quotes, credit notes.
- Payments and batch payments.
- Bank transactions and bank transfers.
- Manual journals.
- Reports: profit and loss, balance sheet, trial balance, aged receivables, and
  aged payables.
- Attachments and history where supported.
- Deduplication and audit checks before writes.
- Local snapshots for stable reference data.
- Targeted live checks before mutation.

The first wrapper should expose the official MCP's full tool surface for MVP
power, then add governor and audit tooling around it. Permission pruning is not
part of the MVP, but capability boundaries must still be documented because Xero
scopes and accounting side effects are real.

Official MCP write tools remain visible for full-power compatibility. They are
rate-governed by the wrapper, but they do not enforce local finance-rule
preflight by themselves. `xero-mcp-local surface` therefore emits a
`mutation_safety` inventory that lists official mutating tools and points agents
to local `xero-workflows`/CLI alternatives that require dry-run or audit
preflight reports.

## Finance Rules Layer

Finance rules are reusable but should not hard-code one business's private
bookkeeping into the generic connector. The layer should provide:

- `[prototype]` Rule file format for naming conventions and mappings.
- `[prototype]` Generic bookkeeping convention template for draft-first
  document defaults, evidence expectations, reconciliation guardrails, and
  review-required rules without shipping private account/tax policy.
- `[prototype]` Parsers for source-system names into structured fields.
- `[prototype]` Exact alias and regex mapping helpers with reasons.
- `[prototype]` Snapshot-backed dedup checks for invoices, bills, payments, bank
  transactions, and references.
- `[prototype]` Read-only local snapshots for stable reference data: accounts,
  tax rates, items, contacts, and tracking categories.
- `[prototype]` Preflight-enforced reference upsert helpers cover contacts,
  items, accounts, tracking categories, and tracking options.
- `[prototype]` Dry-run output that explains proposed write readiness, duplicate
  blocks, missing mappings, review-only mapping suggestions, convention review
  issues, and targeted live checks.
- `[prototype]` Targeted live-reference checks by reference, name, or code before
  mutation.
- `[prototype]` Redacted apply-report ledger for created/updated/skipped/failed
  outcomes.
- `[planned]` Fuzzy matching helpers with explicit confidence thresholds.
- `[planned]` Live write flows that emit audit logs automatically.

Lab Flow is the source of the first lessons:

- Pre-dispatch Xero rate governor.
- Per-tenant minute/day/concurrency accounting.
- App-wide minute accounting.
- `[prototype]` Heavy-operation FIFO lock.
- Targeted reference reads instead of full invoice sweeps.
- Draft/audit-before-write patterns.
- Naming convention parsers.
- Persistent mapping rules that improve over time.
- Batch dry-run and proof reports.

## Reconciliation Layer

The public API can create the accounting-side records that make books correct.
It cannot reliably clear all imported bank statement lines from Xero's Reconcile
tab. The reconciliation companion therefore does the smallest possible UI work:

- Inspect imported statement lines in the Reconcile tab.
- Accept Xero suggestions when they match expected API-created records.
- Match statement lines to existing transactions/payments/transfers.
- Create or confirm UI-only reconciliation actions when there is no API
  equivalent.
- Produce an audit report showing what was matched, accepted, skipped, or
  escalated.

The Xero plugin must not package login automation, MFA retrieval, credential
entry, or Cloudflare/security-control bypass behavior. It may connect to a
browser/CDP endpoint that the user has already opened and authenticated.

## Rate Limit Requirements

The core client must enforce Xero limits before dispatch. The current prototype
injects this into the patched official MCP client as an SDK proxy plus shared
JSON budget store:

- `[prototype]` Per-tenant concurrency cap with headroom.
- `[prototype]` Per-tenant rolling minute cap with headroom.
- `[prototype]` Per-tenant daily budget with headroom.
- `[prototype]` App-wide rolling minute budget.
- `[prototype]` Cross-process shared JSON accounting for tenant minute, tenant
  day, and app-wide minute budgets.
- `[prototype]` Operator-visible status command: `xero rate status`.
- `[prototype]` Heavy-operation FIFO lease commands: `xero lock acquire`,
  `xero lock release`, and `xero lock status`.
- `[prototype]` Observation of safe Xero remaining-limit response headers.
- `[prototype]` Bounded one-shot Retry-After handling for 429 responses.
- `[prototype]` DayLimit circuit breaker with explicit unblock file workflow.
- `[planned]` Live tenant smoke for header observation and retry behavior.

Lab Flow's governor is the implementation precedent. The plugin should port the
behavior, not the project-specific invoice lane.

## Installation Surfaces

The plugin should support:

- Codex plugin package.
- Claude Desktop MCP config.
- Cursor MCP config.
- CLI-only use for auth, smoke tests, exports, and dry-runs.

The core install should not require a browser automation dependency. CDP
reconciliation dependencies are optional and installed only with the
reconciliation companion.

## Completion Criteria

The core MVP is complete when:

- A user can install the plugin without developer credentials.
- `xero auth login` completes Xero OAuth via browser and local callback.
- The token store refreshes and rotates tokens correctly.
- A selected tenant can be listed and switched.
- The MCP starts and uses fresh tokens automatically.
- The official Xero MCP API surface is available through the wrapper/fork.
- Rate-limit status is visible and pre-dispatch throttling is active.
- Read-only smoke tests pass against a connected tenant.

The reconciliation companion is complete when:

- It can attach to a user-provided logged-in browser/CDP session.
- It can enumerate pending Reconcile tab statement lines.
- It can match or accept a known API-created transaction.
- It records a dry-run and applied audit report.
- It never stores or automates login credentials.
