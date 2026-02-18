from scripts.build_critique_packet import failure_taxonomy
from scripts.run_critic_loop import generate_fix_report


def test_failure_taxonomy_empty_for_pass_scorecard():
    scorecard = {
        "overall_pass": True,
        "forbidden_strings_found": [],
        "has_placeholder_dates": False,
        "has_uuid_provider_ids": False,
        "has_raw_fragment_dump": False,
        "has_atom_dump_marker": False,
        "has_date_not_documented_pt_visit": False,
        "has_provider_lines_in_timeline": False,
        "provider_misassignment_count": 0,
        "empty_surgery_entries": 0,
        "timeline_entry_count": 9,
    }
    assert failure_taxonomy(scorecard) == []


def test_failure_taxonomy_flags_critical_issues():
    scorecard = {
        "forbidden_strings_found": ["records of harry potter"],
        "has_placeholder_dates": True,
        "has_uuid_provider_ids": True,
        "has_raw_fragment_dump": True,
        "has_atom_dump_marker": True,
        "has_date_not_documented_pt_visit": True,
        "has_provider_lines_in_timeline": True,
        "provider_misassignment_count": 2,
        "empty_surgery_entries": 1,
        "timeline_entry_count": 99,
    }
    failures = failure_taxonomy(scorecard)
    codes = {f["code"] for f in failures}
    assert "forbidden_strings" in codes
    assert "placeholder_dates" in codes
    assert "atom_dump_leak" in codes
    assert "provider_misassignment" in codes


def test_generate_fix_report_none_when_no_failures():
    report = generate_fix_report([])
    assert report["action"] == "none"
    assert report["targets"] == []


def test_generate_fix_report_targets_expected_files():
    failures = [
        {"code": "atom_dump_leak", "hint": "x"},
        {"code": "provider_misassignment", "hint": "y"},
    ]
    report = generate_fix_report(failures)
    assert report["action"] == "manual_patch_required"
    assert "apps/worker/steps/step12_export.py" in report["targets"]
    assert "apps/worker/project/chronology.py" in report["targets"]
