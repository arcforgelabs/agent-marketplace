# Creative figures

The kit renderers in `kit/charts.js` draw correct figures. Correct is the floor, not the bar. A first draft built only from kit boxes reads as plain, and the reader then asks for "more creative" in a second or third round. This file sets the bar for the first draft.

The bar comes from the three best pages so far:

- **A file-encryption explainer.** The hero draws one real file with its locked values, one data key and a locked copy for each key holder. Later figures: paint mixing as an analogy for key agreement, a clock for one-way maths, one value scrambled step by step, and a ruler from 10⁰ to 10⁸⁰ that puts "keys to try" beside "atoms in the universe".
- **A secret-store plan.** The hero draws the store as a vault door with three ways in and short tokens out. Later figures: a blast radius with an "as asked" and a "recommended" view, an outage story strip stamped HYPOTHETICAL, a state machine with icons, a sunburst of namespaces, a snake of build steps with the hold points.
- **A model-pricing page.** Charts use the real company logos as the marks. A scatter plot shades the "good" quadrant, draws the price cap as a line, joins the best-value models with a dashed line and rings the winner. Segmented filters, a slider and a search list change the chart live. A small dot grows into its logo on a click.

`kit/draw.js` (`ExDraw`) gives the parts those pages drew by hand: icons, icon discs, logo plates, arrows with ids, moving dots, stamps, leader lines and blast rings. Section 10 of `examples/explainer-kit.html` uses each one.

## The first-draft rule

1. Before you write code, name the subject's own shape: the real-world thing it is like (a vault, a locked file, a pipe, a ladder, a clock, a map, a funnel, a ring of walls). Write down three candidates. Pick the one a reader knows at a glance.
2. Draw the hero figure as that shape with `ExDraw`. Do not open a page with an `ExCharts.connection` box diagram. Kit renderers are for the alternative view and for later sections.
3. Draw at least half of the sections by hand. Use a kit renderer where the subject has no shape of its own (a timeline of dates, a tree of causes).
4. Each hand-drawn figure answers one question, with one red thing. Decoration with no content is not allowed.
5. Run the creative check (below) before `scripts/check`. Fix each miss in the first draft.

## Patterns

Pick by the question. Use a pattern only when the subject fits it. Use at least four different patterns on a page of six or more sections.

| Pattern | Use it when | How to draw it |
| --- | --- | --- |
| Metaphor hero | Always, for the opening figure | The subject as its real-world shape, with the main parts as icon discs around it. Arrows name what moves. Dots show the main flow. |
| Icon discs | A part is a kind of thing: person, agent, server, key, phone | `ExDraw.badge(x, y, {icon, title, sub, tone, ex})`. Never a plain box for a thing that has an icon. |
| Real logos | A named product, company, vendor or model maker is on the figure | `ExDraw.logo(x, y, {src, title, ex})`. Also use logos as the marks on a chart, in a legend and in a pick list. |
| Flow in motion | Something moves: data, tokens, requests, an attack | `ExDraw.arrow(d, {id})` and `ExDraw.dots(id, n, seconds, tone)`. Red dots only on the key path. |
| Blast radius | A risk, a lost key, a takeover | `ExDraw.rings(cx, cy, rings, core)`. Solid red = reached. Dashed = not reached or not checked. Add a wall (`.ex-wall`) where a control stops it. Give an "as asked" and a "recommended" view in a view switch. |
| Story strip | A failure in time, or why a fix matters | Five panels with a time, an icon, a title and the fix that would stop it. Stamp HYPOTHETICAL. |
| Analogy | A mechanism is hard: maths, crypto, a protocol | A picture from daily life (paint mixing, a clock, a post box). Stamp ANALOGY. Put the real mechanism in a second view of the same switch. |
| Worked example | A transform: encrypt, hash, route, price | Follow one synthetic value through each step. Show the real bytes or numbers. Stamp SYNTHETIC. |
| Scale ruler | A number too large or small to feel | A log ruler with real-world anchors (seconds since the Big Bang, grains of sand, atoms). Mark the subject's numbers in red. |
| Before and after | A change, a fix, a migration | The same picture twice, side by side or in a switch. Stamp the after view PROPOSAL, NOT APPROVED until it is approved. |
| State machine | A thing moves between states | Pill boxes with icons, curved arrows that name each trigger. A dashed arrow for a path not used. |
| Sunburst or rings | A hierarchy with two or three levels | Centre = the whole, inner ring = groups, outer ring = parts. Red on the group the page is about. Tree view as the alternative. |
| Snake path | Steps in order, with hold points | A path that turns at the row end. A hardware-key icon or a red disc at each step that needs a person. |
| Live data chart | A choice among many options with numbers | A scatter or bar chart with logos as marks, a shaded good quadrant, a limit line, a best-value line and a ringed winner. Filters (segmented control), a slider and a search list change it live. |

