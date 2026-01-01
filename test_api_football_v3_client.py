#!/usr/bin/env python3
"""
Test script for API-Football v3 client
This script can be run without Django to test the client's basic functionality
"""

import sys
import os

# Add the backend directory to the path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'whatsappcrm_backend'))

def test_client_import():
    """Test that the client can be imported"""
    print("=" * 60)
    print("TEST 1: Client Import")
    print("=" * 60)
    try:
        from football_data_app.api_football_v3_client import (
            APIFootballV3Client,
            APIFootballV3Exception
        )
        print("✓ Successfully imported APIFootballV3Client")
        print("✓ Successfully imported APIFootballV3Exception")
        return True
    except ImportError as e:
        print(f"✗ Import failed: {e}")
        return False

def test_client_structure():
    """Test that the client has the expected methods"""
    print("\n" + "=" * 60)
    print("TEST 2: Client Structure")
    print("=" * 60)
    
    from football_data_app.api_football_v3_client import APIFootballV3Client
    
    expected_methods = [
        'get_leagues',
        'get_fixtures',
        'get_upcoming_fixtures',
        'get_live_fixtures',
        'get_odds',
        'get_fixture_odds',
        'get_standings',
        'get_teams',
        'get_head_to_head',
        'get_players',
        'get_bookmakers',
        'get_bets',
    ]
    
    all_pass = True
    for method_name in expected_methods:
        if hasattr(APIFootballV3Client, method_name):
            print(f"✓ Method '{method_name}' exists")
        else:
            print(f"✗ Method '{method_name}' missing")
            all_pass = False
    
    return all_pass

def test_client_initialization():
    """Test that the client can be initialized (without API key)"""
    print("\n" + "=" * 60)
    print("TEST 3: Client Initialization")
    print("=" * 60)
    
    from football_data_app.api_football_v3_client import (
        APIFootballV3Client,
        APIFootballV3Exception
    )
    
    # This should fail without an API key, which is expected
    print("Testing initialization without API key (should fail gracefully)...")
    try:
        client = APIFootballV3Client()
        print("✗ Client initialized without API key (unexpected)")
        return False
    except ValueError as e:
        if "API Key for API-Football v3 must be configured" in str(e):
            print("✓ Client correctly requires API key")
            return True
        else:
            print(f"✗ Unexpected error: {e}")
            return False
    except Exception as e:
        print(f"✗ Unexpected exception type: {type(e).__name__}: {e}")
        return False

def test_client_with_dummy_key():
    """Test client initialization with a dummy key"""
    print("\n" + "=" * 60)
    print("TEST 4: Client with Dummy Key")
    print("=" * 60)
    
    from football_data_app.api_football_v3_client import APIFootballV3Client
    
    try:
        client = APIFootballV3Client(api_key="dummy_key_for_testing")
        print("✓ Client initialized with provided API key")
        
        # Check that the key is stored
        if hasattr(client, 'api_key'):
            print("✓ Client has 'api_key' attribute")
        else:
            print("✗ Client missing 'api_key' attribute")
            return False
        
        # Check base URL
        if hasattr(client, 'base_url'):
            expected_url = "https://v3.football.api-sports.io"
            if client.base_url == expected_url:
                print(f"✓ Base URL is correct: {expected_url}")
            else:
                print(f"✗ Base URL incorrect: {client.base_url} (expected {expected_url})")
                return False
        else:
            print("✗ Client missing 'base_url' attribute")
            return False
        
        # Check headers method
        if hasattr(client, '_get_headers'):
            headers = client._get_headers()
            if 'x-apisports-key' in headers:
                print("✓ Headers include 'x-apisports-key'")
            else:
                print("✗ Headers missing 'x-apisports-key'")
                return False
        else:
            print("✗ Client missing '_get_headers' method")
            return False
        
        return True
    except Exception as e:
        print(f"✗ Unexpected error: {e}")
        return False

def main():
    """Run all tests"""
    print("\n" + "=" * 60)
    print("API-Football v3 Client Test Suite")
    print("=" * 60)
    
    tests = [
        test_client_import,
        test_client_structure,
        test_client_initialization,
        test_client_with_dummy_key,
    ]
    
    results = []
    for test_func in tests:
        try:
            result = test_func()
            results.append(result)
        except Exception as e:
            print(f"\n✗ Test crashed: {e}")
            import traceback
            traceback.print_exc()
            results.append(False)
    
    # Summary
    print("\n" + "=" * 60)
    print("TEST SUMMARY")
    print("=" * 60)
    passed = sum(results)
    total = len(results)
    print(f"Passed: {passed}/{total}")
    
    if all(results):
        print("\n✅ ALL TESTS PASSED!")
        return 0
    else:
        print("\n❌ SOME TESTS FAILED")
        return 1

if __name__ == "__main__":
    sys.exit(main())
