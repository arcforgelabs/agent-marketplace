# Multi-business (profiles)

Run several dedicated businesses through one Xero connector without their
auth/tenant state colliding.

## The problem it solves

A single Xero token store holds one **active tenant** — a global pointer set by
`xero tenants use`. With two live businesses sharing one store, every tool call
targets whichever tenant was selected last. Nothing infers "the business this
task needs": a forgotten `tenants use` posts invoices, payments, or journals to
the **wrong legal entity**, silently.

Profiles remove the shared pointer. Each business gets its **own token store**,
so there is no global switch to forget. When more than one business is
registered, the aggregator also **namespaces every tool** by business, so a tool
literally named `newco__create-invoice` cannot hit Arc Forge.

## What is isolated vs shared

The same Xero *app* (OAuth client id) backs every business — you connect each
business's organisation to that one app, into separate token stores. So:

| State | Scope | Why |
|---|---|---|
| `token_store` (`XERO_TOKEN_STORE`) | **per business** | different orgs / active tenants |
| per-tenant rate-governor + day-limit files | **per business** | independent call budgets |
| token-store encryption key | shared | one key decrypts all stores |
| app-minute budget (`…SHARED_RATE_LIMIT_STORE`) | shared | the 10k/min limit is app-wide |
| OAuth app / client id | global (not pinned) | same Xero app for all businesses; resolved by the connector's own fall-through chain (env → `~/.config` → repo plugin `oauth-app.json`), not a per-profile path |

Legacy business state lives at the original paths
(`~/.config/arc-forge-tools/xero/…`). Each additional business lives under
`~/.config/arc-forge-tools/xero/businesses/<key>/`.

## Zero-config default

With **no registry file** the connector behaves exactly as the original
single-business setup: the legacy default paths, unprefixed tool names, nothing
moved. Multi-business is strictly opt-in by creating the registry.

## The registry

`~/.config/arc-forge-tools/xero/businesses.json` (override with
`ARC_FORGE_XERO_BUSINESS_REGISTRY`):

```json
{
  "version": 1,
  "businesses": [
    { "key": "arcforge", "label": "Arc Forge", "legacy": true },
    { "key": "newco", "label": "New Co Pty Ltd" }
  ]
}
```

- `key` — slug `[a-z0-9-]`, also the MCP tool-name prefix.
- `legacy` — at most one; maps the business to the existing legacy paths so the
  current Arc Forge connection is reused untouched.
- `root` / `paths` — optional directory or per-field path overrides.

## CLI

```
xero profiles list                                  # registered businesses + token state
xero profiles add --key arcforge --label "Arc Forge" --legacy
xero profiles add --key newco --label "New Co Pty Ltd"
xero --profile newco profiles show                  # resolved paths + env overlay
xero --profile newco auth login                     # connect/operate that business
xero --profile newco tenants list
xero profiles remove --key newco                    # leaves token files on disk
```

`-p/--profile` (or `XERO_PROFILE`) pins every path-resolving env var to that
business before the command runs; an explicit `--store` still wins. With no
`--profile` and a legacy entry present, commands target the legacy business, so
existing habits keep working.

## Aggregator namespacing rule

`xero_mcp.py` builds an `xero-official` + `xero-workflows` backend pair per
business, each with that business's env overlay. The official Node server reads
the right store because it authenticates by shelling out to `xero auth token`
with its own environment (`XERO_TOKEN_STORE`).

- **One business** (or no registry) → tool names stay **bare**
  (`create-invoice`) for backwards compatibility.
- **Two or more businesses** → **every** tool is prefixed (`arcforge__…`,
  `newco__…`) and its description is tagged with the business label. No bare,
  ambiguous tool name can exist. `xero_backends` stays unprefixed and reports
  the grouping.

## Onboard a new business

1. Create/subscribe the business as a Xero organisation (its own subscription).
2. `xero profiles add --key arcforge --label "Arc Forge" --legacy` (once, to
   capture the existing connection) then
   `xero profiles add --key <new> --label "<Name>"`.
3. `xero --profile <new> auth login` — on the consent screen grant the new org.
4. `xero --profile <new> tenants list` to confirm, then operate with
   `--profile <new>` (CLI) or the `<new>__…` tools (MCP).

See also [`plugin-architecture.md`](plugin-architecture.md) for the aggregator
and local-token-provider design.
