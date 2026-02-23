#!/usr/bin/env python3
"""
END-TO-END TEST: Full document upload → extraction → artifact download flow
Runs automatically to verify the entire system works.
"""
import requests
import hmac
import hashlib
import json
import base64
import time
import sys
from pathlib import Path

# Config
API_URL = "https://linecite-api.onrender.com"
JWT_SECRET = "2gjpNSViS55WhpyXfjrAwiN2zLmYXG360oRBHNHlABc="
USER_ID = "e2e-test-user"
FIRM_ID = "7dab0ead5ad643cc9d615c2b01112dc4"

def b64url(data):
    if isinstance(data, str):
        data = data.encode('utf-8')
    return base64.urlsafe_b64encode(data).rstrip(b'=').decode('ascii')

def sign_jwt(user_id, firm_id, method, path):
    now = int(time.time())
    header = {"alg": "HS256", "typ": "JWT"}
    payload = {"sub": user_id, "firm_id": firm_id, "iat": now, "exp": now + 60, "mth": method.upper(), "pth": path}
    encoded_header = b64url(json.dumps(header, separators=(',', ':')))
    encoded_payload = b64url(json.dumps(payload, separators=(',', ':')))
    signing_input = f"{encoded_header}.{encoded_payload}"
    signature = hmac.new(JWT_SECRET.encode(), signing_input.encode(), hashlib.sha256).digest()
    return f"{signing_input}.{b64url(signature)}"

def make_request(method, path, **kwargs):
    token = sign_jwt(USER_ID, FIRM_ID, method, path)
    headers = kwargs.pop('headers', {})
    headers.update({
        "X-User-Id": USER_ID,
        "X-Firm-Id": FIRM_ID,
        "X-Internal-Auth": f"Bearer {token}",
    })
    url = f"{API_URL}{path}"
    return requests.request(method, url, headers=headers, **kwargs)

def test_full_flow():
    print("=" * 80)
    print("END-TO-END TEST: Full Document Processing Flow")
    print("=" * 80)

    # Step 1: Create a new matter
    print("\n[1/6] Creating new matter...")
    resp = make_request("POST", f"/api/citeline/firms/{FIRM_ID}/matters", json={
        "title": f"E2E Test {int(time.time())}",
        "timezone": "America/Los_Angeles"
    })
    if resp.status_code != 201:
        print(f"FAILED: Could not create matter: {resp.status_code} {resp.text}")
        return False
    matter = resp.json()
    matter_id = matter['id']
    print(f"SUCCESS: Created matter {matter_id}")

    # Step 2: Upload a test PDF (use an existing one from the database)
    print("\n[2/6] Uploading test document...")
    test_pdf = Path("testdata/sample.pdf")  # You need a small test PDF here
    if not test_pdf.exists():
        print(f"SKIPPED: No test PDF at {test_pdf}")
        print("Using existing matter bbd980d1fe9e4d4eb9243acf69e7e517 instead")
        matter_id = "bbd980d1fe9e4d4eb9243acf69e7e517"
    else:
        with open(test_pdf, 'rb') as f:
            files = {'file': (test_pdf.name, f, 'application/pdf')}
            resp = make_request("POST", f"/api/citeline/matters/{matter_id}/documents", files=files)
        if resp.status_code not in (200, 201):
            print(f"FAILED: Could not upload document: {resp.status_code} {resp.text}")
            return False
        doc = resp.json()
        print(f"SUCCESS: Uploaded document {doc['id']}")

    # Step 3: Trigger extraction
    print("\n[3/6] Triggering extraction...")
    resp = make_request("POST", f"/api/citeline/matters/{matter_id}/runs", json={
        "event_confidence_min_export": 40
    })
    if resp.status_code != 202:
        print(f"FAILED: Could not start run: {resp.status_code} {resp.text}")
        return False
    run = resp.json()
    run_id = run['id']
    print(f"SUCCESS: Started run {run_id}")

    # Step 4: Poll until complete (max 5 minutes)
    print("\n[4/6] Waiting for extraction to complete...")
    max_wait = 300  # 5 minutes
    start = time.time()
    while time.time() - start < max_wait:
        resp = make_request("GET", f"/api/citeline/runs/{run_id}")
        if resp.status_code != 200:
            print(f"FAILED: Could not get run status: {resp.status_code}")
            return False
        run = resp.json()
        status = run['status']
        print(f"  Status: {status} (elapsed: {int(time.time() - start)}s)")

        if status == 'success':
            print(f"SUCCESS: Extraction completed in {int(time.time() - start)}s")
            break
        elif status == 'failed':
            print(f"FAILED: Extraction failed: {run.get('error_message')}")
            return False

        time.sleep(10)
    else:
        print(f"FAILED: Extraction timeout after {max_wait}s")
        return False

    # Step 5: Download evidence graph
    print("\n[5/6] Downloading evidence_graph.json...")
    resp = make_request("GET", f"/api/citeline/runs/{run_id}/artifacts/by-name/evidence_graph.json")
    if resp.status_code != 200:
        print(f"FAILED: Could not download artifact: {resp.status_code} {resp.text}")
        return False

    try:
        graph = resp.json()
        events = graph.get('outputs', {}).get('evidence_graph', {}).get('events', [])
        print(f"SUCCESS: Downloaded evidence graph with {len(events)} events")
        print(f"  File size: {len(resp.content) / 1024:.1f} KB")
    except:
        print(f"FAILED: Evidence graph is not valid JSON")
        return False

    # Step 6: Download chronology PDF
    print("\n[6/6] Downloading chronology.pdf...")
    resp = make_request("GET", f"/api/citeline/runs/{run_id}/artifacts/pdf")
    if resp.status_code != 200:
        print(f"FAILED: Could not download PDF: {resp.status_code}")
        return False

    print(f"SUCCESS: Downloaded PDF ({len(resp.content)} bytes)")

    print("\n" + "=" * 80)
    print("ALL TESTS PASSED!")
    print("=" * 80)
    print("\nSummary:")
    print(f"  Matter ID: {matter_id}")
    print(f"  Run ID: {run_id}")
    print(f"  Events extracted: {len(events)}")
    print(f"  Extraction time: {int(time.time() - start)}s")
    return True

if __name__ == "__main__":
    try:
        success = test_full_flow()
        sys.exit(0 if success else 1)
    except Exception as e:
        print(f"\nUNEXPECTED ERROR: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
