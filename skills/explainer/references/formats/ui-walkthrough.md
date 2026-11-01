# UI walkthrough video

A UI walkthrough video is one continuous screen recording of a UI change that already works. It shows the change as a person meets it. Setup stays out of the take.

## When to record

Record when all of these are true:

- The change is on a screen: a button, a dialog, a form, a list, a flow.
- The change is finished and its tests pass. Record only a path that already works.
- The environment has tier A or tier B (below).

Do not record setup, a failing path or a change with no on-screen action. A still screenshot is enough for a layout-only change and for phone widths: one desktop take cannot show 375 px.

## Tiers

A tier is the best clip that an environment can make. Use the highest tier you have.

| Tier | Clip | Needs | Who has it |
| --- | --- | --- | --- |
| A | Desktop take, one window, visible cursor, mp4 | A display (real or Xvfb), ffmpeg, Chromium, Playwright | Claude Code cloud (Xvfb, ffmpeg and Chromium are installed), Claude Code and Codex on a workstation, Cursor cloud agents |
| B | Browser-only take, visible cursor, mp4 | Playwright and Chromium; ffmpeg to trim and convert | Codex cloud and any terminal agent that can install Playwright |
| C | Stills only | A screenshot tool | Claude chat and project threads without a browser |

At tier C, say that no recording was made and why. Hand the recording to an agent that has tier A when the user needs one.

## What the environment needs

1. **A screen.** A real desktop or a virtual display (Xvfb), and permission to start a browser on it.
2. **The app, running, with safe data.** A throwaway database with synthetic names. Never live customer data.
3. **A way past sign-in.** A test session, a stand-in auth script or a seeded cookie. Without it the take stops on the sign-in page.
4. **A recorder.** ffmpeg on the display (tier A) or Playwright `recordVideo` (tier B). It must start, stop and save a file the user can play.
5. **A driver.** Something that performs the clicks: a Playwright script, or a computer-use loop.
6. **This rule.** Without a rule, the agent finishes the code and never opens the app.

## Make the clip

1. Do the setup off camera: start the app, seed the data, sign in, open the first screen at 1280×800.
2. Write the shot list (below) as a JSON file. Each step names one action, its target and what must be visible after it.
3. Run `scripts/record-walkthrough <shots.json> <out.mp4>`. It picks tier A when Xvfb and ffmpeg are present, else tier B. It loads the first screen, waits, then starts the take. A drawn cursor shows each move and each click.
4. If a step fails, the script discards the take and exits 1. Fix the cause and record again. Never upload a failed take.

### Pace: move like a person

These rules come from Cursor's desktop recorder, which makes smooth walkthroughs (asked 28 October 2026). Its clips look natural for two reasons. A real pointer moves on a real screen. The agent stops to look between actions.

- Never cite a bare Playwright `recordVideo` take. It has no cursor, and each click or `page.goto` jumps to the next screen in one frame. Customers read this as "too fast".
- Record the screen, not the page: one headed Chromium window at 1280×800 on a display, and ffmpeg `x11grab` at 30 frames a second.
- Show a cursor in every frame. A desktop driver (`xdotool`, computer use) moves the system pointer. A Playwright driver needs the drawn cursor that `scripts/record-walkthrough` adds.
- Move the cursor on an ease-in-out path: about 20 points over 300 to 500 ms. Playwright `mouse.move` with `steps` sends all the points at once, so the cursor jumps.
- Stop on the target for about 400 ms before a click. Hold the result for 600 to 1100 ms.
- Type real keystrokes, about 50 ms each.
- Keep one tab. Go to the next screen with a click in the app, not with a new address.
- Start the take on the first useful screen. Stop it when the result shows. Trim with ffmpeg `-ss` and `-t`.
- Ring one control only: the control that the clip names.

`scripts/record-walkthrough` uses these values. The public plugin does not ship `scripts/`. Without the script, apply the same numbers in your own driver.

### Driver: script or computer use

- **Script (default).** `scripts/record-walkthrough` moves the mouse with Playwright and draws a cursor in the page. It costs no model calls. It needs a CSS or text selector for each target.
- **Computer use (fallback).** A model sees a screenshot, returns a click, and repeats. Use it when the targets have no stable selectors, or when the take must show the real desktop outside the browser. Each step costs one screenshot and one model call, so a one-minute take is dozens of calls. Start the recorder yourself (ffmpeg `x11grab` on the display), hand the shot list to the computer-use agent, and stop the recorder when it reports that every step passed.

