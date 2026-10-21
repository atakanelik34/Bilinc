"""Secret scanning on hosted writes: provider shapes are rejected, credential fields redacted.

Fixtures are built at runtime from a hash, so no credential-shaped literal sits in
this file (scripts/check_secret_safety.py scans tracked files).
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import os
import uuid

import pytest

from bilinc.security.secret_scan import REDACTED, find_secret_shape, scan_write

DSN = os.getenv("BILINC_TEST_POSTGRES_DSN")
needs_postgres = pytest.mark.skipif(not DSN, reason="BILINC_TEST_POSTGRES_DSN not set")


def fake(length: int, alphabet: str = "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789", seed: str = "x") -> str:
    """A deterministic random-looking string (no runs, no example words)."""
    out = ""
    counter = 0
    while len(out) < length:
        digest = hashlib.sha256(f"{seed}:{counter}".encode()).digest()
        out += "".join(alphabet[b % len(alphabet)] for b in digest)
        counter += 1
    return out[:length]


UPPER_DIGITS = "ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789"
SHAPES = {
    "aws_access_key": "AK" + "IA" + fake(16, UPPER_DIGITS),
    "github_token": "gh" + "p_" + fake(36),
    "gitlab_token": "gl" + "pat-" + fake(20),
    "slack_token": "xo" + "xb-" + fake(12, "0123456789") + "-" + fake(24),
    "stripe_live_key": "sk" + "_live_" + fake(24),
    "anthropic_api_key": "sk" + "-ant-api03-" + fake(90),
    "openai_api_key": "sk" + "-proj-" + fake(60),
    "google_api_key": "AI" + "za" + fake(35),
    "pypi_token": "py" + "pi-AgEIcHlwaS5vcmc" + fake(60),
    "bilinc_key": "bil" + "_live_" + fake(43),
    "jwt": "ey" + "J" + fake(20) + ".ey" + "J" + fake(30) + "." + fake(40),
    "private_key": "-----BEGIN " + "RSA PRIVATE" + " KEY-----\n" + fake(64),
}


@pytest.mark.parametrize("rule", sorted(SHAPES))
def test_provider_shaped_secrets_are_rejected_by_rule(rule):
    text = f"Deploy notes: use {SHAPES[rule]} for the staging job."
    assert find_secret_shape(text) == rule
    result = scan_write(key="deploy.notes", value=text)
    assert result.rejection is not None
    assert (result.rejection.rule, result.rejection.field) == (rule, "value")


@pytest.mark.parametrize(
    "text",
    [
        str(uuid.uuid4()),
        hashlib.sha256(b"x").hexdigest(),
        "data:image/png;base64," + fake(120, "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/"),
        "integrity sha512-" + fake(86),
        "we use sk-learn and sk-abc for tests",
        "sk" + "_test_" + fake(24),  # Stripe test keys are not rejected
        "pk" + "_live_" + fake(24),  # publishable keys are public
        "your key starts with bil" + "_live_7h3f",  # the dashboard shows only a short prefix
        "AK" + "IA" + "IOSFODNN7" + "EXAMPLE",  # the AWS documentation example key
        "bil" + "_live_" + "placeholder_" + fake(30),
        "gh" + "p_" + "x" * 36,
    ],
)
def test_ordinary_and_documentation_values_are_not_rejected(text):
    assert find_secret_shape(text) is None
    assert scan_write(key="k", value=text).rejection is None


def test_key_metadata_and_reason_are_scanned_too():
    secret = SHAPES["github_token"]
    assert scan_write(key=f"token.{secret}", value="v").rejection.field == "key"
    assert scan_write(key="k", value="v", metadata={"note": secret}).rejection.field == "metadata.note"
    assert scan_write(key="k", value={"steps": ["ok", secret]}).rejection.field == "value.steps[1]"
    assert scan_write(key="k", value="v", reason=f"rotated {secret}").rejection.field == "reason"
    assert scan_write(key="k", value="v", labels={"source": secret}).rejection.field == "source"


def test_commit_rejects_secrets_in_source_and_session_id(tmp_path):
    manager = _manager(tmp_path)
    project = str(uuid.uuid4())

    async def scenario():
        for labels in ({"source": SHAPES["slack_token"]}, {"session_id": SHAPES["jwt"]}):
            with pytest.raises(ValueError, match="secret_detected"):
                await manager.commit(project, key="k", value="v", **labels)
        assert manager._planes == {}
        await manager.close()

    _run(scenario())


def test_credential_fields_are_redacted_with_a_finding_not_rejected():
    password = fake(12, seed="pw") + "7"
    bearer = fake(32, seed="bearer")
    result = scan_write(
        key="ops.smtp",
        value={
            "notes": f"SMTP login uses password={password} and Authorization: Bearer {bearer}",
            "api_key": fake(28, seed="api") + "9",
            "token_budget": "40000000",
            "owner": "Atakan",
        },
    )
    assert result.rejection is None
    assert password not in str(result.value) and bearer not in str(result.value)
    assert result.value["notes"] == f"SMTP login uses password={REDACTED} and Authorization: Bearer {REDACTED}"
    assert result.value["api_key"] == REDACTED
    assert result.value["token_budget"] == "40000000"
    assert {(item.rule, item.field) for item in result.redactions} == {
        ("credential_assignment", "value.notes"),
        ("authorization_header", "value.notes"),
        ("sensitive_field", "value.api_key"),
    }


def test_json_encoded_credentials_inside_a_string_are_redacted():
    api_key = fake(30, seed="json") + "4"
    text = json.dumps({"service": "mailer", "api_key": api_key})
    result = scan_write(key="cfg", value=text)
    assert api_key not in result.value
    assert json.loads(result.value)["api_key"] == REDACTED
    assert [(item.rule, item.field) for item in result.redactions] == [("credential_assignment", "value")]


@pytest.mark.parametrize(
    "value",
    [
        "password: Configured",
        "Basic setup/teardown/notes in the runbook",
        "Token: ~/.config/bilinc/token",
        "password: ${SMTP_PASSWORD}",
        {"api_key": "configured_on_vm_only"},
        {"modal_secret": "elevenlabs voice key and HF_TOKEN"},
    ],
)
def test_prose_paths_and_placeholders_are_left_alone(value):
    result = scan_write(key="k", value=value)
    assert result.rejection is None
    assert result.redactions == []
    assert result.value == value


def _manager(tmp_path):
    from bilinc.cloud.runtime import ProjectRuntimeManager

    return ProjectRuntimeManager(tmp_path)


def _run(coro):
    return asyncio.new_event_loop().run_until_complete(coro)


def test_runtime_rejects_before_loading_the_project(tmp_path):
    manager = _manager(tmp_path)
    project = str(uuid.uuid4())

    async def scenario():
        with pytest.raises(ValueError, match="secret_detected"):
            await manager.commit(project, key="ci.deploy", value=f"key {SHAPES['aws_access_key']}")
        assert manager._planes == {}
        await manager.commit(project, key="ci.deploy", value="uses the vault entry ci/aws")
        with pytest.raises(ValueError, match="secret_detected"):
            await manager.revise(project, key="ci.deploy", value=f"now {SHAPES['bilinc_key']}")
        plane = await manager.get_plane(project)
        assert (await plane.backend.load("ci.deploy")).value == "uses the vault entry ci/aws"
        await manager.close()

    _run(scenario())


def test_runtime_redacts_fields_and_reports_warnings(tmp_path):
    manager = _manager(tmp_path)
    project = str(uuid.uuid4())
    password = fake(14, seed="smtp") + "3"

    async def scenario():
        result = await manager.commit(project, key="ops.smtp", value=f"password={password}")
        assert result["success"] is True
        assert result["warnings"] == [{"code": "secret_redacted", "rule": "credential_assignment", "field": "value"}]
        plane = await manager.get_plane(project)
        assert (await plane.backend.load("ops.smtp")).value == f"password={REDACTED}"
        plain = await manager.commit(project, key="ops.note", value="nothing sensitive")
        assert "warnings" not in plain
        await manager.close()

    _run(scenario())


def test_revise_redacts_value_and_reason_before_storage(tmp_path):
    manager = _manager(tmp_path)
    project = str(uuid.uuid4())
    password = fake(14, seed="rotate") + "5"
    token = fake(20, seed="reason") + "8"

    async def scenario():
        await manager.commit(project, key="ops.smtp", value="password lives in the vault")
        response = await manager.revise(
            project,
            key="ops.smtp",
            value=f"password={password}",
            reason=f"rotated, token={token}",
        )
        assert response["warnings"] == [
            {"code": "secret_redacted", "rule": "credential_assignment", "field": "value"},
            {"code": "secret_redacted", "rule": "credential_assignment", "field": "reason"},
        ]
        plane = await manager.get_plane(project)
        assert (await plane.backend.load("ops.smtp")).value == f"password={REDACTED}"
        history = await manager.history(project, key="ops.smtp")
        latest = history["entries"][0]
        assert latest["reason"] == f"rotated, token={REDACTED}"
        assert password not in str(history) and token not in str(history)
        await manager.close()

    _run(scenario())


def test_forget_and_confirm_mask_secrets_in_the_reason_but_never_refuse(tmp_path):
    manager = _manager(tmp_path)
    project = str(uuid.uuid4())
    secret = SHAPES["github_token"]

    async def scenario():
        await manager.commit(project, key="a", value="first")
        await manager.commit(project, key="b", value="second")
        confirmed = await manager.confirm(project, key="a", reason=f"checked with {secret}")
        forgotten = await manager.forget(project, key="b", reason=f"leaked {secret}")
        assert confirmed["success"] and forgotten["removed"]
        for response in (confirmed, forgotten):
            assert response["warnings"] == [{"code": "secret_redacted", "rule": "github_token", "field": "reason"}]
        for key in ("a", "b"):
            history = await manager.history(project, key=key)
            assert secret not in str(history)
            assert history["entries"][0]["reason"].endswith(REDACTED)
        await manager.close()

    _run(scenario())


def test_snapshot_label_metadata_and_rollback_reason_are_masked(tmp_path):
    manager = _manager(tmp_path)
    project = str(uuid.uuid4())
    secret = SHAPES["bilinc_key"]

    async def scenario():
        await manager.commit(project, key="a", value="first")
        snap = await manager.create_snapshot(project, label=f"before {secret}", metadata={"note": secret})
        assert secret not in json.dumps(await manager.load_snapshot(project, snap.id))
        result = await manager.rollback_execute(
            project, snapshot_id=snap.id, reason=f"undo with {secret}", expected_current_root=None
        )
        assert result["success"] is True
        assert result["warnings"] == [{"code": "secret_redacted", "rule": "bilinc_key", "field": "reason"}]
        plane = await manager.get_plane(project)
        assert secret not in json.dumps(plane.audit.get_history("__system"), default=str)
        await manager.close()

    _run(scenario())


def test_scan_can_be_switched_off(tmp_path, monkeypatch):
    monkeypatch.setenv("BILINC_SECRET_SCAN", "off")
    manager = _manager(tmp_path)

    async def scenario():
        result = await manager.commit(str(uuid.uuid4()), key="k", value=SHAPES["jwt"])
        assert result["success"] is True
        await manager.close()

    _run(scenario())


def test_sidecar_returns_422_secret_detected(tmp_path):
    pytest.importorskip("fastapi")
    from fastapi.testclient import TestClient

    from bilinc.cloud.service import create_app

    headers = {"X-Bilinc-Sidecar-Token": "secret"}
    with TestClient(create_app(runtime_dir=tmp_path, sidecar_token="secret")) as client:
        project = str(uuid.uuid4())
        response = client.post(
            f"/v1/projects/{project}/commit",
            headers=headers,
            json={"key": "ci.deploy", "value": f"use {SHAPES['stripe_live_key']}"},
        )
        assert response.status_code == 422
        assert response.json()["detail"] == "secret_detected"
        assert SHAPES["stripe_live_key"] not in response.text
        assert "secret_scan" in client.get("/health", headers=headers).json()["capabilities"]


@needs_postgres
def test_rejected_secret_never_reaches_postgres(tmp_path, monkeypatch):
    monkeypatch.setenv("BILINC_STORAGE_BACKEND", "postgres")
    monkeypatch.setenv("BILINC_POSTGRES_DSN", DSN)
    from bilinc.storage.postgres_tenancy import project_schema

    manager = _manager(tmp_path)
    project = str(uuid.uuid4())
    secret = SHAPES["anthropic_api_key"]

    async def scenario():
        import asyncpg

        await manager.commit(project, key="llm.config", value="key lives in the vault")
        with pytest.raises(ValueError, match="secret_detected"):
            await manager.revise(project, key="llm.config", value=f"key {secret}")
        await manager.close()
        schema = project_schema(project)
        conn = await asyncpg.connect(DSN)
        try:
            stored = await conn.fetchval(f'SELECT string_agg(value, \' \') FROM "{schema}".bilinc_entries')
            audited = await conn.fetchval(
                f'SELECT string_agg(COALESCE(before_value, \'\') || COALESCE(after_value, \'\'), \' \') FROM "{schema}".audit_log'
            )
            assert secret not in (stored or "")
            assert secret not in (audited or "")
        finally:
            await conn.execute(f'DROP SCHEMA IF EXISTS "{schema}" CASCADE')
            await conn.close()

    _run(scenario())
