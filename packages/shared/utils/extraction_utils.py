import re
from apps.worker.steps.events.report_quality import sanitize_for_report

def extract_pt_elements(text: str) -> list[str]:
    out: list[str] = []
    if not text:
        return out
    low = text.lower()
    if re.search(r"\b(initial (evaluation|eval)|pt eval)\b", low):
        out.append("PT Initial Evaluation documented.")
    if re.search(r"\b(re-?evaluation|re-?eval|progress note)\b", low):
        out.append("PT Re-evaluation/Progress documented.")
    if re.search(r"\b(discharge summary|pt discharge)\b", low):
        out.append("PT Discharge Summary documented.")
    for m in re.finditer(r"\bpain(?:\s*(?:score|level|severity))?\s*[:=]?\s*(\d{1,2}\s*/\s*10|\d{1,2})\b", text, re.IGNORECASE):
        out.append(f"Pain score: {m.group(1).replace(' ', '')}.")
    for m in re.finditer(r"\b(?:cervical|lumbar|thoracic)?\s*rom[^.;\n]{0,80}", text, re.IGNORECASE):
        out.append(m.group(0).strip())
    for m in re.finditer(r"\bstrength\s*[:=]?\s*\d(?:\.\d)?\s*/\s*5\b", text, re.IGNORECASE):
        out.append(m.group(0).strip())
    for m in re.finditer(r"\b(difficulty with adls|functional limitation[^.;\n]*|sitting tolerance[^.;\n]*|lifting[^.;\n]*restriction[^.;\n]*)", low, re.IGNORECASE):
        out.append(m.group(1).strip())
    for m in re.finditer(r"\b(plan[^.;\n]{0,120}|home exercise[^.;\n]{0,120}|follow[- ]?up[^.;\n]{0,120})", text, re.IGNORECASE):
        out.append(m.group(0).strip())
    dedup: list[str] = []
    seen: set[str] = set()
    for s in out:
        cleaned = sanitize_for_report(s).strip()
        if not cleaned:
            continue
        k = cleaned.lower()
        if k in seen:
            continue
        seen.add(k)
        dedup.append(cleaned)
    return dedup[:10]

def extract_imaging_elements(text: str) -> list[str]:
    out: list[str] = []
    if not text:
        return out
    low = text.lower()
    modality = None
    if "mri" in low:
        modality = "MRI"
    elif re.search(r"\b(x-?ray|xr|radiograph)\b", low):
        modality = "XR"
    if modality:
        out.append(f"Imaging modality: {modality}.")
    levels = sorted(set(m.group(1).upper() for m in re.finditer(r"\b([CTL]\d-\d)\b", text, re.IGNORECASE)))
    if levels:
        out.append(f"Anatomical level(s): {', '.join(levels)}.")
    for m in re.finditer(r"\bimpression\s*[:\-]\s*([^\n]+)", text, re.IGNORECASE):
        out.append(f"Impression: {m.group(1).strip()}")
    for m in re.finditer(r"\b([CTL]\d-\d)\s*:\s*([^\n]+)", text, re.IGNORECASE):
        out.append(f"{m.group(1).upper()}: {m.group(2).strip()}")
    for m in re.finditer(r"\b(disc protrusion[^.;\n]*|foramen[^.;\n]*|thecal sac[^.;\n]*|no cord signal abnormality[^.;\n]*)", low, re.IGNORECASE):
        out.append(m.group(1).strip())
    dedup: list[str] = []
    seen: set[str] = set()
    for s in out:
        cleaned = sanitize_for_report(s).strip()
        if not cleaned:
            continue
        k = cleaned.lower()
        if k in seen:
            continue
        seen.add(k)
        dedup.append(cleaned)
    return dedup[:10]
