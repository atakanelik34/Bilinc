"""The API key only goes to an https host, or to this computer over http."""

from __future__ import annotations

import json
import urllib.request

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


def _creds(scheme: str, user: str, secret: str, rest: str) -> str:
    """Build a URL with a user:password part at runtime, so the source holds no credential-shaped literal."""

    return scheme + "://" + user + ":" + secret + "@" + rest


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
        _creds("https", "user", "pass", "bilinc.space"),
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


def test_env_base_url_cannot_move_a_saved_custom_key(monkeypatch):
    save_config_api_key("bil_live_saved", base_url="https://self-hosted.example.com", allow_custom_host=True)
    monkeypatch.setenv("BILINC_BASE_URL", "http://127.0.0.1:9999")

    with pytest.raises(BilincBaseUrlError, match="belongs to https://self-hosted.example.com"):
        CloudClient(transport=RecordingTransport())


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
    for url in (_creds("https", "admin", "s3cret", "proxy.example"), _creds("http", "admin", "s3cret", "evil.example.com")):
        with pytest.raises(BilincBaseUrlError) as caught:
            validate_base_url(url)
        assert "s3cret" not in str(caught.value)
        assert "admin" not in str(caught.value)


def test_cli_error_never_shows_credentials(monkeypatch, capsys):
    monkeypatch.setenv("BILINC_API_KEY", "bil_live_example")
    monkeypatch.setenv("BILINC_BASE_URL", _creds("https", "admin", "s3cret", "proxy.example"))
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


def test_cli_passes_explicit_base_url_to_the_client(monkeypatch):
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

    with pytest.raises(BilincBaseUrlError, match="belongs to https://bilinc.space, not https://other.example"):
        CloudClient(transport=RecordingTransport())


def test_env_base_url_with_env_key_is_fine(monkeypatch):
    save_config_api_key("bil_live_saved")
    monkeypatch.setenv("BILINC_BASE_URL", "https://other.example")
    monkeypatch.setenv("BILINC_API_KEY", "bil_live_env")

    transport = RecordingTransport()
    CloudClient(transport=transport).status()

    assert transport.calls[0]["url"] == "https://other.example/api/cloud/status"


def test_explicit_base_url_always_wins_over_env(monkeypatch):
    monkeypatch.setenv("BILINC_BASE_URL", "https://staging.example")

    transport = RecordingTransport()
    CloudClient(api_key="bil_live_ci", base_url="https://bilinc.space", transport=transport).status()

    assert transport.calls[0]["url"] == "https://bilinc.space/api/cloud/status"


def test_cross_origin_redirect_error_names_the_target():
    from bilinc.client import BilincConnectionError, _default_transport

    srv = _RedirectServer(lambda port: _creds("https", "user", "pw", "elsewhere.example/api"))
    try:
        with pytest.raises(BilincConnectionError) as caught:
            _default_transport("GET", f"http://127.0.0.1:{srv.port}/start", headers={}, body=None, timeout=5)
    finally:
        srv.close()
    message = str(caught.value)
    assert "redirected to https://<redacted>@elsewhere.example/api" in message
    assert "user:pw" not in message
    assert caught.value.retryable is False


def test_explicit_base_url_cannot_take_a_saved_key_to_another_host():
    save_config_api_key("bil_live_saved")
    with pytest.raises(BilincBaseUrlError, match="not https://attacker.example"):
        CloudClient(base_url="https://attacker.example", transport=RecordingTransport())


def test_cli_base_url_cannot_take_a_saved_key_to_another_host(capsys):
    save_config_api_key("bil_live_saved")
    assert main(["--base-url", "https://attacker.example", "status"]) == 1
    assert "belongs to https://bilinc.space" in capsys.readouterr().err


def test_key_saved_for_custom_host_not_sent_to_default():
    save_config_api_key("bil_live_saved", base_url="https://self.example", allow_custom_host=True)
    with pytest.raises(BilincBaseUrlError, match="belongs to https://self.example"):
        CloudClient(base_url="https://bilinc.space", transport=RecordingTransport())


def test_saved_key_is_not_sent_to_a_local_port_either():
    """Any local user can listen on 127.0.0.1, so a saved key is bound to its exact host."""

    save_config_api_key("bil_live_saved")
    with pytest.raises(BilincBaseUrlError):
        CloudClient(base_url="http://127.0.0.1:8000", transport=RecordingTransport())


