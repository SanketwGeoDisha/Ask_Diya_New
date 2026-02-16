"""
Quick performance test for optimized NIRF collector
"""
import asyncio
import time
from nirf_collector import NIRFCollector

async def test_performance():
    """Test NIRF collection performance after optimizations"""
    
    print("="*80)
    print("PERFORMANCE TEST: IIT Bombay NIRF Collection (Optimized)")
    print("="*80)
    print()
    
    collector = NIRFCollector(max_depth=4, max_urls=1000)
    
    college_name = "IIT Bombay"
    base_url = "https://www.iitb.ac.in/"
    
    print(f"College: {college_name}")
    print(f"Website: {base_url}")
    print()
    
    # Time the collection
    start_time = time.time()
    print(f"Starting collection at {time.strftime('%H:%M:%S')}...")
    print()
    
    results = await collector.collect_nirf_data(college_name, base_url)
    
    end_time = time.time()
    duration = end_time - start_time
    
    # Results
    print()
    print("="*80)
    print("PERFORMANCE RESULTS:")
    print("="*80)
    print(f"Total time: {duration:.2f} seconds")
    print(f"Total NIRF documents found: {len(results['all'])}")
    print(f"  - From nirfindia.org: {len(results['nirfindia'])}")
    print(f"  - From college website: {len(results['college_website'])}")
    print()
    
    # Check for target PDF
    target_pdf = "https://www.iitb.ac.in/sites/www.iitb.ac.in/files/2025-02/NIRF_IITBombay_2025_Overall_Category_0.pdf"
    found = any(doc.url == target_pdf for doc in results['all'])
    
    print(f"Target PDF found: {'✓ YES' if found else '✗ NO'}")
    
    if found:
        for doc in results['all']:
            if doc.url == target_pdf:
                print(f"  Year: {doc.year}")
                print(f"  Category: {doc.category}")
                print(f"  Priority: {doc.priority_score}")
    
    print()
    print("="*80)
    print("OPTIMIZATION SUMMARY:")
    print("="*80)
    print("✓ Reduced Drupal patterns from ~556 to ~60")
    print("✓ Parallel probing (20 URLs at a time)")
    print("✓ Early termination (stops after finding 3 PDFs)")
    print("✓ Skip Phase 3 crawl if PDFs already found")
    print("✓ Reduced timeouts (60s -> 30s)")
    print("✓ Removed slow URL verifications")
    print()
    
    # Performance rating
    if duration < 10:
        print("⚡ EXCELLENT: < 10 seconds")
    elif duration < 20:
        print("✓ GOOD: 10-20 seconds")
    elif duration < 30:
        print("⚠ ACCEPTABLE: 20-30 seconds")
    else:
        print("✗ SLOW: > 30 seconds (needs more optimization)")

if __name__ == "__main__":
    asyncio.run(test_performance())
