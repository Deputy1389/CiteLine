import json
import time
from pathlib import Path

import requests

API = "https://linecite-api.onrender.com"
OUT_ROOT = Path("C:/citeline/reference/pass_052/cloud_runs")
OUT_ROOT.mkdir(parents=True, exist_ok=True)

PACKET_CYCLE = [
    ("05_minor_quick", Path("C:/Citeline/PacketIntake/05_minor_quick/packet.pdf")),
    ("batch_029_complex_prior", Path("C:/Citeline/PacketIntake/batch_029_complex_prior/packet.pdf")),
]
TOTAL_RUNS = 10
TERMINAL = {"success", "partial", "needs_review", "failed"}
POLL_SECONDS = 10
MAX_POLLS = 210  # 35 minutes max per run

session = requests.Session()


def safe_json(resp: requests.Response):
    try:
        return resp.json()
    except Exception:
        return {"_status": resp.status_code, "_text": resp.text[:2000]}


def write_json(path: Path, payload) -> None:
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


summaries = []

for idx in range(TOTAL_RUNS):
    label, packet = PACKET_CYCLE[idx % len(PACKET_CYCLE)]
    if not packet.exists():
        raise SystemExit(f"Missing packet: {packet}")

    stamp = int(time.time())
    run_label = f"run{idx+1:02d}_{label}_{stamp}"
    run_dir = OUT_ROOT / run_label
    run_dir.mkdir(parents=True, exist_ok=True)

    print(f"=== [{idx+1}/{TOTAL_RUNS}] {label}: create firm/matter", flush=True)
    firm = safe_json(session.post(f"{API}/firms", json={"name": f"Pass052 Stress {run_label}"}, timeout=120))
    if "id" not in firm:
        write_json(run_dir / "firm_error.json", firm)
        summaries.append({"index": idx + 1, "label": label, "error": "firm_create_failed", "response": firm})
        continue
    firm_id = firm["id"]

    matter_resp = session.post(
        f"{API}/firms/{firm_id}/matters",
        json={"title": f"Pass052 {run_label}", "timezone": "America/Los_Angeles"},
        timeout=120,
    )
    matter = safe_json(matter_resp)
    if matter_resp.status_code >= 300 or "id" not in matter:
        write_json(run_dir / "matter_error.json", matter)
        summaries.append({"index": idx + 1, "label": label, "error": "matter_create_failed", "response": matter})
        continue
    matter_id = matter["id"]

    print(f"=== [{idx+1}/{TOTAL_RUNS}] {label}: upload", flush=True)
    with packet.open("rb") as f:
        up_resp = session.post(
            f"{API}/matters/{matter_id}/documents",
            files={"file": ("packet.pdf", f, "application/pdf")},
            timeout=600,
        )
    upload = safe_json(up_resp)

    print(f"=== [{idx+1}/{TOTAL_RUNS}] {label}: start run", flush=True)
    run_start_resp = session.post(
        f"{API}/matters/{matter_id}/runs",
        json={"export_mode": "INTERNAL", "quality_mode": "pilot"},
        timeout=120,
    )
    started = safe_json(run_start_resp)

    run_id = str(started.get("id") or "")
    status = "pending"
    run_detail = {}

    if run_start_resp.status_code < 300 and run_id:
        print(f"=== [{idx+1}/{TOTAL_RUNS}] {label}: poll run {run_id}", flush=True)
        for poll in range(MAX_POLLS):
            time.sleep(POLL_SECONDS)
            rr = session.get(f"{API}/runs/{run_id}", timeout=120)
            run_detail = safe_json(rr)
            if rr.status_code >= 300:
                status = "failed"
                break
            status = str(run_detail.get("status") or "").lower()
            print(f"  poll {poll:03d} status={status}", flush=True)
            if status in TERMINAL:
                break

    runs_resp = session.get(f"{API}/matters/{matter_id}/runs", timeout=120)
    runs_json = safe_json(runs_resp)

    exports_resp = session.get(f"{API}/matters/{matter_id}/exports/latest?export_mode=INTERNAL", timeout=180)
    exports_json = safe_json(exports_resp)

    artifact_results = []
    required_hits = {"evidence_graph.json": False, "chronology.pdf": False, "missing_records.csv": False}

    if exports_resp.status_code == 200 and isinstance(exports_json, dict):
        artifacts = list(exports_json.get("artifacts") or [])
        for art in artifacts:
            art_type = str(art.get("artifact_type") or "")
            storage_uri = str(art.get("storage_uri") or "")
            filename = Path(storage_uri).name if storage_uri else f"{art_type}.bin"
            if not filename:
                filename = f"{art_type}.bin"
            params = {"export_mode": "INTERNAL"} if filename.lower().endswith(".pdf") else {}
            url = f"{API}/runs/{exports_json.get('run_id')}/artifacts/by-name/{filename}"
            ar = session.get(url, params=params, timeout=360)
            downloaded = ar.status_code == 200
            if downloaded:
                (run_dir / filename).write_bytes(ar.content)
                if filename in required_hits:
                    required_hits[filename] = True
            artifact_results.append(
                {
                    "filename": filename,
                    "artifact_type": art_type,
                    "status_code": ar.status_code,
                    "bytes": len(ar.content),
                }
            )

    write_json(run_dir / "firm.json", firm)
    write_json(run_dir / "matter.json", matter)
    write_json(run_dir / "upload.json", upload)
    write_json(run_dir / "run_started.json", started)
    write_json(run_dir / "run_final.json", run_detail)
    write_json(run_dir / "runs_list.json", runs_json)
    write_json(run_dir / "exports_latest.json", exports_json)
    write_json(run_dir / "artifact_download_results.json", artifact_results)
    write_json(run_dir / "required_artifacts.json", required_hits)

    summary = {
        "index": idx + 1,
        "label": label,
        "packet": str(packet),
        "run_dir": str(run_dir),
        "firm_id": firm_id,
        "matter_id": matter_id,
        "run_id": run_id,
        "run_status": status,
        "run_create_status_code": run_start_resp.status_code,
        "exports_latest_status_code": exports_resp.status_code,
        "artifacts_attempted": len(artifact_results),
        "artifacts_downloaded_ok": sum(1 for x in artifact_results if x.get("status_code") == 200),
        "required_artifacts": required_hits,
    }
    summaries.append(summary)
    print(json.dumps(summary), flush=True)

write_json(OUT_ROOT / "summary.json", summaries)

contract = {
    "total_runs": len(summaries),
    "terminal_runs": sum(1 for s in summaries if s.get("run_status") in TERMINAL),
    "exports_200_runs": sum(1 for s in summaries if s.get("exports_latest_status_code") == 200),
    "required_artifacts_all_present_runs": sum(
        1
        for s in summaries
        if all(bool(v) for v in (s.get("required_artifacts") or {}).values())
    ),
    "run_failures": [s for s in summaries if s.get("run_status") == "failed" or s.get("run_create_status_code", 500) >= 300],
}
write_json(OUT_ROOT / "artifact_contract_report.json", contract)
print("DONE")
print(json.dumps(contract, indent=2))
