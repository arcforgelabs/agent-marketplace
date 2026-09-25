---
name: deputy
description: "Operate Deputy payroll/workforce through the OpenClaw plugin: timesheets, leave, rosters; API gaps."
---

# Deputy

Use this plugin to operate **one** Deputy install through the public REST API.

Unofficial integration by Arc Forge Labs; not affiliated with or endorsed by Deputy.
This plugin talks only to `https://{installHost}/api`. Do not wrap community MCP
servers, implement OAuth/PKCE, or call arbitrary URLs.

## Account context

Public packages contain a blank template only, never a customer profile.
If account-specific guidance is wanted, copy `ACCOUNT.template.md` beside this
skill to a private, operator-selected workspace file (for example `deputy-account.md`).
Never overwrite an existing profile. Record the install host from plugin config
and verify `deputy_status` before using any mappings.
Fill only facts observed in tools or confirmed by the operator; unknowns stay blank.
Credentials remain in the host credential store. Do not store employee records here.

Fictional examples only: “Northwind Clinics”, install `northwind.au.deputy.com`,
employee `101`.

## Install (OpenClaw)

Tenant `installHost` and the token are **per Gateway**. Do not put them in this
skill, git, or chat. This skill is the generic install/operate pattern only.

Trusted updates come from ClawHub (`clawhub:@arcforgelabs/openclaw-deputy@<version>`)
or the public `agent-marketplace` tag `deputy-v<version>`. A path overlay from an
`arc-forge-tools` checkout is a one-shot, not the update lane.

1. On the **owning** Gateway, store a protected secret named `DEPUTY_API_TOKEN`.
   Leave **Allowed hosts empty**. That field is HTTP egress substitution only; filling
   it can leave the plugin seeing an unresolved SecretRef object instead of a token.
   Never paste the token into chat, git, or argv.
2. Get the token as an admin on that Deputy install:
   `https://{install}.{geo}.deputy.com/exec/devapp/oauth_clients`.
   The list page has no token. Open an existing OAuth client (or **New OAuth Client**;
   Redirect URI `http://localhost` is required even though this plugin does not use
   OAuth) → **Get an Access Token**. Shown once. Reuse a stored token if you already
   have one for that client.
3. Install the package. `openclaw plugins install` copies code only; it does not
   accept a SecretRef or token. When ClawHub search shows the intended `latestVersion`:

   ```sh
   openclaw plugins install clawhub:@arcforgelabs/openclaw-deputy@0.1.0
   ```

   No `--force` on a clean ClawHub version. GitHub-tag fallback: install
   `plugins/deputy/openclaw` from `agent-marketplace` tag `deputy-v0.1.0` with
   `--force --accept-capabilities --acknowledge-install-policy-warning`.
   If load fails with missing `typebox`, in the extension directory run
   `npm install --omit=dev --omit=peer`. Do not install the OpenClaw peer there.
4. Write **both** required config fields in one shot (setting them separately fails
   validation), then enable:

   ```sh
   openclaw config set plugins.entries.arcforgelabs-deputy.config --strict-json '{
     "installHost": "northwind.au.deputy.com",
     "apiToken": {"source":"store","provider":"default","id":"DEPUTY_API_TOKEN"}
   }'
   openclaw plugins enable arcforgelabs-deputy --accept-capabilities
   ```

   `installHost` is the hostname in the browser bar (`{name}.{au|eu|uk|us|na}.deputy.com`).
   No scheme, path, port, or `once.deputy.com`. Never pass a JSON SecretRef as a
   positional `config set` value for the token field alone.
5. Grant tools once, not by copying every tool name:

   ```json5
   { tools: { alsoAllow: ["arcforgelabs-deputy"] } }
   ```

   Sandboxed sessions need the same id under `tools.sandbox.tools.alsoAllow`.
   Prove in a **fresh** session.
6. If `deputy_status` reports an unresolved SecretRef after the store entry exists,
   recycle the Gateway process so plugin config is rematerialized. Plugin *config*
   hot-reloads; first package install still often needs a process restart.

## Auth

- Permanent token as above. SecretRef on
  `plugins.entries.arcforgelabs-deputy.config.apiToken` with `source` one of
  `env` / `file` / `exec` / **`store`**. Omitting `store` is a release blocker.
- `installHost` is plugin config, not a secret and not this skill. Example:
  `northwind.au.deputy.com`.
- Header contract: `Authorization: Bearer <token>`, identifying `User-Agent`.
- OAuth2 / `once.deputy.com` exists on the vendor; this plugin does **not** implement it.

## Rate limit

Deputy does **not** publish a numeric vendor rate limit. Honour `retry-after` and
`x-ratelimit-*` when present.

This plugin’s local governor defaults to **60/min** (hard-capped at 120), FIFO so
parallel tools cannot stampede, and header-authoritative remaining when sent.
GET/HEAD may retry **once** after 429. **Writes are never auto-retried.**
Do not parallel-spray list calls. Check `deputy_status` for remaining/queued/last 429.

## Tools

Mutating calls need an explicit `action`. There is no default write.

| Tool | Class | Notes |
| --- | --- | --- |
| `deputy_status` | GET-only | `/v1/me`, `/v1/resource/Company`, governor snapshot |
| `deputy_employees` | writable | list/get/create/update, terminate/reactivate/invite, add/remove company, QUERY |
| `deputy_timesheets` | writable | QUERY plus start/end/pause/approve/discard/update |
| `deputy_leave` | writable | QUERY, get, supervise create, leave-by-employee |
| `deputy_rosters` | writable | QUERY, 12h/36h list, get, copy/publish/discard |
| `deputy_locations` | writable | Company list/get/create/update/archive; delete omitted |
| `deputy_areas` | writable | OperationalUnit list/QUERY/create/update/delete |
| `deputy_pay` | GET-only | TimesheetPayReturn, EmployeePaycycle, EmployeeAgreement, PayPeriod |

IDs are digits-only. QUERY `max` defaults to 100 and is capped at 500.

## Hard API gaps (not plugin backlog)

The product has modules this plugin does **not** expose. Do not invent tools for them.

- No official Deputy MCP
- OAuth2 / `once.deputy.com` (not implemented)
- Deputy Embed partner APIs
- Advanced Employee confidential/TFN API
- DeXML
- Inbound webhook listener
- POS sales metrics
- Employee self-service “me” newsfeed/tasks/training
- V2 Management API except a payroll guide’s agreed-hours path (named gap; prefer V1 supervise + resource QUERY)
- Pay rule / agreement writes (payroll identity and rate mutation)

Closest substitutes: **terminate** instead of deleting an employee account;
**archive** instead of destroying a location.

## CLI

`deputy <group> [JSON]`. Groups match the tools without the `deputy_` prefix
(`status`, `employees`, `timesheets`, …). Token from `DEPUTY_API_TOKEN` and host
from `DEPUTY_INSTALL_HOST`, never argv. JSON stdout only.

## Proof

Use `deputy_status` as the read-only probe. Do not create or mutate live
timesheets, employees, leave, or rosters as a smoke test.
