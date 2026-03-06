from __future__ import annotations


def is_compact_packet(
    *,
    score_row_count: int,
    projection_count: int,
    page_count: int,
    total_encounters: int | None = None,
) -> bool:
    """Shared policy for compact citation-backed packets.

    Compact packets are short admission/discharge style records with a small
    number of substantive encounters. They should not be downgraded solely by
    prose-density or generic visit-bucket soft gates.
    """
    substantive_count = int(total_encounters if total_encounters is not None else score_row_count)
    return (
        substantive_count > 0
        and substantive_count <= 3
        and projection_count <= 3
        and page_count <= 5
    )
