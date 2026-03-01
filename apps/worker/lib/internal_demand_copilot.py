"""
Internal Demand Co-Pilot v1 — INTERNAL ONLY demand intelligence package.

Never exported in MEDIATION mode. Fully deterministic. No LLM.
All inputs sourced from structured evidence signals only.

Public API:
    build_internal_demand_package(evidence_graph, csi_internal, damages_structured) -> dict
    classify_counteroffer(offer_amount, specials_total, adjusted_band) -> dict
"""
from __future__ import annotations

import logging
from datetime import date as _date
from decimal import Decimal, InvalidOperation
from typing import Any

logger = logging.getLogger(__name__)

# ── Schema / mode tags ───────────────────────────────────────────────────────

_SCHEMA_VERSION = "internal_demand_package.v1"
_MODE_TAG = "INTERNAL_ONLY_DO_NOT_EXPORT"

# ── Base multiplier bands by injury profile ──────────────────────────────────

_BASE_BANDS: dict[str, list[float]] = {
    "surgical":    [5.5, 9.0],
    "injection":   [3.5, 6.0],
    "disc_radic":  [2.5, 4.5],
    "soft_tissue": [2.0, 3.5],
    "minimal":     [1.5, 2.5],
}

_GLOBAL_FLOOR   = [1.0, 2.0]
_SURGERY_FLOOR  = [5.0, 8.0]
_UP_CAP         = 2.0
_DOWN_CAP       = 2.0

# ── Adjustment human-readable labels ─────────────────────────────────────────

_ADJ_LABELS: dict[str, str] = {
    "radiculopathy_documented":              "Radiculopathy documented",
    "multi_level_disc_pathology":            "Multi-level disc pathology (2+ levels)",
    "emg_ncs_positive":                      "EMG/NCS positive",
    "specialist_management":                 "Specialist management (pain mgmt/ortho/neuro)",
    "injection_or_intervention":             "Injection or interventional procedure",
    "surgery_recommended":                   "Surgery recommended (not yet performed)",
    "work_restriction_or_disability_rating": "Work restriction or disability rating documented",
    "persistent_neuro_deficit":              "Persistent neurological deficit (objective)",
    "treatment_duration_gt_180_days":        "Treatment duration >180 days",
    "treatment_duration_gt_365_days":        "Treatment duration >365 days",
    "major_gap_in_care_gt_120_days":         "Major gap in care (>120 days)",
    "gap_in_care_60_120_days":               "Gap in care (60–120 days)",
    "delayed_first_care_gt_14_days":         "Delayed first care (>14 days from DOI)",
    "prior_similar_injury":                  "Prior similar injury documented",
    "conservative_only_no_imaging":          "Conservative-only care, no imaging or specialist",
    "pt_visits_lt_6":                        "PT visits <6 (conservative-only case)",
    "imaging_negative_or_minor":             "Imaging negative or minor findings only",
}

# ── Negotiation strategy templates ───────────────────────────────────────────

