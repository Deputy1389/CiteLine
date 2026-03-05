from __future__ import annotations

import re
from datetime import date
from typing import Any

from packages.shared.models import Citation, Event, Provider

_ICD_RE = re.compile(r"\b([A-TV-Z][0-9][0-9A-Z](?:\.[0-9A-Z]{1,4})?)\b", re.I)

_BUCKET_MATRIX: dict[str, dict[str, str]] = {
    "er": {
        "complaints": "required",
        "objective_findings": "required",
        "diagnostics": "conditional",
        "diagnoses": "required",
        "treatments": "required",
        "prescriptions_or_referrals": "conditional",
        "functional_limitations": "conditional",
        "causation_statements": "conditional",
    },
    "primary_care": {
        "complaints": "required",
        "objective_findings": "conditional",
        "diagnostics": "conditional",
        "diagnoses": "required",
        "treatments": "required",
        "prescriptions_or_referrals": "conditional",
        "functional_limitations": "conditional",
        "causation_statements": "conditional",
    },
    "specialist": {
        "complaints": "required",
        "objective_findings": "required",
        "diagnostics": "conditional",
        "diagnoses": "required",
        "treatments": "required",
        "prescriptions_or_referrals": "conditional",
        "functional_limitations": "conditional",
        "causation_statements": "conditional",
    },
    "imaging": {
        "complaints": "optional",
        "objective_findings": "optional",
        "diagnostics": "required",
        "diagnoses": "conditional",
        "treatments": "optional",
        "prescriptions_or_referrals": "optional",
        "functional_limitations": "optional",
        "causation_statements": "optional",
    },
    "therapy": {
        "complaints": "required",
        "objective_findings": "conditional",
        "diagnostics": "optional",
        "diagnoses": "optional",
        "treatments": "required",
        "prescriptions_or_referrals": "optional",
        "functional_limitations": "required",
        "causation_statements": "optional",
    },
    "surgery": {
        "complaints": "required",
        "objective_findings": "required",
        "diagnostics": "conditional",
        "diagnoses": "required",
        "treatments": "required",
        "prescriptions_or_referrals": "conditional",
        "functional_limitations": "conditional",
        "causation_statements": "conditional",
    },
    "follow_up": {
        "complaints": "required",
        "objective_findings": "conditional",
        "diagnostics": "optional",
        "diagnoses": "conditional",
        "treatments": "required",
        "prescriptions_or_referrals": "conditional",
        "functional_limitations": "conditional",
        "causation_statements": "optional",
    },
}


def _text_of_facts(facts: list[Any]) -> list[str]:
    out: list[str] = []
    for fact in facts or []:
        text = str(getattr(fact, "text", "") or "").strip()
        if text:
            out.append(text)
    return out


def _iso_start(e: Event) -> str | None:
    d = getattr(e, "date", None)
    if not d or getattr(d, "value", None) is None:
        return None
    v = d.value
    if isinstance(v, date):
        return v.isoformat()
    start = getattr(v, "start", None)
    return start.isoformat() if isinstance(start, date) else None


def _provider_lookup(providers: list[Provider]) -> dict[str, Provider]:
    return {str(p.provider_id): p for p in providers or [] if str(getattr(p, "provider_id", "")).strip()}


def _provider_role(provider: Provider | None, event: Event) -> str:
    et = str(getattr(getattr(event, "event_type", None), "value", getattr(event, "event_type", "")) or "").lower()
    if et in {"imaging_study"}:
        return "imaging"
    if et in {"pt_visit"}:
        return "therapy"
    if et in {"procedure"}:
        return "surgery"
    if et in {"er_visit", "hospital_admission", "hospital_discharge"}:
        return "er"

    ptype = str(getattr(getattr(provider, "provider_type", None), "value", getattr(provider, "provider_type", "")) or "").lower()
    if ptype == "er":
        return "er"
    if ptype in {"imaging"}:
        return "imaging"
    if ptype in {"pt"}:
        return "therapy"
    if ptype in {"pcp"}:
        return "primary_care"
    if ptype in {"specialist"}:
        return "specialist"
    if ptype in {"physician", "hospital"}:
        return "follow_up"
    return "follow_up"


