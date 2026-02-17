
import requests
import time
import sys
import os
import argparse
from pathlib import Path

# Config
API_URL = "http://127.0.0.1:8000"

def ingest_file(file_path: str, output_dir: str):
    path = Path(file_path)
    if not path.exists():
        print(f"❌ File not found: {file_path}")
        sys.exit(1)
        
    print(f"🚀 Ingesting: {path.name}")
    
    # 1. Create/Get Firm
    print("1. Setting up Firm/Matter...")
    # For now, just create new ones for simplicity or reuse a known one?
    # Let's create new ones to keep runs isolated
    try:
        resp = requests.post(f"{API_URL}/firms", json={"name": "Tuning Firm"})
        if resp.status_code == 201:
            firm_id = resp.json()["id"]
        else:
            # Fallback if name conflict? (Though API doesn't enforce unique names yet)
             firm_id = resp.json().get("id") or "tuning_firm"
    except Exception as e:
        print(f"❌ API Connection Failed: {e}")
        sys.exit(1)

    resp = requests.post(f"{API_URL}/firms/{firm_id}/matters", json={"title": f"Tuning Case - {path.name}"})
    resp.raise_for_status()
    matter_id = resp.json()["id"]
    
    # 2. Upload
    print("2. Uploading...")
    with open(path, "rb") as f:
        resp = requests.post(
            f"{API_URL}/matters/{matter_id}/documents",
            files={"file": (path.name, f, "application/pdf")}
        )
    resp.raise_for_status()
    doc_id = resp.json()["id"]
    
    # 3. Start Run
    print("3. Starting Run...")
    resp = requests.post(f"{API_URL}/matters/{matter_id}/runs", json={"max_pages": 1000})
    resp.raise_for_status()
    run_id = resp.json()["id"]
    print(f"   Run ID: {run_id}")
    
    # 4. Poll
    print("4. Waiting for completion...")
    start_time = time.time()
    while True:
        resp = requests.get(f"{API_URL}/runs/{run_id}")
        if resp.status_code != 200:
            print(f"   Error polling run: {resp.status_code}")
            time.sleep(2)
            continue
            
        data = resp.json()
        status = data["status"]
        elapsed = int(time.time() - start_time)
        print(f"   [{elapsed}s] Status: {status}")
        
        if status in ["success", "failed", "partial"]:
            break
        time.sleep(2)

    if status == "failed":
        print(f"❌ Run Failed: {data.get('error_message')}")
        sys.exit(1)
        
    # 5. Download Artifacts
    print("5. Downloading Artifacts...")
    out_path = Path(output_dir) / run_id
    out_path.mkdir(parents=True, exist_ok=True)
    
    resp = requests.get(f"{API_URL}/matters/{matter_id}/exports/latest")
    if resp.status_code == 200:
        exports = resp.json()
        artifacts = exports.get("artifacts", [])
        
        # Also try to get them from the run object metrics/artifacts if available?
        # The API endpoint `GET /runs/{id}/artifacts/{type}` is the direct way.
        
        for art_type in ["pdf", "csv", "json"]:
            try:
                # The endpoint is /runs/{run_id}/artifacts/{type}
                # But wait, did we implement that exactly?
                # Looking at valid routes: router.get("/{run_id}/artifacts/{artifact_type}")
                
                resp = requests.get(f"{API_URL}/runs/{run_id}/artifacts/{art_type}")
                if resp.status_code == 200:
                    ext = "json" if art_type == "json" else art_type
                    fname = f"chronology.{ext}" if art_type != "json" else "evidence_graph.json"
                    with open(out_path / fname, "wb") as f:
                        f.write(resp.content)
                    print(f"   ✅ Saved {fname}")
                else:
                    print(f"   ⚠️ Could not download {art_type}: {resp.status_code}")
            except Exception as e:
                print(f"   ⚠️ Error downloading {art_type}: {e}")
    
    print(f"\n✨ Done! Artifacts in: {out_path.absolute()}")

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Ingest a PDF file for extraction tuning.")
    parser.add_argument("file", help="Path to PDF file")
    parser.add_argument("--out", default="tuning_output", help="Output directory")
    args = parser.parse_args()
    
    ingest_file(args.file, args.out)
