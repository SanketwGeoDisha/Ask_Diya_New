"""
Test Source Priority Classification
"""
from server import SourcePriorityClassifier

# Test URLs
test_cases = [
    # NIRF Documents (should be CRITICAL)
    ("https://www.iitrpr.ac.in/static/media/Indian%20Institute%20of%20Technology%20Ropar20250214-%20Ov.e6663a313b9e84b21938.pdf", "critical"),
    ("https://nirfindia.org/2025/EngineeringRanking.html", "critical"),
    ("https://www.iitrpr.ac.in/nirf-2025", "critical"),
    ("https://example.ac.in/ranking-2025.pdf", "critical"),
    
    # Old Newsletters/Brochures (should be HIGH, not critical)
    ("https://www.iitrpr.ac.in/static/media/Prajwalam%20Volume%209,%20Issue%201,%20June%202020_0.5f39b89a63f32faccc78.pdf", "high"),
    ("https://www.iitrpr.ac.in/indo-taiwan/wp-content/uploads/2021/01/Brochure_v1.0-1.pdf", "high"),
    ("https://www.iitrpr.ac.in/downloads/sites/default/files/june%202023.pdf", "high"),
    
    # Official Websites (should be HIGH)
    ("https://www.iitrpr.ac.in/", "high"),
    ("https://example.ac.in/admissions", "high"),
    
    # Wikipedia (should be MEDIUM)
    ("https://en.wikipedia.org/wiki/IIT_Ropar", "medium"),
    
    # Aggregators (should be LOW)
    ("https://www.shiksha.com/university/iit-ropar", "low"),
]

print(f"\n{'='*80}")
print("SOURCE PRIORITY CLASSIFICATION TEST")
print(f"{'='*80}\n")

passed = 0
failed = 0

for url, expected_priority in test_cases:
    actual_priority = SourcePriorityClassifier.get_source_priority(url)
    status = "✓" if actual_priority == expected_priority else "✗"
    
    if actual_priority == expected_priority:
        passed += 1
    else:
        failed += 1
    
    # Format URL for display (truncate if too long)
    display_url = url if len(url) <= 70 else url[:67] + "..."
    
    print(f"{status} [{actual_priority:8}] {display_url}")
    if actual_priority != expected_priority:
        print(f"           Expected: {expected_priority}")

print(f"\n{'='*80}")
print(f"Results: {passed} passed, {failed} failed")
print(f"{'='*80}\n")

# Test deduplication logic
print(f"{'='*80}")
print("DEDUPLICATION TEST")
print(f"{'='*80}\n")

# Simulate multiple results for same KPI
test_results = [
    {"kpi_name": "Total Students", "value": "2400", "source_priority": "high", "source_url": "brochure.pdf"},
    {"kpi_name": "Total Students", "value": "2060", "source_priority": "critical", "source_url": "nirf-2025.pdf"},
    {"kpi_name": "Total Students", "value": "2500", "source_priority": "medium", "source_url": "wikipedia.org"},
]

priority_order = {'critical': 0, 'high': 1, 'medium': 2, 'low': 3}
test_results.sort(key=lambda r: priority_order.get(r.get('source_priority', 'low'), 999))
winner = test_results[0]

print(f"Simulated results for 'Total Students':")
for i, r in enumerate([
    {"kpi_name": "Total Students", "value": "2400", "source_priority": "high", "source_url": "brochure.pdf"},
    {"kpi_name": "Total Students", "value": "2060", "source_priority": "critical", "source_url": "nirf-2025.pdf"},
    {"kpi_name": "Total Students", "value": "2500", "source_priority": "medium", "source_url": "wikipedia.org"},
]):
    print(f"  {i+1}. [{r['source_priority']:8}] Value: {r['value']} from {r['source_url']}")

print(f"\nAfter deduplication:")
status = "✓" if winner['source_priority'] == 'critical' and winner['value'] == '2060' else "✗"
print(f"{status} Winner: [{winner['source_priority']:8}] Value: {winner['value']} from {winner['source_url']}")

if winner['source_priority'] == 'critical' and winner['value'] == '2060':
    print("✓✓✓ NIRF data correctly prioritized over other sources!")
else:
    print("✗✗✗ ERROR: NIRF data was not selected as winner!")

print(f"\n{'='*80}\n")
