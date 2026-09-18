# Maintaining the marketplace

This repository distributes agent integrations. Keep its overview and GitHub description host-neutral and integration-neutral. Put service-specific setup in the corresponding package README.

## Source and release boundaries

Maintain implementations in their canonical source repositories. Generate or copy reviewed release payloads here; do not maintain a divergent implementation in the marketplace.

- **GoHighLevel / OpenClaw:** canonical source and staging tooling live in `arcforgelabs/arc-forge-tools`. Follow its `docs/architecture/plugin-publishing.md` and `forge-tools plugin stage gohighlevel` entry point. The package lives at `plugins/gohighlevel/openclaw/` and records source provenance.
- **HubSpot / OpenClaw:** canonical source and staging tooling live in `arcforgelabs/arc-forge-tools`. Follow its `docs/architecture/plugin-publishing.md` and `forge-tools plugin stage hubspot` entry point. The package lives at `plugins/hubspot/openclaw/` and records source provenance.
- **Xero / OpenClaw:** canonical source and staging tooling live in `arcforgelabs/arc-forge-tools`. Follow its `docs/architecture/plugin-publishing.md` and `forge-tools plugin stage xero` entry point. The package lives at `plugins/xero/openclaw/` and records source provenance. Runtime id `arcforgelabs-xero`. Org-specific bill policy stays in a private runbook copied from the packaged template.
- **Field / OpenClaw:** canonical source and staging tooling live in `arcforgelabs/arc-forge-tools`. Follow its `docs/architecture/plugin-publishing.md` and `forge-tools plugin stage field` entry point. The package lives at `plugins/field/openclaw/` and records source provenance. It is an OAuth MCP connector; do not ship a Field CLI, workspace runbook skill, or long-lived bearer in that payload.
- **Generic skills (Codex, Claude Code, Cursor):** canonical source lives in `arcforgelabs/arc-forge-tools` under `components/skills/<name>`. Stage with `forge-tools skills stage <name> --out <dir>` and copy the result to `plugins/<name>/`; it carries the skill under `skills/<name>/`, the three host `plugin.json` files and `PROVENANCE.json` with `kind: skill`. One skill per plugin, no runtime, no account state. `test/skill-plugins.test.js` checks every staged skill is complete and listed in all three marketplace manifests. Current: `replit-github`.
- **Field / portable (Codex, Claude, Cursor):** the CLI comes from `arcforgelabs/arc-forge-field/scripts/field-cli.js`. Keep the reviewed production-compatible copy at `plugins/field/scripts/field-cli.js` until that harness lane is retired. The public package must not require access to the private application repository. OpenClaw must not use this CLI lane.

## Release checks

1. Build and validate the selected integration at its canonical source.
2. Stage its complete self-contained payload, with no dependency on sibling checkout folders.
3. Update that package's version and any host catalog entries carrying its version. Only list hosts whose runtime compatibility has been verified.
4. Run `npm test` here and the applicable host package validators and installation checks.
5. Inspect the complete payload for credentials, customer records and populated account profiles. Only generic guidance and blank templates belong in public packages.
6. Preserve or update provenance when changing a generated payload. Follow the source release process rather than editing generated files independently.
7. Keep compatibility, installation and release status in the relevant package documentation, not the root README. Do not make one integration's instructions the marketplace-wide default.
8. Publish through the appropriate delivery target. A ClawHub submission or successful dry run is not proof of public availability; report registry review status accurately.

Shared portable payloads may carry multiple host manifests. Split assemblies only when their runtime needs differ. Actual account profiles are separately authenticated private delivery and must never be bundled in public releases or overwritten by plugin upgrades.
