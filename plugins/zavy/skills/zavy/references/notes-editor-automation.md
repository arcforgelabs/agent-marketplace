# Notes Editor Automation (Lexical)

Zavy's note composer is a **Lexical** rich-text editor (`contenteditable`).
Driving it over CDP has sharp edges; these are the ones that cost time.

## Composer anatomy

- Route: `/patients/{id}/notes` — the composer is inline at the top.
- Note **type** is an Ant-style `.zavy-select`. In observed DOM the selects in
  order are `Author, Status, Type, Snippets` (Type is usually index 2). Open with
  a `mousedown` on `.zavy-select-selector`, then click the
  `.zavy-select-item-option` whose text matches (e.g. `General Note`).
- Buttons: **Draft**, **Publish**, **Lock**.
- **Drafts do not persist unless you Publish.** `location.reload()` wipes the
  composer. Good for experiments (nothing saved), but don't expect a half-built
  note to survive.

## Inserting content — use paste, not execCommand

- DO NOT build the note line-by-line with
  `execCommand('insertParagraph')` + `execCommand('insertText')`. The paragraph
  breaks collapse and you get one wall-of-text block.
- DO dispatch a synthetic paste with an HTML payload. Lexical's paste importer
  turns it into real blocks:

  ```js
  const dt = new DataTransfer();
  dt.setData('text/html', html);
  ed.dispatchEvent(new ClipboardEvent('paste', {clipboardData: dt, bubbles:true, cancelable:true}));
  ```

### Paste fidelity (tested)

- **Preserved:** headings `<h1>`–`<h4>`, bullet/numbered lists `<ul>/<ol><li>`,
  inline font size via `<span style="font-size: 16px">…</span>`.
- **Stripped:** `<strong>`/`<b>` bold and text colour. Apply those via the
  toolbar afterwards, or design without them.
- Implication: structure (headings, lists, body font size) is reliable from a
  single paste; emphasis is not.

### Duplication gotcha (important)

The paste handler **non-deterministically fires 2–3×**, and `selectAll`+`delete`
does NOT reliably clear first. Reliable pattern:

1. `location.reload()` (true clean slate), wait ~6s.
2. Re-select the note Type.
3. Paste once.
4. **Verify a structural count** (e.g. `editor.querySelectorAll('h3').length`
   equals the number you authored).
5. If doubled, repeat from step 1. Do not loop the paste itself — it compounds.

When scripting the check in bash, the eval helper prints JSON (`"9"` with
quotes); strip quotes before comparing or the test silently fails and you keep
appending copies.

## Block types and the toolbar

Toolbar buttons carry class `zavy-lexical-toolbar-toolbarButton`. The first is
the block-type dropdown. Available block types:

> Heading 1–4 · Normal · Bullet List · Numbered List · **Checklist** · Code · Quote

- **Make a checklist:** select the target list's `<li>` range (a DOM `Range`
  from first `<li>` to last), open the block dropdown, click `Checklist`.
  Produces interactive tickboxes (`zavy-lexical-list-ul`).
- **Font size is inline on the text run.** Applying a size to a whole-document
  selection overrides heading sizes too. Size the **body only** — cleanest by
  pasting body text wrapped in `<span style="font-size:16px">`; leave headings
  unwrapped so H-tags keep their size (H3 ≈ 24px, body 16px reads well).

## Other insert tools

- **Variables** = merge fields grouped `Business / Practice / Patient /
  Patient App` — insert live patient/practice data (e.g. name, DOB) that
  auto-fills. Good for header fields that should never go stale.
- **Snippets** = saved reusable text blocks (practice-shared or private).
- Link, Image, Table also available.

## Editing an existing note in place (use CDP Input, not synthetic JS)

The decisive lesson: **synthetic JS and real CDP input behave completely
differently** in this Lexical editor.

- **Synthetic JS does NOT register** — `execCommand('insertText'/'selectAll')`,
  a dispatched `ClipboardEvent` paste into a *populated* editor, or setting
  `input.value` all silently no-op or jumble (the editor's internal selection
  never moves), and a follow-up Publish then saves nothing or spawns a stray
  draft. This is why naive headless edits fail.
- **The CDP Input domain DOES register** — `Input.dispatchMouseEvent` +
  `Input.insertText` are real input; Lexical processes them as genuine typing, so
  the edit lands and Publish saves it to the **same note**. Validated live on an
  id-tracked note (id unchanged, no duplicate).

Reliable in-place edit recipe:

1. **Open Edit** by clicking the card's `data-testid="components-notes-note-edit-button"`.
   (Button *clicks* register fine via synthetic events — only text *input* needs
   real events.) Work only in the edit panel — the ancestor that contains a
   **Cancel** button — and ignore the always-present empty new-note composer.
2. **Place the caret with a real click**: compute the target point from a DOM
   `Range` at the text position (`range.getBoundingClientRect()` → `{x,y}`), then
   `Input.dispatchMouseEvent` `mousePressed`+`mouseReleased` at that point.
