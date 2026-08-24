# Maintaining the marketplace

The Field CLI is vendored from `arcforgelabs/arc-forge-field/scripts/field-cli.js` so the public
plugin is self-contained and does not require access to the private application repository.

For a Field release:

1. Copy the reviewed production-compatible CLI into `plugins/field/scripts/field-cli.js`.
2. Bump the Field version in its Codex, Claude Code, and Cursor manifests and both marketplace
   catalogs that carry versions.
3. Run `npm test`.
4. Validate `plugins/field` with the Codex and Claude plugin validators.
5. Inspect the complete diff for credentials, customer data, and private messages before publishing.

Keep shared skills and scripts at the plugin root. Host-specific directories contain manifests only.
