"""The Workers AI encoder, with the HTTP call replaced: no network, no real token."""
from __future__ import annotations

import io
import json

import numpy as np
import pytest

from bilinc.embeddings import encoder as encoder_module
from bilinc.embeddings.encoder import WorkersAIEncoder

ACCOUNT = "0123456789abcdef0123456789abcdef"


@pytest.fixture
def token_file(tmp_path):
    path = tmp_path / "token"
    path.write_text("test-token-value\n", encoding="utf-8")
    return str(path)


class _Response(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def _fake_urlopen(calls, vectors=None, fail=0):
    def urlopen(request, timeout, context):
        calls.append(request)
        if len(calls) <= fail:
            raise OSError("unreachable")
        texts = json.loads(request.data)["text"]
        data = vectors if vectors is not None else [[3.0, 4.0] for _ in texts]
        return _Response(json.dumps({"result": {"data": data}}).encode())

    return urlopen


def test_encodes_with_the_model_prompts_and_normalizes(monkeypatch, token_file):
    calls = []
    monkeypatch.setattr(encoder_module.urllib.request, "urlopen", _fake_urlopen(calls))
    enc = WorkersAIEncoder("@cf/google/embeddinggemma-300m", account_id=ACCOUNT, token_file=token_file)
    rows = enc.encode(["query: nerede", "passage: burada", "plain"])
    assert np.allclose(rows, [[0.6, 0.8]] * 3)
    assert enc.dim == 2 and enc.model_id == "workers-ai:@cf/google/embeddinggemma-300m"
    sent = json.loads(calls[0].data)["text"]
    assert sent == ["task: search result | query: nerede", "title: none | text: burada", "plain"]
    assert calls[0].full_url.endswith(f"/accounts/{ACCOUNT}/ai/run/@cf/google/embeddinggemma-300m")
    assert calls[0].get_header("Authorization") == "Bearer test-token-value"


def test_bge_m3_gets_the_text_without_prefixes(monkeypatch, token_file):
    calls = []
    monkeypatch.setattr(encoder_module.urllib.request, "urlopen", _fake_urlopen(calls))
    WorkersAIEncoder(account_id=ACCOUNT, token_file=token_file).encode(["query: Başvuru"])
    assert json.loads(calls[0].data)["text"] == ["Başvuru"]


def test_retries_then_fails_without_leaking_the_token(monkeypatch, token_file):
    calls = []
    monkeypatch.setattr(encoder_module.urllib.request, "urlopen", _fake_urlopen(calls, fail=10))
    monkeypatch.setattr(encoder_module.time, "sleep", lambda _: None)
    enc = WorkersAIEncoder(account_id=ACCOUNT, token_file=token_file, retries=2)
    with pytest.raises(RuntimeError) as raised:
        enc.encode(["x"])
    assert len(calls) == 3
    assert "test-token-value" not in str(raised.value)
    assert raised.value.__cause__ is None


def test_recovers_after_a_transient_failure(monkeypatch, token_file):
    calls = []
    monkeypatch.setattr(encoder_module.urllib.request, "urlopen", _fake_urlopen(calls, fail=1))
    monkeypatch.setattr(encoder_module.time, "sleep", lambda _: None)
    rows = WorkersAIEncoder(account_id=ACCOUNT, token_file=token_file).encode(["x"])
    assert rows.shape == (1, 2) and len(calls) == 2


def test_a_short_answer_is_an_error(monkeypatch, token_file):
    monkeypatch.setattr(encoder_module.urllib.request, "urlopen", _fake_urlopen([], vectors=[[1.0, 0.0]]))
    with pytest.raises(RuntimeError):
        WorkersAIEncoder(account_id=ACCOUNT, token_file=token_file).encode(["a", "b"])


def test_configuration_is_checked(monkeypatch, tmp_path, token_file):
    monkeypatch.delenv("BILINC_CF_ACCOUNT_ID", raising=False)
    with pytest.raises(ValueError):
        WorkersAIEncoder(token_file=token_file)
    with pytest.raises(ValueError):
        WorkersAIEncoder("@cf/unknown/model", account_id=ACCOUNT, token_file=token_file)
    empty = tmp_path / "empty"
    empty.write_text("", encoding="utf-8")
    with pytest.raises(ValueError):
        WorkersAIEncoder(account_id=ACCOUNT, token_file=str(empty))
    monkeypatch.setenv("BILINC_CF_ACCOUNT_ID", ACCOUNT)
    monkeypatch.setenv("BILINC_CF_AI_TOKEN_FILE", token_file)
    assert WorkersAIEncoder().account_id == ACCOUNT
