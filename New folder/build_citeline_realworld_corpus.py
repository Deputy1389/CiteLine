import os
import re
import json
import time
import random
from pathlib import Path
from typing import Dict, List, Tuple, Optional

import requests
from pypdf import PdfReader

# -----------------------------
# Config
# -----------------------------
BASE = Path("citeline_corpus")
MANIFEST = BASE / "manifest.json"
TARGET = 100

# Prefer PI-paralegal style packets (multi-visit / multi-provider)
MIN_PAGES = 15

# Dense text helps, but medical-signature is the real gate
DENSITY_THRESHOLD = 8   # lower to 6 if you want more permissive
MEDSIG_THRESHOLD = 6    # lower to 4 if too strict

# Debug prints a sample of returned result keys per query page
DEBUG_COURTLISTENER = False

# Read secrets from environment (do NOT hardcode keys)
GOVINFO_KEY = os.getenv("GOVINFO_API_KEY", "").strip()
COURTLISTENER_TOKEN = os.getenv("COURTLISTENER_TOKEN", "").strip()
CL_TOKEN = COURTLISTENER_TOKEN  # alias used throughout

HEADERS = {"User-Agent": "CiteLineCorpusBuilder/4.0"}

TIERS = [
    ("tier0_tiny", 0, 20),
    ("tier1_small", 21, 60),
    ("tier2_medium", 61, 120),
    ("tier3_large", 121, 500),
    ("tier4_extreme", 501, 10_000_000),
]

# -----------------------------
# CourtListener RECAP queries (fielded)
#
# These are intentionally "RECAP-document centric":
# - type=r (RECAP) rather than d (dockets)
# - is_available:true to bias toward downloadable docs
# - page_count ranges to bias toward big packets
# - description matches exhibit-style naming conventions
# -----------------------------
COURTLISTENER_QUERIES = [
    'is_available:true AND page_count:[30 TO *] AND (description:"medical records" OR description:"hospital records")',
    'is_available:true AND page_count:[30 TO *] AND (description:"emergency" OR description:"ER" OR description:"ED")',
    'is_available:true AND page_count:[30 TO *] AND (description:"radiology" OR description:"MRI" OR description:"CT" OR description:"X-ray")',
    'is_available:true AND page_count:[30 TO *] AND (description:"treatment" OR description:"progress notes" OR description:"clinic note")',
    'is_available:true AND page_count:[30 TO *] AND (description:"physical therapy" OR description:"PT notes")',
    'is_available:true AND document_type:Attachment AND page_count:[20 TO *] AND (description:"medical" OR description:"records")',
]

# -----------------------------
# Medical signature filter
# -----------------------------
MEDICAL_TERMS = [
    "history of present illness", "hpi", "chief complaint", "review of systems",
    "assessment", "plan", "problem list", "impression", "findings",
    "emergency department", "ed course", "triage", "disposition", "admitted", "discharge",
    "vitals", "bp", "hr", "rr", "temp", "spo2",
    "medications", "allergies", "dose", "dosage", "mg", "ml", "po", "iv", "prn",
    "icd", "cpt", "mrn", "dob", "date of birth",
    "radiology", "ct", "mri", "x-ray", "ultrasound",
    "physical therapy", "pt note", "occupational therapy", "ot note",
    "attending", "provider", "rn", "md", "do", "pa-c", "np",
]

# -----------------------------
# Helpers
# -----------------------------
def ensure_base() -> None:
    BASE.mkdir(parents=True, exist_ok=True)

def load_manifest() -> List[Dict]:
    if MANIFEST.exists():
        return json.loads(MANIFEST.read_text(encoding="utf-8"))
    return []

def save_manifest(manifest: List[Dict]) -> None:
    MANIFEST.write_text(json.dumps(manifest, indent=2), encoding="utf-8")

def sha1_file(p: Path) -> str:
    import hashlib
    h = hashlib.sha1()
    with p.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()