_STRATEGY_MAP: dict[str, dict[str, Any]] = {
    "PUSH_HIGH_ANCHOR": {
        "opening_strategy": (
            "Lead with objective findings, escalation ladder, and treatment duration. "
            "Anchor high before discussing any risk factors."
        ),
        "anticipated_defense_moves": ["Argue overtreatment", "Challenge causation"],
        "counter_positioning": [
            "Cite independent provider corroboration",
            "Emphasize documented escalation milestones",
        ],
    },
    "ASSERTIVE_WITH_PREEMPTION": {
        "opening_strategy": (
            "Lead with objective findings and disability before addressing gap."
        ),
        "anticipated_defense_moves": [
            "Minimize treatment gap",
            "Challenge escalation necessity",
        ],
        "counter_positioning": [
            "Highlight continuous symptom documentation",
            "Emphasize treating physician rationale for escalation",
        ],
    },
    "STANDARD_WITH_REBUTTAL": {
        "opening_strategy": (
            "Open with objective findings; address risk factors proactively in opening statement."
        ),
        "anticipated_defense_moves": [
            "Attack gap duration",
            "Argue prior history contribution",
        ],
        "counter_positioning": [
            "Document gap context from treating notes",
            "Separate prior condition trajectory from current injury",
        ],
    },
    "STANDARD": {
        "opening_strategy": (
            "Present documented medical course with corroborating findings. Build to specials anchor."
        ),
        "anticipated_defense_moves": ["Argue soft-tissue only", "Challenge treatment necessity"],
        "counter_positioning": [
            "Lead with objective tier findings",
            "Present escalation ladder",
        ],
    },
    "BUILD_CASE": {
        "opening_strategy": (
            "Anchor near specials. Emphasize continuity and credibility. Address risk factors upfront."
        ),
        "anticipated_defense_moves": [
            "Lowball offer based on gaps and prior history",
            "Minimize objective findings",
        ],
        "counter_positioning": [
            "Focus on documented injury mechanism",
            "Highlight treatment compliance within documented constraints",
        ],
    },
    "ANCHOR_NEAR_SPECIALS": {
        "opening_strategy": (
            "Anchor near specials. Emphasize continuity of care and documented mechanism."
        ),
        "anticipated_defense_moves": [
            "Challenge causation entirely",
            "Offer near-specials settlement",
        ],
        "counter_positioning": [
            "Use consistency of presenting complaints as credibility anchor",
            "Keep focus on documented objective evidence",
        ],
    },
}

# ── Counteroffer response posture templates ───────────────────────────────────

_COUNTEROFFER_POSTURES: dict[str, str] = {
    "LOWBALL":           "Hold firm. Re-anchor to documented objective findings and escalation milestones.",
    "BELOW_RANGE":       "Hold firm. Decline and restate demand with documentation summary.",
    "NEGOTIABLE":        "Evaluate. Modest reduction acceptable if risk factors are significant.",
    "STRONG_OFFER":      "Strong offer within band. Evaluate litigation risk before countering.",
    "ABOVE_EXPECTATION": "Offer exceeds expected band. Evaluate carefully before countering down.",
}


# ── Private helpers ───────────────────────────────────────────────────────────

def _safe_dict(v: Any) -> dict[str, Any]:
    return v if isinstance(v, dict) else {}


def _safe_list(v: Any) -> list[Any]:
    return v if isinstance(v, list) else []


def _parse_iso_date(s: Any) -> _date | None:
    if s is None:
        return None
    try:
        parts = str(s).strip()[:10].split("-")
        if len(parts) == 3:
            return _date(int(parts[0]), int(parts[1]), int(parts[2]))
    except Exception:
        pass
    return None


def _parse_specials_total(damages: dict | None) -> float | None:
    """Extract total specials from specials_summary payload. Returns None if absent or zero."""
    if not isinstance(damages, dict):
        return None
    totals = _safe_dict(damages.get("totals"))
    raw = totals.get("total_charges")
    if raw is None:
        return None
    try:
        val = float(Decimal(str(raw)))
        return val if val > 0 else None
    except (InvalidOperation, ValueError, TypeError):
        return None


def _base_band_from_csi(csi: dict | None) -> tuple[list[float], bool]:
    """Determine base multiplier band and surgical flag from CSI tier data.

    Priority (first match wins):
      surgery/surgical_indication → [5.5, 9.0]
      injection_specialist        → [3.5, 6.0]
      radiculopathy/disc_displacement → [2.5, 4.5]
      soft_tissue                 → [2.0, 3.5]
      default                     → [1.5, 2.5]

    Returns (base_band, is_surgical). Never raises.
    """
    if not isinstance(csi, dict):
        return list(_BASE_BANDS["minimal"]), False
    tiers = _safe_dict(csi.get("selected_tiers"))
    i_tier = str(tiers.get("intensity") or "").lower()
    o_tier = str(tiers.get("objective") or "").lower()
    is_surgical = (i_tier == "surgery") or ("surgical" in o_tier)
    if is_surgical:
        return list(_BASE_BANDS["surgical"]), True
    if i_tier == "injection_specialist":
        return list(_BASE_BANDS["injection"]), False
    if "radiculopathy" in o_tier or "disc_displacement" in o_tier:
        return list(_BASE_BANDS["disc_radic"]), False
    if "soft_tissue" in o_tier:
        return list(_BASE_BANDS["soft_tissue"]), False
    return list(_BASE_BANDS["minimal"]), False


