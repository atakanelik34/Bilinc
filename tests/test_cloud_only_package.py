import importlib
import json
import os
import tarfile
import zipfile
from pathlib import Path

import pytest


def test_public_api_is_cloud_only():
    import bilinc

    assert bilinc.__version__ == "2.1.1"
    assert bilinc.version == "2.1.1"
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


def test_cloud_client_normalizes_base_url():
    from bilinc import CloudClient

    transport = RecordingTransport({"status": "ok"})
    client = CloudClient(api_key="bil_live_test", base_url="https://bilinc.space///", transport=transport)

    client.status()

    assert transport.calls[0]["url"] == "https://bilinc.space/api/cloud/health"


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
                "User-Agent": "bilinc-python/2.1.1",
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
                "User-Agent": "bilinc-python/2.1.1",
            },
            "body": None,
            "timeout": 30.0,
        }
    ]


def test_cloud_mcp_import_does_not_require_api_key(monkeypatch):
    monkeypatch.delenv("BILINC_API_KEY", raising=False)

    module = importlib.import_module("bilinc.cloud_mcp")

    assert hasattr(module, "build_server")
    assert hasattr(module, "create_client")


def test_cli_signup_and_missing_key_failure(monkeypatch, capsys):
    from bilinc.cli.main import main

    monkeypatch.delenv("BILINC_API_KEY", raising=False)

    assert main(["signup"]) == 0
    signup_out = capsys.readouterr()
    assert "https://bilinc.space/signup" in signup_out.out

    assert main(["commit", "--key", "smoke_key", "--value", "hello"]) == 1
    commit_out = capsys.readouterr()
    assert "https://bilinc.space/signup" in commit_out.err
    assert "Traceback" not in commit_out.err

    assert main(["recall", "--query", "smoke_key"]) == 1
    recall_out = capsys.readouterr()
    assert "https://bilinc.space/signup" in recall_out.err
    assert "Traceback" not in recall_out.err


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
