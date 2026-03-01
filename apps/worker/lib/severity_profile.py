"""
Mediation-safe severity profile transform.

Transforms internal CSI payloads into a deterministic, citation-backed
surface contract with no valuation math fields.
"""
from __future__ import annotations

from typing import Any


def _safe_dict(v: Any) -> dict[str, Any]:
    return v if isinstance(v, dict) else {}


def _safe_list(v: Any) -> list[Any]:
    return v if isinstance(v, list) else []


def _clean(v: Any) -> str:
    s = str(v or "").strip()
    return " ".join(s.split())


def _sorted_unique_str(items: list[Any]) -> list[str]:
    out = sorted({str(x).strip() for x in items if str(x).strip()})
    return out


_BAND_MAP = {
    "Minor soft tissue": {"primary_label": "Low objective severity profile", "band": "LOW"},
    "Moderate soft tissue": {"primary_label": "Moderate soft tissue profile", "band": "MODERATE"},
    "Moderate soft tissue with objective support": {"primary_label": "Objective-support profile", "band": "MODERATE_PLUS"},
    "Injection-tier profile": {"primary_label": "Injection-tier treatment profile", "band": "HIGH"},
    "Surgical-tier profile": {"primary_label": "Surgical-tier treatment profile", "band": "CRITICAL"},
}


_RISK_FACTOR_MAP = {
    "care_gap_over_60_days": "Defense may argue treatment interruption weakens continuity.",
    "prior_similar_injury": "Defense may argue symptoms overlap with prior similar injury history.",
    "delayed_first_care_over_14_days": "Defense may argue delayed first care weakens acute-causation framing.",
}

_RISK_CONTEXT_MAP = {
    "care_gap_over_60_days": "Continuity concern appears in timeline chronology.",
    "prior_similar_injury": "Prior-history concern appears in cited record context.",
    "delayed_first_care_over_14_days": "Delay-to-care concern appears in early treatment chronology.",
}


def build_severity_profile(csi_internal: dict[str, Any] | None) -> dict[str, Any]:
    csi = _safe_dict(csi_internal)
    comp = _safe_dict(csi.get("component_scores"))
    objective = _safe_dict(comp.get("objective"))
    intensity = _safe_dict(comp.get("intensity"))
    duration = _safe_dict(comp.get("duration"))
    support = _safe_dict(csi.get("support"))
    band_raw = _clean(csi.get("band"))
    band_cfg = _BAND_MAP.get(band_raw, {"primary_label": "Medical severity profile", "band": "MODERATE"})

    all_citation_ids = _sorted_unique_str(_safe_list(support.get("citation_ids")))
    all_page_refs = [r for r in _safe_list(support.get("page_refs")) if isinstance(r, dict)]

    drivers = []
    for rank, (name, payload) in enumerate(
        [
            ("objective", objective),
            ("intensity", intensity),
            ("duration", duration),
        ],
        start=1,
    ):
        label = _clean(payload.get("label"))
        tier_key = _clean(payload.get("tier_key"))
        if not label:
            continue
        drivers.append(
            {
                "rank": rank,
                "component": name,
                "tier_key": tier_key,
                "label": label,
                "support_citation_ids": list(all_citation_ids),
            }
        )

    progression = []
    intensity_tier = _clean(intensity.get("tier_key"))
    duration_tier = _clean(duration.get("tier_key"))
    intensity_label = _clean(intensity.get("label"))
    duration_label = _clean(duration.get("label"))
    if intensity_label:
        progression.append(
            {
                "phase": "intensity",
                "tier_key": intensity_tier,
                "label": intensity_label,
                "support_citation_ids": list(all_citation_ids),
            }
        )
    if duration_label:
        progression.append(
            {
                "phase": "duration",
                "tier_key": duration_tier,
                "label": duration_label,
                "support_citation_ids": list(all_citation_ids),
            }
        )

    defense = []
    for factor in _sorted_unique_str(_safe_list(csi.get("risk_factors"))):
        defense.append(
            {
                "factor_key": factor,
                "argument": _RISK_FACTOR_MAP.get(factor, "Defense may challenge causation or continuity based on record context."),
                "context_supported_in_records": _RISK_CONTEXT_MAP.get(factor, "Context appears in cited records and should be addressed directly."),
                "support_citation_ids": list(all_citation_ids),
            }
        )

    profile = {
        "schema_version": "severity_profile.v1",
        "export_intent": "mediation",
        "provenance": {
            "source_schema": _clean(csi.get("schema_version")) or "csi.internal",
            "transform_version": "severity_profile.transform.v1",
        },
        "primary_label": band_cfg["primary_label"],
        "band": band_cfg["band"],
        "severity_drivers": drivers,
        "treatment_progression": progression,
        "anticipated_defense_arguments": defense,
        "support": {
            "citation_ids": list(all_citation_ids),
            "page_refs": all_page_refs,
        },
    }
    return profile

