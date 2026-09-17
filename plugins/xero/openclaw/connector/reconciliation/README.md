# Xero Reconciliation Companion

Optional CDP companion for final Xero Reconcile-tab workflows.

This is not part of the core MCP path. The core plugin remains API-first and
works without browser automation.

## Boundary

The companion must not:

- Launch a browser for login.
- Enter Xero credentials.
- Retrieve or generate MFA codes.
- Bypass Cloudflare or any security control.
- Store browser cookies, profiles, or credentials.

It may only use a CDP endpoint for a browser session the user has already opened
and authenticated.

## Optional Dependency

The core Xero MCP/CLI install does not require browser automation dependencies.
Live CDP capture needs the Python `websockets` package. Live apply uses the
Node Playwright engine in `apply-engine/xero-reconcile-apply.js`, because Xero's
classic BankRec widgets only commit account/contact/tax selections after real
browser interaction. Check local readiness with:

```bash
connectors/xero/reconciliation/xero-reconcile status
```

The status output reports `optional_dependencies.websockets`,
`optional_dependencies.node`, `optional_dependencies.playwright`,
`optional_dependencies.playwright_apply_engine`, and `live_cdp_ready`. The
apply engine first tries the local Node module resolver, then
`$PLAYWRIGHT_MODULE`, then `~/repos/openclaw/node_modules/playwright`. Dry-run
commands that work from saved statement snapshots do not need a live browser
websocket connection.

## Current Commands

```bash
connectors/xero/reconciliation/xero-reconcile status
connectors/xero/reconciliation/xero-reconcile inspect --cdp-endpoint ws://127.0.0.1:9222/devtools/browser/<id>
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

Current `inspect` uses Chrome DevTools' HTTP target list to identify open Xero
and likely Reconcile tabs. It redacts query strings/fragments and does not read
DOM, cookies, local storage, credentials, MFA, or browser profile files.

Current `capture-lines` connects to the selected already-open page target and
reads visible text only. It parses statement-line candidates and records that it
did not access cookies or browser storage. It does not click or submit anything;
clicks are isolated to the separate explicit-plan `apply` command.

Current `dry-run` is a preflight artifact: it validates the explicit CDP
endpoint requirement, records expected reconciliation candidates, optionally
parses a visible statement-line text or JSON snapshot, and writes a report
without clicking Xero. When a saved statement line exactly matches an expected
API-created record by reference and amount, the report records the match in the
preflight artifact but does not emit an executable apply plan unless the target
is known to already be visible in the row. The current Playwright engine does
not yet drive Find & Match search.

Current `apply` consumes a reviewed line-intent plan. Without
`--confirm-apply`, it runs the Playwright engine in dry-run mode: it fills and
verifies fields but does not click row-scoped OK. With `--confirm-apply`, it
clicks OK only after one-row and hidden-field guards pass. The engine does not
launch or log into a browser; it connects to the supplied already-authenticated
CDP endpoint.

Every completer-driven selection must include the expected hidden `id`/code.
For contacts this is the Xero `ContactID`; for accounts this is the committed
account GUID from the BankRec hidden field, not just the chart-of-accounts
code; for tax this is the committed tax code only when that tax widget is
explicitly rendered and selected. Plans that provide only `query`/`display`
for contact/account/tax/transfer completers are unsafe and the apply engine
must reject them before clicking OK.

Confirmed apply is intentionally one line per invocation. Dry-run may verify a
multi-line plan, but `--confirm-apply` refuses plans with anything other than
one reviewed line intent.

Supported apply actions:

- `create`
- `transfer`
- `match`
- `accept-suggestion` (alias of `match`)

Example reviewed line-intent plan:

```json
{
  "lines": [
    {
      "statement_line_id": "11111111-1111-1111-1111-111111111111",
      "action": "create",
      "amount": 300.00,
      "account": {
        "query": "881",
        "display": "881 - Owner A Funds Introduced",
        "id": "cf6813ff-22ba-4448-a594-4f5e12ef7595"
      },
      "tax": {
        "query": "BAS Excluded",
        "display": "BAS Excluded",
        "id": "BASEXCLUDED"
      },
      "description": "Owner funds introduced"
    },
    {
      "statement_line_id": "22222222-2222-2222-2222-222222222222",
      "action": "transfer",
      "amount": -300.00,
      "transfer_account": {
        "query": "Wise",
        "display": "Wise Business",
        "id": "3d9942ea-ebae-46e4-8527-b0d3fd749ef9"
      }
    },
    {
      "statement_line_id": "33333333-3333-3333-3333-333333333333",
      "action": "match",
      "amount": 95.00,
      "match_text": "INV-123"
    }
  ]
}
```

## Planned Commands

- Validate transfer completer behavior against live Xero markup.
- Validate tax combo behavior against live Xero markup.
- Add richer Find & Match dialog handling once a live match case is captured.

## Expected File Shape

```json
[
  {
    "statement_line": "Bank fee",
    "expected_reference": "BANK-FEE-1",
    "expected_amount": 12.34,
    "expected_action": "match_existing"
  }
]
```

## Statement Snapshot Shapes

Plain text snapshots split blank-line-separated blocks into statement-line
candidates:

```text
BANK-FEE-1
Bank fee
$12.34
```

JSON snapshots may be a list or an object with `statement_lines`/`lines`:

```json
{
  "statement_lines": [
    {
      "statement_line": "Bank fee BANK-FEE-1",
      "amount": 12.34
    }
  ]
}
```

## Apply Plan Shape

The apply plan may be a JSON array or an object with `lines`/`plan`. It is an
accounting-intent shape, not a selector-action language:

```json
{
  "lines": [
    {
      "statement_line_id": "11111111-1111-1111-1111-111111111111",
      "action": "create",
      "amount": 12.34,
      "account": "404 - Bank Fees",
      "tax": "BAS Excluded",
      "description": "Bank fee"
    },
    {
      "statement_line_id": "22222222-2222-2222-2222-222222222222",
      "action": "transfer",
      "amount": -250.00,
      "transfer_account": "Wise Business"
    }
  ]
}
```

Every line must include `statement_line_id`, `action`, and signed `amount`.
`create` requires `account`. `transfer` requires `transfer_account`.
`match` requires `match_text`, `transaction_text`, `expected_match`, or
`reference`, and the apply engine selects/verifies a matching transaction
candidate in the Match tab before OK can be clicked.
`account`, `tax`, `contact`, and `transfer_account` must be objects with
`query`, `display`, and expected hidden `id` whenever the apply engine will
commit a Xero completer selection. String-only selections are for legacy
planning output only and must not be used for confirmed apply.