def _extract_signals(eg: dict | None, csi: dict | None) -> dict[str, Any]:
    """Extract structured clinical signals from evidence graph.

    Reads settlement_feature_pack and litigation_safe_v1 from extensions.
    Falls back to event scanning where necessary.
    Never raises.
    """
    eg = _safe_dict(eg)
    ext = _safe_dict(eg.get("extensions"))
    fp = _safe_dict(ext.get("settlement_feature_pack"))
    lsv1 = _safe_dict(ext.get("litigation_safe_v1"))
    events = _safe_list(eg.get("events"))

    # ── Duration from CSI inputs (already computed, most reliable) ─────────
    csi_safe = _safe_dict(csi)
    inputs_used = _safe_dict(csi_safe.get("inputs_used"))
    date_start = _parse_iso_date(inputs_used.get("date_start"))
    date_end = _parse_iso_date(inputs_used.get("date_end"))
    duration_days: int | None = None
    if date_start and date_end and date_end >= date_start:
        duration_days = (date_end - date_start).days

    # ── Max gap ─────────────────────────────────────────────────────────────
    max_gap_days = 0.0
    for src in (fp, lsv1):
        v = src.get("max_gap_days")
        if v is not None:
            try:
                max_gap_days = max(max_gap_days, float(v))
            except Exception:
                pass

    # ── Days to first care ──────────────────────────────────────────────────
    days_to_first_care: float | None = None
    for key in ("days_to_first_treatment", "days_to_first_care"):
        v = fp.get(key) or lsv1.get(key)
        if v is not None:
            try:
                days_to_first_care = float(v)
                break
            except Exception:
                pass

    # ── PT visit count ──────────────────────────────────────────────────────
    pt_count: int | None = None
    try:
        raw_pt = fp.get("pt_total_encounters")
        if raw_pt is not None:
            pt_count = int(raw_pt)
    except Exception:
        pass

    # ── Multi-level disc (2+ vertebral levels in diagnoses) ─────────────────
    _DISC_LEVELS = [
        "c3", "c4", "c5", "c6", "c7",
        "l1", "l2", "l3", "l4", "l5", "s1",
        "t1", "t2", "t3",
        "cervical", "lumbar", "thoracic",
    ]
    _DISC_KW = ("disc", "herniat", "displacement", "protrusion", "bulge")
    disc_levels: set[str] = set()
    for ev in events:
        for dx in _safe_list(ev.get("diagnoses")):
            text = str(dx.get("text") if isinstance(dx, dict) else dx).lower()
            if any(kw in text for kw in _DISC_KW):
                for lvl in _DISC_LEVELS:
                    if lvl in text:
                        disc_levels.add(lvl)
    multi_level_disc = len(disc_levels) >= 2

    # ── Imaging negative: only "imaging_negative_only" CSI tier ─────────────
    o_tier = str(_safe_dict(csi_safe.get("selected_tiers")).get("objective") or "").lower()
    imaging_is_negative = "imaging_negative" in o_tier

    # ── Disability / work restriction ────────────────────────────────────────
    has_disability = bool(fp.get("has_disability_rating") or fp.get("has_impairment_rating"))
    if not has_disability:
        _DISABILITY_KW = frozenset([
            "disability", "tpd", "ppd", "impairment",
            "work restriction", "restricted", "unable to work",
        ])
        for ev in events:
            for ef in _safe_list(ev.get("exam_findings")):
                t = str(ef.get("text") if isinstance(ef, dict) else ef).lower()
                if any(kw in t for kw in _DISABILITY_KW):
                    has_disability = True
                    break
            if has_disability:
                break

    # ── Surgery recommended (not performed) ─────────────────────────────────
    has_surgery = bool(fp.get("has_surgery"))
    has_surgical_indication = bool(fp.get("has_surgical_indication")) and not has_surgery

    # ── Persistent neuro deficit in last 2 dated events ─────────────────────
    _NEURO_KW = frozenset([
        "radiculopathy", "radicular", "paresthesia", "numbness",
        "tingling", "weakness", "sensory loss", "deficit", "neuropathy",
    ])
    dated_events = sorted(
        [ev for ev in events if _parse_iso_date(ev.get("date"))],
        key=lambda ev: _parse_iso_date(ev.get("date")),
    )
    last_two = dated_events[-2:]
    has_persistent_neuro = False
    for ev in last_two:
        for ef in _safe_list(ev.get("exam_findings")):
            t = str(ef.get("text") if isinstance(ef, dict) else ef).lower()
            if any(kw in t for kw in _NEURO_KW):
                has_persistent_neuro = True
                break
        if has_persistent_neuro:
            break

    return {
        "has_surgery":               has_surgery,
        "has_injection":             bool(fp.get("has_injection")),
        "has_specialist":            bool(fp.get("has_specialist")),
        "has_radiculopathy":         bool(fp.get("has_radiculopathy")),
        "has_disc_herniation":       bool(fp.get("has_disc_herniation")),
        "has_emg_positive":          bool(fp.get("has_emg_positive")),
        "has_imaging":               bool(fp.get("has_imaging")),
        "has_neuro_deficit_keywords":bool(fp.get("has_neuro_deficit_keywords")),
        "has_surgical_indication":   has_surgical_indication,
        "has_disability":            has_disability,
        "has_persistent_neuro":      has_persistent_neuro,
        "multi_level_disc":          multi_level_disc,
        "imaging_is_negative":       imaging_is_negative,
        "duration_days":             duration_days,
        "max_gap_days":              max_gap_days,
        "days_to_first_care":        days_to_first_care,
        "pt_count":                  pt_count,
        "has_prior_similar_injury":  bool(fp.get("has_prior_similar_injury")),
    }


