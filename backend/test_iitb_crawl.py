"""
Test actual crawling of IIT Bombay website to find NIRF documents
"""
import asyncio
import sys
import logging
from nirf_collector import NIRFCollector

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(levelname)s: %(message)s')

async def test_iitb_crawl():
    """Test NIRF collection for IIT Bombay"""
    
    college_name = "IIT Bombay"
    base_url = "https://www.iitb.ac.in/"
    target_url = "https://www.iitb.ac.in/sites/www.iitb.ac.in/files/2025-02/NIRF_IITBombay_2025_Overall_Category_0.pdf"
    
    print(f"{'='*80}")
    print(f"Testing NIRF Collection for: {college_name}")
    print(f"Website: {base_url}")
    print(f"Target URL we're looking for:")
    print(f"  {target_url}")
    print(f"{'='*80}\n")
    
    collector = NIRFCollector(max_depth=4, max_urls=1000)
    results = await collector.collect_nirf_data(college_name, base_url)
    
    # Check if target URL was found
    all_urls = {doc.url for doc in results['all']}
    found = target_url in all_urls
    
    print(f"\n{'='*80}")
    print(f"RESULTS SUMMARY:")
    print(f"{'='*80}")
    print(f"Total NIRF documents found: {len(results['all'])}")
    print(f"From nirfindia.org: {len(results['nirfindia'])}")
    print(f"From college website: {len(results['college_website'])}")
    print(f"\nTarget URL found? {'✓ YES' if found else '✗ NO'}")
    
    if found:
        # Find the document
        for doc in results['all']:
            if doc.url == target_url:
                print(f"\nTarget document details:")
                print(f"  Year: {doc.year}")
                print(f"  Category: {doc.category}")
                print(f"  Priority: {doc.priority_score}")
                print(f"  Source: {doc.source}")
                break
    else:
        print(f"\n{'='*80}")
        print(f"TARGET URL NOT FOUND - Investigation:")
        print(f"{'='*80}")
        
        # Check if similar URLs were found
        print(f"\nSimilar IIT Bombay 2025 URLs found:")
        for doc in results['all']:
            if '2025' in doc.url and 'iitb' in doc.url.lower():
                print(f"  - {doc.url}")
                print(f"    Year: {doc.year}, Category: {doc.category}, Score: {doc.priority_score}")
        
        # Show 2025 overall category PDFs
        print(f"\nAll 2025 Overall PDFs found:")
        overall_2025 = [doc for doc in results['all'] 
                       if doc.year == 2025 and doc.category == 'overall' and doc.doc_type == 'pdf']
        
        if overall_2025:
            for doc in overall_2025:
                print(f"  - {doc.url}")
        else:
            print(f"  (None found)")
        
        # Show top priority documents
        print(f"\nTop 10 priority documents found:")
        top_docs = sorted(results['all'], key=lambda x: x.priority_score, reverse=True)[:10]
        for i, doc in enumerate(top_docs, 1):
            print(f"  {i}. [{doc.year or 'N/A'}] {doc.title} (Score: {doc.priority_score})")
            print(f"     {doc.url[:100]}...")
    
    print(f"\n{'='*80}")
    print(f"RECOMMENDATION:")
    print(f"{'='*80}")
    
    if not found:
        print(f"""
The target URL is not being discovered during crawling. This suggests:

1. The PDF is not linked from pages the crawler can find
2. The URL may be in a Drupal /sites/ directory that's not in sitemap
3. The NIRF page may use JavaScript to load the PDF links

SOLUTIONS:
a) Check if IIT Bombay has a /nirf or /ranking page that links to this PDF
b) Manually add this URL as a known pattern for IIT Bombay
c) Enhance crawler to check Drupal-specific paths
   (e.g., /sites/[domain]/files/[year]-[month]/ pattern)
""")

if __name__ == "__main__":
    asyncio.run(test_iitb_crawl())
