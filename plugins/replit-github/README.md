# replit-github

Wire a Replit project to a GitHub repo so the Replit Agent can push, open PRs, and pull main; diagnose or repair Replit/GitHub history drift; set up new Replit projects or accounts against arcforgelabs repos.

A generic operating skill from [arc-forge-tools](https://github.com/arcforgelabs/arc-forge-tools)
(`components/skills/replit-github`, staged from `55c87c896a71`). Fix and review it
there; this package is a generated release payload.

## Install

- **Claude Code / Codex / Cursor:** add the `arc-forge-agents` marketplace from
  this repository and install the `replit-github` plugin. The skill loads as
  `replit-github`.
- **Manual:** copy `skills/replit-github/` into your harness's skills directory.

The skill's own `SKILL.md` documents when it applies and what it needs.
Nothing in this package contains credentials or account-specific data.