def _compute_adjustments(
    signals: dict[str, Any],
    is_surgical: bool,
    i_tier: str,
) -> tuple[list[dict[str, Any]], float, float]:
    """Compute adjustment records with cap enforcement.

    Returns (adj_records, up_total, down_total).
    Each adjustment fires at most once. No compounding.
    """
    adj_records: list[dict[str, Any]] = []
    up_total = 0.0
    down_total = 0.0

    def _add_up(key: str, delta: float) -> None:
        nonlocal up_total
        remaining = max(0.0, _UP_CAP - up_total)
        actual = min(delta, remaining)
        if actual <= 0:
            return
        up_total = round(up_total + actual, 4)
        adj_records.append({
            "key": key,
            "label": _ADJ_LABELS.get(key, key),
            "direction": "up",
            "delta": round(actual, 2),
            "support_citation_ids": [],
        })

    def _add_down(key: str, delta: float) -> None:
        nonlocal down_total
        remaining = max(0.0, _DOWN_CAP - down_total)
        actual = min(abs(delta), remaining)
        if actual <= 0:
            return
        down_total = round(down_total + actual, 4)
        adj_records.append({
            "key": key,
            "label": _ADJ_LABELS.get(key, key),
            "direction": "down",
            "delta": -round(actual, 2),
            "support_citation_ids": [],
        })

    # ── Upward adjustments ───────────────────────────────────────────────────
    if signals["has_radiculopathy"]:
        _add_up("radiculopathy_documented", 0.5)

    if signals["multi_level_disc"]:
        _add_up("multi_level_disc_pathology", 0.5)

    if signals["has_emg_positive"]:
        _add_up("emg_ncs_positive", 0.5)

    if signals["has_specialist"]:
        _add_up("specialist_management", 0.5)

    if signals["has_injection"] and not is_surgical:
        _add_up("injection_or_intervention", 1.0)

    if signals["has_surgical_indication"]:
        _add_up("surgery_recommended", 1.0)

    if signals["has_disability"]:
        _add_up("work_restriction_or_disability_rating", 0.5)

    if signals["has_persistent_neuro"]:
        _add_up("persistent_neuro_deficit", 0.5)

    # Duration (>365 replaces >180, not additive)
    duration_days = signals.get("duration_days")
    if duration_days is not None:
        if duration_days > 365:
            _add_up("treatment_duration_gt_365_days", 1.0)
        elif duration_days > 180:
            _add_up("treatment_duration_gt_180_days", 0.5)

    # ── Downward adjustments ─────────────────────────────────────────────────
    max_gap = signals.get("max_gap_days", 0)
    if max_gap > 120:
        _add_down("major_gap_in_care_gt_120_days", 1.0)
    elif max_gap >= 60:
        _add_down("gap_in_care_60_120_days", 0.5)

    dtf = signals.get("days_to_first_care")
    if dtf is not None and dtf > 14:
        _add_down("delayed_first_care_gt_14_days", 0.5)

    if signals["has_prior_similar_injury"]:
        _add_down("prior_similar_injury", 0.5)

    # Conservative-only: no imaging AND no specialist AND no injection AND no surgery
    if (
        not signals["has_imaging"]
        and not signals["has_specialist"]
        and not signals["has_surgery"]
        and not signals["has_injection"]
    ):
        _add_down("conservative_only_no_imaging", 0.5)

    # PT visits < 6: guard — only if truly conservative (no escalation present)
    pt_count = signals.get("pt_count")
    is_conservative_case = (
        not signals["has_injection"]
        and not signals["has_surgery"]
        and not signals["has_specialist"]
        and i_tier not in {"injection_specialist", "surgery"}
    )
    if pt_count is not None and pt_count < 6 and is_conservative_case:
        _add_down("pt_visits_lt_6", 0.5)

    # Imaging negative: guard — suppress if radiculopathy/disc documented, or escalation present
    radiculopathy_active = signals["has_radiculopathy"] or signals["multi_level_disc"]
    escalation_present = signals["has_injection"] or signals["has_surgery"] or signals["has_specialist"]
    if signals["imaging_is_negative"] and not radiculopathy_active and not escalation_present:
        _add_down("imaging_negative_or_minor", 0.5)

    return adj_records, round(up_total, 4), round(down_total, 4)


