"""Bilinc Cloud client.

Bilinc 2.1.1 is cloud-only: the PyPI package is a thin SDK and MCP adapter for
https://bilinc.space. Local self-hosted StatePlane internals are no longer
shipped in the public package.
"""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Any, Callable

__version__ = "2.1.1"
DEFAULT_BASE_URL = "https://bilinc.space"
SIGNUP_URL = "https://bilinc.space/signup"


class BilincError(RuntimeError):
    """Base Bilinc SDK error."""


class BilincApiKeyRequired(BilincError):
    """Raised when no Bilinc Cloud API key is configured."""


class BilincCloudError(BilincError):
    """Raised when Bilinc Cloud rejects or fails a request."""


Transport = Callable[..., dict[str, Any]]


def _default_transport(
    method: str,
    url: str,
    *,
    headers: dict[str, str],
    body: bytes | None,
    timeout: float,
) -> dict[str, Any]:
    request = urllib.request.Request(url, data=body, headers=headers, method=method)
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:  # noqa: S310 - configured endpoint
            raw = response.read().decode("utf-8")
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise BilincCloudError(f"Bilinc Cloud request failed: HTTP {exc.code}: {detail}") from exc
    except urllib.error.URLError as exc:
        raise BilincCloudError(f"Bilinc Cloud request failed: {exc.reason}") from exc

    if not raw:
        return {}
    try:
        return json.loads(raw)
    except json.JSONDecodeError as exc:
        raise BilincCloudError("Bilinc Cloud returned invalid JSON") from exc


@dataclass(slots=True)
class CloudClient:
    """Minimal Bilinc Cloud SDK client."""

    api_key: str | None = None
    base_url: str = DEFAULT_BASE_URL
    timeout: float = 30.0
    transport: Callable[..., dict[str, Any]] = _default_transport

    def __post_init__(self) -> None:
        if self.api_key is None:
            self.api_key = os.environ.get("BILINC_API_KEY")
        if not self.api_key:
            raise BilincApiKeyRequired(
                "Bilinc requires a Bilinc Cloud API key. "
                f"Start a 7-day trial at {SIGNUP_URL}, then set BILINC_API_KEY."
            )
        self.base_url = self.base_url.rstrip("/")

    def commit(
        self,
        key: str,
        value: Any,
        *,
        memory_type: str = "semantic",
        importance: float = 1.0,
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Commit a memory entry to Bilinc Cloud."""

        return self._post(
            "/api/cloud/memory/commit",
            {
                "key": key,
                "value": value,
                "memoryType": memory_type,
                "importance": importance,
                "metadata": metadata or {},
            },
        )

    def recall(
        self,
        query: str,
        *,
        profile: str = "balanced",
        limit: int = 10,
    ) -> dict[str, Any]:
        """Recall memories from Bilinc Cloud."""

        return self._post(
            "/api/cloud/memory/recall",
            {"query": query, "profile": profile, "limit": limit},
        )

    def status(self) -> dict[str, Any]:
        """Return Cloud account/runtime status."""

        return self._get("/api/cloud/health")

    def _headers(self, *, content_type: bool = False) -> dict[str, str]:
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "User-Agent": f"bilinc-python/{__version__}",
        }
        if content_type:
            headers["Content-Type"] = "application/json"
        return headers

    def _post(self, path: str, payload: dict[str, Any]) -> dict[str, Any]:
        body = json.dumps(payload, separators=(",", ":")).encode("utf-8")
        return self.transport(
            "POST",
            f"{self.base_url}{path}",
            headers=self._headers(content_type=True),
            body=body,
            timeout=float(self.timeout),
        )

    def _get(self, path: str) -> dict[str, Any]:
        return self.transport(
            "GET",
            f"{self.base_url}{path}",
            headers=self._headers(),
            body=None,
            timeout=float(self.timeout),
        )


Bilinc = CloudClient


__all__ = [
    "Bilinc",
    "BilincApiKeyRequired",
    "BilincCloudError",
    "BilincError",
    "CloudClient",
    "DEFAULT_BASE_URL",
    "SIGNUP_URL",
]
