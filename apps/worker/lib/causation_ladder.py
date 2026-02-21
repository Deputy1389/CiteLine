from __future__ import annotations

import re
from datetime import date
from typing import Any

from packages.shared.models import ClaimEdge
from packages.shared.utils.claim_utils import extract_body_region
from packages.shared.utils.claim_utils import parse_iso as _parse_iso
from packages.shared.utils.claim_utils import stable_id as _stable_id

RUNG_ORDER = ["INCIDENT", "INITIAL_DX", "TREATMENT", "ESCALATION", "OUTCOME"]
RUNG_INDEX = {name: i + 1 for i, name in enumerate(RUNG_ORDER)}
TEMPORAL_DECAY_START_DAYS = 730  # 2 years
TEMPORAL_DECAY_EVERY_DAYS = 180
TEMPORAL_DECAY_STEP_POINTS = 2
MAX_TEMPORAL_DECAY_POINTS = 24

ClaimRowLike = dict[str, Any] | ClaimEdge


def _region(row: ClaimRowLike) -> str:
    reg = str(row.get("body_region") or "").strip().lower()
    if reg:
        return reg
    return extract_body_region(str(row.get("assertion") or ""))


def _rung_type(row: ClaimRowLike) -> str | None:
    ctype = str(row.get("claim_type") or "")
    txt = str(row.get("assertion") or "").lower()
    if re.search(r"\b(mva|mvc|rear[- ]end|collision|accident|emergency|chief complaint|date of injury)\b", txt):
        return "INCIDENT"
    if ctype == "INJURY_DX":
        return "INITIAL_DX"
    if ctype in {"TREATMENT_VISIT", "MEDICATION_CHANGE", "WORK_RESTRICTION"}:
        return "TREATMENT"
    if ctype in {"PROCEDURE", "IMAGING_FINDING"}:
        return "ESCALATION"
    if re.search(r"\b(discharge|return to work|mmi|maximum medical improvement|improved|final pain)\b", txt):
        return "OUTCOME"
    return None


def _provider_reliability_multiplier(provider_name: str) -> float:
    low = (provider_name or "").lower()
    if re.search(r"\b(er|emergency|orthop|neuro|spine|hospitalist|attending|surgeon|radiolog)\b", low):
        return 1.0
    if re.search(r"\b(primary care|internal medicine|family medicine|physician)\b", low):
        return 0.95
    if re.search(r"\b(physical therapy|pt|occupational therapy|ot)\b", low):
        return 0.85
    if re.search(r"\b(chiro|chiropractic)\b", low):
        return 0.75
    if not low or low == "unknown":
        return 0.8
    return 0.9


