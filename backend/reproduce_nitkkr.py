import requests
import time
import urllib3
import ssl

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

urls = ["https://www.nitkkr.ac.in", "https://nitkkr.ac.in"]
    
def check(url):
    print(f"Checking {url}...")
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36',
        'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
        'Accept-Language': 'en-US,en;q=0.5',
        'Connection': 'keep-alive',
        'Upgrade-Insecure-Requests': '1'
    }
    
    # Method 1: HEAD then GET (Current)
    print("  [Method 1: HEAD -> GET]")
    start = time.time()
    try:
        try:
            resp = requests.head(url, headers=headers, timeout=25, allow_redirects=True, verify=False)
            if 200 <= resp.status_code < 400:
                print(f"    HEAD Success: {time.time() - start:.2f}s")
            else:
                raise Exception(f"Status {resp.status_code}")
        except Exception:
            resp = requests.get(url, headers=headers, timeout=25, stream=True, verify=False)
            resp.close()
            print(f"    GET Success (fallback): {time.time() - start:.2f}s")
    except Exception as e:
        print(f"    FAILED: {e}, Time: {time.time() - start:.2f}s")

    # Method 2: GET stream=True Only (Proposed)
    print("  [Method 2: GET stream=True Only]")
    start = time.time()
    try:
        resp = requests.get(url, headers=headers, timeout=20, stream=True, verify=False) # 20s timeout
        resp.close()
        if 200 <= resp.status_code < 400:
            print(f"    GET Success: {time.time() - start:.2f}s")
        else:
            print(f"    GET Failed Status: {resp.status_code}")
    except Exception as e:
        print(f"    GET Failed: {e}, Time: {time.time() - start:.2f}s")

print("--- Benchmarking Check Methods ---")
for url in urls:
    check(url)
