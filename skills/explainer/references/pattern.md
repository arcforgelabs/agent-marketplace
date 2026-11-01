# Explainer pattern

> Public copy of the Arc Forge explainer pattern, 2026-10-20, with the 25 and 26 October 2026 view, depth, full-word, picture and table rules. In this folder the kit is `kit/` and the starter is `examples/starter.html`.

An explainer is a page or inline widget that explains a system, a plan or a comparison with visuals first. Use one whenever someone asks to explain something, for more detail, how something works, or to compare things. Marketing pages follow the rest of this book; explainers follow this section.

Reference page: `references/chart-lab.html`. Start a new page from `examples/starter.html`: it links `kit/tokens.css`, `kit/explainer.css`, `kit/charts.js` and `kit/explainer.js`.

## Pages are wiki pages

- Explainers grow into a wiki. The best ones are refined and published as learning material.
- One subject per page. A loosely related question gets its own page, not another chart on this one.
- Pages link like a wiki: an item that touches another page's subject holds one fact with that page's name and link, and the other page links back.
- Each page stands alone: it defines its own terms, lists its sources and holds no project chatter.

## Choose the views (critical)

- **Draw the hero by hand** as the subject's own real-world shape, with icons, logos and moving dots (`references/creative.md`, `kit/draw.js`). A kit box diagram is never the opening figure.
- In later sections, default to a **ConnectionDiagram**: parts joined by labelled arrows. Most explainers show how pieces fit together, and only connections show that. Give each part its icon or logo.
- Each arrow names what moves along it. A box with no arrow is a sign of a missing connection.
- Use another kind when the subject needs it. Pick by the question the section answers:
  - How do the parts fit together? A ConnectionDiagram or a container diagram.
  - What happened, and when? A timeline (`ExCharts.timeline`). Never a table of dates.
  - Why did it happen, or what is it made of? A tree (`ExCharts.tree`): the result, then its causes or parts.
  - How does one thing change state? A state machine.
  - How much, against a limit or against each other? Capacity bars, bars, a heatmap or a sankey.
  - Which option, customer or host? Tabs (`ExCharts.tabs`): one figure per item, and the reader switches.
  - What is known and what is not? One diagram with the known parts solid and the unknown parts dashed.
- **Vary the kinds**: two sections in a row that answer different questions use different kinds. A page that uses one kind for every section is a sign that the kind was not picked.
- Pick the best primary view for the subject. Then add at least one alternative view of the same subject from a different family, in a view switch, tabs or a second figure.
- The families are structure, time, amount, hierarchy, and comparison. A table can be an alternative view, never the primary one.
- **Build up from the problem** for a design or a technique: figure 1 shows the problem at its simplest. Each next figure changes one thing, names the change, and shows what it fixes or what still fails. Later figures can combine fixes. Simple figures, many steps. Reference: https://samwho.dev/load-balancing/.
- **Open with a promise, then keep it**: the opening visual shows real data about the exact subject and the question the page answers, so readers know fast if the page is for them. No bait: it should not catch everyone, and the page must deliver what it promises. Reference: https://ngrok.com/blog/prompt-caching.
- **Pretty, with substance**: care in the look is care for the reader. Decoration with no content is not allowed.
- Never use a sequence diagram (lifelines with messages): rated D tier. Show a request path as a connection diagram when structure is the right primary view, and add a second view from another family.
- FlowLanes (chip lanes) are low tier: they only group things. Use them for short, simple lists.
- Chart Lab rates each kind on the same subject: `references/chart-lab.html`. Its ratings decide this list. The tiers are in `charts.md`.

## Picture rules

- Show the problem as a picture. Drawn figures carry it. The open page has almost no paragraphs.
- Where the subject is a threat or a failure, show it in motion. Animate the paths and the dots. Set them against real live numbers.
- Draw risk as a blast radius. Rings spread outward from the point of impact. A solid ring is confirmed. A dashed ring is not checked.
- A story strip is allowed when it is clearly stamped HYPOTHETICAL. Each step shows which fix would have stopped it.
- Add a good-example contrast figure beside a bad case.
- When the page proposes a change, redraw the main picture as an after view. Stamp that figure PROPOSAL, NOT APPROVED. Keep the alternative view from the other family as well.
- Keep the visuals honest. Show an unknown as a question mark or a dashed line. Leave a guess off the figure.

## Words

- Diagrams and visual parts first. Add words only where they help.
- One fact per sentence. Use Simplified Technical English (ASD-STE100) as `ste.md` sets out: 20 words or fewer in an instruction, 25 in a description, approved verb forms and approved words. Australian spelling.
- Simple English means short sentences and common words. Each main item still needs about 4 to 8 substantive facts.
- No acronyms. Write the full words in page text, titles, labels, and pop-ups. Where knowing the short form helps, write it once in brackets after the full term, for example "Web Content Accessibility Guidelines (WCAG)". Then keep using the full term.
- Text longer than one sentence goes behind progressive disclosure: a DetailPopover or a FactsList. Never show it open on the page.
- No preamble and no "This diagram shows…". No slogan or marketing titles.

## Definitions first (critical)

- Every item that opens shows a **definition first**, under its title: pop-ups, Facts lists, More buttons, diagram boxes, table rows.
- A definition says what the item is. One or two sentences is enough for the meaning. The rest of the explanation follows as facts.
- Style it apart: `text-strong`, 14px, with a 1px `border` rule under it. Numbered facts follow. Facts never repeat the definition.
- Every pop-up needs depth after the definition. Aim for about 4 to 8 substantive facts on each main item.
- Cover why the item exists, how it works, how it connects to its neighbours, real numbers, limits and failure modes, and a source or a link where one exists.
- Short sentences are fine. Few facts are not.

