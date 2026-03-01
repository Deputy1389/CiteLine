"""
Defense Attack Map v2 — signal-based flag scanner for settlement intelligence.

Scans the evidence graph for 8 deterministic risk flags. Each triggered flag
carries a case-specific detail string, a paired defense_argument (template),
and a plaintiff_counter enriched with case-specific facts where available.

No claim-row fragility scores required — fires on any packet.

Public API:
    build_defense_attack_map(evidence_graph_payload, renderer_manifest, feature_pack=None) -> dict

Returns DefenseAttackMap.v2 dict. Never raises.
"""
from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)

# ── Flag registry ─────────────────────────────────────────────────────────────

_FLAG_DEFS: list[dict[str, str]] = [
    {
        "flag_id": "CARE_GAP_OVER_30_DAYS",
        "label": "Gap in Care (>30 days)",
        "severity": "HIGH",
        "source_type": "gap",
    },
    {
        "flag_id": "IMAGING_NO_FRACTURE",
        "label": "Imaging Negative for Fracture",
        "severity": "MED",
        "source_type": "promoted_finding",
    },
    {
        "flag_id": "CONSERVATIVE_CARE_ONLY",
        "label": "Conservative Care Only (No Surgery or Injection)",
        "severity": "MED",
        "source_type": "event",
    },
    {
        "flag_id": "SHORT_TREATMENT_DURATION",
        "label": "Short Treatment Duration (<30 days)",
        "severity": "MED",
        "source_type": "pt_summary",
    },
    {
        "flag_id": "LOW_PT_VISITS",
        "label": "Low Physical Therapy Visit Count (<6)",
        "severity": "MED",
        "source_type": "pt_summary",
    },
    {
        "flag_id": "DELAYED_FIRST_TREATMENT",
        "label": "Delayed First Treatment (>7 days post-incident)",
        "severity": "MED",
        "source_type": "event",
    },
    {
        "flag_id": "PRIOR_SIMILAR_INJURY",
        "label": "Prior Similar Injury Documented",
        "severity": "HIGH",
        "source_type": "event",
    },
    {
        "flag_id": "NO_OBJECTIVE_NEURO_DEFICIT",
        "label": "No Objective Neurological Deficit Documented",
        "severity": "LOW",
        "source_type": "event",
    },
]

_FLAGS_CHECKED = len(_FLAG_DEFS)


# ── Flag evaluators ───────────────────────────────────────────────────────────

def _eval_care_gap(fp: dict) -> tuple[bool, str, str, str, list[str]]:
    """Returns (triggered, detail, defense_argument, plaintiff_counter, citation_ids)."""
    gaps = fp.get("gaps") or []
    for g in gaps:
        try:
            days = int(g.get("duration_days") or 0)
        except Exception:
            days = 0
        if days > 30:
            gap_id = str(g.get("gap_id") or g.get("id") or "")
            date_from = g.get("date_from") or g.get("gap_start") or ""
            date_to = g.get("date_to") or g.get("gap_end") or ""
            date_range = (
                f" between {date_from} and {date_to}"
                if date_from and date_to
                else ""
            )
            # Collect all gaps > 30d for a richer detail
            large_gaps = [
                gg for gg in gaps
                if isinstance(gg, dict) and int(gg.get("duration_days") or 0) > 30
            ]
            if len(large_gaps) == 1:
                detail = f"{days}-day gap in treatment{date_range}."
            else:
                total_gap_days = sum(int(gg.get("duration_days") or 0) for gg in large_gaps)
                detail = (
                    f"{len(large_gaps)} gaps in treatment exceeding 30 days "
                    f"(largest: {days} days{date_range}; "
                    f"combined: {total_gap_days} days)."
                )
            defense = (
                f"A {days}-day gap in treatment suggests the plaintiff's condition "
                f"had resolved or was not serious enough to require ongoing care."
            )
            counter = (
                "Treatment gaps are explained by scheduling constraints, insurance "
                "authorization delays, or documented symptom plateau — not resolution. "
                "Subsequent care resumption and continued objective findings confirm "
                "persistent injury."
            )
            cids = [gap_id] if gap_id else []
            return True, detail, defense, counter, cids
    return False, "", "", "", []


def _eval_imaging_no_fracture(fp: dict) -> tuple[bool, str, str, str, list[str]]:
    imaging_pf = fp.get("imaging_promoted_findings") or []
    if not imaging_pf:
        return False, "", "", "", []
    # Imaging present — check if any have fracture
    has_fracture = fp.get("has_fracture", False)
    if has_fracture:
        return False, "", "", "", []
    cids: list[str] = []
    for pf in imaging_pf:
        for cid in (pf.get("citation_ids") or []):
            if cid and str(cid) not in cids:
                cids.append(str(cid))
    detail = (
        f"Imaging present ({len(imaging_pf)} study/studies) with no fracture documented."
    )
    defense = (
        "Imaging excludes acute fracture, undermining claims of severe structural trauma."
    )
    counter = (
        "Absence of fracture does not exclude significant injury. Cervical and lumbar "
        "disc pathology, soft tissue injury, and radiculopathy are well-documented "
        "traumatic sequelae that appear on MRI despite fracture-negative plain films. "
        "Soft tissue injuries are the predominant mechanism in low-velocity MVA cases."
    )
    return True, detail, defense, counter, cids[:5]


