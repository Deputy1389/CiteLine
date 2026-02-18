from __future__ import annotations

import json
import re
import shutil
import sys
from pathlib import Path
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.eval_sample_172 import extract_pdf_text, run_sample_pipeline


def evaluate_mega_stress() -> dict:
    src = ROOT / "data" / "synthea" / "packets" / "MEGA_STRESS_TEST_1000_PAGES.pdf"
    if not src.exists():
        raise FileNotFoundError(f"Mega stress packet not found: {src}")

    run_id = f"eval-mega-{uuid4().hex[:8]}"
    pdf_path, ctx = run_sample_pipeline(src, run_id)

    eval_dir = ROOT / "data" / "evals" / "mega_stress"
    eval_dir.mkdir(parents=True, exist_ok=True)
    out_pdf = eval_dir / "output.pdf"
    shutil.copyfile(pdf_path, out_pdf)
    text = extract_pdf_text(out_pdf)
    low = text.lower()

    timeline_rows = len(
        re.findall(
            r"^\d{4}-\d{2}-\d{2}.*-\s*(Imaging Study|Procedure|Office Visit|Pt Visit|Er Visit|Hospital Admission|Hospital Discharge|Inpatient Daily Note)",
            text,
            re.IGNORECASE | re.MULTILINE,
        )
    )
    date_of_injury = re.search(r"Date of Injury:\s*(.*)", text, re.IGNORECASE)
    mechanism = re.search(r"Mechanism:\s*(.*)", text, re.IGNORECASE)

    scorecard = {
        "source_pdf": str(src),
        "timeline_rows": timeline_rows,
        "contains_date_not_documented_pt_visit": bool(re.search(r"date not documented\s*-\s*pt visit", low)),
        "contains_provider_lines": "provider:" in low,
        "contains_encounter_fallback": "encounter documented; details available" in low,
        "contains_gunshot": "gunshot wound" in low,
        "date_of_injury": date_of_injury.group(1).strip() if date_of_injury else None,
        "mechanism": mechanism.group(1).strip() if mechanism else None,
        "projection_entry_count": len(ctx.get("projection_entries", [])),
        "projection_patient_label_count": len(
            {e.patient_label for e in ctx.get("projection_entries", []) if getattr(e, "patient_label", "Unknown Patient") != "Unknown Patient"}
        ),
        "patient_section_count": len(re.findall(r"^Patient:\s+", text, re.IGNORECASE | re.MULTILINE)),
    }
    requires_patient_sections = scorecard["projection_patient_label_count"] > 1
    scorecard["overall_pass"] = not any(
        [
            scorecard["contains_date_not_documented_pt_visit"],
            scorecard["contains_provider_lines"],
            scorecard["contains_encounter_fallback"],
            scorecard["contains_gunshot"],
            scorecard["timeline_rows"] >= 80,
            requires_patient_sections and scorecard["patient_section_count"] < 2,
        ]
    )

    (eval_dir / "scorecard.json").write_text(json.dumps(scorecard, indent=2), encoding="utf-8")
    return scorecard


def main() -> int:
    scorecard = evaluate_mega_stress()
    print(json.dumps(scorecard, indent=2))
    return 0 if scorecard["overall_pass"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
