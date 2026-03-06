# OCR Coverage Audit

## Why this pass exists
Validated compact MIMIC packets succeeded without needing OCR. That proves general pipeline health, not OCR readiness.

## Gap
The current launch evidence does not prove:
- image-only packet success
- OCR-degraded packet cleanliness
- stable OCR-triggered citation and provider quality

## Required evidence
- packets with `pages_ocr > 0`
- terminal artifacts
- artifact review notes on citation/provider/event quality
