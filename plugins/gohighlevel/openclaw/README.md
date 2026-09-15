# GoHighLevel by Arc Forge

Unofficial HighLevel integration for OpenClaw. Independently developed by Arc Forge Labs; not affiliated with or endorsed by HighLevel.

## Package

- Package: `@arcforgelabs/openclaw-gohighlevel`
- Native plugin ID: `arcforgelabs-gohighlevel`
- Skill: `gohighlevel`; tools: `ghl_*`
- One sub-account PIT; full supported read/write operations. No agency provisioning.
- Tested hosts: OpenClaw 2026.9.3 and 2026.9.4. Other host versions are not yet verified.

## Install

Until a ClawHub release is confirmed, install the packaged GitHub release artifact or a local copy of this directory:

```sh
openclaw plugins install /absolute/path/to/package
```

Review and accept the declared capabilities using the normal installer. Configure
`plugins.entries.arcforgelabs-gohighlevel.config` with your location ID and a
host-managed SecretRef for `privateIntegrationToken`. Example source configuration:

```json
{
  "locationId": "YOUR_LOCATION_ID",
  "privateIntegrationToken": {"source":"store","provider":"default","id":"GHL_TOKEN"}
}
```

`source` must accept `env`, `file`, `exec`, and `store`. One-shot Gateway installs
use the protected `store` acceptor; omitting `store` is a release blocker.
Supply that id through the Gateway's supported protected setup, not chat,
source control, command arguments or a public profile. An unresolved reference
fails closed. `timezone` is optional with no regional default; use explicit UTC
offsets in appointment timestamps. Enable the plugin, restart the target Gateway
if the installer requires it, and verify `ghl_status` against the intended account.
A valid sub-account PIT must grant the scopes listed in the bundled skill.

Installing the package does not create a token or grant API access. Existing
installations of the old unpublished `gohighlevel` prototype must migrate the
configuration to the new ID and disable the old plugin; do not enable both.

## CLI

The package includes `lib/cli.js`, backed by the same operations as native tools:

```sh
node lib/cli.js --help
node lib/cli.js contacts '{"action":"search","query":"Alex Example"}'
```

The CLI receives `GHL_TOKEN`, `GHL_LOCATION_ID`, and optional `GHL_TIMEZONE` from
the operator-configured environment. `-` reads operation JSON from stdin.
No credentials on argv. Native OpenClaw tools use the host's resolved SecretRef.

## Account context

Only `skills/gohighlevel/ACCOUNT.template.md` ships. A populated profile belongs
outside the installed package in an authorised private workspace, explicitly
selected for the matching location. Profiles hold stable mappings and rules,
not credentials or customer records. Installation and updates do not create,
overwrite or fetch a populated profile. No client workflows are seeded.

## Behavior and scope

Contacts, notes, tasks, conversations, messages, opportunities, pipelines,
custom fields, calendars, workflow enrollment, users and tags are supported.
By-ID authorization is enforced by HighLevel's sub-account PIT, not by trusting
model-supplied location IDs. There is no arbitrary HTTP tool.

Writes execute when invoked; they are not silently converted to dry runs.
Ambiguous failures are not retried automatically for writes. Verify provider
state before retrying a send/create. Reads use bounded retries and a 30-second
request deadline. Redirects are refused. No background polling or telemetry.
API records returned to the host are subject to that host's transcript policy.

Offline tests and native manifest validation are included. No live customer
write was used as a release test; live PIT connectivity remains an installation
acceptance step. Recording responses are currently returned as API data; binary
media delivery is not implemented.

## Development

Source is maintained in Arc Forge Tools and assembled for this public catalog.
The package contains its TypeScript source and compiled runtime; it does not
reference sibling folders at runtime. Use the tested OpenClaw SDK, TypeScript
and TypeBox dependencies to build and run `npm test` / `npm run plugin:validate`.
Release assembly: `python3 scripts/stage-release.py --output <new-directory>`
from the development source checkout (the assembler is not a runtime file).
