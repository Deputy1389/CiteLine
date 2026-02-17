import requests
import os
import json

TOKEN = os.getenv("COURTLISTENER_TOKEN", "dd4ba64c6eb1822552c29ac26212c02cddc29715")
HEADERS = {"Authorization": f"Token {TOKEN}"}

def probe(name, params):
    print(f"\n--- {name} ---")
    url = "https://www.courtlistener.com/api/rest/v4/search/"
    p = params.copy()
    p['page_size'] = 20
    
    try:
        resp = requests.get(url, params=p, headers=HEADERS)
        print(f"Status: {resp.status_code}")
        if resp.status_code == 200:
            data = resp.json()
            print(f"Count: {data.get('count')}")
            results = data.get("results", [])
            for i, r0 in enumerate(results[:5]):
                print(f"Result {i}:")
                # Check for recap_documents
                rdocs = r0.get("recap_documents")
                if rdocs is None:
                    print("recap_documents: None")
                elif isinstance(rdocs, list):
                    print(f"recap_documents: List len={len(rdocs)}")
                    for rd in rdocs:
                         if rd.get("is_available"):
                             print(f"  Doc {rd.get('id')} fpath: {rd.get('filepath_local')}")
                             # print(f"  Doc {rd.get('id')} keys: {sorted(rd.keys())}")
                         # print(f"  Doc {rd.get('id')} avail={rd.get('is_available')}")
                else:
                    print(f"recap_documents: {type(rdocs)}")
        else:
            print("Error")
    except Exception as e:
        print(f"Exception: {e}")

def main():
    q = '"administrative record" "Commissioner of Social Security"'
    
    # 1. type=r, file_available=true
    probe("type=r, file_available=true", {"q": q, "type": "r", "file_available": "true"})
    
    # 2. type=d, file_available=true
    probe("type=d, file_available=true", {"q": q, "type": "d", "file_available": "true"})
    
    # 3. No type, file_available=true
    probe("No type, file_available=true", {"q": q, "file_available": "true"})

    # 4. type=r, q property "available:true" (just to double check)
    probe("type=r, q=available:true", {"q": q + " available:true", "type": "r"})

if __name__ == "__main__":
    main()
