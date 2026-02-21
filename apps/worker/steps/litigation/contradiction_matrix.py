from __future__ import annotations

import re
from datetime import date
from typing import Any

from packages.shared.models import ClaimEdge
from packages.shared.utils.claim_utils import parse_iso as _parse_date

ClaimRowLike = dict[str, Any] | ClaimEdge


def _days_apart(a: date | None, b: date | None) -> int | None:
    if not a or not b:
        return None
    return abs((b - a).days)


def _support_strength_bucket(score: int) -> str:
    if score >= 6:
        return "Strong"
    if score >= 3:
        return "Medium"
    return "Weak"


def _pain_mentions(row: ClaimRowLike) -> list[dict]:
    txt = str(row.get("assertion") or "")
    out: list[dict] = []
    for m in re.finditer(r"\b([0-9]{1,2})\s*/\s*10\b", txt):
        val = int(m.group(1))
        if 0 <= val <= 10:
            out.append({"kind": "pain_severity", "value": str(val), "row": row})
    return out


def _laterality_mentions(row: ClaimRowLike) -> list[dict]:
    txt = str(row.get("assertion") or "").lower()
    vals: list[str] = []
    if re.search(r"\bleft\b", txt):
        vals.append("left")
    if re.search(r"\bright\b", txt):
        vals.append("right")
    return [{"kind": "laterality", "value": v, "row": row} for v in vals]


def _functional_mentions(row: ClaimRowLike) -> list[dict]:
    txt = str(row.get("assertion") or "").lower()
    out: list[dict] = []
    if re.search(r"\b(unable to work|off work|work restriction|modified duty)\b", txt):
        out.append({"kind": "functional_status", "value": "restricted", "row": row})
    if re.search(r"\b(returned to work|full duty|no restrictions)\b", txt):
        out.append({"kind": "functional_status", "value": "full_duty", "row": row})
    return out


def _mechanism_mentions(row: ClaimRowLike) -> list[dict]:
    txt = str(row.get("assertion") or "").lower()
    if re.search(r"\b(mva|mvc|motor vehicle|rear[- ]end|collision)\b", txt):
        return [{"kind": "mechanism", "value": "mva", "row": row}]
    if re.search(r"\b(fall|slip and fall)\b", txt):
        return [{"kind": "mechanism", "value": "fall", "row": row}]
    if re.search(r"\b(work injury|occupational)\b", txt):
        return [{"kind": "mechanism", "value": "work_injury", "row": row}]
    return []


def _diagnosis_mentions(row: ClaimRowLike) -> list[dict]:
    if str(row.get("claim_type") or "") != "INJURY_DX":
        return []
    txt = str(row.get("assertion") or "").lower()
    if re.search(r"\b(cervical strain|whiplash)\b", txt):
        return [{"kind": "diagnosis_track", "value": "cervical_strain", "row": row}]
    if re.search(r"\b(lumbar strain|lumbago)\b", txt):
        return [{"kind": "diagnosis_track", "value": "lumbar_strain", "row": row}]
    if re.search(r"\b(radiculopathy)\b", txt):
        return [{"kind": "diagnosis_track", "value": "radiculopathy", "row": row}]
    if re.search(r"\b(neck pain|cervicalgia)\b", txt):
        return [{"kind": "diagnosis_track", "value": "neck_pain", "row": row}]
    if re.search(r"\b(low back pain|back pain)\b", txt):
        return [{"kind": "diagnosis_track", "value": "low_back_pain", "row": row}]
    return []


def _collect_mentions(row: ClaimRowLike) -> list[dict]:
    out: list[dict] = []
    out.extend(_pain_mentions(row))
    out.extend(_laterality_mentions(row))
    out.extend(_functional_mentions(row))
    out.extend(_mechanism_mentions(row))
    out.extend(_diagnosis_mentions(row))
    return out


def _is_contradiction(kind: str, a_val: str, b_val: str) -> bool:
    if kind in {"laterality", "mechanism", "functional_status"}:
        return a_val != b_val
    if kind == "pain_severity":
        try:
            return abs(int(a_val) - int(b_val)) >= 3
        except ValueError:
            return False
    if kind == "diagnosis_track":
        # Only contradictions for same body-track family conflicts.
        pairs = {
            ("cervical_strain", "neck_pain"),
            ("lumbar_strain", "low_back_pain"),
        }
        if a_val == b_val:
            return False
        return (a_val, b_val) not in pairs and (b_val, a_val) not in pairs
    return False


def build_contradiction_matrix(claim_rows: list[ClaimRowLike], *, window_days: int = 45) -> list[dict]:
    mentions: list[dict] = []
    for row in claim_rows:
        citations = [str(c).strip() for c in (row.get("citations") or []) if str(c).strip()]
        for m in _collect_mentions(row):
            m["date_obj"] = _parse_date(str(row.get("date") or ""))
            m["date"] = str(row.get("date") or "unknown")
            m["support_score"] = int(row.get("support_score") or 0)
            m["citations"] = citations[:3]
            mentions.append(m)

    matrix: list[dict] = []
    seen_keys: set[tuple[str, str, str, str]] = set()
    for i in range(len(mentions)):
        for j in range(i + 1, len(mentions)):
            a = mentions[i]
            b = mentions[j]
            if a["kind"] != b["kind"]:
                continue
            apart = _days_apart(a.get("date_obj"), b.get("date_obj"))
            if apart is not None and apart > window_days:
                continue
            if not _is_contradiction(str(a["kind"]), str(a["value"]), str(b["value"])):
                continue
            key = (
                str(a["kind"]),
                str(a["value"]),
                str(b["value"]),
                str(min(a["date"], b["date"])),
            )
            if key in seen_keys:
                continue
            seen_keys.add(key)
            delta = abs(int(a.get("support_score") or 0) - int(b.get("support_score") or 0))
            matrix.append(
                {
                    "category": str(a["kind"]),
                    "supporting": {
                        "date": a["date"],
                        "value": str(a["value"]),
                        "support_score": int(a.get("support_score") or 0),
                        "support_strength": _support_strength_bucket(int(a.get("support_score") or 0)),
                        "citations": list(a.get("citations") or []),
                    },
                    "contradicting": {
                        "date": b["date"],
                        "value": str(b["value"]),
                        "support_score": int(b.get("support_score") or 0),
                        "support_strength": _support_strength_bucket(int(b.get("support_score") or 0)),
                        "citations": list(b.get("citations") or []),
                    },
                    "strength_delta": delta,
                    "window_days": apart,
                }
            )

    matrix.sort(
        key=lambda r: (
            -int(r.get("strength_delta") or 0),
            str(r.get("category") or ""),
            str(((r.get("supporting") or {}).get("date") or "")),
        )
    )
    return matrix[:24]
