# Field

## OpenClaw

The OpenClaw product integration is the native plugin at `plugins/field/openclaw` (`@arcforgelabs/openclaw-field`). The operator points it at their Field origin and authenticates with `openclaw mcp login`. Quote and catalog tools come from Field MCP. Do not install a Field CLI or long-lived bearer into an OpenClaw Gateway.

See `plugins/field/openclaw/README.md`.

## Portable (Codex, Claude Code, Cursor)

Portable Field integration for **Codex, Claude Code and Cursor**. Bundles the Field CLI and operating skill for jobs, quotes, invoices, email templates and catalog workflows. This lane is not the OpenClaw product integration.

## Install

Register the marketplace in your host, then install Field:

- **Codex:** run `codex plugin marketplace add arcforgelabs/agent-marketplace`, then `codex plugin add field@arc-forge-agents`.
- **Claude Code:** run `/plugin marketplace add arcforgelabs/agent-marketplace`, then `/plugin install field@arc-forge-agents`.
- **Cursor:** import `https://github.com/arcforgelabs/agent-marketplace` in the team dashboard under **Settings → Plugins → Import**, then select Field and set its team availability policy.

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

## Updates

- **Codex:** run `codex plugin marketplace upgrade arc-forge-agents`, then update Field.
- **Claude Code:** run `/plugin marketplace update arc-forge-agents`, then update Field in `/plugin`.
- **Cursor:** enable Auto Refresh on the imported marketplace.

Start a new agent conversation after updating.
