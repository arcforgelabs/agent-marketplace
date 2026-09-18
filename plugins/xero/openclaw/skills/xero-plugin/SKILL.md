---
name: xero
description: "Use Xero for cashflow, P&L, unentered bills, aged receivables/payables, tenant checks, and finance preflight; never write without an explicit audit/preflight."
---

# Use Xero

Use the bundled Xero MCP and CLI to inspect cashflow, profit and loss, aged
receivables/payables, accounts, payments, unentered bills, and tenant status.
Confirm the active tenant before interpreting figures or preparing a write.

## Authentication

This is a public OAuth PKCE client. Do not ask for or invent a client secret or
static token field. Do not use SSH tunnels or SecretRef for the auth code.

- Local: `xero auth login` (redirect `http://localhost:8765/callback`).
- VPS/OpenClaw: register `https://<gateway-public-origin>/xero/oauth/callback` on
  the Xero app, bypass Cloudflare Access for that exact path, then
  `xero auth login --redirect-uri https://<gateway-public-origin>/xero/oauth/callback`.
  The plugin HTTP route captures the callback; the operator only completes Xero
  login/MFA/consent in a browser.

Then `xero tenants list --refresh` and `xero tenants use <tenant-id>`.

## Unentered bills (any organisation)

High-level product. It works the same for every Xero org.

Org-specific policy does **not** belong here: approver, email-to-bills address,
default GL codes, known suppliers, Hubdoc habits. Those live in that org's
local bill runbook and `finance-rules.json`. If a local `xero-bills` runbook
skill exists, follow it after the generic loop below.

Copy [references/org-bill-runbook.template.md](references/org-bill-runbook.template.md)
into the org workspace and keep it there. This skill stays generic.

1. Confirm the active tenant is the intended organisation.
2. `xero_bills_inbox` — DRAFT ACCPAY already ingested (email-to-bills or published Hubdoc).
3. `xero_bills_review` — original supplier file, extract, mapping suggestion.
4. Confirm supplier, dates, totals, and lines from the file. Native OCR is untrusted and does not learn.
5. Dry-run `xero_documents_update` kind `bill` only with operator authorisation.
6. After a confirmed coding decision: `xero_bills_learn`, then update the org runbook.

Not in this product: Hubdoc documents not yet published to Xero; Xero Files
without `files` scope; Xero's generated invoice PDF (that is not the supplier
upload).

Lower-level attachment tools: `xero_evidence_attachments` and CLI
`xero evidence attachments list|download bill <InvoiceID>`.
`xero_evidence_audit` finds bills with `HasAttachments=false`.

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
