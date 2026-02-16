"""Quick debug of pattern matching"""
import re
from urllib.parse import unquote

url = "https://www.iitrpr.ac.in/static/media/Indian%20Institute%20of%20Technology%20Ropar20250214-%20Ov.e6663a313b9e84b21938.pdf"
url_lower = url.lower()
url_decoded = unquote(url_lower)

print(f"Original: {url}")
print(f"Decoded: {url_decoded}\n")

patterns = [
    r'nirf.*20[0-9]{2}',
    r'20[0-9]{2}.*nirf',
    r'/static/media/.*20[0-9]{8}',  # Updated: removed \.pdf requirement
    r'/static/media/.*(?:ropar|iit|institute).*20[0-9]{8}',
    r'20[0-9]{8}[-_\s].*(?:Ov|ov|overall|engg|engineering)',  # Updated: added [-_\s]
    r'overall.*ranking',
    r'engineering.*ranking',
    r'india.*ranking.*framework',
    r'nirfindia\.org'
]

print("Pattern matching:")
for pattern in patterns:
    match = re.search(pattern, url_decoded)
    status = "✓" if match else "✗"
    print(f"{status} {pattern}")
    if match:
        print(f"  Matched: '{match.group()}'")
