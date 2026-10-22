"""Embedding indexing for the hosted runtime: one task per process, every loaded tenant.

The local daemon keeps one SQLite file current; the hosted runtime holds many
Postgres tenants. ``HostedIndexer`` visits the loaded planes in turn, embeds a
bounded number of changed memories per tenant per pass, and removes vectors of
memories that are gone. Writes go through the backend, which drops a vector
whose memory changed or was forgotten while it was being embedded.
"""
from __future__ import annotations

import asyncio
import logging
from typing import Callable, Dict, Iterable, List, Optional

import numpy as np

from bilinc.embeddings.daemon import RECOMMENDED_EXCLUDE_PREFIXES
from bilinc.embeddings.encoder import Encoder
from bilinc.embeddings.text import PASSAGE_PREFIX, chunk_words, memory_text, text_sha

logger = logging.getLogger(__name__)


class HostedIndexer:
    def __init__(
        self,
        encoder: Encoder,
        planes: Callable[[], Iterable[object]],
        *,
        exclude_prefixes: Iterable[str] = RECOMMENDED_EXCLUDE_PREFIXES,
        batch_size: int = 4,
        keys_per_pass: int = 50,
        poll_seconds: float = 10.0,
    ):
        self.encoder = encoder
        self.planes = planes
        self.exclude_prefixes = tuple(prefix for prefix in exclude_prefixes if prefix)
        self.batch_size = max(1, int(batch_size))
        self.keys_per_pass = max(1, int(keys_per_pass))
        self.poll_seconds = float(poll_seconds)
        self._wake = asyncio.Event()

    def nudge(self) -> None:
        """Start the next pass now (after a write) instead of at the next poll."""
        self._wake.set()

    def _embed(self, text: str) -> np.ndarray:
        chunks = [PASSAGE_PREFIX + chunk for chunk in chunk_words(text)]
        parts = [self.encoder.encode(chunks[i:i + self.batch_size]) for i in range(0, len(chunks), self.batch_size)]
        return np.vstack(parts)

    async def index_backend(self, backend) -> Dict[str, int]:
        """One bounded pass over one tenant. ``pending`` > 0 means more work is due."""
        model = self.encoder.model_id
        candidates = await backend.embedding_candidates(model, self.keys_per_pass + 1, self.exclude_prefixes)
        written = touched = 0
        for key, value, updated_at, indexed_sha in candidates[: self.keys_per_pass]:
            text = memory_text(key, value)
            sha = text_sha(text)
            if sha == indexed_sha:
                # Saved again with the same text: the vectors are still right.
                touched += int(await backend.touch_embeddings(key, model, updated_at))
                continue
            try:
                vectors = await asyncio.to_thread(self._embed, text)
            except Exception as exc:  # a memory the encoder rejects must not block the rest
                logger.warning("Embedding failed for one memory: %s", type(exc).__name__)
                continue
            written += int(await backend.write_embeddings(key, model, sha, vectors.tolist(), updated_at))
        removed = await backend.prune_embeddings(model, self.exclude_prefixes)
        return {
            "embedded": written,
            "touched": touched,
            "removed": removed,
            # Only a pass that made progress asks for another right away.
            "pending": int(len(candidates) > self.keys_per_pass and (written + touched) > 0),
        }

    async def run_once(self) -> bool:
        """Visit every loaded tenant once; True when any tenant still has work pending."""
        pending = False
        for plane in list(self.planes()):
            backend = getattr(plane, "backend", None)
            if backend is None or not hasattr(backend, "write_embeddings"):
                continue
            try:
                result = await self.index_backend(backend)
            except Exception as exc:  # one tenant's failure must not stop the others
                logger.warning("Embedding pass failed for %s: %s", getattr(backend, "schema", "?"), type(exc).__name__)
                continue
            if result["embedded"] or result["removed"]:
                logger.info("Embedding pass for %s: %s", getattr(backend, "schema", "?"), result)
            pending = pending or result["pending"] > 0
        return pending

    async def run(self) -> None:
        while True:
            self._wake.clear()
            if await self.run_once():
                await asyncio.sleep(0)
                continue
            try:
                await asyncio.wait_for(self._wake.wait(), self.poll_seconds)
            except asyncio.TimeoutError:
                pass


def build_encoder(name: Optional[str]) -> Optional[Encoder]:
    """The hosted encoder named by ``BILINC_CLOUD_EMBEDDINGS``; None when semantic recall is off."""
    choice = (name or "").strip().lower()
    if choice in {"", "0", "off", "false", "no"}:
        return None
    if choice in {"1", "on", "true", "e5", "onnx-e5"}:
        from bilinc.embeddings.encoder import OnnxE5Encoder

        return OnnxE5Encoder()
    raise ValueError(f"unknown BILINC_CLOUD_EMBEDDINGS value: {name!r}")


__all__: List[str] = ["HostedIndexer", "build_encoder"]
