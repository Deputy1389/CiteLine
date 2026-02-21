from __future__ import annotations

import re
from typing import Any


MECHANISM_RE = re.compile(
    r"\b(mva|mvc|motor vehicle|rear[- ]end|collision|fall|slip and fall|assault)\b",
    re.IGNORECASE,
)
DAMAGES_RE = re.compile(
    r"\b(pain\s*\d+\s*/\s*10|rom|range of motion|strength\s*[0-5](?:\.\d+)?\s*/\s*5|restriction|unable to work|light duty)\b",
    re.IGNORECASE,
)
TREATMENT_RE = re.compile(
    r"\b(procedure|surgery|injection|epidural|fluoroscopy|depo-?medrol|lidocaine)\b",
    re.IGNORECASE,
)


def build_legal_usability_report(
    report_text: str,
    ctx: dict[str, Any],
    luqa: dict[str, Any],
    attorney: dict[str, Any],
) -> dict[str, Any]:
    failures: list[dict[str, Any]] = []
    hard_fail = False

    luqa_pass = bool(luqa.get("luqa_pass"))
    attorney_pass = bool(attorney.get("attorney_ready_pass"))
    luqa_score = int(luqa.get("luqa_score_0_100", 0) or 0)
    attorney_score = int(attorney.get("attorney_ready_score_0_100", 0) or 0)

    if not luqa_pass:
        hard_fail = True
        failures.append(
            {
                "code": "LEGAL_LUQA_FAILED",
                "severity": "hard",
                "message": "LUQA failed; chronology is not legally usable.",
                "examples": [f.get("code") for f in (luqa.get("failures") or [])[:5]],
            }
        )
    if not attorney_pass:
        hard_fail = True
        failures.append(
            {
                "code": "LEGAL_ATTORNEY_READINESS_FAILED",
                "severity": "hard",
                "message": "Attorney readiness failed.",
                "examples": [f.get("code") for f in (attorney.get("failures") or [])[:5]],
            }
        )

    required_sections = ["Liability Facts", "Causation Chain", "Damages Progression"]
    missing_sections = [s for s in required_sections if s.lower() not in report_text.lower()]
    if missing_sections:
        hard_fail = True
        failures.append(
            {
                "code": "LEGAL_MISSING_CASE_THEORY_SECTIONS",
                "severity": "hard",
                "message": "Required case-theory sections are missing from rendered output.",
                "examples": missing_sections[:5],
            }
        )

    for section in required_sections:
        low = report_text.lower()
        start = low.find(section.lower())
        if start < 0:
            continue
        candidates = [low.find(x, start + 1) for x in ["top 10 case-driving events", "appendix a:", "appendix b:", "appendix c:", "appendix d:", "appendix e:", "appendix f:"]]
        ends = [e for e in candidates if e > start]
        end = min(ends) if ends else len(report_text)
        sec = report_text[start:end]
        if "citation(s):" not in sec.lower():
            hard_fail = True
            failures.append(
                {
                    "code": "LEGAL_SECTION_UNCITED",
                    "severity": "hard",
                    "message": f"{section} section lacks citation-backed statements.",
                    "examples": [],
                }
            )

    source_buckets = set()
    page_text_by_number = (ctx.get("page_text_by_number") or {})
    for txt in page_text_by_number.values():
        low = (txt or "").lower()
        if re.search(r"\b(triage|hpi|emergency|ed visit|chief complaint)\b", low):
            source_buckets.add("ED")
        if re.search(r"\b(mri|impression)\b", low):
            source_buckets.add("MRI")
        if re.search(r"\b(ortho|orthopedic)\b", low) and re.search(r"\b(assessment|plan)\b", low):
            source_buckets.add("ORTHO")
        if re.search(r"\b(depo-?medrol|lidocaine|fluoroscopy|interlaminar|transforaminal|epidural)\b", low):
            source_buckets.add("PROCEDURE")
        if re.search(r"\b(pt eval|physical therapy|range of motion|strength\s*[0-5]\s*/\s*5)\b", low):
            source_buckets.add("PT")

    timeline_start = report_text.lower().find("chronological medical timeline")
    top10_start = report_text.lower().find("top 10 case-driving events")
    timeline_slice = report_text[timeline_start:top10_start] if timeline_start >= 0 and top10_start > timeline_start else report_text
    low_timeline = timeline_slice.lower()

    mechanism_present = bool(MECHANISM_RE.search(low_timeline))
    treatment_present = bool(TREATMENT_RE.search(low_timeline))
    damages_present = bool(DAMAGES_RE.search(low_timeline))

    if "ED" in source_buckets and not mechanism_present:
        hard_fail = True
        failures.append(
            {
                "code": "LEGAL_MISSING_MECHANISM_CHAIN",
                "severity": "hard",
                "message": "ED signal present in source but mechanism is absent in rendered timeline.",
                "examples": [],
            }
        )
    if "PROCEDURE" in source_buckets and not treatment_present:
        hard_fail = True
        failures.append(
            {
                "code": "LEGAL_MISSING_TREATMENT_CHAIN",
                "severity": "hard",
                "message": "Procedure signal present in source but treatment intervention chain is absent.",
                "examples": [],
            }
        )
    if "PT" in source_buckets and not damages_present:
        hard_fail = True
        failures.append(
            {
                "code": "LEGAL_MISSING_DAMAGES_PROGRESSION",
                "severity": "hard",
                "message": "PT signal present in source but damages/progression facts are absent in timeline.",
                "examples": [],
            }
        )

    low_value_patterns = [
        r"\binformed consent\b",
        r"\bface sheet\b",
        r"\bimpact was bp\b",
        r"\bchief complaint\s*&\s*history of present illness:?\b",
    ]
    low_value_hits: list[str] = []
    top10_start = report_text.lower().find("top 10 case-driving events")
    appendix_start = report_text.lower().find("appendix a:", top10_start + 1) if top10_start >= 0 else -1
    top10_slice = report_text[top10_start:appendix_start] if top10_start >= 0 and appendix_start > top10_start else report_text
    for pat in low_value_patterns:
        m = re.search(pat, top10_slice, re.IGNORECASE)
        if m:
            low_value_hits.append(m.group(0))
    if low_value_hits:
        hard_fail = True
        failures.append(
            {
                "code": "LEGAL_LOW_VALUE_SNIPPET_LEAK",
                "severity": "hard",
                "message": "Top 10 contains low-value administrative/consent snippets.",
                "examples": low_value_hits[:5],
            }
        )

    artifact_leaks: list[str] = []
    for pat in [r"\bimpact was bp\b", r"\[\s*[xX ]\s*\]", r"\bchief complaint\s*&\s*history of present illness\s*:\s*$"]:
        m = re.search(pat, report_text, re.IGNORECASE | re.MULTILINE)
        if m:
            artifact_leaks.append(m.group(0))
    if artifact_leaks:
        hard_fail = True
        failures.append(
            {
                "code": "LEGAL_ARTIFACT_TEXT_LEAK",
                "severity": "hard",
                "message": "Rendered report contains residual extraction artifacts.",
                "examples": artifact_leaks[:5],
            }
        )

    score = min(luqa_score, attorney_score)
    if hard_fail:
        score = min(score, 60)
    legal_pass = (not hard_fail) and score >= 90

    return {
        "legal_pass": legal_pass,
        "legal_score_0_100": int(score),
        "failures": failures,
        "metrics": {
            "luqa_pass": luqa_pass,
            "attorney_ready_pass": attorney_pass,
            "source_buckets": sorted(source_buckets),
            "mechanism_present": mechanism_present,
            "treatment_present": treatment_present,
            "damages_present": damages_present,
            "missing_sections": missing_sections,
            "low_value_snippet_hits": low_value_hits,
            "artifact_text_hits": artifact_leaks,
        },
    }
