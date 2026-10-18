"""
Opt-in cross-encoder reranking for recall results.

Off unless ``BILINC_RERANK_MODEL`` names a Sentence Transformers cross-encoder
(for example ``cross-encoder/ms-marco-MiniLM-L-6-v2``). When configured, the top
``BILINC_RERANK_DEPTH`` fused results (default 100), and never more than
``HEAD_PER_RESULT`` times the recall limit (at least ``MIN_HEAD``), are rescored
against the query and reordered; everything below keeps its fused order. Scores
are the model's raw logits (no sigmoid), whatever activation the model's config
names, so tie tolerances mean the same thing for every model. The
model runs locally (``BILINC_RERANK_DEVICE``, default ``cpu``) and
``BILINC_RERANK_MODEL_REVISION`` can pin a repository revision. If the model
cannot be loaded or scoring fails, recall falls back to the fused order, logs a
warning, and tries to load the model again after ``RETRY_AFTER_SECONDS``. The
first recall after start waits for the model to load (and download, if it is not
cached); recalls that arrive meanwhile skip rerank. One model instance scores one
batch at a time, because tokenizers are not safe for concurrent use.
"""

from __future__ import annotations

import logging
import os
import threading
import time
from typing import Callable, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

_DEFAULT_DEPTH = 100
_MAX_DOCUMENT_CHARS = 2000  # cross-encoders read ~512 tokens; longer text is truncated
RETRY_AFTER_SECONDS = 300.0
HEAD_PER_RESULT = 5
MIN_HEAD = 20

_models: Dict[Tuple[str, str, str], object] = {}
_predict_locks: Dict[Tuple[str, str, str], threading.Lock] = {}
_failed_at: Dict[Tuple[str, str, str], float] = {}
_loading: set = set()
_lock = threading.Lock()


def _load_rerank_model(model_name: str, device: str, revision: str) -> Optional[Tuple[object, threading.Lock]]:
    """Load an explicitly configured local cross-encoder, caching successes only.

    A failed load is remembered for RETRY_AFTER_SECONDS so recall does not retry
    on every call, but a transient error (a dropped download, say) does not turn
    rerank off for the life of the process.
    """
    cache_key = (model_name, device, revision)
    with _lock:
        if cache_key in _models:
            return _models[cache_key], _predict_locks[cache_key]
        failed = _failed_at.get(cache_key)
        if failed is not None and time.monotonic() - failed < RETRY_AFTER_SECONDS:
            return None
        if cache_key in _loading:  # another call is loading it; skip rerank rather than wait
            return None
        _loading.add(cache_key)
    try:  # load (possibly a download) outside the lock
        from sentence_transformers import CrossEncoder

        model = CrossEncoder(model_name, device=device, revision=revision or None, max_length=512)
    except Exception as exc:  # noqa: BLE001 - any load failure falls back to the fused order
        with _lock:
            _loading.discard(cache_key)
            _failed_at[cache_key] = time.monotonic()
        logger.warning("bilinc rerank model %r could not be loaded (%s); recall keeps the fused order", model_name, exc)
        return None
    with _lock:
        _loading.discard(cache_key)
        _failed_at.pop(cache_key, None)
        _models[cache_key] = model
        _predict_locks[cache_key] = threading.Lock()
        return model, _predict_locks[cache_key]


def _raw_logits() -> Dict[str, object]:
    """predict() arguments that return raw logits instead of the config's activation."""
    try:
        import torch
    except ImportError:  # a real CrossEncoder cannot load without torch; test doubles can
        return {}
    return {"activation_fct": torch.nn.Identity()}


def _clear_model_cache() -> None:
    with _lock:
        _models.clear()
        _predict_locks.clear()
        _failed_at.clear()
        _loading.clear()


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
    config: Optional[Tuple[str, str, str, int]] = None,
) -> Tuple[List[str], Dict[str, float]]:
    """Reorder the head of ``ordered_keys`` by cross-encoder score.

    Synchronous and CPU-bound; async callers run it in a worker thread. Returns
    the new order and the scores of the reranked keys. The order is unchanged
    when reranking is off, the model is unavailable, or scoring fails.
    """
    config = config or rerank_config()
    if config is None or not ordered_keys:
        return ordered_keys, {}
    model_name, device, revision, depth = config
    loaded = _load_rerank_model(model_name, device, revision)
    if loaded is None:
        return ordered_keys, {}
    model, predict_lock = loaded
    head = ordered_keys[: min(depth, max(MIN_HEAD, HEAD_PER_RESULT * max(1, int(limit))))]
    try:
        pairs = [(query, (text_of(key) or "")[:_MAX_DOCUMENT_CHARS]) for key in head]
        with predict_lock:
            raw = model.predict(pairs, batch_size=32, show_progress_bar=False, **_raw_logits())
        scores = {key: float(score) for key, score in zip(head, raw)}
    except Exception as exc:  # noqa: BLE001 - scoring failure falls back to the fused order
        logger.warning("bilinc rerank scoring failed (%s); recall keeps the fused order", exc)
        return ordered_keys, {}
    position = {key: index for index, key in enumerate(head)}
    reranked = sorted(head, key=lambda key: (-scores[key], position[key]))
    return reranked + ordered_keys[len(head):], scores
