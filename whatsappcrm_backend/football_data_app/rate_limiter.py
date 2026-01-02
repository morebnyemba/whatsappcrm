# football_data_app/rate_limiter.py
"""
Rate limiter for API-Football requests to ensure we don't exceed 300 requests per minute.
Uses Django cache backend for distributed rate limiting support.
"""
import time
import logging
from functools import wraps
from typing import Optional
from django.core.cache import cache
from django.conf import settings

logger = logging.getLogger(__name__)

# Rate limiting configuration
MAX_REQUESTS_PER_MINUTE = getattr(settings, 'API_FOOTBALL_MAX_REQUESTS_PER_MINUTE', 300)
RATE_LIMIT_WINDOW_SECONDS = 60
RATE_LIMIT_CACHE_KEY_PREFIX = 'api_football_rate_limit'


class RateLimitExceeded(Exception):
    """Exception raised when rate limit is exceeded."""
    def __init__(self, retry_after: float = None):
        self.retry_after = retry_after
        message = f"Rate limit exceeded. Retry after {retry_after:.1f} seconds." if retry_after else "Rate limit exceeded."
        super().__init__(message)


class APIFootballRateLimiter:
    """
    Rate limiter for API-Football requests.
    Ensures we don't exceed MAX_REQUESTS_PER_MINUTE requests per minute.
    """
    
    def __init__(self, max_requests: int = MAX_REQUESTS_PER_MINUTE, window_seconds: int = RATE_LIMIT_WINDOW_SECONDS):
        self.max_requests = max_requests
        self.window_seconds = window_seconds
        self.cache_key = f"{RATE_LIMIT_CACHE_KEY_PREFIX}_requests"
        self.window_start_key = f"{RATE_LIMIT_CACHE_KEY_PREFIX}_window_start"
    
    def _get_current_window_data(self):
        """Get current rate limit window data from cache."""
        request_count = cache.get(self.cache_key, 0)
        window_start = cache.get(self.window_start_key, time.time())
        return request_count, window_start
    
    def _reset_window(self):
        """Reset the rate limit window."""
        cache.set(self.cache_key, 0, timeout=self.window_seconds + 10)  # Add buffer
        cache.set(self.window_start_key, time.time(), timeout=self.window_seconds + 10)
        logger.info(f"Rate limit window reset. New window starts now.")
    
    def _increment_counter(self):
        """Increment the request counter."""
        try:
            # Use atomic increment if available (Redis, Memcached)
            new_count = cache.incr(self.cache_key)
        except (ValueError, AttributeError):
            # Fallback for cache backends that don't support incr
            current_count = cache.get(self.cache_key, 0)
            new_count = current_count + 1
            cache.set(self.cache_key, new_count, timeout=self.window_seconds + 10)
        return new_count
    
    def acquire(self, wait: bool = True) -> bool:
        """
        Attempt to acquire a rate limit slot.
        
        Args:
            wait: If True, wait until a slot becomes available. If False, raise exception immediately.
        
        Returns:
            True if slot acquired successfully
            
        Raises:
            RateLimitExceeded: If rate limit exceeded and wait=False
        """
        current_time = time.time()
        request_count, window_start = self._get_current_window_data()
        window_elapsed = current_time - window_start
        
        # Check if we need to start a new window
        if window_elapsed >= self.window_seconds:
            self._reset_window()
            request_count = 0
            window_start = current_time
            window_elapsed = 0
        
        # Check if we're at the limit
        if request_count >= self.max_requests:
            # Calculate time to wait until window resets
            time_until_reset = self.window_seconds - window_elapsed
            
            if not wait:
                raise RateLimitExceeded(retry_after=time_until_reset)
            
            # Wait until window resets
            logger.warning(
                f"Rate limit reached ({request_count}/{self.max_requests} requests). "
                f"Waiting {time_until_reset:.1f} seconds for window reset..."
            )
            time.sleep(time_until_reset + 0.1)  # Add small buffer
            
            # Reset window and try again
            self._reset_window()
            request_count = 0
        
        # Increment counter and allow request
        new_count = self._increment_counter()
        
        logger.debug(
            f"Rate limit: {new_count}/{self.max_requests} requests in current window "
            f"({window_elapsed:.1f}s elapsed)"
        )
        
        return True
    
    def get_current_usage(self) -> dict:
        """Get current rate limit usage statistics."""
        current_time = time.time()
        request_count, window_start = self._get_current_window_data()
        window_elapsed = current_time - window_start
        
        return {
            'requests_made': request_count,
            'max_requests': self.max_requests,
            'window_seconds': self.window_seconds,
            'window_elapsed': window_elapsed,
            'window_remaining': max(0, self.window_seconds - window_elapsed),
            'requests_remaining': max(0, self.max_requests - request_count),
            'percentage_used': (request_count / self.max_requests) * 100 if self.max_requests > 0 else 0
        }


# Global rate limiter instance
_rate_limiter = None


def get_rate_limiter() -> APIFootballRateLimiter:
    """Get or create the global rate limiter instance."""
    global _rate_limiter
    if _rate_limiter is None:
        _rate_limiter = APIFootballRateLimiter()
    return _rate_limiter


def rate_limit(wait: bool = True):
    """
    Decorator to apply rate limiting to API functions.
    
    Args:
        wait: If True, wait for rate limit slot. If False, raise exception immediately.
    
    Usage:
        @rate_limit(wait=True)
        def fetch_data():
            # API call here
            pass
    """
    def decorator(func):
        @wraps(func)
        def wrapper(*args, **kwargs):
            limiter = get_rate_limiter()
            limiter.acquire(wait=wait)
            return func(*args, **kwargs)
        return wrapper
    return decorator


def check_rate_limit_status() -> dict:
    """
    Check current rate limit status without making a request.
    
    Returns:
        Dictionary with current usage statistics
    """
    limiter = get_rate_limiter()
    return limiter.get_current_usage()
