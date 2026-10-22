"""Encoders. ``OnnxE5Encoder`` runs on this machine, ``WorkersAIEncoder`` on Cloudflare
Workers AI; ``HashingEncoder`` serves tests.

Inputs are already prefixed (``query: `` / ``passage: ``); outputs are
L2-normalized float32 rows.
"""
from __future__ import annotations

import hashlib
import json
import logging
import os
import re
import threading
import time
import urllib.request
from pathlib import Path
from typing import Optional, Protocol, Sequence

import numpy as np

# multilingual-e5-small as an int8 ONNX graph. Both repositories are pinned:
# a silently updated graph or tokenizer would change every stored vector.
E5_ONNX_REPO = "Xenova/multilingual-e5-small"
E5_ONNX_REVISION = "761b726dd34fb83930e26aab4e9ac3899aa1fa78"
E5_ONNX_FILE = "onnx/model_quantized.onnx"
E5_TOKENIZER_REPO = "intfloat/multilingual-e5-small"
E5_TOKENIZER_REVISION = "614241f622f53c4eeff9890bdc4f31cfecc418b3"
E5_MAX_TOKENS = 512


class Encoder(Protocol):
    model_id: str
    dim: int

    def encode(self, texts: Sequence[str]) -> np.ndarray: ...


class OnnxE5Encoder:
    """multilingual-e5-small, int8, on onnxruntime: no torch, about 0.5 GB resident."""

    dim = 384

    def __init__(self, threads: int = 2):
        import onnxruntime as ort
        from huggingface_hub import hf_hub_download
        from tokenizers import Tokenizer

        options = ort.SessionOptions()
        options.intra_op_num_threads = max(1, int(threads))
        options.inter_op_num_threads = 1
        # The default arena keeps the largest batch's buffers for the process
        # lifetime (several GB after long chunks); a daemon must stay small.
        options.enable_cpu_mem_arena = False
        options.enable_mem_pattern = False
        model_path = hf_hub_download(E5_ONNX_REPO, E5_ONNX_FILE, revision=E5_ONNX_REVISION)
        self._session = ort.InferenceSession(model_path, options, providers=["CPUExecutionProvider"])
        self._inputs = {item.name for item in self._session.get_inputs()}
        tokenizer = Tokenizer.from_file(
            hf_hub_download(E5_TOKENIZER_REPO, "tokenizer.json", revision=E5_TOKENIZER_REVISION)
        )
        tokenizer.enable_truncation(max_length=E5_MAX_TOKENS)
        tokenizer.enable_padding(pad_id=tokenizer.token_to_id("<pad>"), pad_token="<pad>")
        self._tokenizer = tokenizer
        self._lock = threading.Lock()
        self.model_id = f"{E5_ONNX_REPO}@{E5_ONNX_REVISION[:12]}:int8"

    def encode(self, texts: Sequence[str]) -> np.ndarray:
        if not texts:
            return np.zeros((0, self.dim), dtype=np.float32)
        with self._lock:
            encoded = self._tokenizer.encode_batch(list(texts))
            ids = np.array([item.ids for item in encoded], dtype=np.int64)
            mask = np.array([item.attention_mask for item in encoded], dtype=np.int64)
            feed = {"input_ids": ids, "attention_mask": mask}
            if "token_type_ids" in self._inputs:
                feed["token_type_ids"] = np.zeros_like(ids)
            hidden = self._session.run(None, feed)[0]
        weights = mask[..., None].astype(hidden.dtype)
        pooled = (hidden * weights).sum(axis=1) / np.clip(weights.sum(axis=1), 1e-9, None)
        pooled /= np.clip(np.linalg.norm(pooled, axis=1, keepdims=True), 1e-12, None)
        return pooled.astype(np.float32)


logger = logging.getLogger(__name__)

# The callers' e5 prefixes, rewritten into each model's own prompt format.
_QUERY, _PASSAGE = "query: ", "passage: "
WORKERS_AI_PROMPTS = {
    "@cf/baai/bge-m3": ("", ""),
    "@cf/google/embeddinggemma-300m": ("task: search result | query: ", "title: none | text: "),
}
WORKERS_AI_DEFAULT_MODEL = "@cf/baai/bge-m3"
WORKERS_AI_TOKEN_FILE = Path.home() / ".config" / "bilinc" / "cf-ai-token"


