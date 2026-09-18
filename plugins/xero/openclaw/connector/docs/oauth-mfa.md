# OAuth, MFA, and User Login

The core connector uses Xero OAuth 2.0 Code + PKCE through an Arc Forge-owned
Xero OAuth app.

## User Flow

0. Operator runs `xero auth configure-app --client-id <public-client-id>` if
   the public Arc Forge client ID is not packaged locally, then runs
   `xero auth app-config` to confirm the OAuth app redirect URI and scopes.
1. User runs `xero auth login`.
2. Browser opens Xero's consent flow.
3. User signs in with their Xero account.
4. User completes Xero MFA if required.
5. User selects the Xero organisation.
6. Xero redirects to the registered URI:
   - local/dev: `http://localhost:<port>/callback` (IPv4 waiter on `127.0.0.1`)
   - VPS/OpenClaw Gateway: `https://<gateway-public-origin>/xero/oauth/callback`
     (plugin HTTP route, no SSH tunnel). Cloudflare Access must bypass that exact path.
7. The CLI exchanges the code and stores token state.
8. The MCP wrapper requests fresh access tokens from `xero auth token`.

The connector does not receive or automate the user's Xero password or MFA code.

## App Configuration

`xero auth app-config` prints the machine-readable setup contract for the
Arc Forge-owned public OAuth app:

- App type: PKCE-capable public client.
- Client secret: not required and not used.
- Public client ID source: command argument, environment variable, local user
  config, plugin packaged config, or connector packaged config.
- Redirect URIs: `http://localhost:<port>/callback` (default) and, for a headless
  Gateway, `https://<public-origin>/xero/oauth/callback`. Both must be registered
  on the Arc Forge Xero app. Set `ARC_FORGE_XERO_REDIRECT_URI` or pass
  `--redirect-uri` on `xero auth login` so the authorize URL matches the VPS
  callback. Do not use SSH `-L` for this.
- Scopes: the default full-power MVP accounting scope set, including
  `offline_access` for refresh tokens.

Users of the finished plugin should not create their own Xero developer app.
Operators can write the shared public client ID to local user config with
`xero auth configure-app --client-id <public-client-id>`. That writes
`~/.config/arc-forge-tools/xero/oauth-app.json` with `0600` permissions and no
client secret.
They need only their own Xero account access once the shared public client ID is
packaged with the plugin or written to local config.

On a headless OpenClaw VPS, prefer the Gateway HTTPS callback over SSH port
forwarding. The plugin serves `GET /xero/oauth/callback` (`auth: plugin`). Put
that exact path on the Xero app redirect list and exclude it from Cloudflare
Access. Then `xero auth login --redirect-uri https://<public-origin>/xero/oauth/callback`.

## Token Handling

Verified against Xero Developer OAuth documentation on 2026-06-07.

Xero access tokens are valid for up to 30 minutes. Refresh tokens are returned
when the `offline_access` scope is granted, are valid for up to 60 days when
kept active, rotate on refresh, and must be stored carefully. The CLI persists
the rotated refresh token after refresh.

For PKCE apps, Xero documents that the token refresh request does not include a
client secret. If a refresh response is lost before the new refresh token is
stored, the previous refresh token has a grace period of up to 30 minutes. This
is why the connector writes a local backup before replacing token state and
treats refresh-token persistence as part of the success path.

Current prototype storage writes an encrypted JSON envelope when Python
`cryptography` is available. The token file and local encryption key file are
created with `0600` permissions. Existing plaintext token stores remain readable
and are rewritten encrypted on the next save. Run `xero auth migrate-store` to
rewrite an existing store immediately.

Before replacing an existing token store, the CLI writes a local `0600` backup
beside it, for example:

```text
~/.config/arc-forge-tools/xero/tokens.json.bak
```

When encrypted storage is available, the backup is the encrypted envelope, not
plaintext token material. This gives the local operator a recovery point if a
refresh-token rotation or migration is interrupted, but it is still credential
state and must not be committed, copied into prompts, or shared.
The same rotation path is used by `xero auth token`, so the MCP wrapper can ask
for a fresh access token without losing the newly issued refresh token.
The token-provider path serializes load, refresh, and save with a local guard
file beside the token store. This prevents concurrent MCP calls from trying to
rotate the same Xero refresh token at the same time.

Token-store controls:

- `ARC_FORGE_XERO_TOKEN_STORE_MODE=auto` defaults to encrypted when supported.
- `ARC_FORGE_XERO_TOKEN_STORE_MODE=encrypted` refuses to run if encryption
  support is unavailable.
- `ARC_FORGE_XERO_TOKEN_STORE_MODE=plaintext` is for emergency/debug use only.
- `ARC_FORGE_XERO_TOKEN_KEY_FILE` overrides the local encryption key path.

The local key-file backend is an MVP encrypted-at-rest layer for single-user
machines. OS keychain or hardware-backed key storage remains a future hardening
step.

## Re-auth Conditions

Run `xero auth login` again when:

- The refresh token expires or is revoked.
- The user disconnects the app in Xero.
- Scopes need to change.
- The selected organisation is no longer available.

The full-power MVP default scope set includes Xero's attachment scopes
(`accounting.attachments` and `accounting.attachments.read`) so evidence files
can be listed, uploaded, and downloaded for supported Accounting API records.

## Boundaries

The core plugin must not package:

- Xero credential entry automation.
- MFA retrieval or TOTP handling.
- Browser-login automation.
- Cloudflare or security-control bypass.
- Browser cookie/profile transfer.

Those concerns remain outside the Xero plugin. The reconciliation extension may
only use a browser/CDP session the user has already logged into.

## Official References

- Xero OAuth overview: <https://developer.xero.com/documentation/guides/oauth2/overview>
- Xero PKCE flow: <https://developer.xero.com/documentation/guides/oauth2/pkce-flow>
- Xero token types: <https://developer.xero.com/documentation/guides/oauth2/token-types>
- Xero OAuth FAQ: <https://developer.xero.com/faq/oauth2>