def _eval_conservative_care_only(fp: dict) -> tuple[bool, str, str, str, list[str]]:
    has_surgery = fp.get("has_surgery", False)
    has_injection = fp.get("has_injection", False)
    # Require at least some documented care to conclude it was conservative
    has_any_care = fp.get("has_ed_visit", False) or fp.get("has_pt", False) or fp.get("has_imaging", False)
    if has_surgery or has_injection or not has_any_care:
        return False, "", "", "", []
    detail = "No surgical procedure or injection documented. Conservative care only."
    defense = (
        "Conservative-only treatment (no injections, no surgery) indicates the injury "
        "was not severe enough to warrant escalated intervention."
    )
    counter = (
        "Conservative management is clinically appropriate for many documented soft "
        "tissue and disc injuries and reflects responsible clinical judgment rather "
        "than mild injury severity. Many patients with significant disc pathology are "
        "managed conservatively per established guidelines."
    )
    return True, detail, defense, counter, []


def _eval_short_treatment_duration(fp: dict) -> tuple[bool, str, str, str, list[str]]:
    duration = fp.get("treatment_duration_days")
    if duration is None:
        return False, "", "", "", []
    if duration >= 30:
        return False, "", "", "", []
    detail = f"Treatment duration {duration} days (threshold: 30 days)."
    defense = (
        f"A {duration}-day treatment course is consistent with minor, self-resolving "
        "injury rather than a significant traumatic condition."
    )
    counter = (
        "Treatment duration may be limited by insurance authorization, financial "
        "constraints, or documented discharge at maximum therapeutic benefit — not "
        "by symptom resolution. Ongoing pain and functional limitations are documented "
        "regardless of formal treatment end."
    )
    return True, detail, defense, counter, []


def _eval_low_pt_visits(fp: dict) -> tuple[bool, str, str, str, list[str]]:
    visits = fp.get("pt_total_encounters")
    if visits is None:
        return False, "", "", "", []
    if visits >= 6:
        return False, "", "", "", []
    detail = f"{visits} physical therapy encounter(s) documented (threshold: 6)."
    defense = (
        f"Only {visits} PT encounter(s) documented, suggesting limited functional "
        "impairment inconsistent with a serious injury claim."
    )
    counter = (
        "Low visit count may reflect early discharge at functional goals, insurance "
        "authorization limits, or transfer to home exercise program — not absence "
        "of injury. Even brief PT courses document functional deficits at intake."
    )
    return True, detail, defense, counter, []


def _eval_delayed_first_treatment(fp: dict) -> tuple[bool, str, str, str, list[str]]:
    days_delay = fp.get("days_to_first_treatment")
    if days_delay is None:
        return False, "", "", "", []
    if days_delay <= 7:
        return False, "", "", "", []
    doi = fp.get("doi") or ""
    first_date = fp.get("first_event_date") or ""
    date_context = (
        f" (incident: {doi}; first treatment: {first_date})"
        if doi and first_date
        else ""
    )
    detail = f"First documented treatment {days_delay} days after incident{date_context}."
    defense = (
        f"A {days_delay}-day delay in seeking treatment is inconsistent with acute "
        "severe injury and suggests the plaintiff did not require immediate care."
    )
    counter = (
        "Delayed treatment presentation is common in traumatic soft tissue injury where "
        "adrenaline initially masks pain. Symptom progression over 24–72 hours is "
        "well-documented in the literature. Financial and logistical barriers also "
        "contribute to delayed care-seeking after motor vehicle collisions."
    )
    return True, detail, defense, counter, []


def _eval_prior_similar_injury(fp: dict) -> tuple[bool, str, str, str, list[str]]:
    if not fp.get("has_prior_similar_injury", False):
        return False, "", "", "", []
    detail = "Prior similar injury or overlapping body region referenced in medical records."
    defense = (
        "Prior similar injury documentation raises significant causation questions: "
        "plaintiff's current complaints may be attributable to pre-existing conditions "
        "rather than the incident at issue."
    )
    counter = (
        "Pre-existing conditions do not bar recovery for aggravation of a prior condition. "
        "The eggshell plaintiff doctrine holds that defendants take plaintiffs as they find "
        "them. Medical records can document the aggravation component and delta from "
        "pre-incident baseline where documented."
    )
    return True, detail, defense, counter, []


