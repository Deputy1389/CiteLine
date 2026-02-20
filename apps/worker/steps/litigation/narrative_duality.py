from __future__ import annotations

from apps.worker.lib.claim_ledger_lite import select_top_claim_rows
from apps.worker.steps.case_collapse import build_case_collapse_candidates, build_defense_attack_paths
from apps.worker.steps.litigation.contradiction_matrix import build_contradiction_matrix


def build_narrative_duality(claim_rows: list[dict]) -> dict:
    top = select_top_claim_rows(claim_rows, limit=12)
    plaintiff_points: list[dict] = []
    for row in top:
        ctype = str(row.get("claim_type") or "")
        if ctype not in {"PROCEDURE", "IMAGING_FINDING", "INJURY_DX", "WORK_RESTRICTION", "GAP_IN_CARE"}:
            continue
        plaintiff_points.append(
            {
                "date": str(row.get("date") or "unknown"),
                "assertion": str(row.get("assertion") or ""),
                "claim_type": ctype,
                "support_strength": str(row.get("support_strength") or "Weak"),
                "citations": list((row.get("citations") or []))[:3],
            }
        )
        if len(plaintiff_points) >= 5:
            break

    collapse = build_case_collapse_candidates(claim_rows)
    attacks = build_defense_attack_paths(collapse, limit=5)
    defense_points: list[dict] = []
    for a in attacks:
        defense_points.append(
            {
                "attack": str(a.get("attack") or ""),
                "path": str(a.get("path") or ""),
                "confidence_tier": str(a.get("confidence_tier") or "Low"),
                "citations": list((a.get("citations") or []))[:3],
            }
        )
    if not defense_points:
        matrix = build_contradiction_matrix(claim_rows, window_days=60)
        for row in matrix[:4]:
            s = row.get("supporting") or {}
            c = row.get("contradicting") or {}
            defense_points.append(
                {
                    "attack": f"{str(row.get('category') or '').replace('_', ' ').title()} conflict",
                    "path": (
                        f"Supporting {s.get('value')} ({s.get('date')}) conflicts with "
                        f"{c.get('value')} ({c.get('date')})."
                    ),
                    "confidence_tier": "Medium",
                    "citations": list((s.get("citations") or [])[:1] + (c.get("citations") or [])[:1]),
                }
            )

    return {
        "plaintiff_narrative": {
            "summary": "Citation-backed medical progression emphasizing objective findings and treatment escalation.",
            "points": plaintiff_points,
        },
        "defense_narrative": {
            "summary": "Citation-backed competing medical interpretation emphasizing fragility points.",
            "points": defense_points,
        },
    }
