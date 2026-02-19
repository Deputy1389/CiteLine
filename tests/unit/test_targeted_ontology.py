from apps.worker.lib.targeted_ontology import (
    canonical_disposition,
    canonical_injuries,
    canonical_procedures,
    extract_concepts,
)


def test_extract_concepts_hits_multiple_domains():
    text = "MRI impression shows C5-6 disc protrusion. Plan for epidural steroid injection with Depo-Medrol and lidocaine."
    hits = extract_concepts(text)
    domains = {h.domain for h in hits}
    assert "imaging" in domains
    assert "injury" in domains
    assert "procedure" in domains


def test_canonical_injuries_returns_specific_labels():
    facts = [
        "Assessment: cervical radiculopathy after MVC.",
        "Impression: C5-6 disc protrusion.",
    ]
    got = canonical_injuries(facts)
    assert "cervical radiculopathy" in got
    assert "disc protrusion" in got or "cervical disc protrusion" in got


def test_canonical_procedures_normalizes_esi():
    facts = ["Procedure: C6-7 interlaminar epidural steroid injection under fluoroscopy."]
    got = canonical_procedures(facts)
    assert "epidural steroid injection" in got


def test_canonical_disposition_prefers_home():
    facts = ["Disposition: discharged home with instructions."]
    assert canonical_disposition(facts) == "Home"

