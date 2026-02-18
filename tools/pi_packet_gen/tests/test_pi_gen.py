import os
import shutil
import pytest
import sys
import json
from datetime import date
from pypdf import PdfReader

# Add project root to path if needed (though pytest usually handles it)
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '../../..')))

from tools.pi_packet_gen.schema import PacketConfig, Archetype, DocumentType
from tools.pi_packet_gen.casegen import CaseGenerator
from tools.pi_packet_gen.render import DocumentRenderer
from tools.pi_packet_gen.merge import PacketMerger
from tools.pi_packet_gen.messify import Messifier

OUTPUT_DIR = "test_output_pi_gen"

@pytest.fixture
def clean_output():
    if os.path.exists(OUTPUT_DIR):
        shutil.rmtree(OUTPUT_DIR)
    os.makedirs(OUTPUT_DIR)
    yield
    # shutil.rmtree(OUTPUT_DIR) # Keep for inspection if needed

def test_config_initialization():
    config = PacketConfig(archetype=Archetype.SOFT_TISSUE, seed=123, target_pages=10, noise_level="none")
    assert config.seed == 123
    assert config.archetype == Archetype.SOFT_TISSUE

def test_end_to_end_generation(clean_output):
    """Test full pipeline: Case -> Render -> Merge -> Messify"""
    config = PacketConfig(
        archetype=Archetype.HERNIATION,
        target_pages=20,
        noise_level="light",
        seed=12345
    )
    
    # 1. Case Gen
    print("Generating case...")
    gen = CaseGenerator(config)
    case = gen.generate()
    
    assert case.patient.name is not None
    assert len(case.documents) > 0
    
    # Check Ground Truth Population
    gt = case.ground_truth
    assert len(gt["key_events"]) > 0
    assert len(gt["diagnoses"]) > 0, "Diagnoses should be populated"
    assert len(gt["med_changes"]) > 0, "Med changes should be populated"
    assert len(gt["imaging"]) > 0, "Imaging should be populated for Herniation"
    
    # 2. Render
    print("Rendering...")
    renderer = DocumentRenderer(OUTPUT_DIR)
    renderer.render_case(case)
    
    docs_dir = os.path.join(OUTPUT_DIR, "docs")
    assert os.path.exists(docs_dir)
    num_docs = len(os.listdir(docs_dir))
    assert num_docs == len(case.documents)
    
    # Check PDF Content (basic check)
    mri_files = [f for f in os.listdir(docs_dir) if "Imaging" in f or "MRI" in f]
    assert len(mri_files) > 0, "Expected at least one Imaging report"
    
    # Verify content in first MRI file
    reader = PdfReader(os.path.join(docs_dir, mri_files[0]))
    text = ""
    for page in reader.pages:
        text += page.extract_text()
    assert "IMPRESSION:" in text or "FINDINGS:" in text, "Imaging report missing standard sections"

    # 3. Messify (Per Document)
    print("Messifying...")
    messy = Messifier("light", seed=12345)
    for doc in case.documents:
        filepath = os.path.join(docs_dir, doc.filename)
        messy.messify_document(filepath, doc.date)
        
    # Check if file still valid PDF
    reader = PdfReader(os.path.join(docs_dir, case.documents[0].filename))
    assert len(reader.pages) > 0

    # 4. Merge
    print("Merging...")
    merger = PacketMerger(OUTPUT_DIR)
    merger.merge(case)
    
    packet_path = os.path.join(OUTPUT_DIR, "packet.pdf")
    assert os.path.exists(packet_path)
    
    # Verify index
    index_path = os.path.join(OUTPUT_DIR, "packet_index.json")
    assert os.path.exists(index_path)
    with open(index_path, "r") as f:
        index = json.load(f)
    assert len(index) == len(case.documents)


