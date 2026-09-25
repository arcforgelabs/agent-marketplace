# Deputy by Arc Forge

Unofficial Deputy integration for OpenClaw. Independently developed by Arc Forge Labs; not affiliated with or endorsed by Deputy.

## Package

- Package: `@arcforgelabs/openclaw-deputy`
- Native plugin ID: `arcforgelabs-deputy`
- Skill: `deputy`; tools: `deputy_*`
- Permanent Bearer token; official REST at `https://{install}.{geo}.deputy.com/api`
- Requires OpenClaw 2026.9.3 or newer. No upper bound; newer Gateways stay loadable.

## Install

Trusted updates: ClawHub `clawhub:@arcforgelabs/openclaw-deputy@<version>` or the
public `agent-marketplace` tag `deputy-v<version>`. A path overlay from an
`arc-forge-tools` checkout is not the update lane.

Store `DEPUTY_API_TOKEN` as a protected secret on the **owning** Gateway. Leave
Allowed hosts empty so the plugin config SecretRef resolves in-process. Token
comes from `{install}.{geo}.deputy.com/exec/devapp/oauth_clients` → client
detail → Get an Access Token (shown once). Never put it in chat, git, or argv.

```sh
openclaw plugins install clawhub:@arcforgelabs/openclaw-deputy@0.1.1
openclaw config set plugins.entries.arcforgelabs-deputy.config --strict-json '{
  "installHost": "northwind.au.deputy.com",
  "apiToken": {"source":"store","provider":"default","id":"DEPUTY_API_TOKEN"}
}'
openclaw plugins enable arcforgelabs-deputy --accept-capabilities
```

Use `--force --accept-capabilities --acknowledge-install-policy-warning` only for
a GitHub-tag / local-path fallback. `plugins install` copies the package; it does
**not** accept a SecretRef. Set `installHost` and `apiToken` together (both are
required). `installHost` is tenant host only, for example `northwind.au.deputy.com`.
Optional: `maxRequestsPerMinute` (default 60, hard-capped at 120) and `timezone`.

If load fails with missing `typebox`, run `npm install --omit=dev --omit=peer` in
the extension directory (do not install the OpenClaw peer). If `deputy_status`
reports an unresolved SecretRef after the store entry exists, recycle the Gateway
process so plugin config rematerializes.

Prove with `deputy_status`. Do not mutate live timesheets, employees, leave, or
rosters as a smoke test. Bundled skill `deputy` has the full generic sequence.

## Tool availability

Deputy tools opt into OpenClaw's `coding` and `full` tool profiles. Explicit
operator allowlists and deny rules still win. If an older package or a narrower
profile hides the tools, grant the plugin once instead of copying every current
tool name:

```json5
{
  tools: {
    profile: "coding",
    alsoAllow: ["arcforgelabs-deputy"],
  },
}
```

For a single agent, put the same `alsoAllow` entry under that agent's `tools`
block. Sandboxed sessions have an independent gate; add
`arcforgelabs-deputy` to `tools.sandbox.tools.alsoAllow` when sandboxing is
enabled. Start a fresh session and prove availability with the read-only
`deputy_status` tool after changing policy.

## Rate limit

Deputy does **not** publish a numeric vendor rate limit. This plugin queues
locally at 60/min by default (hard-capped at 120), honours `x-ratelimit-*` /
`retry-after` when present, retries GET 429 once, and never auto-retries writes.

## CLI

```sh
node lib/cli.js --help
node lib/cli.js employees '{"action":"list"}'
```

The CLI reads `DEPUTY_API_TOKEN` and `DEPUTY_INSTALL_HOST`, plus optional
`DEPUTY_MAX_REQUESTS_PER_MINUTE` and `DEPUTY_TIMEZONE` from the environment.
No credentials on argv. JSON stdout only.

## Account context

Only `skills/deputy/ACCOUNT.template.md` ships. A populated profile belongs
outside the installed package. No client workflows are seeded.

## Scope

Official V1 supervise + resource QUERY payroll/workforce surface. Hard vendor
gaps: no official Deputy MCP, OAuth2 / once.deputy.com, Embed partner APIs,
Advanced Employee confidential/TFN API, DeXML, inbound webhook listener, POS
sales metrics, employee self-service newsfeed/tasks/training, and V2 Management
except as a named gap. See the bundled skill.