def _encounter_type(role: str, event: Event) -> str:
    et = str(getattr(getattr(event, "event_type", None), "value", getattr(event, "event_type", "")) or "").lower()
    if role == "therapy":
        return "therapy"
    if role == "imaging":
        return "imaging"
    if role == "surgery" or et == "procedure":
        return "surgery"
    if role == "er" or et in {"er_visit", "hospital_admission", "hospital_discharge"}:
        return "er"
    if role == "primary_care":
        return "primary_care"
    if role == "specialist":
        return "specialist"
    return "follow_up"


def _collect_bucket_text(event: Event) -> dict[str, list[str]]:
    complaints = [x for x in [str(getattr(event, "chief_complaint", "") or "").strip(), str(getattr(event, "reason_for_visit", "") or "").strip()] if x]
    exam = _text_of_facts(list(getattr(event, "exam_findings", []) or []))
    diagnoses = _text_of_facts(list(getattr(event, "diagnoses", []) or []))
    procedures = _text_of_facts(list(getattr(event, "procedures", []) or []))
    meds = _text_of_facts(list(getattr(event, "medications", []) or []))
    plans = _text_of_facts(list(getattr(event, "treatment_plan", []) or []))
    facts = _text_of_facts(list(getattr(event, "facts", []) or []))

    imaging_impression = _text_of_facts(list(getattr(getattr(event, "imaging", None), "impression", []) or []))

    diagnostics = []
    for t in imaging_impression + facts + procedures:
        if re.search(r"\b(mri|x-?ray|ct|ultrasound|imaging|radiograph|scan)\b", t, re.I):
            diagnostics.append(t)

    objective = list(exam)
    for t in facts:
        if re.search(r"\b(rom|range of motion|strength|weakness|reflex|spasm|tenderness|deficit|4/5|5/5)\b", t, re.I):
            objective.append(t)

    treatments = list(procedures) + list(plans)
    for t in meds:
        if re.search(r"\b(start|continue|prescrib|medication|mg|injection|therapy)\b", t, re.I):
            treatments.append(t)

    referrals = []
    for t in plans + facts + meds:
        if re.search(r"\b(refer|referral|follow-?up|prescrib|rx|medication)\b", t, re.I):
            referrals.append(t)

    functional = []
    for t in facts + exam + plans:
        if re.search(r"\b(unable|difficulty|limited|restriction|work status|cannot|impair)\b", t, re.I):
            functional.append(t)

    causation = []
    for t in facts + diagnoses + complaints:
        if re.search(r"\b(result of|secondary to|after (the )?(accident|collision|incident)|due to)\b", t, re.I):
            causation.append(t)

    all_diag_text = diagnoses + [t for t in facts if re.search(r"\b(diagnosis|assessment|impression|strain|sprain|radiculopathy|tear|fracture|bursitis)\b", t, re.I)]

    return {
        "complaints": _dedupe_strings(complaints),
        "objective_findings": _dedupe_strings(objective),
        "diagnostics": _dedupe_strings(diagnostics),
        "diagnoses": _dedupe_strings(all_diag_text),
        "treatments": _dedupe_strings(treatments),
        "prescriptions_or_referrals": _dedupe_strings(referrals),
        "functional_limitations": _dedupe_strings(functional),
        "causation_statements": _dedupe_strings(causation),
    }


def _dedupe_strings(items: list[str]) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    for raw in items:
        val = re.sub(r"\s+", " ", str(raw or "")).strip()
        key = val.lower()
        if not val or key in seen:
            continue
        seen.add(key)
        out.append(val)
    return out


