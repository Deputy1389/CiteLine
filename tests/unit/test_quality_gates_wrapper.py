from apps.worker.lib.quality_gates import run_quality_gates
import apps.worker.lib.luqa as luqa_mod
import apps.worker.lib.attorney_readiness as attorney_mod


def test_quality_gates_flags_attorney_placeholder_leaks() -> None:
    report_text = "CASE SNAPSHOT\nPatient: See Patient Header\nDate of Injury: 1900-01-01\n"
    res = run_quality_gates(report_text=report_text, page_text_by_number={})
    assert res["overall_pass"] is False
    codes = {f.get("code") for f in (res.get("failures") or [])}
    assert "SEE_PATIENT_HEADER" in codes
    assert "SENTINEL_DATE_1900" in codes
    assert res["gate_report"]["placeholder_scan"]["pass"] is False


def test_quality_gates_flags_pt_count_conflict() -> None:
    report_text = (
        "Treatment Course & Compliance\n"
        "PT visits (Verified): 2 encounters\n"
        "PT visits (Reported in records): 141 encounters\n"
    )
    res = run_quality_gates(report_text=report_text, page_text_by_number={})
    assert res["overall_pass"] is False
    codes = {f.get("code") for f in (res.get("failures") or [])}
    assert "PT_COUNT_CONFLICT" in codes
    assert res["gate_report"]["pt_count_consistency"]["pass"] is False


def test_quality_gates_flags_high_volume_unverified_pt() -> None:
    report_text = "Treatment Course & Compliance\nPT visits (Reported in records): 141 encounters\n"
    res = run_quality_gates(report_text=report_text, page_text_by_number={})
    assert res["overall_pass"] is False
    codes = {f.get("code") for f in (res.get("failures") or [])}
    assert "PT_HIGH_VOLUME_UNVERIFIED" in codes
    assert res["gate_report"]["pt_count_consistency"]["pass"] is False


def test_quality_gates_flags_uncited_projection_row() -> None:
    report_text = "Medical Timeline (Litigation Ready)\n"
    projection_entries = [
        {
            "event_id": "e1",
            "event_type_display": "Emergency Visit",
            "citation_display": "",
        }
    ]
    res = run_quality_gates(report_text=report_text, page_text_by_number={}, projection_entries=projection_entries)
    assert res["overall_pass"] is False
    codes = {f.get("code") for f in (res.get("failures") or [])}
    assert "EXPORT_UNCITED_TIMELINE_ROW" in codes
    assert res["gate_report"]["export_citation_integrity"]["pass"] is False


def test_quality_gates_flags_uncited_top10_item() -> None:
    report_text = (
        "Top 10 Case-Driving Events\n"
        "- Mechanism documented without citation\n"
        "Liability Facts\n"
    )
    res = run_quality_gates(report_text=report_text, page_text_by_number={})
    assert res["overall_pass"] is False
    codes = {f.get("code") for f in (res.get("failures") or [])}
    assert "EXPORT_UNCITED_TOP10_ITEM" in codes
    assert res["gate_report"]["export_citation_integrity"]["pass"] is False


def test_quality_mode_pilot_demotes_luqa_meta_language_ban(monkeypatch) -> None:
    monkeypatch.setattr(
        luqa_mod,
        "build_luqa_report",
        lambda report_text, ctx: {
            "luqa_pass": False,
            "luqa_score_0_100": 10,
            "failures": [{"code": "LUQA_META_LANGUAGE_BAN", "message": "meta", "severity": "hard"}],
        },
    )
    monkeypatch.setattr(
        attorney_mod,
        "build_attorney_readiness_report",
        lambda report_text, ctx: {
            "attorney_ready_pass": True,
            "attorney_ready_score_0_100": 100,
            "failures": [],
        },
    )

    res = run_quality_gates(report_text="ok", page_text_by_number={}, quality_mode="pilot")
    assert res["overall_pass"] is True
    assert res["export_status"] == "REVIEW_RECOMMENDED"
    assert len(res.get("hard_failures") or []) == 0
    assert "LUQA_META_LANGUAGE_BAN" in {f.get("code") for f in (res.get("soft_failures") or [])}


