# BankRec live-DOM verification — 2026-06-08

Read-only CDP inspection of the live Xero Bank Reconciliation page
(`https://go.xero.com/BankRec/BankRec.aspx?accountID=…`, Business #5357) to verify
the assumptions baked into `scripts/xero_reconciliation.py`'s capture/apply.
No clicks, no writes — `Runtime.evaluate` returning DOM structure only.
Contains **UI schema only**; no amounts, payees, or balances.

## Headline finding: the page is a HYBRID, not classic ExtJS

The connector's capture was built for the **classic ExtJS BankRec grid**
(`.x-grid-row` / `.x-grid-cell` / `.x-grid-cell-inner`). On the live page those
selectors match **nothing**:

| Selector | Live count |
|---|---|
| `table`, `tr`, `td` | **0** |
| `.x-grid-row`, `.x-grid-cell` | **0** |
| `[role="row"]`, `[role="gridcell"]` | **0** |
| `[data-testid]` | 50 |
| `[data-automationid]` | 47 |
| `[class*="statement-line"]` | 7 (6 real lines + 1 header/template) |

Statement-line **data** is rendered by a modern React MFE. Statement-line
**confirm controls** are still the classic anchors. Hence "hybrid".

## Capture — target these test-ids (per statement line, each ×6)

```
[class*="statement-line"]        line container (6 real + 1 template)
  [data-testid="posted-date"]    date            (SPAN, font-size-small)
  [data-testid="notes"]          payee / description (SPAN, font-size-medium)
  [data-testid="analysis-code"]  reference       (SPAN, font-size-medium)
  [data-testid="amount-spent"]   SPENT amount    (font-size-medium)  -> negative
  [data-testid="amount-received"]RECEIVED amount (font-size-medium)  -> positive
  [data-testid="more-details"]   per-line button
```

**Sign is now unambiguous and column-order-free:** `amount-spent` and
`amount-received` are *dedicated named fields*. A line populates exactly one of
them. Map `amount-spent` → negative, `amount-received` → positive. No
"last-two-columns" inference, no `sign_confidence:"low"` guessing needed when the
modern fields are present.

> The `date | desc | ref | spent | received` *column-order* assumption in
> `parse_grid_rows` is therefore moot for the live UI — there are no columns.

## Apply — classic anchors still present

- `a.okayButton` / `a.xbtn` / `a.x-btn` → **12 matched**, of which **6** are
  `<a class="xbtn skip okayButton exclude">OK</a>` (text "OK"), one per line.
- So FIX 1 (adding `a.okayButton` to the apply button selectors) is **valid and
  confirmed against the live DOM**. The classic confirm control is real.
- `[data-testid="more-details"]` (×6) is the modern per-line expander, not the
  confirm.

## Status of the committed connector work (commit 53555a9) vs live reality

| Fix | Verdict |
|---|---|
| FIX 1 — `a.okayButton` apply selectors | ✅ validated live (6 OK anchors present) |
| FIX 2 — column-structured `.x-grid-*` capture + sign confidence | ⚠️ design is sound but the `.x-grid-*` path matches nothing live; needs a **modern test-id capture path** (preferred) ahead of the blob fallback |
| FIX 3 — dry-run inline-JSON/file args | ✅ UI-independent |

## Reproduce

Read-only probes used (kept in `/tmp`, not committed):
`inspect_bankrec_grid.py`, `probe_bankrec_dom.py`, `probe_bankrec_modern.py`,
`probe_bankrec_buttons.py` — each imports `cdp_evaluate` from
`scripts/xero_reconciliation.py` and evaluates a structure-only expression
against the open BankRec page on CDP `http://127.0.0.1:9226`.

## Caveats / not yet verified

- Captured against **one** account (#5357) with 6 lines in "Reconcile" view.
  Re-confirm test-ids hold for the "Account transactions" tab and for lines with
  both spent+received, FX lines, and the match/create sub-flows.
- The full **match → confirm** click sequence (search transaction, select, then
  the `a.okayButton` OK) was **not** exercised — that mutates real books and must
  be done with a single-element guard, never autonomously.
