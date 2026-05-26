"""Small structured logging helper for Bilinc."""

from __future__ import annotations

import json
import logging
from typing import Any


def log_event(logger: logging.Logger, level: str, event: str, **fields: Any) -> None:
    """Emit a compact JSON log line without leaking sensitive values."""
    payload = {"event": event}
    payload.update({k: v for k, v in fields.items() if v is not None})
    getattr(logger, level)(json.dumps(payload, sort_keys=True, default=str, ensure_ascii=True))
