
import requests
import time
import sys
import os
from pathlib import Path

# Config
API_URL = "http://localhost:8000"
PDF_PATH = "sample_pilot.pdf"

def create_sample_pdf():
    from reportlab.pdfgen import canvas
    c = canvas.Canvas(PDF_PATH)
    c.drawString(100, 750, "Medical Record")
    c.drawString(100, 730, "Patient: John Doe")
    c.drawString(100, 710, "Date: 2023-10-27")
    c.drawString(100, 690, "Provider: General Hospital")
    c.drawString(100, 670, "Chief Complaint: Severe headache.")
    c.save()
    print(f"Created {PDF_PATH}")

def run_verification():
    # 1. Create Firm
    print("1. Creating Firm...")
    resp = requests.post(f"{API_URL}/firms", json={"name": "Pilot Firm"})
    resp.raise_for_status()
    firm_id = resp.json()["id"]
    print(f"   Firm ID: {firm_id}")

    # 2. Create Matter
    print("2. Creating Matter...")
    resp = requests.post(f"{API_URL}/firms/{firm_id}/matters", json={"title": "Pilot Case"})
    resp.raise_for_status()
    matter_id = resp.json()["id"]
    print(f"   Matter ID: {matter_id}")

    # 3. Upload Document
    print("3. Uploading Document...")
    if not os.path.exists(PDF_PATH):
        create_sample_pdf()
    
    with open(PDF_PATH, "rb") as f:
        resp = requests.post(
            f"{API_URL}/matters/{matter_id}/documents",
            files={"file": (PDF_PATH, f, "application/pdf")}
        )
    resp.raise_for_status()
    doc_id = resp.json()["id"]
    print(f"   Document ID: {doc_id}")

    # 4. Start Run
    print("4. Starting Run...")
    resp = requests.post(f"{API_URL}/matters/{matter_id}/runs", json={"max_pages": 5})
    resp.raise_for_status()
    run_id = resp.json()["id"]
    print(f"   Run ID: {run_id}")

    # 5. Poll Status
    print("5. Polling Status...")
    for _ in range(30):
        resp = requests.get(f"{API_URL}/runs/{run_id}")
        resp.raise_for_status()
        data = resp.json()
        status = data["status"]
        print(f"   Status: {status}")
        if status in ["success", "failed", "partial"]:
            break
        time.sleep(1)
    
    if status != "success":
        print(f"❌ Run failed or timed out: {data}")
        sys.exit(1)

    # 6. Check Artifacts
    print("6. Checking Artifacts...")
    resp = requests.get(f"{API_URL}/matters/{matter_id}/exports/latest")
    resp.raise_for_status()
    exports = resp.json()
    print(f"   Exports: {exports}")

    print("\n✅ Verification SUCCESS! Run completed and artifacts generated.")
    # Check claim info if available in run response
    if "worker_id" in data:
        print(f"   Claimed by Worker: {data['worker_id']}")
    if "claimed_at" in data:
        print(f"   Claimed At: {data['claimed_at']}")

if __name__ == "__main__":
    try:
        run_verification()
    except Exception as e:
        print(f"\n❌ Verification Failed: {e}")
        sys.exit(1)
