import os
import requests

urls = [
    "https://www.govinfo.gov/content/pkg/USCOURTS-azd-4_12-cv-00128/pdf/USCOURTS-azd-4_12-cv-00128-0.pdf",
    "https://www.govinfo.gov/content/pkg/USCOURTS-moed-4_07-cv-00922/pdf/USCOURTS-moed-4_07-cv-00922-0.pdf",
    "https://www.govinfo.gov/content/pkg/USCOURTS-casd-3_10-cv-02008/pdf/USCOURTS-casd-3_10-cv-02008-0.pdf",
    "https://www.govinfo.gov/content/pkg/USCOURTS-nyed-1_24-cv-03653/pdf/USCOURTS-nyed-1_24-cv-03653-0.pdf",
    "https://www.govinfo.gov/content/pkg/USCOURTS-pamd-1_22-cv-00582/pdf/USCOURTS-pamd-1_22-cv-00582-0.pdf",
    "https://www.govinfo.gov/content/pkg/USCOURTS-cofc-1_18-cv-01784/pdf/USCOURTS-cofc-1_18-cv-01784-2.pdf",
    "https://www.govinfo.gov/content/pkg/USCOURTS-azd-2_22-cv-00959/pdf/USCOURTS-azd-2_22-cv-00959-0.pdf",
    "https://www.govinfo.gov/content/pkg/USCOURTS-ca5-23-30831/pdf/USCOURTS-ca5-23-30831-0.pdf",
    "https://www.govinfo.gov/content/pkg/USCOURTS-ilsd-3_23-cv-03680/pdf/USCOURTS-ilsd-3_23-cv-03680-0.pdf",
    "https://www.govinfo.gov/content/pkg/USCOURTS-caed-1_20-cv-00145/pdf/USCOURTS-caed-1_20-cv-00145-3.pdf",
    "https://www.courtlistener.com/recap/gov.uscourts.cand.327878/gov.uscourts.cand.327878.51.0_1.pdf"
]

os.makedirs("citeline_test_corpus", exist_ok=True)

for url in urls:
    filename = url.split("/")[-1]
    path = os.path.join("citeline_test_corpus", filename)

    print(f"Downloading {filename}...")
    r = requests.get(url)
    with open(path, "wb") as f:
        f.write(r.content)

print("Done.")
