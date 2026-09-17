# Xero API vs CDP Responsibility Map

Last updated: 2026-06-06.

## Rule

Use the Xero API for deterministic accounting objects and reports. Use CDP only
where Xero's public API does not expose the user's intended workflow.

## API-Owned Work

| Area | API/MCP responsibility | Notes |
| --- | --- | --- |
| Contacts | list, get, create, update, group membership reads; `xero reference upsert contact` / `xero_reference_upsert` | Prefer `ContactID` once resolved; contact names may not remain unique. Contact `TaxNumber` is API-owned even if the upstream official MCP `create-contact`/`update-contact` schema omits a tax/ABN field. |
| Accounts | list chart of accounts, create/update where exposed; `xero reference upsert account` | Creation and mutation are full-power operations; dry-run required. |
| Items | list, create, update; `xero reference upsert item` | Use item codes and tax/account metadata for invoice preparation. |
| Tax rates | list | Tax treatment is jurisdiction/project policy, not inferred only from Xero. |
| Tracking | list/create/update categories and options; `xero reference upsert tracking-category`, `xero reference upsert tracking-option` | Options require a `TrackingCategoryID` and use Xero's nested options endpoint. |
| Invoices/bills | create, update, authorize, void/delete where valid; `xero documents create invoice`, `xero documents create bill`, `xero documents update invoice`, `xero documents update bill` | Creating a paid invoice requires invoice authorization plus payment. |
| Quotes | create/list/update draft quotes; `xero documents create quote`, `xero documents update quote` | API coverage exists in official MCP; CLI helper is dry-run-first. |
| Credit notes | create/list/update draft credit notes; `xero documents create credit-note`, `xero documents update credit-note` | Apply through supported Xero flows; payload should specify the intended credit-note type. |
| Payments | create/list payments against invoices/bills/credit notes; `xero prework create payment` | Marks invoices paid when fully applied. |
| Batch payments | create/list/update batch payments; `xero prework create batch-payment` | Useful when several payments should match one statement line. |
| Bank transactions | create/list/update spend/receive money transactions; `xero prework create bank-transaction` | Creates accounting-side bank transactions; does not necessarily clear imported statement lines. |
| Bank transfers | create transfers between bank accounts; `xero prework create bank-transfer` | Useful for transfer reconciliation preparation. |
| Manual journals | create/list/update; `xero prework create manual-journal` | Full-power accounting mutation. |
| Reports | `xero reports get` for profit and loss, balance sheet, trial balance, aged receivables, aged payables | Read-only reporting surface. `reports get profit-and-loss` accepts `--tracking-category-id`/`--tracking-option-id` for tracking-split P&L. |
| P&L by tracking (file export) | `xero reports export-pnl-tracking` / `xero_export_pnl_tracking` | Writes a normalized one-row-per-account/option CSV with a per-segment net reconciliation. Replaces CDP `Compare <category>` report exports. |
| Budgets (Budget Manager, read-only) | `xero budgets list` / `xero budgets get` · `xero_budgets_list` / `xero_budgets_get` | Read-only budget summaries (list: BudgetID/Type/Description/UpdatedDateUTC) and per-account, per-period BudgetLines (get). Xero Budgets API is GET-only — no create/update endpoint. Requires `accounting.budgets.read` (opt in: `auth login --add budgets-read`). |
| Account transactions (file export) | `xero journals export` / `xero_export_account_transactions` | Reconstructs account transactions from the `/Journals` general ledger, signed revenue +/cost −. Requires the `accounting.journals.read` scope, available only on Xero connections created before 29 April 2026 (broad-scope); granular connections (on/after that date) get `invalid_scope`/HTTP 401 and cannot use it. Eligible operators opt in with `auth login --add journals-broad`. Replaces CDP account-transaction drilldowns. |
| Attachments/history | `xero evidence history` and `xero evidence attachments` for allowlisted records | Use for evidence and audit trails. |
| Audit/dedup | targeted live reads and local snapshots | Avoid full sweeps as default because of Xero limits. |

