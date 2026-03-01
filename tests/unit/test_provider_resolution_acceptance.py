from scripts.verify_litigation_export_acceptance import _check_provider_resolution_quality
from scripts.verify_litigation_export_acceptance import _check_pt_count_defensible, _check_pt_same_day_inflation_guard
from scripts.verify_litigation_export_acceptance import _check_g1_promotion_integrity
from scripts.verify_litigation_export_acceptance import _check_g4_provider_resolution, _check_page1_promoted_parity_guard


def test_provider_resolution_gate_review_required_for_mid_ratio() -> None:
    eg = {
        'extensions': {
            'pt_reconciliation': {'verified_pt_count': 12},
            'provider_resolution_quality': {
                'pt_ledger': {
                    'pt_ledger_rows_total': 12,
                    'pt_facility_resolved': 9,
                    'pt_provider_resolved': 8,
                    'pt_facility_resolved_ratio': 0.75,
                    'pt_provider_resolved_ratio': 0.6667,
                    'pt_provider_facility_gate': {'status': 'REVIEW_RECOMMENDED', 'reason': 'PT_FACILITY_RESOLUTION_RATIO_LT_090'},
                    'top_unresolved_examples': [],
                }
            }
        }
    }
    pdf = 'Export Status = REVIEW_RECOMMENDED\nPT visits (Verified): 12 encounters\nPT Visit Ledger'
    res = _check_provider_resolution_quality(eg, pdf)
    assert res['PASS'] is True
    assert res['gate_status'] == 'REVIEW_RECOMMENDED'


def test_provider_resolution_gate_blocked_for_low_ratio() -> None:
    eg = {
        'extensions': {
            'pt_reconciliation': {'verified_pt_count': 14},
            'provider_resolution_quality': {
                'pt_ledger': {
                    'pt_ledger_rows_total': 14,
                    'pt_facility_resolved': 4,
                    'pt_provider_resolved': 4,
                    'pt_facility_resolved_ratio': 0.2857,
                    'pt_provider_resolved_ratio': 0.2857,
                    'pt_provider_facility_gate': {'status': 'BLOCKED', 'reason': 'PT_FACILITY_RESOLUTION_RATIO_LT_050'},
                    'top_unresolved_examples': [{'page_number': 10}],
                }
            }
        }
    }
    pdf = 'Export Status = BLOCKED\nPT visits (Verified): 14 encounters\nPT Visit Ledger'
    res = _check_provider_resolution_quality(eg, pdf)
    assert res['PASS'] is True
    assert res['gate_status'] == 'BLOCKED'


def test_pt_same_day_inflation_guard_requires_visible_warning_when_triggered() -> None:
    eg = {
        'extensions': {
            'pt_reconciliation': {
                'verified_pt_count': 8,
                'date_concentration_anomaly': {
                    'triggered': True,
                    'max_date': '2024-10-11',
                    'max_date_count': 5,
                    'max_date_ratio': 0.625,
                }
            }
        }
    }
    pdf = 'Export Status = REVIEW_RECOMMENDED\\nPT date concentration anomaly: 2024-10-11 has 5 of 8 verified PT encounters'
    res = _check_pt_same_day_inflation_guard(eg, pdf)
    assert res['PASS'] is True
    assert res['anomaly_triggered'] is True


def test_pt_count_defensible_rejects_clinical_note_pt_encounter() -> None:
    eg = {
        'pages': [
            {'page_number': 13, 'page_type': 'clinical_note'},
        ],
        'extensions': {
            'pt_encounters': [
                {'source': 'primary', 'page_number': 13, 'encounter_date': '2024-10-11', 'evidence_citation_ids': ['c13']},
            ],
            'pt_reconciliation': {'verified_pt_count': 1},
        },
    }
    pdf = 'Export Status = REVIEW_RECOMMENDED\\nPT visits (Verified): 1 encounters\\nPT Visit Ledger'
    res = _check_pt_count_defensible(eg, pdf)
    assert res['PASS'] is False
    assert res['pt_encounter_clinical_note_rows']


def test_g1_promotion_integrity_fails_when_blocked_claim_exists() -> None:
    eg = {
        "extensions": {
            "claim_context_alignment": {
                "failures": [
                    {
                        "claim_type": "mechanism",
                        "severity": "BLOCKED",
                    }
                ]
            }
        }
    }
    pdf = "Case Snapshot\nMechanism not elevated to snapshot (context review recommended; see timeline and cited records)."
    res = _check_g1_promotion_integrity(eg, pdf)
    assert res["PASS"] is False
    assert res["outcome"] == "FAIL"


def test_g1_promotion_integrity_passes_when_no_blocked_failures() -> None:
    eg = {
        "extensions": {
            "claim_context_alignment": {
                "failures": [
                    {
                        "claim_type": "pt_claim",
                        "severity": "REVIEW_REQUIRED",
                    }
                ]
            }
        }
    }
    pdf = "Case Snapshot\nMechanism: Not documented."
    res = _check_g1_promotion_integrity(eg, pdf)
    assert res["PASS"] is True
    assert res["outcome"] == "PASS"


def test_g4_provider_resolution_fails_below_threshold() -> None:
    eg = {
        "extensions": {
            "provider_resolution_quality": {
                "rows_total": 10,
                "rows_resolved": 7,
                "resolved_ratio": 0.79,
            }
        }
    }
    res = _check_g4_provider_resolution(eg)
    assert res["PASS"] is False
    assert res["outcome"] == "FAIL"


def test_g4_provider_resolution_passes_at_threshold() -> None:
    eg = {
        "extensions": {
            "provider_resolution_quality": {
                "rows_total": 10,
                "rows_resolved": 8,
                "resolved_ratio": 0.80,
            }
        }
    }
    res = _check_g4_provider_resolution(eg)
    assert res["PASS"] is True
    assert res["outcome"] == "PASS"


def test_page1_promoted_parity_guard_fails_on_invariant_flag() -> None:
    eg = {
        "extensions": {
            "sprint4d_invariants": {
                "PAGE1_PROMOTED_PARITY_FAILURE": True,
                "page1_promoted_considered": 8,
                "page1_promoted_rendered": 0,
                "page1_promoted_fallback_used": False,
            }
        }
    }
    res = _check_page1_promoted_parity_guard(eg)
    assert res["PASS"] is False
    assert res["outcome"] == "FAIL"
