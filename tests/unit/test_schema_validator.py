"""
Unit tests for schema validator.
"""
from __future__ import annotations

from packages.shared.schema_validator import validate_output

def test_validate_output_valid():
    """Test validation with a minimal valid JSON object."""
    data = {
        "schema_version": "0.1.0",
        "generated_at": "2023-10-27T10:00:00Z",
        "case": {
            "case_id": "123456",
            "firm_id": "firm123",
            "title": "Test Case",
            "timezone": "America/Los_Angeles"
        },
        "inputs": {
            "source_documents": [
                {
                    "document_id": "doc123",
                    "filename": "test.pdf",
                    "mime_type": "application/pdf",
                    "sha256": "a" * 64,
                    "bytes": 1024
                }
            ]
        },
        "outputs": {
            "run": {
                "run_id": "run12345678",
                "started_at": "2023-10-27T10:00:00Z",
                "finished_at": "2023-10-27T10:01:00Z",
                "status": "success",
                "warnings": [],
                "metrics": {
                    "documents": 1,
                    "pages_total": 5,
                    "pages_ocr": 0,
                    "events_total": 2,
                    "events_exported": 2,
                    "providers_total": 1
                },
                "provenance": {
                    "pipeline_version": "0.1.0",
                    "extractor": {"name": "CiteLine", "version": "0.1.0"},
                    "ocr": {"engine": "tesseract", "version": "5.3.0", "language": "en"},
                    "hashes": {"inputs_sha256": "b" * 64, "outputs_sha256": "c" * 64}
                }
            },
            "evidence_graph": {
                "documents": [],
                "pages": [],
                "providers": [],
                "events": [],
                "citations": [],
                "gaps": []
            },
            "chronology": {
                "export_format_version": "0.1.0",
                "events_exported": [],
                "exports": {
                    "pdf": {
                        "uri": "s3://bucket/test.pdf",
                        "sha256": "d" * 64,
                        "bytes": 2048
                    },
                    "csv": {
                        "uri": "s3://bucket/test.csv",
                        "sha256": "e" * 64,
                        "bytes": 512
                    }
                }
            }
        }
    }
    is_valid, errors = validate_output(data)
    assert is_valid, f"Validation failed: {errors}"

def test_validate_output_invalid():
    """Test validation with missing required fields."""
    data = {
        "schema_version": "0.1.0",
        # Missing generated_at, case, inputs, outputs
    }
    is_valid, errors = validate_output(data)
    assert not is_valid
    assert len(errors) > 0
    # Check that error messages are informative
    assert any("generated_at" in e for e in errors)