Run `connectors/xero/mcp/xero-mcp-local surface` after preparing the MCP cache
to inventory the official tool names and verify this map. As of the current
`@xeroapi/xero-mcp-server@0.0.17` cache, the official MCP covers contacts,
items, tax rates, accounts, tracking categories, invoices/bills, quotes, credit
notes, payments, bank transactions, manual journals, and core reports. Local
plugin companion tools, exposed by both CLI and the `xero-workflows` MCP
backend, cover batch payments, bank transfers, attachments/history, dedup/audit,
reference snapshots, targeted live checks, and CDP-gated reconciliation helper
workflows.

Contact ABN/GST/VAT/Tax ID entry is a known schema mismatch in the official MCP
tool surface, not a Xero API gap. The Xero Contacts endpoint supports
`TaxNumber`; use `xero_reference_upsert` or `xero reference upsert contact`
with a raw contact payload when the official MCP contact tool does not expose
that field. Browser/CDP is a fallback for visual confirmation or UI-only
settings, not the primary path for contact tax numbers.

## CDP-Owned Work

| Area | CDP responsibility | Why API is not enough |
| --- | --- | --- |
| Reconcile tab statement lines | inspect imported bank statement lines waiting for reconciliation | Public Accounting API exposes accounting transactions, not a general statement-line reconciliation action. |
| Suggested matches | accept a Xero suggestion after policy/API pre-checks | Xero suggestion acceptance is a UI workflow. |
| Match existing transaction | match a statement line to an API-created payment/transaction/transfer | The accounting object can be created by API; clearing the imported statement line may still require UI action. |
| Create-on-reconcile UI paths | perform UI-only create/confirm steps when necessary | Some Reconcile tab flows have no equivalent public endpoint. |
| Rule/settings screens | configure or confirm Xero settings not exposed by API | Keep as optional workflow, not core MCP dependency. |

## Reconciliation Strategy

Prefer this sequence:

1. Use API reads to understand contacts, accounts, invoices, payments, bank
   transactions, and candidate duplicates.
2. Use finance rules to decide the expected accounting-side object.
3. Use API writes to create the object when deterministic.
4. Use CDP dry-run to verify the Xero Reconcile tab offers the expected match.
5. Use CDP apply to accept or match the statement line.
6. Record an audit row linking source evidence, API object IDs, UI action, and
   final status.

This reduces browser automation to final confirmation and statement-line
clearing rather than using the browser as the primary accounting engine.

## Design Implications

- The core MCP must be valuable without CDP.
- Reconciliation installs as an optional plugin extension.
- Reconciliation tools must accept an existing CDP endpoint and must not own
  login, MFA, browser profile, or credential storage.
- Dry-run output is mandatory before applied reconciliation.
- API pre-work must be rate-governed, deduplicated, and dry-run before any UI
  apply step. Current CLI pre-work commands are dry-run by default and require
  `--apply --preflight-report <dry-run-or-audit-report>` for mutation, unless an
  operator deliberately supplies `--confirm-apply-without-preflight`.
- Current prototype: `connectors/xero/reconciliation/xero-reconcile` provides a
  CDP-gated target inspection command plus a dry-run/preflight artifact and
  refuses to run without an explicit endpoint. It can capture visible text from
  an already-open page target, parse statement-line candidates, and match
  expected records against saved visible statement-line text/JSON snapshots. For
  exact reference+amount matches, dry-run reports include review-only suggested
  apply-plan actions. It can also execute an explicit-plan apply command that requires
  `--confirm-apply`, clicks only row-scoped controls for requested
  `accept-suggestion`/`match-existing`/`open-match-dialog` actions, supports
  explicit search/select/confirm match-dialog steps, and writes a redacted audit
  report. Live Xero selector refinement remains required before broad use.

## Non-Goals

- Replicating Xero's bank feed engine.
- Shipping browser login automation in the Xero plugin.
- Bypassing MFA, Cloudflare, or other security controls.
- Treating raw bank statement data from partner-only finance APIs as a general
  public API dependency.
