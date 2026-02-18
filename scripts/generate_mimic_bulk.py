"""
MIMIC-IV Bulk Stress Test Generator.
Generates 50+ large patient record PDFs with multiple admissions and heavy text.
"""
import random
import uuid
from pathlib import Path
from datetime import datetime, timedelta
from reportlab.lib.pagesizes import LETTER
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer
from reportlab.lib.styles import getSampleStyleSheet

DATA_DIR = Path("c:/CiteLine/data/mimic_demo")
PDF_DIR = DATA_DIR / "pdfs"

DIAGNOSES = [
    "SEPSIS", "CONGESTIVE HEART FAILURE", "PNEUMONIA", "HIP FRACTURE", 
    "COVID-19", "CHRONIC KIDNEY DISEASE", "DIABETIC KETOACIDOSIS",
    "PULMONARY EMBOLISM", "ACUTE MYOCARDIAL INFARCTION", "CELLULITIS"
]

COMPLAINTS = [
    "Shortness of breath and chest pain.",
    "Altered mental status and fever.",
    "Falls at home with left hip pain.",
    "Productive cough and fatigue.",
    "Severe abdominal pain and nausea."
]

LOREM_IPSUM = (
    "In patient presented with progressive symptoms. Physical examination revealed elevated heart rate "
    "and borderline hypotension. Labs show leukocytosis and elevated lactate. Initial management included "
    "aggressive fluid resuscitation and broad-spectrum antibiotics (Vancomycin/Zosyn). Respiratory status "
    "deteriorated requiring supplemental oxygen via nasal cannula. Chest X-ray showed bilateral infiltrates. "
    "Cardiology consulted for suspected NSTEMI. Patient spent three days in ICU before stabilizing. "
    "Transitioned to floor on day 4. Physical therapy initiated for mobility. Discharge planning started "
    "with home health and oxygen. Final assessment shows stable hemodynamics and resolving infection. "
) * 10  # Make it long

def generate_random_date(start_year=2150, end_year=2190):
    year = random.randint(start_year, end_year)
    month = random.randint(1, 12)
    day = random.randint(1, 28)
    return datetime(year, month, day)

def create_bulk_pdfs(count=50):
    PDF_DIR.mkdir(parents=True, exist_ok=True)
    styles = getSampleStyleSheet()
    
    print(f"Generating {count} large patient records...")
    
    for i in range(count):
        patient_id = 100000 + i
        output_path = PDF_DIR / f"Patient_{patient_id}.pdf"
        
        doc = SimpleDocTemplate(str(output_path), pagesize=LETTER)
        story = []
        
        # Patient Header
        story.append(Paragraph(f"<b>METRO GENERAL HOSPITAL - STRESS TEST RECORD</b>", styles['Title']))
        story.append(Paragraph(f"Patient ID: {patient_id}", styles['Normal']))
        story.append(Paragraph(f"DOB: 01/01/{random.randint(2100, 2130)}", styles['Normal']))
        story.append(Spacer(1, 20))
        
        # Generate 3-8 admissions per patient to make the file "large"
        num_admissions = random.randint(3, 8)
        
        base_date = generate_random_date()
        
        for j in range(num_admissions):
            admit_date = base_date + timedelta(days=j*180) # Spread out
            disch_date = admit_date + timedelta(days=random.randint(3, 10))
            
            hadm_id = 200000 + (i * 10) + j
            diag = random.choice(DIAGNOSES)
            
            story.append(Paragraph(f"<b>Admission ID: {hadm_id}</b>", styles['Heading2']))
            story.append(Paragraph(f"Admit Date: {admit_date.strftime('%m/%d/%Y')} | Discharge: {disch_date.strftime('%m/%d/%Y')}", styles['Normal']))
            story.append(Paragraph(f"Diagnosis: {diag}", styles['Normal']))
            story.append(Spacer(1, 10))
            
            # Discharge Summary
            story.append(Paragraph("<b>DISCHARGE SUMMARY</b>", styles['Heading3']))
            story.append(Paragraph(f"<b>Chief Complaint:</b> {random.choice(COMPLAINTS)}", styles['Normal']))
            story.append(Paragraph(f"<b>History of Present Illness:</b> {LOREM_IPSUM}", styles['Normal']))
            story.append(Paragraph(f"<b>Assessment & Plan:</b> Continue medications. Follow up with PCM in 1 week.", styles['Normal']))
            story.append(Spacer(1, 20))
            
        doc.build(story)
        if (i+1) % 10 == 0:
            print(f"Generated {i+1}/{count} files...")

    print(f"Bulk generation complete. Files are in {PDF_DIR}")

if __name__ == "__main__":
    create_bulk_pdfs(50)
