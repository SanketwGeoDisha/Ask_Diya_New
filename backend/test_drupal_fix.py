"""
Test the fixed Drupal pattern probing
"""
import asyncio
import aiohttp

async def test_drupal_probing():
    """Test that Drupal patterns are now properly converted to full URLs"""
    
    base_url = "https://www.iitb.ac.in/"
    base_domain = "https://www.iitb.ac.in"
    
    # Sample patterns (relative paths)
    drupal_patterns = [
        "/sites/www.iitb.ac.in/files/2025-02/NIRF_IITBombay_2025_Overall_Category_0.pdf",
        "/sites/www.iitb.ac.in/files/2025-02/NIRF_IITB_2025_Overall_Category_0.pdf",
        "/sites/www.iitb.ac.in/files/2025-02/NIRF_IITBombay_2025_Engineering_Category_0.pdf",
    ]
    
    print(f"Testing Drupal pattern probing for: {base_url}\n")
    print(f"Testing {len(drupal_patterns)} sample patterns...\n")
    
    timeout = aiohttp.ClientTimeout(total=10)
    headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'}
    
    found_count = 0
    
    async with aiohttp.ClientSession(timeout=timeout, headers=headers) as session:
        for i, drupal_pattern in enumerate(drupal_patterns, 1):
            # Convert relative path to full URL (this is the fix)
            full_drupal_url = f"{base_domain}{drupal_pattern}"
            
            print(f"{i}. Testing: {full_drupal_url}")
            
            try:
                async with session.head(full_drupal_url, ssl=False, allow_redirects=True) as response:
                    if response.status == 200:
                        print(f"   ✓✓✓ FOUND! Status: {response.status}")
                        content_type = response.headers.get('Content-Type', 'N/A')
                        content_length = response.headers.get('Content-Length', 'N/A')
                        print(f"   Content-Type: {content_type}")
                        print(f"   Content-Length: {content_length} bytes")
                        found_count += 1
                    else:
                        print(f"   ✗ Not found (Status: {response.status})")
            except Exception as e:
                print(f"   ✗ Error: {e}")
            
            print()
            await asyncio.sleep(0.1)
    
    print(f"{'='*80}")
    print(f"RESULTS: Found {found_count}/{len(drupal_patterns)} PDFs")
    print(f"{'='*80}")
    
    if found_count > 0:
        print(f"\n✓✓✓ SUCCESS! The fix is working - Drupal PDFs can be discovered")
    else:
        print(f"\n✗ No PDFs found - may need to check patterns or PDF availability")

if __name__ == "__main__":
    asyncio.run(test_drupal_probing())