def _apply_band_adjustments(
    base_band: list[float],
    up_total: float,
    down_total: float,
    is_surgical: bool,
) -> tuple[list[float], bool, bool]:
    """Apply net adjustment to base band, enforce floors.

    Returns (adjusted_band, up_cap_hit, down_cap_hit).
    """
    up_cap_hit   = up_total >= _UP_CAP
    down_cap_hit = down_total >= _DOWN_CAP
    net  = up_total - down_total
    low  = round(base_band[0] + net, 2)
    high = round(base_band[1] + net, 2)

    # Surgery floor (never below [5.0, 8.0] even under max risk)
    if is_surgical:
        low  = max(low,  _SURGERY_FLOOR[0])
        high = max(high, _SURGERY_FLOOR[1])

    # Global floor
    low  = max(low,  _GLOBAL_FLOOR[0])
    high = max(high, _GLOBAL_FLOOR[1])

    # Ensure valid band
    if low >= high:
        high = round(low + 0.5, 2)

    return [round(low, 2), round(high, 2)], up_cap_hit, down_cap_hit


def _compute_anchor(
    adjusted_band: list[float],
    specials_total: float,
    risk_count: int,
) -> dict[str, Any] | None:
    """Compute single suggested demand anchor. Returns None if specials absent."""
    if specials_total <= 0:
        return None
    low, high = adjusted_band[0], adjusted_band[1]

    # Percentile selection from risk count
    if risk_count >= 2:
        percentile = 0.70
    elif risk_count == 1:
        percentile = 0.80
    else:
        percentile = 0.90

    chosen_mult = low + percentile * (high - low)

    # Round to nearest $100
    anchor = round(specials_total * chosen_mult / 100) * 100

    # Clamp inside band
    anchor = max(anchor, specials_total * low)
    anchor = min(anchor, specials_total * high)

    # Floor safety: prevent under-anchoring in tight bands
    floor_anchor = round(specials_total * (low + 0.25) / 100) * 100
    anchor = max(anchor, floor_anchor)

    # Final upper clamp (floor safety must not push above high)
    anchor = min(anchor, specials_total * high)

    return {
        "risk_count":             risk_count,
        "percentile_used":        percentile,
        "chosen_multiplier":      round(chosen_mult, 3),
        "suggested_demand_anchor": int(anchor),
    }


