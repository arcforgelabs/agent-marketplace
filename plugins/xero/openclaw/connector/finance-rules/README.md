# Xero Finance Rules

Generic rule scaffolding for Xero audit and dry-run workflows.

This directory must not contain private customer names, account mappings, tax
decisions, credential names, or tenant exports. Use `xero rules init` to create a
local private copy at `~/.config/arc-forge-tools/xero/finance-rules.json`, then
edit that local file for deployment-specific mappings.

## Commands

```bash
connectors/xero/cli/xero rules init
connectors/xero/cli/xero rules validate
connectors/xero/cli/xero rules parse-name "INV-1001 Example"
connectors/xero/cli/xero rules map contact "Example Customer"
connectors/xero/cli/xero rules upsert-mapping contact --name example-contact --alias "Example Customer" --target-json '{"name":"Example Customer Pty Ltd"}'
connectors/xero/cli/xero audit dry-run --candidates ./candidates.json --max-batch-size 25
connectors/xero/cli/xero audit check-live invoice INV-1001
connectors/xero/cli/xero audit record-apply --event ./apply-event.json
connectors/xero/cli/xero audit list-apply
```

`audit dry-run` reads optional snapshots from
`~/.config/arc-forge-tools/xero/snapshots` by default. Snapshot files may be JSON
arrays or objects with a `records`, `items`, `invoices`, `bills`, `payments`, or
`bank_transactions` array.

Supported snapshot names:

- `invoices.json`
- `bills.json`
- `payments.json`
- `bank_transactions.json`

The dry-run report is intentionally proof-oriented: it lists candidate status,
duplicate matches, resolved mappings, missing mappings, and targeted live checks
an operator or MCP tool should run before mutation. Missing mapping findings also
produce review-only `mapping_suggestions` with `rules upsert-mapping` command
templates. These suggestions never mutate the private rules file by themselves;
they are starting points for a reviewed account, contact, item, or tax decision.
Duplicate results include a `duplicate_match_count` and `duplicate_ambiguous`
flag so a single exact match and multiple exact matches are distinguishable.
Near misses do not block; encode broader matching policy in private review rules
or run targeted live checks before mutation.

Ready candidates also produce a `batch_plan`. The plan groups candidates by
object type, splits them into bounded chunks, estimates apply API call count,
and records that each batch still requires the dry-run/audit report as preflight
evidence. Use `--max-batch-size` to lower the bound for conservative runs.

The template also includes a generic `conventions` block. It is not a private
bookkeeping policy; it gives local installs a place to encode reusable review
rules such as draft-first document defaults, missing-reference review,
negative-total review, evidence expectations, and API-prework-before-CDP
reconciliation. `audit dry-run` applies the supported review rules and reports
the reason each candidate needs review.

Use `rules upsert-mapping` after an operator review to persist a reusable
account, contact, item, or tax mapping. It merges aliases/patterns into the
matching named rule, validates the full private rules file, and writes it with
user-only file permissions.

`audit check-live` runs one targeted read-only Xero API query by reference, name,
or code. It is intended for write-grade verification after a dry-run report, not
for broad catalog or invoice sweeps.

`audit record-apply` stores a redacted local report for mutation results and
appends a compact ledger entry. It accepts created, updated, skipped, and failed
events from future write flows.
