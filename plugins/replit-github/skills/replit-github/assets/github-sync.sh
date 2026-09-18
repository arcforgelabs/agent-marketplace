#!/usr/bin/env bash
# GitHub sync helper for the Replit workspace (and any clone).
#
#   scripts/github-sync.sh status                 # remote, upstream, ahead/behind, auth
#   scripts/github-sync.sh pull                   # fast-forward main from GitHub
#   scripts/github-sync.sh push-branch [name]     # push current (or named) branch
#   scripts/github-sync.sh open-pr "<title>" [body-file]   # push + open PR from current branch
#   scripts/github-sync.sh handoff                # print a handoff block when no token is available
#
# Transport: real git over HTTPS using the GITHUB_TOKEN secret through
# scripts/git-credential-github.sh. Without GITHUB_TOKEN nothing here can reach
# GitHub — use `handoff` and let a human push from the Replit Git pane.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
HELPER="$ROOT/scripts/git-credential-github.sh"
REPO_URL="https://github.com/${GITHUB_REPO:-__OWNER__/__REPO__}.git"
OWNER_REPO="${GITHUB_REPO:-__OWNER__/__REPO__}"
MAIN="main"

die() { echo "github-sync: $*" >&2; exit 1; }

# The Replit Git pane names the GitHub remote after the workspace (subrepl-*);
# a plain clone calls it origin. Find whichever remote points at GitHub.
remote_name() {
  git -C "$ROOT" remote -v | awk -v url="$REPO_URL" '$2 == url && $3 == "(fetch)" {print $1; exit}'
}

ensure_remote() {
  local r
  r="$(remote_name)"
  if [ -z "$r" ]; then
    git -C "$ROOT" remote add origin "$REPO_URL"
    r=origin
  fi
  echo "$r"
}

ensure_helper() {
  chmod +x "$HELPER"
  if [ "$(git -C "$ROOT" config --get credential.helper || true)" != "$HELPER" ]; then
    git -C "$ROOT" config credential.helper "$HELPER"
  fi
}

have_token() { [ -n "${GITHUB_TOKEN:-}" ]; }

require_token() {
  have_token || die "GITHUB_TOKEN is not set. Add it as a Replit Secret (fine-grained PAT: Contents RW, Pull requests RW on $OWNER_REPO), or run: $0 handoff"
}

cmd_status() {
  local r; r="$(ensure_remote)"; ensure_helper
  echo "remote:   $r -> $REPO_URL"
  echo "branch:   $(git -C "$ROOT" branch --show-current)"
  echo "head:     $(git -C "$ROOT" rev-parse --short HEAD)"
  echo "upstream: $(git -C "$ROOT" rev-parse --abbrev-ref --symbolic-full-name @{u} 2>/dev/null || echo none)"
  echo "dirty:    $(git -C "$ROOT" status --porcelain | wc -l) file(s)"
  if have_token; then
    if git -C "$ROOT" ls-remote --exit-code --heads "$r" "$MAIN" >/dev/null 2>&1; then
      echo "auth:     GITHUB_TOKEN works (ls-remote ok)"
      git -C "$ROOT" fetch -q "$r" "$MAIN"
      echo "vs main:  $(git -C "$ROOT" rev-list --left-right --count "HEAD...$r/$MAIN" | awk '{print "ahead " $1 ", behind " $2}')"
    else
      echo "auth:     GITHUB_TOKEN is set but GitHub rejected it"
    fi
  else
    echo "auth:     no GITHUB_TOKEN — push/pull must go through the Replit Git pane (see: $0 handoff)"
  fi
}

cmd_pull() {
  require_token
  local r; r="$(ensure_remote)"; ensure_helper
  [ "$(git -C "$ROOT" branch --show-current)" = "$MAIN" ] || die "switch to $MAIN first"
  [ -z "$(git -C "$ROOT" status --porcelain)" ] || die "working tree is dirty; commit or stash first"
  git -C "$ROOT" fetch "$r" "$MAIN"
  git -C "$ROOT" merge --ff-only "$r/$MAIN"
  git -C "$ROOT" branch --set-upstream-to="$r/$MAIN" "$MAIN" >/dev/null
  echo "main is now $(git -C "$ROOT" rev-parse --short HEAD)"
}

cmd_push_branch() {
  require_token
  local r b; r="$(ensure_remote)"; ensure_helper
  b="${1:-$(git -C "$ROOT" branch --show-current)}"
  [ "$b" != "$MAIN" ] || die "refusing to push $MAIN directly; open a PR instead"
  git -C "$ROOT" push -u "$r" "$b:$b"
}

cmd_open_pr() {
  require_token
  local title="${1:?usage: open-pr \"<title>\" [body-file]}" body_file="${2:-}"
  local b; b="$(git -C "$ROOT" branch --show-current)"
  cmd_push_branch "$b" >/dev/null
  local body
  if [ -n "$body_file" ]; then body="$(cat "$body_file")"; else body="$(git -C "$ROOT" log --reverse --format='- %s' "$MAIN..HEAD")"; fi
  local payload
  payload="$(jq -n --arg t "$title" --arg h "$b" --arg b "$MAIN" --arg body "$body" '{title:$t, head:$h, base:$b, body:$body}')"
  curl -sS -f -X POST \
    -H "Authorization: Bearer $GITHUB_TOKEN" \
    -H "Accept: application/vnd.github+json" \
    "https://api.github.com/repos/$OWNER_REPO/pulls" \
    -d "$payload" | jq -r '"PR #\(.number): \(.html_url)"'
}

cmd_handoff() {
  local b r; b="$(git -C "$ROOT" branch --show-current)"; r="$(remote_name)"; r="${r:-origin}"
  cat <<EOF
=== GitHub handoff (no GITHUB_TOKEN in this workspace) ===
repo:    $OWNER_REPO
branch:  $b
head:    $(git -C "$ROOT" rev-parse HEAD)
dirty:   $(git -C "$ROOT" status --porcelain | wc -l) uncommitted file(s)
commits not on $MAIN:
$(git -C "$ROOT" log --format='  %h %s' "$MAIN..HEAD" 2>/dev/null || echo '  (unknown - main not fetched)')

To publish this to GitHub, a human (or a supervising agent driving the
browser) opens the Replit Git tool on this project, confirms "Pass GitHub
credentials" if prompted, and clicks "Push branch as '$r/$b'".
Then open the PR at https://github.com/$OWNER_REPO/compare/$b?expand=1
After it merges: switch to $MAIN in the Git tool and click Pull (fast-forward).
Alternatively, add a GITHUB_TOKEN secret and re-run: scripts/github-sync.sh open-pr "<title>"
EOF
}

case "${1:-}" in
  status) cmd_status ;;
  pull) cmd_pull ;;
  push-branch) shift; cmd_push_branch "$@" ;;
  open-pr) shift; cmd_open_pr "$@" ;;
  handoff) cmd_handoff ;;
  *) sed -n '2,12p' "$0"; exit 1 ;;
esac
