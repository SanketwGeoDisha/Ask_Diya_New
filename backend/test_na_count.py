"""
Test N/A counting in audit summary
"""

# Simulate audit results with various statuses
results = [
    {"kpi_name": "KPI1", "value": "100", "category": "Academic"},
    {"kpi_name": "KPI2", "value": "N/A", "category": "Academic"},
    {"kpi_name": "KPI3", "value": "200", "category": "Faculty"},
    {"kpi_name": "KPI4", "value": "N/A", "category": "Faculty"},
    {"kpi_name": "KPI5", "value": "N/A", "category": "Faculty"},
    {"kpi_name": "KPI6", "value": "Data Not Found", "category": "Placements"},
    {"kpi_name": "KPI7", "value": "300", "category": "Placements"},
    {"kpi_name": "KPI8", "value": "error", "category": "Infrastructure"},
    {"kpi_name": "KPI9", "value": "N/A", "category": "Infrastructure"},
    {"kpi_name": "KPI10", "value": "500", "category": "Infrastructure"},
]

total = len(results)

# Count data availability with explicit N/A tracking
na_count = 0
found_count = 0
error_count = 0

for r in results:
    value = str(r.get('value', '')).strip().lower()
    if value in ['n/a', 'not available']:
        na_count += 1
    elif value in ['data not found', 'error', 'processing error', '']:
        error_count += 1
    else:
        found_count += 1

# Group by category
categories = {}
for r in results:
    cat = r.get('category', 'Other')
    if cat not in categories:
        categories[cat] = {'total': 0, 'found': 0, 'na': 0}
    categories[cat]['total'] += 1
    
    value = str(r.get('value', '')).strip().lower()
    if value in ['n/a', 'not available']:
        categories[cat]['na'] += 1
    elif value not in ['data not found', 'error', 'processing error', '']:
        categories[cat]['found'] += 1

print(f"\n{'='*60}")
print("AUDIT SUMMARY TEST")
print(f"{'='*60}\n")

print(f"Total KPIs: {total}")
print(f"Data Found: {found_count} ({round((found_count/total)*100, 1)}%)")
print(f"N/A Count: {na_count} ({round((na_count/total)*100, 1)}%)")
print(f"Error Count: {error_count} ({round((error_count/total)*100, 1)}%)")
print(f"Total Unavailable: {na_count + error_count}")

print(f"\n{'='*60}")
print("BY CATEGORY")
print(f"{'='*60}\n")

for cat, stats in categories.items():
    print(f"{cat}:")
    print(f"  Total: {stats['total']}")
    print(f"  Found: {stats['found']}")
    print(f"  N/A: {stats['na']}")
    missing = stats['total'] - stats['found'] - stats['na']
    if missing > 0:
        print(f"  Other Missing: {missing}")

print(f"\n{'='*60}\n")

# Verify calculations
expected_na = 4  # KPI2, KPI4, KPI5, KPI9
expected_found = 4  # KPI1, KPI3, KPI7, KPI10
expected_error = 2  # KPI6, KPI8

if na_count == expected_na and found_count == expected_found and error_count == expected_error:
    print("✓✓✓ ALL COUNTS CORRECT!")
else:
    print("✗✗✗ COUNT MISMATCH!")
    print(f"  Expected: N/A={expected_na}, Found={expected_found}, Error={expected_error}")
    print(f"  Got: N/A={na_count}, Found={found_count}, Error={error_count}")
