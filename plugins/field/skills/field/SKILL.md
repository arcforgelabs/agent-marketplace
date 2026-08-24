---
name: field
description: Operate the Field production app, including jobs, quote revisions, milestone invoices, email templates, catalog data, documents, and the Field CLI.
---

# Field

Use this skill whenever a request touches Field jobs, quotes, invoices, payments, email templates,
catalog entries, PDFs, or the `field` command.

## Bundled tool

The dependency-free CLI is at `scripts/field-cli.js` under this plugin's root. Resolve the plugin
root from this `SKILL.md` path and invoke the script with an absolute path:

```bash
node "<plugin-root>/scripts/field-cli.js" --help
```

Prefer an installed `field` command when `command -v field` succeeds. If it is missing and the user
has asked to set up or use Field, run:

```bash
node "<plugin-root>/scripts/install-field-cli.js"
```

The installer writes only to a user-writable command prefix and prints the installed launcher path.

## Authentication

Production is `https://field.embarkearthworks.au`.

Check authentication before an operational request:

```bash
field auth status
```

If authentication is missing, tell the user to run this in their own terminal:

```bash
field auth login --url https://field.embarkearthworks.au
```

The prompt hides the service key and stores it at `~/.config/field/token` with user-only
permissions. Never ask the user to paste a key into chat, place one in argv, print one, or read one
back into the conversation. `FIELD_TOKEN` and `FIELD_TOKEN_FILE` are supported for managed runtime
delivery.

## Working rules

- Read the job or template before changing it and report the exact target.
- Treat non-draft customer-facing quote revisions as locked history.
- Payment documents must remain anchored to the customer-facing revision.
- Record the actual amount paid; do not recalculate an old deposit from a revised quote total.
- Sent or paid milestone prefixes are immutable until explicitly marked unsent or unpaid.
- Keep one requested final invoice as one invoice; do not split it unless the user asks.
- Preserve all template placeholders unless the user explicitly removes one after reviewing it.
- Preview consequential document or template changes before sending them to a customer.

## Email templates

```bash
field email-templates list
field email-templates show invoice standard
field email-templates update invoice standard --subject "Invoice {{invoice_number}}"
field email-templates update invoice standard --body-file invoice-template.html
```

Use `show` before `update`. Write non-trivial HTML to a workspace file and use `--body-file`; do not
put large HTML bodies or credentials on a command line.

## Jobs and documents

```bash
field list-jobs
field get-job <job-id> --version customer
field get-job <job-id> --version latest
field status <job-id>
field get-pdf <job-id> out.pdf --document quote|invoice|receipt --milestone 2
field send-document <job-id> client@example.com --document quote|invoice|receipt --milestone 2
```

For a landed job, compare `customer` and `latest` before changing or sending documents. Use an
explicit `--document` and milestone when ambiguity could affect a customer.

## Milestones

```bash
field list-milestones <job-id>
field generate-milestones <job-id> --schedule schedule.json
field update-milestone <job-id> 2 --status authorised
field record-milestone-payment <job-id> 1 12003.02 --reference "bank receipt"
field mark-milestone-unpaid <job-id> 1
field mark-milestone-unsent <job-id> 1
```

Milestone numbers are human-facing: `1` or `M1` is the first milestone.

## Presentation and catalog

Use `field --help` as the current command authority. Relevant organizer commands include
`get-presentation`, `add-group`, `add-manual-item`, `move-node`, `rename-node`, `hide-amount`,
`exclude-node`, and `remove-node`. Prefer the Field API through the CLI rather than editing runtime
files. For a capability without a dedicated command, inspect the live API contract before using it.

## Completion

After a write, read the affected resource back and summarize what changed, what remains unsent, and
whether human verification is still required.
