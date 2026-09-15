# HubSpot by Arc Forge

Unofficial HubSpot integration maintained by Arc Forge Labs; not affiliated with or endorsed by HubSpot, Inc.

Install this directory with `openclaw plugins install /absolute/path/to/package` and configure
`plugins.entries.arcforgelabs-hubspot.config` with a host-managed SecretRef:

```json
{"accessToken":{"source":"store","provider":"default","id":"HUBSPOT_TOKEN"}}
```

`source` must accept `env`, `file`, `exec`, and `store`. One-shot Gateway installs use the protected `store` acceptor; omitting `store` rejects that credential.

The optional `portalId` pins operator context and `timezone` is validated when supplied; no regional
timezone is assumed. The CLI is backed by the same implementation:

```sh
node lib/cli.js --help
node lib/cli.js contacts '{"action":"search","query":"Alex Example"}'
```

CLI environment: `HUBSPOT_TOKEN` (required), optional `HUBSPOT_PORTAL_ID` and `HUBSPOT_TIMEZONE`.
Never pass credentials as arguments. Only the blank `ACCOUNT.template.md` ships; populated account
profiles belong in a private authorised workspace.

The tools perform live writes when invoked. Reads retry bounded 429/5xx responses; writes do not auto-retry.
No customer write is used as a release test. Tested against OpenClaw 2026.9.3–2026.9.4.

## Development

```sh
npm install
npm test
npm run build
npm run plugin:validate
```
