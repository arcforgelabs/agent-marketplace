# AGENTS.md

Read `VISION.md` before starting work. `README.md` indexes the rest of the documentation.

The shared rules are referenced below; this repo's own rules are in Marketplace safeguards, at the end.

<!-- arc-forge-org-consistency:start -->
Read the shared Arc Forge instructions before work:
https://github.com/arcforgelabs/tools/blob/main/docs/AGENTS.shared.md

Optional local source: ~/repos/tools/docs/AGENTS.shared.md.
Verify that the local checkout has the origin arcforgelabs/tools before use.
Do not copy the shared rules here.
Keep repository-specific safeguards and document references outside this block.

Common agent workflows: https://github.com/openclaw/agent-skills.
Product repositories own their product-specific skills.
Reusable release workflows: https://github.com/openclaw/release-workflows.
<!-- arc-forge-org-consistency:end -->

## Marketplace safeguards

### Layout

Each package lives once, in `plugins/<name>/`. A skill package holds one copy of the skill at `skills/<name>/SKILL.md`, which every platform reads unchanged (Agent Skills format). Only the wrappers differ, and they are generated, not hand-written:

| File | Read by |
| --- | --- |
| `plugins/<name>/plugin.json` (Agent Plugins format, agent-plugins.org) | Codex, Cursor |
| `plugins/<name>/.claude-plugin/plugin.json` | Claude |
| `.agents/plugins/marketplace.json` | Codex |
| `.cursor-plugin/marketplace.json` | Cursor |
| `.claude-plugin/marketplace.json` | Claude |

Skill packages (`PROVENANCE.json` with `kind: skill`) come from `arcforgelabs/tools` through `forge-tools skills cloud publish`. Fix a skill there, not here. OpenClaw packages keep their own layout under `plugins/<name>/openclaw/`.

### Install

The marketplace is `arc-forge-agents`, from `arcforgelabs/marketplace`.

- **Claude** (claude.ai, Cowork, Claude Code cloud sessions and project threads): on claude.ai open **Customize > Plugins > Add > Add marketplace**, enter `arcforgelabs/marketplace`, turn on **Sync automatically**, then install the plugins you want. Claude Code CLI: `claude plugin marketplace add arcforgelabs/marketplace`, then `claude plugin install <name>@arc-forge-agents`.
- **Codex**: `codex plugin marketplace add arcforgelabs/marketplace`, then `codex plugin add <name>@arc-forge-agents`.
- **Cursor**: import `arcforgelabs/marketplace` as a team marketplace, then install the plugins you want. A Cloud Agent keeps the plugin versions it started with.
- **OpenClaw**: install an OpenClaw package with the steps in its `plugins/<name>/README.md`. For a skill package, run `openclaw skills install` on `plugins/<name>/skills/<name>/`.
- **Any other harness that reads Agent Skills**: copy `plugins/<name>/skills/<name>/` into that harness's skills folder.