def test_pre_272_custom_host_config_keeps_working_with_env(monkeypatch):
    path = config_path()
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps({"api_key": "bil_live_saved", "base_url": "https://staging.example"}))
    monkeypatch.setenv("BILINC_BASE_URL", "https://staging.example")

    transport = RecordingTransport()
    CloudClient(transport=transport).status()

    assert transport.calls[0]["url"] == "https://staging.example/api/cloud/status"


def test_pre_272_custom_host_config_not_sent_to_a_third_host(monkeypatch):
    path = config_path()
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps({"api_key": "bil_live_saved", "base_url": "https://staging.example"}))
    monkeypatch.setenv("BILINC_BASE_URL", "https://other.example")

    with pytest.raises(BilincBaseUrlError):
        CloudClient(transport=RecordingTransport())


def test_cli_login_accepts_allow_custom_host_after_login():
    code = main(["--base-url", "https://self.example", "login", "--allow-custom-host", "--api-key", "bil_live_x"])
    assert code == 0
    assert json.loads(config_path().read_text())["allow_custom_host"] is True


def test_cli_login_flag_before_login_still_works():
    code = main(["--allow-custom-host", "--base-url", "https://self.example", "login", "--api-key", "bil_live_x"])
    assert code == 0


def test_same_origin_redirect_that_urllib_refuses_is_not_called_cross_origin():
    from bilinc.client import BilincCloudError, _default_transport

    srv = _RedirectServer(lambda port: f"http://127.0.0.1:{port}/start")  # endless loop on one host
    try:
        with pytest.raises(BilincCloudError) as caught:
            _default_transport("GET", f"http://127.0.0.1:{srv.port}/start", headers={}, body=None, timeout=5)
    finally:
        srv.close()
    assert getattr(caught.value, "code", None) != "cross_origin_redirect"


def test_consented_bad_host_without_key_reports_missing_key():
    from bilinc.client import BilincApiKeyRequired

    path = config_path()
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps({"allow_custom_host": True, "base_url": "http://remote"}))
    with pytest.raises(BilincApiKeyRequired):
        CloudClient(transport=RecordingTransport())
    assert load_config_base_url() is None


def test_saved_key_is_bound_to_its_path():
    save_config_api_key("bil_live_a", base_url="https://proxy.example/tenant-a", allow_custom_host=True)
    with pytest.raises(BilincBaseUrlError):
        CloudClient(base_url="https://proxy.example/tenant-b", transport=RecordingTransport())
    transport = RecordingTransport()
    CloudClient(transport=transport).status()
    assert transport.calls[0]["url"] == "https://proxy.example/tenant-a/api/cloud/status"


def test_cli_flag_and_login_agree_on_the_host(monkeypatch):
    monkeypatch.setenv("BILINC_BASE_URL", "https://self.example")
    assert main(["--base-url", "https://bilinc.space", "login", "--api-key", "bil_live_x"]) == 0
    seen = {}

    def fake_client(*, api_key, base_url, timeout):
        client = CloudClient(api_key=api_key, base_url=base_url, timeout=timeout, transport=RecordingTransport())
        seen["base_url"] = client.base_url
        raise SystemExit(0)

    monkeypatch.setattr("bilinc.cli.main.CloudClient", fake_client)
    with pytest.raises(SystemExit):
        main(["--base-url", "https://bilinc.space", "status"])
    assert seen["base_url"] == "https://bilinc.space"


def test_cli_top_level_api_key_does_not_skip_login_sign_in(monkeypatch):
    """As in 2.7.1, only `login --api-key` saves a key; a global --api-key still signs in."""

    started = []

    def fake_login(base_url, **kwargs):
        started.append(base_url)
        return {"api_key": "bil_live_from_browser"}

    monkeypatch.setattr("bilinc.cli.main.loopback_login", fake_login)
    monkeypatch.setattr("bilinc.cli.main.device_login", fake_login)
    assert main(["--api-key", "bil_live_top", "login"]) == 0
    assert started == ["https://bilinc.space"]
    assert json.loads(config_path().read_text())["api_key"] == "bil_live_from_browser"


