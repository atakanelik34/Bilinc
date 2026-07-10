import importlib
import json
import os
import ssl
import tarfile
import zipfile
from pathlib import Path

import pytest


def test_public_api_is_cloud_only():
    import bilinc

    assert bilinc.__version__ == "2.1.4"
    assert bilinc.version == "2.1.4"
    assert "utm_campaign=activation_2_1_3" in bilinc.ACTIVATION_SIGNUP_URL
    assert hasattr(bilinc, "Bilinc")
    assert hasattr(bilinc, "CloudClient")
    assert not hasattr(bilinc, "StatePlane")


class RecordingTransport:
    def __init__(self, response):
        self.response = response
        self.calls = []

    def __call__(self, method, url, *, headers, body, timeout):
        self.calls.append({"method": method, "url": url, "headers": headers, "body": body, "timeout": timeout})
        return self.response


def test_cloud_client_requires_api_key():
    from bilinc import BilincApiKeyRequired, CloudClient

    with pytest.raises(BilincApiKeyRequired) as exc:
        CloudClient(api_key="")

    assert "https://bilinc.space/signup" in str(exc.value)


def test_cloud_client_reads_saved_cli_config(monkeypatch, tmp_path):
    from bilinc import CloudClient
    from bilinc.client import config_path, save_config_api_key

    monkeypatch.delenv("BILINC_API_KEY", raising=False)
    monkeypatch.setenv("BILINC_CONFIG_DIR", str(tmp_path))

    saved_path = save_config_api_key("bil_live_saved_test")
    transport = RecordingTransport({"status": "ok"})
    client = CloudClient(transport=transport)

    client.status()

    assert saved_path == config_path()
    assert transport.calls[0]["headers"]["Authorization"] == "Bearer bil_live_saved_test"


def test_cloud_client_normalizes_base_url():
    from bilinc import CloudClient

    transport = RecordingTransport({"status": "ok"})
    client = CloudClient(api_key="bil_live_test", base_url="https://bilinc.space///", transport=transport)

    client.status()

    assert transport.calls[0]["url"] == "https://bilinc.space/api/cloud/health"


def test_cloud_client_base_url_can_come_from_env(monkeypatch):
    from bilinc import CloudClient

    monkeypatch.setenv("BILINC_BASE_URL", "http://127.0.0.1:9999/")
    transport = RecordingTransport({"status": "ok"})
    client = CloudClient(api_key="bil_live_test", transport=transport)

    client.status()

    assert transport.calls[0]["url"] == "http://127.0.0.1:9999/api/cloud/health"


def test_cloud_client_commit_posts_to_hosted_api():
    from bilinc import CloudClient

    transport = RecordingTransport({"success": True, "id": "mem_123"})
    client = CloudClient(api_key="bil_live_test", base_url="https://bilinc.space", transport=transport)

    result = client.commit("project.status", {"phase": "trial"}, memory_type="semantic", importance=0.8)

    assert result == {"success": True, "id": "mem_123"}
    assert transport.calls == [
        {
            "method": "POST",
            "url": "https://bilinc.space/api/cloud/memory/commit",
            "headers": {
                "Authorization": "Bearer bil_live_test",
                "Content-Type": "application/json",
                "User-Agent": "bilinc-python/2.1.4",
            },
            "body": json.dumps(
                {
                    "key": "project.status",
                    "value": {"phase": "trial"},
                    "memoryType": "semantic",
                    "importance": 0.8,
                    "metadata": {},
                },
                separators=(",", ":"),
            ).encode("utf-8"),
            "timeout": 30.0,
        }
    ]


def test_cloud_client_recall_posts_to_hosted_api():
    from bilinc import CloudClient

    transport = RecordingTransport({"results": [{"key": "project.status"}]})
    client = CloudClient(api_key="bil_live_test", transport=transport)

    result = client.recall("trial status", profile="balanced", limit=5)

    assert result == {"results": [{"key": "project.status"}]}
    call = transport.calls[0]
    assert call["method"] == "POST"
    assert call["url"] == "https://bilinc.space/api/cloud/memory/recall"
    assert json.loads(call["body"].decode("utf-8")) == {"query": "trial status", "profile": "balanced", "limit": 5}


def test_cloud_client_status_reads_hosted_health_endpoint():
    from bilinc import CloudClient

    transport = RecordingTransport({"status": "ok", "mode": "live_cloud"})
    client = CloudClient(api_key="bil_live_test", transport=transport)

    result = client.status()

    assert result == {"status": "ok", "mode": "live_cloud"}
    assert transport.calls == [
        {
            "method": "GET",
            "url": "https://bilinc.space/api/cloud/health",
            "headers": {
                "Authorization": "Bearer bil_live_test",
                "User-Agent": "bilinc-python/2.1.4",
            },
            "body": None,
            "timeout": 30.0,
        }
    ]


def test_default_transport_uses_explicit_ssl_context(monkeypatch):
    from bilinc.client import _default_transport

    captured = {}

    class FakeResponse:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def read(self):
            return b'{"status":"ok"}'

    def fake_urlopen(request, *, timeout, context):
        captured["timeout"] = timeout
        captured["context"] = context
        return FakeResponse()

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)

    result = _default_transport(
        "GET",
        "https://bilinc.space/api/cloud/health",
        headers={},
        body=None,
        timeout=7.0,
    )

    assert result == {"status": "ok"}
    assert captured["timeout"] == 7.0
    assert isinstance(captured["context"], ssl.SSLContext)


