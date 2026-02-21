"""
Render manifest and anchor helpers for bidirectional navigation.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List


def chron_anchor(event_id: str) -> str:
    return f"chron_row_{event_id}"


def appendix_anchor(doc_id: str, page: int) -> str:
    return f"app_{doc_id}_p_{page}_{_stable_suffix(doc_id, page)}"


def _stable_suffix(doc_id: str, page: int) -> str:
    import hashlib
    key = f"{doc_id}|{page}"
    return hashlib.sha1(key.encode("utf-8")).hexdigest()[:8]


def parse_chron_anchor(anchor: str) -> str | None:
    if not anchor.startswith("chron_row_"):
        return None
    return anchor.replace("chron_row_", "", 1)


def parse_appendix_anchor(anchor: str) -> tuple[str, int] | None:
    if not anchor.startswith("app_"):
        return None
    tail = anchor.replace("app_", "", 1)
    parts = tail.rsplit("_p_", 1)
    if len(parts) != 2:
        return None
    doc_id = parts[0]
    suffix_parts = parts[1].split("_", 1)
    try:
        page = int(suffix_parts[0])
    except ValueError:
        return None
    return doc_id, page


@dataclass
class RenderManifest:
    chron_anchors: List[str] = field(default_factory=list)
    appendix_anchors: List[str] = field(default_factory=list)
    forward_links: Dict[str, List[str]] = field(default_factory=dict)
    back_links: Dict[str, List[str]] = field(default_factory=dict)

    def add_chron_anchor(self, anchor: str) -> None:
        if anchor not in self.chron_anchors:
            self.chron_anchors.append(anchor)

    def add_appendix_anchor(self, anchor: str) -> None:
        if anchor not in self.appendix_anchors:
            self.appendix_anchors.append(anchor)

    def add_link(self, from_anchor: str, to_anchor: str) -> None:
        self.forward_links.setdefault(from_anchor, [])
        if to_anchor not in self.forward_links[from_anchor]:
            self.forward_links[from_anchor].append(to_anchor)
        self.back_links.setdefault(to_anchor, [])
        if from_anchor not in self.back_links[to_anchor]:
            self.back_links[to_anchor].append(from_anchor)
