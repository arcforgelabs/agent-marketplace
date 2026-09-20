---
name: xero
description: "Use Xero for cashflow, P&L, unentered bills, aged receivables/payables, tenant checks, and finance preflight; never write without an explicit audit/preflight."
---

# Use Xero

Use the bundled Xero MCP and CLI to inspect cashflow, profit and loss, aged
receivables/payables, accounts, payments, unentered bills, and tenant status.
Confirm the active tenant before interpreting figures or preparing a write.

## Authentication

This is a public OAuth PKCE client. The public client ID is bundled and is NOT
a secret: never request it through a secret-input tool or redact it in a login
request. Never ask for a Xero client secret or copy auth codes into SecretRef.

- First check `xero auth status`; do not replace a working grant unnecessarily.
- Approved installation: `xero auth login --print-url` prints a short
  `https://connect.arcforge.au/xero/start/...` link. Deliver that link exactly,
  preferably as **Connect Xero**. Never reconstruct an authorize URL.
- Keep that process alive for the login. Link lifetime is ten minutes, and a
  new attempt replaces the old one. Do not create multiple concurrent waiters.
- Missing approval means an operator must provision the private installation
  credential, not a Xero app/client secret. See the package README.
- The user completes Xero login/MFA/consent. The browser confirms receipt only;
  verify CLI success and `xero smoke organisation` before declaring connected.
- Existing direct mode remains explicit:
  `xero auth login --redirect-uri <already-registered-callback>`.
  Do not alter working direct grants while the shared service is being enabled.

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
