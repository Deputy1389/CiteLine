# Litigation Output Contract

## Purpose
Define the minimum contract for a chronology to be attorney-usable without rewrite.

## Required Sections
- `Medical Chronology Analysis`
- `Chronological Medical Timeline`
- `Top 10 Case-Driving Events`
- `Appendix A` (Medication changes)
- `Appendix B` (Diagnoses/Problems)
- `Appendix C` (Treatment gaps and anchors)

## Timeline Row Contract
Each timeline row must include:
- Date + encounter label
- At least one direct clinical snippet
- Citation(s)

Rows are ineligible if they are placeholder/meta or uncited.

## Hard Bans
- Meta language (e.g., "identified from source", "encounter recorded", "markers")
- Placeholder rows
- Uncited factual rows
- Missing milestone buckets when present in source (ED, MRI, ORTHO, PROCEDURE)

## Pass Conditions
`overall_pass` requires:
- Litigation QA pass
- LUQA pass
- Attorney Readiness pass

Current implementation gate:
`overall_pass = qa_pass AND luqa_pass AND attorney_ready_pass`

