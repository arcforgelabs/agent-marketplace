# Arc Forge Agent Marketplace

Public agent plugins maintained by [Arc Forge Labs](https://github.com/arcforgelabs). One
repository distributes the same plugin payload to Codex, Claude Code, and Cursor using each host's
native marketplace manifest.

## Codex

```bash
codex plugin marketplace add arcforgelabs/agent-marketplace
codex plugin add field@arc-forge-agents
```

Start a new Codex task and ask: **Set up Field for me and verify the connection.**

## Claude Code

```text
/plugin marketplace add arcforgelabs/agent-marketplace
/plugin install field@arc-forge-agents
```

Run `/reload-plugins` when prompted, then ask: **Set up Field for me and verify the connection.**

## Cursor

In the team dashboard, open **Settings → Plugins → Import**, then import:

```text
https://github.com/arcforgelabs/agent-marketplace
```

Publish **Field** as Optional, Default On, or Required. Developers will find it in **Customize →
Plugins**. Start a new Agent conversation and ask: **Set up Field for me and verify the connection.**

## Authenticate Field

The agent installs the bundled `field` launcher. Authenticate once from your own terminal:

```bash
field auth login --url https://field.embarkearthworks.au
```

Paste the service key into the hidden prompt. The key is stored locally at
`~/.config/field/token` and does not need to be included in a Codex conversation.

Verify the handoff without exposing the key:

```bash
field auth status
field email-templates list
```

The first command must identify the expected Field service account. The second must return the
live template catalogue. If either fails, keep the task open and repair setup before operational
work begins.

## Updates

- Codex: `codex plugin marketplace upgrade arc-forge-agents`, then reinstall/update Field.
- Claude Code: `/plugin marketplace update arc-forge-agents`, then update Field in `/plugin`.
- Cursor: enable Auto Refresh on the imported GitHub marketplace.

Open a new agent conversation after installing or updating so the refreshed skill is loaded.

## Plugins

- **Field** — jobs, quotes, invoices, email templates, catalog, and production workflows.

Codex Desktop and Cursor display the catalog as **Arc Forge**. Claude Code uses the unique catalog
identifier **arc-forge-agents**. The installed plugin appears as **Field** in all three hosts. No
production credentials, customer records, or runtime data belong in this repository.
