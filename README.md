# Arc Forge Agent Marketplace

Agent integrations, tools and skills maintained by [Arc Forge Labs](https://github.com/arcforgelabs), distributed for **OpenClaw, Codex, Claude Code and Cursor**.

Choose an integration and a supported host below. Each package includes its own installation, authentication and usage instructions; not every integration supports every host.

## Available integrations

| Integration | Supported hosts | Package and setup |
| --- | --- | --- |
| **GoHighLevel** | OpenClaw | [CRM, conversations, opportunities, calendars and workflows](plugins/gohighlevel/openclaw/README.md) |
| **Field** | Codex, Claude Code, Cursor | [Jobs, quotes, invoices, email templates and catalog workflows](plugins/field/README.md) |

GoHighLevel is an unofficial integration developed by Arc Forge Labs, not affiliated with or endorsed by HighLevel.

## Install by host

### OpenClaw

Native OpenClaw packages are distributed individually through release artifacts and ClawHub, not through the other hosts' marketplace catalogs.

Start with the [GoHighLevel package instructions](plugins/gohighlevel/openclaw/README.md) or its [0.2.0 source release](https://github.com/arcforgelabs/agent-marketplace/releases/tag/gohighlevel-v0.2.0). ClawHub submission has been accepted but registry review is pending; a public registry installation is not yet claimed. The source release has no binary attachment.

### Codex

Register this catalog:

```bash
codex plugin marketplace add arcforgelabs/agent-marketplace
```

Select a compatible plugin from the table above and follow its package instructions. The catalog identifier is `arc-forge-agents`.

### Claude Code

Register this catalog:

```text
/plugin marketplace add arcforgelabs/agent-marketplace
```

Select a compatible plugin in `/plugin`, then follow its package instructions. Run `/reload-plugins` when prompted. The catalog identifier is `arc-forge-agents`.

### Cursor

In the team dashboard, open **Settings → Plugins → Import** and import:

```text
https://github.com/arcforgelabs/agent-marketplace
```

Choose a compatible plugin and its team availability policy. Developers find published plugins in **Customize → Plugins**. Follow the selected package's setup instructions.

## Authentication and account context

Authentication is integration-specific; use the selected package's instructions. Do not paste credentials into agent conversations or commit them to this repository.

Public packages contain generic code, skills, fictional examples and blank templates only. Actual account endpoints, IDs, mappings and business rules belong in private profiles delivered separately to authorised workspaces. Credentials and customer records do not belong in those profiles. Installs and upgrades must not overwrite or automatically fetch a populated profile.

## Updates

- **OpenClaw:** follow the package's release and update instructions for the source you installed.
- **Codex:** run `codex plugin marketplace upgrade arc-forge-agents`, then update the selected plugin.
- **Claude Code:** run `/plugin marketplace update arc-forge-agents`, then update the selected plugin in `/plugin`.
- **Cursor:** enable Auto Refresh on the imported GitHub marketplace.

Open a new agent conversation after installing or updating to load refreshed skills.

## How this repository is organised

This is a public distribution repository, not a second implementation source. Maintained source projects produce self-contained release packages with provenance.

- `plugins/<capability>/<runtime>/` contains an assembly when a host needs a distinct runtime, such as `plugins/gohighlevel/openclaw/`.
- `plugins/field/` retains its established portable package path, shared by Codex, Claude Code and Cursor.
- Root host catalogs list only implemented compatible packages; a directory or manifest alone is not a compatibility claim.

See [Contributing](CONTRIBUTING.md) for release maintenance. Report problems through [GitHub Issues](https://github.com/arcforgelabs/agent-marketplace/issues), including the integration, version and host—but no credentials or customer data.
