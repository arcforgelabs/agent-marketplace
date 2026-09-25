# Operations and Admin Gotchas

## Licensing

Staff invite acceptance can fail when the account has no available licences.
The UI may show a plan/licence cap and active staff count. A plan can be over
the displayed cap while still blocking new invite acceptance.

Possible causes include:

- Licence enforcement changed.
- Subscription/plan limit changed.
- Account is blocked until billing is resolved.
- Additional licences or a higher plan are required.

Confirm with Zavy support/billing. Do not infer historical subscription changes
from the UI alone.

## Billing

Zavy subscription cost may not be visible in the Zavy UI, especially for
legacy/manual/default subscription states. Payment history may show SMS credit
purchases but not base subscription charges.

If Xero or accounting data is available, search supplier bills separately from
Zavy UI billing history. Draft/deleted bills may not appear in aged payables.

Keep business-specific billing details out of this generic skill.

## Location Branding

Public booking location cards use location branding fields.

Path:

```text
Settings > Business > Locations > edit location (pen) > Business and Branding
```

Useful controls:

- `Upload CoverPhoto`: large public location card image.
- logo upload/remove: location logo/brand mark.
- phone, website, email, advertised open hours: public contact details.

Always save and verify from the public booking location selection page.

## Documentation

Public help center and release notes are useful, but for account capabilities
Zavy support responses and the authenticated UI are usually more accurate.
When a user asks for latest functionality, check current docs/support/UI rather
than relying on memory.
