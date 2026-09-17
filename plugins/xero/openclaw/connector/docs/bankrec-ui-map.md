# Xero BankRec UI map — capture + navigate + apply (2026-06-08)

Authoritative, **read-only-verified** map of the Xero bank-reconciliation page so the
connector can reliably drive it, detect which UI variant is live, and degrade cleanly
when Xero ships a new one. Selectors below were confirmed live against `#5357`
(`BankRec.aspx?accountID=…`) via read-only `Runtime.evaluate` — no clicks/mutations.

Companion: `bankrec-live-dom-2026-06-08.md` (the read-layer finding that kicked this off).

---

## 1. The reality: a HYBRID, evolving page — detect 3 layers independently

Each reconcile row is `div.line#sl<HASH>` and has TWO halves:
- **LEFT — statement-line display: MODERN React MFE** (keyed on `data-testid`).
- **RIGHT — action panel (Match/Create/Transfer + form + OK): CLASSIC ExtJS.**

So "the new UI" only modernized the **display**; **apply is still the legacy ExtJS flow**.
Treat these as independent, separately-detected concerns:
1. **READ layer** (how statement lines are scraped) — modern `data-testid` *or* classic grid.
2. **APPLY layer** (how a line is reconciled) — classic ExtJS today (both variants).
3. **Page identity** — which account, how many lines, reconcile vs other tab.

`<HASH>` = the statement line id with dashes stripped. The row carries it three ways:
`id="sl<HASH>"`, `data-statementlineid="<dashed-guid>"`, `data-index="<n>"`. Every form
field id for that line is suffixed with `<HASH>`.

---

## 2. Detection signals (drive `detect_reconcile_ui()`)

| Concern | MODERN signal | CLASSIC signal |
|---|---|---|
| READ | `[data-testid="amount-spent"]` / `[data-testid="amount-received"]` present | `tr.x-grid-row` / `.x-grid-cell` present, no modern testids |
| APPLY | *(not yet observed)* React form testids, **no** `a.okayButton` / `a.t*` | `a.t2`(Create)+`a.t3`(Transfer)+`a.t1`(Match) anchors AND `input[id^="paidAccount"]` AND `a.okayButton` present |
| Empty / done | reconcile-view banner text "Great job…reconciled all" / "No transactions imported yet" | same banner |

**Clean-update rule:** if the READ layer is modern but the APPLY layer matches **neither**
classic nor a known modern variant (e.g. a future fully-React apply with no `a.okayButton`),
`detect_reconcile_ui()` returns `apply_variant="unknown"` → the connector **captures
read-only and REFUSES autonomous apply**, logging the unknown markup for a human + a new
entry in this doc. Never guess-click an unrecognized confirm control.

---

## 3. READ layer

- **Modern (current):** per-line `data-testid` — `posted-date`, `notes`, `analysis-code`,
  `amount-spent` (→ negative), `amount-received` (→ positive). Implemented:
  `capture_visible_text` → `modern_lines` → `parse_modern_lines`. Sign is column-free
  and unambiguous. See `bankrec-live-dom-2026-06-08.md`.
- **Classic (legacy fallback):** ExtJS grid — rows `tr.x-grid-row`, cells `td.x-grid-cell`
  → `.x-grid-cell-inner`. Implemented: `grid_rows` → `parse_grid_rows`, with blob/selector
  fallbacks. Kept for older orgs / any page still serving the classic grid.
- Capture precedence already encodes this: `modern-testid` > `grid-rows` > `grid-innertext`
  > `selector`.

---

## 4. APPLY layer (classic ExtJS — current for BOTH variants)

Row addressing (pick a line): `#sl<HASH>`, or `[data-statementlineid="<guid>"]`, or
`[data-index="<n>"]`. Scope every field/button query to that row element.

**Mode tabs (anchors inside the row, `href="javascript:"`, onclick handlers):**

