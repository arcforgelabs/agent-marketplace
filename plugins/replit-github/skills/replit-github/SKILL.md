---
name: replit-github
description: "Wire a Replit project to a GitHub repo so the Replit Agent can push, open PRs, and pull main; diagnose or repair Replit/GitHub history drift; set up new Replit projects or accounts against arcforgelabs repos."
---

# Replit ↔ GitHub

Replit projects and GitHub repos drift apart unless wired deliberately. This
skill is the pattern; the reusable files live in `assets/`; the long-form model,
setup checklist, and repair procedure live in `references/`.

## The model (memorise this)

| Actor | Can | Cannot |
|---|---|---|
| Replit **Git tool** (UI) | fetch/pull/push using the *human's* browser session | be driven by the Agent |
| Replit **Agent shell** | local git (branch/commit/config) | reach GitHub — no credential helper exists |
| GitHub **connector** (Agent) | REST API via `proxyFetch` (`repo` scope) | expose a token, so it cannot drive `git` |
| Replit **publish** | deploy the **workspace files** | read GitHub |

Consequences:

- Without a token the Agent "pushes" by reconstructing commits through the
  REST API → different hashes → unrelated histories. This is the usual root
  cause of drift. Never let an Agent do that.
- The remote the Git tool creates is named `subrepl-<id>`, not `origin`.
  Task sandboxes each get their own; do git work in the *main version*.
- Replit auto-commits ("Published your App") on the current branch, so
  feature work must live on branches to keep `main` fast-forwardable.
- A publish is not live from GitHub; the workspace must pull first.

## Target state for every wired project

1. Git tool → Settings → Remote URL = `https://github.com/<owner>/<repo>.git`;
   workspace `main` tracks `<subrepl-remote>/main`.
2. Replit Secret `GITHUB_TOKEN` = fine-grained PAT scoped to that repo,
   *Contents: read/write* + *Pull requests: read/write*. A human creates it;
   agents never handle token values.
3. In the repo: `scripts/github-sync.sh`, `scripts/git-credential-github.sh`,
   `.agents/skills/github-sync/SKILL.md` (copy from `assets/`, replace
   `__OWNER__/__REPO__`). Plus a short "GitHub" section in `replit.md`.
4. Rule: nothing commits to `main` directly on either side. Branch → PR →
   merge on GitHub → `scripts/github-sync.sh pull`. Off-Replit work follows
   the same path, so no second sync process is needed.

Verify with `scripts/github-sync.sh status` → `auth: GITHUB_TOKEN works`,
`ahead 0, behind 0`. Then prove it: have the Agent open a trivial PR by itself
and pull after merge.

## Which reference to open

- New project, new repo, or new Replit account: `references/setup.md`
- Existing project whose Git tool says `BRANCH_ALREADY_EXISTS`, or
  `git merge-base` between workspace and GitHub is empty: `references/repair.md`
- Supervising from outside Replit (Claude Code + Replit MCP + browser):
  `references/supervising.md`

## Gotchas

- Fine-grained PATs are per resource owner; select the org (e.g.
  `arcforgelabs`), not the personal account. One token may cover several
  repos, but each Replit project needs the secret added separately.
- Git tool fetch sometimes reports UNAUTHENTICATED; "Sync Changes" retries fine.
- Driving the Replit Shell through browser automation is unreliable; ask the
  Agent (MCP `ask_question`) to run commands and report output instead.
- GitHub rejects pushes authored with a private email; use the
  `<id>+<user>@users.noreply.github.com` address.
- The Agent's `.agents/skills/*` are versioned files, so the project skill
  arrives on the next pull — no UI step.
