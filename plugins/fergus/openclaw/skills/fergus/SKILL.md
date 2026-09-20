---
name: fergus
description: "Operate Fergus job management through the OpenClaw plugin: jobs, quotes, calendar, customers, files; API gaps."
---

# Fergus

Use this plugin to operate **one** Fergus company through the public REST API.

Unofficial integration by Arc Forge Labs; not affiliated with or endorsed by Fergus.
This plugin talks only to `https://api.fergus.com`. Do not wrap community MCP servers
or call arbitrary URLs.

## Account context

Public packages contain a blank template only, never a customer profile.
If account-specific guidance is wanted, copy `ACCOUNT.template.md` beside this
skill to a private, operator-selected workspace file (for example `fergus-account.md`).
Never overwrite an existing profile. Record the company guid from `fergus_status`
and verify it matches plugin configuration before using any mappings.
Fill only facts observed in tools or confirmed by the operator; unknowns stay blank.
Credentials remain in the host credential store. Do not store customer records here.

Fictional examples only: “Northwind Plumbing”, job `1001`, quote version `1`.

## Auth

- Company **Personal Access Token** from Fergus account settings, stored as a
  SecretRef on `plugins.entries.arcforgelabs-fergus.config.apiToken`.
  One-shot installs use `{"source":"store","provider":"default","id":"FERGUS_API_TOKEN"}`.
  `env` / `file` / `exec` remain valid. Omitting `store` is a release blocker.
- Optional `companyId` is plugin config, not a secret. When set, `fergus_status`
  checks it against `GET /company`.
- Header contract: `Authorization: Bearer <token>`, identifying `User-Agent`.
- OAuth2 exists on the vendor spec; this plugin does **not** implement it.

## Rate limit

Fergus enforces **100 requests per minute per company**, shared across tokens and
endpoints. Headers: `x-ratelimit-limit`, `x-ratelimit-remaining`,
`x-ratelimit-reset`, plus `retry-after` on 429.

This plugin’s local governor defaults to **80/min** (hard-capped at 100), FIFO so
parallel tools cannot stampede the budget, and header-authoritative remaining.
GET/HEAD may retry **once** after 429. **Writes are never auto-retried.**
Do not parallel-spray list calls. Check `fergus_status` for remaining/queued/last 429.

## Tools

Mutating calls need an explicit `action`. There is no default write.

| Tool | Writable | Notes |
| --- | --- | --- |
| `fergus_status` | no | `/version`, `/users/me`, `/company`, governor snapshot |
| `fergus_jobs` | yes | create/update/finalise/hold/resume, phases, financials |
| `fergus_quotes` | yes | create/update/version, publish, send/viewed, accept, decline, void, totals |
| `fergus_calendar` | yes | events; update is POST; types JOB_PHASE/QUOTE/ESTIMATE/OTHER |
| `fergus_customers` | yes | including delete |
| `fergus_sites` | yes | including archive/restore |
| `fergus_contacts` | yes | create/update |
| `fergus_users` | yes | list/me/get/update |
| `fergus_notes` | yes | entities: job, customer, customer_invoice, quote, site, task, enquiry, works_order |
| `fergus_tasks` | yes | including complete/reopen |
| `fergus_files` | yes* | upload/delete on customer/job/site/enquiry/job_phase. Upload accepts base64 content, never host file paths. `form` and `certificate` are list+download only. Max 20MB. Download returns a short-lived URL; do not cache. |
| `fergus_enquiries` | yes | create/list/get |
| `fergus_invoices` | no | GET `/customerInvoices` only |
| `fergus_time` | no | GET `/timeEntries` only |
| `fergus_stock` | mixed | stock-on-hand writes; `/stockUsed` read |
| `fergus_pricebooks` | no | search/list/items plus pricing tiers |
| `fergus_favourites` | no | GET sections/folders only |

`POST /disconnect` is omitted from tools.

Job types: `Quote`, `Estimate`, `Charge Up`. Calendar update uses POST, not PUT.
Finalise spelling is `finalise`.

## Hard API gaps (not plugin backlog)

The product has modules this API does **not** expose. Do not invent tools for them.

- Fergus Assistant chat and customer SMS
- Health & Safety product: SWMS, incidents, hazards, toolbox talks
- Creating or sending invoices
- Creating time entries
- Writing favourites / price books
- Webhooks (none in the spec)

Closest substitutes: **notes** for team comms; **files** on a job/site for documents;
`form`/`certificate` attachments may be some PDFs, not the H&S module.

## CLI

`fergus <group> [JSON]`. Groups match the tools without the `fergus_` prefix
(`status`, `jobs`, `quotes`, …). Token from `FERGUS_API_TOKEN`, never argv.
JSON stdout only.

## Proof

Use `fergus_status` as the read-only probe. Do not create or mutate live jobs,
quotes, customers, or files as a smoke test.