| Tab | Selector | Text |
|---|---|---|
| Match | `a.t1` | "Match" |
| Create | `a.t2` | "Create" |
| Transfer | `a.t3` | "Transfer" |
| Discuss | `a.t4` | "Discuss" |
| Find & Match | `a.t5.find` | "Find & Match" |

**Create-tab fields (all ids suffixed `<HASH>`; visible input → backing hidden field):**

| Purpose | Visible input (type here) | Placeholder | Backing hidden field |
|---|---|---|---|
| Contact (Who) | `input#paidTo<HASH>_value` (`.autocompleter`) | "Name of the contact..." | `paidToID<HASH>`, `paidTo<HASH>` |
| Account (What) | `input#paidAccount<HASH>_value` (`.legacy-control`) | "Choose the account..." | `paidAccount<HASH>` |
| Tax / GST | *(visible sibling likely `paidGSTCode<HASH>_value`; confirm on Create-tab expand)* | — | `paidGSTCode<HASH>` |
| Description | `input#paidDesc<HASH>` (`.legacy-control`) | "Enter a description..." | — |
| Reference | `input#reference<HASH>_value` | — | — |

**Transfer-tab field:** `input#transferAccount<HASH>_value` → hidden `transferAccount<HASH>`.
(Rule-creation variants exist: `rulePaidTo<HASH>_value`, `ruleTransferAccount<HASH>_value` —
ignore unless creating a bank rule.)

**Confirm controls (row-scoped):**
- `a.okayButton` = `a.xbtn.skip.okayButton.exclude`, text "OK" → **reconciles the line (MUTATES BOOKS)**.
- `button.save-button` text "Save" (used in some sub-forms).

**Apply flow per line:**
1. Resolve the row by statement line id.
2. Click the mode tab (`a.t2` Create / `a.t3` Transfer / `a.t1` Match).
3. Fill fields. The account/tax/contact inputs are **ExtJS autocompleters** — you must type
   to trigger the dropdown and SELECT the option so the hidden id field is set; setting
   `.value` alone does not populate the hidden id. Description/reference are plain text.
4. Click the **row-scoped** `a.okayButton`.

> **SAFETY — apply mutates real, hard-to-reverse financial records.**
> Step 4 must be human-guarded: assert EXACTLY ONE row matches the intended statement line
> id (and amount) before any click, one line at a time. The connector must NOT auto-apply
> a batch unattended. This is policy, not a TODO.

---

## 5. Legacy (pre-hybrid, fully-classic) instructions

Older Xero served the WHOLE reconcile page as classic ExtJS (no `data-testid` line display).
- READ: `grid_rows`/`parse_grid_rows` (rows `.x-grid-row`, cells `.x-grid-cell`).
- APPLY: identical to §4 (same `a.t*` tabs, `paid*<HASH>` fields, `a.okayButton`).
- DETECT: modern READ signals absent; classic grid present. Route capture to `grid_rows`.

This path stays supported; do not delete the classic read selectors when the modern path
is preferred — they are the fallback the detection layer selects for legacy orgs.

---

## 6. Where this is implemented / to implement

- READ + precedence: `scripts/xero_reconciliation.py` (`capture_visible_text`,
  `parse_modern_lines`, `parse_grid_rows`, `build_capture_report`). DONE.
- `detect_reconcile_ui()` / `classify_reconcile_ui()` (read_variant,
  apply_variant, row_selector, field_map, + unknown-apply refusal): DONE in
  `scripts/xero_reconciliation.py`.
- Apply intent validation: DONE in `scripts/xero_reconciliation.py`
  (`load_reconciliation_plan`). The plan is line intent (`create`/`transfer`/
  `match`), not a selector DSL.
- Apply EXECUTION: `reconciliation/apply-engine/xero-reconcile-apply.js`.
  It connects over Playwright CDP, fills widgets by real browser interaction,
  verifies hidden backing fields, and only clicks row-scoped OK when
  `--confirm-apply` is supplied.
