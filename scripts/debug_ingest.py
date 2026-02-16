import requests
import time
import sys
from pathlib import Path

API_URL = "http://localhost:8000"
FILE_PATH = Path("C:/CiteLine/testdata/eval_06_julia_day1.pdf")

def main():
    print(f"DTO Debugging: {FILE_PATH}")
    
    # Create matter
    resp = requests.post(f"{API_URL}/firms", json={"name": "Debug Firm"})
    firm_id = resp.json().get("id") or "firm_debug"
    resp = requests.post(f"{API_URL}/firms/{firm_id}/matters", json={"title": "Debug Matter"})
    matter_id = resp.json()["id"]
    
    # Upload
    with open(FILE_PATH, "rb") as f:
        resp = requests.post(f"{API_URL}/matters/{matter_id}/documents", files={"file": (FILE_PATH.name, f, "application/pdf")})
    if resp.status_code != 201:
        print(f"Upload failed: {resp.text}")
        return
    
    # Run
    resp = requests.post(f"{API_URL}/matters/{matter_id}/runs", json={"max_pages": 1000})
    run_id = resp.json()["id"]
    print(f"Run ID: {run_id}")
    
    # Poll
    while True:
        resp = requests.get(f"{API_URL}/runs/{run_id}")
        status = resp.json()["status"]
        print(f"Status: {status}")
        if status in ["success", "failed", "partial"]:
            print(f"Result: {resp.json().get('error_message')}")
            break
        time.sleep(2)

if __name__ == "__main__":
    main()
