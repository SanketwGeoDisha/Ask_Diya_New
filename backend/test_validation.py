"""
Quick validation test for Phase 1.3 data validation layer
Run this to verify all validation functions work correctly
"""

import sys
from pathlib import Path

# Add backend to path
sys.path.insert(0, str(Path(__file__).parent))

from data_validator import (
    DataValidator,
    ConfidenceScorer,
    EvidenceQualityScorer,
    ConsistencyChecker,
    validate_kpi_result
)


def test_data_validator():
    """Test DataValidator class"""
    print("\n=== Testing DataValidator ===")
    
    # Test percentage validation
    is_valid, reason, value = DataValidator.validate_value("Placement Rate", "85.5%")
    print(f"✓ Percentage: {value} - {reason} (Valid: {is_valid})")
    assert is_valid and value == 85.5
    
    # Test year validation
    is_valid, reason, value = DataValidator.validate_value("Established Year", "Founded in 2005")
    print(f"✓ Year: {value} - {reason} (Valid: {is_valid})")
    assert is_valid and value == 2005
    
    # Test currency validation
    is_valid, reason, value = DataValidator.validate_value("Median Compensation", "12 LPA")
    print(f"✓ Currency: {value} rupees - {reason} (Valid: {is_valid})")
    assert is_valid and value == 1200000
    
    # Test count validation
    is_valid, reason, value = DataValidator.validate_value("Total Students", "2,500 students")
    print(f"✓ Count: {value} - {reason} (Valid: {is_valid})")
    assert is_valid and value == 2500
    
    # Test invalid percentage
    is_valid, reason, value = DataValidator.validate_value("Pass Rate", "150%")
    print(f"✓ Invalid percentage: {reason} (Valid: {is_valid})")
    assert not is_valid
    
    print("✅ DataValidator: All tests passed!")


def test_confidence_scorer():
    """Test ConfidenceScorer class"""
    print("\n=== Testing ConfidenceScorer ===")
    
    # Test high confidence scenario
    level, score, breakdown = ConfidenceScorer.calculate_system_confidence(
        source_priority="official_website",
        recency="recent",
        value_validated=True,
        evidence_length_ok=True,
        value_in_evidence=True,
        llm_confidence="high"
    )
    print(f"✓ High scenario: {level} (score: {score})")
    assert level == "high" and score >= 0.8
    
    # Test low confidence scenario
    level, score, breakdown = ConfidenceScorer.calculate_system_confidence(
        source_priority="third_party",
        recency="old",
        value_validated=False,
        evidence_length_ok=False,
        value_in_evidence=False,
        llm_confidence="low"
    )
    print(f"✓ Low scenario: {level} (score: {score})")
    assert level == "low" and score < 0.6
    
    print("✅ ConfidenceScorer: All tests passed!")


def test_evidence_quality_scorer():
    """Test EvidenceQualityScorer class"""
    print("\n=== Testing EvidenceQualityScorer ===")
    
    # Test high quality evidence
    evidence = "The college achieved 85% placement rate in 2025 with 450 students placed out of 529 graduates."
    score, breakdown = EvidenceQualityScorer.score_evidence(
        evidence=evidence,
        value="85%",
        source_url="https://college.ac.in/placements",
        kpi_name="Placement Rate"
    )
    print(f"✓ High quality evidence: {score} (breakdown: {breakdown})")
    assert score >= 0.7
    
    # Test low quality evidence
    evidence = "N/A"
    score, breakdown = EvidenceQualityScorer.score_evidence(
        evidence=evidence,
        value="85%",
        source_url="https://college.ac.in",
        kpi_name="Placement Rate"
    )
    print(f"✓ Low quality evidence: {score}")
    assert score < 0.5
    
    print("✅ EvidenceQualityScorer: All tests passed!")


def test_consistency_checker():
    """Test ConsistencyChecker class"""
    print("\n=== Testing ConsistencyChecker ===")
    
    # Test placement consistency - invalid case
    kpis = {
        "Total Graduate Students (2025)": {"value": "500"},
        "Placed Students Count": {"value": "600"},  # More than total!
        "Placement Rate": {"value": "95%"}
    }
    warnings = ConsistencyChecker.check_placement_consistency(kpis)
    print(f"✓ Inconsistent placement: {len(warnings)} warnings")
    assert len(warnings) > 0
    
    # Test year consistency - future year
    kpis = {
        "Established Year": {"value": "2027"}  # Future year!
    }
    warnings = ConsistencyChecker.check_year_consistency(kpis)
    print(f"✓ Future year: {len(warnings)} warnings")
    assert len(warnings) > 0
    
    print("✅ ConsistencyChecker: All tests passed!")


def test_validate_kpi_result():
    """Test the main validation function"""
    print("\n=== Testing validate_kpi_result ===")
    
    result = {
        "kpi_name": "Placement Rate",
        "value": "85%",
        "evidence_quote": "The college achieved 85% placement rate in 2025 with 450 students placed.",
        "source_url": "https://college.ac.in/placements",
        "source_priority": "official_website",
        "recency": "recent",
        "llm_confidence": "high"
    }
    
    enhanced = validate_kpi_result(result)
    
    print(f"✓ Validation status: {enhanced['validation']['is_valid']}")
    print(f"✓ Normalized value: {enhanced['validation']['normalized_value']}")
    print(f"✓ Evidence quality: {enhanced['quality_scores']['evidence_quality']}")
    print(f"✓ Confidence score: {enhanced['confidence_score']}")
    print(f"✓ System confidence: {enhanced['system_confidence']}")
    
    assert enhanced['validation']['is_valid']
    assert 'quality_scores' in enhanced
    assert 'confidence_score' in enhanced
    
    print("✅ validate_kpi_result: All tests passed!")


def test_value_evidence_match():
    """Test value-evidence matching"""
    print("\n=== Testing Value-Evidence Matching ===")
    
    # Direct match
    has_match, score = DataValidator.check_value_evidence_match(
        "85%",
        "The placement rate is 85% for this year"
    )
    print(f"✓ Direct match: score={score} (has_match: {has_match})")
    assert has_match and score == 1.0
    
    # Numeric match
    has_match, score = DataValidator.check_value_evidence_match(
        "12 LPA",
        "Median salary was 12 lakhs per annum"
    )
    print(f"✓ Numeric match: score={score} (has_match: {has_match})")
    assert has_match and score >= 0.8
    
    # No match
    has_match, score = DataValidator.check_value_evidence_match(
        "85%",
        "The college is located in Delhi"
    )
    print(f"✓ No match: score={score} (has_match: {has_match})")
    assert not has_match
    
    print("✅ Value-Evidence Matching: All tests passed!")


def run_all_tests():
    """Run all validation tests"""
    print("=" * 60)
    print("Phase 1.3 Data Validation Layer - Test Suite")
    print("=" * 60)
    
    try:
        test_data_validator()
        test_confidence_scorer()
        test_evidence_quality_scorer()
        test_consistency_checker()
        test_validate_kpi_result()
        test_value_evidence_match()
        
        print("\n" + "=" * 60)
        print("✅ ALL TESTS PASSED! Phase 1.3 validation is working correctly.")
        print("=" * 60)
        return True
        
    except AssertionError as e:
        print(f"\n❌ TEST FAILED: {e}")
        return False
    except Exception as e:
        print(f"\n❌ ERROR: {e}")
        import traceback
        traceback.print_exc()
        return False


if __name__ == "__main__":
    success = run_all_tests()
    sys.exit(0 if success else 1)