def _conditional_required(bucket: str, blobs: str, encounter_type: str) -> bool:
    if bucket == "diagnostics":
        return bool(re.search(r"\b(mri|x-?ray|ct|ultrasound|imaging|radiograph|scan)\b", blobs, re.I)) or encounter_type == "imaging"
    if bucket == "prescriptions_or_referrals":
        return bool(re.search(r"\b(refer|referral|prescrib|rx|medication|follow-?up)\b", blobs, re.I))
    if bucket == "functional_limitations":
        return bool(re.search(r"\b(unable|difficulty|restriction|limited|cannot|impair|work status)\b", blobs, re.I))
    if bucket == "causation_statements":
        return bool(re.search(r"\b(accident|collision|incident|mva|mvc|due to|result of|secondary to)\b", blobs, re.I))
    if bucket == "objective_findings":
        return bool(re.search(r"\b(rom|range of motion|strength|weakness|reflex|spasm|deficit|exam)\b", blobs, re.I))
    if bucket == "diagnoses":
        return bool(re.search(r"\b(diagnosis|assessment|impression|strain|sprain|radiculopathy|tear|fracture|bursitis)\b", blobs, re.I))
    return False


def _bucket_missing(encounter_type: str, bucket_values: dict[str, list[str]], event_blob: str) -> list[str]:
    rules = _BUCKET_MATRIX.get(encounter_type, _BUCKET_MATRIX["follow_up"])
    missing: list[str] = []
    for bucket, mode in rules.items():
        vals = list(bucket_values.get(bucket) or [])
        if mode == "required" and not vals:
            missing.append(bucket)
            continue
        if mode == "conditional" and _conditional_required(bucket, event_blob, encounter_type) and not vals:
            missing.append(bucket)
    return missing


def _extract_icd_codes(event: Event, texts: list[str]) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    for c in list((getattr(event, "coding", {}) or {}).get("icd10", []) or []):
        code = str(c or "").strip().upper()
        if code and code not in seen:
            seen.add(code)
            out.append(code)
    for t in texts:
        for m in _ICD_RE.findall(t or ""):
            code = str(m or "").strip().upper()
            if code and code not in seen:
                seen.add(code)
                out.append(code)
    return out


def _cluster_name(diagnosis_label: str) -> str:
    low = diagnosis_label.lower()
    if re.search(r"\b(shoulder|ac joint|labral|rotator)\b", low):
        return "shoulder_injury"
    if re.search(r"\b(knee|meniscus|acl|patella)\b", low):
        return "knee_injury"
    if re.search(r"\b(cervical|lumbar|thoracic|disc|radicul|spine|neck|back)\b", low):
        return "spine_injury"
    if re.search(r"\b(concussion|tbi|head injury|post-concussive)\b", low):
        return "neuro_injury"
    return "general_injury"


def _classification(diagnosis_label: str) -> str:
    low = diagnosis_label.lower()
    if re.search(r"\b(prior|history of|preexisting|degenerative|chronic)\b", low):
        return "preexisting"
    if re.search(r"\b(strain|sprain|pain|contusion)\b", low):
        return "secondary"
    return "primary"


