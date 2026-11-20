"""The API key only goes to an https host, or to this computer over http."""

from __future__ import annotations

import json

import pytest

import bilinc.client as client_module
from bilinc.cli.login import LoginError, device_login, loopback_login
from bilinc.cli.main import main
from bilinc.client import (
    BilincBaseUrlError,
    CloudClient,
    config_path,
    load_config_base_url,
    save_config_api_key,
    validate_base_url,
)


class RecordingTransport:
    def __init__(self) -> None:
        self.calls: list[dict] = []

    def __call__(self, method, url, *, headers, body, timeout):
        self.calls.append({"method": method, "url": url, "headers": headers})
        return {"status": "ok"}


@pytest.fixture(autouse=True)
def _isolated(monkeypatch, tmp_path):
    monkeypatch.setenv("BILINC_CONFIG_DIR", str(tmp_path / "cfg"))
    monkeypatch.delenv("BILINC_API_KEY", raising=False)
    monkeypatch.delenv("BILINC_BASE_URL", raising=False)
    monkeypatch.setattr(client_module, "_WARNED_HOSTS", set())


@pytest.mark.parametrize(
    "url, expected",
    [
        ("https://bilinc.space/", "https://bilinc.space"),
        ("https://self-hosted.example.com:8443", "https://self-hosted.example.com:8443"),
        ("http://localhost:8000", "http://localhost:8000"),
        ("http://127.0.0.1:9999/", "http://127.0.0.1:9999"),
        ("http://[::1]:8000", "http://[::1]:8000"),
        ("http://127.0.0.2:8000", "http://127.0.0.2:8000"),
        ("http://[0:0:0:0:0:0:0:1]:8000", "http://[0:0:0:0:0:0:0:1]:8000"),
        ("http://localhost.:8000", "http://localhost.:8000"),
        ("HTTPS://Bilinc.Space", "HTTPS://Bilinc.Space"),
    ],
)
def test_accepted_base_urls(url, expected):
    assert validate_base_url(url) == expected


@pytest.mark.parametrize(
    "url",
    [
        "http://bilinc.space",
        "http://evil.example.com",
        "http://localhost.evil.example.com",
        "ftp://bilinc.space",
        "bilinc.space",
        "",
        "   ",
        "https://",
        "https://user:pass@bilinc.space",
        "https://bilinc.space?x=1",
        "https://bilinc.space#frag",
        "https://bilinc.space:notaport",
        None,
    ],
)
def test_refused_base_urls(url):
    with pytest.raises(BilincBaseUrlError):
        validate_base_url(url)


def test_base_url_error_is_a_value_error():
    assert issubclass(BilincBaseUrlError, ValueError)


def test_client_refuses_plain_http_host():
    with pytest.raises(BilincBaseUrlError):
        CloudClient(api_key="bil_live_example", base_url="http://evil.example.com", transport=RecordingTransport())


def test_client_refuses_plain_http_from_env(monkeypatch):
    monkeypatch.setenv("BILINC_BASE_URL", "http://evil.example.com")
    with pytest.raises(BilincBaseUrlError):
        CloudClient(api_key="bil_live_example", transport=RecordingTransport())


def test_client_warns_once_for_custom_https_host(capsys):
    for _ in range(2):
        CloudClient(api_key="bil_live_example", base_url="https://self-hosted.example.com", transport=RecordingTransport())
    err = capsys.readouterr().err
    assert err.count("sending your API key to https://self-hosted.example.com") == 1


def test_client_does_not_warn_for_default_or_loopback(capsys):
    CloudClient(api_key="bil_live_example", transport=RecordingTransport())
    CloudClient(api_key="bil_live_example", base_url="http://127.0.0.1:9999", transport=RecordingTransport())
    assert capsys.readouterr().err == ""


def test_save_refuses_custom_host_without_consent():
    with pytest.raises(BilincBaseUrlError, match="--allow-custom-host"):
        save_config_api_key("bil_live_example", base_url="https://self-hosted.example.com")
    assert not config_path().exists()


