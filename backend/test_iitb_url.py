"""
Test why IIT Bombay 2025 NIRF PDF is not being picked up
"""
import re
from urllib.parse import unquote

def test_url_detection():
    """Test if the URL would be detected by nirf_collector logic"""
    
    url = "https://www.iitb.ac.in/sites/www.iitb.ac.in/files/2025-02/NIRF_IITBombay_2025_Overall_Category_0.pdf"
    
    print(f"Testing URL: {url}\n")
    
    # Test 1: Is it NIRF-related?
    url_lower = url.lower()
    url_normalized = url_lower.replace('%20', ' ').replace('-', ' ').replace('_', ' ')
    
    print("=== NIRF Detection Tests ===")
    
    # Direct indicators
    direct_indicators = [
        'nirf', 'ranking', 'national rank', 'india rank',
        'engineering.pdf', 'overall.pdf', 'management.pdf',
        'pharmacy.pdf', 'innovation.pdf'
    ]
    
    print(f"1. Direct indicators in URL:")
    for indicator in direct_indicators:
        if indicator in url_lower:
            print(f"   ✓ Found: '{indicator}'")
    
    # Test 2: Year extraction
    print(f"\n=== Year Extraction ===")
    year_patterns = [
        r'nirf[_-]?(202[0-9])',
        r'ranking[_-]?(202[0-9])',
        r'/(202[0-9])/',
        r'[_-](202[0-9])[_.-]',
        r'(202[0-9])(?:0[1-9]|1[0-2])(?:0[1-9]|[12][0-9]|3[01])',  # YYYYMMDD format
    ]
    
    decoded_url = unquote(url_lower)
    year_found = None
    
    for i, pattern in enumerate(year_patterns):
        match = re.search(pattern, decoded_url)
        if match:
            year_found = int(match.group(1))
            print(f"Pattern {i+1} matched: {pattern}")
            print(f"Extracted year: {year_found}")
            break
    
    if not year_found:
        # Fallback
        year_match = re.search(r'(202[0-7])', decoded_url)
        if year_match:
            year_found = int(year_match.group(1))
            print(f"Fallback pattern matched")
            print(f"Extracted year: {year_found}")
    
    # Test 3: Category detection
    print(f"\n=== Category Detection ===")
    category = None
    
    if 'engineering' in decoded_url or 'engg' in decoded_url:
        category = 'engineering'
    elif 'overall' in decoded_url or 'ov.' in decoded_url or ' ov' in decoded_url:
        category = 'overall'
    elif 'management' in decoded_url or 'mgmt' in decoded_url:
        category = 'management'
    
    print(f"Detected category: {category}")
    
    # Test 4: Priority score calculation
    print(f"\n=== Priority Score Calculation ===")
    score = 5.0  # Base score
    
    if year_found:
        if year_found == 2025:
            score += 10.0
            print(f"Year bonus (2025): +10.0")
        elif year_found == 2024:
            score += 2.0
            print(f"Year bonus (2024): +2.0")
    
    if category in ['overall', 'engineering']:
        score += 2.0
        print(f"Category bonus ({category}): +2.0")
    
    if url_lower.endswith('.pdf'):
        score += 3.0
        print(f"PDF bonus: +3.0")
    
    print(f"\nTotal priority score: {score}")
    
    # Test 5: Would it be filtered?
    print(f"\n=== URL Filtering ===")
    IGNORED_PATTERNS = [
        'login', 'signup', 'register', 'cart', 'checkout',
        'gallery', 'photo', 'video', 'event', 'notice',
        'admission', 'application', 'brochure', 'prospectus',
        'news', 'blog', 'article', 'announcement'
    ]
    
    ignored = any(pattern in url_lower for pattern in IGNORED_PATTERNS)
    print(f"Would be filtered out? {ignored}")
    
    # Final verdict
    print(f"\n{'='*50}")
    print(f"FINAL VERDICT:")
    print(f"{'='*50}")
    print(f"✓ URL contains NIRF indicators: YES")
    print(f"✓ Year extracted: {year_found}")
    print(f"✓ Category detected: {category}")
    print(f"✓ Priority score: {score}")
    print(f"✓ Would be included: {'YES' if not ignored else 'NO'}")
    
    print(f"\n{'='*50}")
    print(f"DIAGNOSIS:")
    print(f"{'='*50}")
    print(f"This URL SHOULD be detected if it's discovered during crawling.")
    print(f"\nPossible reasons it's not being picked up:")
    print(f"1. URL not found during site crawl (check if /nirf page exists)")
    print(f"2. URL not in sitemap.xml")
    print(f"3. PDF link not extracted from parent pages")
    print(f"4. Path /sites/www.iitb.ac.in/files/ is unusual Drupal structure")
    print(f"   and may not be linked from crawlable pages")


if __name__ == "__main__":
    test_url_detection()