def test_determinism():
    """Verify seed produces identical output"""
    config = PacketConfig(archetype=Archetype.SOFT_TISSUE, seed=999, target_pages=10, noise_level="none")
    
    gen1 = CaseGenerator(config)
    case1 = gen1.generate()
    
    gen2 = CaseGenerator(config)
    case2 = gen2.generate()
    
    assert case1.case_id == case2.case_id
    assert case1.patient.model_dump() == case2.patient.model_dump()
    assert len(case1.documents) == len(case2.documents)
    
    # Deep compare ground truth
    assert json.dumps(case1.ground_truth, sort_keys=True) == json.dumps(case2.ground_truth, sort_keys=True)

def test_ground_truth_structure_surgical():
    """Verify specific ground truth fields are populated for Surgical archetype"""
    config = PacketConfig(archetype=Archetype.SURGICAL, seed=42, target_pages=50, noise_level="none")
    gen = CaseGenerator(config)
    case = gen.generate()
    
    gt = case.ground_truth
    
    # Check Procedures
    procedures = [p['name'] for p in gt.get('procedures', [])]
    assert any("ACDF" in p or "Laminectomy" in p for p in procedures)
    
    # Check Imaging Impression
    imaging = gt.get('imaging', [])
    assert len(imaging) > 0
    assert any("Large" in img.get('impression_contains', [])[0] or "extrusion" in str(img) for img in imaging)

def test_billing_ledger(clean_output):
    """Verify Billing Ledger generation"""
    config = PacketConfig(archetype=Archetype.SOFT_TISSUE, seed=101, target_pages=20, noise_level="none")
    gen = CaseGenerator(config)
    case = gen.generate()
    
    # Ledger should be last doc
    assert case.documents[-1].doc_type == DocumentType.BILLING_LEDGER
    ledger = case.documents[-1]
    
    # Check content
    content = ledger.content
    assert "rows" in content
    assert "total_balance" in content
    assert len(content["rows"]) > 0

def test_litigation_grade_features():
    """Verify new realism features: ESI, Discharge Summary, Work Status, Contradictions"""
    config = PacketConfig(archetype=Archetype.HERNIATION, seed=555, target_pages=30, noise_level="none")
    gen = CaseGenerator(config)
    case = gen.generate()
    
    docs = case.documents
    gt = case.ground_truth
    
    # 1. Check for ESI Procedure Note
    esi_docs = [d for d in docs if d.doc_type == DocumentType.PROCEDURE_NOTE]
    assert len(esi_docs) > 0, "ESI Procedure Note missing for Herniation case"
    assert "Epidural Steroid Injection" in esi_docs[0].content['procedure']
    
    # 2. Check for PT Discharge Summary
    discharge_docs = [d for d in docs if d.doc_type == DocumentType.DISCHARGE_SUMMARY]
    assert len(discharge_docs) > 0, "PT Discharge Summary missing"
    
    # 3. Check for Work Status in PCP
    pcp_docs = [d for d in docs if "PCP" in d.filename]
    assert len(pcp_docs) > 0
    assert "Modified duty" in pcp_docs[0].content['plan'], "Work status missing from PCP plan"
    
    # 4. Check for Pre-Accident Contradiction
    ed_docs = [d for d in docs if d.doc_type == DocumentType.ED_NOTES]
    assert len(ed_docs) > 0
    assert "Patient denies prior neck pain" in ed_docs[0].content['hpi'], "Denial of prior history missing from ED Note"
    
    prior_docs = [d for d in docs if d.doc_type == DocumentType.PRIOR_RECORDS]
    assert len(prior_docs) > 0
    assert "intermittent neck stiffness" in prior_docs[0].content['note'], "Prior history content missing"

    # 5. Check Imaging Splits
    xr_docs = [d for d in docs if "XR" in d.filename]
    mri_docs = [d for d in docs if "MRI" in d.filename]
    assert len(xr_docs) >= 2, "Should have separated XR reports"
    assert len(mri_docs) >= 1, "Should have MRI report"
    assert isinstance(mri_docs[0].content['findings'], dict), "MRI findings should be dict"

