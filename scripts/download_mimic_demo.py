"""
MIMIC-IV Demo Downloader.
Downloads Admissions, Patients, and Discharge Summaries from PhysioNet.
"""
import requests
from pathlib import Path

DATA_DIR = Path("c:/CiteLine/data/mimic_demo")
BASE_URL = "https://physionet.org/files/mimic-iv-demo/2.2/"
NOTE_URL = "https://physionet.org/files/mimic-iv-note-demo/2.2/"

FILES = [
    (BASE_URL + "hosp/admissions.csv.gz", "admissions.csv.gz"),
    (BASE_URL + "hosp/patients.csv.gz", "patients.csv.gz"),
    (BASE_URL + "hosp/diagnoses_icd.csv.gz", "diagnoses_icd.csv.gz"),
    (NOTE_URL + "note/discharge.csv.gz", "discharge.csv.gz"),
]

import gzip
import shutil

def download_file(url, filename):
    dest = DATA_DIR / filename
    csv_dest = DATA_DIR / filename.replace('.gz', '')
    if csv_dest.exists():
        print(f"Skipping {filename}, CSV already exists.")
        return
    
    print(f"Downloading {url}...")
    try:
        r = requests.get(url, stream=True, timeout=30)
        r.raise_for_status()
        with open(dest, 'wb') as f:
            for chunk in r.iter_content(chunk_size=8192):
                f.write(chunk)
        
        # Decompress
        print(f"Decompressing {filename}...")
        with gzip.open(dest, 'rb') as f_in:
            with open(csv_dest, 'wb') as f_out:
                shutil.copyfileobj(f_in, f_out)
        
        dest.unlink() # Remove gz
        print(f"Saved to {csv_dest}")
    except Exception as e:
        print(f"Error downloading {url}: {e}")

def main():
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    for url, bname in FILES:
        download_file(url, bname)

if __name__ == "__main__":
    main()
