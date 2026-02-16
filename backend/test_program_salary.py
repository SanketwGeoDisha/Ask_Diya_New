#!/usr/bin/env python3
"""
Test program-wise multi-year salary extraction from NIRF PDF
"""

import asyncio
import sys
from pathlib import Path

# Add backend to path
sys.path.insert(0, str(Path(__file__).parent))

from advanced_nirf_extractor import AdvancedNIRFExtractor
import PyPDF2
import json


async def test_program_salary_extraction():
    """Test extraction of program-wise 3-year salary data from IIT Ropar NIRF PDF"""
    
    # IIT Ropar NIRF 2025 PDF URL
    pdf_url = "https://www.iitrpr.ac.in/static/media/Indian%20Institute%20of%20Technology%20Ropar20250214-%20Ov.e6663a313b9e84b21938.pdf"
    
    print("=" * 80)
    print("TESTING PROGRAM-WISE MULTI-YEAR SALARY EXTRACTION")
    print("=" * 80)
    print(f"\n📄 PDF: {pdf_url}\n")
    
    # For this test, we'll use a mock text since we can't download in test
    # In production, the PDF would be downloaded and extracted
    mock_nirf_text = """
    PROGRAM WISE PERFORMANCE
    
    Computer Science & Engineering
    Placement & Higher Studies
    
    Year 2023-24: Intake 100 Admitted 98 Graduated 95 Placed 85 Median Salary 1219000 Higher Studies 8
    Year 2022-23: Intake 100 Admitted 97 Graduated 94 Placed 82 Median Salary 1150000 Higher Studies 9
    Year 2021-22: Intake 95 Admitted 94 Graduated 92 Placed 80 Median Salary 1103000 Higher Studies 8
    
    Electrical Engineering
    Placement & Higher Studies
    
    Year 2023-24: Intake 90 Admitted 88 Graduated 85 Placed 75 Median Salary 1098000 Higher Studies 7
    Year 2022-23: Intake 90 Admitted 87 Graduated 84 Placed 73 Median Salary 1045000 Higher Studies 6
    Year 2021-22: Intake 85 Admitted 84 Graduated 82 Placed 71 Median Salary 998000 Higher Studies 7
    
    Mechanical Engineering
    Placement & Higher Studies
    
    Year 2023-24: Intake 80 Admitted 78 Graduated 76 Placed 68 Median Salary 987000 Higher Studies 5
    Year 2022-23: Intake 80 Admitted 77 Graduated 75 Placed 66 Median Salary 945000 Higher Studies 6
    Year 2021-22: Intake 75 Admitted 74 Graduated 72 Placed 63 Median Salary 912000 Higher Studies 5
    """
    
    print("📥 Extracting data from NIRF text...")
    extractor = AdvancedNIRFExtractor(mock_nirf_text)
    nirf_data = extractor.extract_all_kpis()
    extracted_dict = extractor.to_dict()
    
    print("\n✅ Extraction complete!")
    print(f"   Total placement records extracted: {len(extractor.data.placement_details)}")
    
    # Get program-wise salary data
    program_salary_3yr = extracted_dict.get('program_wise_salary_3yr', {})
    
    print("\n" + "=" * 80)
    print("PROGRAM-WISE MEDIAN SALARY (LAST 3 YEARS)")
    print("=" * 80)
    
    if program_salary_3yr:
        for program, years_data in program_salary_3yr.items():
            print(f"\n📚 {program}:")
            for year in sorted(years_data.keys(), reverse=True):
                salary = years_data[year]
                salary_lpa = salary / 100000
                print(f"   {year}: ₹{salary:,} ({salary_lpa:.2f} LPA)")
    else:
        print("❌ No program-wise salary data extracted!")
        return False
    
    # Verify data structure
    print("\n" + "=" * 80)
    print("DATA STRUCTURE VALIDATION")
    print("=" * 80)
    
    checks = []
    
    # Check 1: Is it a dictionary?
    is_dict = isinstance(program_salary_3yr, dict)
    checks.append(("Data type is dict", is_dict))
    print(f"{'✅' if is_dict else '❌'} Data type is dict: {is_dict}")
    
    # Check 2: Has programs?
    has_programs = len(program_salary_3yr) > 0
    checks.append(("Has programs", has_programs))
    print(f"{'✅' if has_programs else '❌'} Has programs: {len(program_salary_3yr)}")
    
    # Check 3: Each program has years?
    has_years = all(isinstance(years, dict) and len(years) > 0 for years in program_salary_3yr.values())
    checks.append(("Each program has year data", has_years))
    print(f"{'✅' if has_years else '❌'} Each program has year data: {has_years}")
    
    # Check 4: Years are strings (2023, 2024, 2025)?
    valid_years = all(
        all(year in ['2023', '2024', '2025'] for year in years.keys())
        for years in program_salary_3yr.values()
    )
    checks.append(("Years are in valid format", valid_years))
    print(f"{'✅' if valid_years else '❌'} Years are in valid format (2023-2025): {valid_years}")
    
    # Check 5: Salaries are integers?
    valid_salaries = all(
        all(isinstance(salary, int) and salary > 0 for salary in years.values())
        for years in program_salary_3yr.values()
    )
    checks.append(("Salaries are positive integers", valid_salaries))
    print(f"{'✅' if valid_salaries else '❌'} Salaries are positive integers: {valid_salaries}")
    
    # Check 6: JSON serializable?
    try:
        json_str = json.dumps(program_salary_3yr)
        json_valid = True
    except:
        json_valid = False
    checks.append(("JSON serializable", json_valid))
    print(f"{'✅' if json_valid else '❌'} JSON serializable: {json_valid}")
    
    # Final result
    all_passed = all(check[1] for check in checks)
    
    print("\n" + "=" * 80)
    if all_passed:
        print("✅ ALL CHECKS PASSED! Program-wise salary extraction working correctly.")
        print("=" * 80)
        
        # Show JSON output
        print("\n📤 JSON Output:")
        print(json.dumps(program_salary_3yr, indent=2))
        return True
    else:
        print("❌ SOME CHECKS FAILED! Please review the extraction logic.")
        print("=" * 80)
        return False


if __name__ == "__main__":
    success = asyncio.run(test_program_salary_extraction())
    sys.exit(0 if success else 1)
