# HubSpot by Arc Forge

Unofficial HubSpot integration maintained by Arc Forge Labs; not affiliated with or endorsed by HubSpot, Inc.

`openclaw plugins install` copies the package. It does **not** accept a SecretRef
object, JSON token, or `--config` flag. Noninteractive installs from this GitHub
path require `--force` and `--accept-capabilities`. Wire the token afterwards
with SecretRef builder mode — never as a positional string.

```sh
export OPENCLAW_CONFIG_PATH=/path/to/openclaw.json5
openclaw plugins install /absolute/path/to/package \
  --force --accept-capabilities --acknowledge-install-policy-warning
openclaw config set plugins.entries.arcforgelabs-hubspot.config.accessToken \
  --ref-source store --ref-provider default --ref-id HUBSPOT_TOKEN
openclaw plugins enable arcforgelabs-hubspot --accept-capabilities
```

Collect `HUBSPOT_TOKEN` with the Gateway protected acceptor (`source: store`,
host `api.hubapi.com`) before `config set`. `env`/`file`/`exec` remain valid
schema sources. A schema that omits `store` is a release blocker.

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
No customer write is used as a release test. Requires OpenClaw 2026.9.3 or newer; no upper bound.

## Development

```sh
npm install
npm test
npm run build
npm run plugin:validate
```