def build_competitive_registries(
    *,
    events: list[Event],
    providers: list[Provider],
    citations: list[Citation] | None = None,
    mechanism: str | None = None,
) -> dict[str, Any]:
    provider_by_id = _provider_lookup(providers)

    visit_rows: list[dict[str, Any]] = []
    role_rows: list[dict[str, Any]] = []
    diagnosis_rows: list[dict[str, Any]] = []
    diagnosis_index: dict[str, dict[str, Any]] = {}
    role_seen: set[tuple[str, str]] = set()

    for e in sorted(events or [], key=lambda x: (_iso_start(x) or "9999-99-99", str(getattr(x, "event_id", "")))):
        event_id = str(getattr(e, "event_id", "") or "").strip()
        if not event_id:
            continue
        provider_id = str(getattr(e, "provider_id", "") or "").strip()
        provider = provider_by_id.get(provider_id) if provider_id else None
        role = _provider_role(provider, e)
        encounter_type = _encounter_type(role, e)
        start = _iso_start(e)
        cids = [str(c).strip() for c in (getattr(e, "citation_ids", []) or []) if str(c).strip()]

        role_key = (provider_id, role)
        if provider_id and role_key not in role_seen:
            role_seen.add(role_key)
            role_rows.append(
                {
                    "provider_id": provider_id,
                    "provider_name": str(getattr(provider, "normalized_name", "") or "Unknown").strip() or "Unknown",
                    "provider_role": role,
                }
            )

        buckets = _collect_bucket_text(e)
        blob = " ".join(
            [
                *buckets.get("complaints", []),
                *buckets.get("objective_findings", []),
                *buckets.get("diagnostics", []),
                *buckets.get("diagnoses", []),
                *buckets.get("treatments", []),
                *buckets.get("prescriptions_or_referrals", []),
                *buckets.get("functional_limitations", []),
                *buckets.get("causation_statements", []),
            ]
        )
        missing_required = _bucket_missing(encounter_type, buckets, blob)

        visit_rows.append(
            {
                "event_id": event_id,
                "date": start,
                "provider_id": provider_id or None,
                "provider_name": str(getattr(provider, "normalized_name", "") or "Unknown").strip() or "Unknown",
                "provider_role": role,
                "encounter_type": encounter_type,
                "citation_ids": cids,
                "buckets": buckets,
                "missing_required_buckets": missing_required,
                "bucket_completeness_pass": len(missing_required) == 0,
            }
        )

        diagnosis_texts = list(buckets.get("diagnoses") or [])
        if not diagnosis_texts:
            continue
        icd_codes = _extract_icd_codes(e, diagnosis_texts)
        for label in diagnosis_texts:
            key = re.sub(r"\s+", " ", label.lower()).strip()
            if not key:
                continue
            row = diagnosis_index.get(key)
            if row is None:
                row = {
                    "diagnosis_label": label,
                    "icd_codes": list(icd_codes),
                    "first_seen_date": start,
                    "provider": str(getattr(provider, "normalized_name", "") or "Unknown").strip() or "Unknown",
                    "provider_id": provider_id or None,
                    "citation_ids": list(cids),
                    "cluster_name": _cluster_name(label),
                    "classification": _classification(label),
                    "event_ids": [event_id],
                }
                diagnosis_index[key] = row
            else:
                if start and (not row.get("first_seen_date") or str(start) < str(row.get("first_seen_date"))):
                    row["first_seen_date"] = start
                    row["provider"] = str(getattr(provider, "normalized_name", "") or "Unknown").strip() or "Unknown"
                    row["provider_id"] = provider_id or None
                row["icd_codes"] = _dedupe_strings(list(row.get("icd_codes") or []) + list(icd_codes))
                row["citation_ids"] = _dedupe_strings(list(row.get("citation_ids") or []) + cids)
                row["event_ids"] = _dedupe_strings(list(row.get("event_ids") or []) + [event_id])

    diagnosis_rows = sorted(diagnosis_index.values(), key=lambda x: (str(x.get("first_seen_date") or "9999-99-99"), str(x.get("diagnosis_label") or "")))

    cluster_map: dict[str, dict[str, Any]] = {}
    for row in diagnosis_rows:
        cname = str(row.get("cluster_name") or "general_injury")
        c = cluster_map.get(cname)
        if c is None:
            c = {
                "cluster_name": cname,
                "classification": row.get("classification") or "primary",
                "diagnosis_labels": [],
                "diagnosis_refs": [],
                "event_ids": [],
            }
            cluster_map[cname] = c
        c["diagnosis_labels"] = _dedupe_strings(list(c.get("diagnosis_labels") or []) + [str(row.get("diagnosis_label") or "")])
        c["diagnosis_refs"] = _dedupe_strings(list(c.get("diagnosis_refs") or []) + list(row.get("citation_ids") or []))
        c["event_ids"] = _dedupe_strings(list(c.get("event_ids") or []) + list(row.get("event_ids") or []))
        if c.get("classification") != "preexisting" and row.get("classification") == "preexisting":
            c["classification"] = "preexisting"

    clusters = sorted(cluster_map.values(), key=lambda x: str(x.get("cluster_name") or ""))

    visit_by_id = {str(r.get("event_id")): r for r in visit_rows if str(r.get("event_id") or "")}
    severity_rows: list[dict[str, Any]] = []
    for c in clusters:
        ev_ids = [str(eid) for eid in (c.get("event_ids") or []) if str(eid)]
        c_visits = [visit_by_id[eid] for eid in ev_ids if eid in visit_by_id]
        all_text = " ".join(
            [
                str(t)
                for v in c_visits
                for bucket in list((v.get("buckets") or {}).values())
                for t in (bucket or [])
            ]
        )
        surgery_present = bool(re.search(r"\b(surgery|operative|repair|arthroscop|fusion)\b", all_text, re.I))
        injection_present = bool(re.search(r"\b(injection|epidural|esi|trigger point)\b", all_text, re.I))
        mri_pathology_present = bool(re.search(r"\b(mri)\b", all_text, re.I) and re.search(r"\b(tear|herniat|protrusion|stenosis|fracture|compression|displacement)\b", all_text, re.I))
        pt_visit_count = sum(1 for v in c_visits if str(v.get("encounter_type") or "") == "therapy")
        specialist_involvement = any(str(v.get("provider_role") or "") in {"specialist", "surgery"} for v in c_visits)

        dates = [str(v.get("date") or "") for v in c_visits if str(v.get("date") or "")]
        treatment_duration_days = None
        if len(dates) >= 2:
            try:
                start_d = date.fromisoformat(min(dates))
                end_d = date.fromisoformat(max(dates))
                treatment_duration_days = max(0, (end_d - start_d).days)
            except Exception:
                treatment_duration_days = None

        treatment_intensity_index = (25 if surgery_present else 0) + (15 if injection_present else 0) + min(20, pt_visit_count * 2) + (10 if specialist_involvement else 0)
        escalation_level = 0
        if specialist_involvement:
            escalation_level += 1
        if injection_present:
            escalation_level += 1
        if surgery_present:
            escalation_level += 2
        if mri_pathology_present:
            escalation_level += 1

        severity_score = min(
            100,
            20
            + (25 if surgery_present else 0)
            + (15 if injection_present else 0)
            + (20 if mri_pathology_present else 0)
            + (10 if specialist_involvement else 0)
            + min(10, pt_visit_count)
            + (min(10, int((treatment_duration_days or 0) / 30)) if treatment_duration_days is not None else 0),
        )

        severity_rows.append(
            {
                "cluster_name": c.get("cluster_name"),
                "classification": c.get("classification"),
                "severity_score_0_100": int(severity_score),
                "surgery_present": surgery_present,
                "injection_present": injection_present,
                "mri_pathology_present": mri_pathology_present,
                "treatment_duration_days": treatment_duration_days,
                "pt_visit_count": int(pt_visit_count),
                "specialist_involvement": bool(specialist_involvement),
                "treatment_intensity_index": int(min(100, treatment_intensity_index)),
                "escalation_level": int(min(5, escalation_level)),
                "citation_ids": list(c.get("diagnosis_refs") or []),
            }
        )

    severity_rows = sorted(severity_rows, key=lambda x: (-int(x.get("severity_score_0_100") or 0), str(x.get("cluster_name") or "")))

    stage_rank = {"er": 1, "primary_care": 2, "specialist": 3, "imaging": 4, "surgery": 5, "therapy": 6, "follow_up": 7}
    staged: dict[str, dict[str, Any]] = {}
    for v in visit_rows:
        role = str(v.get("provider_role") or "follow_up")
        cur = staged.get(role)
        if cur is None or str(v.get("date") or "9999-99-99") < str(cur.get("date") or "9999-99-99"):
            staged[role] = {
                "stage": role,
                "date": v.get("date"),
                "event_id": v.get("event_id"),
                "citation_ids": list(v.get("citation_ids") or []),
                "provider_name": v.get("provider_name"),
            }
    escalation_path = sorted(staged.values(), key=lambda x: (stage_rank.get(str(x.get("stage") or "follow_up"), 99), str(x.get("date") or "9999-99-99")))

    def _first_by(predicate: Any) -> dict[str, Any] | None:
        candidates = [v for v in visit_rows if predicate(v)]
        if not candidates:
            return None
        return sorted(candidates, key=lambda x: str(x.get("date") or "9999-99-99"))[0]

    incident_rung = {
        "rung": "incident",
        "date": str(min([x.get("date") for x in visit_rows if x.get("date")], default="") or "") or None,
        "label": mechanism or "incident not explicitly documented",
        "citation_ids": [],
        "status": "present" if mechanism else "missing",
        "missing_reason": None if mechanism else "incident_mechanism_not_explicit",
    }
    first_treat = _first_by(lambda v: True)
    first_dx = diagnosis_rows[0] if diagnosis_rows else None
    first_imaging = _first_by(lambda v: str(v.get("encounter_type") or "") == "imaging")
    first_spec = _first_by(lambda v: str(v.get("provider_role") or "") in {"specialist", "surgery"})
    first_surg = _first_by(lambda v: str(v.get("encounter_type") or "") == "surgery")

    causation_rungs = [incident_rung]
    def _rung(name: str, row: dict[str, Any] | None, label: str) -> dict[str, Any]:
        if not row:
            return {"rung": name, "date": None, "label": label, "citation_ids": [], "status": "missing", "missing_reason": f"{name}_not_found"}
        return {
            "rung": name,
            "date": row.get("date"),
            "label": label,
            "citation_ids": list(row.get("citation_ids") or []),
            "status": "present",
            "missing_reason": None,
        }

    causation_rungs.append(_rung("first_treatment", first_treat, "first documented treatment"))
    if first_dx:
        causation_rungs.append(
            {
                "rung": "first_diagnosis",
                "date": first_dx.get("first_seen_date"),
                "label": first_dx.get("diagnosis_label"),
                "citation_ids": list(first_dx.get("citation_ids") or []),
                "status": "present",
                "missing_reason": None,
            }
        )
    else:
        causation_rungs.append({"rung": "first_diagnosis", "date": None, "label": "first diagnosis", "citation_ids": [], "status": "missing", "missing_reason": "first_diagnosis_not_found"})

    causation_rungs.append(_rung("imaging_confirmation", first_imaging, "first imaging confirmation"))
    causation_rungs.append(_rung("specialist_confirmation", first_spec, "first specialist confirmation"))
    causation_rungs.append(_rung("surgical_repair_or_high_intensity_equivalent", first_surg, "first surgical repair"))

    missing_rungs = [r for r in causation_rungs if str(r.get("status") or "") == "missing"]

    required_miss_rows = [r for r in visit_rows if list(r.get("missing_required_buckets") or [])]
    total = len(visit_rows)
    required_misses = sum(len(list(r.get("missing_required_buckets") or [])) for r in visit_rows)
    encounter_missing = len(required_miss_rows)
    ratio = (encounter_missing / total) if total else 0.0

    return {
        "registry_contract_version": "pass53.v1",
        "visit_abstraction_registry": visit_rows,
        "provider_role_registry": sorted(role_rows, key=lambda x: (str(x.get("provider_role") or ""), str(x.get("provider_name") or ""))),
        "diagnosis_registry": diagnosis_rows,
        "injury_clusters": clusters,
        "injury_cluster_severity": severity_rows,
        "treatment_escalation_path": escalation_path,
        "causation_timeline_registry": {
            "rungs": causation_rungs,
            "missing_rungs": missing_rungs,
        },
        "visit_bucket_quality": {
            "total_encounters": total,
            "encounters_with_missing_required_buckets": encounter_missing,
            "required_bucket_miss_count": required_misses,
            "missing_required_bucket_ratio": round(ratio, 4),
            "encounter_ids_with_missing_required_buckets": [str(r.get("event_id") or "") for r in required_miss_rows][:200],
        },
    }