def safe_name(s: str) -> str:
    s = re.sub(r"[^a-zA-Z0-9._-]+", "_", s).strip("_")
    return s[:180] if len(s) > 180 else s

def pdf_page_count(p: Path) -> int:
    try:
        r = PdfReader(str(p))
        return len(r.pages)
    except Exception:
        return 0

def pdf_text_density(p: Path, pages_to_sample=5) -> float:
    try:
        r = PdfReader(str(p))
        n = len(r.pages)
        if n == 0:
            return 0.0
        sample = min(n, pages_to_sample)
        chars = 0
        for i in range(sample):
            t = r.pages[i].extract_text() or ""
            chars += len(re.sub(r"\s+", "", t))
        return chars / sample
    except Exception:
        return 0.0

def medical_signature(p: Path, pages_to_sample=6) -> int:
    try:
        r = PdfReader(str(p))
        n = len(r.pages)
        if n == 0:
            return 0
        sample = min(n, pages_to_sample)
        hits = 0
        for i in range(sample):
            t = (r.pages[i].extract_text() or "").lower()
            hits += sum(1 for term in MEDICAL_TERMS if term in t)
        return hits
    except Exception:
        return 0

def tier_for_pages(pages: int) -> str:
    for name, lo, hi in TIERS:
        if lo <= pages <= hi:
            return name
    return "tier_unknown"

def download_to(url: str, out: Path, headers: Dict = None, timeout=180) -> bool:
    headers = headers or {}
    try:
        with requests.get(url, headers=headers, stream=True, timeout=timeout) as r:
            if r.status_code != 200:
                return False
            out.parent.mkdir(parents=True, exist_ok=True)
            with out.open("wb") as f:
                for chunk in r.iter_content(chunk_size=1024 * 256):
                    if chunk:
                        f.write(chunk)
        return True
    except requests.RequestException:
        return False

def good_pdf(p: Path) -> Tuple[bool, Dict]:
    pages = pdf_page_count(p)
    if pages < MIN_PAGES:
        return False, {"pages": pages, "density": 0.0, "score": 0, "medsig": 0}

    density = pdf_text_density(p)
    medsig = medical_signature(p)

    score = int(min(300, pages * 0.25 + density * 0.03 + medsig * 3.0))
    ok = (density >= DENSITY_THRESHOLD) and (medsig >= MEDSIG_THRESHOLD)

    return ok, {"pages": pages, "density": density, "score": score, "medsig": medsig}

# -----------------------------
# CourtListener harvesting (RECAP / search)
# -----------------------------
def cl_headers() -> Dict:
    return {
        "Authorization": f"Token {CL_TOKEN}",
        "User-Agent": "CiteLineCorpusBuilder/4.0",
    }

def cl_search_url() -> str:
    return "https://www.courtlistener.com/api/rest/v4/search/"

def cl_get(url: str, params: Dict = None, timeout=60) -> Optional[Dict]:
    try:
        r = requests.get(url, headers=cl_headers(), params=params or {}, timeout=timeout)
        if r.status_code != 200:
            if DEBUG_COURTLISTENER:
                print(f"  [debug] GET {r.status_code}: {r.text[:200].replace(chr(10),' ')}")
            return None
        return r.json()
    except requests.RequestException as e:
        if DEBUG_COURTLISTENER:
            print(f"  [debug] request error: {type(e).__name__}")
        return None

def extract_pdf_url_from_result(item: Dict) -> Optional[str]:
    """
    CourtListener v4 search results vary.
    For RECAP results (type=r), we try:
      - direct fields (download_url / file_url / absolute_url)
      - nested recap_documents list (choose largest page_count first)
    """
    pdf_url = None

    # 1) Direct fields
    for k in ("download_url", "file_url", "absolute_url"):
        v = item.get(k)
        if isinstance(v, str) and ".pdf" in v.lower():
            pdf_url = v
            break

    # 2) Nested recap docs
    if not pdf_url:
        recap_docs = item.get("recap_documents") or []
        if isinstance(recap_docs, list) and recap_docs:
            recap_docs_sorted = sorted(
                [rd for rd in recap_docs if isinstance(rd, dict)],
                key=lambda rd: (rd.get("page_count") or 0),
                reverse=True,
            )
            for rd in recap_docs_sorted:
                v = rd.get("download_url") or rd.get("absolute_url") or rd.get("file_url")
                if isinstance(v, str) and ".pdf" in v.lower():
                    pdf_url = v
                    break

    if not pdf_url:
        return None

    # Normalize relative -> absolute
    if pdf_url.startswith("/"):
        pdf_url = "https://www.courtlistener.com" + pdf_url

    return pdf_url

