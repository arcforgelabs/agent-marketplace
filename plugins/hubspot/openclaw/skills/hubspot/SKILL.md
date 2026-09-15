# HubSpot by Arc Forge

Unofficial integration maintained by Arc Forge Labs; not affiliated with or endorsed by HubSpot, Inc.

## Configuration

Set `plugins.entries.arcforgelabs-hubspot.config.accessToken` to a host-managed
SecretRef, for example `{"source":"env","provider":"default","id":"HUBSPOT_TOKEN"}`.
`portalId` is optional and `timezone` is optional with no regional default.

A private app intended for the full toolset generally needs `crm.objects.contacts.read/write`,
`crm.objects.companies.read/write`, `crm.objects.deals.read/write`,
`crm.objects.custom.read/write`, `crm.objects.owners.read`, `crm.schemas.contacts.read/write`,
`crm.schemas.companies.read/write`, `crm.schemas.deals.read/write`, `crm.schemas.custom.read/write`,
`crm.lists.read/write`, and `automation.workflows.read` plus the current contact enrollment scope.
HubSpot may vary scope names by account and API generation; grant only the scopes your operator needs.

## Tools

`hs_status`, `hs_contacts`, `hs_companies`, `hs_deals`, `hs_tickets`, `hs_notes`, `hs_tasks`,
`hs_emails`, `hs_calls`, `hs_meetings`, `hs_associations`, `hs_pipelines`, `hs_properties`,
`hs_owners`, `hs_lists`, `hs_workflows`, and `hs_objects` (custom-object escape hatch).

## Operating rules

Search indexes can lag: confirm important results with get-by-id. Creating deals is not upsert.
Contacts can be upserted by email with create plus `idProperty`, or by search then update.
There is no arbitrary HTTP tool. Writes are live when invoked. Use fictional records such as
`Alex Example` and `Acme Landscaping` in documentation and tests; never put customer data in this package.

```sh
HUBSPOT_TOKEN=... hubspot contacts '{"action":"search","query":"Alex Example","properties":["email"]}'
```

Only `ACCOUNT.template.md` ships. Keep portal ID, pipeline/property mappings, list/workflow IDs
and naming conventions in a private authorised profile; never credentials or customer records.
