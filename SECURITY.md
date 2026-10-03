# Security Policy

If you believe you have found a security issue in an Arc Forge marketplace package, report it privately first.

Do not open a public issue or pull request that discloses an unpatched vulnerability, exploit path, secret, customer record, or security-sensitive proof of concept.

## Reporting

Submit a private [GitHub Security Advisory](https://github.com/arcforgelabs/agent-marketplace/security/advisories/new) for this repository. If you cannot use it, open a public issue that only asks for a disclosure contact and contains no details.

Useful reports include:

- the affected package, version, and commit SHA,
- the agent host and version (for example OpenClaw, Claude Code, or Codex),
- the impacted file path,
- reproduction steps against the latest published package or current `main`,
- the actual impact and which trust boundary below it crosses,
- a suggested fix when practical.

Reports without reproduction steps and demonstrated impact may be deprioritized.

## Scope

Security-relevant surfaces in this repository include:

- packaged connectors, CLIs, MCP servers, and skills under `plugins/` (Xero, HubSpot, GoHighLevel, Deputy, Fergus, Field, and the generic skills),
- how those packages obtain, store, refresh, and redact account credentials (SecretRef, OAuth, and personal access tokens),
- any credential, customer record, or populated account profile shipped in a public payload,
- marketplace manifests (`.claude-plugin/marketplace.json` and the per-package host manifests) and `PROVENANCE.json`,
- GitHub Actions and package validation.

## Out of Scope

The following are usually out of scope for this repository:

- vulnerabilities in the third-party services these packages connect to (Xero, HubSpot, GoHighLevel, Deputy, Fergus, Field, Replit, Zavy),
- issues in OpenClaw core, its plugin loader, or gateway behavior that must be fixed in [openclaw/openclaw](https://github.com/openclaw/openclaw/security/advisories/new),
- a package doing what it documents after a trusted operator installs and enables it: installed plugins run with the host agent's trust ([OpenClaw's plugin trust boundary](https://github.com/openclaw/openclaw/blob/main/SECURITY.md#plugin-trust-boundary)),
- prompt injection by itself, unless it demonstrates a concrete auth, approval, sandbox, or credential-scope bypass,
- OAuth client IDs and redirect URIs in package config, which are public identifiers by design,
- reports that require prior write access to trusted local state, such as the agent's config, installed packages, or local credential stores,
- scanner-only findings without a working reproduction and demonstrated impact.

## Trust Boundaries

These packages assume the agent host and the account that installs them are trusted.

- Account credentials belong to the installing user, who supplies them at install or run time. Public payloads carry only generic guidance and blank templates.
- An installed package runs with the host agent's privileges, and its tool access is limited only by the host's tool policy.
- Untrusted inputs are data returned by third-party APIs, and content the agent reads that originates outside the installing account.

Reports should show how an untrusted input crosses one of those boundaries, or how a public payload exposes a credential or customer data.
