# How to get recalls from Zavy

Zavy already tracks who is due for recall. This is how to read or export that
list from Zavy. Do not rebuild a recall product around it.

## In the app

1. Open **`/recalls`**. That is the working due list.
2. Confirm an individual patient on their record/profile if a row looks wrong.
3. Use reports only as another export path, then check them against `/recalls`:
   - `/reports/patient/recalls` — Patient Recalls
   - `/reports/patient/recalls-due` — Patient Recalls Due
   - `/reports/appointment/non-rebooked` — Non Rebooked (appointments, not the
     due list)

Name the screen before interpreting an export. A spreadsheet is not automatically
the same set as `/recalls`.

## What `/recalls` is counting

The page is month-scoped. Observed filters on the due view:

- active patients
- due window = that month (`recallDueTime` start/end)
- skip patients with an upcoming visit
- skip patients who already have an active recall
- skip patients with 4 or more consecutive missed appointments
- drop-off recalls are not skipped by default

Practice default interval is in configuration (`newPatientDefaultRecallPeriod`).

The first page is not the full list. If `totalCount` is larger than the visible
rows, page through or request more rows before quoting a count or exporting.

Patient profile links from this list use the user-practice-connection GUID:

```text
/patients/<node.guid>/profile
```

Do not use `node.profile.guid`. That 404s.

## Exporting a report

Reports are AG Grid pages under `/reports/...`. Load the period, then export.
Right-click a cell for CSV/Excel if the toolbar does not offer it.

Pitfalls already seen:

- **Patient Recalls** can show recall metadata with blank due fields for the
  selected period.
- **Patient Recalls Due** can time out, or export headers/zero rows, even when
  `/recalls` has due patients.
- **Non Rebooked** is useful for follow-up opportunities. It is not the due
  recall list.
- Grid export can be only the visible/paginated rows unless you scroll/page
  through first.

Keep patient names, phones, emails, and screenshots out of chat and this skill.

## Optional: count from the open page

If an authenticated Zavy tab is already on `/recalls`, the Apollo cache can
give `totalCount` without scraping rows into chat. See
[`api-and-browser.md`](api-and-browser.md) for CDP attach. Observed due query
name: `UserPracticeConnectionRecalls` with `recallFilter: "due"`.
