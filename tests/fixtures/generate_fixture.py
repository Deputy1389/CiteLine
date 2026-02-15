"""
Generate a synthetic PDF fixture for testing.
This creates a realistic-looking medical PDF with clinical content.
"""
from __future__ import annotations

import io
from pathlib import Path

from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer
from reportlab.lib.units import inch


def create_synthetic_pdf() -> bytes:
    """Create a multi-page synthetic medical record PDF."""
    buf = io.BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=letter)
    styles = getSampleStyleSheet()
    story = []

    # Page 1: Clinical note
    story.append(Paragraph("Southwest Regional Medical Center", styles["Title"]))
    story.append(Paragraph("Provider: Dr. Sarah Johnson, MD", styles["Normal"]))
    story.append(Spacer(1, 0.2 * inch))
    story.append(Paragraph("Date of Service: 03/15/2024", styles["Normal"]))
    story.append(Paragraph("Patient: John Smith", styles["Normal"]))
    story.append(Spacer(1, 0.2 * inch))
    story.append(Paragraph("<b>Chief Complaint:</b>", styles["Heading3"]))
    story.append(Paragraph(
        "Patient presents with lower back pain radiating to left leg following motor vehicle accident on 03/01/2024.",
        styles["Normal"],
    ))
    story.append(Spacer(1, 0.1 * inch))
    story.append(Paragraph("<b>History of Present Illness:</b>", styles["Heading3"]))
    story.append(Paragraph(
        "45-year-old male involved in rear-end collision on 03/01/2024. "
        "Reports onset of low back pain immediately after accident. Pain rated 7/10.",
        styles["Normal"],
    ))
    story.append(Spacer(1, 0.1 * inch))
    story.append(Paragraph("<b>Physical Exam:</b>", styles["Heading3"]))
    story.append(Paragraph(
        "Vital Signs: BP 130/85, HR 78, Temp 98.6F. "
        "Lumbar spine: tenderness at L4-L5. Straight leg raise positive on left.",
        styles["Normal"],
    ))
    story.append(Spacer(1, 0.1 * inch))
    story.append(Paragraph("<b>Assessment:</b>", styles["Heading3"]))
    story.append(Paragraph(
        "1. Lumbar disc herniation, L4-L5\n"
        "2. Left-sided radiculopathy\n"
        "3. Cervical strain",
        styles["Normal"],
    ))
    story.append(Spacer(1, 0.1 * inch))
    story.append(Paragraph("<b>Plan:</b>", styles["Heading3"]))
    story.append(Paragraph(
        "1. Order MRI lumbar spine\n"
        "2. Prescribe Naproxen 500mg BID\n"
        "3. Refer to physical therapy 2-3x/week\n"
        "4. Follow up in 2 weeks",
        styles["Normal"],
    ))
    story.append(Spacer(1, 0.1 * inch))
    story.append(Paragraph("<b>Work Status:</b>", styles["Heading3"]))
    story.append(Paragraph(
        "Restrictions: No lifting over 10 lbs, no prolonged sitting. Light duty only.",
        styles["Normal"],
    ))

    # Page 2: Imaging report
    story.append(Spacer(1, 3 * inch))  # Force page break
    story.append(Paragraph("Southwest Radiology Associates", styles["Title"]))
    story.append(Paragraph("Radiology Report", styles["Heading2"]))
    story.append(Spacer(1, 0.2 * inch))
    story.append(Paragraph("Exam Date: 03/18/2024", styles["Normal"]))
    story.append(Paragraph("Study: MRI Lumbar Spine without contrast", styles["Normal"]))
    story.append(Paragraph("Referring Provider: Dr. Sarah Johnson", styles["Normal"]))
    story.append(Spacer(1, 0.2 * inch))
    story.append(Paragraph("<b>Technique:</b>", styles["Heading3"]))
    story.append(Paragraph(
        "Standard MRI protocol for lumbar spine was performed without IV contrast.",
        styles["Normal"],
    ))
    story.append(Spacer(1, 0.1 * inch))
    story.append(Paragraph("<b>Findings:</b>", styles["Heading3"]))
    story.append(Paragraph(
        "L4-L5: Posterior disc herniation measuring 5mm, causing mild left foraminal narrowing "
        "and impingement of the left L5 nerve root. "
        "No spinal canal stenosis.",
        styles["Normal"],
    ))
    story.append(Spacer(1, 0.1 * inch))
    story.append(Paragraph("<b>Impression:</b>", styles["Heading3"]))
    story.append(Paragraph(
        "1. L4-L5 disc herniation with left foraminal narrowing and L5 nerve root impingement.\n"
        "2. No fracture or significant stenosis identified.\n"
        "3. Recommend clinical correlation.",
        styles["Normal"],
    ))

    # Page 3: Physical therapy note
    story.append(Spacer(1, 3 * inch))  # Force page break
    story.append(Paragraph("Pinnacle Physical Therapy & Rehabilitation", styles["Title"]))
    story.append(Paragraph("Physical Therapy Daily Note", styles["Heading2"]))
    story.append(Spacer(1, 0.2 * inch))
    story.append(Paragraph("Visit Date: 03/22/2024", styles["Normal"]))
    story.append(Paragraph("Visit #1", styles["Normal"]))
    story.append(Paragraph("Plan of Care: Lumbar stabilization", styles["Normal"]))
    story.append(Spacer(1, 0.2 * inch))
    story.append(Paragraph("<b>Subjective:</b>", styles["Heading3"]))
    story.append(Paragraph(
        "Patient reports continued low back pain 6/10, with radiating left leg symptoms.",
        styles["Normal"],
    ))
    story.append(Paragraph("<b>Exercise:</b>", styles["Heading3"]))
    story.append(Paragraph(
        "Therapeutic exercise: core stabilization, nerve glides, gentle ROM. "
        "20 minutes total.",
        styles["Normal"],
    ))
    story.append(Paragraph("<b>Progress:</b>", styles["Heading3"]))
    story.append(Paragraph(
        "Patient tolerated treatment well. Goals: reduce pain to 3/10 by week 6.",
        styles["Normal"],
    ))

    # Page 4: Billing statement
    story.append(Spacer(1, 3 * inch))  # Force page break
    story.append(Paragraph("Southwest Regional Medical Center", styles["Title"]))
    story.append(Paragraph("Patient Statement of Charges", styles["Heading2"]))
    story.append(Spacer(1, 0.2 * inch))
    story.append(Paragraph("Statement Date: 04/01/2024", styles["Normal"]))
    story.append(Paragraph("Patient: John Smith", styles["Normal"]))
    story.append(Spacer(1, 0.2 * inch))
    story.append(Paragraph("Office Visit 03/15/2024 — CPT 99214 — $250.00", styles["Normal"]))
    story.append(Paragraph("X-Ray Cervical Spine — CPT 72040 — $175.00", styles["Normal"]))
    story.append(Spacer(1, 0.1 * inch))
    story.append(Paragraph("Total Due: $425.00", styles["Normal"]))
    story.append(Paragraph("Balance Due: $425.00", styles["Normal"]))

    doc.build(story)
    return buf.getvalue()


if __name__ == "__main__":
    # Generate and save the fixture
    fixture_dir = Path(__file__).parent
    pdf_bytes = create_synthetic_pdf()
    output_path = fixture_dir / "synthetic_medical_record.pdf"
    output_path.write_bytes(pdf_bytes)
    print(f"Generated {len(pdf_bytes)} bytes → {output_path}")
