---
name: xero
description: "Use Xero for cashflow, P&L, aged receivables/payables, tenant checks, and finance preflight; never write without an explicit audit/preflight."
---

# Use Xero

Use the bundled Xero MCP and CLI to inspect cashflow, profit and loss, aged
receivables/payables, accounts, payments, and tenant status. Confirm the active
tenant before interpreting figures or preparing a write.

## Authentication

This is a public OAuth PKCE client. Run `xero auth login`, then select the
organisation with `xero tenants list --refresh` and `xero tenants use <tenant-id>`.
Do not ask for or invent a client secret or static token field.

## Operating rules

- Prefer read-only reports and exports for financial questions.
- Before any write, run the relevant dry-run/audit and attach its preflight
  report; never use a bare apply path.
- State the tenant and reporting period in the result.
- Reconciliation browser work requires an explicitly supplied,
  already-authenticated CDP endpoint; never harvest sessions or bypass MFA.
- Keep tenant IDs, credentials, profile packs, and organisation-specific
  mappings outside this public package.

Generic implementation references live in the bundled connector's README and
architecture/API-vs-CDP documentation. They are operational background, not a
customer runbook.
