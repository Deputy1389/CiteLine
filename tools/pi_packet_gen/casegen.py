import random
import uuid
from datetime import date, timedelta, datetime
from typing import List, Tuple, Dict, Any
from faker import Faker

from .schema import (
    Case, PacketConfig, Person, Archetype, Gender, 
    GeneratedDocument, DocumentType, Anomaly, AnomalyType, TextAnchor
)
from .page_budget import allocate_pages
from .text_lib import TextLibrary

class CaseGenerator:
    def __init__(self, config: PacketConfig):
        self.config = config
        self.rnd = random.Random(config.seed)
        Faker.seed(config.seed)
        self.fake = Faker()
        self.text_lib = TextLibrary(config.seed)
        
    def generate(self) -> Case:
        gender = self.rnd.choice([Gender.MALE, Gender.FEMALE])
        if gender == Gender.MALE:
            name = self.fake.name_male()
        else:
            name = self.fake.name_female()

        dob = self.fake.date_of_birth(minimum_age=18, maximum_age=80)
        
        patient = Person(
            name=name,
            gender=gender,
            dob=dob,
            mrn=f"MRN{self.rnd.randint(100000, 999999)}",
            address=self.fake.address().replace("\n", ", ")
        )
        
        # Incident 6-18 months ago
        days_ago = self.rnd.randint(180, 540)
        incident_date = date.today() - timedelta(days=days_ago)
        
        case_id = str(uuid.UUID(int=self.rnd.getrandbits(128)))
        
        case = Case(
            case_id=case_id,
            seed=self.config.seed,
            config=self.config,
            patient=patient,
            incident_date=incident_date,
            incident_description="Motor Vehicle Accident - Rear ended while stopped at red light."
        )
        
        # Allocate Pages
        budget = allocate_pages(
            self.config.archetype, 
            self.config.target_pages, 
            self.config.noise_level, 
            self.rnd
        )
        print(f"Page Budget: {budget}")
        
        self._generate_storyline(case, budget)
        self._generate_anomaly_plan(case)
        return case

    def _generate_anomaly_plan(self, case: Case):
        level = self.config.anomalies_level
        if level == "none":
            return
            
        count = self.rnd.randint(1, 3) if level == "light" else self.rnd.randint(4, 8)
        
        # 1. Wrong Patient Info
        if count > 0:
            doc = self.rnd.choice(case.documents)
            incorrect_name = case.patient.name + "s" if self.rnd.random() > 0.5 else case.patient.name[:-1]
            anomaly = Anomaly(
                type=AnomalyType.WRONG_PATIENT_INFO,
                doc_type=doc.doc_type.value,
                page_in_doc=self.rnd.randint(1, doc.page_count),
                details={
                    "expected_name": case.patient.name,
                    "incorrect_name": incorrect_name
                }
            )
            doc.anomalies.append(anomaly)
            case.anomalies.append(anomaly)
            count -= 1

        # 2. Conflicting Date
        if count > 0:
            pt_docs = [d for d in case.documents if d.doc_type == DocumentType.PT_RECORDS and "Daily" in d.filename]
            if pt_docs:
                doc = self.rnd.choice(pt_docs)
                incorrect_date = doc.date - timedelta(days=2)
                anomaly = Anomaly(
                    type=AnomalyType.CONFLICTING_DATE,
                    doc_type=doc.doc_type.value,
                    page_in_doc=1,
                    details={
                        "correct_date": doc.date.isoformat(),
                        "incorrect_date": incorrect_date.isoformat()
                    }
                )
                doc.anomalies.append(anomaly)
                case.anomalies.append(anomaly)
                count -= 1
        
        # 3. Occlusion (Handled in Messifier, but planned here)
        while count > 0:
            doc = self.rnd.choice(case.documents)
            anomaly = Anomaly(
                type=AnomalyType.OCCLUSION,
                doc_type=doc.doc_type.value,
                page_in_doc=self.rnd.randint(1, doc.page_count),
                details={"overlap_type": self.rnd.choice(["FAX_HEADER", "STAMP_RECEIVED"])}
            )
            doc.anomalies.append(anomaly)
            case.anomalies.append(anomaly)
            count -= 1

        case.ground_truth["anomalies"] = [a.model_dump(mode='json') for a in case.anomalies]

    def _generate_storyline(self, case: Case, budget: Dict[str, int]):
        documents = []
        gt = {
            "case_id": case.case_id,
            "seed": case.seed,
            "archetype": case.config.archetype.value,
            "patient": case.patient.model_dump(mode='json'),
            "incident": {
                "date": case.incident_date.isoformat(),
                "type": "MVA",
                "mechanism": case.incident_description
            },
            "key_events": [],
            "diagnoses": [],
            "imaging": [],
            "procedures": [],
            "med_changes": [],
            "work_status": [],
            "treatment_gaps": [],
            "prior_history_flags": [],
            "expected_text_anchors": [],
            "critical_pages": []
        }
        
        # 1. ED Visit (Day 0)
        if budget.get("ed_visit", 0) > 0:
            ed_doc = self._create_ed_visit(case.incident_date, case.patient, budget["ed_visit"])
            documents.append(ed_doc)
            gt["key_events"].append({
                "id": f"evt_ed_{ed_doc.date}",
                "type": "ED Visit",
                "date": ed_doc.date.isoformat(),
                "expected_in_top10": True,
                "notes": "Initial ED presentation for neck/back pain. X-Rays negative."
            })
            gt["diagnoses"].extend([
                {"date": ed_doc.date.isoformat(), "source": "ED Notes", "code": "S13.4XXA", "description": "Cervical Strain"},
                {"date": ed_doc.date.isoformat(), "source": "ED Notes", "code": "S33.5XXA", "description": "Lumbar Strain"}
            ])
            gt["med_changes"].extend([
                {"date": ed_doc.date.isoformat(), "type": "START", "medication": "Flexeril 10mg", "reason": "Muscle Spasm"},
                {"date": ed_doc.date.isoformat(), "type": "START", "medication": "Ibuprofen 800mg", "reason": "Pain"}
            ])
        
        # 1b. ED Imaging (X-Rays) - Same day
        if budget.get("xr_c", 0) > 0:
            xr_c = self._create_xr_report(case.incident_date, case.patient, "Cervical Spine", case.config.archetype, budget["xr_c"])
            documents.append(xr_c)
            gt["imaging"].append({"modality": "XR Cervical Spine", "date": case.incident_date.isoformat(), "impression_contains": xr_c.content['impression']})

        if budget.get("xr_l", 0) > 0:
            xr_l = self._create_xr_report(case.incident_date, case.patient, "Lumbar Spine", case.config.archetype, budget["xr_l"])
            documents.append(xr_l)
            gt["imaging"].append({"modality": "XR Lumbar Spine", "date": case.incident_date.isoformat(), "impression_contains": xr_l.content['impression']})

        # 2. PCP Follow-up (Day 3-7)
        pcp_date = case.incident_date + timedelta(days=self.rnd.randint(3, 7))
        if budget.get("pcp_visit", 0) > 0:
            pcp_doc = self._create_pcp_visit(pcp_date, case.patient, budget["pcp_visit"])
            documents.append(pcp_doc)
            gt["key_events"].append({
                "id": f"evt_pcp_{pcp_date}",
                "type": "PCP Visit",
                "date": pcp_date.isoformat(),
                "expected_in_top10": False,
                "notes": "PCP referral to PT/Ortho. Work status note."
            })
            gt["work_status"].append({
                "date": pcp_date.isoformat(),
                "status": "Modified Duty: No lifting > 10lbs."
            })
        
        # 3. PT Course
        pt_start = pcp_date + timedelta(days=self.rnd.randint(3, 7))
        pt_docs, pt_events, pt_visits = self._create_pt_course(pt_start, case.patient, case.config.archetype, budget)
        documents.extend(pt_docs)
        gt["key_events"].extend(pt_events)
        
        # Detect PT gaps
        if len(pt_visits) > 1:
            pt_visits.sort()
            for i in range(len(pt_visits) - 1):
                delta = (pt_visits[i+1] - pt_visits[i]).days
                if delta > 30:
                    gt["treatment_gaps"].append({
                        "start_date": pt_visits[i].isoformat(),
                        "end_date": pt_visits[i+1].isoformat(),
                        "days": delta,
                        "notes": "Gap in PT attendance."
                    })

        # 4. MRI (Day 30-45)
        mri_docs = []
        if budget.get("mri_c", 0) > 0 and case.config.archetype in [Archetype.HERNIATION, Archetype.SURGICAL, Archetype.COMPLEX_PRIOR]:
            mri_date = case.incident_date + timedelta(days=self.rnd.randint(30, 45))
            mri_doc = self._create_mri_report(mri_date, case.patient, "Cervical Spine", case.config.archetype, budget["mri_c"])
            documents.append(mri_doc)
            mri_docs.append(mri_doc)
            
            impression_text = " ".join(mri_doc.content['impression'])
            gt["imaging"].append({
                "modality": "MRI Cervical Spine",
                "date": mri_date.isoformat(),
                "impression_contains": mri_doc.content['impression']
            })
            gt["key_events"].append({
                "id": f"evt_mri_{mri_date}",
                "type": "MRI",
                "date": mri_date.isoformat(),
                "expected_in_top10": True,
                "notes": f"MRI revealed {impression_text}"
            })

            anchor = TextAnchor(
                anchor_id="mri_impression_primary",
                doc_type="Radiology Report",
                must_contain=["IMPRESSION:"] + mri_doc.content['impression']
            )
            mri_doc.anchors.append(anchor)
            gt["expected_text_anchors"].append(anchor.model_dump())

             # Diagnosis
            if case.config.archetype == Archetype.HERNIATION:
                 gt["diagnoses"].append({"date": mri_date.isoformat(), "source": "MRI", "code": "M50.20", "description": "Cervical Disc Displacement"})

            # 5. Ortho Consult (Day 45-60)
            if budget.get("ortho_consult", 0) > 0:
                ortho_date = mri_date + timedelta(days=self.rnd.randint(7, 14))
                ortho_doc = self._create_ortho_consult(ortho_date, case.patient, case.config.archetype, impression_text, budget["ortho_consult"])
                documents.append(ortho_doc)
                gt["key_events"].append({
                    "id": f"evt_ortho_{ortho_date}",
                    "type": "Ortho Consult",
                    "date": ortho_date.isoformat(),
                    "expected_in_top10": True,
                    "notes": f"Ortho Assessment: {ortho_doc.content['assessment']}"
                })
                
                if case.config.archetype == Archetype.SURGICAL:
                    gt["procedures"].append({"name": "ACDF or Laminectomy recommended", "date": ortho_date.isoformat()})
                
                # 6. ESI Procedure
                if budget.get("procedure_esi", 0) > 0 and case.config.archetype in [Archetype.HERNIATION, Archetype.SURGICAL]:
                    esi_date = ortho_date + timedelta(days=self.rnd.randint(14, 21))
                    esi_doc = self._create_esi_procedure(esi_date, case.patient, budget["procedure_esi"])
                    documents.append(esi_doc)
                    gt["procedures"].append({"name": "Cervical ESI", "date": esi_date.isoformat(), "details": "C6-C7 Interlaminar ESI"})
                    
                    anchor = TextAnchor(
                        anchor_id="esi_procedure_core",
                        doc_type="Procedure Note",
                        must_contain=["C6-C7", "Depo-Medrol", "lidocaine", "Fluoroscopy", "Complications: None"]
                    )
                    esi_doc.anchors.append(anchor)
                    gt["expected_text_anchors"].append(anchor.model_dump())

        # 7. Prior Records
        if budget.get("prior_records", 0) > 0:
            prior_date = case.incident_date - timedelta(days=self.rnd.randint(700, 1000))
            prior_doc = self._create_prior_record(prior_date, case.patient, budget["prior_records"])
            documents.insert(0, prior_doc)
            gt["prior_history_flags"].append({"date": prior_date.isoformat(), "fact": "Prior complaints of intermittent neck stiffnes."})

        # 8. Packet Noise
        if budget.get("noise", 0) > 0:
            noise_docs = self._create_packet_noise(budget["noise"], documents)
            documents.extend(noise_docs)

        # 9. Billing Ledger (End of Packet)
        if budget.get("billing", 0) > 0:
            last_date = max([d.date for d in documents])
            billing_doc = self._create_billing_ledger(case.incident_date, last_date, case.patient, documents, budget["billing"])
            documents.append(billing_doc)

        case.documents = documents
        case.ground_truth = gt

    def _create_ed_visit(self, date_val: date, patient: Person, page_count: int) -> GeneratedDocument:
        # Generate content that SCALES with page_count
        # We need roughly 10-15 nursing notes per page, plus vitals, labs, etc.
        
        # Base content
        nursing_notes = []
        base_time = date_val
        t = datetime.combine(date_val, datetime.min.time()) + timedelta(hours=14)
        
        # Determine number of nursing entries needed to fill pages
        # Assume ~15 lines per page for Nursing flowsheet
        # We reserve ~4-5 pages for other stuff (Face sheet, Triage, MD Note, Orders, Discharge)
        # So filler pages = page_count - 5
        filler_pages = max(0, page_count - 5)
        num_entries = 5 + (filler_pages * 15)
        
        for i in range(num_entries):
             t += timedelta(minutes=self.rnd.randint(10, 30))
             note_type = self.rnd.choice(["Vitals Check", "Pain Assessment", "Rounding", "Meds Given", "Pt Request"])
             note_text = f"{note_type}: {self.fake.sentence()}"
             nursing_notes.append({"time": t.strftime("%H:%M"), "note": note_text})

        # Triage Vitals
        vitals = [
            {"time": "14:02", "bp": "138/88", "hr": "88", "rr": "16", "temp": "98.6", "sats": "99% RA", "pain": "8/10"},
            {"time": "16:45", "bp": "130/82", "hr": "76", "rr": "14", "temp": "98.7", "sats": "100% RA", "pain": "4/10"}
        ]
        
        content = {
            "triage_vitals": vitals,
            "chief_complaint": "Neck and back pain following MVC.",
            "hpi": "Patient presents via private vehicle with neck and low back pain following a rear-end MVA earlier today. Impact was significant. Patient denies prior neck pain or back issues. No LOC reported.",
            "ros": ["Const: Denies fever.", "Eyes: Normal.", "MSK: Neck pain."],
            "physical_exam": ["Gen: Alert.", "Neck: Tenderness."],
            "mdm": "History consistent with strain...",
            "orders": ["XR C-Spine", "XR L-Spine", "Toradol", "Flexeril"],
            "meds_given": [{"name": "Toradol", "dose": "30mg", "route": "IM", "time": "15:15"}],
            "discharge_meds": ["Flexeril 10mg"],
            "nursing_notes": nursing_notes,
            "instructions": "Rest, Ice, NSAIDs."
        }

        return GeneratedDocument(
            doc_type=DocumentType.ED_NOTES,
            date=date_val,
            provider="General Hospital & Trauma Center",
            page_count=page_count,
            content=content,
            filename=f"ED_Visit_{date_val}.pdf"
        )
    
    def _create_pcp_visit(self, date_val: date, patient: Person, page_count: int) -> GeneratedDocument:
        return GeneratedDocument(
            doc_type=DocumentType.MISC,
            date=date_val,
            provider="Dr. Family",
            page_count=page_count,
            content={
                "title": "Office Visit",
                "subjective": "Patient follows up for neck and back pain after MVA. Pain is 6/10.",
                "physical_exam": "Tenderness in cervical and lumbar spine. Normal gait.",
                "plan": "Referral to Physical Therapy. Modified duty: no lifting > 10 lbs. Follow up in 4 weeks.",
                "work_status": "Modified Duty: No lifting > 10lbs."
            },
            filename=f"PCP_Referral_{date_val}.pdf"
        )
        
    def _create_pt_course(self, start_date: date, patient: Person, archetype: Archetype, budget: Dict[str, int]) -> Tuple[List[GeneratedDocument], List[dict], List[date]]:
        docs = []
        events = []
        all_visits = []
        provider = "Elite Physical Therapy"
        
        # 1. Eval
        if budget.get("pt_eval", 0) > 0:
            docs.append(GeneratedDocument(
                doc_type=DocumentType.PT_RECORDS, # Or PT_EVAL
                date=start_date,
                provider=provider,
                page_count=budget["pt_eval"],
                content={"visit_type": "Initial Evaluation", "plan": "2-3x/week"},
                filename=f"PT_Eval_{start_date}.pdf"
            ))
            events.append({"id": f"evt_pt_eval_{start_date}", "type": "PT Eval", "date": start_date.isoformat(), "expected_in_top10": True})
            all_visits.append(start_date)
            
        # 2. Daily Notes
        daily_pages_target = budget.get("pt_daily", 0)
        num_visits = max(1, daily_pages_target // 2)
        
        daily_notes = []
        visit_date = start_date
        
        # State machine for progression
        current_pain = 8
        trend = "stable"
        
        for i in range(num_visits):
            visit_date += timedelta(days=self.rnd.randint(2, 4))
            # Inject gap?
            if archetype in [Archetype.HERNIATION, Archetype.SURGICAL, Archetype.COMPLEX_PRIOR] and i == num_visits // 2:
                 visit_date += timedelta(days=35) # Force gap
            
            all_visits.append(visit_date)
            
            # Update state
            if i > num_visits * 0.7:
                current_pain = max(2, current_pain - self.rnd.randint(0, 1))
                trend = "improving"
            elif i > num_visits * 0.3:
                current_pain = max(4, current_pain - self.rnd.randint(0, 1))
                trend = "stable"
            
            # Focus region based on archetype
            focus = "mixed"
            if archetype == Archetype.HERNIATION: focus = "cervical"
            
            visit_state = {
                "pain_score": current_pain,
                "trend": trend,
                "focus": focus,
                "narrative": self.text_lib.get_pt_narrative(current_pain, trend)
            }

            daily_notes.append({
                "date": visit_date,
                "provider": provider,
                "state": visit_state
            })
            
        # Batching
        if daily_notes:
            chunk_size = 10
            for i in range(0, len(daily_notes), chunk_size):
                chunk = daily_notes[i:i+chunk_size]
                first = chunk[0]['date']
                last = chunk[-1]['date']
                is_last = (i + chunk_size >= len(daily_notes))
                pages_so_far = sum(d.page_count for d in docs if d.doc_type == DocumentType.PT_RECORDS and "Eval" not in d.filename)
                
                if is_last:
                    chunk_pages = daily_pages_target - pages_so_far
                else:
                    chunk_pages = len(chunk) * 2 
                
                chunk_pages = max(1, chunk_pages)
                
                docs.append(GeneratedDocument(
                    doc_type=DocumentType.PT_RECORDS,
                    date=last,
                    provider=provider,
                    page_count=chunk_pages,
                    content={"visits": chunk, "type": "Daily Notes Log"},
                    filename=f"PT_Daily_{first}_{last}.pdf"
                ))

        # 2b. Progress Notes
        if budget.get("pt_progress", 0) > 0:
            prog_date = start_date + timedelta(days=30)
            docs.append(GeneratedDocument(
                doc_type=DocumentType.PT_RECORDS,
                date=prog_date,
                provider=provider,
                page_count=budget["pt_progress"],
                content={
                    "visit_type": "Progress Note",
                    "subjective": "Patient making good progress.",
                    "assessment": "Goals partially met.",
                    "plan": "Continue POC."
                },
                filename=f"PT_Progress_{prog_date}.pdf"
            ))

        # 3. Discharge
        if budget.get("pt_discharge", 0) > 0:
            final_date = visit_date + timedelta(days=3)
            docs.append(GeneratedDocument(
                doc_type=DocumentType.DISCHARGE_SUMMARY,
                date=final_date,
                provider=provider,
                page_count=budget["pt_discharge"],
                content={"title": "Discharge Summary", "final_pain": f"{current_pain}/10"},
                filename=f"PT_Discharge_{final_date}.pdf"
            ))
            
        return docs, events, all_visits

        # 2b. Progress Notes
        if budget.get("pt_progress", 0) > 0:
            prog_date = start_date + timedelta(days=30)
            docs.append(GeneratedDocument(
                doc_type=DocumentType.PT_RECORDS,
                date=prog_date,
                provider=provider,
                page_count=budget["pt_progress"],
                content={
                    "visit_type": "Progress Note",
                    "subjective": "Patient making good progress.",
                    "assessment": "Goals partially met.",
                    "plan": "Continue POC."
                },
                filename=f"PT_Progress_{prog_date}.pdf"
            ))

        # 3. Discharge
        if budget.get("pt_discharge", 0) > 0:
            final_date = visit_date + timedelta(days=3)
            docs.append(GeneratedDocument(
                doc_type=DocumentType.DISCHARGE_SUMMARY,
                date=final_date,
                provider=provider,
                page_count=budget["pt_discharge"],
                content={"title": "Discharge Summary", "final_pain": f"{current_pain}/10"},
                filename=f"PT_Discharge_{final_date}.pdf"
            ))
            
        return docs, events, all_visits

    def _create_xr_report(self, date_val: date, patient: Person, body_part: str, archetype: Archetype, page_count: int) -> GeneratedDocument:
        provider = "Valley Radiology"
        
        findings = []
        impression = []
        
        if "Cervical" in body_part:
            findings = [
                "Alignment: Normal cervical lordosis is maintained.",
                "Vertebral Bodies: Vertebral body heights are preserved. No acute fracture.",
                "Disc Spaces: Disc spaces are preserved.",
                "Soft Tissues: Prevertebral soft tissues are unremarkable."
            ]
            impression = ["No acute fracture or dislocation.", "No significant degenerative changes."]
            
            if archetype in [Archetype.HERNIATION, Archetype.SURGICAL]:
                findings[0] = "Straightening of the normal cervical lordosis attempting to guard against pain."
                impression = ["Straightening of cervical lordosis suggesting muscle spasm.", "No acute fracture."]

        elif "Lumbar" in body_part:
             findings = [
                "Alignment: Normal lumbar lordosis.",
                "Vertebral Bodies: Heights maintained. No fracture.",
                "Disc Spaces: Preserved.",
                "Soft Tissues: Unremarkable."
            ]
             impression = ["Unremarkable lumbar spine series.", "No fracture."]
        
        return GeneratedDocument(
            doc_type=DocumentType.RADIOLOGY_REPORT,
            date=date_val,
            provider=provider,
            page_count=page_count,
            content={
                "modality": f"XR {body_part} 3 Views",
                "technique": "Standard AP, Lateral, and Odontoid views." if "Cervical" in body_part else "Standard AP and Lateral views.",
                "comparison": "None available.",
                "findings": findings,
                "impression": impression
            },
            filename=f"Imaging_XR_{body_part.replace(' ', '_')}_{date_val}.pdf"
        )

    def _create_mri_report(self, date_val: date, patient: Person, body_part: str, archetype: Archetype, page_count: int) -> GeneratedDocument:
        provider = "Valley Radiology"
        technique = "Multiplanar T1 and T2 weighted images were obtained without contrast."
        comparison = "None."
        
        findings_dict = {} # Level by level
        impression = []
        
        if "Cervical" in body_part:
            findings_dict = {
                "C2-C3": "Normal disc signal and height. No canal stenosis.",
                "C3-C4": "Normal disc signal and height. No canal stenosis.",
                "C4-C5": "Normal disc signal and height. No canal stenosis.",
                "C5-C6": "Normal.",
                "C6-C7": "Normal.",
                "C7-T1": "Normal."
            }
             
            if archetype == Archetype.HERNIATION:
                findings_dict["C5-C6"] = "3mm broad-based posterior disc protrusion indenting the thecal sac and contacting the ventral cord."
                impression.append("C5-C6: 3mm central disc protrusion indenting thecal sac.")
                impression.append("No cord signal abnormality.")
            elif archetype == Archetype.SURGICAL:
                findings_dict["C5-C6"] = "Large 6mm left paracentral extrusion compressing the exiting C6 nerve root and deforming the cord."
                impression.append("C5-C6: Large 6mm extrusion compressing left nerve root with potential cord impingement.")
                impression.append("Surgical consultation recommended.")
            else:
                impression.append("No acute fracture or dislocation.")
                impression.append("Mild straightening of lordosis suggestive of spasm.")
                
        elif "Lumbar" in body_part:
            findings_dict = {
                "L1-L2": "Normal.",
                "L2-L3": "Normal.",
                "L3-L4": "Normal.",
                "L4-L5": "Normal.",
                "L5-S1": "Normal."
            }
            if archetype == Archetype.HERNIATION:
                 findings_dict["L4-L5"] = "Broad based bulge with mild facet hypertrophy."
                 impression.append("L4-L5: Mild degenerative changes.")
            else:
                 impression.append("Unremarkable lumbar MRI.")

        return GeneratedDocument(
            doc_type=DocumentType.RADIOLOGY_REPORT,
            date=date_val,
            provider=provider,
            page_count=page_count,
            content={
                "modality": f"MRI {body_part} Without Contrast",
                "technique": technique,
                "comparison": comparison,
                "findings": findings_dict, # Structured dict
                "impression": impression
            },
            filename=f"Imaging_MRI_{body_part.replace(' ', '_')}_{date_val}.pdf"
        )
        
    def _create_ortho_consult(self, date_val: date, patient: Person, archetype: Archetype, mri_results: str, page_count: int) -> GeneratedDocument:
        return GeneratedDocument(
            doc_type=DocumentType.ORTHO_VISIT,
            date=date_val,
            provider="Dr. Bones",
            page_count=page_count,
            content={
                "assessment": "Radiculopathy", 
                "plan": "ESI.", 
                "referring_provider": "Dr. Family",
                "insurance": "Geico",
                "mri_impression": mri_results
            },
            filename=f"Ortho_Consult_{date_val}.pdf"
        )

    def _create_esi_procedure(self, date_val: date, patient: Person, page_count: int) -> GeneratedDocument:
        location = "C6-C7 Interlaminar"
        return GeneratedDocument(
            doc_type=DocumentType.PROCEDURE_NOTE,
            date=date_val,
            provider="Spine Center",
            page_count=page_count,
            content={
                "procedure": "Epidural Steroid Injection", 
                "details": location,
                "medications": "80 mg Depo-Medrol + 1% lidocaine",
                "fluoroscopy": "Fluoroscopy was used to confirm needle placement.",
                "complications": "Complications: None",
                "narrative": f"Under fluoroscopic guidance, a 22 gauge needle was advanced to the {location} epidural space. Loss of resistance was achieved. Contrast confirmed epidural spread. 80mg Depo-Medrol and 1cc 1% lidocaine were injected.",
                "pre_vitals": {"bp": "130/80", "hr": "72", "sats": "99%"},
                "post_vitals": {"bp": "132/82", "hr": "74", "sats": "99%"}
            },
            filename=f"Procedure_ESI_{date_val}.pdf"
        )

    def _create_prior_record(self, date_val: date, patient: Person, page_count: int) -> GeneratedDocument:
        return GeneratedDocument(
            doc_type=DocumentType.PRIOR_RECORDS,
            date=date_val,
            provider="Old Chiro",
            page_count=page_count,
            content={"note": "Prior complaints of intermittent neck stiffness."},
            filename=f"Prior_Chiro_{date_val}.pdf"
        )

    def _create_billing_ledger(self, start_date: date, end_date: date, patient: Person, documents: List[GeneratedDocument], page_count: int) -> GeneratedDocument:
        # Generate enough rows to fill `page_count`. 
        # Assume 20 rows per page.
        target_rows = page_count * 20
        rows = []
        for i in range(target_rows):
            rows.append({"date": start_date, "code": "99999", "desc": "Service", "charge": 100.0, "paid": 0.0})
            
        return GeneratedDocument(
            doc_type=DocumentType.BILLING_LEDGER,
            date=end_date,
            provider="Billing Dept",
            page_count=page_count,
            content={"rows": rows, "total_balance": 5000.0},
            filename="Billing_Ledger.pdf"
        )

    def _create_packet_noise(self, page_count: int, documents: List[GeneratedDocument]) -> List[GeneratedDocument]:
        # Create multiple noise docs to scatter them
        noise_docs = []
        if not documents: return noise_docs
        
        # Split page_count into chunks
        # e.g. 1-3 pages per noise doc
        pages_left = page_count
        while pages_left > 0:
            chunk = self.rnd.randint(1, min(3, pages_left))
            pages_left -= chunk
            
            # Use FAXED dates within 0-14 days of an associated service date
            base_doc = self.rnd.choice(documents)
            noise_date = base_doc.date + timedelta(days=self.rnd.randint(0, 14))
            
            noise_docs.append(GeneratedDocument(
                doc_type=DocumentType.PACKET_NOISE,
                date=noise_date,
                provider="System",
                page_count=chunk,
                content={"type": "mixed_noise"},
                filename=f"Noise_{uuid.uuid4().hex[:6]}.pdf"
            ))
            
        return noise_docs
        