def test_quality_mode_strict_keeps_luqa_meta_language_ban_hard(monkeypatch) -> None:
    monkeypatch.setattr(
        luqa_mod,
        "build_luqa_report",
        lambda report_text, ctx: {
            "luqa_pass": False,
            "luqa_score_0_100": 10,
            "failures": [{"code": "LUQA_META_LANGUAGE_BAN", "message": "meta", "severity": "hard"}],
        },
    )
    monkeypatch.setattr(
        attorney_mod,
        "build_attorney_readiness_report",
        lambda report_text, ctx: {
            "attorney_ready_pass": True,
            "attorney_ready_score_0_100": 100,
            "failures": [],
        },
    )

    res = run_quality_gates(report_text="ok", page_text_by_number={}, quality_mode="strict")
    assert res["overall_pass"] is False
    assert res["export_status"] == "BLOCKED"
    assert "LUQA_META_LANGUAGE_BAN" in {f.get("code") for f in (res.get("hard_failures") or [])}


def test_visit_bucket_quality_threshold_triggers_review_recommended(monkeypatch) -> None:
    monkeypatch.setattr(
        luqa_mod,
        "build_luqa_report",
        lambda report_text, ctx: {"luqa_pass": True, "luqa_score_0_100": 100, "failures": []},
    )
    monkeypatch.setattr(
        attorney_mod,
        "build_attorney_readiness_report",
        lambda report_text, ctx: {"attorney_ready_pass": True, "attorney_ready_score_0_100": 100, "failures": []},
    )
    res = run_quality_gates(
        report_text="ok",
        page_text_by_number={},
        visit_bucket_quality={
            "total_encounters": 8,
            "encounters_with_missing_required_buckets": 4,
            "required_bucket_miss_count": 6,
            "missing_required_bucket_ratio": 0.5,
        },
    )
    assert res["overall_pass"] is True
    assert res["export_status"] == "REVIEW_RECOMMENDED"
    assert "VISIT_BUCKET_REQUIRED_MISSING" in {f.get("code") for f in (res.get("soft_failures") or [])}


def test_compact_packet_visit_bucket_quality_does_not_trigger_review(monkeypatch) -> None:
    monkeypatch.setattr(
        luqa_mod,
        "build_luqa_report",
        lambda report_text, ctx: {"luqa_pass": True, "luqa_score_0_100": 100, "failures": []},
    )
    monkeypatch.setattr(
        attorney_mod,
        "build_attorney_readiness_report",
        lambda report_text, ctx: {"attorney_ready_pass": True, "attorney_ready_score_0_100": 100, "failures": []},
    )
    res = run_quality_gates(
        report_text="Medical Timeline (Litigation Ready)\n2024-01-01 | Encounter: Admission\nCitation(s): [p. 1]\n",
        page_text_by_number={1: "page one", 2: "page two", 3: "page three"},
        projection_entries=[
            {"event_id": "e1", "citation_display": "p. 1"},
            {"event_id": "e2", "citation_display": "p. 2"},
        ],
        visit_bucket_quality={
            "total_encounters": 2,
            "encounters_with_missing_required_buckets": 2,
            "required_bucket_miss_count": 6,
            "missing_required_bucket_ratio": 1.0,
        },
    )
    assert res["overall_pass"] is True
    assert res["export_status"] == "VERIFIED"
    assert "VISIT_BUCKET_REQUIRED_MISSING" not in {f.get("code") for f in (res.get("soft_failures") or [])}
    assert res["gate_report"]["visit_bucket_quality"]["telemetry"]["compact_packet_policy"] is True


def test_five_page_compact_packet_visit_bucket_quality_does_not_trigger_review(monkeypatch) -> None:
    monkeypatch.setattr(
        luqa_mod,
        "build_luqa_report",
        lambda report_text, ctx: {"luqa_pass": True, "luqa_score_0_100": 100, "failures": []},
    )
    monkeypatch.setattr(
        attorney_mod,
        "build_attorney_readiness_report",
        lambda report_text, ctx: {"attorney_ready_pass": True, "attorney_ready_score_0_100": 100, "failures": []},
    )
    res = run_quality_gates(
        report_text="Medical Timeline (Litigation Ready)\n2024-01-01 | Encounter: Admission\nCitation(s): [p. 1]\n",
        page_text_by_number={1: "p1", 2: "p2", 3: "p3", 4: "p4", 5: "p5"},
        projection_entries=[
            {"event_id": "e1", "citation_display": "p. 1"},
            {"event_id": "e2", "citation_display": "p. 5"},
        ],
        visit_bucket_quality={
            "total_encounters": 2,
            "encounters_with_missing_required_buckets": 2,
            "required_bucket_miss_count": 6,
            "missing_required_bucket_ratio": 1.0,
        },
    )
    assert res["overall_pass"] is True
    assert res["export_status"] == "VERIFIED"
    assert "VISIT_BUCKET_REQUIRED_MISSING" not in {f.get("code") for f in (res.get("soft_failures") or [])}
    assert res["gate_report"]["visit_bucket_quality"]["telemetry"]["compact_packet_policy"] is True
