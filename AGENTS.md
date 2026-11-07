# AGENTS.md

Read `VISION.md` before starting work. `README.md` indexes the rest of the documentation.

The shared rules are referenced below; this repo's own rules are in Marketplace safeguards, at the end.

<!-- arc-forge-org-consistency:start -->
Read the shared Arc Forge instructions before work:
https://github.com/arcforgelabs/tools/blob/main/docs/AGENTS.shared.md

Optional local source: ~/repos/tools/docs/AGENTS.shared.md.
Verify that the local checkout has the origin arcforgelabs/tools before use.
Do not copy the shared rules here.
Keep repository-specific safeguards and document references outside this block.

Common agent workflows: https://github.com/openclaw/agent-skills.
Product repositories own their product-specific skills.
Reusable release workflows: https://github.com/openclaw/release-workflows.
<!-- arc-forge-org-consistency:end -->

## Marketplace safeguards

### Source and delivery

OpenClaw plugins live under plugins/<name>/openclaw. Maintain implementations
in arcforgelabs/tools and copy only reviewed, provenance-tracked release payloads.
ClawHub is the only public release channel; source merge is not publication or
activation. Private account profiles and credentials never belong here.

The generic Claude/Codex/Cursor publisher is retired. Do not run the removed
forge-tools skills cloud publish command. Four stale generic packages are
removed; the catalogs retain only the legacy explainer consumer pending its
owning migration (Tools issue 396 and marketplace PR 35). Its generated payload
must not be edited by hand. OpenClaw candidate PR 44 is separate and unactivated.

Do not infer that integrations are unused because no tool bundles were sold.
Preserve Field, Fergus, Xero and other operator integrations until their own
consumer and release references are checked. Read CONTRIBUTING.md for remaining
legacy consumers and source/release safeguards.
