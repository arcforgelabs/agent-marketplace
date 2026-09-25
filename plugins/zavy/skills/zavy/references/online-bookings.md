# Online Bookings

## Data Model

Zavy public online booking services are appointment shortcuts/reasons with the
online booking integration enabled. In the app schema these commonly appear as
`AppointmentReason` records with:

- `name`: public/admin service name.
- `description`: patient-facing modal copy.
- `minutes`: duration.
- `integrations`: includes `ONLINE_BOOKINGS` when public.
- `patientVisibility`: `all`, `new`, or `existing`.
- `category`: used for public filter chips.
- `practitioners`: assigned staff available for that service.
- `shiftTypes`: allowed sessions; blank usually means all sessions.
- `catalogueItemAppointmentReasons`: linked services/items and optional prices.
- `showTotalCost`, `prepaymentType`, deposit flags.

## Categories and Filters

Zavy has a shared category system with different category types.

- `ServiceCategory`: patient-facing appointment shortcut / online booking
  filters. Use this for clean public filter chips.
- `CatalogueItemCategory`: clinical/billing taxonomy. Avoid using these as
  public filters unless the wording is genuinely patient-friendly.
- Other types may exist, such as referral source or clinical note categories.

Recommended public filter categories should be short and patient-oriented:

- Dental
- Emergency
- Dentures
- Cosmetic
- Implants
- Mouthguards

Use clean service names and metadata categories rather than prefixes such as
`Dental |` or `Denture |` in the service name.

## Naming Pattern

Prefer patient intent:

- `Adult Check & Clean`
- `Kids Check & Clean`
- `Emergency - Toothache / Dental Pain`
- `Emergency - Broken or Cracked Tooth`
- `New Denture Consultation`
- `Broken Denture Repair`
- `Denture Reline`
- `Clear Aligner Consultation`
- `Teeth Whitening Consultation`

Avoid internal taxonomy in patient-facing names unless it clarifies the service.

## Emergency Booking Copy

Emergency booking descriptions should be short and action-oriented. Example:

```text
Please call (0X) XXXX XXXX before booking so we can triage your symptoms and confirm this appointment is right for you.
```

The appointment reason `description` field is usually plain text, not rich
HTML. A phone number may be auto-linked by mobile browsers, but do not assume a
`tel:` link will render from that field.

## Session and Friday/Emergency Constraints

Online booking shortcuts can be restricted with allowed sessions/shift types.
Use this when a service should only appear during specific roster/session
blocks. If the shortcut has no allowed sessions, it generally applies to all
bookable sessions for assigned practitioners.

Private blockers affect all booking types for that practitioner/time, not just
one shortcut. Use session restrictions for service-specific availability where
possible.

## Verification

After changes, verify:

1. Admin table shows expected category, assigned staff, online flag, visibility,
   duration, and payment setting.
2. Public booking page shows filter chips and clean names.
3. Patient-type flow still shows the correct new/existing services.
4. Opening a service modal shows expected description and practitioners.
5. Bookable slots appear for the expected staff.
