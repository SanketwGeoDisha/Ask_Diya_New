"""
Quick check: Fetch IIT Bombay homepage and look for NIRF links
"""
import asyncio
import aiohttp
import re
from urllib.parse import urljoin

async def check_iitb_homepage():
    """Check IIT Bombay homepage for NIRF links"""
    
    base_url = "https://www.iitb.ac.in/"
    target_pdf = "https://www.iitb.ac.in/sites/www.iitb.ac.in/files/2025-02/NIRF_IITBombay_2025_Overall_Category_0.pdf"
    
    print(f"Fetching IIT Bombay homepage: {base_url}\n")
    
    timeout = aiohttp.ClientTimeout(total=30)
    headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'}
    
    try:
        async with aiohttp.ClientSession(timeout=timeout, headers=headers) as session:
            async with session.get(base_url, ssl=False) as response:
                if response.status == 200:
                    html = await response.text()
                    
                    print(f"✓ Successfully fetched homepage ({len(html)} bytes)\n")
                    
                    # Check if target PDF is directly linked
                    if target_pdf in html:
                        print(f"✓ TARGET PDF IS LINKED IN HOMEPAGE!")
                        return
                    else:
                        print(f"✗ Target PDF not directly linked in homepage\n")
                    
                    # Look for any NIRF-related links
                    print("="*80)
                    print("NIRF-related links found on homepage:")
                    print("="*80)
                    
                    # Find all links
                    href_pattern = re.compile(r'href=["\']([^"\']+)["\']', re.IGNORECASE)
                    nirf_links = []
                    
                    for match in href_pattern.findall(html):
                        if any(kw in match.lower() for kw in ['nirf', 'ranking', 'rank']):
                            abs_url = urljoin(base_url, match)
                            if abs_url not in nirf_links:
                                nirf_links.append(abs_url)
                    
                    if nirf_links:
                        for link in nirf_links[:20]:  # Show first 20
                            print(f"  - {link}")
                        
                        if len(nirf_links) > 20:
                            print(f"  ... and {len(nirf_links) - 20} more")
                        
                        # Check each NIRF page for the target PDF
                        print(f"\n{'='*80}")
                        print(f"Checking NIRF pages for target PDF...")
                        print(f"{'='*80}\n")
                        
                        for link in nirf_links[:5]:  # Check first 5 NIRF pages
                            print(f"Checking: {link}")
                            try:
                                async with session.get(link, ssl=False, timeout=aiohttp.ClientTimeout(total=10)) as resp2:
                                    if resp2.status == 200:
                                        page_html = await resp2.text()
                                        if target_pdf in page_html:
                                            print(f"  ✓✓✓ FOUND! Target PDF is linked from this page!")
                                            return
                                        else:
                                            # Look for any PDFs with 2025
                                            pdf_2025_pattern = re.compile(r'href=["\']([^"\']*2025[^"\']*\.pdf)["\']', re.IGNORECASE)
                                            pdfs_2025 = pdf_2025_pattern.findall(page_html)
                                            if pdfs_2025:
                                                print(f"  Found {len(pdfs_2025)} PDFs with '2025':")
                                                for pdf in pdfs_2025[:3]:
                                                    abs_pdf = urljoin(link, pdf)
                                                    print(f"    - {abs_pdf}")
                                            else:
                                                print(f"  No 2025 PDFs found on this page")
                            except Exception as e:
                                print(f"  Error fetching page: {e}")
                                
                            await asyncio.sleep(0.2)
                    else:
                        print(f"  (No NIRF-related links found on homepage)")
                        
                        # Check if there's a common NIRF page directly
                        print(f"\n{'='*80}")
                        print(f"Trying direct NIRF URL patterns...")
                        print(f"{'='*80}\n")
                        
                        common_patterns = [
                            '/nirf', '/NIRF', '/ranking', '/Ranking', 
                            '/nirf-ranking', '/nirf-data'
                        ]
                        
                        for pattern in common_patterns:
                            url = base_url.rstrip('/') + pattern
                            print(f"Trying: {url}")
                            try:
                                async with session.get(url, ssl=False, allow_redirects=True, 
                                                      timeout=aiohttp.ClientTimeout(total=10)) as resp3:
                                    if resp3.status == 200:
                                        print(f"  ✓ Page exists! Checking for target PDF...")
                                        page_html = await resp3.text()
                                        if target_pdf in page_html:
                                            print(f"    ✓✓✓ FOUND! Target PDF is linked from {url}")
                                            return
                                        else:
                                            # Look for PDFs
                                            pdf_pattern = re.compile(r'href=["\']([^"\']*\.pdf)["\']', re.IGNORECASE)
                                            pdfs = pdf_pattern.findall(page_html)
                                            nirf_pdfs = [p for p in pdfs if 'nirf' in p.lower() or '2025' in p.lower()]
                                            if nirf_pdfs:
                                                print(f"    Found {len(nirf_pdfs)} NIRF/2025 PDFs:")
                                                for pdf in nirf_pdfs[:5]:
                                                    abs_pdf = urljoin(url, pdf)
                                                    print(f"      - {abs_pdf}")
                                            else:
                                                print(f"    No NIRF PDFs found")
                                    else:
                                        print(f"  ✗ Page not found (status: {resp3.status})")
                            except Exception as e:
                                print(f"  ✗ Error: {e}")
                            
                            await asyncio.sleep(0.2)
                        
                else:
                    print(f"✗ Failed to fetch homepage (status: {response.status})")
                    
    except Exception as e:
        print(f"✗ Error: {e}")
    
    print(f"\n{'='*80}")
    print(f"CONCLUSION:")
    print(f"{'='*80}")
    print(f"The target PDF is not easily discoverable through standard crawling.")
    print(f"It's likely in a CMS directory (/sites/...) not linked from main pages.")
    print(f"\nRECOMMENDATION: Add Drupal-specific patterns to the URL probing logic.")

if __name__ == "__main__":
    asyncio.run(check_iitb_homepage())
