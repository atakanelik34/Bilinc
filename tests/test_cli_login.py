"""One-click `bilinc login`: loopback + PKCE and device-code flows."""

from __future__ import annotations

import base64
import hashlib
import io
import json
import stat
import threading
import urllib.parse
import urllib.request
from pathlib import Path

import pytest

from bilinc.cli import login as cli_login
from bilinc.cli.login import LoginError, device_login, loopback_login, pkce_pair
from bilinc.cli.main import main
from bilinc.client import BilincCloudError, CloudClient, BilincApiKeyRequired


def _challenge(verifier: str) -> str:
    return base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()


def test_pkce_pair_is_rfc7636_s256() -> None:
    verifier, challenge = pkce_pair()
    assert 43 <= len(verifier) <= 128
    assert challenge == _challenge(verifier)
    assert pkce_pair()[0] != verifier


def _browser(query: dict[str, str] | None = None, *, tamper_state: bool = False):
    """Plays the site: after approval it sends the browser to the loopback callback."""

    def on_listening(url: str) -> None:
        params = dict(urllib.parse.parse_qsl(urllib.parse.urlsplit(url).query))
        callback = {"state": "tampered-state-value" if tamper_state else params["state"], **(query or {"code": "one-time-code"})}
        target = f"http://127.0.0.1:{params['port']}/callback?{urllib.parse.urlencode(callback)}"

        def hit() -> None:
            with urllib.request.urlopen(target, timeout=5) as response:  # noqa: S310 - loopback test server
                assert b"Bilinc CLI" in response.read()

        threading.Thread(target=hit, daemon=True).start()
        on_listening.url = url  # type: ignore[attr-defined]

    return on_listening


def test_loopback_login_exchanges_the_code_with_the_matching_verifier() -> None:
    calls: list[tuple[str, dict]] = []
    browser = _browser()

    def transport(method, url, *, headers, body, timeout):
        payload = json.loads(body)
        calls.append((url, payload))
        params = dict(urllib.parse.parse_qsl(urllib.parse.urlsplit(browser.url).query))
        assert payload["code"] == "one-time-code"
        assert _challenge(payload["code_verifier"]) == params["code_challenge"]
        return {"api_key": "bil_live_test", "key_name": "CLI · box · 2026-09-25"}

    result = loopback_login(
        "https://bilinc.test",
        open_browser=False,
        transport=transport,
        stderr=io.StringIO(),
        wait_seconds=10,
        on_listening=browser,
    )

    assert result["api_key"] == "bil_live_test"
    assert calls[0][0] == "https://bilinc.test/api/cli/token"
    authorize = urllib.parse.urlsplit(browser.url)
    assert authorize.path == "/cli/authorize"
    params = dict(urllib.parse.parse_qsl(authorize.query))
    assert params["code_challenge_method"] == "S256"
    assert "api_key" not in browser.url


def test_loopback_login_rejects_a_mismatched_state() -> None:
    with pytest.raises(LoginError, match="unexpected"):
        loopback_login(
            "https://bilinc.test",
            open_browser=False,
            transport=lambda *a, **k: pytest.fail("must not exchange a code with a bad state"),
            stderr=io.StringIO(),
            wait_seconds=10,
            on_listening=_browser(tamper_state=True),
        )


def test_loopback_login_reports_a_denial() -> None:
    with pytest.raises(LoginError, match="denied"):
        loopback_login(
            "https://bilinc.test",
            open_browser=False,
            transport=lambda *a, **k: pytest.fail("must not exchange after a denial"),
            stderr=io.StringIO(),
            wait_seconds=10,
            on_listening=_browser({"error": "access_denied"}),
        )


def test_loopback_login_times_out_cleanly() -> None:
    with pytest.raises(LoginError, match="Timed out"):
        loopback_login("https://bilinc.test", open_browser=False, stderr=io.StringIO(), wait_seconds=0.2)


def test_device_login_polls_through_pending_and_slow_down() -> None:
    responses = iter(
        [
            {
                "device_code": "d" * 43,
                "user_code": "BCDF-GHJK",
                "verification_uri": "https://bilinc.test/device",
                "verification_uri_complete": "https://bilinc.test/device?code=BCDF-GHJK",
                "expires_in": 600,
                "interval": 5,
            },
            BilincCloudError("pending", code="authorization_pending", status=400),
            BilincCloudError("slow", code="slow_down", status=400),
            {"api_key": "bil_live_device", "key_name": "CLI · box · 2026-09-25"},
        ]
    )
    sleeps: list[float] = []

    def transport(method, url, *, headers, body, timeout):
        item = next(responses)
        if isinstance(item, Exception):
            raise item
        return item

    stderr = io.StringIO()
    result = device_login(
        "https://bilinc.test",
        transport=transport,
        stderr=stderr,
        sleep=sleeps.append,
        clock=lambda: 0.0,
    )

    assert result["api_key"] == "bil_live_device"
    assert sleeps == [5, 5, 10]
    assert "BCDF-GHJK" in stderr.getvalue()
    assert "bil_live_device" not in stderr.getvalue()


def test_device_login_reports_a_denial() -> None:
    responses = iter(
        [
            {"device_code": "d" * 43, "user_code": "BCDF-GHJK", "verification_uri_complete": "u", "interval": 1},
            BilincCloudError("denied", code="access_denied", status=400),
        ]
    )

    def transport(method, url, *, headers, body, timeout):
        item = next(responses)
        if isinstance(item, Exception):
            raise item
        return item

    with pytest.raises(LoginError, match="denied"):
        device_login("https://bilinc.test", transport=transport, stderr=io.StringIO(), sleep=lambda _: None, clock=lambda: 0.0)


def test_cli_login_saves_the_key_owner_only_and_never_prints_it(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    config_dir = tmp_path / "bilinc-config"
    monkeypatch.setenv("BILINC_CONFIG_DIR", str(config_dir))
    monkeypatch.setattr(cli_login, "is_headless", lambda: False)
    monkeypatch.setattr(
        "bilinc.cli.main.loopback_login",
        lambda base_url, **kwargs: {"api_key": "bil_live_secret_value", "key_name": "CLI · box · 2026-09-25"},
    )

    assert main(["login"]) == 0

    output = capsys.readouterr()
    assert "bil_live_secret_value" not in output.out + output.err
    saved = json.loads((config_dir / "config.json").read_text())
    assert saved["api_key"] == "bil_live_secret_value"
    assert stat.S_IMODE((config_dir / "config.json").stat().st_mode) == 0o600
    assert stat.S_IMODE(config_dir.stat().st_mode) == 0o700


def test_cli_login_uses_the_device_flow_when_asked(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("BILINC_CONFIG_DIR", str(tmp_path / "cfg"))
    monkeypatch.setattr(
        "bilinc.cli.main.device_login",
        lambda base_url, **kwargs: {"api_key": "bil_live_device", "key_name": "CLI · box · 2026-09-25"},
    )
    monkeypatch.setattr(
        "bilinc.cli.main.loopback_login",
        lambda *a, **k: pytest.fail("--device must not open the loopback flow"),
    )

    assert main(["login", "--device"]) == 0


def test_missing_key_error_points_to_one_click_login(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.delenv("BILINC_API_KEY", raising=False)
    monkeypatch.setenv("BILINC_CONFIG_DIR", str(tmp_path / "empty"))
    with pytest.raises(BilincApiKeyRequired) as excinfo:
        CloudClient()
    message = str(excinfo.value)
    assert "bilinc login" in message
    assert "free, no card required" in message
    assert "7-day" not in message
