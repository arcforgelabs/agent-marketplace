# AGENTS.md

Read `VISION.md` before starting work. `README.md` indexes the rest of the documentation.

<!-- arc-forge-org-consistency:start -->
## Issues

Use the forms in `.github/ISSUE_TEMPLATE/`; they copy upstream OpenClaw's. Answer each field from observed evidence, or write `NOT_ENOUGH_INFO`. Without the web form, use each field label as a `###` heading. One issue per report; reuse an open issue. Agent-authored work starts from an issue, and its pull request links it with `Closes #` or `Related: #`. A defect in OpenClaw itself goes upstream through upstream's own forms and rules.

## Pull requests

Use `.github/pull_request_template.md`. Keep these sections current in the pull request body:

- What Problem This Solves
- User Impact
- Why This Change Was Made
- Evidence

Evidence names the command, the commit, the result, and what was not run. A screenshot is the real product, with the viewport and whether the data was synthetic or live. If the proof could not be run, name the gap in Evidence. When a review asks for more proof, edit the body. Maintainer authorship does not skip the sections. A passing test is evidence about this source. Production activation is a separate record.

The org default procedure is `.github/org-consistency/skill/SKILL.md`. A stricter rule already in this file wins.
<!-- arc-forge-org-consistency:end -->
