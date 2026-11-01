# Reply formats

A reply format is the shape of what the reader gets: a page, a widget, a video, a sound or a picture. This table picks the format. Each live format has one guide. Use the first row that fits.

| Reader need | Format | Guide | State |
| --- | --- | --- | --- |
| See a finished UI change work: on-screen actions, dialogs, flows | UI walkthrough video | `ui-walkthrough.md` | live |
| Understand a system, a plan or a comparison with more than nine parts, or parts that need definitions | Explainer page | `../pattern.md` and `SKILL.md` "Make a page" | live |
| One small idea, five to nine parts, in the chat frame | Inline widget | `SKILL.md` "Inline widgets" | live |
| Hear a reply instead of reading it | Audio reply | none yet | planned |
| See a scene or a motion that no real screen shows | Generated video | none yet | planned |
| See an illustration that no diagram can show | Generated image | none yet | planned |

## Rules for every format

- One format per reply part. A UI change can have a walkthrough video and an explainer page; each answers a different need.
- Use the best tier the environment has. A guide names its tiers. Say in the reply which tier you used when it is not the best one.
- Diagrams stay SVG in the explainer kit. A generated image never replaces a diagram.
- Show only data that is safe to show: synthetic data, or the user's own data in a private reply.
- Check the output before you cite it. A failed take, a wrong frame or a broken page is not delivered.

## Add a format

1. Write `references/formats/<format>.md`: when to use it, what the environment needs, the tiers, how to make it, how to check it, how to deliver it.
2. Change its row here from planned to live.
3. Add a script to `scripts/` only when the format has a repeatable recipe, and prove it with a real output in the pull request.
