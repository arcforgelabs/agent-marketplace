# Field

Portable Field integration for **Codex, Claude Code and Cursor**. Bundles the Field CLI and operating skill for jobs, quotes, invoices, email templates and catalog workflows.

## Install

Register the [marketplace](../../README.md#install-by-host) in your host, then install Field:

- **Codex:** `codex plugin add field@arc-forge-agents`
- **Claude Code:** `/plugin install field@arc-forge-agents`
- **Cursor:** select Field from the imported marketplace and publish it with the desired team availability policy.

Start a new agent conversation and ask: **Set up Field for me and verify the connection.** The agent runs the bundled launcher installer.

## Authenticate

Authenticate once in your own terminal, using your Field service origin:

```bash
field auth login --url https://field.example.com
```

Enter the service key through the hidden prompt. It is stored locally at `~/.config/field/token` with user-only permissions. Never commit it, paste it into a conversation, or add it to this plugin.

## Verify setup

```bash
field auth status
field email-templates list
field email-templates show invoice standard
```

Setup is complete only when `field auth status` identifies the expected service account and `field email-templates list` returns the live template catalogue. If either fails, repair setup before operational work begins.

See the [marketplace update instructions](../../README.md#updates) for your host.
