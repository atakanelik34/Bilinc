"""
Opt-in cross-encoder reranking for recall results.

Off unless ``BILINC_RERANK_MODEL`` names a Sentence Transformers cross-encoder
(for example ``cross-encoder/ms-marco-MiniLM-L-6-v2``). When configured, the top
``BILINC_RERANK_DEPTH`` fused results (default 100) are rescored against the
query and reordered; everything below that depth keeps its fused order. The
model runs locally (``BILINC_RERANK_DEVICE``, default ``cpu``) and
``BILINC_RERANK_MODEL_REVISION`` can pin a repository revision. If the model
cannot be loaded or scoring fails, recall falls back to the fused order.
"""

from __future__ import annotations

import os
from functools import lru_cache
from typing import Callable, Dict, List, Optional, Tuple

_DEFAULT_DEPTH = 100
_MAX_DOCUMENT_CHARS = 2000  # cross-encoders read ~512 tokens; longer text is truncated


@lru_cache(maxsize=2)
def _load_rerank_model(model_name: str, device: str, revision: str):
    """Load an explicitly configured local cross-encoder, if available."""
    try:
        from sentence_transformers import CrossEncoder

        return CrossEncoder(model_name, device=device, revision=revision or None, max_length=512)
    except Exception:
        return None


def rerank_config() -> Optional[Tuple[str, str, str, int]]:
    """(model, device, revision, depth) when reranking is configured, else None."""
    model_name = os.environ.get("BILINC_RERANK_MODEL", "").strip()
    if not model_name:
        return None
    device = os.environ.get("BILINC_RERANK_DEVICE", "").strip() or "cpu"
    revision = os.environ.get("BILINC_RERANK_MODEL_REVISION", "").strip()
    try:
        depth = max(1, int(os.environ.get("BILINC_RERANK_DEPTH", "") or _DEFAULT_DEPTH))
    except (TypeError, ValueError):
        depth = _DEFAULT_DEPTH
    return model_name, device, revision, depth


def rerank_keys(
    query: str,
    ordered_keys: List[str],
    text_of: Callable[[str], str],
    limit: int,
) -> Tuple[List[str], Dict[str, float]]:
    """Reorder the head of ``ordered_keys`` by cross-encoder score.

    Returns the new order and the scores of the reranked keys. The order is
    unchanged when reranking is off, the model is unavailable, or scoring fails.
    """
    config = rerank_config()
    if config is None or not ordered_keys:
        return ordered_keys, {}
    model_name, device, revision, depth = config
    model = _load_rerank_model(model_name, device, revision)
    if model is None:
        return ordered_keys, {}
    head = ordered_keys[: max(depth, limit)]
    try:
        raw = model.predict(
            [(query, (text_of(key) or "")[:_MAX_DOCUMENT_CHARS]) for key in head],
            batch_size=32,
            show_progress_bar=False,
        )
        scores = {key: float(score) for key, score in zip(head, raw)}
    except Exception:
        return ordered_keys, {}
    position = {key: index for index, key in enumerate(head)}
    reranked = sorted(head, key=lambda key: (-scores[key], position[key]))
    return reranked + ordered_keys[len(head):], scores