def test_cloud_mcp_import_does_not_require_api_key(monkeypatch):
    monkeypatch.delenv("BILINC_API_KEY", raising=False)

    module = importlib.import_module("bilinc.cloud_mcp")

    assert hasattr(module, "build_server")
    assert hasattr(module, "create_client")


def test_cli_signup_and_missing_key_failure(monkeypatch, capsys):
    from bilinc.cli.main import main

    monkeypatch.delenv("BILINC_API_KEY", raising=False)
    monkeypatch.setenv("BILINC_CONFIG_DIR", os.devnull)

    assert main(["signup"]) == 0
    signup_out = capsys.readouterr()
    assert "https://bilinc.space/signup" in signup_out.out
    assert "activation_2_1_3" in signup_out.out
    assert "quicktest" in signup_out.out

    assert main(["commit", "--key", "smoke_key", "--value", "hello"]) == 1
    commit_out = capsys.readouterr()
    assert "https://bilinc.space/signup" in commit_out.err
    assert "Traceback" not in commit_out.err

    assert main(["recall", "--query", "smoke_key"]) == 1
    recall_out = capsys.readouterr()
    assert "https://bilinc.space/signup" in recall_out.err
    assert "Traceback" not in recall_out.err


def test_cli_start_login_doctor_quicktest_and_mcp_config(monkeypatch, capsys, tmp_path):
    from bilinc.cli import main as cli_main

    class FakeClient:
        def __init__(self, api_key=None, base_url="https://bilinc.space", timeout=30.0):
            self.api_key = api_key
            self.base_url = base_url
            self.timeout = timeout

        def status(self):
            return {"status": "ok", "mode": "test"}

        def commit(self, key, value, *, memory_type="semantic", importance=1.0, metadata=None):
            return {"success": True, "key": key, "value": value, "metadata": metadata}

        def recall(self, query, *, profile="balanced", limit=10):
            return {"results": [{"key": query}], "profile": profile, "limit": limit}

    monkeypatch.delenv("BILINC_API_KEY", raising=False)
    monkeypatch.setenv("BILINC_CONFIG_DIR", str(tmp_path))
    monkeypatch.setattr(cli_main, "CloudClient", FakeClient)

    assert cli_main.main(["start"]) == 0
    start_out = capsys.readouterr()
    assert "bilinc login --api-key <key>" in start_out.out
    assert "bilinc quicktest" in start_out.out
    assert "install_guide" in start_out.out
    assert "activation_2_1_3" in start_out.out

    assert cli_main.main(["login", "--api-key", "bil_live_cli_test"]) == 0
    login_out = capsys.readouterr()
    assert "bil_live_cli_test" not in login_out.out
    assert "quicktest" in login_out.out

    assert cli_main.main(["doctor"]) == 0
    doctor_out = capsys.readouterr()
    assert '"api_key_configured": true' in doctor_out.out

    assert cli_main.main(["quicktest", "--key", "agent.memory.bootstrap"]) == 0
    quicktest_out = capsys.readouterr()
    assert '"ok": true' in quicktest_out.out
    assert "agent.memory.bootstrap" in quicktest_out.out

    assert cli_main.main(["mcp", "install"]) == 0
    mcp_out = capsys.readouterr()
    assert "bilinc.cloud_mcp" in mcp_out.out
    assert "bil_live_cli_test" not in mcp_out.out


def _forbidden_package_prefixes(root: str = "") -> tuple[str, ...]:
    return tuple(
        f"{root}{prefix}"
        for prefix in (
            "bilinc/core/",
            "bilinc/storage/",
            "bilinc/eval/",
            "bilinc/observability/",
            "bilinc/integrations/",
            "bilinc/mcp_server/",
            "bilinc/adaptive/",
            "bilinc/retrieval/",
            "bilinc/security/",
            "bilinc/jobs/",
            "bilinc/scheduler.py",
        )
    )


def test_built_wheel_does_not_ship_local_runtime(tmp_path):
    wheelhouse = tmp_path / "dist"
    wheelhouse.mkdir()
    # The implementation verification builds the wheel and sets BILINC_TEST_WHEEL.
    wheel_env = os.environ.get("BILINC_TEST_WHEEL", "")
    if not wheel_env:
        pytest.skip("wheel content check runs after build")
    wheel_path = Path(wheel_env)
    if not wheel_path.exists() or not wheel_path.is_file():
        pytest.skip("wheel content check runs after build")

    with zipfile.ZipFile(wheel_path) as wheel:
        names = set(wheel.namelist())

    assert not any(name.startswith(_forbidden_package_prefixes()) for name in names)
    assert "bilinc/client.py" in names
    assert "bilinc/cloud_mcp.py" in names


def test_built_sdist_does_not_ship_local_runtime_sources():
    sdist_env = os.environ.get("BILINC_TEST_SDIST", "")
    if not sdist_env:
        pytest.skip("sdist content check runs after build")
    sdist_path = Path(sdist_env)
    if not sdist_path.exists() or not sdist_path.is_file():
        pytest.skip("sdist content check runs after build")

    root = f"{sdist_path.name.removesuffix('.tar.gz')}/src/"
    with tarfile.open(sdist_path) as sdist:
        names = set(sdist.getnames())

    assert not any(name.startswith(_forbidden_package_prefixes(root)) for name in names)
    assert f"{root}bilinc/client.py" in names
    assert f"{root}bilinc/cloud_mcp.py" in names
    assert f"{sdist_path.name.removesuffix('.tar.gz')}/tests/test_cloud_only_package.py" in names
    assert not any(
        name.startswith(f"{sdist_path.name.removesuffix('.tar.gz')}/tests/")
        and not name.endswith("tests/test_cloud_only_package.py")
        for name in names
    )
