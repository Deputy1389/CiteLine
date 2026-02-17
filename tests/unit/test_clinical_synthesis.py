import pytest
from datetime import date
from apps.worker.steps.events.synthesis_domain import ClinicalAtom, ClinicalEvent
from apps.worker.steps.events.clinical_clustering import cluster_atoms_into_events, SURGERY, IMAGING, FOLLOW_UP, PREOPERATIVE_NOTE
from apps.worker.steps.events.clinical_extraction import extract_concepts, canonicalize_injuries
from apps.worker.steps.events.clinical_rendering import synthesize_event_narrative
from apps.worker.steps.events.clinical_filtering import is_noise_line

def test_canonical_normalization():
    # Preferences laterality
    injuries = {"comminuted acromion fracture", "comminuted right acromion fracture"}
    canonical = canonicalize_injuries(injuries)
    assert len(canonical) == 1
    assert "comminuted right acromion fracture" in canonical

def test_event_classification_guard():
    # 2013-05-21: Imaging note mentioning ORIF should be IMAGING
    day = date(2013, 5, 21)
    atoms = [
        ClinicalAtom(date=day, text="shoulder appeared located", kind="finding", citations=[]),
        ClinicalAtom(date=day, text="ORIF stabilizing a fracture", kind="finding", citations=[]),
        ClinicalAtom(date=day, text="X-ray of the right shoulder", kind="imaging", citations=[])
    ]
    events = cluster_atoms_into_events(atoms)
    assert events[0].event_type == IMAGING

def test_strict_noise_filter():
    assert is_noise_line("records of harry potter from file.pdf_page 12") == True
    # The noise filter check in filtering.py uses NOISE_REGEXES on the trimmed text
    assert is_noise_line("s 143") == True
    assert is_noise_line("143-144") == True
    assert is_noise_line("Patient has fracture") == False

def test_concept_only_rendering():
    day = date(2013, 10, 10)
    ce = ClinicalEvent(date=day, event_type=SURGERY, title="Surg", atoms=[], citations=[])
    ce.procedures = {"open rotator cuff repair", "hardware removal, right shoulder"}
    ce.fractures = {"comminuted right acromion fracture"}
    
    narrative = synthesize_event_narrative(ce)
    # The template sorts concepts for stability
    assert "Patient underwent hardware removal, right shoulder, open rotator cuff repair" in narrative
    assert "Findings included comminuted right acromion fracture" in narrative
    # Ensure raw atom text not used
    assert "Patient was discharged with plan for follow-up and rehabilitation plan" in narrative

def test_procedure_inference():
    day = date(2013, 6, 5)
    # Simulate surgery day with findings but NO procedure name
    ce = ClinicalEvent(date=day, event_type=SURGERY, title="Surg", atoms=[], citations=[])
    ce.infections = {"wound infection"}
    
    extract_concepts(ce)
    # Guard should infer I&D from infection
    assert "Irrigation and debridement, right shoulder" in ce.procedures

def test_plan_metadata_filtering():
    day = date(2013, 10, 10)
    # Plan atom containing metadata noise
    atoms = [ClinicalAtom(date=day, text="interim lsu public hospital physician discharge summary report", kind="fact", citations=[])]
    ce = ClinicalEvent(date=day, event_type=SURGERY, title="Surg", atoms=atoms, citations=[])
    
    extract_concepts(ce)
    # Narrative synthesis should use clinical fallback instead of metadata
    narrative = synthesize_event_narrative(ce)
    assert "physician discharge summary report" not in narrative
    assert "follow-up and rehabilitation plan" in narrative

def test_incomplete_plan_filtering():
    day = date(2013, 10, 10)
    # Simulate a plan that ends in a stopword
    atoms = [ClinicalAtom(date=day, text="advised follow up in.", kind="fact", citations=[])]
    ce = ClinicalEvent(date=day, event_type=FOLLOW_UP, title="Follow-up", atoms=atoms, citations=[])
    
    extract_concepts(ce)
    # The set should be empty because the phrase was rejected
    assert len(ce.plans) == 0

def test_preoperative_note_classification():
    day = date(2013, 8, 27)
    atoms = [ClinicalAtom(date=day, text="patient requested not wanting a catheter", kind="fact", citations=[])]
    events = cluster_atoms_into_events(atoms)
    assert events[0].event_type == "PREOPERATIVE_NOTE"

def test_no_uuid_in_timeline():
    day = date(2013, 10, 10)
    ce = ClinicalEvent(date=day, event_type=IMAGING, title="Img", atoms=[], citations=[], provider="15af076d594144b1")
    
    from apps.worker.steps.events.clinical_rendering import render_timeline
    timeline = render_timeline([ce])
    # UUID should be replaced by facility name
    assert "15af076d594144b1" not in timeline
    assert "Interim LSU Public Hospital" in timeline
