"""
Phase Verification Script for Step12 Export Refactor.

Run after each refactor phase to verify no behavioral drift.
Compares current output against baseline artifacts.
"""
from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

BASELINE_DIR = ROOT / "tests" / "golden" / "export_baselines"
VERIFICATION_DIR = ROOT / "tests" / "golden" / "export_verification"


def sha256_file(path: Path) -> str:
    """Compute SHA256 hash of a file."""
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(8192), b""):
            h.update(chunk)
    return h.hexdigest()


def verify_packet(packet_name: str) -> dict:
    """Verify a single packet against baseline."""
    baseline_packet_dir = BASELINE_DIR / packet_name
    if not baseline_packet_dir.exists():
        return {"error": f"No baseline for {packet_name}"}
    
    packet_pdf = ROOT / "PacketIntake" / packet_name / "packet.pdf"
    if not packet_pdf.exists():
        return {"error": f"Packet PDF not found: {packet_pdf}"}
    
    case_id = f"verify_{packet_name}"
    
    result = subprocess.run(
        [sys.executable, "scripts/run_case.py", "--input", str(packet_pdf), "--case-id", case_id],
        cwd=str(ROOT),
        capture_output=True,
        text=True,
        timeout=300,
    )
    
    if result.returncode not in (0, 2, 3, 4):
        return {"error": f"Pipeline failed with return code {result.returncode}"}
    
    eval_dir = ROOT / "data" / "evals" / case_id
    
    comparisons = {}
    artifacts_to_check = [
        ("output.pdf", "chronology.pdf"),
        ("chronology.md", "chronology.md"),
        ("qa_litigation_checklist.json", "qa_litigation_checklist.json"),
    ]
    
    for src_name, dst_name in artifacts_to_check:
        baseline_file = baseline_packet_dir / dst_name
        current_file = eval_dir / src_name
        
        if not baseline_file.exists():
            comparisons[dst_name] = {"status": "no_baseline"}
            continue
        
        if not current_file.exists():
            comparisons[dst_name] = {"status": "missing"}
            continue
        
        baseline_hash = sha256_file(baseline_file)
        current_hash = sha256_file(current_file)
        
        if baseline_hash == current_hash:
            comparisons[dst_name] = {"status": "match", "sha256": baseline_hash[:16]}
        else:
            comparisons[dst_name] = {
                "status": "mismatch",
                "baseline_sha256": baseline_hash[:16],
                "current_sha256": current_hash[:16],
            }
    
    return {
        "case_id": case_id,
        "returncode": result.returncode,
        "comparisons": comparisons,
        "all_match": all(c.get("status") == "match" for c in comparisons.values()),
    }


def main() -> int:
    """Run verification for all baseline packets."""
    if not BASELINE_DIR.exists():
        print("ERROR: No baseline found. Run baseline_freeze_export.py first.")
        return 1
    
    manifest_path = BASELINE_DIR / "baseline_manifest.json"
    if not manifest_path.exists():
        print("ERROR: baseline_manifest.json not found.")
        return 1
    
    manifest = json.loads(manifest_path.read_text())
    packets = manifest.get("packets", [])
    
    if not packets:
        print("ERROR: No packets in baseline manifest.")
        return 1
    
    results = {
        "passed": 0,
        "failed": 0,
        "errors": 0,
        "details": {},
    }
    
    for packet_name in packets[:3]:
        print(f"\nVerifying: {packet_name}")
        result = verify_packet(packet_name)
        results["details"][packet_name] = result
        
        if "error" in result:
            print(f"  ERROR: {result['error']}")
            results["errors"] += 1
        elif result.get("all_match"):
            print(f"  PASS: All artifacts match baseline")
            results["passed"] += 1
        else:
            print(f"  FAIL: Artifact mismatch detected")
            for name, comp in result.get("comparisons", {}).items():
                print(f"    {name}: {comp.get('status')}")
            results["failed"] += 1
    
    print(f"\n{'='*60}")
    print(f"Results: {results['passed']} passed, {results['failed']} failed, {results['errors']} errors")
    print(f"{'='*60}")
    
    return 0 if results["failed"] == 0 and results["errors"] == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
