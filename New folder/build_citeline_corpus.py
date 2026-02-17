import os
import json
import time
import requests
from pathlib import Path

BASE_DIR = Path("citeline_corpus")

TIERS = {
    "tier1_small": [],
    "tier2_medium": [],
    "tier3_large": [],
    "tier4_extreme": []
}

# High-value real administrative record sources
SOURCE_URLS = [

    # SSA administrative records
    "https://www.govinfo.gov/content/pkg/USCOURTS-azd-4_12-cv-00128/pdf/USCOURTS-azd-4_12-cv-00128-0.pdf",
    "https://www.govinfo.gov/content/pkg/USCOURTS-moed-4_07-cv-00922/pdf/USCOURTS-moed-4_07-cv-00922-0.pdf",
    "https://www.govinfo.gov/content/pkg/USCOURTS-casd-3_10-cv-02008/pdf/USCOURTS-casd-3_10-cv-02008-0.pdf",
    "https://www.govinfo.gov/content/pkg/USCOURTS-pamd-1_22-cv-00582/pdf/USCOURTS-pamd-1_22-cv-00582-0.pdf",
    "https://www.govinfo.gov/content/pkg/USCOURTS-cofc-1_18-cv-01784/pdf/USCOURTS-cofc-1_18-cv-01784-2.pdf",

    # CourtListener RECAP large records
    "https://www.courtlistener.com/recap/gov.uscourts.cand.327878/gov.uscourts.cand.327878.51.0_1.pdf",

]

HEADERS = {
    "User-Agent": "Mozilla/5.0"
}

def ensure_dirs():
    for tier in TIERS:
        (BASE_DIR / tier).mkdir(parents=True, exist_ok=True)

def download_file(url, dest):
    try:
        r = requests.get(url, headers=HEADERS, timeout=60)

        if r.status_code == 200 and len(r.content) > 50000:
            with open(dest, "wb") as f:
                f.write(r.content)
            return True

    except Exception as e:
        print("Failed:", e)

    return False

def assign_tier(file_size):
    mb = file_size / (1024 * 1024)

    if mb < 5:
        return "tier1_small"
    elif mb < 15:
        return "tier2_medium"
    elif mb < 40:
        return "tier3_large"
    else:
        return "tier4_extreme"

def build_manifest(entries):
    manifest_path = BASE_DIR / "manifest.json"

    with open(manifest_path, "w") as f:
        json.dump(entries, f, indent=2)

def main():

    ensure_dirs()

    manifest = []

    for url in SOURCE_URLS:

        filename = url.split("/")[-1]

        temp_path = BASE_DIR / filename

        print("Downloading:", filename)

        success = download_file(url, temp_path)

        if not success:
            continue

        size = temp_path.stat().st_size

        tier = assign_tier(size)

        final_path = BASE_DIR / tier / filename

        temp_path.rename(final_path)

        manifest.append({
            "file": filename,
            "tier": tier,
            "size_mb": round(size / (1024 * 1024), 2),
            "source": url
        })

        time.sleep(1)

    build_manifest(manifest)

    print("Corpus build complete.")

if __name__ == "__main__":
    main()
