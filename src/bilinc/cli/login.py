"""One-click ``bilinc login``.

The default flow opens the browser and hands a one-time code back to a
listener on ``127.0.0.1`` (an OAuth-style loopback redirect with PKCE, RFC 8252
and RFC 7636). The CLI then exchanges that code, plus the PKCE verifier only it
knows, for an API key it saves locally. Machines without a browser use a device
code instead (RFC 8628): the CLI prints a short code, the user approves it in
any browser, and the CLI polls until it is approved.

The API key only ever travels in the body of an HTTPS response; it never
appears in a URL, the browser, or a log line.
"""

from __future__ import annotations

import base64
import hashlib
import html
import http.server
import json
import os
import re
import secrets
import socket
import sys
import time
import urllib.parse
import webbrowser
from typing import Any, Callable, TextIO

from bilinc.client import BilincCloudError, _default_transport

LOOPBACK_TIMEOUT_SECONDS = 600
CALLBACK_PATH = "/callback"
_HOSTNAME_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,62}$")


class LoginError(Exception):
    """The sign-in did not complete; the message says what to do next."""


def pkce_pair() -> tuple[str, str]:
    """Return a PKCE (verifier, S256 challenge) pair."""

    verifier = secrets.token_urlsafe(64)[:96]
    digest = hashlib.sha256(verifier.encode("ascii")).digest()
    challenge = base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")
    return verifier, challenge


def machine_name() -> str:
    """A display name for this computer, shown on the approval page and in the key name."""

    name = socket.gethostname().split(".")[0].strip()
    return name if _HOSTNAME_PATTERN.match(name) else "bilinc-cli"


def is_headless() -> bool:
    """True when no local browser can be opened (SSH sessions, servers, containers)."""

    has_display = bool(os.environ.get("DISPLAY") or os.environ.get("WAYLAND_DISPLAY"))
    if os.environ.get("SSH_CONNECTION") or os.environ.get("SSH_TTY"):
        return not has_display
    if sys.platform.startswith("linux"):
        return not has_display
    return False


def _post(
    transport: Callable[..., dict[str, Any]],
    base_url: str,
    path: str,
    payload: dict[str, Any],
    timeout: float,
) -> dict[str, Any]:
    from bilinc import __version__

    return transport(
        "POST",
        f"{base_url.rstrip('/')}{path}",
        headers={
            "Content-Type": "application/json",
            "Accept": "application/json",
            "User-Agent": f"bilinc-cli/{__version__}",
        },
        body=json.dumps(payload).encode("utf-8"),
        timeout=timeout,
    )


_DONE_PAGE = """<!doctype html><html><head><meta charset="utf-8"><title>Bilinc CLI</title>
<style>body{{background:#02040f;color:#e0f0ff;font:16px/1.5 ui-monospace,Menlo,monospace;
display:grid;place-items:center;min-height:100vh;margin:0}}main{{max-width:34rem;padding:2rem}}
h1{{color:#00f0ff;font-size:1.25rem}}</style></head><body><main><h1>{title}</h1><p>{body}</p></main></body></html>"""


class _CallbackServer(http.server.HTTPServer):
    result: dict[str, str] | None = None


class _CallbackHandler(http.server.BaseHTTPRequestHandler):
    server: _CallbackServer

    def do_GET(self) -> None:  # noqa: N802 - http.server API
        parsed = urllib.parse.urlsplit(self.path)
        if parsed.path != CALLBACK_PATH:
            self.send_error(404)
            return
        params = {key: values[0] for key, values in urllib.parse.parse_qs(parsed.query).items() if values}
        if self.server.result is None:
            self.server.result = params
        if params.get("code"):
            title, body = "Bilinc CLI is signed in", "You can close this tab and return to your terminal."
        else:
            title, body = "Sign-in was not completed", "Return to your terminal for details."
        page = _DONE_PAGE.format(title=html.escape(title), body=html.escape(body)).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(page)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("Referrer-Policy", "no-referrer")
        self.end_headers()
        self.wfile.write(page)

    def log_message(self, format: str, *args: Any) -> None:  # noqa: A002 - http.server API
        return


