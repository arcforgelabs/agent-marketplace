"""Outbound-only, approved-installation Xero callback handoff (protocol v1).

No PKCE verifier or Xero access/refresh token is sent to this service.
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import re
import secrets
import stat
import time
import urllib.error
import urllib.request

ORIGIN = "https://connect.arcforge.au"
REDIRECT_URI = ORIGIN + "/xero/callback"
CLIENT_ID = "36039170F54F49879F08C5F0AFBD3C7D"
STATE = re.compile(r"[a-z0-9_-]{1,40}\.[A-Za-z0-9_-]{43}\Z")


class ConnectError(RuntimeError):
    pass


def credential_path() -> Path:
    raw = os.environ.get("ARC_FORGE_XERO_CONNECT_CREDENTIAL_FILE")
    return Path(raw).expanduser() if raw else Path.home() / ".config/arc-forge-tools/xero/connect-credential"


def read_credential() -> str:
    path = credential_path()
    try:
        info = path.stat()
        if not stat.S_ISREG(info.st_mode) or info.st_mode & 0o077:
            raise ConnectError("Connection credential must be a private file (chmod 600).")
        value = path.read_text().strip()
    except FileNotFoundError:
        raise ConnectError("This installation needs Arc Forge connection approval. Provision its private connect-credential file, then retry. No Xero developer credentials are needed.") from None
    if not re.fullmatch(r"[A-Za-z0-9_-]{43}", value):
        raise ConnectError("Invalid installation credential file.")
    return value


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def request(path: str, credential: str, payload: dict, claim: str | None = None) -> tuple[int, dict]:
    headers = {"User-Agent": "ArcForge-Xero-Connect/0.3.0", "Content-Type": "application/json", "Authorization": "Bearer " + credential}
    if claim:
        headers["X-Claim-Token"] = claim
    req = urllib.request.Request(ORIGIN + path, data=json.dumps(payload).encode(), headers=headers, method="POST")
    try:
        response = urllib.request.build_opener(NoRedirect()).open(req, timeout=15)
    except urllib.error.HTTPError as exc:
        response = exc
    except (urllib.error.URLError, TimeoutError, OSError):
        raise ConnectError("Connection service unreachable. Retry Connect Xero; existing Xero tokens were not changed.") from None
    with response:
        status = response.code
        body = response.read(16_385)
    if len(body) > 16_384:
        raise ConnectError("Invalid connection service response.")
    try:
        result = json.loads(body)
        if not isinstance(result, dict):
            raise ValueError()
    except (ValueError, UnicodeDecodeError):
        raise ConnectError(f"Connection service returned HTTP {status}; retry Connect Xero.") from None
    if status not in (200, 201, 202):
        messages = {
            403: "Installation approval or claim is invalid/revoked. Contact Arc Forge.",
            410: "This login expired, was replaced, or was already retrieved. Start Connect Xero again.",
            429: "Too many login attempts. Wait ten minutes before trying again.",
            503: "The shared Xero connection service is not ready. Existing direct connections are unaffected.",
        }
        raise ConnectError(messages.get(status, f"Connection service rejected the request (HTTP {status})."))
    return status, result


def login(*, client_id: str, challenge: str, scope: str, timeout: int, print_url: bool, open_browser) -> tuple[str, dict]:
    if client_id != CLIENT_ID:
        raise ConnectError("Shared connection requires the bundled Arc Forge public client ID. Use an explicit direct redirect URI for a different Xero app.")
    credential = read_credential()
    claim = secrets.token_urlsafe(32)
    status, session = request("/xero/sessions", credential, {
        "client_id": client_id, "code_challenge": challenge, "scope": scope,
        "claim_sha256": hashlib.sha256(claim.encode()).hexdigest(),
    })
    state = session.get("state", "")
    if (status != 201 or not STATE.fullmatch(state)
            or session.get("connect_url") != ORIGIN + "/xero/start/" + state
            or session.get("redirect_uri") != REDIRECT_URI):
        raise ConnectError("Invalid connection service session; no browser was opened.")
    expires = session.get("expires_at")
    if not isinstance(expires, (int, float)) or not 0 < expires / 1000 - time.time() <= 610:
        raise ConnectError("Connection service returned an invalid expiry.")
    deadline = time.monotonic() + min(timeout, 600, max(0, expires / 1000 - time.time()))
    try:
        print("Connect Xero using this link (expires in at most ten minutes):", flush=True)
        print(session["connect_url"], flush=True)
        if not print_url:
            open_browser(session["connect_url"])
        print("Waiting for Xero consent. Keep this process running; a new attempt replaces this link.", flush=True)
        while time.monotonic() < deadline:
            status, result = request("/xero/result", credential, {"state": state}, claim)
            if status == 200:
                if result.get("state") != state:
                    raise ConnectError("OAuth state mismatch. Aborting.")
                return state, result
            time.sleep(min(2, max(0, deadline-time.monotonic())))
        raise ConnectError("Xero login expired. Start Connect Xero again; existing tokens were not changed.")
    finally:
        try:
            request("/xero/cancel", credential, {"state": state}, claim)
        except ConnectError:
            pass  # Server expiry still removes the session after loss of connectivity.
