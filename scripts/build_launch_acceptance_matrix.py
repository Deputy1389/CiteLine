from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def _load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8-sig"))


def _status_rank(status: str) -> int:
    ranks = {
        "blocked": 0,
        "limited": 1,
        "pilot_ready": 2,
        "ready": 3,
    }
    return ranks.get(status, -1)


def _dimension(*, key: str, status: str, scope: str, evidence: dict[str, Any], decision: str) -> dict[str, Any]:
    return {
        "key": key,
        "status": status,
        "launch_scope": scope,
        "evidence": evidence,
        "decision": decision,
    }


def build_matrix(repo_root: Path) -> dict[str, Any]:
    compact = _load_json(repo_root / "reference" / "pass_057" / "cloud_batch30_rerun_20260306" / "summary.json")
    sparse_graph = _load_json(repo_root / "reference" / "run_c0e611f937cf4292a328ada3cf57d74b_evidence_graph.json")
    pass63 = _load_json(repo_root / "reference" / "pass_063" / "summary.json")
    pass64 = _load_json(repo_root / "reference" / "pass_064" / "summary.json")
    pass65 = _load_json(repo_root / "reference" / "pass_065" / "summary.json")
    pass67_path = repo_root / "reference" / "pass_067" / "summary.json"
    pass67 = _load_json(pass67_path) if pass67_path.exists() else None

    renderer_manifest = sparse_graph.get("extensions", {}).get("renderer_manifest", {})
    case_skeleton = renderer_manifest.get("case_skeleton", {})

    compact_runs = compact.get("runs", [])
    compact_count = int(compact.get("count", 0))
    compact_success = int(compact.get("status_counts", {}).get("success", 0))
    compact_exports_ok = sum(1 for run in compact_runs if run.get("exports_latest_status_code") == 200)
    compact_status = "ready" if compact_success == compact_count and compact_exports_ok == compact_count else "limited"

    sparse_status = (
        "ready"
        if renderer_manifest.get("top_case_drivers") == []
        and renderer_manifest.get("promoted_findings") == []
        and case_skeleton.get("active") is True
        else "limited"
    )

    pass63_packets = pass63.get("packets", [])
    ocr_nonempty = sum(1 for packet in pass63_packets if int(packet.get("events_total", 0)) > 0)
    if ocr_nonempty == len(pass63_packets):
        ocr_status = "ready"
    elif ocr_nonempty == 0:
        ocr_status = "blocked"
    else:
        ocr_status = "limited"

    rasterized_packet = None
    rasterized_status = "blocked"
    rasterized_decision = "Fully rasterized compact scans remain blocked because the live worker still times out and collapses extraction."
    if pass67:
        rasterized_packet = next(iter(pass67.get("packets", [])), None)
        if rasterized_packet and int(rasterized_packet.get("events_total", 0)) > 0:
            rasterized_status = "limited"
            rasterized_decision = "Fully rasterized compact scans are now recoverable, but the scan class is still under-validated and slower than text-backed packets."
    if rasterized_packet is None:
        rasterized_packet = next((packet for packet in pass63_packets if "rasterized" in str(packet.get("packet", "")).lower()), None)
        if rasterized_packet and int(rasterized_packet.get("events_total", 0)) > 0:
            rasterized_status = "limited"

    pass64_packets = pass64.get("packets", [])
    pass65_packets = pass65.get("packets", [])
    rich_status = (
        "pilot_ready"
        if bool(pass65.get("result", {}).get("event_counts_preserved"))
        and int(pass65.get("result", {}).get("office_visit_packets", 0)) == len(pass65_packets)
        and min(int(packet.get("events_total", 0)) for packet in pass65_packets) >= 8
        else "limited"
    )

    coverage_missing = [
        "non-spine orthopedic packet (shoulder or knee)",
        "TBI/neuro packet",
        "broad rasterized/OCR corpus beyond the current 3-packet sweep",
        "explicit sparse-billing acceptance packet",
    ]

    dimensions = [
        _dimension(
            key="compact_text_packets",
            status=compact_status,
            scope="narrow_pilot",
            evidence={
                "validated_packets": compact_count,
                "success_packets": compact_success,
                "exports_latest_200": compact_exports_ok,
            },
            decision="Validated compact text-backed hospital packets are ready for narrow-pilot use.",
        ),
        _dimension(
            key="sparse_packet_page1_orientation",
            status=sparse_status,
            scope="narrow_pilot",
            evidence={
                "run_id": "c0e611f937cf4292a328ada3cf57d74b",
                "top_case_drivers": len(renderer_manifest.get("top_case_drivers", [])),
                "promoted_findings": len(renderer_manifest.get("promoted_findings", [])),
                "case_skeleton_active": bool(case_skeleton.get("active")),
            },
            decision="Sparse packets no longer render a junky or empty-feeling Page 1 when anchors are absent.",
        ),
        _dimension(
            key="ocr_degraded_packets",
            status=ocr_status,
            scope="narrow_pilot",
            evidence={
                "validated_packets": pass63.get("result", {}).get("validated_packets", 0),
                "ocr_positive_packets": pass63.get("result", {}).get("ocr_positive_packets", 0),
                "non_empty_event_packets": ocr_nonempty,
                "open_issue": pass63.get("open_issue", ""),
            },
            decision="OCR is proven on some degraded packets but not yet across the full scan class.",
        ),
        _dimension(
            key="fully_rasterized_scan_packets",
            status=rasterized_status,
            scope="broad_launch",
            evidence={
                "packet": rasterized_packet.get("packet") if rasterized_packet else None,
                "status": rasterized_packet.get("status") if rasterized_packet else None,
                "pages_total": rasterized_packet.get("pages_total") if rasterized_packet else None,
                "pages_ocr": rasterized_packet.get("pages_ocr") if rasterized_packet else None,
                "events_total": rasterized_packet.get("events_total") if rasterized_packet else None,
            },
            decision=rasterized_decision,
        ),
        _dimension(
            key="rich_chronology_semantics",
            status=rich_status,
            scope="narrow_pilot",
            evidence={
                "validated_packets": len(pass65_packets),
                "event_counts_preserved": bool(pass65.get("result", {}).get("event_counts_preserved")),
                "office_visit_packets": pass65.get("result", {}).get("office_visit_packets", 0),
                "min_events_total": min(int(packet.get("events_total", 0)) for packet in pass65_packets),
                "pass64_validated_packets": len(pass64_packets),
            },
            decision="Richer spine packets preserve more chronology structure and better encounter semantics on the validated slice.",
        ),
        _dimension(
            key="coverage_breadth",
            status="blocked",
            scope="broad_launch",
            evidence={
                "validated_case_buckets": [
                    "compact text-backed hospital packets",
                    "sparse synthetic packet fallback",
                    "MVA/spine fast packet",
                    "MVA/spine complex packet",
                    "procedure-heavy spine packet",
                    "noisy OCR packet",
                ],
                "missing_buckets": coverage_missing,
            },
            decision="Broad launch remains blocked until non-spine and deeper OCR coverage are validated.",
        ),
    ]

    required_status = {
        "compact_text_packets": "ready",
        "sparse_packet_page1_orientation": "ready",
        "rich_chronology_semantics": "pilot_ready",
    }
    narrow_pilot_ready = all(
        _status_rank(d["status"]) >= _status_rank(required_status[d["key"]])
        for d in dimensions
        if d["key"] in required_status
    )
    broad_launch_ready = all(d["status"] == "ready" for d in dimensions)
    blockers = [d["decision"] for d in dimensions if d["launch_scope"] == "broad_launch" and d["status"] != "ready"]

    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "overall": {
            "recommended_launch_scope": "narrow_pilot" if narrow_pilot_ready and not broad_launch_ready else ("broad_launch" if broad_launch_ready else "hold"),
            "narrow_pilot_ready": narrow_pilot_ready,
            "broad_launch_ready": broad_launch_ready,
            "blocking_reasons": blockers,
        },
        "dimensions": dimensions,
    }