class WorkersAIEncoder:
    """An embedding model on Cloudflare Workers AI: no model in this process.

    The account comes from ``BILINC_CF_ACCOUNT_ID``; the API token is read from
    ``BILINC_CF_AI_TOKEN_FILE`` (default ``~/.config/bilinc/cf-ai-token``) and
    never logged. Memory text leaves the machine, so this encoder is opt-in.
    """

    def __init__(
        self,
        model: str = WORKERS_AI_DEFAULT_MODEL,
        account_id: Optional[str] = None,
        token_file: Optional[str] = None,
        timeout: float = 30.0,
        retries: int = 2,
    ):
        if model not in WORKERS_AI_PROMPTS:
            raise ValueError(f"unsupported Workers AI model: {model}")
        self.account_id = (account_id or os.environ.get("BILINC_CF_ACCOUNT_ID", "")).strip()
        if not re.fullmatch(r"[0-9a-f]{32}", self.account_id):
            raise ValueError("BILINC_CF_ACCOUNT_ID must be a Cloudflare account id")
        path = Path(token_file or os.environ.get("BILINC_CF_AI_TOKEN_FILE") or WORKERS_AI_TOKEN_FILE).expanduser()
        if path.stat().st_mode & 0o077:
            logger.warning("%s is readable by other users; chmod 600 it", path)
        token = path.read_text(encoding="utf-8").strip()
        if not token:
            raise ValueError("the Workers AI token file is empty")
        self._auth = "Bearer " + token
        self.model = model
        self.model_id = f"workers-ai:{model}"
        self.dim = 0  # known after the first call
        self.timeout = float(timeout)
        self.retries = max(0, int(retries))
        self._url = f"https://api.cloudflare.com/client/v4/accounts/{self.account_id}/ai/run/{model}"
        self._context = _tls_context()

    def _prompt(self, text: str) -> str:
        query, passage = WORKERS_AI_PROMPTS[self.model]
        if text.startswith(_QUERY):
            return query + text[len(_QUERY):]
        if text.startswith(_PASSAGE):
            return passage + text[len(_PASSAGE):]
        return text

    def encode(self, texts: Sequence[str]) -> np.ndarray:
        return self._run(texts, self.timeout, self.retries)

    def encode_query(self, text: str, timeout: float = 1.5) -> np.ndarray:
        """One query vector, fast or not at all: recall stops waiting after about a second anyway."""
        return self._run([text], timeout, 0)[0]

    def _run(self, texts: Sequence[str], timeout: float, retries: int) -> np.ndarray:
        if not texts:
            return np.zeros((0, self.dim), dtype=np.float32)
        body = json.dumps({"text": [self._prompt(text) for text in texts]}).encode("utf-8")
        request = urllib.request.Request(
            self._url, data=body, headers={"Authorization": self._auth, "Content-Type": "application/json"}
        )
        for attempt in range(retries + 1):
            try:
                with urllib.request.urlopen(request, timeout=timeout, context=self._context) as response:
                    payload = json.loads(response.read())
                break
            except Exception as exc:
                status = getattr(exc, "code", None)
                # A rejected request (bad input, revoked token) fails the same way again.
                rejected = isinstance(status, int) and 400 <= status < 500 and status not in (408, 429)
                if attempt == retries or rejected:
                    # The message names the failure, never the request or its headers.
                    detail = f"{type(exc).__name__} {status}" if isinstance(status, int) else type(exc).__name__
                    raise WorkersAIError(f"Workers AI request failed: {detail}", status) from None
                time.sleep(0.5 * 2 ** attempt)
        try:
            rows = np.asarray(payload["result"]["data"], dtype=np.float32)
        except (KeyError, TypeError, ValueError):
            raise WorkersAIError("Workers AI returned no vectors", None) from None
        if rows.ndim != 2 or rows.shape[0] != len(texts):
            raise WorkersAIError("Workers AI returned a different number of vectors", None)
        rows /= np.clip(np.linalg.norm(rows, axis=1, keepdims=True), 1e-12, None)
        self.dim = int(rows.shape[1])
        return rows


class WorkersAIError(RuntimeError):
    def __init__(self, message: str, status: Optional[int]):
        super().__init__(message)
        self.status = status if isinstance(status, int) else None


def _tls_context():
    """System trust store, or certifi's bundle when Python ships without one (python.org macOS builds)."""
    import ssl

    try:
        import certifi
    except ImportError:
        return ssl.create_default_context()
    return ssl.create_default_context(cafile=certifi.where())


class HashingEncoder:
    """Deterministic bag-of-words vectors for tests: texts that share words are similar."""

    def __init__(self, dim: int = 64, model_id: str = "test-hashing"):
        self.dim = dim
        self.model_id = model_id

    def encode(self, texts: Sequence[str]) -> np.ndarray:
        rows = np.zeros((len(texts), self.dim), dtype=np.float32)
        for row, text in enumerate(texts):
            for word in re.findall(r"\w+", str(text).lower()):
                if word in {"query", "passage"}:
                    continue
                digest = hashlib.sha256(word.encode("utf-8")).digest()
                rows[row, int.from_bytes(digest[:4], "little") % self.dim] += 1.0
        norms = np.linalg.norm(rows, axis=1, keepdims=True)
        return rows / np.clip(norms, 1e-12, None)
