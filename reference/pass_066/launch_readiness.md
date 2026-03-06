# Pass 066 Launch Readiness

- Recommended scope: `narrow_pilot`
- Narrow pilot ready: `true`
- Broad launch ready: `false`

## Dimensions

### compact_text_packets
- Status: `ready`
- Scope: `narrow_pilot`
- Decision: Validated compact text-backed hospital packets are ready for narrow-pilot use.
- Evidence: `{"exports_latest_200": 30, "success_packets": 30, "validated_packets": 30}`

### sparse_packet_page1_orientation
- Status: `ready`
- Scope: `narrow_pilot`
- Decision: Sparse packets no longer render a junky or empty-feeling Page 1 when anchors are absent.
- Evidence: `{"case_skeleton_active": true, "promoted_findings": 0, "run_id": "c0e611f937cf4292a328ada3cf57d74b", "top_case_drivers": 0}`

### ocr_degraded_packets
- Status: `limited`
- Scope: `narrow_pilot`
- Decision: OCR is proven on some degraded packets but not yet across the full scan class.
- Evidence: `{"non_empty_event_packets": 2, "ocr_positive_packets": 3, "open_issue": "Fully rasterized compact MIMIC pages still hit live Tesseract timeouts on 4/5 pages and collapse to zero events; synthetic image-only and noisy corpus OCR paths complete.", "validated_packets": 3}`

### fully_rasterized_scan_packets
- Status: `limited`
- Scope: `broad_launch`
- Decision: Fully rasterized compact scans are now recoverable, but the scan class is still under-validated and slower than text-backed packets.
- Evidence: `{"events_total": 6, "packet": "packet_mimic_10002930_rasterized_clean.pdf", "pages_ocr": 5, "pages_total": 5, "status": "needs_review"}`

### rich_chronology_semantics
- Status: `pilot_ready`
- Scope: `narrow_pilot`
- Decision: Richer spine packets preserve more chronology structure and better encounter semantics on the validated slice.
- Evidence: `{"event_counts_preserved": true, "min_events_total": 8, "office_visit_packets": 3, "pass64_validated_packets": 4, "validated_packets": 3}`

### coverage_breadth
- Status: `blocked`
- Scope: `broad_launch`
- Decision: Broad launch remains blocked until non-spine and deeper OCR coverage are validated.
- Evidence: `{"missing_buckets": ["non-spine orthopedic packet (shoulder or knee)", "TBI/neuro packet", "broad rasterized/OCR corpus beyond the current 3-packet sweep", "explicit sparse-billing acceptance packet"], "validated_case_buckets": ["compact text-backed hospital packets", "sparse synthetic packet fallback", "MVA/spine fast packet", "MVA/spine complex packet", "procedure-heavy spine packet", "noisy OCR packet"]}`

## Blocking Reasons

- Fully rasterized compact scans are now recoverable, but the scan class is still under-validated and slower than text-backed packets.
- Broad launch remains blocked until non-spine and deeper OCR coverage are validated.