def test_save_refuses_plain_http_even_with_consent():
    with pytest.raises(BilincBaseUrlError):
        save_config_api_key("bil_live_example", base_url="http://evil.example.com", allow_custom_host=True)
    assert not config_path().exists()


def test_saved_key_goes_back_to_its_host():
    save_config_api_key("bil_live_saved", base_url="https://self-hosted.example.com/", allow_custom_host=True)
    assert json.loads(config_path().read_text())["base_url"] == "https://self-hosted.example.com"

    transport = RecordingTransport()
    CloudClient(transport=transport).status()

    assert transport.calls[0]["url"] == "https://self-hosted.example.com/api/cloud/status"
    assert transport.calls[0]["headers"]["Authorization"] == "Bearer bil_live_saved"


def test_env_key_is_not_paired_with_saved_host(monkeypatch):
    save_config_api_key("bil_live_saved", base_url="https://self-hosted.example.com", allow_custom_host=True)
    monkeypatch.setenv("BILINC_API_KEY", "bil_live_env")

    transport = RecordingTransport()
    CloudClient(transport=transport).status()

    assert transport.calls[0]["url"] == "https://bilinc.space/api/cloud/status"


def test_env_base_url_wins_over_saved_host(monkeypatch):
    save_config_api_key("bil_live_saved", base_url="https://self-hosted.example.com", allow_custom_host=True)
    monkeypatch.setenv("BILINC_BASE_URL", "http://127.0.0.1:9999")

    transport = RecordingTransport()
    CloudClient(transport=transport).status()

    assert transport.calls[0]["url"] == "http://127.0.0.1:9999/api/cloud/status"


def test_tampered_saved_host_is_refused():
    path = config_path()
    path.parent.mkdir(parents=True)
    path.write_text(
        json.dumps({"api_key": "bil_live_saved", "base_url": "http://evil.example.com", "allow_custom_host": True})
    )

    with pytest.raises(BilincBaseUrlError, match="run bilinc login again"):
        CloudClient(transport=RecordingTransport())
    with pytest.raises(BilincBaseUrlError):
        load_config_base_url()


def test_config_without_base_url_uses_default():
    path = config_path()
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps({"api_key": "bil_live_saved"}))

    transport = RecordingTransport()
    CloudClient(transport=transport).status()

    assert transport.calls[0]["url"] == "https://bilinc.space/api/cloud/status"


def test_cli_refuses_plain_http_base_url(capsys):
    assert main(["--base-url", "http://evil.example.com", "status"]) == 1
    assert "plain http" in capsys.readouterr().err


def test_cli_login_custom_host_needs_flag_before_sign_in(monkeypatch, capsys):
    def fail(*args, **kwargs):  # pragma: no cover - must not be reached
        raise AssertionError("sign-in must not start")

    monkeypatch.setattr("bilinc.cli.main.loopback_login", fail)
    monkeypatch.setattr("bilinc.cli.main.device_login", fail)

    assert main(["--base-url", "https://self-hosted.example.com", "login"]) == 1
    assert "--allow-custom-host" in capsys.readouterr().err
    assert not config_path().exists()


def test_cli_login_api_key_custom_host_with_flag(capsys):
    code = main(
        [
            "--base-url",
            "https://self-hosted.example.com",
            "--allow-custom-host",
            "login",
            "--api-key",
            "bil_live_example",
        ]
    )
    assert code == 0
    assert json.loads(config_path().read_text())["base_url"] == "https://self-hosted.example.com"


def test_login_flows_refuse_plain_http_before_any_request():
    transport = RecordingTransport()
    with pytest.raises(LoginError):
        device_login("http://evil.example.com", transport=transport)
    with pytest.raises(LoginError):
        loopback_login("http://evil.example.com", transport=transport, open_browser=False)
    assert transport.calls == []


def test_error_message_never_shows_credentials():
    for url in ("https://admin:s3cret@proxy.example", "http://admin:s3cret@evil.example.com"):
        with pytest.raises(BilincBaseUrlError) as caught:
            validate_base_url(url)
        assert "s3cret" not in str(caught.value)
        assert "admin" not in str(caught.value)


