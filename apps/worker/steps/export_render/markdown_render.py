from __future__ import annotations

from apps.worker.steps.events.report_quality import sanitize_for_report
from apps.worker.steps.litigation import build_contradiction_matrix, build_narrative_duality
from apps.worker.lib.claim_ledger_lite import build_claim_ledger_lite


def build_markdown_bytes(
    *,
    projection,
    matter_title: str,
    events: list,
    narrative_synthesis: str | None,
    clean_narrative_text,
    generate_executive_summary,
    case_info=None,
) -> bytes:
    md_lines: list[str] = [f"# {matter_title}", "", "## Medical Chronology Analysis"]
    summary_for_md = (
        clean_narrative_text(narrative_synthesis)
        if narrative_synthesis
        else generate_executive_summary(events, matter_title, case_info=case_info)
    )
    if summary_for_md:
        md_lines.extend(["", summary_for_md.strip(), ""])
    md_lines.extend(["## Chronological Medical Timeline", ""])
    for entry in projection.entries:
        date_cell = sanitize_for_report(entry.date_display or "Date not documented")
        type_cell = sanitize_for_report(entry.event_type_display or "Clinical Event")
        facts_cell = sanitize_for_report(" ".join((entry.facts or [])[:2]) or "Encounter documented.")
        cite_cell = sanitize_for_report(entry.citation_display or "Citation unavailable")
        md_lines.append(f"- **{date_cell}** | **{type_cell}** | {facts_cell} | Citation(s): {cite_cell}")

    claim_rows_md = build_claim_ledger_lite(projection.entries, raw_events=events)
    contradiction_rows = build_contradiction_matrix(claim_rows_md, window_days=45)
    md_lines.extend(["", "## Medical Contradiction Matrix", ""])
    if contradiction_rows:
        for row in contradiction_rows[:8]:
            s = row.get("supporting") or {}
            c = row.get("contradicting") or {}
            md_lines.append(
                f"- **{str(row.get('category') or '').replace('_', ' ').title()}**: "
                f"{s.get('value')} ({s.get('date')}) vs {c.get('value')} ({c.get('date')}) "
                f"| Strength Delta: {row.get('strength_delta')}"
            )
    else:
        md_lines.append("- No material contradictions detected.")

    duality = build_narrative_duality(claim_rows_md)
    md_lines.extend(["", "## Narrative Duality", "", "### Plaintiff Narrative"])
    for p in ((duality.get("plaintiff_narrative") or {}).get("points") or [])[:5]:
        cits = " | ".join((p.get("citations") or [])[:2])
        md_lines.append(f"- {p.get('date', 'Date not documented')}: {p.get('assertion', '')} | Citation(s): {cits}")
    md_lines.extend(["", "### Defense Narrative"])
    for d in ((duality.get("defense_narrative") or {}).get("points") or [])[:5]:
        cits = " | ".join((d.get("citations") or [])[:2])
        md_lines.append(f"- {d.get('attack', 'Competing path')}: {d.get('path', '')} | Citation(s): {cits}")
    return ("\n".join(md_lines).strip() + "\n").encode("utf-8")