def _lookup_strategy(strength_band: str, risk_count: int) -> str:
    """Deterministic negotiation strategy key lookup."""
    if strength_band in {"STRONG", "HIGH"}:
        if risk_count == 0:
            return "PUSH_HIGH_ANCHOR"
        elif risk_count == 1:
            return "ASSERTIVE_WITH_PREEMPTION"
        else:
            return "STANDARD_WITH_REBUTTAL"
    elif strength_band == "MODERATE":
        if risk_count <= 1:
            return "STANDARD"
        else:
            return "BUILD_CASE"
    return "ANCHOR_NEAR_SPECIALS"


def _build_demand_letter(
    eg: dict | None,
    specials_total: float | None,
    anchor: dict[str, Any] | None,
    csi: dict | None,
) -> dict[str, Any]:
    """Build template-driven demand letter blocks. No new facts introduced.

    Block F hard constraints:
    - No verdict prediction language ("jury would likely award", etc.)
    - No "permanent injury/disability" unless documented permanency is in structured signals
    - No multiplier or CSI values mentioned
    - Opening template only for demand line
    """
    eg = _safe_dict(eg)
    ext = _safe_dict(eg.get("extensions"))
    fp = _safe_dict(ext.get("settlement_feature_pack"))
    csi_safe = _safe_dict(csi)

    # A: Liability summary — mechanism from first event with mechanism field
    mechanism = ""
    for ev in _safe_list(eg.get("events")):
        m = str(ev.get("mechanism") or "").strip()
        if m:
            mechanism = m.lower()
            break
    if mechanism:
        a_text = (
            f"Based on documented records, the claimant sustained injuries "
            f"resulting from a {mechanism}."
        )
    else:
        a_text = (
            "Based on documented records, the claimant sustained injuries "
            "requiring medical treatment."
        )

    # B: Medical overview — CSI profile string
    b_text = str(csi_safe.get("profile") or "Documented medical findings on file.")

    # C: Treatment course — CSI component labels
    comp = _safe_dict(csi_safe.get("component_labels"))
    course_parts = [
        comp.get("treatment_intensity", ""),
        comp.get("duration", ""),
    ]
    c_text = "; ".join(p for p in course_parts if p) or "Documented treatment course on file."

    # D: Functional impact
    has_disability = bool(fp.get("has_disability_rating") or fp.get("has_neuro_deficit_keywords"))
    if has_disability:
        d_text = (
            "Documented functional limitations including work restrictions "
            "and/or neurological deficit on file."
        )
    else:
        d_text = "Documented functional limitations on file."

    # E: Damages
    if specials_total and specials_total > 0:
        e_text = f"Total documented medical expenses: ${specials_total:,.0f}"
    else:
        e_text = "Total documented medical expenses: [See attached billing records]"

    blocks: dict[str, str] = {
        "A_LIABILITY_SUMMARY": a_text,
        "B_MEDICAL_OVERVIEW":  b_text,
        "C_TREATMENT_COURSE":  c_text,
        "D_FUNCTIONAL_IMPACT": d_text,
        "E_DAMAGES":           e_text,
    }

    # F: Demand — only when anchor is available; template-locked opening
    if anchor and anchor.get("suggested_demand_anchor"):
        demand_amount = anchor["suggested_demand_anchor"]
        blocks["F_DEMAND"] = (
            f"Based on the documented objective findings, escalation of care, "
            f"and functional limitations, our client demands "
            f"${demand_amount:,} in full settlement."
        )

    return {
        "label": "INTERNAL DRAFT — DO NOT EXPORT — EDIT BEFORE SENDING",
        "blocks": blocks,
    }


