import os
import sys
import time
import json
import requests
import logging
from pathlib import Path
from datetime import datetime

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(message)s",
    handlers=[logging.StreamHandler(sys.stdout)]
)
logger = logging.getLogger(__name__)

# Config
API_URL = "http://localhost:8000"
TEST_DATA_DIR = Path("C:/CiteLine/testdata")
OUTPUT_BASE_DIR = Path("C:/CiteLine/data/batch_runs")

def get_or_create_firm(name="Batch Evaluation Firm"):
    try:
        # Simple check if exists (listing not strictly required if we just try create and catch/ignore)
        # But for batch, let's just create and ignore 201 vs 200 catch-all for MVP
        resp = requests.post(f"{API_URL}/firms", json={"name": name})
        if resp.status_code in [200, 201]:
            return resp.json()["id"]
        # If 409 conflict isn't explicitly returned but we get an error, might need handling. 
        # API MVP usually returns 201 for create.
        # Let's assume it works or we use a fallback if we had list endpoint.
        # For this script, we'll assume we can just create it.
        if resp.status_code == 409: # Conflict?
             # If we can't search, we might fail. 
             # But current API implementation of POST /firms likely just creates or returns?
             # Actually previous ingest_file ignored status != 201 somewhat.
             pass
        
        # If we failed to get ID from 201, return a fallback or strict fail?
        # Let's try to be robust.
        if "id" in resp.json():
            return resp.json()["id"]
    except Exception as e:
        logger.error(f"Failed to create firm: {e}")
    return None

def create_matter(firm_id, title):
    try:
        resp = requests.post(f"{API_URL}/firms/{firm_id}/matters", json={"title": title})
        resp.raise_for_status()
        return resp.json()["id"]
    except Exception as e:
        logger.error(f"Failed to create matter: {e}")
        return None

def process_file(pdf_path, matter_id, output_dir):
    filename = pdf_path.name
    logger.info(f"\nProcessing: {filename}")
    
    result = {
        "file": filename,
        "run_id": None,
        "status": "failed",
        "pages": 0,
        "events": 0,
        "providers": 0,
        "gaps": 0,
        "error": None
    }

    try:
        # 1. Upload
        with open(pdf_path, "rb") as f:
            resp = requests.post(
                f"{API_URL}/matters/{matter_id}/documents",
                files={"file": (filename, f, "application/pdf")}
            )
        if resp.status_code != 201:
            result["error"] = f"Upload failed: {resp.status_code} {resp.text}"
            logger.error(result["error"])
            return result
            
        doc_id = resp.json()["id"]

        # 2. Start Run
        resp = requests.post(f"{API_URL}/matters/{matter_id}/runs", json={"max_pages": 1000})
        if resp.status_code != 202: # Assuming 202 Accepted or 201 Created
             if resp.status_code != 200:
                result["error"] = f"Start run failed: {resp.status_code} {resp.text}"
                logger.error(result["error"])
                return result
        
        run_data = resp.json()
        run_id = run_data["id"]
        result["run_id"] = run_id
        logger.info(f"Run ID: {run_id}")

        # 3. Poll
        status = "pending"
        start_time = time.time()
        timeout = 300 # 5 minutes per file max
        
        while time.time() - start_time < timeout:
            try:
                resp = requests.get(f"{API_URL}/runs/{run_id}")
                if resp.status_code == 200:
                    data = resp.json()
                    status = data["status"]
                    if status in ["success", "failed", "partial"]:
                        break
            except Exception as e:
                logger.warning(f"Polling error: {e}")
            
            time.sleep(2)
        
        result["status"] = status
        logger.info(f"Status: {status}")

        if status == "running" or status == "pending":
             result["error"] = "Timed out"
             return result

        if status == "failed":
            result["error"] = data.get("error_message", "Unknown error")
            logger.error(f"Run failed: {result['error']}")
            # We still try to get artifacts if partial?
            # But usually failed means stopped.
        
        # 4. Download Artifacts & Metrics
        run_dir = output_dir / run_id
        run_dir.mkdir(parents=True, exist_ok=True)
        
        # Get Evidence Graph for metrics
        metrics_resp = requests.get(f"{API_URL}/runs/{run_id}/artifacts/json")
        if metrics_resp.status_code == 200:
            evidence = metrics_resp.json()
            # Save it
            with open(run_dir / "evidence_graph.json", "w") as f:
                json.dump(evidence, f, indent=2)
                
            # Parse metrics
            # Look at structure from previous runs
            # "outputs": { "run": { "metrics": { ... } } }
            
            run_output = evidence.get("outputs", {}).get("run", {})
            metrics = run_output.get("metrics", {})
            
            result["pages"] = metrics.get("pages_total", 0)
            result["events"] = metrics.get("events_total", 0)
            result["providers"] = metrics.get("providers_total", 0)
            
            # Gaps? "outputs": { "evidence_graph": { "gaps": [] } }
            eg_out = evidence.get("outputs", {}).get("evidence_graph", {})
            gaps = eg_out.get("gaps", [])
            result["gaps"] = len(gaps)
            
            logger.info(f"Events: {result['events']}")
        else:
            logger.warning("Could not retrieve evidence_graph.json")

        # Try download other artifacts
        for art_type in ["pdf", "csv"]:
            try:
                r = requests.get(f"{API_URL}/runs/{run_id}/artifacts/{art_type}")
                if r.status_code == 200:
                    ext = art_type
                    with open(run_dir / f"chronology.{ext}", "wb") as f:
                        f.write(r.content)
            except Exception:
                pass

    except Exception as e:
        logger.exception(f"Unexpected error processing {filename}")
        result["error"] = str(e)

    return result

def main():
    if not TEST_DATA_DIR.exists():
        logger.error(f"Test data directory not found: {TEST_DATA_DIR}")
        sys.exit(1)

    # Setup output
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    # Actually user requested C:\CiteLine\data\batch_runs\<run_id>\
    # So we should put them directly in OUTPUT_BASE_DIR? 
    # Or should we group this batch execution? 
    # "Save artifacts into: C:\CiteLine\data\batch_runs\<run_id>\" -> implies flat or per-run folders in batch_runs.
    # But usually a batch run implies a session.
    # I'll stick to the user req: output_dir = OUTPUT_BASE_DIR
    
    OUTPUT_BASE_DIR.mkdir(parents=True, exist_ok=True)
    summary_path = OUTPUT_BASE_DIR / "summary.json"
    
    # 1. Firm/Matter
    logger.info("Setting up Batch Run...")
    firm_id = get_or_create_firm()
    if not firm_id:
        logger.error("Could not get firm ID.")
        sys.exit(1)
        

    # 2. Enumerate Files
    pdf_files = list(TEST_DATA_DIR.glob("*.pdf"))
    logger.info(f"Found {len(pdf_files)} PDF files.")
    
    summary = []
    
    if summary_path.exists():
        try:
            with open(summary_path, "r") as f:
                summary = json.load(f)
        except:
            summary = []

    for pdf in pdf_files:
        matter_title = f"Batch Eval {timestamp} - {pdf.name}"
        matter_id = create_matter(firm_id, matter_title)
        if not matter_id:
            logger.error(f"Could not create matter for {pdf.name}")
            continue

        result = process_file(pdf, matter_id, OUTPUT_BASE_DIR)
        summary.append(result)
        
        # Incremental save
        with open(summary_path, "w") as f:
            json.dump(summary, f, indent=2)

    logger.info(f"\nBatch Complete. Summary saved to {summary_path}")

if __name__ == "__main__":
    main()
