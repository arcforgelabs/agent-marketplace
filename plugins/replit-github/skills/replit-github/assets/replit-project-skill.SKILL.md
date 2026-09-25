---
name: github-sync
description: Push work to GitHub, open a pull request, or pull main from GitHub for this project. Use whenever the user says push, PR, pull request, sync to GitHub, pull main, get this into the repo, or asks whether the workspace matches GitHub.
---

# GitHub sync (__OWNER__/__REPO__)

GitHub `main` is the source of truth. The Replit workspace is a clone of it and
publishes from its own files, so keep the two identical.

## Facts you must not re-discover

- The GitHub remote in this workspace is **not** called `origin`. The Replit
  Git tool names it after the workspace (`subrepl-*`). `scripts/github-sync.sh`
  finds it by URL; do not add a second remote.
- Your shell has **no GitHub credentials by default**. The GitHub connector
  only gives API access (`proxyFetch`), never a token, so plain `git push`
  fails with "Invalid username or token". The Replit Git tool authenticates
  with the human's browser session, which you cannot use.
- **Never** create commits on GitHub through the REST API (blobs/trees/commits).
  That produces commits whose hashes differ from the local ones and splits the
  history; it took a manual merge to repair last time.
- `main` must only move by fast-forward. Never rebase, amend, or force-push it.
- Replit auto-commits ("Published your App", checkpoints) land on the current
  branch. Do feature work on a branch so `main` stays fast-forwardable.

## Decide which path

Run `scripts/github-sync.sh status`.

- `auth: GITHUB_TOKEN works` → you can push and pull yourself (Path A).
- `auth: no GITHUB_TOKEN` → prepare the work and hand it off (Path B).

## Path A — do it yourself (GITHUB_TOKEN secret present)

1. Start from current main: `git checkout main && scripts/github-sync.sh pull`
2. Branch: `git checkout -b <type>/<short-slug>` (feat/, fix/, chore/)
3. Make the change, run the relevant typecheck/tests, commit with a clear message.
4. Open the PR: `scripts/github-sync.sh open-pr "<title>"` — this pushes the
   branch and prints the PR URL. Report the URL to the user.
5. When the user says it is merged: `git checkout main && scripts/github-sync.sh pull`,
   then delete the branch locally.
6. "Sync main" / "pull from GitHub" alone = step 5 only.

## Path B — hand off (no token)

1. Do steps 1–3 of Path A, except replace the pull with a warning that main
   may be behind GitHub (you cannot fetch).
2. Run `scripts/github-sync.sh handoff` and paste its output verbatim in your
   reply. It contains the branch name, HEAD sha, and the exact clicks a human
   or supervising agent needs in the Replit Git tool
   (Push branch as `<remote>/<branch>` → open PR → after merge, Pull on main).
3. Tell the user the permanent fix is a `GITHUB_TOKEN` secret and walk them
   through **Setting up GITHUB_TOKEN** below. Then Path A works without any
   handoff.

## Setting up GITHUB_TOKEN (walk the human through this)

Use this whenever `status` says `no GITHUB_TOKEN` or `GitHub rejected it`, or
the user asks how to give you push access. The human does every step; you never
see, print, or store the token value.

1. Open **https://github.com/settings/personal-access-tokens/new**
   (GitHub → avatar → Settings → Developer settings → Personal access tokens →
   Fine-grained tokens → Generate new token).
2. **Token name:** `replit-__REPO__`. **Expiration:** 90 days.
3. **Resource owner:** switch from the personal account to **__OWNER__**.
   If this is skipped, the repo will not appear in the list.
4. **Repository access:** *Only select repositories* → `__REPO__`.
5. **Repository permissions:**
   - *Contents:* Read and write (push)
   - *Pull requests:* Read and write (open PRs)
   - *Workflows:* Read and write — only if you will edit `.github/workflows/`
   - *Metadata:* Read-only is added automatically
6. **Generate token** and copy it — GitHub shows it only once.
7. In Replit: **Tools → Secrets → New Secret**, key `GITHUB_TOKEN`, paste the
   value. Tell the user not to paste it into the Agent chat.
8. If the org requires approval the token shows as pending; an org owner
   approves it at https://github.com/organizations/__OWNER__/settings/personal-access-token-requests
9. Verify: run `scripts/github-sync.sh status` → `auth: GITHUB_TOKEN works`.

If the token is later rejected, check in this order: expired (make a new one
and replace the secret), still pending org approval, resource owner was the
personal account, or `__REPO__` is not in its repository list. To reuse one
token for another repo, edit its repository list on GitHub and add the same
secret to that project.

## After any pull

Run `pnpm install --frozen-lockfile` if `pnpm-lock.yaml` changed, then
`pnpm run typecheck`. Publishing deploys the workspace files, not GitHub, so
the workspace must contain the merged commit before you publish.
