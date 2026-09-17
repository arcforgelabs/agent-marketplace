# Xero Workflow Playbooks

These playbooks describe connector behavior. They do not provide accounting,
tax, or legal advice.

For current browser-specific invoice behavior, tenant guards, copy-to-draft,
autosave cleanup, stable DOM hooks, and end-state verification, see
[Invoice browser workflows](invoice-browser-workflows.md).

## First-Time Setup

```bash
connectors/xero/mcp/xero-mcp-local prepare
connectors/xero/cli/xero auth configure-app --client-id <public-client-id>
connectors/xero/cli/xero auth app-config
connectors/xero/cli/xero auth login
connectors/xero/cli/xero tenants list --refresh
connectors/xero/cli/xero tenants use <tenant-id>
connectors/xero/cli/xero smoke organisation
connectors/xero/cli/xero smoke accounts
connectors/xero/cli/xero-smoke --live-api
```

If the public client ID is already packaged, skip `auth configure-app`. If it is
not packaged, either run that command, set `ARC_FORGE_XERO_CLIENT_ID`, or run
`plugins/xero/scripts/install-xero-plugin --target <target> --client-id <id>`.

## Reference Snapshot Refresh

Use snapshots for stable reference data instead of repeated live reads.

```bash
connectors/xero/cli/xero lock acquire --holder snapshot-refresh --wait
connectors/xero/cli/xero snapshots fetch accounts
connectors/xero/cli/xero snapshots fetch tax-rates
connectors/xero/cli/xero snapshots fetch items
connectors/xero/cli/xero snapshots fetch contacts
connectors/xero/cli/xero snapshots fetch tracking-categories
connectors/xero/cli/xero lock release <lease-id>
```

## Read-Only Reports

Use `reports get` for read-only report checks before exporting or comparing
financial state:

```bash
connectors/xero/cli/xero reports get profit-and-loss --from-date 2026-01-01 --to-date 2026-01-31
connectors/xero/cli/xero reports get balance-sheet --date 2026-01-31
connectors/xero/cli/xero reports get trial-balance --date 2026-01-31
connectors/xero/cli/xero reports get aged-receivables --date 2026-01-31
connectors/xero/cli/xero reports get aged-payables --date 2026-01-31
```

## Evidence and History

Use the evidence helpers to read audit history, add a note, or attach supporting
files to Xero records after the accounting object exists:

```bash
connectors/xero/cli/xero evidence history get invoice <invoice-id>
connectors/xero/cli/xero evidence history add-note invoice <invoice-id> --details "Reviewed source evidence"
connectors/xero/cli/xero evidence attachments list invoice <invoice-id>
connectors/xero/cli/xero evidence attachments upload invoice <invoice-id> --file ./receipt.pdf
connectors/xero/cli/xero evidence attachments download invoice <invoice-id> receipt.pdf --out ./receipt.pdf
```

## Candidate Write Audit

Before any write flow:

```bash
connectors/xero/cli/xero rules validate
connectors/xero/cli/xero audit dry-run --candidates ./candidates.json --max-batch-size 25 --out ./dry-run.json
```

When review confirms a missing mapping, persist the decision before repeating
the dry-run. The dry-run report includes review-only `mapping_suggestions` with
command templates; replace the target placeholder with the reviewed Xero account,
contact, item, or tax value before running one:

```bash
connectors/xero/cli/xero rules upsert-mapping contact --name example-contact --alias "Example Customer" --target-json '{"name":"Example Customer Pty Ltd"}'
```

For each ready candidate, run targeted live checks rather than broad sweeps:

```bash
connectors/xero/cli/xero audit check-live invoice INV-1001
connectors/xero/cli/xero audit check-live contact "Example Customer"
connectors/xero/cli/xero audit check-live item ITEM-CODE
```

Only then should API pre-work create payments, journals, bank transactions, or
transfers. The command is dry-run by default and writes an apply report when
`--apply` is used:

Before any invoice write, confirm that the selected API profile/tenant is the
intended legal entity. An authenticated Xero browser tab may be open to a
different organisation than the local token.

