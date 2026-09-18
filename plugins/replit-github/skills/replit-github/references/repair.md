# Repairing a Replit project whose history has diverged from GitHub

Symptoms: the Git tool shows `BRANCH_ALREADY_EXISTS` when pushing `main`;
`git merge-base <workspace> origin/main` is empty; the Agent reports it
"cannot fast-forward"; GitHub PRs exist whose commits are not in the workspace
(REST-reconstructed).

Worked example: arcforgelabs/field-crew, 2026-09-18 — 77 workspace commits,
no merge-base, three API-made PRs on GitHub. Total repair ≈ 40 minutes.

## Procedure

1. **Freeze.** No pushes or publishes from either side until done. From the
   Agent get `git rev-parse HEAD`, `git status --porcelain | wc -l`,
   `git branch -a`, `git remote -v`.
2. **Point the Git tool at GitHub** if it is not already (Settings → Remote
   URL). It will fetch GitHub's branches under the `subrepl-*` remote.
3. **Get the workspace history onto GitHub under a new name.** Agent:
   `git checkout -b replit-workspace`. Human (Git tool): *Push branch as
   `<remote>/replit-workspace`*. Confirm the credential prompt.
4. **Decide the winner on a real clone** (a workstation, not Replit):
   ```bash
   git fetch origin --prune
   git merge-base origin/main origin/replit-workspace   # usually empty
   git diff --stat origin/main origin/replit-workspace
   git diff --diff-filter=D --name-only origin/main origin/replit-workspace  # GitHub-only files
   ```
   The workspace is normally the deployed, tested lineage and a superset of
   GitHub; check that GitHub-only files are genuinely superseded.
5. **Merge without rewriting.** Workspace wins:
   ```bash
   git checkout -B sync-main origin/replit-workspace
   git merge -s ours --allow-unrelated-histories origin/main \
     -m "Merge GitHub main into Replit workspace history"
   ```
   Old `main` stays reachable; the tree is exactly the workspace. If GitHub
   has real changes the workspace lacks, use a normal merge and resolve.
6. **Verify the merged tree builds** (install, typecheck, tests). On pnpm
   workspaces run the libs build first (`pnpm run typecheck:libs`) or
   package typechecks fail on stale declarations.
7. **Fast-forward GitHub main**: `git push origin sync-main:main`. No force.
8. **Re-point the workspace.** Agent:
   `git checkout main && git branch --set-upstream-to=<remote>/main main && git branch -D replit-workspace`.
   Human (Git tool): *Refresh and Fetch* → *Sync Changes / Pull*.
   Agent: `git rev-parse HEAD` must equal GitHub `main`.
9. Continue with `setup.md` steps 5–9 (files, token, verify, prove).
10. Republish if the deployed build should include the reconciled tree.

## Anti-patterns that make it worse

- Letting the Agent "fix" it through the GitHub API.
- Force-pushing GitHub `main` to the workspace SHA (loses GitHub-only work
  and any PR history).
- Doing steps 3 or 8 inside a Replit *task* view — it pushes as
  `subrepl-<task>/…` and the main workspace is untouched.
