# Setting up a Replit project against a GitHub repo

Do this before the Agent makes its first commit if at all possible. Budget
15 minutes for a fresh project, more if section `repair.md` applies.

## Prerequisites (once per GitHub org / Replit account)

- The GitHub org allows fine-grained personal access tokens
  (Settings → Personal access tokens → "Allow access via fine-grained tokens").
  `arcforgelabs` already does.
- The Replit account has the GitHub connection active (Replit → Integrations →
  GitHub). This provides the Git tool's browser-session auth and the Agent's
  read-only connector; it does **not** give the Agent push.

## Per project

1. **Create the GitHub repo first** (empty is fine). Note the HTTPS URL.
2. In Replit open the project's **main version** (not a task view):
   Tools → **Git** → ⚙ **Settings** → **Remote URL** = the HTTPS URL → Save.
3. In the Git tool, push once. Approve "Pass GitHub Credentials → Confirm for
   this session". If the repo already had a `main`, expect
   `BRANCH_ALREADY_EXISTS`: switch the workspace to a new branch name (Agent:
   `git checkout -b replit-workspace`), push that, merge on GitHub, then pull.
4. Set upstream so Pull/Push appear (Agent shell, no auth needed):
   `git branch --set-upstream-to=<remote>/<default> <default>` (`main` or `master`) where `<remote>` is the
   `subrepl-*` remote pointing at GitHub (`git remote -v | grep github.com`).
5. Add the three files from this skill's `assets/` to the repo unchanged
   (they detect the repo and default branch):
   - `scripts/github-sync.sh`
   - `scripts/git-credential-github.sh`
   - `.agents/skills/github-sync/SKILL.md` (from `replit-project-skill.SKILL.md`)
   Add a "GitHub" section to `replit.md` pointing at them. Commit and push
   (via PR, per the rule).
6. **Token** (human only). Open https://github.com/settings/personal-access-tokens/new
   (GitHub → Settings → Developer settings → Fine-grained tokens → Generate):
   - Resource owner: the org (e.g. `arcforgelabs`)
   - Repository access: *Only select repositories* → the repo
   - Permissions: *Contents* read/write, *Pull requests* read/write
     (*Metadata* read is added automatically)
   - Expiry: 90 days is a sane default; note the date in `replit.md`.
   Then Replit → Tools → **Secrets** → `GITHUB_TOKEN` = the token.
   To reuse one token for another repo, edit the token's repository list
   (takes effect immediately) and add the secret to that project too.
7. Verify: Agent runs `scripts/github-sync.sh status` →
   `auth: GITHUB_TOKEN works`, `ahead 0, behind 0`.
8. Prove it: ask the Agent to make a one-line change and "open a PR" — it
   should branch, push, and print a PR URL. Merge it, then ask it to
   "sync main" — HEAD must equal GitHub `main`.
9. Optional but recommended: GitHub branch protection on `main` (require PR,
   no force-push) so the "nothing commits to main directly" rule is enforced
   mechanically.
10. Consider `attached_assets/` in `.gitignore`; Replit commits every
    screenshot the Agent is shown otherwise.

## What the Agent does afterwards

`.agents/skills/github-sync/SKILL.md` tells it: work on a branch, open PRs with
`scripts/github-sync.sh open-pr`, pull main with `scripts/github-sync.sh pull`,
and if `GITHUB_TOKEN` is missing, print `scripts/github-sync.sh handoff` — a
block with branch, SHA, and the exact Git-tool clicks for a human or a
supervising agent.
