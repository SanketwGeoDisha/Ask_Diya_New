"""
Test if AdvancedNIRFExtractor can extract KPIs from actual IIT Ropar NIRF PDF
"""
from advanced_nirf_extractor import AdvancedNIRFExtractor
from pathlib import Path
import PyPDF2

def test_nirf_extraction():
    """Test extraction from actual NIRF PDF"""
    pdf_path = Path("Indian Institute of Technology Ropar20250214- Ov.e6663a313b9e84b21938.pdf")
    
    if not pdf_path.exists():
        print(f"✗ PDF not found: {pdf_path}")
        return
    
    print(f"\n{'='*80}")
    print(f"Testing NIRF Extraction")
    print(f"{'='*80}\n")
    print(f"PDF: {pdf_path.name}")
    print(f"Size: {pdf_path.stat().st_size / 1024:.1f} KB\n")
    
    try:
        # Read PDF content
        print("Reading PDF...")
        with open(pdf_path, 'rb') as f:
            pdf_reader = PyPDF2.PdfReader(f)
            pages = len(pdf_reader.pages)
            print(f"Pages: {pages}\n")
            
            text_content = ""
            for page in pdf_reader.pages:
                text_content += page.extract_text()
        
        print(f"Extracted {len(text_content)} characters of text\n")
        
        print(f"{'='*80}")
        print("Extracting all KPIs...")
        print(f"{'='*80}\n")
        
        extractor = AdvancedNIRFExtractor(text_content)
        nirf_data = extractor.extract_all_kpis()
        
        # Convert to dict for display
        print(f"{'='*80}")
        print("EXTRACTED DATA")
        print(f"{'='*80}\n")
        
        print(f"Institution: {nirf_data.institution_name}")
        print(f"NIRF ID: {nirf_data.nirf_id}\n")
        
        # Key metrics
        metrics = {
            "Total Graduates": nirf_data.total_graduates,
            "Total Placed": nirf_data.total_placed,
            "Max Compensation": f"₹{nirf_data.max_compensation:,}" if nirf_data.max_compensation else "N/A",
            "Median Compensation": f"₹{nirf_data.median_compensation:,}" if nirf_data.median_compensation else "N/A",
            "Higher Education": nirf_data.total_higher_education,
            "Total Students": nirf_data.total_students,
            "Female Students": nirf_data.female_students,
            "Total Faculty": nirf_data.total_faculty,
            "PhD Faculty": nirf_data.phd_faculty,
            "PhD Students": nirf_data.total_phd_students,
        }
        
        found_count = 0
        for key, value in metrics.items():
            if value and value not in [0, "₹0", "N/A", ""]:
                print(f"✓ {key}: {value}")
                found_count += 1
            else:
                print(f"  {key}: [Not Found]")
        
        print(f"\n{'='*80}")
        print(f"Success: {found_count}/{len(metrics)} key metrics extracted")
        print(f"{'='*80}\n")
    
    except Exception as e:
        print(f"✗ EXTRACTION FAILED: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    test_nirf_extraction()