def test_redirect_rule():
    from bilinc.client import _redirect_allowed

    assert _redirect_allowed("http://localhost:8080/a", "https://localhost/a")
    assert _redirect_allowed("https://bilinc.space/a", "https://bilinc.space/b")
    assert not _redirect_allowed("https://bilinc.space/a", "http://bilinc.space/a")
    assert not _redirect_allowed("https://bilinc.space/a", "https://www.bilinc.space/a")
    assert not _redirect_allowed("https://bilinc.space/a", "https://bilinc.space:8443/a")


@pytest.mark.parametrize(
    "url, secret",
    [
        (_creds("https", "user", "se/cret", "host.example"), "se/cret"),
        (_creds("https", "user", "sec?ret", "host.example"), "sec"),
        (_creds("https", "user", "sec#ret", "host.example"), "sec"),
        (_creds("http", "admin", "pw", "evil.example.com"), "pw@"),
    ],
)
def test_password_with_url_delimiters_is_never_shown(url, secret):
    with pytest.raises(BilincBaseUrlError) as caught:
        validate_base_url(url)
    assert secret not in str(caught.value)
    assert "user:" not in str(caught.value) and "admin" not in str(caught.value)


def test_http_to_https_upgrade_only_to_443_or_same_port():
    from bilinc.client import _redirect_allowed

    assert _redirect_allowed("http://localhost:8080/a", "https://localhost/a")
    assert _redirect_allowed("http://localhost:8080/a", "https://localhost:8080/a")
    assert not _redirect_allowed("http://localhost:8080/a", "https://localhost:9443/a")


def test_base_url_reassignment_is_refused():
    transport = RecordingTransport()
    client = CloudClient(api_key="bil_live_example", transport=transport)
    client.base_url = "http://evil.example"
    with pytest.raises(BilincBaseUrlError, match="changed after"):
        client.status()
    assert transport.calls == []




@pytest.mark.parametrize("url", ["https://bili\nnc.space", "https://bilinc\t.space", "https://bil inc.space", "https://bilinc\x00.space"])
def test_control_characters_are_refused(url):
    with pytest.raises(BilincBaseUrlError, match="control character"):
        validate_base_url(url)


@pytest.mark.parametrize(
    "url, shown",
    [
        ("https://bilinc.space#a@evil", "https://bilinc.space"),
        ("https://bilinc.space/p@th?q=1", "https://bilinc.space/p@th"),
        (_creds("https", "user", "pw", "host.example/x"), "https://<redacted>@host.example/x"),
        (_creds("https", "user", "se/cret", "host.example"), "https://<redacted>@host.example"),
    ],
)
def test_display_redacts_only_credentials(url, shown):
    from bilinc.client import _display_base_url

    assert _display_base_url(url) == shown


def test_uri_header_redirect_is_reported_as_cross_origin():
    import email.message
    import urllib.error

    from bilinc.client import BilincConnectionError, _default_transport
    import bilinc.client as cm

    headers = email.message.Message()
    headers["URI"] = "https://evil.example/x"

    def fake_open(request, *, timeout, context):
        raise urllib.error.HTTPError(request.full_url, 302, "Found", headers, None)

    import pytest as _pytest

    with _pytest.MonkeyPatch.context() as mp:
        mp.setattr(cm, "_open", fake_open)
        with pytest.raises(BilincConnectionError, match="redirected to https://evil.example/x"):
            _default_transport("GET", "https://bilinc.space/api", headers={}, body=None, timeout=1)


def test_local_server_bypasses_http_proxy(monkeypatch):
    import ssl

    from bilinc.client import _direct_opener_for, _opener_for

    monkeypatch.setenv("HTTP_PROXY", "http://corp-proxy.example:3128")
    monkeypatch.setenv("HTTPS_PROXY", "http://corp-proxy.example:3128")
    _direct_opener_for.cache_clear()
    try:
        context = ssl.create_default_context()

        def proxied(opener):
            return [h for h in opener.handlers if isinstance(h, urllib.request.ProxyHandler) and h.proxies]

        assert proxied(_opener_for(context, direct=False))
        assert not proxied(_opener_for(context, direct=True))
    finally:
        _direct_opener_for.cache_clear()