def write_outputs(repo_root: Path, matrix: dict[str, Any]) -> None:
    output_dir = repo_root / "reference" / "pass_066"
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "launch_acceptance_matrix.json").write_text(json.dumps(matrix, indent=2) + "\n", encoding="utf-8")

    lines = [
        "# Pass 066 Launch Readiness",
        "",
        f"- Recommended scope: `{matrix['overall']['recommended_launch_scope']}`",
        f"- Narrow pilot ready: `{str(matrix['overall']['narrow_pilot_ready']).lower()}`",
        f"- Broad launch ready: `{str(matrix['overall']['broad_launch_ready']).lower()}`",
        "",
        "## Dimensions",
        "",
    ]
    for dimension in matrix["dimensions"]:
        lines.append(f"### {dimension['key']}")
        lines.append(f"- Status: `{dimension['status']}`")
        lines.append(f"- Scope: `{dimension['launch_scope']}`")
        lines.append(f"- Decision: {dimension['decision']}")
        lines.append(f"- Evidence: `{json.dumps(dimension['evidence'], sort_keys=True)}`")
        lines.append("")
    lines.extend(["## Blocking Reasons", ""])
    for blocker in matrix["overall"]["blocking_reasons"]:
        lines.append(f"- {blocker}")
    lines.append("")

    (output_dir / "launch_readiness.md").write_text("\n".join(lines), encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo-root", default=".", help="Repository root")
    args = parser.parse_args()

    repo_root = Path(args.repo_root).resolve()
    matrix = build_matrix(repo_root)
    write_outputs(repo_root, matrix)


if __name__ == "__main__":
    main()