def _build_attorney_notes(
    signals: dict[str, Any],
    strength_band: str,
    risk_count: int,
    up_adj_sorted: list[dict[str, Any]],
) -> list[str]:
    """Template-driven attorney notes. No new facts."""
    notes: list[str] = []

    if signals.get("max_gap_days", 0) > 120:
        notes.append(
            "Preempt care gap by citing treating notes documenting continued symptoms, "
            "insurance delays, or financial constraints."
        )

    if signals.get("has_prior_similar_injury"):
        notes.append(
            "Distinguish prior injury trajectory from current claim "
            "using treating physician records."
        )

    if strength_band in {"STRONG", "HIGH"} and risk_count == 0:
        notes.append(
            "Minimal defense exposure. "
            "Anchor demand using objective findings and escalation milestones."
        )
    elif strength_band in {"STRONG", "HIGH"}:
        notes.append(
            "Lead with objective findings and disability tier before addressing risk factors."
        )
    elif strength_band == "MODERATE":
        notes.append(
            "Build demand around documented objective findings. "
            "Address risk factors proactively."
        )
    else:
        notes.append(
            "Anchor near documented medical expenses. "
            "Emphasize treatment consistency and mechanism."
        )

    if up_adj_sorted:
        top_driver = up_adj_sorted[0].get("label", "")
        if top_driver:
            notes.append(f"Primary value driver: {top_driver}.")

    return notes


# ── Public API ────────────────────────────────────────────────────────────────

