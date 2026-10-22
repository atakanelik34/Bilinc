"""Query encoding over the daemon's unix socket. Recall calls this; it never loads a model."""
from __future__ import annotations

import base64
import json
import os
import socket
from pathlib import Path
from typing import Optional, Tuple

import numpy as np

DEFAULT_SOCKET = Path.home() / ".bilinc" / "embed.sock"
# Recall waits at most this long for a query vector, then runs without the signal.
QUERY_TIMEOUT_SECONDS = 1.0


def socket_path() -> Path:
    configured = os.environ.get("BILINC_EMBED_SOCKET", "").strip()
    return Path(configured).expanduser() if configured else DEFAULT_SOCKET


def request(payload: dict, path: Optional[Path] = None, timeout: float = 2.0) -> Optional[dict]:
    """One JSON line out, one JSON line back; None when the daemon is not there."""
    target = path or socket_path()
    if not target.exists():
        return None
    try:
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as conn:
            conn.settimeout(timeout)
            conn.connect(str(target))
            conn.sendall((json.dumps(payload) + "\n").encode("utf-8"))
            data = b""
            while not data.endswith(b"\n"):
                chunk = conn.recv(65536)
                if not chunk:
                    break
                data += chunk
        return json.loads(data.decode("utf-8")) if data else None
    except (OSError, ValueError):
        return None


def encode_query(text: str, path: Optional[Path] = None, timeout: float = QUERY_TIMEOUT_SECONDS) -> Optional[Tuple[str, np.ndarray]]:
    """``(model_id, vector)`` for a query, or None when semantic recall is unavailable."""
    reply = request({"op": "encode_query", "text": text}, path=path, timeout=timeout)
    if not reply or "vector" not in reply or "model" not in reply:
        return None
    vector = np.frombuffer(base64.b64decode(reply["vector"]), dtype=np.float32)
    return str(reply["model"]), vector
