"""
MIMIC-IV Real Packet Generator.
Uses admissions.csv, patients.csv, and diagnoses_icd.csv to generate realistic PDFs.
"""
import csv
import random
from pathlib import Path
from datetime import datetime, timedelta
from reportlab.lib.pagesizes import LETTER
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, PageBreak
from reportlab.lib.styles import getSampleStyleSheet

DATA_DIR = Path("c:/CiteLine/data/mimic_demo")
PDF_DIR = DATA_DIR / "real_packets"

# Simple mapping for demo ICD-9/10 codes
ICD_MAP = {
    "414": "Coronary atherosclerosis",
    "250": "Diabetes mellitus",
    "401": "Essential hypertension",
    "272": "Disorders of lipoid metabolism",
    "482": "Pneumonia",
    "038": "Septicemia",
    "995": "Systemic inflammatory response",
    "560": "Intestinal obstruction",
    "287": "Purpura and other hemorrhagic conditions",
    "600": "Hyperplasia of prostate",
    "389": "Hearing loss",
}

CLINICAL_TEMPLATES = [
    "Patient presented with worsening {complaint}. Physical exam notable for {finding}. Baseline labs reviewed.",
    "History is significant for {history}. Recent symptoms including {complaint} led to current evaluation.",
    "Acute medical management focused on {management}. Patient responded well to initial therapy.",
    "Discharge planning involves follow-up for {diagnosis}. Patient instructed on medication adherence.",
]

FINDINGS = ["tachycardia", "hypotension", "crackles on lung exam", "abdominal tenderness", "lower extremity edema"]
MANAGEMENTS = ["IV fluids", "antibiotic therapy", "diuresis", "surgical consultation", "pain management"]

def get_diagnosis_name(code):
    prefix = str(code)[:3]
    return ICD_MAP.get(prefix, f"Medical Condition {code}")

def load_data():
    admissions = []
    with open(DATA_DIR / "admissions.csv", 'r') as f:
        admissions = list(csv.DictReader(f))
    
    diagnoses = {}
    with open(DATA_DIR / "diagnoses_icd.csv", 'r') as f:
        for row in csv.DictReader(f):
            hid = row['hadm_id']
            if hid not in diagnoses: diagnoses[hid] = []
            diagnoses[hid].append(get_diagnosis_name(row['icd_code']))
            
    return admissions, diagnoses

def generate_pdf(subject_id, admin_list, diagnoses_map):
    output_path = PDF_DIR / f"Patient_{subject_id}.pdf"
    doc = SimpleDocTemplate(str(output_path), pagesize=LETTER)
    styles = getSampleStyleSheet()
    story = []
    
    # Header
    story.append(Paragraph(f"<b>UNIVERSITY MEDICAL CENTER - CLINICAL SUMMARY</b>", styles['Title']))
    story.append(Paragraph(f"PATIENT ID: {subject_id}", styles['Normal']))
    story.append(Spacer(1, 15))
    
    # Ensure admissions are sorted by date
    admin_list.sort(key=lambda x: x['admittime'])
    
    for adm in admin_list:
        hid = adm['hadm_id']
        adms = diagnoses_map.get(hid, ["Unspecified diagnosis"])
        primary_diag = adms[0]
        
        story.append(Paragraph(f"<b>ADMISSION RECORD: #{hid}</b>", styles['Heading2']))
        story.append(Paragraph(f"ADMITTED: {adm['admittime']} | DISCHARGED: {adm['dischtime']}", styles['Normal']))
        story.append(Paragraph(f"PRIMARY DIAGNOSIS: {primary_diag}", styles['Normal']))
        story.append(Spacer(1, 10))
        
        # discharge Summary
        story.append(Paragraph("<b>DISCHARGE SUMMARY</b>", styles['Heading3']))
        
        # Synthesize Realistic Note
        note_body = []
        note_body.append(CLINICAL_TEMPLATES[0].format(
            complaint=primary_diag.lower(),
            finding=random.choice(FINDINGS)
        ))
        note_body.append(CLINICAL_TEMPLATES[2].format(
            management=random.choice(MANAGEMENTS)
        ))
        if len(adms) > 1:
            note_body.append(f"Secondary findings included {', '.join(adms[1:4]).lower()}.")
        
        story.append(Paragraph(" ".join(note_body), styles['Normal']))
        
        # Add some "Lab Results" mock table
        story.append(Paragraph("<b>SELECTED LABS:</b>", styles['Normal']))
        story.append(Paragraph(f"WBC: {random.uniform(4.0, 15.0):.1f} | Hgb: {random.uniform(10.0, 16.0):.1f} | Plt: {random.randint(150, 450)}", styles['Normal']))
        story.append(Paragraph(f"Sodium: {random.randint(135, 145)} | Potassium: {random.uniform(3.5, 5.0):.1f} | Creatinine: {random.uniform(0.7, 1.5):.2f}", styles['Normal']))
        
        story.append(Spacer(1, 20))
    
    doc.build(story)

def main():
    PDF_DIR.mkdir(parents=True, exist_ok=True)
    print("Loading MIMIC-IV demo data...")
    admissions, diagnoses = load_data()
    
    # Group by patient
    patient_map = {}
    for adm in admissions:
        sid = adm['subject_id']
        if sid not in patient_map: patient_map[sid] = []
        patient_map[sid].append(adm)
        
    print(f"Generating packets for {len(patient_map)} patients...")
    for sid, adms in patient_map.items():
        generate_pdf(sid, adms, diagnoses)
        
    print(f"Complete. Packets in {PDF_DIR}")

if __name__ == "__main__":
    main()
