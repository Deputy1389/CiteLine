from apps.worker.lib.artifacts_writer import build_export_evidence_graph


def test_build_export_evidence_graph_strips_valuation_extensions_in_mediation():
    payload = {
        "extensions": {
            "case_severity_index": {"base_csi": 6.9},
            "settlement_model_report": {"label": "internal"},
            "settlement_leverage_model": {"x": 1},
            "settlement_feature_pack": {"x": 2},
            "defense_attack_map": {"x": 3},
            "severity_profile": {"schema_version": "severity_profile.v1"},
            "renderer_manifest": {"manifest_version": "1.0"},
            "unrelated_debug_blob": {"x": 1},
        }
    }
    out = build_export_evidence_graph(payload, "MEDIATION")
    ext = out["extensions"]
    assert "case_severity_index" not in ext
    assert "settlement_model_report" not in ext
    assert "settlement_leverage_model" not in ext
    assert "settlement_feature_pack" not in ext
    assert "defense_attack_map" not in ext
    assert "unrelated_debug_blob" not in ext
    assert "severity_profile" in ext
    assert "renderer_manifest" in ext
    assert ext.get("export_mode") == "MEDIATION"


def test_build_export_evidence_graph_keeps_internal_extensions_in_internal_mode():
    payload = {"extensions": {"case_severity_index": {"base_csi": 7.2}, "severity_profile": {"schema_version": "severity_profile.v1"}}}
    out = build_export_evidence_graph(payload, "INTERNAL")
    assert "case_severity_index" in out["extensions"]
    assert "severity_profile" in out["extensions"]