## The shot list

A shot list is the written script that the driver follows. Order it the way a person meets the feature, and the way the issue lists it.

1. **Open on the control.** The first shot is the control the issue asked for.
2. **Cancel before confirm.** Before each confirm, open the dialog and cancel it. This shows the dialog is a gate and a mis-click is harmless.
3. **Confirm with visible proof.** End the confirm on a state change the reader can see: a toast, a count that drops, a row that goes.
4. **Each control on its own.** A second control (for example a bulk action) gets its own cancel and confirm. Do not assume it works because the first did.
5. **Show, do not repeat.** Where a control only has to be present, show it and do not use it again.
6. **End on the boundary.** The last shot shows where the feature must not appear. The rule is then seen, not only asserted by a test.

Hold each state for about one second so a reader can see it. Keep the take under about 60 seconds.

### Shot list file

```json
{
  "title": "Delete a draft invoice",
  "url": "http://localhost:3000/invoices/123",
  "viewport": [1280, 800],
  "steps": [
    {"shot": "1 Open on the control", "do": "hover", "target": "button:has-text('Delete')"},
    {"shot": "2 Cancel before confirm", "do": "click", "target": "button:has-text('Delete')", "expect": "[role=dialog]"},
    {"shot": "2 Cancel", "do": "click", "target": "[role=dialog] >> text=Cancel", "expectHidden": "[role=dialog]"},
    {"shot": "3 Confirm", "do": "click", "target": "button:has-text('Delete')", "expect": "[role=dialog]"},
    {"shot": "3 Confirm", "do": "click", "target": "[role=dialog] >> button:has-text('Delete')", "expect": "text=Invoice deleted"}
  ]
}
```

- `do`: `hover`, `click`, `press` (with `key`), `type` (with `target` and `text`), `scroll` (brings `target` into view), `wait` (with `ms`).
- `expect` / `expectHidden`: a selector that must be visible / hidden after the step. A miss fails the take.
- `hold`: milliseconds to stay on the result (default 1100). `lead` and `tail` on the file: the pause before the first step and after the last (default 1500).
- `examples/walkthrough-shots.json` is a full shot list for the explainer kit page.

## Check the clip

Check the clip before you cite it. The script writes:

- `<out>.json`: each step with its start and end time in the clip.
- `<out>-frames/NN.png`: one frame at the end of each step.

Look at each frame and compare it with its step: the right screen, the dialog open or closed, the proof visible, the cursor on the target. A frame that does not match means the take is wrong: record again. For a computer-use take, watch the video, or have a second agent watch it, and compare it with the shot list.

## Deliver

- **Pull request:** name the clip in Evidence with the command, the commit, the tier, the viewport, and that the data was synthetic. Attach the mp4 or link it.
- **Chat or thread:** attach the mp4 and give one line: what the take shows.
- Add stills for phone widths and for any state the take does not show.

## Worked example

A Cursor cloud agent recorded the Delete action for draft invoices in Flow. The take was one 55-second desktop recording at 1280×800, 12 MB, on synthetic clinics. The app ran against a throwaway Postgres database, and a stand-in script presented a signed-in owner. A computer-use agent drove the mouse; a second pass watched the mp4 before it was cited.

| Shot | What it showed | Rule |
| --- | --- | --- |
| 1 | A pending invoice with Delete, Preview, Save and Approve | Open on the control |
| 2 | Delete, then "Delete this invoice?", then Cancel: the invoice is still open | Cancel before confirm |
| 3 | Delete and confirm: toast "Invoice deleted.", Pending count 8 to 7 | Confirm with visible proof |
| 4 | Two Pending rows ticked, bulk Delete, Cancel, then "Delete 2": count 7 to 5 | Each control on its own |
| 5 | Ready tab, one row ticked: the bulk Delete is there, not used | Show, do not repeat |
| 6 | An approved invoice: Void, Revise, Preview and no Delete | End on the boundary |

Seeding, the sign-in stand-in and the phone layouts stayed out of the take. Phone layouts were stills.

## Cost

- The script driver costs no model calls: a virtual display, one Chromium window, and ffmpeg.
- A computer-use driver costs one screenshot and one model call per step. It is the expensive part.
- A clip check is one look at each step frame, or one model pass over the video.
- A tier A take of 20 seconds is about 0.3 MB; one minute of a busy app is about 10 MB.
