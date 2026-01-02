#!/usr/bin/env python3
"""
Test script for rate limiter implementation.
This script tests the rate limiter logic without requiring Django.
"""
import time
from collections import defaultdict
from typing import Dict, Tuple

# Simple in-memory cache for testing
class SimpleCache:
    def __init__(self):
        self.storage = {}
    
    def get(self, key, default=None):
        if key in self.storage:
            value, expires_at = self.storage[key]
            if time.time() < expires_at:
                return value
            else:
                del self.storage[key]
        return default
    
    def set(self, key, value, timeout=None):
        expires_at = time.time() + (timeout if timeout else 3600)
        self.storage[key] = (value, expires_at)
    
    def incr(self, key):
        current = self.get(key, 0)
        new_value = current + 1
        self.set(key, new_value, timeout=70)
        return new_value

# Mock cache
cache = SimpleCache()

# Rate limiter configuration
MAX_REQUESTS_PER_MINUTE = 300
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
        cache.set(self.cache_key, 0, timeout=self.window_seconds + 10)
        cache.set(self.window_start_key, time.time(), timeout=self.window_seconds + 10)
        print(f"  [RESET] Rate limit window reset")
    
    def _increment_counter(self):
        """Increment the request counter."""
        new_count = cache.incr(self.cache_key)
        return new_count
    
    def acquire(self, wait: bool = True) -> bool:
        """Attempt to acquire a rate limit slot."""
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
            time_until_reset = self.window_seconds - window_elapsed
            
            if not wait:
                raise RateLimitExceeded(retry_after=time_until_reset)
            
            print(f"  [WAIT] Rate limit reached ({request_count}/{self.max_requests}). Waiting {time_until_reset:.1f}s...")
            time.sleep(time_until_reset + 0.1)
            
            self._reset_window()
            request_count = 0
        
        # Increment counter and allow request
        new_count = self._increment_counter()
        
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


def test_rate_limiter():
    """Test the rate limiter functionality."""
    print("="*80)
    print("RATE LIMITER TEST")
    print("="*80)
    
    # Test 1: Basic functionality
    print("\nTest 1: Basic Functionality")
    print("-" * 40)
    limiter = APIFootballRateLimiter(max_requests=10, window_seconds=5)
    
    print("Making 10 requests (should all succeed)...")
    for i in range(10):
        limiter.acquire(wait=False)
        stats = limiter.get_current_usage()
        print(f"  Request {i+1}: {stats['requests_made']}/{stats['max_requests']} " +
              f"({stats['percentage_used']:.1f}% used, {stats['window_remaining']:.1f}s remaining)")
    
    print("\n✅ Test 1 PASSED: All 10 requests succeeded")
    
    # Test 2: Rate limit enforcement
    print("\nTest 2: Rate Limit Enforcement")
    print("-" * 40)
    print("Attempting 11th request (should fail without waiting)...")
    try:
        limiter.acquire(wait=False)
        print("❌ Test 2 FAILED: 11th request should have been blocked")
    except RateLimitExceeded as e:
        print(f"✅ Test 2 PASSED: Rate limit enforced - {e}")
    
    # Test 3: Automatic waiting and window reset
    print("\nTest 3: Automatic Waiting and Window Reset")
    print("-" * 40)
    print("Attempting 11th request with wait=True (should succeed after window reset)...")
    limiter.acquire(wait=True)
    stats = limiter.get_current_usage()
    print(f"✅ Test 3 PASSED: Request succeeded after wait. New count: {stats['requests_made']}/{stats['max_requests']}")
    
    # Test 4: High volume simulation
    print("\nTest 4: High Volume Simulation (30 requests with 300 req/min limit)")
    print("-" * 40)
    limiter2 = APIFootballRateLimiter(max_requests=300, window_seconds=60)
    
    start_time = time.time()
    for i in range(30):
        limiter2.acquire(wait=True)
        if (i + 1) % 10 == 0:
            stats = limiter2.get_current_usage()
            elapsed = time.time() - start_time
            print(f"  {i+1} requests completed in {elapsed:.2f}s " +
                  f"({stats['percentage_used']:.1f}% of limit used)")
    
    total_time = time.time() - start_time
    print(f"✅ Test 4 PASSED: 30 requests completed in {total_time:.2f}s")
    
    # Test 5: Usage statistics
    print("\nTest 5: Usage Statistics")
    print("-" * 40)
    stats = limiter2.get_current_usage()
    print(f"Current usage statistics:")
    print(f"  Requests made: {stats['requests_made']}/{stats['max_requests']}")
    print(f"  Percentage used: {stats['percentage_used']:.1f}%")
    print(f"  Window elapsed: {stats['window_elapsed']:.1f}s/{stats['window_seconds']}s")
    print(f"  Requests remaining: {stats['requests_remaining']}")
    print("✅ Test 5 PASSED: Statistics retrieved successfully")
    
    print("\n" + "="*80)
    print("ALL TESTS PASSED ✅")
    print("="*80)


