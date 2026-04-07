"""
Input Validation for Bilinc
"""
import re
import json
from typing import Any

class InputValidator:
    # Güvenli key pattern: alfanumerik, tire, alt çizgi, nokta
    SAFE_KEY_RE = re.compile(r'^[a-zA-Z0-9_\-\.\:]{1,256}$')
    MAX_VAL_BYTES = 1024 * 1024  # 1MB

    @staticmethod
    def validate_key(key: str) -> str:
        if not key or not key.strip():
            raise ValueError("Key cannot be empty or whitespace.")
        if '..' in key or '/' in key or '\\' in key:
            raise ValueError("Key contains illegal characters (path traversal attempt).")
        if not InputValidator.SAFE_KEY_RE.match(key):
            raise ValueError("Key contains disallowed characters.")
        return key

    @staticmethod
    def validate_value(value: Any) -> Any:
        try:
            serialized = json.dumps(value, ensure_ascii=False, default=str)
        except Exception as e:
            raise ValueError(f"Value is not JSON serializable: {e}")
        
        if len(serialized.encode('utf-8')) > InputValidator.MAX_VAL_BYTES:
            raise ValueError("Value exceeds maximum size limit (1MB).")
        return value

    @staticmethod
    def sanitize_for_kg(text: str) -> str:
        """Sanitize text for KG node names (removes tags/injection)."""
        if not isinstance(text, str):
            return str(text)
        # HTML tags
        clean = re.sub(r'<[^>]+>', '', text)
        clean = re.sub(r'(?i)javascript\s*:', '', clean)
        clean = clean.replace('\0', '')
        return clean.strip()[:500]