def _eval_no_objective_neuro_deficit(fp: dict) -> tuple[bool, str, str, str, list[str]]:
    has_emg = fp.get("has_emg_positive", False)
    has_neuro = fp.get("has_neuro_deficit_keywords", False)
    # Require documented care before flagging absence of neuro deficit
    has_any_care = fp.get("has_ed_visit", False) or fp.get("has_pt", False) or fp.get("has_imaging", False)
    if has_emg or has_neuro or not has_any_care:
        return False, "", "", "", []
    detail = "No EMG positive result and no objective neurological deficit documented."
    defense = (
        "Absence of documented neurological deficit (no positive EMG, no documented "
        "sensory or motor deficit) indicates the injury is subjective complaint only."
    )
    counter = (
        "Neurological deficits are not required for compensable injury. Documented "
        "disc pathology, pain, and functional limitation are independently compensable. "
        "EMG is not ordered in every case and its absence does not indicate absence of "
        "radicular pathology."
    )
    return True, detail, defense, counter, []


# ── Assembler ─────────────────────────────────────────────────────────────────

_EVALUATORS = [
    ("CARE_GAP_OVER_30_DAYS", _eval_care_gap),
    ("IMAGING_NO_FRACTURE", _eval_imaging_no_fracture),
    ("CONSERVATIVE_CARE_ONLY", _eval_conservative_care_only),
    ("SHORT_TREATMENT_DURATION", _eval_short_treatment_duration),
    ("LOW_PT_VISITS", _eval_low_pt_visits),
    ("DELAYED_FIRST_TREATMENT", _eval_delayed_first_treatment),
    ("PRIOR_SIMILAR_INJURY", _eval_prior_similar_injury),
    ("NO_OBJECTIVE_NEURO_DEFICIT", _eval_no_objective_neuro_deficit),
]

# Map flag_id → definition metadata
_FLAG_META: dict[str, dict] = {d["flag_id"]: d for d in _FLAG_DEFS}


def _build_dam(
    eg: dict | None,
    rm: dict | None,
    feature_pack: dict | None,
) -> dict[str, Any]:
    from apps.worker.lib.settlement_features import build_settlement_feature_pack

    fp = feature_pack if isinstance(feature_pack, dict) else build_settlement_feature_pack(eg, rm)

    flags: list[dict[str, Any]] = []
    flags_triggered = 0

    for flag_id, evaluator in _EVALUATORS:
        meta = _FLAG_META[flag_id]
        try:
            triggered, detail, defense, counter, cids = evaluator(fp)
        except Exception as exc:
            logger.warning(f"DAM flag {flag_id} evaluator raised: {exc}")
            triggered, detail, defense, counter, cids = False, "", "", "", []

        if triggered:
            flags_triggered += 1

        flags.append({
            "flag_id": flag_id,
            "label": meta["label"],
            "triggered": triggered,
            "severity": meta["severity"],
            "detail": detail,
            "defense_argument": defense,
            "plaintiff_counter": counter,
            "citation_ids": cids,
            "source_type": meta["source_type"],
        })

    return {
        "schema_version": "dam.v2",
        "flags_triggered": flags_triggered,
        "flags_checked": _FLAGS_CHECKED,
        "flags": flags,
    }


def build_defense_attack_map(
    evidence_graph_payload: dict | None,
    renderer_manifest: dict | None,
    feature_pack: dict | None = None,
) -> dict[str, Any]:
    """
    Build the Defense Attack Map v2.

    Parameters
    ----------
    evidence_graph_payload
        JSON-serialised EvidenceGraph dict or None.
    renderer_manifest
        JSON-serialised RendererManifest dict or None.
    feature_pack
        Optional pre-extracted SettlementFeaturePack.v1 dict. If None, extracted
        from evidence_graph_payload and renderer_manifest.

    Returns
    -------
    dict
        DefenseAttackMap.v2 schema. Never raises.
    """
    try:
        eg = evidence_graph_payload if isinstance(evidence_graph_payload, dict) else None
        rm = renderer_manifest if isinstance(renderer_manifest, dict) else None
        return _build_dam(eg, rm, feature_pack)
    except Exception as exc:
        logger.exception(f"DefenseAttackMap build failed: {exc}")
        return {
            "schema_version": "dam.v2",
            "flags_triggered": 0,
            "flags_checked": _FLAGS_CHECKED,
            "flags": [
                {
                    "flag_id": d["flag_id"],
                    "label": d["label"],
                    "triggered": False,
                    "severity": d["severity"],
                    "detail": "",
                    "defense_argument": "",
                    "plaintiff_counter": "",
                    "citation_ids": [],
                    "source_type": d["source_type"],
                }
                for d in _FLAG_DEFS
            ],
            "error": str(exc),
        }