For larger candidate files, use the dry-run report's `batch_plan` to apply
bounded chunks by object type. The plan estimates apply API calls and records
candidate indexes for each batch; do not dispatch an unbounded candidate list.

```bash
connectors/xero/cli/xero documents create invoice --payload ./invoice.json --out ./invoice-dry-run.json
connectors/xero/cli/xero documents create invoice --payload ./invoice.json --apply --preflight-report ./invoice-dry-run.json
connectors/xero/cli/xero documents create bill --payload ./bill.json --out ./bill-dry-run.json
connectors/xero/cli/xero documents create bill --payload ./bill.json --apply --preflight-report ./bill-dry-run.json
connectors/xero/cli/xero documents create quote --payload ./quote.json --out ./quote-dry-run.json
connectors/xero/cli/xero documents create quote --payload ./quote.json --apply --preflight-report ./quote-dry-run.json
connectors/xero/cli/xero documents create credit-note --payload ./credit-note.json --out ./credit-note-dry-run.json
connectors/xero/cli/xero documents create credit-note --payload ./credit-note.json --apply --preflight-report ./credit-note-dry-run.json
connectors/xero/cli/xero documents update invoice --identifier INV-123 --status AUTHORISED --out ./invoice-authorise-dry-run.json
connectors/xero/cli/xero documents update invoice --identifier INV-123 --status AUTHORISED --apply --preflight-report ./invoice-authorise-dry-run.json
connectors/xero/cli/xero documents update invoice --identifier INV-123 --status VOIDED --out ./invoice-void-dry-run.json
connectors/xero/cli/xero documents update invoice --identifier INV-123 --status VOIDED --apply --preflight-report ./invoice-void-dry-run.json
connectors/xero/cli/xero documents update quote --identifier <quote-id> --status SENT --out ./quote-sent-dry-run.json
connectors/xero/cli/xero documents update quote --identifier <quote-id> --status SENT --apply --preflight-report ./quote-sent-dry-run.json
connectors/xero/cli/xero reference upsert contact --payload ./contact.json --out ./contact-dry-run.json
connectors/xero/cli/xero reference upsert contact --payload ./contact.json --apply --preflight-report ./contact-dry-run.json
connectors/xero/cli/xero reference upsert item --payload ./item.json --out ./item-dry-run.json
connectors/xero/cli/xero reference upsert item --payload ./item.json --apply --preflight-report ./item-dry-run.json
connectors/xero/cli/xero reference upsert account --payload ./account.json --method PUT --out ./account-dry-run.json
connectors/xero/cli/xero reference upsert account --payload ./account.json --method PUT --apply --preflight-report ./account-dry-run.json
connectors/xero/cli/xero reference upsert tracking-category --payload ./tracking-category.json --out ./tracking-category-dry-run.json
connectors/xero/cli/xero reference upsert tracking-category --payload ./tracking-category.json --apply --preflight-report ./tracking-category-dry-run.json
connectors/xero/cli/xero reference upsert tracking-option --payload ./tracking-option.json --out ./tracking-option-dry-run.json
connectors/xero/cli/xero reference upsert tracking-option --payload ./tracking-option.json --apply --preflight-report ./tracking-option-dry-run.json
connectors/xero/cli/xero prework create payment --payload ./payment.json --out ./payment-prework.json
connectors/xero/cli/xero prework create payment --payload ./payment.json --apply --preflight-report ./payment-prework.json
connectors/xero/cli/xero prework create batch-payment --payload ./batch-payment.json --out ./batch-payment-prework.json
connectors/xero/cli/xero prework create batch-payment --payload ./batch-payment.json --apply --preflight-report ./batch-payment-prework.json
connectors/xero/cli/xero prework create bank-transaction --payload ./bank-transaction.json --out ./bank-transaction-prework.json
connectors/xero/cli/xero prework create bank-transaction --payload ./bank-transaction.json --apply --preflight-report ./bank-transaction-prework.json
connectors/xero/cli/xero prework create bank-transfer --payload ./bank-transfer.json --out ./bank-transfer-prework.json
connectors/xero/cli/xero prework create bank-transfer --payload ./bank-transfer.json --apply --preflight-report ./bank-transfer-prework.json
connectors/xero/cli/xero prework create manual-journal --payload ./manual-journal.json --out ./manual-journal-prework.json
connectors/xero/cli/xero prework create manual-journal --payload ./manual-journal.json --apply --preflight-report ./manual-journal-prework.json
```