def _temporal_decay_penalty(incident: date | None, rung_date: date | None) -> int:
    if not incident or not rung_date:
        return 0
    days = (rung_date - incident).days
    if days <= TEMPORAL_DECAY_START_DAYS:
        return 0
    extra = days - TEMPORAL_DECAY_START_DAYS
    steps = max(1, extra // TEMPORAL_DECAY_EVERY_DAYS)
    return min(MAX_TEMPORAL_DECAY_POINTS, steps * TEMPORAL_DECAY_STEP_POINTS)


def _integrity_score(rungs: list[dict], incident_date: date | None) -> tuple[int, list[int], int]:
    if not rungs:
        return 0, [], 0
    score = 100
    break_points: list[int] = []
    seen = {str(r.get("rung_type") or "") for r in rungs}
    for rung_name in RUNG_ORDER:
        if rung_name not in seen:
            score -= 15
    dated = [r for r in rungs if _parse_iso(str(r.get("date") or ""))]
    for i in range(1, len(dated)):
        prev = _parse_iso(str(dated[i - 1].get("date") or ""))
        cur = _parse_iso(str(dated[i].get("date") or ""))
        if not prev or not cur:
            continue
        gap = (cur - prev).days
        if gap > 60:
            score -= 8
        if gap > 90:
            break_points.append(i + 1)
    temporal_penalty = 0
    for rung in dated:
        rung_date = _parse_iso(str(rung.get("date") or ""))
        temporal_penalty += _temporal_decay_penalty(incident_date, rung_date)
    if dated:
        temporal_penalty = int(temporal_penalty / len(dated))
    score -= temporal_penalty
    return max(0, min(100, score)), break_points, max(0, temporal_penalty)


def build_causation_ladders(claim_rows: list[ClaimRowLike]) -> list[dict]:
    grouped: dict[str, list[dict]] = {}
    for row in claim_rows:
        rt = _rung_type(row)
        if not rt:
            continue
        region = _region(row)
        key = region or "general"
        grouped.setdefault(key, []).append(row)

    chains: list[dict] = []
    for region, rows in sorted(grouped.items(), key=lambda kv: kv[0]):
        # one representative per rung/date/assertion tuple to stay deterministic and compact
        seen_rows: set[tuple[str, str, str]] = set()
        selected: list[dict] = []
        rows_sorted = sorted(
            rows,
            key=lambda r: (
                _parse_iso(str(r.get("date") or "")) or date(9999, 12, 31),
                RUNG_INDEX.get(_rung_type(r) or "", 99),
                str(r.get("id") or ""),
            ),
        )
        for row in rows_sorted:
            rung = _rung_type(row) or ""
            d = str(row.get("date") or "unknown")
            a = re.sub(r"\W+", " ", str(row.get("assertion") or "").lower()).strip()[:120]
            key = (rung, d, a)
            if key in seen_rows:
                continue
            seen_rows.add(key)
            selected.append(row)
            if len(selected) >= 18:
                break

        rungs: list[dict] = []
        prev_d: date | None = None
        incident_date: date | None = None
        provider_mult_sum = 0.0
        provider_mult_count = 0
        for row in selected:
            rung_type = _rung_type(row)
            if not rung_type:
                continue
            dval = str(row.get("date") or "unknown")
            cur_d = _parse_iso(dval)
            gap_days = None
            if prev_d and cur_d:
                gap_days = (cur_d - prev_d).days
            if cur_d:
                prev_d = cur_d
            if rung_type == "INCIDENT" and cur_d and incident_date is None:
                incident_date = cur_d
            provider_mult = _provider_reliability_multiplier(str(row.get("provider") or "unknown"))
            provider_mult_sum += provider_mult
            provider_mult_count += 1
            row_integrity = int(float(row.get("support_score") or 0) * 10 * provider_mult)
            rungs.append(
                {
                    "rung_order": RUNG_INDEX[rung_type],
                    "event_id": str(row.get("event_id") or ""),
                    "rung_type": rung_type,
                    "body_region": region,
                    "date": dval,
                    "citation_ids": list(row.get("citations") or [])[:3],
                    "temporal_gap_from_previous_days": gap_days,
                    "integrity_score": row_integrity,
                    "provider_reliability_multiplier": round(provider_mult, 2),
                }
            )
        rungs.sort(
            key=lambda r: (
                _parse_iso(str(r.get("date") or "")) or date(9999, 12, 31),
                int(r.get("rung_order") or 99),
                str(r.get("event_id") or ""),
            )
        )
        chain_score, break_points, temporal_penalty = _integrity_score(rungs, incident_date)
        avg_provider_mult = round(provider_mult_sum / provider_mult_count, 2) if provider_mult_count else 0.8
        provider_penalty = int(max(0.0, (1.0 - avg_provider_mult)) * 15)
        chain_score = max(0, chain_score - provider_penalty)
        present = {str(r.get("rung_type") or "") for r in rungs}
        missing = [name for name in RUNG_ORDER if name not in present]
        chain_id = _stable_id([region, *(str(r.get("event_id") or "") for r in rungs[:4])])
        max_days_from_incident = 0
        if incident_date:
            for rung in rungs:
                rung_date = _parse_iso(str(rung.get("date") or ""))
                if rung_date:
                    max_days_from_incident = max(max_days_from_incident, (rung_date - incident_date).days)
        chains.append(
            {
                "id": chain_id,
                "body_region": region,
                "rungs": rungs,
                "chain_integrity_score": chain_score,
                "break_points": break_points,
                "missing_rungs": missing,
                "incident_date": incident_date.isoformat() if incident_date else None,
                "temporal_decay_penalty": temporal_penalty,
                "provider_reliability_multiplier_avg": avg_provider_mult,
                "provider_reliability_penalty": provider_penalty,
                "max_days_from_incident": max_days_from_incident,
            }
        )
    chains.sort(key=lambda c: (-int(c.get("chain_integrity_score") or 0), str(c.get("body_region") or "")))
    return chains
