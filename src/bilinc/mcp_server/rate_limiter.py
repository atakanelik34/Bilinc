"""
MCP Server Rate Limiter

Simple in-memory token bucket rate limiter.
No external dependencies, no Redis, no async complexity.
"""

from __future__ import annotations

import time
from collections import defaultdict
from typing import Dict, Tuple


class TokenBucketLimiter:
    """
    Per-client token bucket rate limiter.
    
    Usage:
        limiter = TokenBucketLimiter(max_tokens=10, refill_rate=1.0)  # 10 tokens, 1/sec refill
        if limiter.allow("client_123"):
            process_request()
        else:
            return "Rate limited"
    """

    def __init__(self, max_tokens: int = 10, refill_rate: float = 1.0):
        """
        max_tokens: Maximum tokens a client can accumulate
        refill_rate: Tokens added per second
        
        Default: 10 requests burst, then 1 request/second sustained.
        """
        self.max_tokens = max_tokens
        self.refill_rate = refill_rate
        # {client_id: (tokens, last_refill_time)}
        self._buckets: Dict[str, Tuple[float, float]] = defaultdict(
            lambda: (float(max_tokens), time.time())
        )
        self._max_entries = 10_000  # Prevent unbounded memory growth

    def allow(self, client_id: str, tokens: int = 1) -> bool:
        """
        Check if a client is allowed to make a request.
        
        Args:
            client_id: Unique client identifier
            tokens: Number of tokens to consume (default: 1)
            
        Returns:
            True if allowed, False if rate limited
        """
        # Evict old entries if too many
        if len(self._buckets) > self._max_entries:
            self._evict_oldest()

        now = time.time()
        bucket_tokens, last_refill = self._buckets[client_id]

        # Calculate tokens to add based on elapsed time
        elapsed = now - last_refill
        new_tokens = elapsed * self.refill_rate
        bucket_tokens = min(self.max_tokens, bucket_tokens + new_tokens)

        # Check if enough tokens available
        if bucket_tokens >= tokens:
            bucket_tokens -= tokens
            self._buckets[client_id] = (bucket_tokens, now)
            return True
        else:
            # Update the refill time to prevent token accumulation during limit
            self._buckets[client_id] = (bucket_tokens, now)
            return False

    def get_remaining(self, client_id: str) -> float:
        """Get remaining tokens for a client (for X-RateLimit-Remaining header)."""
        now = time.time()
        bucket_tokens, last_refill = self._buckets.get(client_id, (float(self.max_tokens), now))
        elapsed = now - last_refill
        new_tokens = elapsed * self.refill_rate
        return min(self.max_tokens, bucket_tokens + new_tokens)

    def _evict_oldest(self) -> None:
        """Remove the oldest half of buckets to prevent memory growth."""
        if not self._buckets:
            return
        # Sort by last_refill time, keep the newest half
        sorted_buckets = sorted(self._buckets.items(), key=lambda x: x[1][1])
        keep_count = max(len(sorted_buckets) // 2, 100)
        to_keep = dict(sorted_buckets[-keep_count:])
        self._buckets.clear()
        self._buckets.update(to_keep)

    def reset(self, client_id: str) -> None:
        """Reset a client's token bucket to full."""
        self._buckets[client_id] = (float(self.max_tokens), time.time())

    def clear(self) -> None:
        """Clear all buckets."""
        self._buckets.clear()
