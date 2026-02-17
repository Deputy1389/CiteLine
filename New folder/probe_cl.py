import requests
import os
import json

TOKEN = os.getenv("COURTLISTENER_TOKEN", "dd4ba64c6eb1822552c29ac26212c02cddc29715")
HEADERS = {"Authorization": f"Token {TOKEN}"}

def probe():
    url = "https://www.courtlistener.com/api/rest/v4/search/"
    params = {
        "q": '"administrative record" "Commissioner of Social Security" file_available:true',
        "type": "r",
        "page_size": 1
    }
    print(f"Searching {url}...")
    resp = requests.get(url, params=params, headers=HEADERS)
    print(f"Status: {resp.status_code}")
    if resp.status_code == 200:
        data = resp.json()
        results = data.get("results", [])
        if results:
            first = results[0]
            print("First result keys:", first.keys())
            recap_docs = first.get("recap_documents", [])
            if recap_docs:
                print("First recap_doc keys:", recap_docs[0].keys())
                print("First recap_doc sample:", json.dumps(recap_docs[0], indent=2))
            else:
                print("No recap_documents in first result")
        else:
            print("No results found")
    else:
        print("Error:", resp.text[:200])

if __name__ == "__main__":
    probe()
