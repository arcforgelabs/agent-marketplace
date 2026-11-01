# Chart catalogue

Chart Lab drew 42 kinds of chart on the same subject. Each kind was rated: great, good, meh or poor. Use this list to pick a chart. Pick from great and good. Use meh only with the fix in its note. Do not use poor.

Source: Chart Lab, `references/chart-lab.html` (ratings of 2026-10-19). The page source holds a hand-drawn vector graphic for every kind: copy from it when `charts.js` has no renderer.

`charts.js` column: the renderer name in `kit/charts.js`, or `—` (draw it by hand). The kit also has helpers that are not rated kinds: `bars` (one bar per row, series colours), `table` (a CrispTable from rows; the last resort, see pattern.md), `data` (one data set with a chart, table and diagram view switch) and `tabs` (one figure per item, such as a customer or an option).

## Great

| Kind | Family | charts.js | Note |
| --- | --- | --- | --- |
| Container diagram | Boxes and arrows | `container` | Zones that hold parts. Better than a layer stack. |
| Live anatomy | Boxes and arrows | — | Lines of code next to their effect on a chart. Highest potential for teaching. Make the controls strong. |
| Sketch style | Boxes and arrows | — | A rough-pen filter over a normal diagram. A style, not a kind: use it on a diagram that is a quick idea. |
| Heatmap | Amounts | `heatmap` | A value for each row and column pair. Columns keep a fixed width. Column titles never overlap: `headers: 'auto'` (default) sets them flat when they fit, on two lines when that fits, else at an angle of 40 degrees. Set `'flat'`, `'wrap'` or `'angle'` to force one. |
| Sankey | Amounts | `sankey` | Flows as bands; band width is the amount. |
| Parallel sets | Amounts | — | One group split by several categories in turn. |
| GPU graph | Networks | — | Thousands of linked parts (cosmos.gl). For real, large graphs only. |

## Good

| Kind | Family | charts.js | Note |
| --- | --- | --- | --- |
| Connection diagram | Boxes and arrows | `connection` | A structure view. Parts as boxes, joined by labelled arrows. Pair it with a view from another family. |
| State machine | Boxes and arrows | — | States of one thing and the events that move it. For lifecycles. |
| Anatomy callout | Boxes and arrows | — | Labels on the parts of one thing. Tie code lines to their effect. |
| Expand and collapse | Boxes and arrows | — | Groups open on tap. Readers keep open what they need. |
| Capacity bars | Amounts | `capacity` | One limit split into named parts, one bar per step. |
| Treemap | Amounts | — | How much space each part takes. Add details on tap. |
| Sunburst | Amounts | — | Related parts on the inner ring, their details on the outer ring. |
| Timeline | Time and order | `timeline` | Events and waits on a real time scale. One home for a HYPOTHETICAL story strip. |
| Snake flow | Time and order | — | A long line of steps that wraps. One home for a HYPOTHETICAL story strip. |
| Tree | Hierarchy | `tree` | Parent and child parts. |
| Fishbone, version 2 | Hierarchy | — | Causes of one failure; each failure path is obvious. |
| Arc diagram, version 2 | Networks | — | Parts on one line, links as arcs, with focus on hover. |
| Grouped graph | Networks | — | Parts in hulls. Good in sketch style. |
| Grouped graph, version 2 | Networks | — | Layers that turn on and off. |
| Concentric | Networks | — | Rings of parts. Use a high-contrast theme for busy lines. For risk, draw a blast radius: solid for confirmed, dashed for not checked. |
| Particle flow graph | Networks | — | Moving dots show speed, volume and where data backs up. Use it to show a threat or a failure in motion against real live numbers. |
| 3D graph | Networks | — | Needs labels, a legend and pause on hover. |
| 3D graph, WebGL | Networks | — | Calm motion: drag turns the view; hover waits. |

## Meh: use only with the fix

| Kind | Fix |
| --- | --- |
| Arc diagram | Use version 2. |
| Area chart with tooltip | Use only with data that is a real series over time. |
| Bump chart | Ranks over time. No note yet. |
| Edge bundling | Attractive but slow to read. Add hover focus or expand and collapse. |
| Chord diagram | Attractive but slow to read. Same fix as edge bundling. |
| Fishbone | Use version 2. |
| Hive plot | No note yet. |
| Keyed container diagram | Prefer the container diagram with the diagram colour key in a legend. |
| Ladder | No note yet. |
| Mind map | Other kinds do this job better. |
| Radial tree | Add expand and collapse. |
| Sequence diagram | Do not use. A chart that needs a tutorial is a bad chart. Show a request path as a connection diagram. |
| Step-through simulation | A great feature. Free it from fixed colours: let it follow the theme. |
| Every token | No note yet. |

## Poor: do not use

| Kind | Why |
| --- | --- |
| Chip lanes (FlowLanes) | Shows no connections. Only for very short, simple lists. |
| Layer stack | You have to squint. Use a container diagram. |
| Scroll story, WebGL | Rated poor. |

## Lessons from the ratings

- A theme can make or break a chart. High contrast made the concentric layout clear.
- Attractive is not enough. If the meaning is slow to read, add focus on hover, hidden detail or expand and collapse.
- The data must fit the chart. A good chart with the wrong data reads as meh.
- Progressive disclosure wins: expand and collapse, pop-ups and Facts lists.
- Show the problem as a drawn figure. Keep paragraphs off the open page.
- Show an unknown as a question mark or a dashed line. Leave a guess off the figure.

## Alternative views for these page rules

Use these when the subject needs them. The ratings above stay as they are. Pair the primary view with one from another family, as in `pattern.md`.

| Page rule | Alternative view | Kind |
| --- | --- | --- |
| Threat or failure | Animated paths and dots against real live numbers | Particle flow graph |
| Risk | Blast radius. Rings spread outward. Solid means confirmed. Dashed means not checked. | Concentric |
| What would have stopped it | Story strip stamped HYPOTHETICAL. Each step shows the fix. | Timeline, or snake flow |
| Bad case | Good-example contrast figure | A comparison view of the same subject, often a table or a second diagram |
| Proposed change | After view of the main picture. Banner reads PROPOSAL, NOT APPROVED. | The same kind as the main picture |
