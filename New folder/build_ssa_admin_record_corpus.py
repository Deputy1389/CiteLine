"""
build_ssa_admin_record_corpus.py

Harvest SSA appeal “Administrative Record” PDFs using CourtListener.

Key points:
- CourtListener search results here are DOCKET-ish objects with a `recap_documents` array.
- We extract each RECAPDocument id from `recap_documents[*].id`
- Resolve each RECAPDocument via /api/rest/v4/recap-documents/{id}/ (fallback to v3)
- Download from real /recap/ file URLs, never /docket/ HTML

PowerShell:
  $env:COURTLISTENER_TOKEN="YOUR_TOKEN"
  pip install requests pypdf
  python build_ssa_admin_record_corpus.py
"""

import os
import re
import json
import time
import random
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import requests
from pypdf import PdfReader

# -----------------------
# Config
# -----------------------
BASE = Path("ssa_corpus")
MANIFEST = BASE / "manifest.json"
TARGET = 100

PAGE_SIZE = 20
MAX_PAGES_TO_SCAN_PER_QUERY = 100          # ~2000 search results per query
MAX_DOWNLOAD_ATTEMPTS_PER_QUERY = 35      # cap downloads so you don't hammer CL

# Post-download filters (keep permissive first; tighten later)
MIN_LOCAL_PAGES = 40
DENSITY_THRESHOLD = 2
MEDSIG_THRESHOLD = 1

SEARCH_TIMEOUT = 45
DOWNLOAD_TIMEOUT = 180
RETRIES = 4

DEBUG = True
DEBUG_PRINT_FIRST_N_FAILURES = 10

CL_TOKEN = os.getenv("COURTLISTENER_TOKEN", "").strip()

TIERS = [
    ("tier1_small", 0, 120),
    ("tier2_medium", 121, 300),
    ("tier3_large", 301, 800),
    ("tier4_extreme", 801, 10_000_000),
]

# We use these to bias toward admin records, but we do NOT hard-require them.
ADMIN_KEYWORDS = [
    "administrative record",
    "certified administrative record",
    "record on appeal",
    "certified transcript",
    "transcript",
    "car",
]

MEDICAL_TERMS = [
    "history of present illness", "hpi", "chief complaint",
    "assessment", "plan", "impression", "findings",
    "emergency department", "ed course", "discharge",
    "vitals", "bp", "hr", "rr", "spo2",
    "medications", "allergies", "dosage", "mg", "ml",
    "icd", "cpt", "mrn", "dob", "date of birth",
    "radiology", "ct", "mri", "x-ray", "ultrasound",
    "physical therapy", "pt note",
    "attending", "provider", "rn", "md", "do", "np", "pa-c",
]

QUERIES = [
    '"administrative record" "Commissioner of Social Security"',
    '"certified administrative record" "Commissioner of Social Security"',
    '"administrative record" "Social Security" "Commissioner"',
    '"record on appeal" "Commissioner of Social Security" administrative',
    '"transcript" "Commissioner of Social Security" "administrative record"',
]

# -----------------------
# Helpers
# -----------------------
def ensure_base() -> None:
    BASE.mkdir(parents=True, exist_ok=True)
    (BASE / "tmp").mkdir(parents=True, exist_ok=True)

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

def tier_for_pages(pages: int) -> str:
    for name, lo, hi in TIERS:
        if lo <= pages <= hi:
            return name
    return "tier_unknown"

def is_pdf_file(p: Path) -> bool:
    try:
        with p.open("rb") as f:
            return f.read(5) == b"%PDF-"
    except Exception:
        return False

def pdf_page_count(p: Path) -> int:
    try:
        with p.open("rb") as f:
            r = PdfReader(f)
            # pypdf might need the stream to stay open, so we read len inside the block
            return len(r.pages)
    except Exception:
        return 0

def pdf_text_density(p: Path, pages_to_sample: int = 5) -> float:
    try:
        with p.open("rb") as f:
            r = PdfReader(f)
            n = len(r.pages)
            if n == 0:
                return 0.0
            sample = min(n, pages_to_sample)
            chars = 0
            for i in range(sample):
                t = r.pages[i].extract_text() or ""
                t = re.sub(r"\s+", "", t)
                chars += len(t)
            return chars / sample
    except Exception:
        return 0.0

