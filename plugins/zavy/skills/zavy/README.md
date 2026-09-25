# Zavy Skill

Knowledge base for Zavy/Zavy360: where operational data, reports, and exports
come from, how notes/billing/recalls/bookings behave, and optional
authenticated-browser inspection.

Not a plugin or API client. Business-specific account details belong in a
private profile outside this skill, not in these files.

## Helper Scripts

- `scripts/zavy-cdp-helper.mjs` attaches to an existing authenticated
  Chrome/Brave CDP session and performs read-only Zavy tab discovery, patient
  lookup, staff lookup, schema inspection, and non-clinical note extraction.
  Requires `--base-url` or `ZAVY_BASE_URL`. It prints JSON to stdout and does
  not write patient exports.
