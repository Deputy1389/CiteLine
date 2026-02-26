from scripts.verify_litigation_export_acceptance import _check_provider_resolution_quality


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
