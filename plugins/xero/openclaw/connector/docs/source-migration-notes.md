# Xero Source Migration Notes

Last updated: 2026-06-06.

Reviewed sources:

- `~/repos/MCP/xero-mcp`
- `~/repos/SKILLS/using-xero/SKILL.md`
- `components/mcp/xero`
- `components/skills/xero` (renamed from `components/skills/using-xero`)
- `~/repos/lab-flow/server/src/xero`
- `~/repos/lab-flow/docs/adrs/0012-xero-draft-writer-boundary.md`
- `XeroAPI/xero-mcp-server`

## Source Assessment

`~/repos/MCP/xero-mcp` and the copied `components/mcp/xero` source contain a
working Python FastMCP server for the Xero Accounting API. It includes tools for
accounts, contacts, invoices, bank transactions, expenses, and reports, plus
OAuth token management and browser reconciliation scripts.

The Python source should not become the new core unchanged because it mixes:

- generic Xero API connector code
- MCP harness exposure
- OAuth helper scripts
- local credential workflow assumptions
- Arc Forge-specific bookkeeping context in `src/tools/arc_forge_context.py`
- browser-based reconciliation automation

The official Xero MCP server now exists under `XeroAPI/xero-mcp-server` and is
published as `@xeroapi/xero-mcp-server`. It is the preferred API foundation
because it tracks Xero's public MCP direction and uses the official
`xero-node` SDK. It is not sufficient by itself for the target product because
it expects either Custom Connection client credentials or an externally supplied
bearer token. The target product requires users to sign in with their own Xero
account without bringing developer credentials.

Lab Flow is the implementation precedent for rate-limit and audit design, not a
source to copy wholesale. The reusable lessons are:

- pre-dispatch rate governor
- app-wide and per-tenant buckets
- DayLimit circuit breaker
- FIFO operation lock for heavy Xero operations
- targeted live reads instead of full invoice-history sweeps
- dedup and dry-run reporting before writes
- naming/mapping rules that improve over time

## Migration Split

Recommended target shape:

- `connectors/xero/src/`: official MCP wrapper/fork, local token provider, rate
  governor, and reusable Xero client helpers.
- `connectors/xero/cli/`: PKCE login, token refresh, tenant selection, smoke
  checks, snapshots, dry-runs, and diagnostics.
- `connectors/xero/finance-rules/`: reusable rule schema and generic mapping,
  dedup, and report helpers.
- `connectors/xero/reconciliation/`: optional CDP finalizer that attaches to an
  already authenticated browser session.
- `connectors/xero/docs/`: plugin architecture, API/CDP map, auth setup, rate
  limits, support boundary, and migration notes.
- `components/skills/xero/`: generic agent skill component pointing at
  the connector tools.

Keep out of the generic Connector:

- private organization-specific chart-of-accounts mappings
- tax treatment rules for a specific business
- project-specific reconciliation plans
- local secret item names as defaults
- browser profiles, tokens, cookies, and generated runtime state
- login automation, MFA retrieval, or security-control bypass logic

## Next Step

Implement the first core MVP slice:

1. `[done]` Add a local CLI with `xero auth login`, `xero auth status`, and tenant
   selection.
2. `[prototype]` Implement OAuth Code + PKCE against the Arc Forge-owned Xero app.
3. `[done]` Add a local token-store abstraction with redaction tests.
4. `[prototype]` Wrap/fork the official MCP client so it obtains bearer tokens and tenant IDs
   from the local token provider.
5. `[prototype]` Port the Lab Flow rate governor shape before large write/batch
   tools are treated as production-ready. The wrapper has in-process
   pre-dispatch limits, visible status, and a JSON-backed FIFO operation lock;
   safe header observation and bounded one-shot Retry-After behavior exist in
   the prototype. Live tenant smoke remains planned.
6. `[prototype]` Extract the first generic audit layer: local finance-rules
   template, parser/mapping helpers, snapshot duplicate checks, and dry-run proof
   reports. Targeted live-check commands and guarded reconciliation pre-work
   creates exist for payments, bank transactions, bank transfers, and manual
   journals. Authenticated tenant smoke and broader live write flows remain
   planned. Redacted local apply-report ledger commands exist for mutation
   results.
