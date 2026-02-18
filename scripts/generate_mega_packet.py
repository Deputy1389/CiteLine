"""
Synthea Mega-Packet Generator.
Creates a massive (1000+ page) medical record PDF by aggregating and repeating Synthea data.
"""
import csv
import os
from pathlib import Path
from reportlab.lib.pagesizes import LETTER
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, PageBreak
from reportlab.lib.styles import getSampleStyleSheet

BASE_DIR = Path("c:/CiteLine/data/synthea/output/csv")
PDF_DIR = Path("c:/CiteLine/data/synthea/packets")
OUTPUT_FILE = PDF_DIR / "MEGA_STRESS_TEST_1000_PAGES.pdf"

def load_csv(name):
    path = BASE_DIR / f"{name}.csv"
    if not path.exists(): return []
    with open(path, 'r', encoding='utf-8') as f:
        return list(csv.DictReader(f))

def main():
    PDF_DIR.mkdir(parents=True, exist_ok=True)
    
    print("Loading Synthea CSVs...")
    patients = load_csv("patients")
    encounters = load_csv("encounters")
    observations = load_csv("observations")
    medications = load_csv("medications")
    conditions = load_csv("conditions")
    
    # Index everything by Patient ID
    data_by_pat = {}
    for p in patients:
        data_by_pat[p['Id']] = {
            'info': p,
            'encounters': [],
            'obs': {},
            'meds': {},
            'conds': {}
        }
    
    print("Indexing data...")
    for e in encounters:
        pid = e['PATIENT']
        if pid in data_by_pat:
            data_by_pat[pid]['encounters'].append(e)
    
    for o in observations:
        pid = o['PATIENT']
        if pid in data_by_pat:
            eid = o['ENCOUNTER']
            if eid not in data_by_pat[pid]['obs']: data_by_pat[pid]['obs'][eid] = []
            data_by_pat[pid]['obs'][eid].append(o)
            
    for m in medications:
        pid = m['PATIENT']
        if pid in data_by_pat:
            eid = m['ENCOUNTER']
            if eid not in data_by_pat[pid]['meds']: data_by_pat[pid]['meds'][eid] = []
            data_by_pat[pid]['meds'][eid].append(m)
            
    for c in conditions:
        pid = c['PATIENT']
        if pid in data_by_pat:
            eid = c['ENCOUNTER']
            if eid not in data_by_pat[pid]['conds']: data_by_pat[pid]['conds'][eid] = []
            data_by_pat[pid]['conds'][eid].append(c)

    styles = getSampleStyleSheet()
    doc = SimpleDocTemplate(str(OUTPUT_FILE), pagesize=LETTER)
    story = []
    
    story.append(Paragraph("<b>EXTREME STRESS TEST: 1000+ PAGE MEDICAL RECORD</b>", styles['Title']))
    story.append(Spacer(1, 20))

    page_count_est = 0
    iteration = 0
    
    # We aggregate all patients and repeat them until we reach a massive size.
    # To hit 1000 pages, we'll likely need to loop through the population a few times
    # or just ensure we have enough PageBreaks.
    
    while page_count_est < 1000:
        iteration += 1
        print(f"Adding iteration {iteration} of patient data (Est. page count: {page_count_est})...")
        
        for pid, pdata in data_by_pat.items():
            p = pdata['info']
            story.append(Paragraph(f"<b>PATIENT: {p['FIRST']} {p['LAST']} (Ref: {iteration})</b>", styles['Heading1']))
            story.append(Paragraph(f"Patient ID: {pid}", styles['Normal']))
            story.append(Spacer(1, 10))
            
            # Encounters
            for e in pdata['encounters']:
                eid = e['Id']
                story.append(Paragraph(f"Encounter: {e['DESCRIPTION']} ({e['START']})", styles['Heading2']))
                
                # Medications
                e_meds = pdata['meds'].get(eid, [])
                if e_meds:
                    story.append(Paragraph("Medications:", styles['Heading3']))
                    for med in e_meds:
                        story.append(Paragraph(f"• {med['DESCRIPTION']}", styles['Normal']))
                
                # observations
                e_obs = pdata['obs'].get(eid, [])
                if e_obs:
                    story.append(Paragraph("Observations:", styles['Heading3']))
                    story.append(Paragraph("; ".join([f"{o['DESCRIPTION']}: {o['VALUE']} {o['UNITS']}" for o in e_obs]), styles['Normal']))
                
                story.append(PageBreak()) # Force many pages
                page_count_est += 1
                
                if page_count_est >= 1100: # Targeted overshoot
                    break
            if page_count_est >= 1100:
                break
                
    print(f"Building PDF {OUTPUT_FILE} with ~{page_count_est} pages...")
    doc.build(story)
    print("Completed!")

if __name__ == "__main__":
    main()