## Live data charts

A page that compares many options lets the reader ask their own question.

- Marks are logos on light plates (`.ex-plate`). Small dots stand for options that are not picked; a click grows a dot into its logo.
- Shade the good quadrant with `--accent-subtle` or `--accent-2-subtle`, and name it in the corner in mono capitals ("UNDER CAP · HIGH SCORE").
- Draw each limit as a labelled line. Draw the best-value frontier as a dashed line through the marks on it. Ring the winner.
- Put the controls above the chart: a segmented control (`.ex-seg`) for each choice, a slider for a continuous value, and a search list beside the chart. Each control redraws the chart and the winner line under it ("Best: … · score · price").
- Keep axis titles in mono capitals with an arrow ("PRICE A MONTH, LOG SCALE →"). Use a log scale when the values span more than 20 times.
- Keep the control state in the page. Store it in `localStorage` only when the reader will come back.

## Logos

- Get a logo from Simple Icons at a pinned version, for example `https://cdn.jsdelivr.net/npm/simple-icons@13.21.0/icons/github.svg`, or from the product's own press kit. Simple Icons are free to use (CC0); the marks stay the owners' trademarks.
- Put the file in the page as a base64 data address (`data:image/svg+xml;base64,…`), so the page works offline and holds no literal colour.
- Put each logo on a plate (`ExDraw.logo` or `.ex-plate`). The plate stays light in dark mode.
- Use a logo only for a real, named product. A kind of thing (a server, a person) takes an icon.

## Icons

- `ExDraw.icons` holds 32 line icons on a 24 by 24 grid: key, hard key, person, people, agent, server, database, lock, unlock, vault, shield, file, cloud, phone, laptop, terminal, clock, door, bolt, eye, no, check, warn, globe, coin, gauge, spark, gear, mail, chat, box, branch.
- Add a page icon with `ExDraw.icons.name = '<path d="…"/>'`. Keep it to strokes on the 24 by 24 grid.

## The creative check

Answer each line before `scripts/check`. A "no" is a fix in this draft, not a note for later.

- The hero is a drawn picture of the subject's own shape, not a kit box diagram.
- Every named product or company on a figure shows its logo.
- Every part that is a kind of thing shows an icon.
- One flow moves (dots), where something moves.
- The page uses at least four patterns from the table above.
- A hard mechanism has an analogy (stamped) or a worked example (stamped).
- A huge or tiny number sits on a scale with real-world anchors.
- A comparison of many options is a live chart with logos and filters, not a table.
- Each figure has one red thing.
- Each main concept still has a second view from another family.

## Drawing rules

- Draw in a fixed view box. Give `ExDraw.svg` a minimum width so a wide figure scrolls inside its card on a phone.
- Text in a figure uses the kit classes: `ex-t` (title), `ex-ts` (sub line), `ex-tm` (mono capitals), `ex-ta` (red mono), `ex-tl` (mono label).
- Shapes use the kit classes: `ex-box`, `ex-disc`, `ex-plate`, `ex-ring`, `ex-core`, `ex-solid`, `ex-lead`, `ex-line`, each with `--key`, `--alt` or `--off`. Add a page class only for a shape the kit does not have, and give it token colours only.
- Every part a reader can ask about has `data-ex` (use `ExDraw.hit` or the `ex` option). The runtime opens its pop-up.
- Moving dots stop when the reader asks for reduced motion. `ExDraw.dots` does this.
