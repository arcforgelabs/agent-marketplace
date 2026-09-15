# Field by Arc Forge

Connect OpenClaw to a customer's Field quoting app. The user authenticates against **their** Field origin with OAuth. Quote and catalog tools come from Field's `/mcp` resource after login.

This is the OpenClaw product integration. Do not install a Field CLI, a workspace runbook skill, or a long-lived bearer into the Gateway.

Package: `@arcforgelabs/openclaw-field`  
Plugin ID: `arcforgelabs-field`  
Skill: `field`  
Tested hosts: OpenClaw 2026.9.3 and 2026.9.4.

## Install

```sh
openclaw plugins install /absolute/path/to/package
openclaw plugins enable arcforgelabs-field --accept-capabilities
openclaw config set plugins.entries.arcforgelabs-field.config.origin https://field.example.com
openclaw mcp set field '{"url":"https://field.example.com/mcp","transport":"streamable-http","auth":"oauth","oauth":{"scope":"catalog.read catalog.write quote.read quote.draft"},"toolFilter":{"include":["field_*"]}}'
openclaw mcp login field
```

Installing the package does not grant Field access. The operator must complete `openclaw mcp login field` in a browser against that origin. OpenClaw stores only its own OAuth credentials. There is no plugin token field.

`field_connection_status` prints the origin, MCP URL, and the exact set/login commands. It does not call Field.

Until a ClawHub release is confirmed, install from the packaged GitHub payload at `plugins/field/openclaw` in `arcforgelabs/agent-marketplace`.

## Tools after login

Read/calculation MCP tools: `field_quote_catalog_list`, `field_price_item_list`, `field_price_item_get`, `field_pricing_review`, `field_markup_preview`, `field_catalog_structure`, `field_quote_list`, `field_quote_get`, `field_quote_validate`.

Optional mutation tools need matching Field scopes plus `apply: true`, `confirmation: "APPLY"`, and a fresh `expectedVersion`: `field_price_item_update`, `field_catalog_structure_update`, `field_quote_draft_create`, `field_quote_draft_update`, `field_quote_recalculate`.

There is no send, email, publish, issue, invoice, payment, or acceptance tool.

## Hard boundary

Field remains the quoting authority. This plugin does not read Field SQLite files or invent endpoints. Do not interpret “send” or “publish” as permission to use another tool.
