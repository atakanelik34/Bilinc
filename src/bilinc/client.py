"""Bilinc Cloud client.

Bilinc 2.1.5 is cloud-only: the PyPI package is a thin SDK and MCP adapter for
https://bilinc.space. Local self-hosted StatePlane internals are no longer
shipped in the public package.
"""

from __future__ import annotations

import json
import os
import ssl
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

__version__ = "2.1.5"
DEFAULT_BASE_URL = "https://bilinc.space"
SIGNUP_URL = "https://bilinc.space/signup"
ACTIVATION_CAMPAIGN = "activation_2_1_3"
ACTIVATION_SIGNUP_URL = (
    f"{SIGNUP_URL}?utm_source=pypi&utm_medium=cli&utm_campaign={ACTIVATION_CAMPAIGN}"
)
INSTALL_URL = (
    f"{DEFAULT_BASE_URL}/install?utm_source=pypi&utm_medium=cli&utm_campaign={ACTIVATION_CAMPAIGN}"
)
CONFIG_DIR_ENV = "BILINC_CONFIG_DIR"
CONFIG_FILE_NAME = "config.json"


class BilincError(RuntimeError):
    """Base Bilinc SDK error."""


class BilincApiKeyRequired(BilincError):
    """Raised when no Bilinc Cloud API key is configured."""


class BilincCloudError(BilincError):
    """Raised when Bilinc Cloud rejects or fails a request."""


Transport = Callable[..., dict[str, Any]]


def _default_ssl_context() -> ssl.SSLContext:
    """Return a CA-backed TLS context for Bilinc Cloud requests.

    Some macOS Python installs do not populate OpenSSL's default CA file, which
    makes stdlib urllib fail with CERTIFICATE_VERIFY_FAILED even when the
    system browser and curl can reach bilinc.space. certifi gives the public SDK
    a stable Mozilla CA bundle while still allowing explicit SSL_CERT_FILE or
    BILINC_CA_BUNDLE overrides for locked-down enterprise environments.
    """

    ca_bundle = os.environ.get("BILINC_CA_BUNDLE") or os.environ.get("SSL_CERT_FILE")
    if ca_bundle:
        return ssl.create_default_context(cafile=ca_bundle)

    try:
        import certifi
    except ImportError:
        return ssl.create_default_context()

    return ssl.create_default_context(cafile=certifi.where())


def config_path() -> Path:
    """Return the local Bilinc CLI config path."""

    override = os.environ.get(CONFIG_DIR_ENV)
    if override:
        return Path(override).expanduser() / CONFIG_FILE_NAME
    xdg_config_home = os.environ.get("XDG_CONFIG_HOME")
    if xdg_config_home:
        return Path(xdg_config_home).expanduser() / "bilinc" / CONFIG_FILE_NAME
    return Path.home() / ".config" / "bilinc" / CONFIG_FILE_NAME


def load_config() -> dict[str, Any]:
    """Load local CLI config without raising on missing or malformed files."""

    path = config_path()
    if not path.exists():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return payload if isinstance(payload, dict) else {}


def load_config_api_key() -> str | None:
    """Return a stored API key if one was saved with `bilinc login`."""

    value = load_config().get("api_key")
    return value if isinstance(value, str) and value.strip() else None


def save_config_api_key(api_key: str, *, base_url: str = DEFAULT_BASE_URL) -> Path:
    """Persist the Cloud API key for local CLI use with user-only permissions."""

    key = api_key.strip()
    if not key:
        raise BilincApiKeyRequired(
            "Bilinc requires a Bilinc Cloud API key. "
            f"Start a 7-day trial at {ACTIVATION_SIGNUP_URL}, "
            "then run bilinc login --api-key <key> and bilinc quicktest."
        )

    path = config_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {"api_key": key, "base_url": base_url.rstrip("/") or DEFAULT_BASE_URL}
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    try:
        path.chmod(0o600)
    except OSError:
        pass
    return path


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
        with urllib.request.urlopen(  # noqa: S310 - configured endpoint
            request,
            timeout=timeout,
            context=_default_ssl_context(),
        ) as response:
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
            self.api_key = os.environ.get("BILINC_API_KEY") or load_config_api_key()
        if not self.api_key:
            raise BilincApiKeyRequired(
                "Bilinc requires a Bilinc Cloud API key. "
                f"Start a 7-day trial at {ACTIVATION_SIGNUP_URL}, "
                "then run bilinc login --api-key <key> and bilinc quicktest."
            )
        if self.base_url == DEFAULT_BASE_URL:
            self.base_url = os.environ.get("BILINC_BASE_URL", self.base_url)
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
    "ACTIVATION_SIGNUP_URL",
    "config_path",
    "DEFAULT_BASE_URL",
    "INSTALL_URL",
    "load_config_api_key",
    "save_config_api_key",
    "SIGNUP_URL",
]
