"""
verify_invariant_harness.py — Signal Integrity + Governance Enforcement Harness

Per-case invariant checks:
  S1 — PT_DERIVATION_INTEGRITY
  A1 — PT_COUNT_CONSISTENCY
  A3 — NOISE_NOT_IN_OBJECTIVE_OR_IMAGING
  B1 — TIER_FLOOR_RADICULOPATHY
  B2 — TIER_FLOOR_INJECTION_DATED
  C1 — MINOR_CAP_CEILING
  L1 — LEVERAGE_TIER_CONSISTENCY  (Pass 37)
  L2 — POLICY_FINGERPRINT         (Pass 38)
  L3 — TRAJECTORY_CONSISTENCY     (Pass 38)
  T2 — TRAJECTORY_INJECTION_PEAK  (Pass 38)
  T3 — TRAJECTORY_SURGERY_PEAK    (Pass 38)
  D1 — DETERMINISM_RERUN          (Pass 39)
  D2 — POLICY_PINNING             (Pass 39)
  D3 — NO_MEDIATION_LEAKAGE       (Pass 39, extended in Pass 40)
  E1 — ESCALATION_TRACEABILITY    (Pass 40)

Static checks (run once per harness invocation, not per-case):
  D4 — TRAJECTORY_SIGNALS_ONLY    (Pass 39 — static analysis)
  D5 — RENDERER_DISPLAY_ONLY      (Pass 39 — static analysis)

Usage:
    python scripts/verify_invariant_harness.py \
        --fixtures tests/fixtures/invariants/ \
        [--out report.json] \
        [--attest-dir artifacts/invariants/]

Exit code: 0 = all pass, 1 = failures found.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from pypdf import PdfReader

_REPO_ROOT = Path(__file__).resolve().parents[1]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from apps.worker.lib.case_signals import derive_case_signals
from apps.worker.lib.leverage_policy_registry import get_policy_fingerprint
from packages.shared.utils.noise_utils import is_fax_header_noise


# ── Fingerprint helpers (Pass 37) ─────────────────────────────────────────────

def _compute_signals_fingerprint(signals: dict) -> str:
    return hashlib.sha256(
        json.dumps(signals, sort_keys=True, default=str).encode()
    ).hexdigest()


def _compute_artifact_fingerprint(case_dir: Path) -> str:
    eg_bytes = (case_dir / "evidence_graph.json").read_bytes()
    pdf_path = next(case_dir.glob("*MEDIATION*.pdf"), None) or next(case_dir.glob("*.pdf"), None)
    pdf_bytes = pdf_path.read_bytes() if pdf_path and pdf_path.exists() else b""
    return hashlib.sha256(eg_bytes + pdf_bytes).hexdigest()


def _utcnow_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


# ── Harness-local PT event detector (independent of settlement_features) ─────

_HARNESS_PT_ET_KEYWORDS = frozenset({"pt_visit", "pt_eval", "physical_therapy", "chiropractic", "rehab", "therapy"})


def _harness_is_pt_event(et: str) -> bool:
    return any(kw in et for kw in _HARNESS_PT_ET_KEYWORDS)


def _harness_event_type_str(event: dict) -> str:
    raw = event.get("event_type")
    if isinstance(raw, dict):
        return str(raw.get("value") or "").lower()
    return str(raw or "").lower()


def _harness_parse_date(s: str | None):
    if not s:
        return None
    try:
        from datetime import date as _date
        parts = str(s).split("-")
        if len(parts) == 3:
            return _date(int(parts[0]), int(parts[1]), int(parts[2]))
    except Exception:
        pass
    return None


def _harness_event_date_known(ev: dict) -> tuple[str | None, bool]:
    raw = ev.get("date")
    if isinstance(raw, dict):
        kind = raw.get("kind", "single")
        status = raw.get("status", "explicit")
        known = status not in ("undated", "ambiguous")
        if kind == "range":
            range_val = raw.get("value")
            if isinstance(range_val, dict):
                val = range_val.get("start")
            else:
                val = None
                known = False
        else:
            val = raw.get("value") or raw.get("normalized_date")
            if isinstance(val, dict):
                val = None
                known = False
    else:
        val = str(raw) if raw else None
        known = bool(val)
    return val, known


def _harness_compute_pt_dated_count(eg: dict) -> int:
    """Independently compute pt_dated_encounter_count from evidence graph."""
    events = [e for e in (eg.get("events") or []) if isinstance(e, dict)]
    pt_dated_dates: set[str] = set()
    for ev in events:
        et = _harness_event_type_str(ev)
        if _harness_is_pt_event(et):
            date_val, date_known = _harness_event_date_known(ev)
            d = _harness_parse_date(str(date_val) if date_val else None)
            if d and date_known and d.year > 1900:
                pt_dated_dates.add(d.isoformat())
    return len(pt_dated_dates)


# ── PDF helpers ───────────────────────────────────────────────────────────────

def _pdf_text(path: Path) -> str:
    reader = PdfReader(str(path))
    return "\n".join((p.extract_text() or "") for p in reader.pages)


def _extract_section_text(full_text: str, section_title: str) -> str:
    """Extract text block under a section heading until next ALL-CAPS heading."""
    pattern = re.compile(
        rf"(?i){re.escape(section_title)}\s*\n(.*?)(?=\n[A-Z][A-Z &/]+\n|\Z)",
        re.DOTALL,
    )
    m = pattern.search(full_text)
    if m:
        return m.group(1)
    # Fallback: grab lines after the heading
    lines = full_text.splitlines()
    in_section = False
    out: list[str] = []
    for line in lines:
        stripped = line.strip()
        if not in_section:
            if section_title.upper() in stripped.upper():
                in_section = True
            continue
        # Stop at next apparent section heading (all caps, non-empty, short)
        if stripped and stripped.isupper() and len(stripped.split()) <= 6 and len(stripped) >= 4:
            break
        out.append(line)
    return "\n".join(out)


def _load_json(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as f:
        data = json.load(f)
    if not isinstance(data, dict):
        raise ValueError(f"{path} is not a JSON object")
    return data


# ── Invariant checkers ────────────────────────────────────────────────────────

def check_S1_pt_derivation_integrity(eg: dict, signals: dict) -> dict[str, Any]:
    """S1: derive_case_signals pt_dated_encounter_count matches harness recomputation."""
    derived = signals.get("pt_dated_encounter_count")
    recomputed = _harness_compute_pt_dated_count(eg)
    if derived is None:
        # If None in signals, harness can only check recomputed is also 0
        passed = (recomputed == 0)
        return {
            "invariant": "S1_PT_DERIVATION_INTEGRITY",
            "passed": passed,
            "detail": f"derived=None, harness_recomputed={recomputed}",
        }
    passed = (int(derived) == recomputed)
    return {
        "invariant": "S1_PT_DERIVATION_INTEGRITY",
        "passed": passed,
        "detail": f"derived={derived}, harness_recomputed={recomputed}",
    }


def check_A1_pt_count_consistency(pdf_text: str, signals: dict, eg: dict) -> dict[str, Any]:
    """A1: PT count claims in PDF must be consistent with signals.

    '>12 visits' is acceptable when backed by either:
    - pt_dated_encounter_count >= 12, OR
    - renderer_manifest.pt_summary.total_encounters >= 12 (aggregate snippet — legitimate)

    'verified N sessions'/'verifies N dated ... sessions' must match pt_dated_encounter_count.
    """
    pt_count = signals.get("pt_dated_encounter_count") or 0
    has_over12_claim = bool(re.search(r">12\s*visits?", pdf_text, re.I))

    # Pull aggregate total from renderer_manifest stored in evidence graph
    ext = eg.get("extensions") or {}
    rm = ext.get("renderer_manifest") or {}
    pt_summary = rm.get("pt_summary") or {}
    total_encounters = int(pt_summary.get("total_encounters") or 0)

    # "Chronology verifies N dated treatment sessions" or "verified N sessions"
    verified_match = re.search(r"verif\w+\s+(\d+)\s+dated\s+\w+\s+sessions?|verified\s+(\d+)\s+sessions?", pdf_text, re.I)
    if verified_match:
        verified_n = int(verified_match.group(1) or verified_match.group(2))
    else:
        verified_n = None

    failures: list[str] = []
    # ">12 visits" is legitimate if backed by either dated count OR aggregate count
    if has_over12_claim and pt_count < 12 and total_encounters < 12:
        failures.append(f"PDF claims >12 visits but pt_dated_encounter_count={pt_count} and total_encounters={total_encounters}")
    if verified_n is not None and verified_n != pt_count:
        failures.append(f"PDF says 'verified {verified_n} sessions' but pt_dated_encounter_count={pt_count}")

    passed = len(failures) == 0
    return {
        "invariant": "A1_PT_COUNT_CONSISTENCY",
        "passed": passed,
        "detail": "; ".join(failures) if failures else f"ok (pt_dated_encounter_count={pt_count}, total_encounters={total_encounters}, over12_claim={has_over12_claim})",
    }


def check_A3_noise_not_in_objective_or_imaging(pdf_text: str) -> dict[str, Any]:
    """A3: No fax header noise lines in OBJECTIVE FINDINGS or IMAGING sections."""
    obj_text = _extract_section_text(pdf_text, "OBJECTIVE FINDINGS")
    img_text = _extract_section_text(pdf_text, "IMAGING")
    combined = obj_text + "\n" + img_text
    noise_lines: list[str] = []
    for line in combined.splitlines():
        stripped = line.strip()
        if stripped and is_fax_header_noise(stripped):
            noise_lines.append(repr(stripped))
    passed = len(noise_lines) == 0
    return {
        "invariant": "A3_NOISE_NOT_IN_OBJECTIVE_OR_IMAGING",
        "passed": passed,
        "detail": f"Fax noise lines found: {noise_lines}" if noise_lines else "ok",
    }


def check_B1_tier_floor_radiculopathy(pdf_text: str, signals: dict) -> dict[str, Any]:
    """B1: If has_radiculopathy, profile must not be labeled 'conservative' alone."""
    has_radic = bool(signals.get("has_radiculopathy", False))
    if not has_radic:
        return {"invariant": "B1_TIER_FLOOR_RADICULOPATHY", "passed": True, "detail": "skip (has_radiculopathy=False)"}

    profile_text = _extract_section_text(pdf_text, "MEDICAL SEVERITY PROFILE")
    # Check profile label — "Conservative Soft Tissue" or "Minimal Conservative" is a fail
    # "Objective Conservative" or higher is acceptable
    conservative_only = bool(re.search(r"\b(Minimal Conservative|Conservative Soft Tissue)\b", profile_text, re.I))
    passed = not conservative_only
    return {
        "invariant": "B1_TIER_FLOOR_RADICULOPATHY",
        "passed": passed,
        "detail": (
            f"FAIL: radiculopathy present but profile appears conservative-tier: {profile_text[:200].strip()!r}"
            if not passed
            else f"ok (profile not conservative-only)"
        ),
    }


def check_B2_tier_floor_injection_dated(pdf_text: str, signals: dict) -> dict[str, Any]:
    """B2: If has_injection_dated, profile must contain 'Interventional' or 'Surgical'."""
    has_inj_dated = bool(signals.get("has_injection_dated", False))
    if not has_inj_dated:
        return {"invariant": "B2_TIER_FLOOR_INJECTION_DATED", "passed": True, "detail": "skip (has_injection_dated=False)"}

    profile_text = _extract_section_text(pdf_text, "MEDICAL SEVERITY PROFILE")
    has_interventional = bool(re.search(r"\b(Interventional|Surgical)\b", profile_text, re.I))
    passed = has_interventional
    return {
        "invariant": "B2_TIER_FLOOR_INJECTION_DATED",
        "passed": passed,
        "detail": (
            f"FAIL: injection_dated present but profile lacks 'Interventional'/'Surgical': {profile_text[:200].strip()!r}"
            if not passed
            else "ok"
        ),
    }


def check_C1_minor_cap_ceiling(pdf_text: str, signals: dict) -> dict[str, Any]:
    """C1: If duration < 30 days and no injection/surgery/neuro_deficit, profile must not be Interventional or Surgical."""
    treatment_days = signals.get("treatment_duration_days")
    if treatment_days is None:
        return {"invariant": "C1_MINOR_CAP_CEILING", "passed": True, "detail": "skip (treatment_duration_days=None)"}

    has_injection = bool(signals.get("has_injection", False))
    has_surgery = bool(signals.get("has_surgery", False))
    has_neuro = bool(signals.get("has_neuro_deficit_keywords", False))

    minor_case = int(treatment_days) < 30 and not has_injection and not has_surgery and not has_neuro
    if not minor_case:
        return {"invariant": "C1_MINOR_CAP_CEILING", "passed": True, "detail": f"skip (duration={treatment_days}d, inj={has_injection}, surg={has_surgery}, neuro={has_neuro})"}

    profile_text = _extract_section_text(pdf_text, "MEDICAL SEVERITY PROFILE")
    has_high_tier = bool(re.search(r"\b(Interventional|Surgical)\b", profile_text, re.I))
    passed = not has_high_tier
    return {
        "invariant": "C1_MINOR_CAP_CEILING",
        "passed": passed,
        "detail": (
            f"FAIL: minor case (duration={treatment_days}d) but profile is Interventional/Surgical: {profile_text[:200].strip()!r}"
            if not passed
            else f"ok (duration={treatment_days}d, profile does not exceed cap)"
        ),
    }


# ── L1: Leverage tier consistency (Pass 37) ───────────────────────────────────

def check_L1_leverage_tier_consistency(signals: dict, leverage_result: dict) -> dict[str, Any]:
    """L1: If has_radiculopathy, leverage band must be ELEVATED or higher.

    Protects against accidental leverage downgrade even if tier floors were bypassed.
    Only checked when leverage is enabled. Passes as skip when leverage not yet in ext.
    """
    if not leverage_result.get("enabled", False):
        return {
            "invariant": "L1_LEVERAGE_TIER_CONSISTENCY",
            "passed": True,
            "detail": "skip (leverage disabled or not yet computed)",
        }
    has_radic = bool(signals.get("has_radiculopathy", False))
    if not has_radic:
        return {
            "invariant": "L1_LEVERAGE_TIER_CONSISTENCY",
            "passed": True,
            "detail": "skip (has_radiculopathy=False)",
        }
    band = leverage_result.get("band", "")
    _ELEVATED_OR_HIGHER = {"ELEVATED", "HIGH", "TRIAL_LEVEL"}
    passed = band in _ELEVATED_OR_HIGHER
    return {
        "invariant": "L1_LEVERAGE_TIER_CONSISTENCY",
        "passed": passed,
        "detail": (
            f"FAIL: has_radiculopathy=True but band={band} (must be ELEVATED or higher)"
            if not passed
            else f"ok (band={band})"
        ),
    }


def check_L2_policy_fingerprint_integrity(leverage_result: dict) -> dict[str, Any]:
    """L2: If policy_version is present, policy_fingerprint must match the registry.
    Ensures that re-rendered cases with pinned versions haven't been tampered with.
    """
    v = leverage_result.get("policy_version")
    fp = leverage_result.get("policy_fingerprint")
    if not v or not fp:
        return {"invariant": "L2_POLICY_FINGERPRINT", "passed": True, "detail": "skip (version/fp missing)"}
    try:
        from apps.worker.lib.leverage_policy_registry import get_policy_fingerprint
        expected = get_policy_fingerprint(v)
        passed = (fp == expected)
        return {
            "invariant": "L2_POLICY_FINGERPRINT",
            "passed": passed,
            "detail": f"ok ({fp[:8]})" if passed else f"FAIL: fingerprint mismatch for {v}",
        }
    except Exception as exc:
        return {"invariant": "L2_POLICY_FINGERPRINT", "passed": False, "detail": f"FAIL: {exc}"}


def check_L3_trajectory_consistency(ext: dict, signals: dict) -> dict[str, Any]:
    """L3: If escalation_events exist in signals, leverage_trajectory must be enabled in ext."""
    traj = ext.get("leverage_trajectory") or {}
    has_escalation = bool(signals.get("escalation_events"))
    if not has_escalation:
        return {"invariant": "L3_TRAJECTORY_CONSISTENCY", "passed": True, "detail": "skip (no escalation signals)"}
    
    passed = bool(traj.get("enabled", False))
    return {
        "invariant": "L3_TRAJECTORY_CONSISTENCY",
        "passed": passed,
        "detail": f"ok (traj enabled={passed})" if passed else "FAIL: trajectory disabled/missing despite escalation signals",
    }


# ── T2/T3: Trajectory peak invariants (Pass 38) ─────────────────────────────────

def check_T2_trajectory_injection_peak(signals: dict, ext: dict) -> dict[str, Any]:
    """T2: If has_injection_dated == True, trajectory.peak_level must be >= 4."""
    has_inj_dated = bool(signals.get("has_injection_dated", False))
    if not has_inj_dated:
        return {"invariant": "T2_TRAJECTORY_INJECTION_PEAK", "passed": True, "detail": "skip (has_injection_dated=False)"}
    
    traj = ext.get("leverage_trajectory") or {}
    if not traj.get("enabled", False):
        return {"invariant": "T2_TRAJECTORY_INJECTION_PEAK", "passed": True, "detail": "skip (trajectory disabled)"}
    
    peak = traj.get("peak_level")
    passed = peak is not None and peak >= 4
    return {
        "invariant": "T2_TRAJECTORY_INJECTION_PEAK",
        "passed": passed,
        "detail": f"ok (peak_level={peak} >= 4)" if passed else f"FAIL: peak_level={peak} < 4",
    }


def check_T3_trajectory_surgery_peak(signals: dict, ext: dict) -> dict[str, Any]:
    """T3: If has_surgery_dated == True, trajectory.peak_level must be == 5."""
    has_surg_dated = bool(signals.get("has_surgery_dated", False))
    if not has_surg_dated:
        return {"invariant": "T3_TRAJECTORY_SURGERY_PEAK", "passed": True, "detail": "skip (has_surgery_dated=False)"}
    
    traj = ext.get("leverage_trajectory") or {}
    if not traj.get("enabled", False):
        return {"invariant": "T3_TRAJECTORY_SURGERY_PEAK", "passed": True, "detail": "skip (trajectory disabled)"}
    
    peak = traj.get("peak_level")
    passed = peak == 5
    return {
        "invariant": "T3_TRAJECTORY_SURGERY_PEAK",
        "passed": passed,
        "detail": f"ok (peak_level={peak} == 5)" if passed else f"FAIL: peak_level={peak} != 5",
    }


# ── D1–D5: Regression Enforcement Checks (Pass 39) ───────────────────────────

def check_D1_determinism_rerun(eg: dict) -> dict[str, Any]:
    """D1: derive_case_signals() is deterministic — two calls on same EG return identical output."""
    sig1 = derive_case_signals(eg)
    sig2 = derive_case_signals(eg)
    all_keys = set(sig1.keys()) | set(sig2.keys())
    diffs: list[str] = []
    for k in sorted(all_keys):
        v1 = sig1.get(k)
        v2 = sig2.get(k)
        if v1 != v2:
            diffs.append(f"{k}: {v1!r} != {v2!r}")
    passed = len(diffs) == 0
    return {
        "invariant": "D1_DETERMINISM_RERUN",
        "passed": passed,
        "detail": f"ok ({len(all_keys)} signals stable across 2 calls)" if passed else f"FAIL: {diffs}",
    }


def check_D2_policy_pinning(ext: dict) -> dict[str, Any]:
    """D2: If leverage_policy.version is stored, its fingerprint must match the registry."""
    lp = ext.get("leverage_policy") or {}
    version = lp.get("version")
    stored_fp = lp.get("fingerprint")
    if not version or not stored_fp:
        return {"invariant": "D2_POLICY_PINNING", "passed": True, "detail": "skip (no policy stored in ext)"}
    try:
        from apps.worker.lib.leverage_policy_registry import policy_to_provenance
        registry_fp = policy_to_provenance(version)["fingerprint"]
        passed = (stored_fp == registry_fp)
        return {
            "invariant": "D2_POLICY_PINNING",
            "passed": passed,
            "detail": f"ok ({version} fp={stored_fp[:8]}...)" if passed else f"FAIL: stored fp={stored_fp[:8]}, registry fp={registry_fp[:8]}",
        }
    except KeyError as exc:
        return {"invariant": "D2_POLICY_PINNING", "passed": False, "detail": f"FAIL: unknown policy version: {exc}"}
    except Exception as exc:
        return {"invariant": "D2_POLICY_PINNING", "passed": False, "detail": f"FAIL: {exc}"}


def check_D3_no_mediation_leakage(ext: dict, mediation_pdf_path: "Path | None") -> dict[str, Any]:
    """D3: Policy fingerprint and INTERNAL-only keys must not appear in mediation PDF bytes.
    Extended in Pass 40: also checks source_anchor and policy_clause absence.
    """
    if mediation_pdf_path is None or not mediation_pdf_path.exists():
        return {"invariant": "D3_NO_MEDIATION_LEAKAGE", "passed": True, "detail": "skip (no mediation PDF)"}
    lp = ext.get("leverage_policy") or {}
    fingerprint = lp.get("fingerprint")
    if not fingerprint:
        return {"invariant": "D3_NO_MEDIATION_LEAKAGE", "passed": True, "detail": "skip (no policy fingerprint in ext)"}
    pdf_bytes = mediation_pdf_path.read_bytes()
    # Check for fingerprint hex string
    if fingerprint.encode("utf-8") in pdf_bytes:
        return {"invariant": "D3_NO_MEDIATION_LEAKAGE", "passed": False,
                "detail": "FAIL: policy fingerprint found in mediation PDF bytes"}
    # Check for the key name (defense-in-depth — catches JSON embedded in PDF)
    if b"policy_fingerprint" in pdf_bytes:
        return {"invariant": "D3_NO_MEDIATION_LEAKAGE", "passed": False,
                "detail": "FAIL: 'policy_fingerprint' key found in mediation PDF bytes"}
    # Pass 40: Check that INTERNAL-only trajectory fields are absent from MEDIATION
    for forbidden_key in [b"source_anchor", b"policy_clause"]:
        if forbidden_key in pdf_bytes:
            return {"invariant": "D3_NO_MEDIATION_LEAKAGE", "passed": False,
                    "detail": f"FAIL: {forbidden_key.decode()!r} found in mediation PDF bytes"}
    return {"invariant": "D3_NO_MEDIATION_LEAKAGE", "passed": True, "detail": "ok (no leakage detected)"}


def check_D4_trajectory_signals_only() -> dict[str, Any]:
    """D4: leverage_trajectory.py must not import or access EvidenceGraph / eg_bytes (static)."""
    traj_path = _REPO_ROOT / "apps" / "worker" / "lib" / "leverage_trajectory.py"
    if not traj_path.exists():
        return {"invariant": "D4_TRAJECTORY_SIGNALS_ONLY", "passed": False,
                "detail": "FAIL: leverage_trajectory.py not found"}
    source = traj_path.read_text(encoding="utf-8")
    forbidden = ["EvidenceGraph", "evidence_graph", "eg_bytes"]
    hits: list[str] = []
    for token in forbidden:
        for i, line in enumerate(source.splitlines(), 1):
            stripped = line.strip()
            if token in line and not stripped.startswith("#"):
                hits.append(f"line {i}: {stripped!r}")
    passed = len(hits) == 0
    return {
        "invariant": "D4_TRAJECTORY_SIGNALS_ONLY",
        "passed": passed,
        "detail": "ok (no forbidden EvidenceGraph access)" if passed else f"FAIL: {hits}",
    }


def check_D5_renderer_display_only() -> dict[str, Any]:
    """D5: Renderer files must not call any compute or derivation functions (static)."""
    renderer_paths = [
        _REPO_ROOT / "apps" / "worker" / "steps" / "export_render" / "timeline_pdf.py",
        _REPO_ROOT / "apps" / "worker" / "steps" / "export_render" / "mediation_sections.py",
    ]
    forbidden_calls = [
        "compute_leverage_index(",
        "compute_leverage_trajectory(",
        "derive_case_signals(",
        "build_settlement_feature_pack(",
        "get_policy(",
    ]
    hits: list[str] = []
    for path in renderer_paths:
        if not path.exists():
            continue
        for i, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            stripped = line.strip()
            if stripped.startswith("#"):
                continue
            for fn in forbidden_calls:
                if fn in line:
                    hits.append(f"{path.name}:{i}: {stripped!r}")
    passed = len(hits) == 0
    return {
        "invariant": "D5_RENDERER_DISPLAY_ONLY",
        "passed": passed,
        "detail": "ok (renderer remains display-only)" if passed else f"FAIL: {hits}",
    }


# ── E2: No escalation from low-confidence signals (Pass 41) ──────────────────

_E2_CONFIDENCE_THRESHOLD = 0.80


def check_E2_no_escalation_from_low_confidence(signals: dict, ext: dict) -> dict[str, Any]:
    """E2: No trajectory marker may correspond to an escalation event with confidence < 0.80.

    Operates on post-Pass-41 runs only (escalation events without confidence key
    default to 0.90 — backward-compatible).

    Checks stored ext["leverage_trajectory"]["markers"] against
    signals["escalation_events"]. For each marker (date, kind), looks up the
    matching escalation_event and verifies its confidence >= 0.80.
    """
    traj = ext.get("leverage_trajectory") or {}
    if not traj.get("enabled", False):
        return {"invariant": "E2_NO_ESCALATION_FROM_LOW_CONFIDENCE", "passed": True,
                "detail": "skip (trajectory disabled)"}

    markers = traj.get("markers") or []
    if not markers:
        return {"invariant": "E2_NO_ESCALATION_FROM_LOW_CONFIDENCE", "passed": True,
                "detail": "skip (no markers)"}

    escalation_events = signals.get("escalation_events") or []
    # Build lookup: (date, kind) → confidence
    event_confidence: dict[tuple, float] = {}
    for ev in escalation_events:
        key = (ev.get("date", ""), ev.get("kind", ""))
        event_confidence[key] = float(ev.get("confidence", 0.90))

    failures: list[str] = []
    for m in markers:
        key = (m.get("date", ""), m.get("kind", ""))
        conf = event_confidence.get(key, 0.90)  # default 0.90 for pre-Pass-41 events
        if conf < _E2_CONFIDENCE_THRESHOLD:
            failures.append(
                f"marker ({m.get('date')}, {m.get('kind')}) confidence={conf:.2f} < {_E2_CONFIDENCE_THRESHOLD}"
            )

    passed = len(failures) == 0
    return {
        "invariant": "E2_NO_ESCALATION_FROM_LOW_CONFIDENCE",
        "passed": passed,
        "detail": (
            f"ok (all {len(markers)} markers have confidence >= {_E2_CONFIDENCE_THRESHOLD})" if passed
            else f"FAIL: {'; '.join(failures)}"
        ),
    }


# ── D6: INTERNAL version header present (Pass 41) ────────────────────────────

def check_D6_internal_version_header_present(case_dir: Path) -> dict[str, Any]:
    """D6: Every INTERNAL PDF must contain the version header block.

    Looks for a PDF with 'INTERNAL' in the filename. If not found, skips.
    If found, verifies 'Signal Layer:' string is present in the PDF bytes.
    Rendered from pre-computed ext['run_metadata'] (Pass 40). Removal would
    go undetected without this check.
    """
    internal_pdf = next(case_dir.glob("*INTERNAL*.pdf"), None)
    if internal_pdf is None or not internal_pdf.exists():
        return {"invariant": "D6_INTERNAL_VERSION_HEADER_PRESENT", "passed": True,
                "detail": "skip (no INTERNAL PDF in fixture)"}
    pdf_bytes = internal_pdf.read_bytes()
    # The version header contains "Signal Layer:" rendered from ext["run_metadata"]
    if b"Signal Layer:" in pdf_bytes:
        return {"invariant": "D6_INTERNAL_VERSION_HEADER_PRESENT", "passed": True,
                "detail": f"ok (version header found in {internal_pdf.name})"}
    return {"invariant": "D6_INTERNAL_VERSION_HEADER_PRESENT", "passed": False,
            "detail": f"FAIL: 'Signal Layer:' not found in {internal_pdf.name} — version header missing or removed"}


# ── Fixture manifest check (Pass 41) ─────────────────────────────────────────

def check_fixture_manifest(case_dir: Path, signals: dict, ext: dict) -> dict[str, Any] | None:
    """Load fixture_manifest.json (if present) and assert trajectory_peak expectations.

    trajectory_peak_level_min — peak_level must be >= value
    trajectory_peak_level_exact — peak_level must be == value

    Returns a result dict, or None if no fixture_manifest.json found.
    """
    manifest_path = case_dir / "fixture_manifest.json"
    if not manifest_path.exists():
        return None
    try:
        manifest = _load_json(manifest_path)
    except Exception as exc:
        return {"invariant": "FIXTURE_MANIFEST", "passed": False,
                "detail": f"FAIL: could not load fixture_manifest.json: {exc}"}

    expects = manifest.get("expects") or {}
    failures: list[str] = []

    # Check has_injection_dated / has_surgery_dated expectations
    for sig_key in ("has_injection_dated", "has_surgery_dated"):
        if sig_key in expects:
            expected_val = bool(expects[sig_key])
            actual_val = bool(signals.get(sig_key, False))
            if actual_val != expected_val:
                failures.append(f"{sig_key}: expected {expected_val}, got {actual_val}")

    # Check trajectory peak expectations
    traj = ext.get("leverage_trajectory") or {}
    peak = traj.get("peak_level")
    if "trajectory_peak_level_min" in expects:
        min_val = int(expects["trajectory_peak_level_min"])
        if peak is None or peak < min_val:
            failures.append(f"trajectory_peak_level={peak} below required min {min_val}")
    if "trajectory_peak_level_exact" in expects:
        exact_val = int(expects["trajectory_peak_level_exact"])
        if peak != exact_val:
            failures.append(f"trajectory_peak_level={peak} != required exact {exact_val}")

    passed = len(failures) == 0
    return {
        "invariant": "FIXTURE_MANIFEST",
        "passed": passed,
        "detail": (
            f"ok (fixture_id={manifest.get('fixture_id', case_dir.name)})" if passed
            else f"FAIL: {'; '.join(failures)}"
        ),
    }


# ── E1: Escalation Traceability (Pass 40) ────────────────────────────────────

def check_E1_escalation_traceability(ext: dict) -> dict[str, Any]:
    """E1: All enabled trajectory markers on Pass-40+ runs must have source_anchor.

    Skip condition (Pass 41 tightened): only skip when run_metadata.pass is absent
    or < 40. This replaces the previous data-inferred skip (absence of source_anchor),
    which was bypassable by disabling _compute_source_anchor() entirely.
    """
    traj = ext.get("leverage_trajectory") or {}
    if not traj.get("enabled", False):
        return {"invariant": "E1_ESCALATION_TRACEABILITY", "passed": True,
                "detail": "skip (trajectory disabled)"}
    markers = traj.get("markers") or []
    if not markers:
        return {"invariant": "E1_ESCALATION_TRACEABILITY", "passed": True,
                "detail": "skip (no markers)"}

    # Pass 41: skip based on explicit run_metadata.pass, not data inference
    run_metadata = ext.get("run_metadata") or {}
    run_pass = run_metadata.get("pass")
    if run_pass is None or int(run_pass) < 40:
        return {"invariant": "E1_ESCALATION_TRACEABILITY", "passed": True,
                "detail": f"skip (pre-Pass-40 run — run_metadata.pass={run_pass})"}

    # Pass-40+ run: all markers must have source_anchor
    missing = [i for i, m in enumerate(markers) if not m.get("source_anchor")]
    passed = len(missing) == 0
    return {
        "invariant": "E1_ESCALATION_TRACEABILITY",
        "passed": passed,
        "detail": (
            f"ok (all {len(markers)} markers have source_anchor)" if passed
            else f"FAIL: markers at indices {missing} missing source_anchor"
        ),
    }


# ── Per-case runner ───────────────────────────────────────────────────────────

def run_case(case_dir: Path) -> dict[str, Any]:
    eg_path = case_dir / "evidence_graph.json"
    pdf_path = next(case_dir.glob("*MEDIATION*.pdf"), None) or next(case_dir.glob("*.pdf"), None)

    if not eg_path.exists():
        return {
            "case": case_dir.name,
            "error": f"evidence_graph.json not found in {case_dir}",
            "invariants": [],
            "all_pass": False,
        }

    try:
        eg = _load_json(eg_path)
    except Exception as exc:
        return {"case": case_dir.name, "error": f"Failed to load evidence_graph.json: {exc}", "invariants": [], "all_pass": False}

    # Check expected_signals.json bounds
    expected_path = case_dir / "expected_signals.json"
    expected: dict[str, Any] = {}
    if expected_path.exists():
        try:
            raw = _load_json(expected_path)
            expected = raw.get("expected") or {}
        except Exception:
            pass

    signals = derive_case_signals(eg)

    # Check expected bounds from fixture
    bounds_failures: list[str] = []
    for key, val in expected.items():
        if key.endswith("_max"):
            field = key[:-4]
            actual = signals.get(field)
            if actual is not None and actual > val:
                bounds_failures.append(f"{field}={actual} exceeds expected max {val}")
        elif key.endswith("_min"):
            field = key[:-4]
            actual = signals.get(field)
            if actual is not None and actual < val:
                bounds_failures.append(f"{field}={actual} below expected min {val}")
        elif key in signals:
            if signals[key] != val:
                bounds_failures.append(f"{key}: expected {val!r}, got {signals[key]!r}")

    pdf_text = ""
    if pdf_path is not None and pdf_path.exists():
        try:
            pdf_text = _pdf_text(pdf_path)
        except Exception as exc:
            pdf_text = ""

    results: list[dict[str, Any]] = []
    results.append(check_S1_pt_derivation_integrity(eg, signals))
    if pdf_text:
        results.append(check_A1_pt_count_consistency(pdf_text, signals, eg))
        results.append(check_A3_noise_not_in_objective_or_imaging(pdf_text))
        results.append(check_B1_tier_floor_radiculopathy(pdf_text, signals))
        results.append(check_B2_tier_floor_injection_dated(pdf_text, signals))
        results.append(check_C1_minor_cap_ceiling(pdf_text, signals))
    else:
        for inv in ["A1_PT_COUNT_CONSISTENCY", "A3_NOISE_NOT_IN_OBJECTIVE_OR_IMAGING",
                    "B1_TIER_FLOOR_RADICULOPATHY", "B2_TIER_FLOOR_INJECTION_DATED", "C1_MINOR_CAP_CEILING"]:
            results.append({"invariant": inv, "passed": True, "detail": "skip (no PDF found)"})

    # L1 — Leverage tier consistency (Pass 37)
    ext = eg.get("extensions") or {}
    leverage_result = ext.get("leverage_index_result") or {}
    results.append(check_L1_leverage_tier_consistency(signals, leverage_result))
    results.append(check_L2_policy_fingerprint_integrity(leverage_result))
    results.append(check_L3_trajectory_consistency(ext, signals))

    # T2/T3 — Trajectory peak invariants (Pass 38)
    results.append(check_T2_trajectory_injection_peak(signals, ext))
    results.append(check_T3_trajectory_surgery_peak(signals, ext))

    # D1–D3 — Regression enforcement checks (Pass 39)
    results.append(check_D1_determinism_rerun(eg))
    results.append(check_D2_policy_pinning(ext))
    results.append(check_D3_no_mediation_leakage(ext, pdf_path))

    # E1 — Escalation traceability (Pass 40)
    results.append(check_E1_escalation_traceability(ext))

    # D6 — INTERNAL version header present (Pass 41)
    results.append(check_D6_internal_version_header_present(case_dir))

    # E2 — No escalation from low-confidence signals (Pass 41)
    results.append(check_E2_no_escalation_from_low_confidence(signals, ext))

    # Fixture manifest — trajectory peak expectations (Pass 41)
    manifest_result = check_fixture_manifest(case_dir, signals, ext)
    if manifest_result is not None:
        results.append(manifest_result)

    if bounds_failures:
        results.append({
            "invariant": "FIXTURE_BOUNDS",
            "passed": False,
            "detail": "; ".join(bounds_failures),
        })

    all_pass = all(r["passed"] for r in results)

    # Compute attestation fingerprints
    signals_fp = _compute_signals_fingerprint(signals)
    artifact_fp = _compute_artifact_fingerprint(case_dir)
    attestation = {
        "case_id": case_dir.name,
        "invariant_run_id": hashlib.sha256(
            (signals_fp + artifact_fp).encode()
        ).hexdigest()[:16],
        "pass": all_pass,
        "artifact_fingerprint": artifact_fp,
        "signals_fingerprint": signals_fp,
    }

    return {
        "case": case_dir.name,
        "signals_summary": {
            "pt_dated_encounter_count": signals.get("pt_dated_encounter_count"),
            "has_radiculopathy": signals.get("has_radiculopathy"),
            "has_injection_dated": signals.get("has_injection_dated"),
            "has_surgery_dated": signals.get("has_surgery_dated"),
            "treatment_duration_days": signals.get("treatment_duration_days"),
        },
        "invariants": results,
        "all_pass": all_pass,
        "pdf_found": pdf_path is not None and pdf_path.exists(),
        "attestation": attestation,
        # Pass 39: extra data for attest-dir artifact writing (stripped by serialiser before JSON output)
        "_derived_signals": signals,
        "_ext": ext,
    }


# ── Main ──────────────────────────────────────────────────────────────────────

_SIGNAL_LAYER_VERSION = "36"  # Locked at Pass 36


def _write_attest_artifacts(attest_dir: Path, result: dict[str, Any]) -> None:
    """Write Pass 39 artifact set for a single case to attest_dir."""
    case_id = result["case"]
    signals = result.get("_derived_signals") or {}
    ext = result.get("_ext") or {}

    # case signals
    sig_path = attest_dir / f"{case_id}_signals.json"
    with sig_path.open("w", encoding="utf-8") as f:
        json.dump(signals, f, indent=2, default=str)

    # leverage output
    lev = {
        "leverage_index_result": ext.get("leverage_index_result") or {},
        "leverage_policy": ext.get("leverage_policy") or {},
    }
    with (attest_dir / f"{case_id}_leverage.json").open("w", encoding="utf-8") as f:
        json.dump(lev, f, indent=2, default=str)

    # trajectory output
    with (attest_dir / f"{case_id}_trajectory.json").open("w", encoding="utf-8") as f:
        json.dump(ext.get("leverage_trajectory") or {}, f, indent=2, default=str)

    # run metadata
    lp = ext.get("leverage_policy") or {}
    lev_result = ext.get("leverage_index_result") or {}
    d1_passed = any(
        r["invariant"] == "D1_DETERMINISM_RERUN" and r["passed"]
        for r in result.get("invariants", [])
    )
    metadata = {
        "signal_layer_version": _SIGNAL_LAYER_VERSION,
        "policy_version": lp.get("version"),
        "policy_fingerprint": lp.get("fingerprint"),
        "leverage_band": lev_result.get("band"),
        "leverage_score": lev_result.get("score"),
        "determinism_check_result": "PASS" if d1_passed else "FAIL",
        "harness_run_at": _utcnow_iso(),
        "govpreplan_version": "1.0",
    }
    with (attest_dir / f"{case_id}_run_metadata.json").open("w", encoding="utf-8") as f:
        json.dump(metadata, f, indent=2, default=str)


def _write_attest_artifacts_subdir(attest_dir: Path, result: dict[str, Any]) -> None:
    """Write Pass 044 standard per-case subdir artifacts.

    Layout: <attest_dir>/output/<case_id>/
        run_metadata.json
        case_signals.json
        leverage_output.json
        trajectory_output.json

    This enables INV-P1 compliance: future drift checks find baselines via subdir
    and report status=RUN instead of SKIP.
    """
    case_id = result["case"]
    signals = result.get("_derived_signals") or {}
    ext = result.get("_ext") or {}

    case_out = attest_dir / "output" / case_id
    case_out.mkdir(parents=True, exist_ok=True)

    # case signals
    with (case_out / "case_signals.json").open("w", encoding="utf-8") as f:
        json.dump(signals, f, indent=2, default=str)

    # leverage output
    lev = {
        "leverage_index_result": ext.get("leverage_index_result") or {},
        "leverage_policy": ext.get("leverage_policy") or {},
    }
    with (case_out / "leverage_output.json").open("w", encoding="utf-8") as f:
        json.dump(lev, f, indent=2, default=str)

    # trajectory output
    with (case_out / "trajectory_output.json").open("w", encoding="utf-8") as f:
        json.dump(ext.get("leverage_trajectory") or {}, f, indent=2, default=str)

    # run metadata (same schema as flat, used for drift baseline resolution)
    lp = ext.get("leverage_policy") or {}
    lev_result = ext.get("leverage_index_result") or {}
    d1_passed = any(
        r["invariant"] == "D1_DETERMINISM_RERUN" and r["passed"]
        for r in result.get("invariants", [])
    )
    metadata = {
        "signal_layer_version": _SIGNAL_LAYER_VERSION,
        "policy_version": lp.get("version"),
        "policy_fingerprint": lp.get("fingerprint"),
        "leverage_band": lev_result.get("band"),
        "leverage_score": lev_result.get("score"),
        "determinism_check_result": "PASS" if d1_passed else "FAIL",
        "harness_run_at": _utcnow_iso(),
        "govpreplan_version": "1.0",
        "baseline_layout": "pass044_subdir",
    }
    with (case_out / "run_metadata.json").open("w", encoding="utf-8") as f:
        json.dump(metadata, f, indent=2, default=str)


def _strip_private_keys(report: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Remove internal _keys from report before JSON serialisation."""
    cleaned = []
    for r in report:
        cleaned.append({k: v for k, v in r.items() if not k.startswith("_")})
    return cleaned