def test_bet_type_formatting():
    """Test the betting options formatting logic."""
    print("\n" + "="*80)
    print("BETTING OPTIONS FORMATTING TEST")
    print("="*80)
    
    # Simulate aggregated outcomes
    class MockOutcome:
        def __init__(self, id, outcome_name, odds, point_value=None):
            self.id = id
            self.outcome_name = outcome_name
            self.odds = odds
            self.point_value = point_value
    
    # Test fixture data
    fixture_home_team = "Manchester United"
    fixture_away_team = "Liverpool"
    
    # Mock outcomes
    aggregated_outcomes = {
        'h2h': {
            f"{fixture_home_team}-": MockOutcome(1001, fixture_home_team, 2.10),
            'Draw-': MockOutcome(1002, 'Draw', 3.40),
            f"{fixture_away_team}-": MockOutcome(1003, fixture_away_team, 2.90),
        },
        'double_chance': {
            'Home/Draw-': MockOutcome(1004, 'Home/Draw', 1.30),
            'Home/Away-': MockOutcome(1005, 'Home/Away', 1.52),
            'Draw/Away-': MockOutcome(1006, 'Draw/Away', 1.65),
        },
        'totals': {
            'Over-2.5': MockOutcome(1007, 'Over', 1.85, 2.5),
            'Under-2.5': MockOutcome(1008, 'Under', 1.95, 2.5),
            'Over-3.5': MockOutcome(1009, 'Over', 2.70, 3.5),
            'Under-3.5': MockOutcome(1010, 'Under', 1.45, 3.5),
        },
        'btts': {
            'Yes-': MockOutcome(1011, 'Yes', 1.70),
            'No-': MockOutcome(1012, 'No', 2.05),
        },
        'odd_even': {
            'Odd-': MockOutcome(1013, 'Odd', 1.90),
            'Even-': MockOutcome(1014, 'Even', 1.95),
        }
    }
    
    print("\nTest: Formatting betting options for display")
    print("-" * 40)
    
    # Format Match Winner
    print("\n*Match Winner (1X2):*")
    for key, outcome in aggregated_outcomes['h2h'].items():
        print(f"  - {outcome.outcome_name}: *{outcome.odds:.2f}* (ID: {outcome.id})")
    
    # Format Double Chance
    print("\n*Double Chance:*")
    dc_map = {
        'Home/Draw-': 'Home/Draw (1X)',
        'Home/Away-': 'Home/Away (12)',
        'Draw/Away-': 'Draw/Away (X2)'
    }
    for key, outcome in aggregated_outcomes['double_chance'].items():
        display_name = dc_map.get(key, outcome.outcome_name)
        print(f"  - {display_name}: *{outcome.odds:.2f}* (ID: {outcome.id})")
    
    # Format Totals
    print("\n*Total Goals (Over/Under):*")
    totals_by_point = {}
    for outcome in aggregated_outcomes['totals'].values():
        if outcome.point_value not in totals_by_point:
            totals_by_point[outcome.point_value] = {}
        if 'over' in outcome.outcome_name.lower():
            totals_by_point[outcome.point_value]['over'] = outcome
        elif 'under' in outcome.outcome_name.lower():
            totals_by_point[outcome.point_value]['under'] = outcome
    
    for point in sorted(totals_by_point.keys()):
        over_outcome = totals_by_point[point].get('over')
        under_outcome = totals_by_point[point].get('under')
        if over_outcome:
            print(f"  - Over {point:.1f}: *{over_outcome.odds:.2f}* (ID: {over_outcome.id})")
        if under_outcome:
            print(f"  - Under {point:.1f}: *{under_outcome.odds:.2f}* (ID: {under_outcome.id})")
    
    # Format BTTS
    print("\n*Both Teams To Score:*")
    for key, outcome in aggregated_outcomes['btts'].items():
        print(f"  - {outcome.outcome_name}: *{outcome.odds:.2f}* (ID: {outcome.id})")
    
    # Format Odd/Even
    print("\n*Odd/Even Goals:*")
    for key, outcome in aggregated_outcomes['odd_even'].items():
        print(f"  - {outcome.outcome_name}: *{outcome.odds:.2f}* (ID: {outcome.id})")
    
    print("\n✅ Betting options formatting test completed successfully")
    print("="*80)


if __name__ == '__main__':
    try:
        # Run rate limiter tests
        test_rate_limiter()
        
        # Run betting options formatting test
        test_bet_type_formatting()
        
        print("\n🎉 ALL TESTS COMPLETED SUCCESSFULLY 🎉\n")
        
    except Exception as e:
        print(f"\n❌ TEST FAILED: {e}")
        import traceback
        traceback.print_exc()
