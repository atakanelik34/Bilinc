"""Encoders. ``OnnxE5Encoder`` is the production model; ``HashingEncoder`` serves tests.

Inputs are already prefixed (``query: `` / ``passage: ``); outputs are
L2-normalized float32 rows.
"""
from __future__ import annotations

import hashlib
import re
import threading
from typing import Protocol, Sequence

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
