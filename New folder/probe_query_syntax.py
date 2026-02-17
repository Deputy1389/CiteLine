import requests
import os

TOKEN = os.getenv("COURTLISTENER_TOKEN", "dd4ba64c6eb1822552c29ac26212c02cddc29715")
HEADERS = {"Authorization": f"Token {TOKEN}"}

def try_query(name, params):
    print(f"--- Trying {name} ---")
    url = "https://www.courtlistener.com/api/rest/v4/search/"
    p = params.copy()
    p['page_size'] = 1
    p['type'] = 'r'
    
    resp = requests.get(url, params=p, headers=HEADERS)
    print(f"Status: {resp.status_code}")
    if resp.status_code == 200:
        data = resp.json()
        count = data.get("count", 0)
        print(f"Count: {count}")
        results = data.get("results", [])
        if results:
            print(f"Top result available? {results[0].get('is_available')}")
        else:
            print("No results returned.")
    else:
        print(f"Error: {resp.text[:100]}")

def main():
    base_q = '"administrative record" "Commissioner of Social Security"'
    
    # Attempt 1: q syntax available:true
    try_query("q=... available:true", {"q": base_q + " available:true"})
    
    # Attempt 2: q syntax file_available:true
    try_query("q=... file_available:true", {"q": base_q + " file_available:true"})
    
    # Attempt 3: param file_available=true
    try_query("param file_available=true", {"q": base_q, "file_available": "true"})
    
    # Attempt 4: param available=true
    try_query("param available=true", {"q": base_q, "available": "true"})

if __name__ == "__main__":
    main()
