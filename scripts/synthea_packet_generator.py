"""
Synthea Packet Generator.
Converts Synthea CSV outputs (Patients, Encounters, Obs, Meds, Conditions) into PDF packets for CiteLine.
"""
import csv
import os
from pathlib import Path
from reportlab.lib.pagesizes import LETTER
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle
from reportlab.lib import colors
from reportlab.lib.styles import getSampleStyleSheet

BASE_DIR = Path("c:/CiteLine/data/synthea/output/csv")
PDF_DIR = Path("c:/CiteLine/data/synthea/packets")

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
    
    count = 0
    for pid, pdata in data_by_pat.items():
        p = pdata['info']
        name = f"{p['FIRST']} {p['LAST']}"
        filename = f"{name.replace(' ', '_')}_{pid[:8]}.pdf"
        output_path = PDF_DIR / filename
        
        doc = SimpleDocTemplate(str(output_path), pagesize=LETTER)
        story = []
        
        # Header
        story.append(Paragraph(f"<b>MEDICAL RECORD SUMMARY: {name}</b>", styles['Title']))
        story.append(Paragraph(f"Patient ID: {pid}", styles['Normal']))
        story.append(Paragraph(f"DOB: {p['BIRTHDATE']} | Gender: {p['GENDER']}", styles['Normal']))
        story.append(Paragraph(f"Address: {p['ADDRESS']}, {p['CITY']}, {p['STATE']} {p['ZIP']}", styles['Normal']))
        story.append(Spacer(1, 20))
        
        # Encounters (Sort by Date)
        sorted_encs = sorted(pdata['encounters'], key=lambda x: x['START'])
        
        for e in sorted_encs:
            eid = e['Id']
            story.append(Paragraph(f"<b>Encounter: {e['DESCRIPTION']}</b>", styles['Heading2']))
            story.append(Paragraph(f"Date: {e['START']} to {e['STOP']}", styles['Normal']))
            story.append(Paragraph(f"Type: {e['ENCOUNTERCLASS'].upper()}", styles['Normal']))
            story.append(Spacer(1, 10))
            
            # Conditions
            e_conds = pdata['conds'].get(eid, [])
            if e_conds:
                story.append(Paragraph("<b>Diagnoses & Conditions:</b>", styles['Heading3']))
                for cond in e_conds:
                    story.append(Paragraph(f"• {cond['DESCRIPTION']}", styles['Normal']))
                story.append(Spacer(1, 5))
                
            # Medications
            e_meds = pdata['meds'].get(eid, [])
            if e_meds:
                story.append(Paragraph("<b>Medications Prescribed/Administered:</b>", styles['Heading3']))
                for med in e_meds:
                    story.append(Paragraph(f"• {med['DESCRIPTION']}", styles['Normal']))
                story.append(Spacer(1, 5))
                
            # observations (Vitals/Labs)
            e_obs = pdata['obs'].get(eid, [])
            if e_obs:
                story.append(Paragraph("<b>Observations & Vitals:</b>", styles['Heading3']))
                # Group by description
                obs_text = []
                for o in e_obs:
                    val = f"{o['VALUE']} {o['UNITS']}" if o['UNITS'] else o['VALUE']
                    obs_text.append(f"{o['DESCRIPTION']}: {val}")
                
                # Split into columns if too long? For now just flow text
                story.append(Paragraph("; ".join(obs_text), styles['Normal']))
                story.append(Spacer(1, 15))
                
            story.append(Spacer(1, 10))
            
        doc.build(story)
        count += 1
        if count % 10 == 0:
            print(f"Generated {count}/100 packets...")

    print(f"Completed! {count} packets in {PDF_DIR}")

if __name__ == "__main__":
    main()
