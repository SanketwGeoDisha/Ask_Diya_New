"""
Quick test to verify the NIRF collector will now find the IIT Bombay PDF
"""
import asyncio
from nirf_collector import NIRFCollector

async def test():
    """Test NIRF collection for IIT Bombay with the fix"""
    
    print("="*80)
    print("TESTING IIT BOMBAY NIRF COLLECTION WITH FIX")
    print("="*80)
    print()
    
    collector = NIRFCollector(max_depth=4, max_urls=1000)
    
    college_name = "IIT Bombay"
    base_url = "https://www.iitb.ac.in/"
    target_pdf = "https://www.iitb.ac.in/sites/www.iitb.ac.in/files/2025-02/NIRF_IITBombay_2025_Overall_Category_0.pdf"
    
    print(f"College: {college_name}")
    print(f"Website: {base_url}")
    print(f"Target PDF: {target_pdf}")
    print()
    print("Starting collection...")
    print()
    
    results = await collector.collect_nirf_data(college_name, base_url)
    
    # Check if target PDF was found
    all_urls = {doc.url for doc in results['all']}
    found = target_pdf in all_urls
    
    print()
    print("="*80)
    print("RESULTS:")
    print("="*80)
    print(f"Total NIRF documents: {len(results['all'])}")
    print(f"Target PDF found: {'✓✓✓ YES' if found else '✗ NO'}")
    
    if found:
        # Find the document details
        for doc in results['all']:
            if doc.url == target_pdf:
                print()
                print("Target PDF details:")
                print(f"  Title: {doc.title}")
                print(f"  Year: {doc.year}")
                print(f"  Category: {doc.category}")
                print(f"  Priority Score: {doc.priority_score}")
                print(f"  Source: {doc.source}")
                break
    
    # Show all 2025 PDFs found
    print()
    print("All 2025 NIRF documents found:")
    nirf_2025 = [doc for doc in results['all'] if doc.year == 2025]
    if nirf_2025:
        for doc in nirf_2025:
            print(f"  - [{doc.category or 'N/A'}] {doc.url}")
    else:
        print("  (None)")
    
    print()
    print("="*80)
    if found:
        print("✓✓✓ SUCCESS! The fix is working in the full collection flow")
    else:
        print("✗ Issue: PDF not found in collection results")
    print("="*80)

if __name__ == "__main__":
    asyncio.run(test())
