"""
Test updated Drupal pattern generation with name variations
"""

def _get_institution_name_variations(base_name: str):
    """Generate institution name variations"""
    base_lower = base_name.lower()
    base_upper = base_name.upper()
    
    # Known institution mappings
    known_names = {
        'iitb': ['IITBombay', 'IITB', 'IIT_Bombay', 'IIT-Bombay'],
        'iitd': ['IITDelhi', 'IITD', 'IIT_Delhi', 'IIT-Delhi'],
        'iitm': ['IITMadras', 'IITM', 'IIT_Madras', 'IIT-Madras'],
        'iitk': ['IITKanpur', 'IITK', 'IIT_Kanpur', 'IIT-Kanpur'],
        'iitkgp': ['IITKharagpur', 'IITKGP', 'IIT_Kharagpur', 'IIT-Kharagpur'],
        'iitbhu': ['IITBHU', 'IIT_BHU', 'IIT-BHU', 'IITBHUVaranasi'],
        'iitg': ['IITGuwahati', 'IITG', 'IIT_Guwahati', 'IIT-Guwahati'],
        'iitr': ['IITRoorkee', 'IITR', 'IIT_Roorkee', 'IIT-Roorkee'],
        'iith': ['IITHyderabad', 'IITH', 'IIT_Hyderabad', 'IIT-Hyderabad'],
        'iiti': ['IITIndore', 'IITI', 'IIT_Indore', 'IIT-Indore'],
        'nit': ['NIT', base_upper, f'NIT_{base_upper}'],
        'rvce': ['RVCE', 'RVCollege', 'RV_College'],
        'bits': ['BITS', 'BITSPilani', 'BITS_Pilani'],
        'vit': ['VIT', 'VITVellore', 'VIT_Vellore'],
        'dtu': ['DTU', 'DelhiTech', 'Delhi_Tech'],
        'nsut': ['NSUT', 'NetajiSubhas', 'NSIT'],
    }
    
    # Check if we have a known mapping
    if base_lower in known_names:
        return known_names[base_lower]
    
    # Check if it starts with known patterns
    for key in known_names:
        if base_lower.startswith(key):
            return known_names[key]
    
    # Default variations
    return [
        base_upper,
        base_name,
        base_name.title(),
    ]

# Test with IIT Bombay
domain = "www.iitb.ac.in"
target_filename = "NIRF_IITBombay_2025_Overall_Category_0.pdf"

base_name = domain.replace('www.', '').split('.')[0]
print(f"Domain: {domain}")
print(f"Base name extracted: {base_name}")
print(f"Target filename: {target_filename}\n")

variations = _get_institution_name_variations(base_name)
print(f"Name variations generated: {variations}\n")

# Check if target name is in variations
target_name = "IITBombay"
if target_name in variations:
    print(f"✓✓✓ SUCCESS! '{target_name}' is in name variations")
else:
    print(f"✗ '{target_name}' NOT in variations")

# Generate a sample pattern
print(f"\nSample generated URLs:")
for var in variations[:3]:
    url = f"/sites/{domain}/files/2025-02/NIRF_{var}_2025_Overall_Category_0.pdf"
    if var == target_name:
        print(f"  ✓ {url}  <-- MATCHES TARGET")
    else:
        print(f"    {url}")
