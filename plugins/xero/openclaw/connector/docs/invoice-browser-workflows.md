# Xero Invoice Browser Workflows

These are generic operating lessons for sales-invoice work in Xero's current
web UI. They were verified against the Arc Forge organisation on 2026-07-26.
Business-specific prices, contacts, accounts, tax decisions, and invoice
templates belong in the relevant finance repo, not here.

## Tenant guard before writes

Xero browser state and local API state can target different organisations at
the same time. A browser tab titled for one organisation does not prove that the
CLI token targets it.

Before an API or MCP write:

```bash
connectors/xero/cli/xero profiles list
connectors/xero/cli/xero doctor
connectors/xero/cli/xero smoke organisation
```

Confirm the returned tenant name is the intended legal entity. If the configured
token selects another organisation, do not write with it. Select the correct
profile/tenant or use an explicitly handed-off authenticated browser tab for the
intended organisation.

Before a browser write:

- connect only to an explicitly handed-off authenticated browser session;
- confirm the Xero organisation in both the page title and visible shell;
- recheck it after redirects from legacy URLs into `/app/...` routes.

Never infer the tenant from a customer name, screenshot content, or a healthy
OAuth token.

## Prefer copy-to-draft for recurring invoice shapes

When a new invoice must match a prior sent invoice, prefer **Copy to draft
invoice** over rebuilding its lines. Copying preserves the source contact,
items, accounts, tax rates, branding theme, and online-payment settings.

Observed behavior:

- The copy can be created and autosaved without an obvious navigation away from
  the source invoice.
- Return to the invoice list and locate the new draft before editing it.
- Record its invoice number and edit URL immediately.
- Change only the fields authorised by the business-specific template.
- Save and close; do not approve or send unless explicitly requested.

## Autosave and invoice-number allocation

Xero's current new-invoice SPA begins autosaving after meaningful form state,
including contact selection. A harmless-looking form probe can therefore create
a real zero-value draft and allocate an invoice number.

Consequences:

- Treat contact selection as a write boundary.
- Use a disposable new-invoice page only before selecting a contact.
- After any interrupted or exploratory invoice session, inspect the Draft list
  for zero-value artifacts.
- Delete only artifacts verified to be drafts with no payments.
- Invoice-number gaps can result from created/deleted drafts; never renumber a
  different invoice merely to close a gap.

## Stable automation hooks

Prefer Xero's `data-automationid` attributes over generated element IDs. The
following hooks were present in the current invoice editor:

| Purpose | `data-automationid` |
|---|---|
| Contact search | `contacts-picker-search-field--input` |
| Contact result | `contacts-picker-search-result-option` |
| Issue date | `InvoiceDateInput--input` |
| Due date | `DueDateInput--input` |
| Invoice number | `invoice-number-input--input` |
| Reference | `reference-input--input` |
| Line row | `InvoiceTable--line-item-grid--row` |
| Item | `InvoiceTable--line-item-grid--inventory--search-field--input` |
| Description | `InvoiceTable--line-item-grid--description--input` |
| Quantity | `InvoiceTable--line-item-grid--quantity--input` |
| Unit amount | `InvoiceTable--line-item-grid--unitAmount--input` |
| Account | `InvoiceTable--line-item-grid--account--search-field--input` |
| Tax rate | `InvoiceTable--line-item-grid--taxRate--search-field--input` |
| Line amount | `InvoiceTable--line-item-grid--lineAmount--input` |
| Save and close | `SaveAndCloseButton-save-and-close` |
| Invoice options | `kebab-options-button` |

Generated `id` values are not stable. Text and automation hooks must still be
checked against the current DOM before use; abort if the expected structure has
changed.

## Repairing incorrect drafts

For each candidate draft:

1. Confirm status is `DRAFT`, amount paid is zero, and it belongs to the intended
   organisation.
2. Open the draft and use **More invoice options → Delete**.
3. Read the confirmation text and confirm the exact invoice number before
   accepting deletion.
4. Treat deletion as irreversible.

Do not delete authorised, sent, paid, credited, or lodged-period invoices through
this repair path.

## End-state verification

Never treat a successful click or redirect as proof that invoice work completed.
Re-open the invoice list and verify:

- the expected number of drafts;
- deleted invoice numbers are absent;
- the replacement invoice number is present;
- contact, issue date, due date, reference, and total match;
- the invoice status is still `DRAFT`;
- it has not been sent.

Open the saved draft again and verify every line's item, description, quantity,
unit amount, account, tax rate, line amount, subtotal, GST, and total.

Repeating-invoice templates are a separate ongoing mutation. Do not change a
template's schedule merely because generated drafts were repaired unless the
user separately authorises the future schedule change.