def build_internal_demand_package(
    evidence_graph: dict | None = None,
    csi_internal: dict | None = None,
    damages_structured: dict | None = None,
) -> dict[str, Any]:
    """Build the internal demand intelligence package.

    INTERNAL ONLY. Stripped from all MEDIATION artifacts by artifacts_writer and
    orchestrator strip logic. Never call from renderer.

    Args:
        evidence_graph:    Full evidence graph payload dict (model_dump output).
        csi_internal:      CSI dict from extensions["case_severity_index"].
        damages_structured: Specials summary payload dict.

    Returns:
        internal_demand_package.v1 dict. Never raises (returns error dict on failure).
    """
    try:
        # ── Specials ────────────────────────────────────────────────────────
        specials_total = _parse_specials_total(damages_structured)
        specials_block: dict[str, Any] = {
            "total": specials_total,
            "currency": "USD",
            "support_citation_ids": [],
        }

        # ── Base band ────────────────────────────────────────────────────────
        base_band, is_surgical = _base_band_from_csi(csi_internal)

        # ── Clinical signals ─────────────────────────────────────────────────
        signals = _extract_signals(evidence_graph, csi_internal)

        # ── Intensity tier (for pt_visits_lt_6 guard) ────────────────────────
        csi_safe = _safe_dict(csi_internal)
        i_tier = str(
            _safe_dict(csi_safe.get("selected_tiers")).get("intensity") or ""
        ).lower()

        # ── Adjustments ──────────────────────────────────────────────────────
        adj_records, up_total, down_total = _compute_adjustments(
            signals, is_surgical, i_tier
        )

        # ── Apply to band ─────────────────────────────────────────────────────
        adjusted_band, up_cap_hit, down_cap_hit = _apply_band_adjustments(
            base_band, up_total, down_total, is_surgical
        )

        # Sort adjustments by key (deterministic serialization order)
        adj_records.sort(key=lambda x: x["key"])

        # ── Counts ────────────────────────────────────────────────────────────
        risk_count = sum(1 for a in adj_records if a["direction"] == "down")
        up_count   = sum(1 for a in adj_records if a["direction"] == "up")

        # ── Anchor ────────────────────────────────────────────────────────────
        anchor = _compute_anchor(adjusted_band, specials_total or 0.0, risk_count)

        # ── Strength summary ──────────────────────────────────────────────────
        csi_score_100  = int(csi_safe.get("score_0_100") or 0)
        raw_strength   = csi_score_100 * 0.6 + up_count * 6 - risk_count * 8
        confidence_score = int(max(0, min(100, round(raw_strength))))
        if confidence_score <= 30:
            strength_band = "LOW"
        elif confidence_score <= 55:
            strength_band = "MODERATE"
        elif confidence_score <= 75:
            strength_band = "STRONG"
        else:
            strength_band = "HIGH"

        # Primary drivers: top 3 upward sorted by delta desc then key
        up_adj = sorted(
            [a for a in adj_records if a["direction"] == "up"],
            key=lambda x: (-x["delta"], x["key"]),
        )
        primary_drivers = [a["label"] for a in up_adj[:3]]
        primary_risks   = [a["label"] for a in adj_records if a["direction"] == "down"]
        confidence_drivers_ranked = [
            {"key": a["key"], "label": a["label"], "weight": round(a["delta"], 2)}
            for a in up_adj[:3]
        ]

        # ── Strategy ─────────────────────────────────────────────────────────
        strategy_key = _lookup_strategy(strength_band, risk_count)
        strategy_template = _STRATEGY_MAP.get(strategy_key, _STRATEGY_MAP["STANDARD"])
        negotiation_strategy: dict[str, Any] = {
            "recommended_anchor_style": strategy_key,
            **strategy_template,
        }

        # ── Demand letter ─────────────────────────────────────────────────────
        demand_letter = _build_demand_letter(
            evidence_graph, specials_total, anchor, csi_internal
        )

        # ── Attorney notes ────────────────────────────────────────────────────
        attorney_notes = _build_attorney_notes(signals, strength_band, risk_count, up_adj)

        return {
            "schema_version": _SCHEMA_VERSION,
            "specials": specials_block,
            "strength_summary": {
                "strength_band":            strength_band,
                "confidence_score_0_100":   confidence_score,
                "primary_drivers":          primary_drivers,
                "primary_risks":            primary_risks,
                "confidence_drivers_ranked": confidence_drivers_ranked,
            },
            "multiplier": {
                "base_band":    base_band,
                "adjustments":  adj_records,
                "adjusted_band": adjusted_band,
                "caps_applied": {
                    "up_cap_hit":   up_cap_hit,
                    "down_cap_hit": down_cap_hit,
                },
            },
            "anchor": anchor,
            "negotiation_strategy": negotiation_strategy,
            "demand_letter_draft": demand_letter,
            "attorney_notes":      attorney_notes,
            "mode": _MODE_TAG,
        }

    except Exception as exc:
        logger.exception("InternalDemandCopilot build failed: %s", exc)
        return {
            "schema_version": _SCHEMA_VERSION,
            "error": str(exc),
            "mode": _MODE_TAG,
        }


def classify_counteroffer(
    offer_amount: float,
    specials_total: float,
    adjusted_band: list[float],
) -> dict[str, Any]:
    """Classify an adjuster's counteroffer relative to the adjusted demand band.

    Classification is band-tied (not ratio-only) for consistency with the
    multiplier output the attorney already sees.

    Args:
        offer_amount:   Adjuster's offer in dollars.
        specials_total: Total documented medical specials.
        adjusted_band:  [low, high] from build_internal_demand_package multiplier.

    Returns:
        Dict with "classification" and "suggested_response_posture".
    """
    if specials_total <= 0 or not adjusted_band or len(adjusted_band) < 2:
        return {
            "classification": "UNKNOWN",
            "suggested_response_posture": "Insufficient data to classify offer.",
        }
    low, high = adjusted_band[0], adjusted_band[1]
    mid = specials_total * (low + high) / 2

    if offer_amount < specials_total * 1.5:
        classification = "LOWBALL"
    elif offer_amount < specials_total * low:
        classification = "BELOW_RANGE"
    elif offer_amount <= mid:
        classification = "NEGOTIABLE"
    elif offer_amount <= specials_total * high:
        classification = "STRONG_OFFER"
    else:
        classification = "ABOVE_EXPECTATION"

    return {
        "classification": classification,
        "suggested_response_posture": _COUNTEROFFER_POSTURES.get(classification, ""),
    }