def loopback_login(
    base_url: str,
    *,
    timeout: float = 30.0,
    open_browser: bool = True,
    transport: Callable[..., dict[str, Any]] = _default_transport,
    browser_open: Callable[[str], bool] = webbrowser.open,
    stderr: TextIO = sys.stderr,
    wait_seconds: float = LOOPBACK_TIMEOUT_SECONDS,
    on_listening: Callable[[str], None] | None = None,
) -> dict[str, Any]:
    """Sign in through the browser and return the token response (``api_key``, ``key_name``)."""

    verifier, challenge = pkce_pair()
    state = secrets.token_urlsafe(24)
    server = _CallbackServer(("127.0.0.1", 0), _CallbackHandler)
    server.timeout = 0.5
    try:
        port = server.server_address[1]
        query = urllib.parse.urlencode(
            {
                "port": port,
                "state": state,
                "code_challenge": challenge,
                "code_challenge_method": "S256",
                "hostname": machine_name(),
            }
        )
        url = f"{base_url.rstrip('/')}/cli/authorize?{query}"
        opened = False
        if open_browser:
            print("Opening your browser to sign in to Bilinc Cloud...", file=stderr)
            try:
                opened = bool(browser_open(url))
            except Exception:  # noqa: BLE001 - any browser failure falls back to the printed URL
                opened = False
        if not opened:
            print(f"Open this URL in a browser on this computer to continue:\n\n  {url}\n", file=stderr)
        if on_listening is not None:
            on_listening(url)

        deadline = time.monotonic() + wait_seconds
        while server.result is None and time.monotonic() < deadline:
            server.handle_request()
        result = server.result
    finally:
        server.server_close()

    if result is None:
        raise LoginError("Timed out waiting for the browser. Run bilinc login again, or bilinc login --device.")
    if not secrets.compare_digest(result.get("state", ""), state):
        raise LoginError("The browser returned an unexpected sign-in response. Run bilinc login again.")
    if result.get("error"):
        raise LoginError("Sign-in was denied in the browser.")
    code = result.get("code")
    if not code:
        raise LoginError("The browser did not return a sign-in code. Run bilinc login again.")

    try:
        return _post(transport, base_url, "/api/cli/token", {"code": code, "code_verifier": verifier}, timeout)
    except BilincCloudError as exc:
        raise LoginError(_explain(exc)) from exc


def device_login(
    base_url: str,
    *,
    timeout: float = 30.0,
    transport: Callable[..., dict[str, Any]] = _default_transport,
    stderr: TextIO = sys.stderr,
    sleep: Callable[[float], None] = time.sleep,
    clock: Callable[[], float] = time.monotonic,
) -> dict[str, Any]:
    """Sign in with a code approved in any browser and return the token response."""

    try:
        start = _post(transport, base_url, "/api/cli/device/code", {"hostname": machine_name()}, timeout)
    except BilincCloudError as exc:
        raise LoginError(_explain(exc)) from exc

    print(
        "To sign in, open this page in any browser:\n\n"
        f"  {start['verification_uri_complete']}\n\n"
        f"and confirm the code {start['user_code']}. Waiting for approval...",
        file=stderr,
    )
    interval = max(1, int(start.get("interval", 5)))
    deadline = clock() + int(start.get("expires_in", 600))
    while clock() < deadline:
        sleep(interval)
        try:
            return _post(transport, base_url, "/api/cli/device/token", {"device_code": start["device_code"]}, timeout)
        except BilincCloudError as exc:
            if exc.code == "authorization_pending":
                continue
            if exc.code == "slow_down":
                interval += 5
                continue
            raise LoginError(_explain(exc)) from exc
    raise LoginError("The code expired before it was approved. Run bilinc login --device again.")


def _explain(exc: BilincCloudError) -> str:
    return {
        "access_denied": "Sign-in was denied in the browser.",
        "expired_token": "The code expired before it was approved. Run bilinc login again.",
        "invalid_grant": "The sign-in code was already used or has expired. Run bilinc login again.",
        "api_key_limit_reached": (
            "Your plan has no free API key slot. Revoke an unused key at https://bilinc.space/api-keys, "
            "then run bilinc login again."
        ),
        "rate_limited": "Too many sign-in attempts. Wait a few minutes and run bilinc login again.",
    }.get(exc.code or "", f"Sign-in failed: {exc}")