## Every item is clickable, every fact has an item

- Every named thing in a diagram, flow, table or chart opens a DetailPopover next to it.
- Every fact belongs to an item. If a fact has no item, the diagram is missing that item: add it.
- A FactsList is built from the items. A click on a fact scrolls to its item, pulses it red and opens its pop-up.
- A pop-up never changes the page below. An outside click, Escape or the item again closes it.

## Section heads

- ExplainerHead: a 3px `accent` rule on top, a big red mono number, a plain title, then a 1–2 fact subtitle in `text` (max 66ch). The first fact defines the subject.
- No mono label above the title. The SectionHead label is for marketing pages only.

## Layout and spacing

- `.ex-shell`: 1040px max, centred, a 16px gutter (safe-area aware).
- `.ex-section`: 40px block padding, 20px gap, a 1px `border` rule at the end.
- Connection diagram: an inline vector graphic; parts 56–70px high, columns with mono caps headers, at least 60px between columns for arrow labels. No label sits on a line.
- FlowLanes: lanes split by 1px `border` rules, mono caps captions, 44px boxes with 8px gaps. Give a busy flow room; never cram it.
- Diagrams and tables sit on `card` with a 1px `border` at `radius-lg`. Reflow for the actual narrow container and wrap labels. Do not shrink text, clip choices or use hidden overflow to simulate fit.

## Colour in diagrams

- Plain part: `card` with `border-strong`. Main family: `accent-subtle` with `accent`. Second family: `accent-2-subtle` with `accent-2` (steel). Optional, not live, unknown, or not checked: dashed. A confirmed blast ring is solid.
- Red marks only the one thing to see first. Status colours only with a word.

## Themes

- Every colour, font, radius and chart series is a token (`kit/tokens.css`). Pages and charts hold no literal colours.
- A page names its theme in `<meta name="ex-theme">`. Clarity is the new default; explicit themes and viewer defaults win. Arc Forge is the fallback, not a fixed look: "red" above means `accent` in the active theme.
- One theme button per page, fixed in the bottom-right corner. Never a theme switcher per component.
- The viewer's pick, then the viewer's saved default, then the page theme, then Arc Forge.
- A data block may have one view switch: chart, table or diagram of the same rows. The first view is never the table. Use the switch, or a second figure, when the second view is another family.

## Tables are the last resort (critical)

- A table shows values. It does not show how things connect, change or cause each other. Most subjects need that, so most pages need no table.
- Use a table only when the reader must look up exact values across three or more columns. Then it sits behind a view switch, after a chart or a diagram of the same rows.
- At most one table shows when a page loads. No section opens on a table. `scripts/check` fails both.
- A table is not a place for sentences. A fact that needs a sentence goes in a pop-up on a diagram part, not in a table cell.
- "Switch, do not stack": several items of the same kind (customers, hosts, options, before and after) go in tabs with one figure each, not in one table with a row each.
- CrispTable: fixed layout, rows at least 44px; wrap values rather than clip labels. Author a stacked narrow view when columns no longer read well. Status columns (76px) sit next to the name. The last column holds a short value and a `More · N` pill.

## Navigation

- TickRail on long pages: fixed in the left gutter, centred top to bottom. Ticks are the same size at rest and grow near the pointer. The current tick is red. Hidden at 900px and below; the content stays centred.

## Full artifact and inline companion

Substantial OpenClaw explainers get both a full responsive artifact and compact native companion from the same facts. Follow `openclaw-delivery.md`: informational native link, genuine blocking native question, existing session identity/link. Never create extra dashboards for decision/status persistence, imitate native controls, or build a state engine.

## Inline widgets

- A small idea gets an inline widget in chat instead of a page: neutral boxes, one red element, transparent ground, frame theme classes only, no hex values.
- The same word rules apply.

## Before you publish

- The main diagram shows connections, unless the subject is a list or a set of values.
- Each main concept has a primary view and at least one alternative view of the same subject from a different family.
- Each section's visual answers its question (Choose the diagram); the kinds vary across the page.
- At most one table shows at load, and no section opens on one.
- Every item opens a pop-up with a definition first, then about 4 to 8 substantive facts on each main item.
- Every fact sits in an item; the FactsList leads to each one.
- No open text longer than one sentence.
- Page text, titles, labels, and pop-ups use full words. Where a short form helps, write it once in brackets after the full term, then keep using the full term.
- The problem is a drawn figure. The open page has almost no paragraphs.
- Where the subject is a threat or a failure, paths or dots move against real live numbers.
- Where the subject is risk, the figure is a blast radius. Solid rings are confirmed. Dashed rings are not checked.
- A story strip is stamped HYPOTHETICAL. Each step shows which fix would have stopped it.
- A bad case has a good-example contrast figure.
- A proposed change has an after view of the main picture, stamped PROPOSAL, NOT APPROVED.
- An unknown is a question mark or a dashed line. A guess is not drawn as a fact.
- Rows keep 44px; the rail picks the right section.
- Light and dark both work in every theme; 320px has no sideways scroll.
- One theme button. Contrast meets Web Content Accessibility Guidelines, level AA, in every theme (`scripts/check`).
- A headless browser test shows no page errors and opens every item and every view.
