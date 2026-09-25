---
name: zavy
description: "Zavy/Zavy360 knowledge: where data lives, reports vs operational pages, exports, notes/billing/recalls, and optional browser inspection."
---

# Zavy

This skill is a knowledge base for Zavy/Zavy360. It is not a plugin, login,
or API connection. There is no bundled tenant and no self-service API key.

Use it when someone asks how Zavy works, where a number came from, why an
export disagrees with the screen they work from, or how reports, recalls,
notes, billing, bookings, or patient records behave. Browser driving is
optional and later: inspect first, change only when asked.

Practice-specific URLs, locations, staff maps, suppliers, and business policy
belong in an operator-selected private profile **outside this skill**. Verify
any profile against the live authenticated tenant before using it. Never
search other customers' profiles. Unknown mappings stay blank. Credentials,
patient records, and invoice copies stay in their protected systems. Skill
updates must not overwrite private profiles.

Zavy is a clinical/health-data system. Treat it as production. Keep patient
data out of notes, screenshots, commits, and chat.

## Where data comes from

Truth order:

1. The operator's question and the live authenticated Zavy UI.
2. Zavy public help / release notes.
3. Zavy support responses.
4. The authenticated app's GraphQL/Apollo cache — for verification and careful
   automation only.

Do not present internal GraphQL as official API access. Zavy does not offer
open self-service API keys. Partner access goes through Zavy's Partner API
Program. Details:
[`references/api-and-browser.md`](references/api-and-browser.md).

Surfaces that often disagree (do not invent a reconciliation):

- **Operational pages vs report grids vs spreadsheet exports.** The screen
  staff work from can differ from report extracts. To see who is due for
  recall, open `/recalls` in Zavy; a report export can disagree until checked
  against that page.
  See [`references/recalls-and-reports.md`](references/recalls-and-reports.md).
- **Charted vs invoiced.** Invoice Builder "Ready to Invoice" is completed
  work not yet billed. Reports → Finance → Uninvoiced Items can under-count
  because it needs a completion timestamp. See
  [`references/clinical-records-and-notes.md`](references/clinical-records-and-notes.md).
- **Admin config vs public booking.** Admin can look correct while the public
  booking page filters, names, or slots differ. Always verify public booking
  after online-booking changes.

When asked about an export, name the screen it came from before interpreting
the numbers.

## Feature map

- **Online booking:** appointment shortcuts/reasons with `ONLINE_BOOKINGS`.
  [`references/online-bookings.md`](references/online-bookings.md).
- **Availability:** rosters define bookable sessions; private appointments
  block time.
  [`references/appointments-and-blockers.md`](references/appointments-and-blockers.md).
- **Location cards:** `Settings > Business > Locations > edit location` →
  `Upload CoverPhoto`.
- **Licensing / subscription UI:** licence caps can block staff invites.
  [`references/operations.md`](references/operations.md).
- **Patient record:** `/patients/{id}/` plus `profile`, `notes`, `chart`,
  `invoices`, `treatment-plan`, and related tabs. Clinical Summary is a
  consolidated timeline of charted items and their Clinical: Treatment notes
  only — not General/Internal notes.
  [`references/clinical-records-and-notes.md`](references/clinical-records-and-notes.md).
- **Lab work entry:** Patients → patient → Labworks → New Lab Work (or the
  main Labworks route). Generic procedure only.
  [`references/lab-invoice-entry.md`](references/lab-invoice-entry.md).
- **Notes editor:** Lexical composer; paste-HTML vs in-place CDP typing.
  [`references/notes-editor-automation.md`](references/notes-editor-automation.md).
- **How to get recalls:** open `/recalls` for the due list. Patient Recalls /
  Patient Recalls Due / Non Rebooked are export paths, not a second product.
  [`references/recalls-and-reports.md`](references/recalls-and-reports.md).

## Optional browser inspection

Only when the operator has an authenticated Zavy tab and wants live lookup or
a later guided click-path (export a report, open a patient record). Attach to
that session; do not start a fresh login.

Default CDP (override with `ZAVY_CDP`):

```bash
http://127.0.0.1:9226
```

List Zavy tabs:

```bash
curl -s http://127.0.0.1:9226/json/list | jq -r '.[] | [.id,.type,.title,.url] | @tsv' | rg 'zavy|bookings'
```

If CDP is unavailable, ask them to reopen the authenticated browser with
remote debugging before changing live settings.

Read-only helper (requires `--base-url` or `ZAVY_BASE_URL`, e.g.
`https://yourpractice.zavy.com`):

```bash
scripts/zavy-cdp-helper.mjs list-tabs --pretty
scripts/zavy-cdp-helper.mjs search-patient --name "Jane Example" --dob 1980-01-31 --pretty
scripts/zavy-cdp-helper.mjs search-staff --name "Alex" --pretty
scripts/zavy-cdp-helper.mjs notes --patient-guid <guid> --created-start 2026-06-29T00:00:00Z --created-end 2026-06-29T23:59:59Z --pretty
```

The helper runs GraphQL from inside the authenticated tab and prints JSON to
stdout. Treat output as patient data: keep it local, summarise minimally, do
not commit it.

CDP handshake, Apollo cache, and public-booking checks:
[`references/api-and-browser.md`](references/api-and-browser.md).

## If asked to change something

1. Identify the exact record and current state.
2. Capture fields that must be preserved.
3. Apply the smallest change.
4. Re-read the admin record.
5. If the change affects patients, verify the public booking flow.

Appointment-reason updates can treat omitted fields as empty. Preserve
practitioners, session filters, catalogue links, templates, visibility,
prepayment, deposit, and cost flags unless you have verified that mutation is
patch-like. Full field list:
[`references/api-and-browser.md`](references/api-and-browser.md).
