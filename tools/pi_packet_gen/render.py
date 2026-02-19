import os
import random
from reportlab.lib.pagesizes import letter
from reportlab.lib import colors
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import inch
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, PageBreak, Frame, PageTemplate
from reportlab.lib.enums import TA_CENTER, TA_LEFT

from .schema import Case, GeneratedDocument, DocumentType, AnomalyType
from .text_lib import TextLibrary

class DocumentRenderer:
    def __init__(self, output_dir: str):
        self.output_dir = output_dir
        self.styles = getSampleStyleSheet()
        self._init_custom_styles()
        self.text_lib = None

    def _init_custom_styles(self):
        self.styles.add(ParagraphStyle(name='Header1', parent=self.styles['Heading1'], fontSize=16, spaceAfter=12))
        self.styles.add(ParagraphStyle(name='Header2', parent=self.styles['Heading2'], fontSize=14, spaceBefore=12, spaceAfter=6))
        self.styles.add(ParagraphStyle(name='NormalSmall', parent=self.styles['Normal'], fontSize=9, leading=11))
        self.styles.add(ParagraphStyle(name='Mono', parent=self.styles['Normal'], fontName='Courier', fontSize=9))

    def render_case(self, case: Case):
        self.text_lib = TextLibrary(case.seed)
        docs_dir = os.path.join(self.output_dir, "docs")
        os.makedirs(docs_dir, exist_ok=True)
        
        for doc in case.documents:
            filepath = os.path.join(docs_dir, doc.filename)
            self._render_document(doc, filepath, case.patient)

    def _header_footer(self, canvas, doc, patient_info, provider_info, date_info, doc_obj: GeneratedDocument):
        canvas.saveState()
        canvas.setFont('Helvetica', 9)
        
        # Anomaly: Wrong Patient Info
        display_patient = patient_info
        for a in doc_obj.anomalies:
            if a.type == AnomalyType.WRONG_PATIENT_INFO and a.page_in_doc == canvas.getPageNumber():
                display_patient = f"{a.details['incorrect_name']} (MRN: ERROR)"
                
        canvas.drawString(50, 750, f"{provider_info}")
        canvas.drawString(50, 740, f"Patient: {display_patient} | Date: {date_info}")
        canvas.line(50, 735, 550, 735)
        
        # Footer
        page_num = canvas.getPageNumber()
        canvas.drawString(500, 30, f"Page {page_num}")
        canvas.restoreState()

    def _render_document(self, doc: GeneratedDocument, filepath: str, patient):
        doc_template = SimpleDocTemplate(
            filepath, 
            pagesize=letter,
            rightMargin=50, leftMargin=50, 
            topMargin=72, bottomMargin=50 # Increased top margin for header
        )
        
        # Create a Frame and PageTemplate to draw header on every page
        frame = Frame(doc_template.leftMargin, doc_template.bottomMargin, doc_template.width, doc_template.height, id='normal')
        
        def on_page(canvas, pdf_doc):
            self._header_footer(canvas, pdf_doc, f"{patient.name} ({patient.mrn})", doc.provider, doc.date, doc)
            
        template = PageTemplate(id='test', frames=frame, onPage=on_page)
        doc_template.addPageTemplates([template])
        
        elements = []
        
        # Title separate from header
        elements.append(Paragraph(f"<b>{doc.doc_type.value.upper()}</b>", self.styles['Header1']))
        elements.append(Spacer(1, 12))
        
        # Dispatch
        if doc.doc_type == DocumentType.ED_NOTES:
            self._render_ed_content(elements, doc.content, doc.page_count)
        elif doc.doc_type == DocumentType.PT_RECORDS:
            self._render_pt_content(elements, doc.content, doc.page_count, doc)
        elif doc.doc_type == DocumentType.BILLING_LEDGER:
            self._render_billing_content(elements, doc.content, doc.page_count)
        elif doc.doc_type == DocumentType.RADIOLOGY_REPORT:
            self._render_radio_content(elements, doc.content, doc.page_count)
        elif doc.doc_type == DocumentType.PROCEDURE_NOTE:
            self._render_procedure_content(elements, doc.content, doc.page_count)
        elif doc.doc_type == DocumentType.ORTHO_VISIT:
            self._render_ortho_content(elements, doc.content, doc.page_count, doc)
        elif doc.doc_type == DocumentType.PACKET_NOISE:
            self._render_noise_content(elements, doc.page_count)
        else:
            self._render_generic_content(elements, doc.content, doc.page_count)
            
        doc_template.build(elements)
        
        # Post-Processing: Enforce Page Count by Padding
        self._pad_to_page_count(filepath, doc.page_count)

    def _pad_to_page_count(self, filepath: str, target_pages: int):
        from pypdf import PdfReader, PdfWriter
        
        try:
            reader = PdfReader(filepath)
            actual_pages = len(reader.pages)
            
            if actual_pages >= target_pages:
                return
                
            # Pad with "Intentionally Blank" or just blank
            writer = PdfWriter()
            writer.append(reader)
            
            # Create a blank page (or use the last page as template?)
            # Just add blank pages.
            # Ideally we'd keep the header/footer, but that requires overlay.
            # For speed/simplicity, just blank pages is safer than crashing. 
            # OR we can assume Render logic SHOULD have worked and this is a fallback.
            
            diff = target_pages - actual_pages
            print(f"Padding {os.path.basename(filepath)}: {actual_pages} -> {target_pages} (+{diff} pages)")
            
            for _ in range(diff):
                writer.add_blank_page(width=letter[0], height=letter[1])
            
            with open(filepath, "wb") as f:
                writer.write(f)
                
        except Exception as e:
            print(f"Error padding {filepath}: {e}")

    def _force_pagination(self, elements, current_content_length_estimate, target_pages):
        pass

    def _render_ed_content(self, elements, content, page_count):
        # ... (keep existing)
        # ... (Existing ED content logic) ...
        # Vitals
        if "triage_vitals" in content:
            elements.append(Paragraph("Triage Vitals", self.styles['Header2']))
            data = [["Time", "BP", "HR", "RR", "Temp", "SpO2", "Pain"]]
            for v in content["triage_vitals"]:
                data.append([v['time'], v['bp'], v['hr'], v['rr'], v['temp'], v['sats'], v['pain']])
            t = Table(data, hAlign='LEFT')
            t.setStyle(TableStyle([
                ('BACKGROUND', (0,0), (-1,0), colors.lightgrey),
                ('GRID', (0,0), (-1,-1), 0.5, colors.black),
                ('FONTSIZE', (0,0), (-1,-1), 9),
            ]))
            elements.append(t)
            elements.append(Spacer(1, 12))

        # Standard Sections
        sections = [("Chief Complaint", "chief_complaint"), ("HPI", "hpi"), ("ROS", "ros"), ("Physical Exam", "physical_exam"), ("MDM", "mdm")]
        for title, key in sections:
             if key in content:
                 elements.append(Paragraph(title, self.styles['Header2']))
                 val = content[key]
                 if isinstance(val, list):
                     for item in val: elements.append(Paragraph(f"• {item}", self.styles['NormalSmall']))
                 else:
                     elements.append(Paragraph(str(val), self.styles['NormalSmall']))
                 elements.append(Spacer(1, 6))

        # Orders & Meds - maybe force page break?
        if page_count > 4: elements.append(PageBreak())
        
        sections2 = [("Orders", "orders"), ("Meds Given", "meds_given"), ("Discharge", "discharge_meds"), ("Instructions", "instructions")]
        for title, key in sections2:
             if key in content:
                 elements.append(Paragraph(title, self.styles['Header2']))
                 val = content[key]
                 if isinstance(val, list):
                     for item in val: elements.append(Paragraph(f"• {item}", self.styles['NormalSmall']))
                 else:
                     elements.append(Paragraph(str(val), self.styles['NormalSmall']))
                 elements.append(Spacer(1, 6))
                 
        # Nursing Notes - heavy filler
        if "nursing_notes" in content:
            elements.append(PageBreak())
            elements.append(Paragraph("Nursing Notes / Flowsheet", self.styles['Header2']))
            data = [["Time", "Note"]]
            for n in content["nursing_notes"]:
                data.append([n['time'], Paragraph(n['note'], self.styles['NormalSmall'])])
            
            t = Table(data, colWidths=[1*inch, 5.5*inch], hAlign='LEFT')
            t.setStyle(TableStyle([('GRID', (0,0), (-1,-1), 0.5, colors.black), ('VALIGN', (0,0), (-1,-1), 'TOP')]))
            elements.append(t)

    def _render_pt_content(self, elements, content, page_count, doc_obj: GeneratedDocument):
        if "visit_type" in content: # Eval or Progress
             self._render_pt_eval_or_progress(elements, content, page_count)
             return

        if "visits" in content:
            for i, visit in enumerate(content["visits"]):
                # Page 1: SOAP Note
                v_date = visit['date']
                for a in doc_obj.anomalies:
                    if a.type == AnomalyType.CONFLICTING_DATE:
                        v_date = a.details['incorrect_date']
                        
                elements.append(Paragraph(f"<b>DAILY TREATMENT NOTE - {v_date}</b>", self.styles['Header2']))
                
                state = visit.get('state', {})
                pain = state.get('pain_score', 5)
                
                data = [
                    ["Subjective:", Paragraph(f"Patient reports pain levels at {pain}/10. {state.get('narrative', '')}", self.styles['NormalSmall'])],
                    ["Objective:", Paragraph(visit.get('objective', f"Palpation reveals guarded movement in {state.get('focus', 'cervical')} region. ROM limited by pain."), self.styles['NormalSmall'])],
                    ["Assessment:", Paragraph(visit.get('assessment', f"Patient is {state.get('trend', 'stable')}. Tolerating treatment."), self.styles['NormalSmall'])],
                    ["Plan:", Paragraph(visit.get('plan', 'Continue with current plan of care.'), self.styles['NormalSmall'])]
                ]
                t = Table(data, colWidths=[1.2*inch, 5.3*inch])
                t.setStyle(TableStyle([
                    ('VALIGN', (0,0), (-1,-1), 'TOP'),
                    ('GRID', (0,0), (-1,-1), 0.5, colors.grey),
                    ('PADDING', (0,0), (-1,-1), 6)
                ]))
                elements.append(t)
                elements.append(Spacer(1, 12))
                
                # Checkbox texture
                elements.append(Paragraph("<b>Modalities / Interventions:</b>", self.styles['Normal']))
                mod_data = [
                    ["[X] Therapeutic Exercise", "[X] Manual Therapy", "[ ] Ultrasound"],
                    ["[X] Neuromuscular Re-ed", "[ ] Electrical Stim", "[X] Hot/Cold Packs"],
                    ["[ ] Therapeutic Activities", "[ ] Traction", "[ ] Gait Training"]
                ]
                mt = Table(mod_data, colWidths=[2.1*inch, 2.1*inch, 2.1*inch])
                mt.setStyle(TableStyle([('FONTSIZE', (0,0), (-1,-1), 8), ('GRID', (0,0), (-1,-1), 0.2, colors.lightgrey)]))
                elements.append(mt)
                elements.append(PageBreak())
                
                # Page 2: Exercise Flowsheet
                elements.append(Paragraph(f"<b>EXERCISE FLOWSHEET - {v_date}</b>", self.styles['Header2']))
                
                focus = state.get('focus', 'mixed')
                if focus == 'cervical':
                    exercises = [
                        ["Cervical Retractions", "3", "10", "Hold 5s, seated"],
                        ["Scapular Squeezes", "3", "15", "Gentle, no weight"],
                        ["Chin Tucks", "2", "10", "Supine, neutral spine"],
                        ["Isometric Rotations", "3", "10", "Bilateral"]
                    ]
                elif focus == 'lumbar':
                    exercises = [
                        ["Pelvic Tilts", "3", "20", "On mat"],
                        ["Bridges", "3", "10", "Hold 3s"],
                        ["Bird Dog", "2", "10", "Maintain neutral spine"],
                        ["Lumbar Extensions", "2", "15", "Standing"]
                    ]
                else:
                    exercises = [
                        ["Cat-Cow", "2", "15", "Flow"],
                        ["Seated Rows", "3", "12", "Yellow band"],
                        ["Wall Slides", "3", "10", "Form check"],
                        ["Core Bracing", "5", "10s", "Engage TA"]
                    ]
                
                ex_data = [["Exercise / Activity", "Sets", "Reps", "Resistance / Notes"]] + exercises
                et = Table(ex_data, colWidths=[2.5*inch, 0.8*inch, 0.8*inch, 2.4*inch])
                et.setStyle(TableStyle([
                    ('BACKGROUND', (0,0), (-1,0), colors.lightgrey),
                    ('GRID', (0,0), (-1,-1), 0.5, colors.black),
                    ('FONTSIZE', (0,0), (-1,-1), 9),
                    ('PADDING', (0,0), (-1,-1), 4)
                ]))
                elements.append(et)
                elements.append(Spacer(1, 12))
                
                # Billing Section
                elements.append(Paragraph("<b>Billing / Coding:</b>", self.styles['Normal']))
                bill_data = [
                    ["CPT Code", "Description", "Time (Min)", "Units"],
                    ["97110", "Therapeutic Exercise", "15", "1"],
                    ["97112", "Neuromuscular Re-education", "15", "1"],
                    ["97140", "Manual Therapy (Myofascial Release)", "15", "1"],
                    ["", "<b>Total Time / Units</b>", "45", "3"]
                ]
                bt = Table(bill_data, colWidths=[1.1*inch, 3.2*inch, 1.1*inch, 1.1*inch])
                bt.setStyle(TableStyle([
                    ('GRID', (0,0), (-1,-1), 0.5, colors.grey),
                    ('FONTSIZE', (0,0), (-1,-1), 8),
                    ('BACKGROUND', (0,-1), (-1,-1), colors.whitesmoke)
                ]))
                elements.append(bt)
                
                elements.append(Spacer(1, 24))
                elements.append(Paragraph(f"Provider: {visit.get('provider', 'John Smith, DPT')} | NPI: 9988776655", self.styles['NormalSmall']))
                elements.append(Paragraph("Signature: ________________________________________", self.styles['NormalSmall']))
                
                if i < len(content["visits"]) - 1:
                    elements.append(PageBreak())


    def _render_pt_eval_or_progress(self, elements, content, page_count):
        # High density PT Eval/Progress note
        title = content.get("visit_type", "Physical Therapy Note")
        elements.append(Paragraph(f"<b>{title.upper()}</b>", self.styles['Header1']))
        
        sections = [
            ("History of Present Illness", content.get("subjective", "Patient presents for evaluation of chronic neck and back pain following a motor vehicle accident.")),
            ("Functional Status", "Patient reports difficulty with ADLs including dressing and grooming. Sitting tolerance limited to 20 minutes."),
            ("Physical Examination", content.get("objective", "Cervical ROM: Flexion 30 deg, Extension 20 deg. Lumbar ROM: Flexion 45 deg. Strength 4/5 in bilateral UE.")),
            ("Clinical Assessment", content.get("assessment", "Patient demonstrates significant deficits in ROM and strength consistent with cervical/lumbar strain.")),
            ("Plan of Care", content.get("plan", "Frequency: 2-3x/week for 8 weeks. Modalities: Manual therapy, therapeutic exercise, NMRE."))
        ]
        
        for i, (sec_title, sec_text) in enumerate(sections):
            elements.append(Paragraph(f"<b>{sec_title}:</b>", self.styles['Header2']))
            elements.append(Paragraph(sec_text, self.styles['Normal']))
            elements.append(Spacer(1, 12))
            
            # If we need to fill multiple pages, break here
            if page_count > 1 and i == 2:
                elements.append(PageBreak())
        
        # Add a goals table if it's an Eval
        if "Evaluation" in title:
            elements.append(Paragraph("<b>STG/LTG Goals:</b>", self.styles['Header2']))
            goal_data = [
                ["Goal Description", "Target Date", "Status"],
                ["Increase Cervical Flexion to 45 deg", "4 weeks", "Pending"],
                ["Improve Sitting Tolerance to 60 mins", "8 weeks", "Pending"],
                ["Independent with HEP", "2 weeks", "In Progress"]
            ]
            gt = Table(goal_data, colWidths=[4*inch, 1.2*inch, 1.3*inch])
            gt.setStyle(TableStyle([('GRID', (0,0), (-1,-1), 0.5, colors.black), ('FONTSIZE', (0,0), (-1,-1), 9)]))
            elements.append(gt)

    def _render_billing_content(self, elements, content, page_count):
        if "rows" in content:
            data = [["Date", "Code", "Description", "Charge", "Paid"]]
            for r in content["rows"]:
                data.append([str(r['date']), r['code'], Paragraph(r['desc'], self.styles['NormalSmall']), f"${r['charge']:.2f}", f"${r['paid']:.2f}"])
            data.append(["", "", "<b>TOTAL</b>", "", f"<b>${content['total_balance']:.2f}</b>"])
            
            t = Table(data, colWidths=[1*inch, 0.8*inch, 2.5*inch, 0.8*inch, 0.8*inch], hAlign='LEFT', repeatRows=1)
            t.setStyle(TableStyle([('GRID', (0,0), (-1,-1), 0.5, colors.grey), ('FONTSIZE', (0,0), (-1,-1), 8), ('ALIGN', (3,0), (-1,-1), 'RIGHT')]))
            elements.append(t)

    def _render_radio_content(self, elements, content, page_count):
        # Distribute sections across pages to hit target
        # Page 1: Header info
        if "modality" in content: elements.append(Paragraph(f"EXAM: {content['modality']}", self.styles['Header2']))
        if "technique" in content: elements.append(Paragraph(f"TECHNIQUE: {content['technique']}", self.styles['Normal']))
        if "comparison" in content: elements.append(Paragraph(f"COMPARISON: {content['comparison']}", self.styles['Normal']))
        
        elements.append(Spacer(1, 12))
        if page_count > 1: elements.append(PageBreak())
        
        # Findings
        if "findings" in content:
            elements.append(Paragraph("FINDINGS:", self.styles['Header2']))
            findings = content['findings']
            if isinstance(findings, dict):
                keys = list(findings.keys())
                for i, (k, v) in enumerate(findings.items()):
                    elements.append(Paragraph(f"<b>{k}:</b> {v}", self.styles['Normal']))
                    elements.append(Spacer(1, 6))
                    # Break every N items? Let's just break every 2 items if pages > 3
                    if page_count > 3 and (i + 1) % 2 == 0:
                        elements.append(PageBreak())
                        
            elif isinstance(findings, list):
                for i, f in enumerate(findings):
                    elements.append(Paragraph(f, self.styles['Normal']))
                    if page_count > 2 and i == 1: elements.append(PageBreak())

        if page_count > 2: elements.append(PageBreak())

        # Impression
        if "impression" in content:
            elements.append(Paragraph("IMPRESSION:", self.styles['Header2']))
            imp = content['impression']
            if isinstance(imp, list):
                for i in imp: elements.append(Paragraph(f"• {i}", self.styles['Normal']))

    def _render_ortho_content(self, elements, content, page_count, doc_obj: GeneratedDocument):
        # High-density Orthopedic Consultation Packet (18-25 pages)
        # We ensure every page has content by looping and adding specific elements
        
        for p in range(1, page_count + 1):
            if p == 1:
                elements.append(Paragraph("<b>ORTHOPEDIC CONSULTATION - FACE SHEET</b>", self.styles['Header1']))
                data = [
                    ["Facility:", "Bones & Joints Specialist Clinic"],
                    ["Patient Name:", "See Patient Header"],
                    ["DOB / MRN:", "See Patient Header"],
                    ["Referring Provider:", content.get('referring_provider', 'Dr. Family')],
                    ["Insurance Carrier:", content.get('insurance', 'Standard Insurance Co.')],
                    ["Claim Number:", "CLM-2025-AX-9921"],
                    ["Date of Injury:", "See Ground Truth"],
                    ["Authorization #:", "AUTH-88271-XYZ"],
                    ["Type of Case:", "Personal Injury / MVA"]
                ]
                t = Table(data, colWidths=[2.2*inch, 4.3*inch], hAlign='LEFT')
                t.setStyle(TableStyle([
                    ('GRID', (0,0), (-1,-1), 1, colors.black),
                    ('BACKGROUND', (0,0), (0,-1), colors.lightgrey),
                    ('PADDING', (0,0), (-1,-1), 8),
                    ('FONTSIZE', (0,0), (-1,-1), 10)
                ]))
                elements.append(t)
                elements.append(Spacer(1, 40))
                elements.append(Paragraph("<b>CONFIDENTIAL MEDICAL RECORD - PROTECTED HEALTH INFORMATION</b>", self.styles['Normal']))
                elements.append(Spacer(1, 20))
                elements.append(Paragraph("This document contains sensitive medical information. Disclosure is prohibited without patient consent.", self.styles['NormalSmall']))
                
            elif p in [2, 3, 4]:
                elements.append(Paragraph(f"<b>PATIENT INTAKE QUESTIONNAIRE - Page {p-1}</b>", self.styles['Header2']))
                if p == 2:
                    elements.append(Paragraph("<b>CHIEF COMPLAINT & HISTORY OF PRESENT ILLNESS:</b>", self.styles['Normal']))
                    elements.append(Paragraph("Patient describes severe, sharp, and radiating pain in the neck and lower back following a motor vehicle collision. Pain is exacerbated by rotation of the head and any lifting activities. Numbness noted in the left arm. The accident occurred approximately 6 months ago. Since then, the patient has experienced intermittent headaches and difficulty sleeping due to persistent discomfort. Previous attempts at conservative management with heat and over-the-counter NSAIDs provided only temporary relief. Patient is concerned about long-term mobility and return to work status.", self.styles['NormalSmall']))
                    elements.append(Spacer(1, 12))
                    elements.append(Paragraph("<b>PAIN DIAGRAM / SYMPTOM LOCALIZATION:</b>", self.styles['Normal']))
                    elements.append(Paragraph("Please mark the area of your pain on the diagram below. X indicates sharp pain, O indicates numbness, S indicates stiffness.", self.styles['NormalSmall']))
                    data = [["[X] Neck", "[ ] Mid Back", "[X] Low Back"], ["[X] L Arm", "[ ] R Arm", "[ ] L Leg"], ["[ ] R Leg", "[X] Headaches", "[X] Numbness"]]
                    t = Table(data, colWidths=[2*inch, 2*inch, 2*inch])
                    t.setStyle(TableStyle([('GRID', (0,0), (-1,-1), 0.5, colors.black), ('FONTSIZE', (0,0), (-1,-1), 9)]))
                    elements.append(t)
                elif p == 3:
                    elements.append(Paragraph("<b>PAST MEDICAL / SURGICAL HISTORY:</b>", self.styles['Normal']))
                    elements.append(Paragraph("No history of spinal surgeries or chronic back pain prior to the current motor vehicle accident. General health is described as good. Denies history of osteoporosis, rheumatoid arthritis, or other systemic bone disease. Past surgeries include an appendectomy and a minor knee arthroscopy several years ago, both without complications. No history of cancer or chronic respiratory issues. Patient reports no regular use of tobacco products and limited alcohol consumption.", self.styles['NormalSmall']))
                    elements.append(Spacer(1, 12))
                    elements.append(Paragraph("<b>SOCIAL HISTORY / OCCUPATIONAL REQUIREMENTS:</b>", self.styles['Normal']))
                    elements.append(Paragraph("Patient works as an office professional with significant requirements for computer use and prolonged sitting. Currently unable to perform full duties due to sitting intolerance and persistent neck pain that radiates into the upper extremities. Lives in a multi-story home, currently having difficulty with stairs and household chores. Patient is motivated to return to baseline function but is currently limited by significant pain and guarding.", self.styles['NormalSmall']))
                else:
                    elements.append(Paragraph("<b>REVIEW OF SYSTEMS (ROS):</b>", self.styles['Normal']))
                    elements.append(Paragraph("Please indicate if you have experienced any of the following symptoms in the past 30 days. All positive findings will be discussed with your provider during the examination.", self.styles['NormalSmall']))
                    data = [["Constitutional", "[X] Fatigue", "[ ] Weight Loss"], ["MSK", "[X] Joint Pain", "[X] Stiffness"], ["Neuro", "[X] Paresthesia", "[ ] Dizziness"], ["GI", "[ ] Nausea", "[ ] Changes"], ["Eyes", "[ ] Vision Blur", "[ ] Pain"]]
                    t = Table(data, colWidths=[2*inch, 1.5*inch, 1.5*inch])
                    t.setStyle(TableStyle([('GRID', (0,0), (-1,-1), 0.5, colors.grey), ('FONTSIZE', (0,0), (-1,-1), 8)]))
                    elements.append(t)
                    elements.append(Spacer(1, 12))
                    elements.append(Paragraph("Additional Comments: Patient notes increased irritability and anxiety regarding the chronicity of the symptoms and the impact on daily quality of life.", self.styles['NormalSmall']))
                
            elif p in [5, 6, 7, 8]:
                elements.append(Paragraph("<b>ORTHOPEDIC PROVIDER NOTE</b>", self.styles['Header2']))
                if p == 5:
                    hpi_text = "The patient is a pleasant individual who presents today for initial orthopedic consultation regarding injuries sustained in a motor vehicle accident. "
                    hpi_text += self.text_lib.get_ortho_hpi_segment("radicular") + " "
                    hpi_text += self.text_lib.get_ortho_hpi_segment("spasm")
                    elements.append(Paragraph("<b>HISTORY OF PRESENT ILLNESS (HPI):</b>", self.styles['Normal']))
                    elements.append(Paragraph(hpi_text, self.styles['NormalSmall']))
                elif p == 6:
                    elements.append(Paragraph("<b>PHYSICAL EXAMINATION - CERVICAL SPINE:</b>", self.styles['Normal']))
                    elements.append(Paragraph("Inspection of the cervical spine reveals no obvious deformity, but significant muscle guarding is noted in the paraspinal muscles. Range of motion is restricted in all planes due to pain and spasm.", self.styles['NormalSmall']))
                    data = [["Test / Motion", "Left Result", "Right Result"], ["Flexion", "Reduced (30 deg)", "Normal (45 deg)"], ["Extension", "Reduced (15 deg)", "Normal (40 deg)"], ["Lateral Rotation", "25 degrees", "45 degrees"], ["Spurling's Test", "POSITIVE (Radicular)", "Negative"], ["Tenderness", "C5-C7 Paravertebral", "None noted"]]
                    t = Table(data, colWidths=[2.2*inch, 2.1*inch, 2.1*inch])
                    t.setStyle(TableStyle([('GRID', (0,0), (-1,-1), 0.5, colors.black), ('FONTSIZE', (0,0), (-1,-1), 9)]))
                    elements.append(t)
                elif p == 7:
                    elements.append(Paragraph("<b>PHYSICAL EXAMINATION - NEUROLOGICAL:</b>", self.styles['Normal']))
                    elements.append(Paragraph("Neurological examination focus on upper and lower extremities to assess for focal deficits or signs of myelopathy. Manual muscle testing performed for all major muscle groups.", self.styles['NormalSmall']))
                    data = [["Reflexes / Strength", "Left Result", "Right Result"], ["C5 (Biceps)", "2+ Normal", "2+ Normal"], ["C6 (Brachiorad)", "1+ Diminished", "2+ Normal"], ["C7 (Triceps)", "2+ Normal", "2+ Normal"], ["C6 Strength (Flex)", "4/5 Weak", "5/5 Normal"], ["C7 Strength (Ext)", "5/5 Normal", "5/5 Normal"]]
                    t = Table(data, colWidths=[2.2*inch, 2.1*inch, 2.1*inch])
                    t.setStyle(TableStyle([('GRID', (0,0), (-1,-1), 0.5, colors.black), ('FONTSIZE', (0,0), (-1,-1), 9)]))
                    elements.append(t)
                else:
                    elements.append(Paragraph("<b>LUMBAR SPINE EXAMINATION:</b>", self.styles['Normal']))
                    elements.append(Paragraph("Examination of the lumbar region shows a loss of the normal lumbar lordosis, likely secondary to significant muscle spasm. Straight Leg Raise (SLR) test is positive on the left side at approximately 45 degrees, reproducing the patient's low back and leg pain. Strength in the lower extremities is 5/5 bilaterally. Sensation is intact to light touch in all dermatomes L2-S1. Gait is noted to be slightly antalgic favoring the left side. Patient is unable to perform a full squat due to low back discomfort.", self.styles['NormalSmall']))
                
            elif p in [9, 10, 11, 12]:
                elements.append(Paragraph("<b>IMAGING AND DIAGNOSTICS REVIEW</b>", self.styles['Header2']))
                elements.append(Paragraph("<b>IMAGING REVIEWED CHECKLIST / STATUS:</b>", self.styles['NormalSmall']))
                elements.append(Paragraph("[X] MRI Cervical Spine (Reviewed Disc)  [X] X-Ray Cervical (Reviewed Films)  [ ] CT Scan", self.styles['NormalSmall']))
                elements.append(Spacer(1, 12))
                if p == 9:
                    elements.append(Paragraph("<b>MRI CERVICAL SPINE FINDINGS - DETAILED REVIEW:</b>", self.styles['Normal']))
                    elements.append(Paragraph(str(content.get('mri_impression', 'MRI demonstrates broad-based disc protrusion at C5-C6 with thecal sac indentation.')), self.styles['NormalSmall']))
                    elements.append(Paragraph("The MRI shows significant disc material extending into the neural foramen on the left side at the C5-C6 level. This directly correlates with the patient's report of numbness in the thumb and index finger and the diminished brachioradialis reflex noted during the physical examination. There is no evidence of spinal cord signal abnormality at this time.", self.styles['NormalSmall']))
                elif p == 10:
                    elements.append(Paragraph("<b>X-RAY REPORT CORRELATION AND ANALYSIS:</b>", self.styles['Normal']))
                    elements.append(Paragraph("Radiographic images of the cervical and lumbar spine were reviewed in the office today. Cervical films show a loss of the normal lordotic curvature, which is a common finding in the setting of acute or subacute muscle spasm. There is no evidence of acute fracture, dislocation, or spondylolisthesis. Mild degenerative changes are noted at the L4-L5 level which are likely pre-existing but may be exacerbated by the recent trauma.", self.styles['NormalSmall']))
                else:
                    elements.append(Paragraph("<b>CLINICAL CORRELATION AND ASSESSMENT:</b>", self.styles['Normal']))
                    elements.append(Paragraph("The objective imaging findings provide a clear anatomical basis for the patient's persistent radicular symptoms. The presence of a confirmed disc protrusion at the same level as the clinical findings (C6) suggests a high likelihood that interventional management will be necessary if conservative care continues to fail. We will monitor for any signs of progressive neurological deficit which would necessitate more urgent surgical consultation.", self.styles['NormalSmall']))
                
            elif p in [13, 14, 15]:
                elements.append(Paragraph("<b>ASSESSMENT AND TREATMENT PLAN</b>", self.styles['Header2']))
                elements.append(Paragraph("<b>DIAGNOSTIC SUMMARY:</b>", self.styles['Normal']))
                elements.append(Paragraph("1. Cervical Disc Displacement (ICD-10 M50.20) with Radiculopathy (M54.12)", self.styles['NormalSmall']))
                elements.append(Paragraph("2. Lumbar Intervertebral Disc Displacement (M51.26) without Myelopathy", self.styles['NormalSmall']))
                elements.append(Paragraph("3. Post-Traumatic Myofascial Pain Syndrome secondary to MVA", self.styles['NormalSmall']))
                elements.append(Spacer(1, 12))
                elements.append(Paragraph("<b>TREATMENT PLAN DISCUSSION:</b>", self.styles['Normal']))
                elements.append(Paragraph("I have spent a significant amount of time today discussing the various management options with the patient. Given the persistence of the radicular symptoms and the failure of initial conservative measures, I am recommending a Cervical Epidural Steroid Injection (ESI). The goal of this procedure is to reduce inflammation around the compressed nerve root and provide symptomatic relief. We will also continue with a structured physical therapy program focusing on stabilization and posture.", self.styles['NormalSmall']))
                elements.append(Spacer(1, 12))
                elements.append(Paragraph("<b>MEDICATION MANAGEMENT:</b>", self.styles['Normal']))
                elements.append(Paragraph("Patient is to continue Flexeril 10mg at bedtime for muscle spasm. Ibuprofen 800mg three times daily is recommended for inflammation. We discussed the importance of taking these medications as prescribed to maintain therapeutic levels and avoid rebound symptoms.", self.styles['NormalSmall']))
                
            elif p in [16, 17, 18]:
                elements.append(Paragraph("<b>WORK STATUS AND DISABILITY DOCUMENTATION</b>", self.styles['Header2']))
                elements.append(Paragraph("<b>PHYSICAL RESTRICTIONS AND LIMITATIONS:</b>", self.styles['Normal']))
                elements.append(Paragraph("The following restrictions are placed on the patient's activities both at home and at work to prevent further injury and facilitate the healing process. These restrictions will remain in place until the next follow-up appointment.", self.styles['NormalSmall']))
                data = [["Restriction Type", "Status / Limit", "Clinical Rationale"], ["Lifting / Carrying", "< 10 lbs", "Avoid spinal loading"], ["Sitting Tolerance", "15-20 min", "Prevent postural strain"], ["Overhead Reaching", "PROHIBITED", "Avoid nerve tension"], ["Driving", "Limited", "Restricted neck rotation"]]
                t = Table(data, colWidths=[1.8*inch, 1.4*inch, 3.2*inch])
                t.setStyle(TableStyle([('GRID', (0,0), (-1,-1), 0.5, colors.black), ('FONTSIZE', (0,0), (-1,-1), 8)]))
                elements.append(t)
                elements.append(Spacer(1, 24))
                elements.append(Paragraph("<b>DISABILITY RATING:</b> Patient is currently considered to have a Temporary Partial Disability. We anticipate a period of 8-12 weeks for recovery pending the outcome of the interventional procedures. Work duties should be modified to accommodate the above restrictions.", self.styles['NormalSmall']))
                
            elif p in [19, 20, 21]:
                elements.append(Paragraph("<b>PATIENT INSTRUCTIONS / ADMINISTRATIVE</b>", self.styles['Header2']))
                elements.append(Paragraph("Follow up in our clinic in approximately 4 weeks for a repeat evaluation and to assess the effectiveness of the ESI. The patient was instructed on signs of worsening neurological status, including progressive weakness or changes in bowel/bladder control, and was advised to seek immediate emergency care should these occur.", self.styles['NormalSmall']))
                elements.append(Spacer(1, 24))
                elements.append(Paragraph("<b>ENCOUNTER SUMMARY / BILLING INFORMATION:</b>", self.styles['Normal']))
                elements.append(Paragraph("The following codes represent the services provided during today's visit. This is not a bill, but a summary for your records and insurance purposes.", self.styles['NormalSmall']))
                data = [["CPT Code", "Description of Service", "Associated ICD-10"], ["99244", "Orthopedic Consultation, Level 4", "M50.20"], ["72141", "MRI Review and Interpretation", "M54.12"], ["99080", "Special Disability Report / Form", "S13.4XXA"]]
                t = Table(data, colWidths=[1.1*inch, 3.4*inch, 1.9*inch])
                t.setStyle(TableStyle([('GRID', (0,0), (-1,-1), 0.5, colors.grey), ('FONTSIZE', (0,0), (-1,-1), 8)]))
                elements.append(t)
                elements.append(Spacer(1, 48))
                elements.append(Paragraph("Physician Signature: ________________________________________________  Date: ___________", self.styles['Normal']))
                elements.append(Paragraph("Electronically Signed by: Dr. J. Bones, Board Certified Orthopedic Surgeon", self.styles['NormalSmall']))
                
            else:
                elements.append(Paragraph("<b>SUPPLEMENTAL CLINICAL RECORDS</b>", self.styles['Header2']))
                elements.append(Paragraph("Additional lab results and historic notes attached for review.", self.styles['NormalSmall']))

            if p < page_count:
                elements.append(PageBreak())

    def _render_procedure_content(self, elements, content, page_count):
        # 6-12 page structure
        # 1: Consent, 2: Timeout, 3: Vitals, 4-5: Narrative, 6+: Instructions
        
        for p in range(1, page_count + 1):
            if p == 1:
                elements.append(Paragraph("<b>INFORMED CONSENT FOR PROCEDURE</b>", self.styles['Header1']))
                elements.append(Paragraph("I, the undersigned, hereby consent to the performance of an Epidural Steroid Injection. The nature and purpose of the procedure, as well as the risks, benefits, and alternatives, have been explained to me in detail by the provider.", self.styles['Normal']))
                elements.append(Spacer(1, 12))
                elements.append(Paragraph("<b>RISKS:</b> Infection, bleeding, nerve damage, allergic reaction to medication, headache, and failure to provide relief.", self.styles['Normal']))
                elements.append(Paragraph("<b>ALTERNATIVES:</b> Continued physical therapy, medication management, and possible surgical consultation.", self.styles['Normal']))
                elements.append(Spacer(1, 48))
                elements.append(Paragraph("Signed: __________________________ (Patient)      Date: ___________", self.styles['Normal']))
                
            elif p == 2:
                elements.append(Paragraph("<b>PROCEDURAL SAFETY TIMEOUT</b>", self.styles['Header2']))
                elements.append(Paragraph("A procedural timeout was performed immediately prior to the start of the procedure.", self.styles['Normal']))
                elements.append(Spacer(1, 12))
                elements.append(Paragraph("[X] Correct Patient Identity Verified (using two identifiers).", self.styles['Normal']))
                elements.append(Paragraph("[X] Correct Site and Side Confirmed: " + content.get('details', 'N/A'), self.styles['Normal']))
                elements.append(Paragraph("[X] Correct Level Confirmed via Fluoroscopic imaging.", self.styles['Normal']))
                elements.append(Paragraph("[X] Allergies and Medications Reviewed. No contraindications.", self.styles['Normal']))
                elements.append(Spacer(1, 24))
                elements.append(Paragraph("Attending Physician: Dr. J. Spine.", self.styles['Normal']))
                
            elif p == 3:
                elements.append(Paragraph("<b>PERI-OPERATIVE VITALS MONITORING</b>", self.styles['Header2']))
                if "pre_vitals" in content:
                    v = content["pre_vitals"]
                    elements.append(Paragraph(f"<b>PRE-PROCEDURE:</b> BP {v.get('bp')} | HR {v.get('hr')} | Sat {v.get('sats')}", self.styles['Normal']))
                elements.append(Spacer(1, 24))
                if "post_vitals" in content:
                    v = content["post_vitals"]
                    elements.append(Paragraph(f"<b>POST-PROCEDURE:</b> BP {v.get('bp')} | HR {v.get('hr')} | Sat {v.get('sats')}", self.styles['Normal']))
                elements.append(Spacer(1, 24))
                elements.append(Paragraph("<b>MONITORING:</b> Patient remained hemodynamically stable throughout the procedure. No respiratory distress noted.", self.styles['Normal']))
                    
            elif p in [4, 5]:
                elements.append(Paragraph("<b>OPERATIVE NARRATIVE</b>", self.styles['Header2']))
                if "narrative" in content:
                    elements.append(Paragraph(content["narrative"], self.styles['Normal']))
                else:
                    elements.append(Paragraph("The patient was placed in the prone position. The target level was localized under fluoroscopy. The skin was prepped and draped in the usual sterile fashion. Local anesthesia was achieved.", self.styles['Normal']))
                    
                elements.append(Spacer(1, 12))
                if "medications" in content:
                    elements.append(Paragraph(f"<b>MEDICATIONS INJECTED:</b> {content['medications']}", self.styles['Normal']))
                if "complications" in content:
                    elements.append(Paragraph(f"<b>{content['complications']}</b>", self.styles['Normal']))
                if "fluoroscopy" in content:
                    elements.append(Paragraph(f"<b>GUIDANCE:</b> {content['fluoroscopy']}", self.styles['Normal']))
                
                elements.append(Spacer(1, 24))
                elements.append(Paragraph("Contrast medium demonstrated an epidural pattern. No intravascular or intrathecal uptake was observed. Needle was removed and dressing applied.", self.styles['Normal']))
                    
            else:
                elements.append(Paragraph("<b>POST-PROCEDURE DISCHARGE INSTRUCTIONS</b>", self.styles['Header2']))
                elements.append(Paragraph("1. You may resume your normal diet immediately. Do not drive or operate machinery for 24 hours.", self.styles['Normal']))
                elements.append(Paragraph("2. You may experience some localized soreness at the injection site. Apply ice for 20 minutes at a time.", self.styles['Normal']))
                elements.append(Paragraph("3. <b>NOTIFICATION CRITERIA:</b> Contact the office or go to the nearest ED if you experience: fever over 101F, severe headache that worsens when upright, or sudden bowel/bladder dysfunction.", self.styles['Normal']))
                elements.append(Spacer(1, 48))
                elements.append(Paragraph("Provider Signature: __________________  Time: ________", self.styles['Normal']))
                elements.append(Spacer(1, 12))
                elements.append(Paragraph("Verbalized understanding by patient.", self.styles['Normal']))

            if p < page_count:
                elements.append(PageBreak())
    
    def _render_noise_content(self, elements, page_count):
        # Blank pages or "Records"
        for i in range(page_count):
             elements.append(Paragraph(" ", self.styles['Normal'])) # Empty content trigger
             if i < page_count - 1:
                 elements.append(PageBreak())

    def _render_generic_content(self, elements, content, page_count):
        if isinstance(content, dict):
            for k, v in content.items():
                if k == "title": elements.append(Paragraph(str(v), self.styles['Header2'])); continue
                elements.append(Paragraph(f"<b>{k.replace('_', ' ').title()}:</b> {v}", self.styles['NormalSmall']))
                elements.append(Spacer(1, 6))