def test_cli_error_never_shows_credentials(monkeypatch, capsys):
    monkeypatch.setenv("BILINC_API_KEY", "bil_live_example")
    monkeypatch.setenv("BILINC_BASE_URL", "https://admin:s3cret@proxy.example")
    assert main(["status"]) == 1
    assert "s3cret" not in capsys.readouterr().err


@pytest.mark.parametrize("url", ["https://bilinc.space:443", "HTTPS://BILINC.SPACE/", "https://bilinc.space"])
def test_default_host_spellings_count_as_default(url, capsys):
    path = save_config_api_key("bil_live_example", base_url=url)
    assert "allow_custom_host" not in json.loads(path.read_text())
    CloudClient(api_key="bil_live_example", base_url=url, transport=RecordingTransport())
    assert capsys.readouterr().err == ""


def test_pre_272_config_with_custom_host_keeps_default(capsys):
    """2.7.1 saved --base-url without consent and never read it: keep sending to bilinc.space."""

    path = config_path()
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps({"api_key": "bil_live_saved", "base_url": "https://staging.example"}))

    transport = RecordingTransport()
    CloudClient(transport=transport).status()

    assert transport.calls[0]["url"] == "https://bilinc.space/api/cloud/status"
    assert load_config_base_url() is None


def test_custom_host_consent_is_recorded():
    path = save_config_api_key("bil_live_saved", base_url="https://self.example", allow_custom_host=True)
    assert json.loads(path.read_text()) == {
        "api_key": "bil_live_saved",
        "base_url": "https://self.example",
        "allow_custom_host": True,
    }


def test_explicit_default_base_url_wins_over_saved_host():
    save_config_api_key("bil_live_saved", base_url="https://self.example", allow_custom_host=True)

    transport = RecordingTransport()
    CloudClient(base_url="https://bilinc.space", transport=transport).status()

    assert transport.calls[0]["url"] == "https://bilinc.space/api/cloud/status"


def test_cli_explicit_default_base_url_wins_over_saved_host(monkeypatch):
    save_config_api_key("bil_live_saved", base_url="https://self.example", allow_custom_host=True)
    seen = {}

    def fake_client(*, api_key, base_url, timeout):
        seen["base_url"] = base_url
        raise SystemExit(0)

    monkeypatch.setattr("bilinc.cli.main.CloudClient", fake_client)
    with pytest.raises(SystemExit):
        main(["--base-url", "https://bilinc.space", "status"])
    assert seen["base_url"] == "https://bilinc.space"


def test_cli_login_signs_in_where_env_points(monkeypatch, capsys):
    monkeypatch.setenv("BILINC_BASE_URL", "https://other.example")

    def fail(*args, **kwargs):  # pragma: no cover - must not be reached
        raise AssertionError("sign-in must not start")

    monkeypatch.setattr("bilinc.cli.main.loopback_login", fail)
    monkeypatch.setattr("bilinc.cli.main.device_login", fail)

    assert main(["login"]) == 1
    assert "https://other.example" in capsys.readouterr().err


def test_cli_login_uses_env_host_with_consent(monkeypatch):
    monkeypatch.setenv("BILINC_BASE_URL", "https://other.example")
    assert main(["--allow-custom-host", "login", "--api-key", "bil_live_example"]) == 0
    assert json.loads(config_path().read_text())["base_url"] == "https://other.example"


def test_package_exports_base_url_error():
    from bilinc import BilincBaseUrlError as exported

    assert exported is BilincBaseUrlError


class _RedirectServer:
    """A local https-less server that redirects every request to ``target``."""

    def __init__(self, target_for):
        import http.server
        import threading

        outer = self
        self.hits: list[tuple[str, str | None]] = []

        class Handler(http.server.BaseHTTPRequestHandler):
            def do_GET(self):  # noqa: N802 - http.server API
                outer.hits.append((self.path, self.headers.get("Authorization")))
                if self.path.startswith("/final"):
                    body = b'{"status": "ok"}'
                    self.send_response(200)
                    self.send_header("Content-Type", "application/json")
                    self.send_header("Content-Length", str(len(body)))
                    self.end_headers()
                    self.wfile.write(body)
                    return
                self.send_response(302)
                self.send_header("Location", target_for(outer.port))
                self.send_header("Content-Length", "0")
                self.end_headers()

            def log_message(self, *args):
                return

        self.server = http.server.HTTPServer(("127.0.0.1", 0), Handler)
        self.port = self.server.server_address[1]
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()

    def close(self):
        self.server.shutdown()
        self.server.server_close()


