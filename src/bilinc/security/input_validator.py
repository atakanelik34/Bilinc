"""
Input Validation for Bilinc

Validates keys, values and sanitizes text before insertion into the system.
"""

import re
import json
from typing import Any

# Regex: alphanumeric, hyphens, underscores, dots. No path traversal!
SAFE_KEY_PATTERN = re.compile(r'^[a-zA-Z0-9_\-\.\:]{1,256}$')

# Max sizes
MAX_KEY_LENGTH = 256
MAX_VALUE_SIZE_BYTES = 1024 * 1024  # 1MB


class InputValidator:
    """Central input validation class."""

    @staticmethod
    def validate_key(key: str) -> str:
        """
        Validate a memory key.
        Must be alphanumeric (plus _, -, ., :) and max 256 chars.
        Raises ValueError on invalid input.
        """
        if not isinstance(key, str):
            raise ValueError(f"Key must be a string, got {type(key).__name__}")

        if not key or not key.strip():
            raise ValueError("Key cannot be empty or whitespace.")

        if len(key) > MAX_KEY_LENGTH:
            raise ValueError(f"Key exceeds max length of {MAX_KEY_LENGTH}.")

        # Block path traversal
        if '..' in key or '/' in key or '\\' in key:
            raise ValueError("Key contains illegal characters (path traversal attempt).")

        if not SAFE_KEY_PATTERN.match(key):
            raise ValueError(f"Key '{key}' contains disallowed characters.")

        return key

    @staticmethod
    def validate_value(value: Any, max_size: int = MAX_VALUE_SIZE_BYTES) -> Any:
        """
        Validate a memory value.
        Must be JSON serializable and within size limits.
        """
        try:
            serialized = json.dumps(value, ensure_ascii=False, default=str)
        except (TypeError, ValueError) as e:
            raise ValueError(f"Value is not JSON serializable: {e}")

        if len(serialized.encode('utf-8')) > max_size:
            raise ValueError(f"Value exceeds max size of {max_size} bytes.")

        return value

    @staticmethod
    def sanitize_for_kg(text: str) -> str:
        """
        Sanitize text for Knowledge Graph insertion.
        Removes HTML tags, potential XSS vectors, and script blocks.
        """
        if not isinstance(text, str):
            return str(text)

        # Remove HTML tags
        clean = re.sub(r'<[^>]+>', '', text)
        # Remove script/style blocks
        clean = re.sub(r'(?i)<script.*?</script>', '', clean, flags=re.DOTALL)
        clean = re.sub(r'(?i)<style.*?</style>', '', clean, flags=re.DOTALL)
        # Remove dangerous javascript: protocol
        clean = re.sub(r'(?i)javascript\s*:', '', clean)
        # Remove null bytes
        clean = clean.replace('\0', '')

        return clean.strip()[:500]  # Limit node name length