def harvest_courtlistener(manifest: List[Dict], target: int) -> None:
    if not CL_TOKEN:
        print("Skipping CourtListener: COURTLISTENER_TOKEN not set.")
        return

    have = {e.get("source_id") for e in manifest}

    for q in COURTLISTENER_QUERIES:
        if len(manifest) >= target:
            return

        print(f'\n[CourtListener] Search: {q}')

        next_url = cl_search_url()
        # IMPORTANT: type="r" for RECAP documents (not "d" dockets)
        params = {"q": q, "type": "r", "page_size": 20}

        for _ in range(120):
            if len(manifest) >= target:
                return

            data = cl_get(next_url, params=params)
            if not data:
                break

            results = data.get("results") or []
            next_url = data.get("next")
            params = None  # pagination URL already includes query

            if DEBUG_COURTLISTENER and results:
                sample = results[0]
                print("  [debug] sample keys:", sorted(sample.keys())[:40])
                if "recap_documents" in sample:
                    print("  [debug] recap_documents count:", len(sample.get("recap_documents") or []))

            if not results:
                break

            # Randomize so you don't always get the same top results
            random.shuffle(results)

            for item in results:
                if len(manifest) >= target:
                    return

                pdf_url = extract_pdf_url_from_result(item)
                if not pdf_url:
                    continue

                source_id = f"courtlistener:{pdf_url}"
                if source_id in have:
                    continue

                tmp = BASE / "tmp" / f"cl_{safe_name(str(abs(hash(pdf_url))))}.pdf"
                ok_dl = download_to(pdf_url, tmp, headers=cl_headers(), timeout=180)
                if not ok_dl:
                    tmp.unlink(missing_ok=True)
                    continue

                is_ok, meta = good_pdf(tmp)
                if not is_ok:
                    tmp.unlink(missing_ok=True)
                    continue

                pages = meta["pages"]
                tier = tier_for_pages(pages)
                out = BASE / tier / f"courtlistener_{safe_name(str(abs(hash(pdf_url))))}.pdf"
                out.parent.mkdir(parents=True, exist_ok=True)
                tmp.replace(out)

                entry = {
                    "source": "courtlistener",
                    "source_id": source_id,
                    "pdf_url": pdf_url,
                    "path": str(out),
                    "sha1": sha1_file(out),
                    "pages": pages,
                    "density": meta["density"],
                    "medsig": meta["medsig"],
                    "score": meta["score"],
                }
                manifest.append(entry)
                have.add(source_id)

                print(f"  ✓ {pages} pages | medsig={meta['medsig']} | score={meta['score']} → {tier}")
                save_manifest(manifest)

            if not next_url:
                break

# -----------------------------
# Main
# -----------------------------
def main():
    ensure_base()
    manifest = load_manifest()
    print(f"Starting with {len(manifest)} files already.")

    harvest_courtlistener(manifest, TARGET)

    print(f"\nDone. Corpus size: {len(manifest)}")
    print(f"Manifest: {MANIFEST}")

    if len(manifest) < TARGET:
        print("\nIf you didn't reach 100:")
        print("- Run again; it appends without duplicates.")
        print("- Lower MEDSIG_THRESHOLD 6 → 4 if filtering too hard.")
        print("- Lower MIN_PAGES 15 → 8 if you want smaller items too.")

if __name__ == "__main__":
    main()
