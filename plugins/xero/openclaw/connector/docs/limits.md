# Xero API Limits

The connector must stay below Xero's published API limits and leave headroom for
manual Xero usage or other integrations.

## Published Limits

Verified against Xero Developer documentation on 2026-06-07.

Xero documents these main limits:

- Concurrent tenant limit: 5 calls in progress.
- Tenant minute limit: 60 calls per minute.
- Tenant daily limit: 5000 calls per day for Core and higher developer tiers.
- Tenant daily limit for Starter-tier apps: 1000 calls per day per organisation.
- App-wide minute limit: 10000 calls per minute.

Treat the published limits as ceilings, not operating targets. The connector's
default `ARC_FORGE_XERO_DAY_LIMIT=5000` assumes the Arc Forge OAuth app is not
on the Starter tier. If the app is on Starter, set
`ARC_FORGE_XERO_DAY_LIMIT=1000` before live use or package that lower limit in
the deployment environment.

## Local Guardrails

The official MCP wrapper injects an in-process SDK proxy with conservative
defaults:

- `ARC_FORGE_XERO_MAX_CONCURRENT=4`
- `ARC_FORGE_XERO_MAX_PER_MINUTE=55`
- `ARC_FORGE_XERO_DAY_LIMIT=5000`
- `ARC_FORGE_XERO_APP_MINUTE_LIMIT=10000`
- `ARC_FORGE_XERO_MAX_RETRY_SLEEP_MS=60000`

The wrapper writes status to:

```text
~/.config/arc-forge-tools/xero/rate-limit-status.json
```

Inspect it with:

```bash
connectors/xero/cli/xero rate status
```

The status snapshot includes the selected tenant ID when local auth has returned
one, the budget scope for the counters, and local budget counters:

- `tenant_id`
- `tenant_budget_scope`
- `in_flight`
- `minute_count`
- `day_count`
- `app_minute_count`
- `circuit_breaker`
- configured limits

After observed API responses, it also records the latest safe rate-limit headers
seen by the wrapper:
`X-DayLimit-Remaining`, `X-MinLimit-Remaining`, `X-AppMinLimit-Remaining`,
`X-Rate-Limit-Problem`, and `Retry-After`. The status snapshot also records a
bounded `last_observed_pressure` object with parsed remaining-count values.

If Xero reports `X-Rate-Limit-Problem: DayLimit` or
`X-DayLimit-Remaining <= 0`, the wrapper treats Xero as authoritative and opens
the local day-limit circuit even when the in-process `day_count` has not reached
the configured limit. This handles the Lab Flow failure mode where other
processes, manual usage, or an app-tier limit consume tenant budget outside the
current MCP process. On HTTP 429 responses with `Retry-After`, the wrapper
releases its local slot, sleeps up to `ARC_FORGE_XERO_MAX_RETRY_SLEEP_MS`, and
retries the SDK call once.

When the in-process `day_count` reaches `ARC_FORGE_XERO_DAY_LIMIT`, the wrapper
opens a day-limit circuit breaker and rejects queued calls instead of waiting
indefinitely. The status snapshot records whether the breaker is open, the UTC
reset time, and the local unblock-store path. An operator can explicitly unblock
the current UTC day only with:

```bash
connectors/xero/cli/xero rate unblock-day-limit \
  --holder <operator-or-workflow> \
  --reason <approval-context>
```

This writes `~/.config/arc-forge-tools/xero/rate-limit-unblock.json` with
`0600` permissions. Use it only after checking Xero tenant usage and confirming
that further API calls are acceptable.

The MCP bridge uses an in-process queue for per-process concurrency and a
JSON-backed shared budget file for cross-process tenant minute, tenant daily,
and app-wide minute accounting. Direct CLI helpers reserve from the same shared
budget before they call the Xero Accounting API, so MCP calls and CLI batch
workflows cannot silently exceed the combined tenant budget. The shared store
defaults to:

```text
~/.config/arc-forge-tools/xero/rate-limit-shared.json
```

Override it with `ARC_FORGE_XERO_SHARED_RATE_LIMIT_STORE` when a harness needs a
custom runtime directory. Continue to use the operation lock for heavy workflows
that should not overlap even when raw request budget is available.

Direct CLI helpers also write their own JSON-backed status snapshot after
reserving from the shared budget. This covers `xero reports`, `xero snapshots`,
`xero documents`, `xero reference`, `xero prework`, `xero evidence`, and live
audit checks whether they are called directly or through the `xero-workflows`
MCP companion.

The CLI governor writes:

```text
~/.config/arc-forge-tools/xero/rate-limit-cli-status.json
```

Inspect both MCP and CLI guardrail state with:

```bash
connectors/xero/cli/xero rate status --include-cli
```

The CLI governor is intentionally conservative and fail-fast: it records
per-tenant rolling-minute counts, per-tenant day counts, and app-wide
rolling-minute counts before dispatch. If Xero reports `DayLimit` pressure or
`X-DayLimit-Remaining <= 0`, it opens a local CLI day-limit circuit for that
tenant so later CLI/helper calls stop before consuming more budget.
Offline regression tests cover the main local gotchas: token/OAuth calls do not
consume Accounting API budget, tenant minute exhaustion and app-wide exhaustion
block before dispatch, Xero DayLimit pressure opens the local circuit, and
`rate status --include-cli` redacts nested secret-like fields.

## Heavy Operations

Catalog refreshes, large dry-runs, and future batch writes should acquire the
operation lock:

```bash
connectors/xero/cli/xero lock acquire --holder catalog-refresh --wait
connectors/xero/cli/xero lock release <lease-id>
```

This prevents concurrent local workflows from burning the same tenant budget.

## API Efficiency Rules

- Prefer targeted reference checks over full invoice sweeps.
- Use local reference snapshots for accounts, contacts, items, tax rates, and
  tracking categories.
- Batch when Xero supports batch create/update endpoints.
- Keep practical Accounting API batch payloads around 50 records or fewer, and
  stay below Xero's request-size ceilings.
- Dry-run before writes.
- Record apply reports for created, updated, skipped, and failed outcomes.
- Watch for 429 responses and `Retry-After` headers.

## Remaining Hardening

Planned governor work:

- Add live tenant smoke coverage for remaining-limit header observation.
- Add deeper SDK queue behavior tests.
- Add live multi-process contention smoke when a connected tenant is available.

## Official References

- Xero limits FAQ: <https://developer.xero.com/faq/limits>
- Xero rate limits guide: <https://developer.xero.com/documentation/best-practices/api-call-efficiencies/rate-limits/>
- Xero pricing and usage tiers: <https://developer.xero.com/pricing>
