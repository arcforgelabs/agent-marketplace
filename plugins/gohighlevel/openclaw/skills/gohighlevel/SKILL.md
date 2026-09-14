---
name: gohighlevel
description: "Operate GoHighLevel / HighLevel CRM through the OpenClaw plugin: contacts, conversations, opportunities, calendars, workflows."
---

# GoHighLevel

Use this plugin to operate **one** HighLevel sub-account through API v2.

Unofficial integration by Arc Forge Labs; not affiliated with or endorsed by HighLevel.
This plugin talks directly to `https://services.leadconnectorhq.com`.

## Account context

Public packages contain a blank template only, never a customer profile.
If account-specific guidance is wanted, copy `ACCOUNT.template.md` beside this
skill to a private, operator-selected workspace file (for example
`ghl-account.md`). Never overwrite an existing profile. Record its location ID
and verify it matches plugin configuration before using any mappings or rules.
Do not discover or load other customers' profiles. Fill only facts observed in
tools or confirmed by the operator; unknowns stay blank.

Profiles may contain stable pipeline/field/calendar mappings and business
conventions. Credentials remain in the host credential store; customer records,
messages and attachments remain in HighLevel. Do not store either in profiles.
Profiles are outside the installed plugin and survive plugin upgrades.
No profile is necessary for generic help. Discover live IDs instead of guessing.

## Auth

- Sub-account **Private Integration Token** (PIT), stored as a SecretRef on
  `plugins.entries.arcforgelabs-gohighlevel.config.privateIntegrationToken`.
- `locationId` is plugin config, not a secret.
- Create the PIT **inside the sub-account**, not at agency level. An agency PIT
  cannot access CRM data.
- Header contract: `Authorization: Bearer <token>`, `Version: 2021-07-28`,
  identifying `User-Agent`.

The default is full operation support. Grant the following scopes for the
complete toolset; the PIT remains the provider-enforced account boundary.

Default PIT scopes:

- `contacts.readonly` + `contacts.write`
- `conversations.readonly` + `conversations.write`
- `conversations/message.readonly` + `conversations/message.write`
- `opportunities.readonly` + `opportunities.write`
- `calendars.readonly` + `calendars.write`
- `calendars/events.readonly` + `calendars/events.write`
- `locations.readonly`
- `locations/customFields.readonly` + `locations/customFields.write`
- `locations/tags.readonly` + `locations/tags.write`
- `workflows.readonly`
- `users.readonly`

Use HighLevel’s current token-rotation procedure when rotating credentials.

## Tools

Location-scoped requests use the configured `locationId`; by-ID operations rely
on the sub-account PIT for provider-enforced account authorization.

| Tool | Use for |
| --- | --- |
| `ghl_status` | Connectivity and location name |
| `ghl_contacts` | search / get / upsert / update / tags / delete |
| `ghl_notes` | contact notes |
| `ghl_tasks` | contact tasks |
| `ghl_conversations` | conversation search and message history |
| `ghl_messages` | send SMS/email; call recording/transcription |
| `ghl_opportunities` | search / get / create / update |
| `ghl_pipelines` | list / create |
| `ghl_custom_fields` | list / create |
| `ghl_calendars` | calendars, free slots, appointments |
| `ghl_workflows` | list / enroll / unenroll |
| `ghl_users` | assignees |
| `ghl_tags` | location tag list |

There is no generic HTTP tool. Do not try to hit arbitrary URLs.

## Operating rules

- **Upsert** contacts (`ghl_contacts` action `upsert`). It dedupes by email/phone.
- Creating an opportunity is **not** idempotent. Search first; a returning
  person at a new job is a new opportunity, not a new contact.
- After create/update, search indexes can lag for a minute. Confirm with get-by-id,
  never with an empty search.
- Opportunity `opportunityStatus` is `open`, `won`, `lost`, or `abandoned`.
  Abandoned = fizzled / out of scope. Lost = genuinely lost on merit.
  Confirm current API support before changing native lost-reason fields; use
  operator-agreed tags when the native field is unavailable.
- This plugin supports workflow listing/enrollment, not workflow construction.
- Search lag: do not delete or recreate because search looks empty.
- Fictional example only: searching `Alex Citizen` at **Acme Landscaping** is a
  shape, not a real account.

## CLI

The bundled CLI uses the same operations as native tools:
`node <plugin-root>/lib/cli.js contacts '{"action":"search","query":"Alex Example"}'`.
Use `--help` for groups. It accepts `GHL_TOKEN`, `GHL_LOCATION_ID`, and optional
`GHL_TIMEZONE` from an operator-configured environment. Never pass tokens in
command arguments or ask for them in chat. Do not copy credentials out of a
host store merely to use the CLI; use native tools when the host owns the PIT.

## Outbound messages

`ghl_messages` action `send` can send SMS and email. That is live customer
communication. Use it when the operator wants the claw to act, not as a demo.
Do not dump recordings or full email HTML into logs.

## What this plugin does not do

- Agency provisioning (create/delete locations, snapshots, SaaS billing).
- Building workflows, lost-reason picklists, or Meta field mapping via API.
- Browser automation of app.gohighlevel.com. API first.
