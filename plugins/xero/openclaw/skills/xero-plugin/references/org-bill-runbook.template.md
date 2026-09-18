# Org Xero bill runbook (template)

Copy this file into the organisation's private workspace or company skill
portfolio. Do not fill it inside the public Xero plugin.

The generic plugin owns the tools: inbox, review, learn, draft update.
This file owns **this org's** policy. Update it when a coding decision is
confirmed so the next session does not start from zero.

## Tenant

- Organisation name: `<org-name>`
- Confirm the live Xero tenant matches before any bill read or write.

## Inbox

- Email-to-bills address: `<bills@…>` (Business → Bills to pay → Automate bill entry)
- Hubdoc: `<used / not used>`. Unpublished Hubdoc documents are not in the API.
- Default inbox command: `xero_bills_inbox` (DRAFT ACCPAY).

## Confirmation

- Approver: `<name>`
- Auto-code below: `<amount or none>`
- Never AUTHORISE a bill with no supplier file stapled.

## Known suppliers

Add a row after each confirmed `xero_bills_learn`. This table is the human
runbook; `finance-rules.json` is the machine mapping.

| Supplier | Account | Tax | Notes | Learned |
| --- | --- | --- | --- | --- |
| | | | | |

## Self-improve

After the operator confirms a new supplier coding:

1. `xero_bills_learn --supplier "…" --account-code … --tax-type …`
2. Add or update the row above in **this** file.
3. Do not wait for a plugin release to remember the mapping.
