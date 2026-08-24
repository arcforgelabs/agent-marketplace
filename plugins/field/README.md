# Field Codex Plugin

This plugin bundles the Field CLI and a Codex skill for production Field workflows.

After installing the plugin, start a new Codex task and ask: **Set up Field for me and verify the
connection.**
Codex will run the bundled installer. Then authenticate once in your own terminal:

```bash
field auth login --url https://field.embarkearthworks.au
```

Useful checks:

```bash
field auth status
field email-templates list
field email-templates show invoice standard
```

The key is entered through a hidden prompt and stored with user-only permissions. Never commit it,
paste it into a conversation, or add it to this plugin.

Setup is complete only when `field auth status` identifies the expected service account and
`field email-templates list` returns the live template catalogue.