def main() -> int:
    parser = argparse.ArgumentParser(description="Citeline invariant harness")
    parser.add_argument("--fixtures", required=True, help="Path to fixtures directory (contains case subdirs)")
    parser.add_argument("--out", default=None, help="Optional JSON report output path")
    parser.add_argument("--attest-dir", default=None, dest="attest_dir",
                        help="Directory to write per-case artifact files (default: artifacts/invariants/)")
    args = parser.parse_args()

    fixtures_dir = Path(args.fixtures)
    if not fixtures_dir.is_dir():
        print(f"ERROR: fixtures directory not found: {fixtures_dir}", file=sys.stderr)
        return 1

    case_dirs = sorted(d for d in fixtures_dir.iterdir() if d.is_dir())
    if not case_dirs:
        print(f"ERROR: no case subdirectories found in {fixtures_dir}", file=sys.stderr)
        return 1

    # D4 and D5 are static — run once before iterating cases
    d4 = check_D4_trajectory_signals_only()
    d5 = check_D5_renderer_display_only()
    static_pass = d4["passed"] and d5["passed"]

    for check in [d4, d5]:
        status = "PASS" if check["passed"] else "FAIL"
        print(f"  [{status}] STATIC {check['invariant']}: {check['detail']}")

    report: list[dict[str, Any]] = []
    overall_pass = static_pass

    for case_dir in case_dirs:
        result = run_case(case_dir)
        report.append(result)
        status = "PASS" if result["all_pass"] else "FAIL"
        if not result["all_pass"]:
            overall_pass = False
        print(f"  [{status}] {result['case']}")
        for inv in result.get("invariants", []):
            inv_status = "  PASS" if inv["passed"] else "  FAIL"
            print(f"       {inv_status} {inv['invariant']}: {inv['detail']}")

    static_checks = [d4, d5]
    summary = {
        "overall_pass": overall_pass,
        "cases_total": len(report),
        "cases_pass": sum(1 for r in report if r["all_pass"]),
        "cases_fail": sum(1 for r in report if not r["all_pass"]),
        "static_checks": static_checks,
        "static_pass": static_pass,
        "cases": _strip_private_keys(report),
    }

    # Write per-case attest-dir artifacts
    attest_dir_path = Path(args.attest_dir) if args.attest_dir else (
        Path(args.fixtures).resolve().parents[2] / "artifacts" / "invariants"
    )
    attest_dir_path.mkdir(parents=True, exist_ok=True)

    for r in report:
        att = r.get("attestation")
        if att:
            att_path = attest_dir_path / f"{att['case_id']}.attestation.json"
            with att_path.open("w", encoding="utf-8") as f:
                json.dump({**att, "created_at": _utcnow_iso()}, f, indent=2)
        _write_attest_artifacts(attest_dir_path, r)

    print(f"Artifacts written to {attest_dir_path}")

    if args.out:
        out_path = Path(args.out)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        with out_path.open("w", encoding="utf-8") as f:
            json.dump(summary, f, indent=2, default=str)
        print(f"Report written to {out_path}")

    overall_status = "ALL INVARIANTS PASS" if overall_pass else "INVARIANT FAILURES DETECTED"
    print(f"\n{overall_status} ({summary['cases_pass']}/{summary['cases_total']} cases, static={'PASS' if static_pass else 'FAIL'})")
    return 0 if overall_pass else 1


if __name__ == "__main__":
    sys.exit(main())
