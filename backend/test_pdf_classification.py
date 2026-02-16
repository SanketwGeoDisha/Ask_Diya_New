"""
Test NIRF collector with actual IIT Ropar PDF URL
"""
import asyncio
from nirf_collector import NIRFCollector

async def test_iit_ropar_pdf():
    """Test if collector recognizes and classifies IIT Ropar NIRF PDF"""
    collector = NIRFCollector()
    
    # Actual IIT Ropar NIRF PDF URL provided by user
    test_url = "https://www.iitrpr.ac.in/static/media/Indian%20Institute%20of%20Technology%20Ropar20250214-%20Ov.e6663a313b9e84b21938.pdf"
    
    print(f"\n{'='*80}")
    print("Testing PDF URL Recognition")
    print(f"{'='*80}\n")
    print(f"URL: {test_url}\n")
    
    # Test if URL is recognized as NIRF-related
    is_nirf = collector._is_nirf_related(test_url)
    print(f"✓ Is NIRF-related: {is_nirf}")
    
    if is_nirf:
        # Classify the URL
        docs = collector._classify_urls([test_url], "https://www.iitrpr.ac.in")
        
        if docs:
            doc = docs[0]
            print(f"\n{'='*80}")
            print("Document Classification")
            print(f"{'='*80}\n")
            print(f"Title: {doc.title}")
            print(f"Type: {doc.doc_type}")
            print(f"Year: {doc.year}")
            print(f"Category: {doc.category}")
            print(f"Priority Score: {doc.priority_score}")
            print(f"Source: {doc.source}")
            
            # Verify correct extraction
            print(f"\n{'='*80}")
            print("Verification")
            print(f"{'='*80}\n")
            
            checks = {
                "Year = 2025": doc.year == 2025,
                "Category = 'overall'": doc.category == 'overall',
                "Type = 'pdf'": doc.doc_type == 'pdf',
                "High priority (>= 15)": doc.priority_score >= 15.0
            }
            
            for check, passed in checks.items():
                status = "✓" if passed else "✗"
                print(f"{status} {check}")
            
            all_passed = all(checks.values())
            print(f"\n{'='*80}")
            if all_passed:
                print("✓✓✓ ALL CHECKS PASSED - PDF correctly classified!")
            else:
                print("✗✗✗ SOME CHECKS FAILED - Review classification logic")
            print(f"{'='*80}\n")
        else:
            print("\n✗ FAILED - URL not classified as document")
    else:
        print("\n✗ FAILED - URL not recognized as NIRF-related")
        print("This means the _is_nirf_related() method needs improvement")

if __name__ == "__main__":
    asyncio.run(test_iit_ropar_pdf())
