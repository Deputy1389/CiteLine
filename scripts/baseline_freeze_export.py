"""
Phase 0: Baseline Freeze for Step12 Export Refactor.

Selects 10 representative packets and generates baseline artifacts with checksums.
Run once before starting refactor to establish preservation targets.
"""
from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

BASELINE_DIR = ROOT / "tests" / "golden" / "export_baselines"
PACKET_SELECTION = [
    "01_soft_tissue_easy",
    "02_herniation_med",
    "03_surgical_hard",
    "04_prior_complex",
    "06_herniation_large_clean",
    "07_surgical_warzone",
    "08_soft_tissue_noisy",
    "09_prior_extreme",
    "10_surgical_standard",
    "batch_014_complex_prior",
]

ARTIFACTS_TO_CAPTURE = [
    ("output.pdf", "chronology.pdf"),
    ("chronology.md", "chronology.md"),
    ("qa_litigation_checklist.json", "qa_litigation_checklist.json"),
    ("luqa_report.json", "luqa_report.json"),
    ("attorney_readiness_report.json", "attorney_readiness_report.json"),
    ("selection_debug.json", "selection_debug.json"),
    ("evidence_graph.json", "evidence_graph.json"),
]


def sha256_file(path: Path) -> str:
    """Compute SHA256 hash of a file."""
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(8192), b""):
            h.update(chunk)
    return h.hexdigest()


def extract_pdf_text(pdf_path: Path) -> str:
    """Extract text from PDF using pypdf."""
    try:
        from pypdf import PdfReader
        reader = PdfReader(str(pdf_path))
        texts = []
        for page in reader.pages:
            t = page.extract_text() or ""
            texts.append(t)
        return "\n\n".join(texts)
    except Exception as e:
        return f"[ERROR extracting PDF text: {e}]"


def run_pipeline_on_packet(packet_name: str) -> dict:
    """Run run_case.py on a packet and return the context."""
    packet_pdf = ROOT / "PacketIntake" / packet_name / "packet.pdf"
    if not packet_pdf.exists():
        return {"error": f"Packet PDF not found: {packet_pdf}"}
    
    case_id = f"baseline_{packet_name}"
    run_label = f"baseline_{packet_name}_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}"
    
    result = subprocess.run(
        [sys.executable, "scripts/run_case.py", "--input", str(packet_pdf), "--case-id", case_id, "--run-label", run_label],
        cwd=str(ROOT),
        capture_output=True,
        text=True,
        timeout=600,
    )
    
    return {
        "packet": packet_name,
        "case_id": case_id,
        "run_label": run_label,
        "returncode": result.returncode,
        "stdout": result.stdout[:2000] if result.stdout else "",
        "stderr": result.stderr[:2000] if result.stderr else "",
    }


def capture_artifacts(packet_name: str, case_id: str) -> dict:
    """Capture artifacts from a completed run and compute checksums."""
    eval_dir = ROOT / "data" / "evals" / case_id
    baseline_packet_dir = BASELINE_DIR / packet_name
    baseline_packet_dir.mkdir(parents=True, exist_ok=True)
    
    captured = {}
    for artifact_spec in ARTIFACTS_TO_CAPTURE:
        if isinstance(artifact_spec, tuple):
            src_name, dst_name = artifact_spec
        else:
            src_name = dst_name = artifact_spec
        src = eval_dir / src_name
        if src.exists():
            dst = baseline_packet_dir / dst_name
            shutil.copy2(src, dst)
            captured[dst_name] = {
                "sha256": sha256_file(dst),
                "bytes": dst.stat().st_size,
            }
            if dst_name.endswith(".pdf"):
                text_path = baseline_packet_dir / f"{dst_name}.txt"
                text = extract_pdf_text(dst)
                text_path.write_text(text, encoding="utf-8")
                captured[dst_name]["text_sha256"] = sha256_file(text_path)
        else:
            captured[dst_name] = {"error": "not found"}
    
    return captured


def main() -> int:
    """Run baseline freeze for all selected packets."""
    BASELINE_DIR.mkdir(parents=True, exist_ok=True)
    
    manifest = {
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "packets": PACKET_SELECTION,
        "artifacts": ARTIFACTS_TO_CAPTURE,
        "results": {},
    }
    
    for packet_name in PACKET_SELECTION:
        print(f"\n{'='*60}")
        print(f"Processing: {packet_name}")
        print(f"{'='*60}")
        
        result = run_pipeline_on_packet(packet_name)
        if "error" in result:
            print(f"  ERROR: {result['error']}")
            manifest["results"][packet_name] = {"error": result["error"]}
            continue
        
        case_id = result["case_id"]
        print(f"  case_id: {case_id}")
        print(f"  returncode: {result['returncode']}")
        
        if result["returncode"] not in (0, 2, 3, 4):
            print(f"  WARNING: unexpected return code")
        
        captured = capture_artifacts(packet_name, case_id)
        manifest["results"][packet_name] = {
            "case_id": case_id,
            "run_label": result["run_label"],
            "returncode": result["returncode"],
            "artifacts": captured,
        }
        
        print(f"  Captured artifacts:")
        for name, info in captured.items():
            if "error" in info:
                print(f"    {name}: {info['error']}")
            else:
                print(f"    {name}: sha256={info['sha256'][:16]}... ({info['bytes']} bytes)")
    
    manifest_path = BASELINE_DIR / "baseline_manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    print(f"\n{'='*60}")
    print(f"Baseline manifest saved: {manifest_path}")
    print(f"{'='*60}")
    
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