def test_transport_follows_same_origin_redirect():
    from bilinc.client import _default_transport

    srv = _RedirectServer(lambda port: f"http://127.0.0.1:{port}/final")
    try:
        result = _default_transport(
            "GET", f"http://127.0.0.1:{srv.port}/start", headers={"Authorization": "Bearer k"}, body=None, timeout=5
        )
    finally:
        srv.close()
    assert result == {"status": "ok"}
    assert srv.hits[-1] == ("/final", "Bearer k")


def test_transport_refuses_cross_origin_redirect():
    from bilinc.client import BilincCloudError, _default_transport

    other = _RedirectServer(lambda port: "http://127.0.0.1:1/never")
    srv = _RedirectServer(lambda port: f"http://localhost:{other.port}/final")
    try:
        with pytest.raises(BilincCloudError):
            _default_transport(
                "GET", f"http://127.0.0.1:{srv.port}/start", headers={"Authorization": "Bearer k"}, body=None, timeout=5
            )
    finally:
        srv.close()
        other.close()
    assert other.hits == []


def test_pre_272_config_with_unsafe_host_still_works(capsys):
    """2.7.1 saved any --base-url unchecked and never read it; that must not break the upgrade."""

    path = config_path()
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps({"api_key": "bil_live_saved", "base_url": "http://staging.internal"}))

    transport = RecordingTransport()
    CloudClient(transport=transport).status()

    assert transport.calls[0]["url"] == "https://bilinc.space/api/cloud/status"


def test_cli_start_does_not_crash_on_unsafe_consented_config(capsys):
    path = config_path()
    path.parent.mkdir(parents=True)
    path.write_text(
        json.dumps({"api_key": "bil_live_saved", "base_url": "http://example.com", "allow_custom_host": True})
    )
    assert main(["start"]) == 1
    assert "bilinc: error:" in capsys.readouterr().err


def test_env_base_url_cannot_take_a_saved_key_to_another_host(monkeypatch):
    save_config_api_key("bil_live_saved")
    monkeypatch.setenv("BILINC_BASE_URL", "https://other.example")

    with pytest.raises(BilincBaseUrlError, match="belongs to https://bilinc.space"):
        CloudClient(transport=RecordingTransport())


def test_env_base_url_with_env_key_is_fine(monkeypatch):
    save_config_api_key("bil_live_saved")
    monkeypatch.setenv("BILINC_BASE_URL", "https://other.example")
    monkeypatch.setenv("BILINC_API_KEY", "bil_live_env")

    transport = RecordingTransport()
    CloudClient(transport=transport).status()

    assert transport.calls[0]["url"] == "https://other.example/api/cloud/status"


def test_explicit_default_still_honours_env_override(monkeypatch):
    monkeypatch.setenv("BILINC_BASE_URL", "https://staging.example")

    transport = RecordingTransport()
    CloudClient(api_key="bil_live_ci", base_url="https://bilinc.space", transport=transport).status()

    assert transport.calls[0]["url"] == "https://staging.example/api/cloud/status"


def test_cross_origin_redirect_error_names_the_target():
    from bilinc.client import BilincConnectionError, _default_transport

    srv = _RedirectServer(lambda port: "https://user:pw@elsewhere.example/api")
    try:
        with pytest.raises(BilincConnectionError) as caught:
            _default_transport("GET", f"http://127.0.0.1:{srv.port}/start", headers={}, body=None, timeout=5)
    finally:
        srv.close()
    message = str(caught.value)
    assert "redirected to https://elsewhere.example/api" in message
    assert "user:pw" not in message
    assert caught.value.retryable is False