def medical_signature(p: Path, pages_to_sample: int = 8) -> int:
    try:
        with p.open("rb") as f:
            r = PdfReader(f)
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

def good_pdf(p: Path) -> Tuple[bool, Dict]:
    pages = pdf_page_count(p)
    if pages < MIN_LOCAL_PAGES:
        return False, {"pages": pages, "density": 0.0, "medsig": 0, "score": 0}

    density = pdf_text_density(p)
    medsig = medical_signature(p)
    score = int(min(450, pages * 0.22 + density * 0.02 + medsig * 4.0))

    ok = (density >= DENSITY_THRESHOLD) and (medsig >= MEDSIG_THRESHOLD)
    return ok, {"pages": pages, "density": density, "medsig": medsig, "score": score}

def looks_adminish(text: str) -> bool:
    if not text:
        return False
    t = text.lower()
    return any(k in t for k in ADMIN_KEYWORDS)

def get_field(d: Dict, *names, default=None):
    for n in names:
        if n in d:
            return d[n]
    return default

def as_abs_url(u: str) -> str:
    return "https://www.courtlistener.com" + u if u.startswith("/") else u

# -----------------------
# HTTP + endpoints
# -----------------------
SEARCH_URL = "https://www.courtlistener.com/api/rest/v4/search/"
RECAPDOC_V4 = "https://www.courtlistener.com/api/rest/v4/recap-documents/{id}/"
RECAPDOC_V3 = "https://www.courtlistener.com/api/rest/v3/recap-documents/{id}/"

def make_session() -> requests.Session:
    s = requests.Session()
    s.headers.update({"User-Agent": "SSACorpusBuilder/5.0"})
    if CL_TOKEN:
        s.headers.update({"Authorization": f"Token {CL_TOKEN}"})
    s.headers.update({"Accept": "application/pdf,application/json;q=0.9,*/*;q=0.8"})
    return s

def get_json(s: requests.Session, url: str, params: Dict = None, timeout: int = 45, retries: int = RETRIES) -> Optional[Dict]:
    for attempt in range(retries):
        try:
            r = s.get(url, params=params or {}, timeout=timeout)
            if r.status_code == 200:
                return r.json()

            if r.status_code in (429, 500, 502, 503, 504):
                sleep_s = min(20.0, (1.8 ** attempt)) + random.random()
                if DEBUG:
                    print(f"  [debug] GET {r.status_code} retry in {sleep_s:.1f}s")
                time.sleep(sleep_s)
                continue

            if DEBUG:
                snip = (r.text or "")[:140].replace("\n", " ")
                print(f"  [debug] GET {r.status_code} {url} -> {snip}")
            return None
        except requests.RequestException as e:
            sleep_s = min(20.0, (1.8 ** attempt)) + random.random()
            if DEBUG:
                print(f"  [debug] error {type(e).__name__} retry in {sleep_s:.1f}s")
            time.sleep(sleep_s)
    return None

def download_file(s: requests.Session, url: str, out: Path) -> Tuple[bool, Dict]:
    info = {"status": None, "ct": None, "final": None, "snippet": None}
    for attempt in range(RETRIES):
        try:
            with s.get(url, stream=True, timeout=DOWNLOAD_TIMEOUT, allow_redirects=True) as r:
                info["status"] = r.status_code
                info["ct"] = r.headers.get("Content-Type", "")
                info["final"] = str(r.url)

                if r.status_code in (429, 500, 502, 503, 504):
                    sleep_s = min(20.0, (1.8 ** attempt)) + random.random()
                    time.sleep(sleep_s)
                    continue

                if r.status_code != 200:
                    try:
                        info["snippet"] = (r.text or "")[:160].replace("\n", " ")
                    except Exception:
                        pass
                    return False, info

                out.parent.mkdir(parents=True, exist_ok=True)
                with out.open("wb") as f:
                    for chunk in r.iter_content(chunk_size=1024 * 256):
                        if chunk:
                            f.write(chunk)

            if is_pdf_file(out):
                return True, info

            try:
                with out.open("rb") as f:
                    info["snippet"] = f.read(160).decode("utf-8", errors="ignore").replace("\n", " ")
            except Exception:
                pass
            out.unlink(missing_ok=True)
            return False, info

        except requests.RequestException as e:
            info["snippet"] = type(e).__name__
            sleep_s = min(20.0, (1.8 ** attempt)) + random.random()
            time.sleep(sleep_s)
    return False, info