def test_messifier_mixed_mode():
    """Test that Messifier handles 'mixed' mode and modifies a PDF."""
    from tools.pi_packet_gen.messify import Messifier
    from reportlab.pdfgen import canvas
    from reportlab.lib.pagesizes import letter

    # 1. Create dummy PDF
    dummy_path = "test_doc.pdf"
    c = canvas.Canvas(dummy_path, pagesize=letter)
    c.drawString(100, 750, "Hello World")
    c.save()
    
    try:
        # 2. Run Messifier
        messy = Messifier(noise_level="mixed", seed=123)
        messy.messify_document(dummy_path, date.today())
        
        # 3. Verify
        assert os.path.exists(dummy_path)
        reader = PdfReader(dummy_path)
        assert len(reader.pages) == 1
        # We can't easily check visual changes, but valid PDF read is good.
        
    finally:
        if os.path.exists(dummy_path):
            os.remove(dummy_path)
def test_subpoena_realism_ortho_procedure(clean_output):
    """Verify Ortho and Procedure documents meet subpoena-grade volume and content requirements (Part 27)."""
    config = PacketConfig(archetype=Archetype.HERNIATION, seed=42, target_pages=200, noise_level="none")
    gen = CaseGenerator(config)
    case = gen.generate()
    
    renderer = DocumentRenderer(OUTPUT_DIR)
    renderer.render_case(case)
    
    docs_dir = os.path.join(OUTPUT_DIR, "docs")
    
    # 1. Ortho Content Test
    ortho_files = [f for f in os.listdir(docs_dir) if "Ortho" in f]
    assert len(ortho_files) > 0
    reader = PdfReader(os.path.join(docs_dir, ortho_files[0]))
    # Assert volume: at least 10 pages contain >300 chars of clinical content
    contentful_pages = 0
    for i in range(1, len(reader.pages)): # Skip page 1 (cover)
        text = reader.pages[i].extract_text()
        if len(text.strip()) > 300:
            contentful_pages += 1
    assert contentful_pages >= 10, f"Ortho doc missing contentful pages. Found only {contentful_pages}."

    # 2. Procedure Content Test
    proc_files = [f for f in os.listdir(docs_dir) if "Procedure" in f]
    assert len(proc_files) > 0
    reader = PdfReader(os.path.join(docs_dir, proc_files[0]))
    full_text = "".join([p.extract_text() for p in reader.pages])
    required_strings = ["Depo-Medrol", "lidocaine", "fluoroscopy", "Complications: None"]
    for s in required_strings:
        assert s in full_text, f"Procedure doc missing required string: {s}"

def test_gap_truth_accuracy():
    """Verify ground_truth.treatment_gaps is populated (Part 27)."""
    config = PacketConfig(archetype=Archetype.HERNIATION, seed=42, target_pages=300, noise_level="none")
    gen = CaseGenerator(config)
    case = gen.generate()
    gt = case.ground_truth
    
    # Herniation with 300 pages should have a gap if the i == num_visits // 2 logic triggered
    assert len(gt["treatment_gaps"]) > 0, "No treatment gaps found in ground truth for 300-page Herniation case"
    assert any(g['days'] >= 30 for g in gt["treatment_gaps"]), "Expected at least one gap >= 30 days"

def test_noise_date_labels(clean_output):
    """Verify Noise documents have 'FAXED: ' labels in index (Part 27)."""
    config = PacketConfig(archetype=Archetype.HERNIATION, seed=42, target_pages=100, noise_level="mixed")
    gen = CaseGenerator(config)
    case = gen.generate()
    
    renderer = DocumentRenderer(OUTPUT_DIR)
    renderer.render_case(case)
    
    merger = PacketMerger(OUTPUT_DIR)
    merger.merge(case)
    
    index_path = os.path.join(OUTPUT_DIR, "packet_index.json")
    with open(index_path, "r") as f:
        index = json.load(f)
        
    noise_entries = [e for e in index if e['doc_type'] == "Packet Noise"]
    assert len(noise_entries) > 0
    for e in noise_entries:
        assert e['date'].startswith("FAXED: "), f"Noise date missing FAXED label: {e['date']}"
