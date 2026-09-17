# Handover — Xero connector: SummarizeErrors=false fail-closed guard

**Date:** 2026-06-11 · **Repo:** `~/repos/arc-forge-tools` (branch `main`) · **Shipped:** `b7704bb` (pushed to origin)

## What this is

Several Xero apply commands POST with `?SummarizeErrors=false`, under which Xero
returns **HTTP 200 even when the element is rejected** (failures embedded as
`ValidationErrors` / `HasValidationErrors`). They were writing an apply-ledger
entry and reporting `"ok": true` regardless — false audit records, including on
money-recording paths. This change makes them **fail closed**.

## State (done, verified, pushed)

- Shared helper `_guard_document_apply` in `connectors/xero/scripts/xero_core.py`
  (reuses `extract_validation_errors`): raises `XeroCliError` **before** any
  audit/ledger write when validation errors are present OR the created-object ID
  is missing. Mirrors the existing `command_ap_batch_pay` stance.
- Wired into **5** commands: `documents create`, `ap draft-bill`,
  `documents update`, `reference upsert`, `prework create` (the last covers
  Payments / BatchPayments / BankTransactions / BankTransfers / ManualJournals;
  `SummarizeErrors=false` is default-on there).
- 11 new tests in `connectors/xero/tests/test_xero_org_billing.py`
  (refuse→0 ledger / success→1 ledger per command, plus the ID-echoed-with-errors
  branch). All 7 suites green; `py_compile` clean.
- Built via the `/forge` multi-model loop (opus/sonnet/fable), exited CLEAN.
  The deep review surfaced `reference upsert` + `prework create` beyond the
  original 3-path scope.

## Remaining / not done

- **No live OAuth test.** All proofs are against faked HTTP-200 responses; the
  guard has not been exercised against a real rejected Xero call. Worth a single
  live smoke test on a sandbox tenant before relying on it operationally.
- `command_ap_batch_pay` (already had its own guard) and `command_documents_action`
  (no `SummarizeErrors` masking) were deliberately left unchanged. There are no
  remaining unguarded instances of this pattern in `xero_core.py`.

## How to verify

```
cd ~/repos/arc-forge-tools/connectors/xero
python3 -m py_compile scripts/xero_core.py tests/test_xero_org_billing.py
for f in tests/test_*.py; do echo "== $f"; python3 "$f"; done
```
