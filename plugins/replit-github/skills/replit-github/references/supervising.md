# Supervising a Replit project from outside (Claude Code / Codex + MCP + browser)

Division of labour that works:

| Need | Use |
|---|---|
| Run shell/git commands in the workspace, read files | Replit MCP: `ask_question` (read-only), `update_app_using_prompt` (changes). Ask for exact command output. |
| Anything needing GitHub auth from the Replit side | Human, or an agent driving the **Replit Git tool** in a logged-in browser. |
| Push/merge on GitHub | Your own clone + `gh`. Author with the noreply email. |
| Publish / status | Replit MCP `publish_app`, `get_publish_status` (poll every 60–90 s; 5–8 min). |

Loop for "get a fix live":

1. Reproduce and fix on your clone; open a PR; merge.
2. Agent: `scripts/github-sync.sh pull` (with token) — or Git tool Pull.
3. `publish_app`; poll; then verify the **live URL renders**, not just that
   status says `success` (a blank page with 200s is the classic failure —
   check asset URLs return JS, not HTML).

Browser-driving notes:

- Replit's new UI hides tools; open them via the "+" tab → search
  ("git", "shell", "secrets").
- Make sure you are in *Return to main version*, not a task, before touching Git.
- The Shell tool does not reliably accept synthetic keystrokes; prefer MCP.
- The in-app browser needs its own Replit/GitHub login; check before assuming.

Token handling: an agent may prefill the GitHub fine-grained-token form
(name, owner, repo, permissions, expiry) and stop at "Generate token". The
human generates it and pastes it into Replit Secrets. Agents never see, store,
or relay the value.