`documents create` accepts Xero-shaped payloads for invoices, bills, quotes, and
credit notes. It is dry-run by default. Sales invoices default to `ACCREC` and
bills default to `ACCPAY` when the payload does not already specify `Type`;
credit notes should specify the intended Xero credit-note type in the payload.
`documents update` is also dry-run by default. Use it for explicit lifecycle
updates or a supplied Xero-shaped update payload; it does not infer whether a
document should be approved, voided, deleted, sent, accepted, or declined.
`reference upsert` is the explicit write path for master data that supports
later document and reconciliation flows. Run targeted live checks and snapshot
refreshes before introducing new contacts, items, accounts, tracking
categories, or tracking options. Tracking-option payloads must include a
single `TrackingCategoryID`; the helper posts the options to Xero's nested
`TrackingCategories/{TrackingCategoryID}/Options` endpoint.
`prework create batch-payment` uses the Xero BatchPayments endpoint and is useful
when several API-created payments should correspond to one bank statement line.
All apply-capable write helpers require `--preflight-report` by default. Use a
matching dry-run report for the same command/payload, or a clean
`audit dry-run` report with ready candidates. `--confirm-apply-without-preflight`
is an explicit operator override for exceptional cases and is recorded in the
command output.

## Apply Report Recording

Future write flows should record every created, updated, skipped, or failed
outcome:

```bash
connectors/xero/cli/xero audit record-apply --event ./apply-event.json
connectors/xero/cli/xero audit list-apply
```

The event format is intentionally generic:

```json
{
  "type": "invoice",
  "action": "create_draft",
  "status": "created",
  "reference": "INV-1001",
  "xero_id": "00000000-0000-0000-0000-000000000000",
  "source_id": "source-row-1",
  "details": {
    "message": "Draft invoice created"
  }
}
```

## Reconciliation Boundary

API pre-work should create or locate the accounting records needed for
reconciliation. Browser/CDP work is limited to the remaining Reconcile-tab UI
gap:

- Read imported bank statement lines.
- Accept Xero suggested matches when they match expected records.
- Match statement lines to API-created transactions.
- Confirm UI-only reconciliation actions.

The connector must not automate login, MFA, or security-control bypass.

Current companion scaffold:

```bash
connectors/xero/reconciliation/xero-reconcile status
connectors/xero/reconciliation/xero-reconcile inspect \
  --cdp-endpoint ws://127.0.0.1:9222/devtools/browser/<id>
connectors/xero/reconciliation/xero-reconcile capture-lines \
  --cdp-endpoint ws://127.0.0.1:9222/devtools/browser/<id> \
  --out ./visible-lines.json
connectors/xero/reconciliation/xero-reconcile dry-run \
  --cdp-endpoint ws://127.0.0.1:9222/devtools/browser/<id> \
  --expected ./expected-reconciliation.json \
  --statement-lines ./visible-lines.json
connectors/xero/reconciliation/xero-reconcile apply \
  --cdp-endpoint ws://127.0.0.1:9222/devtools/browser/<id> \
  --target-id <target-id> \
  --plan ./apply-plan.json \
  --confirm-apply
```

The current inspection step reads only the DevTools target list and redacts
browser URL query strings. `capture-lines` reads visible text only from the
already-open page target and parses statement-line candidates. The dry-run can
match expected API-created records against that saved JSON snapshot. For exact
reference+amount matches, the dry-run report includes a review-only
`suggested_apply_plan` that can be saved as the explicit apply plan after human
review. Apply is explicit-plan only and writes a redacted audit report.

For a single artifact covering local readiness, live API smoke, and optional CDP
capture:

```bash
connectors/xero/cli/xero-smoke \
  --live-api \
  --cdp-endpoint ws://127.0.0.1:9222/devtools/browser/<id> \
  --expected ./expected-reconciliation.json
```
