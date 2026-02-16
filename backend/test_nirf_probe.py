"""
Quick test for NIRF direct URL probing fix
"""
import asyncio
from nirf_collector import NIRFCollector

async def test_iit_ropar():
    """Test NIRF collection for IIT Ropar (React website)"""
    collector = NIRFCollector(timeout=30, max_depth=3, max_urls=500)
    
    college_name = "Indian Institute of Technology Ropar"
    base_url = "https://www.iitrpr.ac.in"
    
    print(f"\n{'='*80}")
    print(f"Testing NIRF Collection for: {college_name}")
    print(f"Base URL: {base_url}")
    print(f"{'='*80}\n")
    
    # Run collection
    results = await collector.collect_nirf_data(college_name, base_url)
    
    # Display results
    print(f"\n{'='*80}")
    print("COLLECTION RESULTS")
    print(f"{'='*80}\n")
    
    print(f"Total documents found: {len(results['all'])}")
    print(f"  - From nirfindia.org: {len(results['nirfindia'])}")
    print(f"  - From college website: {len(results['college_website'])}")
    
    if results['all']:
        print(f"\n{'='*80}")
        print("DOCUMENT DETAILS")
        print(f"{'='*80}\n")
        
        for i, doc in enumerate(results['all'][:10], 1):  # Show first 10
            print(f"{i}. {doc.title}")
            print(f"   URL: {doc.url}")
            print(f"   Type: {doc.doc_type} | Year: {doc.year} | Category: {doc.category}")
            print(f"   Priority: {doc.priority_score} | Source: {doc.source}")
            print()
    else:
        print("\n⚠️  NO DOCUMENTS FOUND - NIRF Collection Failed")
    
    print(f"\n{'='*80}\n")

if __name__ == "__main__":
    asyncio.run(test_iit_ropar())
