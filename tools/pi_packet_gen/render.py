import os
import random
from reportlab.lib.pagesizes import letter
from reportlab.lib import colors
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import inch
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, PageBreak, Frame, PageTemplate
from reportlab.lib.enums import TA_CENTER, TA_LEFT

from .schema import Case, GeneratedDocument, DocumentType

class DocumentRenderer:
    def __init__(self, output_dir: str):
        self.output_dir = output_dir
        self.styles = getSampleStyleSheet()
        self._init_custom_styles()

    def _init_custom_styles(self):
        self.styles.add(ParagraphStyle(name='Header1', parent=self.styles['Heading1'], fontSize=16, spaceAfter=12))
        self.styles.add(ParagraphStyle(name='Header2', parent=self.styles['Heading2'], fontSize=14, spaceBefore=12, spaceAfter=6))
        self.styles.add(ParagraphStyle(name='NormalSmall', parent=self.styles['Normal'], fontSize=9, leading=11))
        self.styles.add(ParagraphStyle(name='Mono', parent=self.styles['Normal'], fontName='Courier', fontSize=9))

    def render_case(self, case: Case):
        docs_dir = os.path.join(self.output_dir, "docs")
        os.makedirs(docs_dir, exist_ok=True)
        
        for doc in case.documents:
            filepath = os.path.join(docs_dir, doc.filename)
            self._render_document(doc, filepath, case.patient)

    def _header_footer(self, canvas, doc, patient_info, provider_info, date_info):
        canvas.saveState()
        canvas.setFont('Helvetica', 9)
        canvas.drawString(50, 750, f"{provider_info}")
        canvas.drawString(50, 740, f"Patient: {patient_info} | Date: {date_info}")
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
            self._header_footer(canvas, pdf_doc, f"{patient.name} ({patient.mrn})", doc.provider, doc.date)
            
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
            self._render_pt_content(elements, doc.content, doc.page_count)
        elif doc.doc_type == DocumentType.BILLING_LEDGER:
            self._render_billing_content(elements, doc.content, doc.page_count)
        elif doc.doc_type == DocumentType.RADIOLOGY_REPORT:
            self._render_radio_content(elements, doc.content, doc.page_count)
        elif doc.doc_type == DocumentType.PROCEDURE_NOTE:
            self._render_procedure_content(elements, doc.content, doc.page_count)
        elif doc.doc_type == DocumentType.ORTHO_VISIT:
            self._render_ortho_content(elements, doc.content, doc.page_count)
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

    def _render_pt_content(self, elements, content, page_count):
        if "visit_type" in content: # Eval
             self._render_generic_content(elements, content, page_count)
             return

        if "visits" in content:
            elements.append(Paragraph(content.get("type", "Daily Notes"), self.styles['Header2']))
            
            # Simple logic: 1 visit = ~0.5 page? 
            # If we want to fill pages, we can just let flow.
            # But if page_count is high and visits low, we might be short.
            # CaseGen calculates visits based on 2 pages/visit.
            # So let's force a page break every 2 visits? Or every 1 visit?
            # Let's do 1 visit per page + back side?
            
            for i, visit in enumerate(content["visits"]):
                elements.append(Paragraph(f"<b>Date: {visit['date']}</b>", self.styles['Normal']))
                cpt_str = ", ".join(visit.get('cpt', []))
                txt = f"S: {visit.get('subjective', '')}<br/>O: {visit.get('objective', '')}<br/>A: {visit.get('assessment', '')}<br/>P: {visit.get('plan', '')}<br/>Billing: {cpt_str}"
                elements.append(Paragraph(txt, self.styles['NormalSmall']))
                elements.append(Spacer(1, 12))
                elements.append(Paragraph("_" * 60, self.styles['Normal']))
                elements.append(Spacer(1, 12))
                
                # Check for needed break
                # CaseGen logic was: chunk_pages = len(chunk) * 2. So 1 visit = 2 pages? 
                # That's a lot of whitespace. Maybe 1 visit per page.
                elements.append(PageBreak())

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

    def _render_ortho_content(self, elements, content, page_count):
        # 18-page structured packet
        # Pages: 
        # 1: Face Sheet, 2-4: Intake, 5-7: Provider Note, 8-10: Imaging, 
        # 11-12: Plan, 13-15: Work Status, 16-18: Instructions/Admin
        
        for p in range(1, page_count + 1):
            if p == 1:
                elements.append(Paragraph("<b>ORTHOPEDIC CONSULTATION - FACE SHEET</b>", self.styles['Header1']))
                data = [
                    ["Patient Name:", "See Global Header"],
                    ["Referring Provider:", content.get('referring_provider', 'N/A')],
                    ["Insurance Carrier:", content.get('insurance', 'N/A')],
                    ["Policy Number:", "GZ-192837465-01"],
                    ["Claim Number:", "CLM-2025-X092"],
                    ["Date of Injury:", "See Ground Truth"],
                    ["Status:", "New Patient Consultation"]
                ]
                t = Table(data, colWidths=[2.5*inch, 3.5*inch], hAlign='LEFT')
                t.setStyle(TableStyle([('GRID', (0,0), (-1,-1), 1, colors.black), ('FONTSIZE', (0,0), (-1,-1), 10)]))
                elements.append(t)
                elements.append(Spacer(1, 20))
                elements.append(Paragraph("<b>CONFIDENTIAL MEDICAL RECORD</b>", self.styles['Normal']))
                
            elif p in [2, 3, 4]:
                elements.append(Paragraph(f"<b>INITIAL INTAKE QUESTIONNAIRE - Page {p-1}</b>", self.styles['Header2']))
                elements.append(Paragraph("<b>CHIEF COMPLAINT:</b> Patient reports severe neck and low back pain following a rear-end collision. Pain is sharp, constant, and increases with movement. Patient also notes numbness and tingling in the left arm (C6 distribution) and occasional weakness in the left hand.", self.styles['Normal']))
                elements.append(Spacer(1, 12))
                elements.append(Paragraph("<b>PAIN DIAGRAM / LOCALIZATION:</b>", self.styles['Normal']))
                elements.append(Paragraph("[X] Neck  [ ] Mid-Back  [X] Low-Back  [X] Left Arm  [ ] Right Arm  [ ] Left Leg  [ ] Right Leg", self.styles['Normal']))
                elements.append(Spacer(1, 12))
                elements.append(Paragraph("<b>FUNCTIONAL LIMITATIONS:</b> Patient is unable to sit for more than 15 minutes. Heavy lifting is impossible. Sleep is disturbed. Patient is currently light-headed and reporting intermittent headaches since the accident. Concentration is affected.", self.styles['Normal']))
                elements.append(Spacer(1, 12))
                elements.append(Paragraph("<b>PAST MEDICAL HISTORY:</b> Denies previous injuries to the spine. Non-smoker. No history of cancer or systemic bone disease. <b>PAST SURGICAL HISTORY:</b> Appendectomy in 2015. <b>SOCIAL HISTORY:</b> Lives with spouse. Works as an accountant, currently struggling with ergonomic setup.", self.styles['Normal']))
                elements.append(Spacer(1, 12))
                elements.append(Paragraph("<b>MEDICATIONS:</b> Ibuprofen 800mg TID, Cyclobenzaprine 10mg QHS. <b>ALLERGIES:</b> NKDA.", self.styles['Normal']))
                
            elif p in [5, 6, 7]:
                elements.append(Paragraph("<b>ORTHOPEDIC PROVIDER NOTE</b>", self.styles['Header2']))
                if p == 5:
                    elements.append(Paragraph("<b>HISTORY OF PRESENT ILLNESS:</b> The patient is a pleasant individual who presents today for evaluation of neck and back pain. The patient was a restrained driver in a vehicle that was struck from behind by another vehicle traveling at approximately 35 mph. Airbags did not deploy. The patient immediate felt a 'snap' in the neck. Over the next 24 hours, the pain progressed significantly. Management to date including ED visit and initial PT has provided minimal relief.", self.styles['Normal']))
                    elements.append(Spacer(1, 12))
                    elements.append(Paragraph("<b>REVIEW OF SYSTEMS:</b> Positive for neck pain, back pain, and paresthesias. Negative for fever, weight loss, or bowel/bladder dysfunction. No visual changes or dizziness.", self.styles['Normal']))
                elif p == 6:
                    elements.append(Paragraph("<b>PHYSICAL EXAMINATION:</b>", self.styles['Header2']))
                    elements.append(Paragraph("<b>GENERAL:</b> Alert and oriented x3. Appears in mild distress when moving from sitting to standing.", self.styles['Normal']))
                    elements.append(Paragraph("<b>CERVICAL SPINE:</b> Decreased range of motion in all planes. Tenderness over the C5-C7 paraspinal muscles. <b>Spurling's Test:</b> Positive on the left, reproducing radicular symptoms into the C6 dermatome.", self.styles['Normal']))
                    elements.append(Paragraph("<b>LUMBAR SPINE:</b> Midline tenderness at L4-S1. Positive straight leg raise on the left at 45 degrees. Decreased flexion/extension due to pain.", self.styles['Normal']))
                    elements.append(Paragraph("<b>NEUROLOGICAL:</b> Strength is 5/5 in bilateral UE/LE except for slight 4+/5 weakness in left elbow flexion. Reflexes are 2+ and symmetric. Sensation is decreased to light touch in the left C6 distribution.", self.styles['Normal']))
                elif p == 7:
                    elements.append(Paragraph("<b>CLINICAL ASSESSMENT / IMPRESSION:</b>", self.styles['Header2']))
                    elements.append(Paragraph("1. Cervical Disc Displacement (M50.20) with Radiculopathy (M54.12).", self.styles['Normal']))
                    elements.append(Paragraph("2. Lumbar Disc Displacement (M51.26) with Sciatica.", self.styles['Normal']))
                    elements.append(Paragraph("3. Myofascial Pain Syndrome secondary to MVA trauma.", self.styles['Normal']))
                    elements.append(Spacer(1, 12))
                    elements.append(Paragraph("The clinical presentation is highly suggestive of a significant cervical disc injury with exiting nerve root compression, likely at the C5-C6 level. Lumbar spine is also symptomatic.", self.styles['Normal']))
                    
            elif p in [8, 9, 10]:
                elements.append(Paragraph("<b>IMAGING AND DIAGNOSTICS REVIEW</b>", self.styles['Header2']))
                if "mri_impression" in content:
                    elements.append(Paragraph(f"<b>MRI CERVICAL SPINE FINDINGS:</b>", self.styles['Normal']))
                    elements.append(Paragraph(str(content['mri_impression']), self.styles['Normal']))
                else:
                    elements.append(Paragraph("The MRI of the cervical spine was reviewed in detail. It demonstrates a broad-based disc protrusion at C5-C6 that contacts the spinal cord and narrows the neural foramen. This correlates with the patient's left-sided symptoms and positive Spurling's test.", self.styles['Normal']))
                elements.append(Spacer(1, 12))
                elements.append(Paragraph("<b>X-RAY REVIEW:</b> Initial X-rays from the ED show straightening of the cervical lordosis which indicates significant muscle spasm. No acute fractures are identified.", self.styles['Normal']))
                    
            elif p in [11, 12]:
                elements.append(Paragraph("<b>TREATMENT PLAN & DISCUSSION</b>", self.styles['Header2']))
                elements.append(Paragraph("We discussed several management options today including conservative care, interventional procedures, and surgical intervention. Given the failure of initial conservative measures and the presence of radicular symptoms, I recommend a Cervical Epidural Steroid Injection (ESI) for both diagnostic and therapeutic purposes.", self.styles['Normal']))
                elements.append(Spacer(1, 12))
                elements.append(Paragraph("<b>RISKS AND BENEFITS:</b> We discussed risks of ESI including infection, bleeding, nerve damage, and dural puncture. Benefits include potential reduction in inflammation and pain relief. Patient understands and wishes to proceed.", self.styles['Normal']))
                elements.append(Paragraph("<b>SURGERY:</b> Surgery is not indicated at this exact moment but remains an option if interventional care fails or if neurological deficits worsen.", self.styles['Normal']))
                
            elif p in [13, 14, 15]:
                elements.append(Paragraph("<b>WORK STATUS AND DISABILITY REPORT</b>", self.styles['Header2']))
                elements.append(Paragraph("<b>PATIENT STATUS:</b> Modified Duty / Light Duty Restricted.", self.styles['Normal']))
                elements.append(Spacer(1, 12))
                elements.append(Paragraph("<b>PHYSICAL RESTRICTIONS:</b>", self.styles['Normal']))
                elements.append(Paragraph("- No lifting, pushing, or pulling over 10 lbs.", self.styles['Normal']))
                elements.append(Paragraph("- No overhead reaching or frequent bending.", self.styles['Normal']))
                elements.append(Paragraph("- Avoid prolonged sitting or standing (allow for stretching every 30 minutes).", self.styles['Normal']))
                elements.append(Paragraph("- No operating heavy machinery while taking muscle relaxants.", self.styles['Normal']))
                elements.append(Spacer(1, 24))
                elements.append(Paragraph("<b>DISABILITY STATUS:</b> [X] Temporary Partial Disability. [ ] Temporary Total Disability. Estimated duration: 6-8 weeks pending treatment response.", self.styles['Normal']))
                
            elif p in [16, 17, 18]:
                elements.append(Paragraph("<b>ADMINISTRATIVE / PATIENT INSTRUCTIONS</b>", self.styles['Header2']))
                elements.append(Paragraph("<b>ICD-10 DIAGNOSIS CODES:</b> M54.2 (Cervicalgia), M54.16 (Radiculopathy, lumbar), S13.4XXA (Cervical strain).", self.styles['Normal']))
                elements.append(Paragraph("<b>PROCEDURE CODES (CPT):</b> 99244 (Level 4 Consultation), 72141 (MRI review).", self.styles['Normal']))
                elements.append(Spacer(1, 24))
                elements.append(Paragraph("<b>PATIENT ATTESTATION:</b> I have reviewed my plan and agree with the course of action outlined above. All my questions have been answered to my satisfaction.", self.styles['Normal']))
                elements.append(Spacer(1, 48))
                elements.append(Paragraph("Patient Signature: __________________________  Date: ___________", self.styles['Normal']))
                elements.append(Spacer(1, 24))
                elements.append(Paragraph("Physician Signature: _________________________  Date: ___________", self.styles['Normal']))
                
            else:
                 elements.append(Paragraph("Attached Supplemental Records and Notes", self.styles['Normal']))

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