3. **Type** with `Input.insertText` (use `Input.dispatchKeyEvent` for Backspace/
   Enter/arrows when you need to delete or move).
4. **Save** with a real Input click on the edit panel's **Publish** (button
   centre).
5. **Verify**: reload, read the note id from the Apollo cache and assert it is
   unchanged (proves in-place, not a new note), exactly one copy, content changed.

`Cancel` reliably discards an in-progress edit (the published note is untouched).
**Recreate is only a fallback** for wholesale rewrites where re-typing is
impractical: archive the old note and paste fresh into an *empty* composer.
Humans editing in the UI have none of these constraints.

## Maintaining a single "living summary" note (upsert)

Treat the summary as a find-by-title **singleton**; never assume it exists, and
never create a second active summary just because writing a fresh note is easier.

1. Query notes for active notes with the agreed title (example:
   `Internal Summary`).
2. Identify system-owned notes by a machine-owned marker in the body/footer.
   Never treat an unmarked/human-authored summary as safe to overwrite.
3. Branch: **0 system-owned →** create. **1 system-owned →** edit that same note
   in place and publish. **>1 active system-owned →** fail closed, report the
   duplicate set, and clean it intentionally; do not create another card.
4. Create = fresh composer → type General → paste-HTML → re-apply **Checklist**
   to the Admin list → Publish → Pin.
5. Update = card Edit → replace content in the edit panel using real CDP Input
   → Publish → leave Pin set.
6. Stamp `Last synced YYYY-MM-DD` once near the top. **Verify** after reload:
   exactly one active system-owned note, Published, Pinned, synced = today, and
   the note id is unchanged for updates.

- **Archive a note** via the card action `data-testid="note-archive-button"`
  (no confirm dialog). Other card actions: `components-notes-note-edit-button`,
  `components-notes-note-print-button`, `components-notes-actions-sticky-link`
  (pin/unpin).
- Use CDP driving for recon, verification, or repairing a known duplicate.
  Do not invent a write API; Zavy has no self-service mutation surface in this
  skill.

## Linking a note to a task

The **Create Task** form (patient Tasks tab) is pre-linked to the **Patient** and
has a **"Search note"** field to attach a specific note — so task→note/patient
linking is native. Tasks have **no stable per-task URL**, so note→specific-task
hyperlinks are not reliable. The form is React-controlled with the same
headless-fill fragility as the editor; a human fills it in a few clicks.

## Worked examples (fictional patients — illustration only)

### 1. Edit a line in place — same note, via CDP Input
Goal: append a minute-level time to the `Last synced` line of patient
**Jane Citizen**'s pinned `Internal Summary` note, without creating a copy.

```js
// (a) open Edit — button clicks register fine; only text input needs real events
card.querySelector('[data-testid="components-notes-note-edit-button"]').click()
// (b) caret point at the END of the target line
const p = [...editor.querySelectorAll('p')].find(p => /Last synced/.test(p.innerText))
const w = document.createTreeWalker(p, NodeFilter.SHOW_TEXT); let t; while (w.nextNode()) t = w.currentNode
const r = document.createRange(); r.setStart(t, t.length); r.setEnd(t, t.length)
const box = r.getBoundingClientRect()         // → x = box.right, y = box.top + box.height/2
```
Then over CDP (NOT synthetic events):
```
Input.dispatchMouseEvent { type: mousePressed,  x, y, button: left, clickCount: 1 }
Input.dispatchMouseEvent { type: mouseReleased, x, y, button: left, clickCount: 1 }
Input.insertText { text: " 14:05" }            // "Last synced 2026-01-15 14:05"
```
Real Input click on the edit panel's **Publish**, then reload and assert the note
id (Apollo cache) is unchanged → in-place edit proven.

### 2. Create a structured note + checklist — manipulation
Goal: add a General Note for patient **John Smith** summarising today's visit with
an actionable checklist.

- Set type to `General Note` (3rd `.zavy-select`), then **paste `text/html`** into
  the empty composer (headings, lists and `<span style="font-size:16px">` survive;
  bold/colour are stripped):
  ```html
  <h3>Visit summary — 15 Jan</h3>
  <ul><li><span style="font-size:16px">Exam + 2× BW, no caries</span></li>
      <li><span style="font-size:16px">Scale &amp; clean, OHI given</span></li></ul>
  <h3>Follow-ups</h3>
  <ul><li>Recall 6/12</li><li>Send hygiene info</li></ul>
  ```
- Select the *Follow-ups* `<li>` range → toolbar block dropdown → **Checklist**
  for interactive tickboxes.
- **Publish**, then **Pin** if it should stay at the top of the Notes tab.

## Verify visually

`Page.captureScreenshot` over CDP works on **background tabs**, so you can build
in a new tab and screenshot to confirm headings/checklist/spacing without
focusing it. Always verify formatting before Publish.
