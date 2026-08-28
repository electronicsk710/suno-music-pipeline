#!/usr/bin/env python3
"""
Deployment testing script for Suno Music Pipeline.
Run this after deployment to verify all components are working.
"""

import requests
import json
import sys
from pathlib import Path
import time

BASE_URL = "http://localhost:8000"
TEST_AUDIO = "test_audio.wav"  # Ensure this file exists

class Colors:
    GREEN = '\033[92m'
    RED = '\033[91m'
    YELLOW = '\033[93m'
    BLUE = '\033[94m'
    END = '\033[0m'

def print_status(test_name, passed, message=""):
    status = f"{Colors.GREEN}✓ PASSED{Colors.END}" if passed else f"{Colors.RED}✗ FAILED{Colors.END}"
    print(f"  {status} - {test_name}")
    if message:
        print(f"         {message}")

def test_server_online():
    """Test if server is running and responding."""
    print(f"\n{Colors.BLUE}[1] Testing Server Connectivity{Colors.END}")
    try:
        response = requests.get(f"{BASE_URL}/", timeout=5)
        passed = response.status_code == 200
        print_status("Server online", passed)
        return passed
    except requests.exceptions.ConnectionError:
        print_status("Server online", False, f"Cannot connect to {BASE_URL}")
        return False

def test_health_endpoint():
    """Test health check endpoint."""
    print(f"\n{Colors.BLUE}[2] Testing Health Check Endpoint{Colors.END}")
    try:
        response = requests.get(f"{BASE_URL}/health", timeout=10)
        passed = response.status_code == 200
        print_status("Health endpoint accessible", passed)
        
        if passed:
            data = response.json()
            print(f"         Status: {data.get('status')}")
            print(f"         Uptime: {data.get('uptime_seconds'):.1f}s")
            print(f"         SoundFont: {'Available' if data.get('soundfont_available') else 'Missing'}")
        return passed
    except Exception as e:
        print_status("Health endpoint accessible", False, str(e))
        return False

def test_stats_endpoint():
    """Test stats endpoint."""
    print(f"\n{Colors.BLUE}[3] Testing Statistics Endpoint{Colors.END}")
    try:
        response = requests.get(f"{BASE_URL}/stats", timeout=10)
        passed = response.status_code == 200
        print_status("Stats endpoint accessible", passed)
        
        if passed:
            data = response.json()
            print(f"         Total requests: {data.get('total_requests')}")
            print(f"         Error rate: {data.get('error_rate_percent')}%")
        return passed
    except Exception as e:
        print_status("Stats endpoint accessible", False, str(e))
        return False

def test_analyze_endpoint():
    """Test audio analysis endpoint."""
    print(f"\n{Colors.BLUE}[4] Testing Audio Analysis Endpoint{Colors.END}")
    
    if not Path(TEST_AUDIO).exists():
        print_status("Analyze endpoint", False, f"Test audio file '{TEST_AUDIO}' not found")
        return False
    
    try:
        with open(TEST_AUDIO, 'rb') as f:
            files = {'file': (TEST_AUDIO, f, 'audio/wav')}
            response = requests.post(f"{BASE_URL}/analyze", files=files, timeout=30)
        
        passed = response.status_code == 200
        print_status("Analyze endpoint functional", passed)
        
        if passed:
            data = response.json()
            print(f"         Detected tempo: {data.get('tempo')} BPM")
            print(f"         Detected key: {data.get('key')}")
            print(f"         Notes extracted: {len(data.get('notes', []))}")
        return passed, data if passed else None
    except Exception as e:
        print_status("Analyze endpoint functional", False, str(e))
        return False, None

def test_generate_endpoint(analysis_data):
    """Test MIDI generation endpoint."""
    print(f"\n{Colors.BLUE}[5] Testing MIDI Generation Endpoint{Colors.END}")
    
    if not analysis_data:
        print_status("Generate endpoint", False, "No analysis data available")
        return False
    
    try:
        payload = {
            "notes": analysis_data.get('notes', []),
            "tempo": analysis_data.get('tempo', 120),
            "key": analysis_data.get('key', 'C major')
        }
        
        response = requests.post(
            f"{BASE_URL}/generate",
            json=payload,
            timeout=60
        )
        
        passed = response.status_code == 200 and response.headers.get('content-type') == 'audio/wav'
        print_status("Generate endpoint functional", passed)
        
        if passed:
            print(f"         Generated audio size: {len(response.content) / 1024:.2f} KB")
        return passed
    except Exception as e:
        print_status("Generate endpoint functional", False, str(e))
        return False

def test_response_times():
    """Test response times for performance."""
    print(f"\n{Colors.BLUE}[6] Testing Response Times{Colors.END}")
    
    try:
        # Health check response time
        start = time.time()
        requests.get(f"{BASE_URL}/health", timeout=10)
        health_time = (time.time() - start) * 1000
        
        print_status("Health response time", health_time < 100, f"{health_time:.2f}ms (target: <100ms)")
        
        # Stats response time
        start = time.time()
        requests.get(f"{BASE_URL}/stats", timeout=10)
        stats_time = (time.time() - start) * 1000
        
        print_status("Stats response time", stats_time < 100, f"{stats_time:.2f}ms (target: <100ms)")
        
        return True
    except Exception as e:
        print_status("Response time check", False, str(e))
        return False

def run_all_tests():
    """Run all deployment tests."""
    print(f"{Colors.BLUE}="*60)
    print(f"  Suno Music Pipeline - Deployment Test Suite")
    print(f"  Server: {BASE_URL}")
    print(f"="*60{Colors.END}")
    
    results = []
    
    # Test 1: Server connectivity
    results.append(("Server Online", test_server_online()))
    if not results[-1][1]:
        print(f"\n{Colors.RED}Server is not responding. Aborting tests.{Colors.END}")
        return False
    
    # Test 2: Health endpoint
    results.append(("Health Endpoint", test_health_endpoint()))
    
    # Test 3: Stats endpoint
    results.append(("Stats Endpoint", test_stats_endpoint()))
    
    # Test 4: Analyze endpoint
    passed, analysis_data = test_analyze_endpoint()
    results.append(("Analyze Endpoint", passed))
    
    # Test 5: Generate endpoint (if analysis succeeded)
    if passed:
        results.append(("Generate Endpoint", test_generate_endpoint(analysis_data)))
    
    # Test 6: Response times
    results.append(("Response Times", test_response_times()))
    
    # Summary
    print(f"\n{Colors.BLUE}="*60)
    print(f"  Test Summary")
    print(f"="*60{Colors.END}")
    
    passed_count = sum(1 for _, passed in results if passed)
    total_count = len(results)
    
    for test_name, passed in results:
        status = f"{Colors.GREEN}PASS{Colors.END}" if passed else f"{Colors.RED}FAIL{Colors.END}"
        print(f"  {status} - {test_name}")
    
    print(f"\n  {Colors.BLUE}Total: {passed_count}/{total_count} tests passed{Colors.END}")
    
    if passed_count == total_count:
        print(f"\n{Colors.GREEN}✓ All tests passed! Deployment is ready.{Colors.END}\n")
        return True
    else:
        print(f"\n{Colors.YELLOW}⚠ Some tests failed. Check logs and configuration.{Colors.END}\n")
        return False

if __name__ == "__main__":
    success = run_all_tests()
    sys.exit(0 if success else 1)