def test_port_zero_is_refused():
    with pytest.raises(BilincBaseUrlError):
        validate_base_url("https://bilinc.space:0")


def test_display_keeps_host_with_port_and_at_in_path():
    from bilinc.client import _display_base_url

    assert _display_base_url(_creds("http", "example.com", "8080/a", "b")) == _creds("http", "example.com", "8080/a", "b")


def test_saved_key_passed_back_explicitly_goes_home(monkeypatch):
    save_config_api_key("bil_live_self", base_url="https://self.example", allow_custom_host=True)
    transport = RecordingTransport()
    CloudClient(api_key="bil_live_self", transport=transport).status()
    assert transport.calls[0]["url"] == "https://self.example/api/cloud/status"

    monkeypatch.setenv("BILINC_API_KEY", "bil_live_self")
    transport = RecordingTransport()
    CloudClient(transport=transport).status()
    assert transport.calls[0]["url"] == "https://self.example/api/cloud/status"


def test_allow_custom_host_outside_login_warns(capsys):
    main(["--allow-custom-host", "--api-key", "bil_live_x", "--base-url", "http://evil.example", "status"])
    err = capsys.readouterr().err
    assert "plain http" in err
    main(["--allow-custom-host", "start"])
    assert "only applies to bilinc login" in capsys.readouterr().err


@pytest.mark.parametrize("url", ["https://bilinc.space/api?", "https://bilinc.space#", "https://bilinc.space?"])
def test_bare_query_or_fragment_marker_is_refused(url):
    with pytest.raises(BilincBaseUrlError, match="query or a fragment"):
        validate_base_url(url)


def test_digit_password_before_slash_is_refused_without_echo():
    with pytest.raises(BilincBaseUrlError) as caught:
        validate_base_url(_creds("https", "admin", "1234/5", "evil.com"))
    assert "1234" not in str(caught.value) and "admin" not in str(caught.value)


class _PostRedirectServer(_RedirectServer):
    def __init__(self):
        import http.server
        import threading

        outer = self
        self.hits = []

        class Handler(http.server.BaseHTTPRequestHandler):
            def do_POST(self):  # noqa: N802 - http.server API
                outer.hits.append(self.path)
                self.send_response(302)
                self.send_header("Location", f"http://127.0.0.1:{outer.port}/elsewhere")
                self.send_header("Content-Length", "0")
                self.end_headers()

            def do_GET(self):  # noqa: N802 - must never be reached
                outer.hits.append("GET " + self.path)
                self.send_response(405)
                self.send_header("Content-Length", "0")
                self.end_headers()

            def log_message(self, *args):
                return

        self.server = http.server.HTTPServer(("127.0.0.1", 0), Handler)
        self.port = self.server.server_address[1]
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()


def test_redirected_write_is_not_followed():
    from bilinc.client import BilincConnectionError, _default_transport

    srv = _PostRedirectServer()
    try:
        with pytest.raises(BilincConnectionError) as caught:
            _default_transport("POST", f"http://127.0.0.1:{srv.port}/commit", headers={}, body=b"{}", timeout=5)
    finally:
        srv.close()
    assert caught.value.code == "redirected_write"
    assert srv.hits == ["/commit"]


def test_proxied_opener_follows_env_changes(monkeypatch):
    import ssl

    from bilinc.client import _opener_for

    context = ssl.create_default_context()
    monkeypatch.delenv("HTTPS_PROXY", raising=False)
    monkeypatch.delenv("https_proxy", raising=False)
    _opener_for(context, direct=False)
    monkeypatch.setenv("HTTPS_PROXY", "http://corp-proxy.example:3128")
    opener = _opener_for(context, direct=False)
    proxies = [h.proxies for h in opener.handlers if isinstance(h, urllib.request.ProxyHandler)]
    assert any("https" in p for p in proxies)


def test_config_is_read_once_until_it_changes(monkeypatch):
    save_config_api_key("bil_live_saved")
    reads = []
    original = type(config_path()).read_text

    def counting(self, *args, **kwargs):
        reads.append(str(self))
        return original(self, *args, **kwargs)

    monkeypatch.setattr(type(config_path()), "read_text", counting)
    for _ in range(3):
        CloudClient(api_key="bil_live_other", transport=RecordingTransport())
    assert len(reads) <= 1

