"""
Test Drupal pattern generation for IIT Bombay
"""

def _generate_drupal_nirf_patterns(domain: str):
    """Test the Drupal pattern generation"""
    patterns = []
    
    # Current year and recent months
    year = 2025
    months = ['02', '03', '01', '04', '12']
    
    # Common NIRF filename patterns
    filename_templates = [
        "NIRF_{short}_2025_Overall_Category_0.pdf",
        "NIRF_{short}_2025_Engineering_Category_0.pdf",
        "NIRF_{short}_2025_Overall.pdf",
        "NIRF_{short}_2025_Engineering.pdf",
        "NIRF_2025_Overall.pdf",
        "NIRF_2025_Engineering.pdf",
        "NIRF_2025_Overall_Category.pdf",
        "nirf_2025_overall.pdf",
        "nirf_2025.pdf",
    ]
    
    # Extract abbreviation
    domain_parts = domain.replace('www.', '').split('.')
    short_name = domain_parts[0].upper() if domain_parts else 'Institute'
    
    # Generate patterns
    base_paths = [
        f"/sites/{domain}/files",
        f"/sites/default/files",
        "/files",
    ]
    
    for base_path in base_paths:
        for month in months:
            date_path = f"{year}-{month}"
            for template in filename_templates:
                filename = template.format(short=short_name)
                patterns.append(f"{base_path}/{date_path}/{filename}")
    
    # 2024 patterns
    for month in ['11', '12']:
        date_path = f"2024-{month}"
        for template in filename_templates:
            filename = template.format(short=short_name).replace('2025', '2024')
            patterns.append(f"/sites/{domain}/files/{date_path}/{filename}")
    
    return patterns

# Test with IIT Bombay
domain = "www.iitb.ac.in"
target = "/sites/www.iitb.ac.in/files/2025-02/NIRF_IITBombay_2025_Overall_Category_0.pdf"

print(f"Testing Drupal pattern generation for: {domain}")
print(f"Target URL path: {target}\n")

patterns = _generate_drupal_nirf_patterns(domain)

print(f"Generated {len(patterns)} patterns\n")

# Check if target is in patterns
found = False
for pattern in patterns:
    if pattern == target:
        print(f"✓✓✓ SUCCESS! Target pattern IS generated:")
        print(f"    {pattern}")
        found = True
        break

if not found:
    print(f"✗ Target pattern NOT found in generated patterns")
    print(f"\nClosest matches:")
    for pattern in patterns:
        if '2025-02' in pattern and 'Overall' in pattern:
            print(f"  {pattern}")
    
    print(f"\nTarget analysis:")
    print(f"  Month folder: 2025-02 ✓")
    print(f"  Filename: NIRF_IITBombay_2025_Overall_Category_0.pdf")
    print(f"  Short name extracted: IITB")
    print(f"  Expected: IITBombay")
    print(f"\n  ISSUE: Abbreviation extraction needs enhancement")
    print(f"         'iitb' -> 'IITB' but target uses 'IITBombay'")

print(f"\nFirst 15 generated patterns:")
for i, pattern in enumerate(patterns[:15], 1):
    print(f"  {i}. {pattern}")
