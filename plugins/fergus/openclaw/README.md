# Fergus by Arc Forge

Unofficial Fergus integration for OpenClaw. Independently developed by Arc Forge Labs; not affiliated with or endorsed by Fergus.

## Package

- Package: `@arcforgelabs/openclaw-fergus`
- Native plugin ID: `arcforgelabs-fergus`
- Skill: `fergus`; tools: `fergus_*`
- Company Personal Access Token (PAT); official REST at `https://api.fergus.com`
- Tested hosts: OpenClaw 2026.9.3 and 2026.9.4. Other host versions are not yet verified.

## Install

Until a ClawHub release is confirmed, install a local copy of this directory:

```sh
export OPENCLAW_CONFIG_PATH=/path/to/openclaw.json5
openclaw plugins install /absolute/path/to/package \
  --force --accept-capabilities --acknowledge-install-policy-warning
openclaw config set plugins.entries.arcforgelabs-fergus.config.apiToken \
  --ref-source store --ref-provider default --ref-id FERGUS_API_TOKEN
openclaw plugins enable arcforgelabs-fergus --accept-capabilities
```

`openclaw plugins install` copies the package. It does **not** accept a SecretRef
object or token. Collect `FERGUS_API_TOKEN` with the Gateway protected acceptor
(`source: store`) before `config set`. `env`/`file`/`exec` remain valid. Omitting
`store` is a release blocker. Never put the PAT in chat, git, or argv.

Optional: `companyId` (guid from `GET /company`) and `maxRequestsPerMinute`
(default 80, hard-capped at 100).

Prove with `fergus_status`. Do not create live jobs, quotes, or files as a smoke test.

## Rate limit

Fergus allows 100 requests per minute per company, shared across tokens and
endpoints. This plugin queues locally at 80/min by default, honours
`x-ratelimit-*` / `retry-after`, retries GET 429 once, and never auto-retries writes.

## CLI

```sh
node lib/cli.js --help
node lib/cli.js jobs '{"action":"list","pageSize":5}'
```

The CLI reads `FERGUS_API_TOKEN` and optional `FERGUS_COMPANY_ID`,
`FERGUS_MAX_REQUESTS_PER_MINUTE`, `FERGUS_TIMEZONE` from the environment.
No credentials on argv. JSON stdout only.

## Account context

Only `skills/fergus/ACCOUNT.template.md` ships. A populated profile belongs
outside the installed package. No client workflows are seeded.

## Scope

Full official OpenAPI surface except `POST /disconnect` (omitted from tools).
Hard vendor gaps: in-app chat/SMS, Health & Safety module, invoice/time writes,
favourites writes, webhooks. See the bundled skill.
