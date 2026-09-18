# replit-github

Status: `active`

Pattern for wiring a Replit project to a GitHub repo so the Replit Agent can
push branches, open PRs, and pull `main` itself, plus the procedure for
repairing projects whose Replit and GitHub histories have already diverged.

- `SKILL.md` — the model and target state (read first)
- `references/setup.md` — new project / repo / account checklist
- `references/repair.md` — reconcile unrelated histories without rewriting
- `references/supervising.md` — driving it from Claude Code/Codex via MCP + browser
- `assets/github-sync.sh`, `assets/git-credential-github.sh`,
  `assets/replit-project-skill.SKILL.md` — files to copy into the target repo
  (replace `__OWNER__/__REPO__`; the script also honours `GITHUB_REPO`)

First applied to `arcforgelabs/field-crew` on 2026-09-18.
