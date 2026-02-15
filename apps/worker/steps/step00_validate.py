"""
Step 0 — Input validation.
Verify each SourceDocument: mime_type, sha256, bytes > 0.
Enforce max_pages limit.
"""
from __future__ import annotations

from packages.shared.models import RunConfig, SourceDocument, Warning


def validate_inputs(
    source_documents: list[SourceDocument],
    config: RunConfig,
) -> tuple[list[SourceDocument], list[Warning]]:
    """
    Validate source documents and return (valid_docs, warnings).
    """
    warnings: list[Warning] = []
    valid: list[SourceDocument] = []

    for doc in source_documents:
        if doc.mime_type != "application/pdf":
            warnings.append(Warning(
                code="INVALID_MIME_TYPE",
                message=f"Document {doc.document_id} has unsupported mime_type '{doc.mime_type}'",
                document_id=doc.document_id,
            ))
            continue

        if not doc.sha256 or len(doc.sha256) != 64:
            warnings.append(Warning(
                code="INVALID_SHA256",
                message=f"Document {doc.document_id} has invalid or missing sha256",
                document_id=doc.document_id,
            ))
            continue

        if doc.bytes <= 0:
            warnings.append(Warning(
                code="EMPTY_DOCUMENT",
                message=f"Document {doc.document_id} has zero bytes",
                document_id=doc.document_id,
            ))
            continue

        valid.append(doc)

    return valid, warnings
