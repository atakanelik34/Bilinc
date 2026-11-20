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
    path.write_text(json.dumps({"api_key": "bil_live_saved", "base_url": "http://evil.example.com"}))

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