# -----------------------
# Core fix: extract recap doc IDs from recap_documents[]
# -----------------------
def extract_recapdoc_candidates_from_search_result(result: Dict) -> List[Dict]:
    """
    Each search result is a docket-ish object with a list of recap_documents.
    We return a list of candidate objects:
      { "recapdoc_id": int, "desc": str, "page_count": int, "score": int }
    """
    out = []
    docket_name = (get_field(result, "caseName", "case_name_full", default="") or "").strip()

    recap_docs = result.get("recap_documents") or []
    if not isinstance(recap_docs, list):
        return out

    for rd in recap_docs:
        if rd.get("is_available"):
            print(f"  [debug] Found available doc {rd.get('id')}")
        if not isinstance(rd, dict):
            continue

        rid = rd.get("id")
        if not isinstance(rid, int):
            continue

        # Skip unavailable documents (avoids 403s)
        if not rd.get("is_available"):
            continue

        desc = (get_field(rd, "description", "short_description", default="") or "").strip()
        pc = get_field(rd, "page_count", default=0) or 0
        
        # New: grab filepath_local to bypass 403 on detailed endpoint
        direct_url = None
        fpath = rd.get("filepath_local")
        if fpath:
            # Construct direct storage URL
            direct_url = f"https://storage.courtlistener.com/{fpath}"
            
        # Also check absolute_url just in case (though probe showed it's a webpage)
        # direct_url = rd.get("absolute_url") 
        # ... logic removed as absolute_url is not PDF ...

        # Score: prefer admin-record-ish descriptions and larger page counts
        score = 0
        if looks_adminish(desc) or looks_adminish(docket_name):
            score += 10
        score += min(8, int(pc) // 100)  # 0..8

        out.append({
            "recapdoc_id": rid, 
            "desc": desc, 
            "page_count": int(pc), 
            "score": score,
            "direct_url": direct_url
        })

    return out

def resolve_pdf_url_from_recapdoc(s: requests.Session, recapdoc_id: int) -> Optional[str]:
    """
    Resolve RECAPDocument JSON to a real file URL.
    Avoid /docket/ links.
    """
    j = get_json(s, RECAPDOC_V4.format(id=recapdoc_id), timeout=SEARCH_TIMEOUT)
    if not j:
        j = get_json(s, RECAPDOC_V3.format(id=recapdoc_id), timeout=SEARCH_TIMEOUT)
    if not j:
        return None

    candidates = []
    for k in ("download_url", "file_url", "absolute_url", "filepath_local", "filepath_ia", "ia_url"):
        v = j.get(k)
        if isinstance(v, str) and v:
            candidates.append(as_abs_url(v))

    # Filter out docket HTML pages (cause 403)
    candidates = [u for u in candidates if "/docket/" not in u]

    def rank(u: str) -> int:
        u2 = u.lower()
        r = 0
        if "/recap/" in u2:
            r += 50
        if u2.endswith(".pdf"):
            r += 20
        if "download" in u2:
            r += 10
        return r

    candidates = sorted(set(candidates), key=rank, reverse=True)
    return candidates[0] if candidates else None

# -----------------------
# Harvest
# -----------------------
def harvest(manifest: List[Dict], target: int) -> None:
    s = make_session()
    have = {e.get("source_id") for e in manifest}

    # smoke test
    t = get_json(s, SEARCH_URL, params={"q": "administrative record commissioner of social security", "type": "r", "page_size": 1})
    got = len((t or {}).get("results") or [])
    print(f"  [debug] smoke-test results={got}")

    printed_keys = False

    for q in QUERIES:
        if len(manifest) >= target:
            return

        print(f"\n[SSA/RECAP] Search: {q}")

        next_url = SEARCH_URL
        params = {"q": q, "type": "r", "page_size": PAGE_SIZE, "file_available": "true"}

        candidates: List[Dict] = []

        for page_i in range(MAX_PAGES_TO_SCAN_PER_QUERY):
            data = get_json(s, next_url, params=params, timeout=SEARCH_TIMEOUT)
            if not data:
                break

            results = data.get("results") or []
            next_url = data.get("next")
            params = None

            if not results:
                break

            if DEBUG and not printed_keys:
                printed_keys = True
                print("  [debug] sample search result keys:", sorted(results[0].keys())[:60])

            for res in results:
                candidates.extend(extract_recapdoc_candidates_from_search_result(res))

            if not next_url:
                break

        # Dedup recapdoc ids and sort best-first
        seen = set()
        uniq = []
        for c in sorted(candidates, key=lambda x: (x["score"], x["page_count"]), reverse=True):
            rid = c["recapdoc_id"]
            if rid in seen:
                continue
            seen.add(rid)
            uniq.append(c)

        if DEBUG:
            print(f"  [debug] candidates={len(candidates)} unique_recapdocs={len(uniq)}")

        attempts = 0
        downloaded = 0
        failures_printed = 0

        for c in uniq:
            if len(manifest) >= target:
                return
            if attempts >= MAX_DOWNLOAD_ATTEMPTS_PER_QUERY:
                break

            rid = c["recapdoc_id"]
            source_id = f"courtlistener:recapdoc:{rid}"
            if source_id in have:
                continue

            attempts += 1

            pdf_url = c.get("direct_url")
            if not pdf_url:
                pdf_url = resolve_pdf_url_from_recapdoc(s, rid)
            if not pdf_url:
                continue

            tmp = BASE / "tmp" / f"recapdoc_{rid}.pdf"
            ok, info = download_file(s, pdf_url, tmp)
            if not ok:
                if DEBUG and failures_printed < DEBUG_PRINT_FIRST_N_FAILURES:
                    failures_printed += 1
                    print(f"  [debug] download_fail rid={rid} status={info['status']} ct={info['ct']} final={info['final']}")
                    print(f"          snippet={info['snippet']}")
                tmp.unlink(missing_ok=True)
                continue

            ok2, meta = good_pdf(tmp)
            if not ok2:
                if DEBUG and failures_printed < DEBUG_PRINT_FIRST_N_FAILURES:
                    failures_printed += 1
                    print(f"  [debug] postfilter_fail rid={rid} pages={meta['pages']} density={meta['density']:.1f} medsig={meta['medsig']}")
                tmp.unlink(missing_ok=True)
                continue

            pages = meta["pages"]
            tier = tier_for_pages(pages)
            out = BASE / tier / f"ssa_admin_record_recapdoc_{rid}.pdf"
            out.parent.mkdir(parents=True, exist_ok=True)
            tmp.replace(out)

            entry = {
                "source": "courtlistener",
                "source_id": source_id,
                "recap_document_id": rid,
                "pdf_url": pdf_url,
                "path": str(out),
                "sha1": sha1_file(out),
                "pages": pages,
                "density": meta["density"],
                "medsig": meta["medsig"],
                "score_local": meta["score"],
                "page_count_meta": c.get("page_count", 0),
                "description_meta": c.get("desc", ""),
                "query": q,
            }
            manifest.append(entry)
            have.add(source_id)
            save_manifest(manifest)

            downloaded += 1
            print(f"  ✓ recapdoc={rid} | {pages} pages | medsig={meta['medsig']} → {tier}")

        if DEBUG:
            print(f"  [debug] attempted={attempts} downloaded={downloaded} (cap={MAX_DOWNLOAD_ATTEMPTS_PER_QUERY})")

# -----------------------
# Main
# -----------------------
def main():
    ensure_base()
    manifest = load_manifest()
    print(f"Starting with {len(manifest)} files already.")

    if not CL_TOKEN:
        print("WARNING: COURTLISTENER_TOKEN is not set. Downloads may fail more often.")

    harvest(manifest, TARGET)

    print(f"\nDone. Corpus size: {len(manifest)}")
    print(f"Manifest: {MANIFEST}")

    if len(manifest) < TARGET:
        print("\nIf you didn't reach target:")
        print("- Paste ONE [debug] download_fail rid=... line. Status/ct/final tells us if files are public or blocked.")
        print("- If postfilter fails a lot: lower MIN_LOCAL_PAGES or MEDSIG_THRESHOLD temporarily.")

if __name__ == "__main__":
    main()
