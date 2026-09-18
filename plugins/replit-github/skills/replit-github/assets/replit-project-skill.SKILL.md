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
3. Tell the user the permanent fix: add a `GITHUB_TOKEN` Replit Secret
   (fine-grained PAT for __OWNER__/__REPO__ with Contents: read/write and
   Pull requests: read/write). Then Path A works without any handoff.

## After any pull

Run `pnpm install --frozen-lockfile` if `pnpm-lock.yaml` changed, then
`pnpm run typecheck`. Publishing deploys the workspace files, not GitHub, so
the workspace must contain the merged commit before you publish.
