#!/usr/bin/env python3
"""
Test the full frontend-to-API flow for LineCite.
Simulates what the Next.js frontend does when loading audit mode.
"""
import requests
import hmac
import hashlib
import json
import base64
import time

# Config
API_URL = "https://linecite-api.onrender.com"
JWT_SECRET = "2gjpNSViS55WhpyXfjrAwiN2zLmYXG360oRBHNHlABc="
USER_ID = "demo-user"
FIRM_ID = "7dab0ead5ad643cc9d615c2b01112dc4"

# Find a matter with successful runs
MATTER_ID = "bbd980d1fe9e4d4eb9243acf69e7e517"
RUN_ID = "847695b25ce940708b1317301b591313"


def b64url(data):
    """Base64 URL-safe encoding"""
    if isinstance(data, str):
        data = data.encode('utf-8')
    return base64.urlsafe_b64encode(data).rstrip(b'=').decode('ascii')


def sign_jwt(user_id: str, firm_id: str, method: str, path: str):
    """Sign JWT token like Next.js frontend does"""
    now = int(time.time())
    ttl = 60

    header = {"alg": "HS256", "typ": "JWT"}
    payload = {
        "sub": user_id,
        "firm_id": firm_id,
        "iat": now,
        "exp": now + ttl,
        "mth": method.upper(),
        "pth": path
    }

    encoded_header = b64url(json.dumps(header, separators=(',', ':')))
    encoded_payload = b64url(json.dumps(payload, separators=(',', ':')))
    signing_input = f"{encoded_header}.{encoded_payload}"

    signature = hmac.new(
        JWT_SECRET.encode('utf-8'),
        signing_input.encode('utf-8'),
        hashlib.sha256
    ).digest()

    return f"{signing_input}.{b64url(signature)}"


def make_authed_request(method, path):
    """Make authenticated request to API"""
    token = sign_jwt(USER_ID, FIRM_ID, method, path)
    headers = {
        "X-User-Id": USER_ID,
        "X-Firm-Id": FIRM_ID,
        "X-Internal-Auth": f"Bearer {token}",
        "ngrok-skip-browser-warning": "true"
    }

    url = f"{API_URL}{path}"
    print(f"\n{'='*80}")
    print(f"{method} {url}")
    print(f"Headers: {headers}")

    response = requests.request(method, url, headers=headers)
    print(f"Status: {response.status_code}")

    return response


def main():
    print("="*80)
    print("TESTING FRONTEND API FLOW")
    print("="*80)

    # Test 1: Get matter details
    print("\n[TEST 1] Get Matter Details")
    resp = make_authed_request("GET", f"/api/citeline/matters/{MATTER_ID}")
    if resp.status_code == 200:
        print(f"[OK] Matter found: {resp.json()}")
    else:
        print(f"❌ Failed: {resp.text}")
        return

    # Test 2: Get runs for matter
    print("\n[TEST 2] Get Runs for Matter")
    resp = make_authed_request("GET", f"/api/citeline/matters/{MATTER_ID}/runs")
    if resp.status_code == 200:
        runs = resp.json()
        print(f"[OK] Found {len(runs)} runs")
        for run in runs[:3]:
            print(f"   - {run['id'][:8]}... status={run['status']}")
    else:
        print(f"❌ Failed: {resp.text}")
        return

    # Test 3: Get documents for matter
    print("\n[TEST 3] Get Documents for Matter")
    resp = make_authed_request("GET", f"/api/citeline/matters/{MATTER_ID}/documents")
    if resp.status_code == 200:
        docs = resp.json()
        print(f"[OK] Found {len(docs)} documents")
    else:
        print(f"❌ Failed: {resp.text}")
        return

    # Test 4: Get evidence graph artifact
    print("\n[TEST 4] Get Evidence Graph (evidence_graph.json)")
    resp = make_authed_request("GET", f"/api/citeline/runs/{RUN_ID}/artifacts/by-name/evidence_graph.json")
    if resp.status_code == 200:
        graph = resp.json()
        events_count = len(graph.get('outputs', {}).get('evidence_graph', {}).get('events', []))
        print(f"[OK] Evidence graph loaded: {events_count} events")
        print(f"   File size: {len(resp.content) / 1024:.1f} KB")
    else:
        print(f"❌ Failed: {resp.text[:200]}")
        return

    # Test 5: Get chronology PDF
    print("\n[TEST 5] Get Chronology PDF")
    resp = make_authed_request("GET", f"/api/citeline/runs/{RUN_ID}/artifacts/pdf")
    if resp.status_code == 200:
        print(f"[OK] PDF downloaded: {len(resp.content)} bytes")
    else:
        print(f"❌ Failed: {resp.text[:200]}")
        return

    print("\n" + "="*80)
    print("ALL TESTS PASSED [OK]")
    print("="*80)
    print("\nThe API is working correctly!")
    print("If the frontend still shows errors, the issue is in the Next.js app,")
    print("not the backend API.")


if __name__ == "__main__":
    main()
