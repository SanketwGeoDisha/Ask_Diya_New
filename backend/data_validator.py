"""
Data Validation Layer for AskDiya v2
Validates extracted KPI data for consistency, completeness, and quality
"""

import re
from typing import Dict, Any, List, Optional, Tuple
from datetime import datetime
import logging

logger = logging.getLogger(__name__)


class DataValidator:
    """Comprehensive data validation for KPI values"""
    
    # Value range constraints for different KPI types
    VALID_RANGES = {
        "percentage": (0, 100),
        "year": (2015, 2026),  # Reasonable year range
        "currency_lpa": (0, 500),  # 0 to 5 Crore in LPA
        "count": (0, 1000000),  # Reasonable student/faculty count
        "ratio": (0, 1000),  # Student-faculty ratio, etc.
    }
    
    # KPI categories with their expected data types
    KPI_TYPE_MAPPING = {
        "percentage": ["Placement Rate", "Pass Percentage", "Research Output Rate", "Populated"],
        "year": ["Established Year", "Accreditation Year", "Latest Data Year"],
        "currency": ["Median Compensation", "Average Package", "Highest Package", "Funding", "Budget"],
        "count": ["Students", "Faculty", "Staff", "Papers", "Patents", "Citations"],
        "ratio": ["Student-Faculty Ratio", "PhD Faculty Percentage"],
        "text": ["Name", "Location", "Accreditation Body", "Affiliation"]
    }
    
    @staticmethod
    def detect_kpi_type(kpi_name: str) -> str:
        """Detect the expected data type for a KPI based on its name"""
        kpi_lower = kpi_name.lower()
        
        # Check for currency indicators
        if any(word in kpi_lower for word in ["compensation", "salary", "package", "ctc", "stipend", "funding", "budget", "revenue"]):
            return "currency"
        
        # Check for percentage indicators
        if any(word in kpi_lower for word in ["rate", "percentage", "%", "ratio of", "proportion"]):
            if "student-faculty" in kpi_lower or "faculty ratio" in kpi_lower:
                return "ratio"
            return "percentage"
        
        # Check for year indicators
        if any(word in kpi_lower for word in ["year", "established", "founded", "accredited"]):
            return "year"
        
        # Check for count indicators
        if any(word in kpi_lower for word in ["number", "count", "total", "students", "faculty", "staff", "papers", "patents"]):
            return "count"
        
        # Check for ratio indicators
        if "ratio" in kpi_lower and "student" in kpi_lower:
            return "ratio"
        
        # Default to text
        return "text"
    
    @staticmethod
    def validate_value(kpi_name: str, value: str, kpi_type: Optional[str] = None) -> Tuple[bool, str, Any]:
        """
        Validate a KPI value based on its type and expected range
        
        Returns:
            (is_valid, reason, normalized_value)
        """
        # Convert value to string if it's not already
        value_str = str(value) if not isinstance(value, str) else value
        if not value_str or value_str.strip() == "":
            return (False, "Value is empty", None)
        value = value_str
        
        if value.lower() in ["not found", "n/a", "na", "not available", "data not found"]:
            return (False, "Value indicates data not found", None)
        
        # Detect KPI type if not provided
        if kpi_type is None:
            kpi_type = DataValidator.detect_kpi_type(kpi_name)
        
        # Validate based on type
        if kpi_type == "percentage":
            return DataValidator._validate_percentage(value)
        elif kpi_type == "year":
            return DataValidator._validate_year(value)
        elif kpi_type == "currency":
            return DataValidator._validate_currency(value)
        elif kpi_type == "count":
            return DataValidator._validate_count(value)
        elif kpi_type == "ratio":
            return DataValidator._validate_ratio(value)
        else:  # text
            return DataValidator._validate_text(value)
    
    @staticmethod
    def _validate_percentage(value: str) -> Tuple[bool, str, Any]:
        """Validate percentage values (0-100)"""
        # Extract numeric value
        match = re.search(r'(\d+(?:\.\d+)?)\s*%?', value)
        if not match:
            return (False, "No numeric value found", None)
        
        try:
            num = float(match.group(1))
            
            if num < 0 or num > 100:
                return (False, f"Percentage {num} out of valid range (0-100)", num)
            
            return (True, "Valid percentage", round(num, 2))
        except ValueError:
            return (False, "Could not parse as number", None)
    
    @staticmethod
    def _validate_year(value: str) -> Tuple[bool, str, Any]:
        """Validate year values (2015-2026)"""
        # Extract 4-digit year
        match = re.search(r'\b(20\d{2})\b', value)
        if not match:
            return (False, "No valid year found", None)
        
        try:
            year = int(match.group(1))
            
            if year < 2015 or year > 2026:
                return (False, f"Year {year} out of reasonable range (2015-2026)", year)
            
            return (True, "Valid year", year)
        except ValueError:
            return (False, "Could not parse as year", None)
    
    @staticmethod
    def _validate_currency(value: str) -> Tuple[bool, str, Any]:
        """Validate currency values"""
        # Look for numeric values with currency indicators
        value_lower = value.lower()
        
        # Extract numbers
        match = re.search(r'(\d+(?:\.\d+)?)\s*(lpa|lakh|lakhs|cr|crore|crores|k|₹|rs\.?)?', value_lower)
        if not match:
            return (False, "No numeric value found", None)
        
        try:
            num = float(match.group(1))
            unit = match.group(2) if match.group(2) else ""
            
            # Normalize to rupees
            if "cr" in unit or "crore" in unit:
                rupees = num * 10000000
            elif "lpa" in unit:
                rupees = num * 100000
            elif "lakh" in unit or "lac" in unit:
                rupees = num * 100000
            elif "k" in unit:
                rupees = num * 1000
            else:
                rupees = num
            
            # Reasonable range: 0 to 100 crore
            if rupees < 0 or rupees > 1000000000:
                return (False, f"Currency value {rupees} out of reasonable range", rupees)
            
            return (True, "Valid currency", int(rupees))
        except ValueError:
            return (False, "Could not parse currency value", None)
    
    @staticmethod
    def _validate_count(value: str) -> Tuple[bool, str, Any]:
        """Validate count values (students, faculty, etc.)"""
        # Extract numeric value
        match = re.search(r'(\d+(?:,\d+)?)', value.replace(',', ''))
        if not match:
            return (False, "No numeric value found", None)
        
        try:
            num = int(match.group(1).replace(',', ''))
            
            if num < 0:
                return (False, "Count cannot be negative", num)
            
            if num > 1000000:
                return (False, f"Count {num} seems unreasonably high", num)
            
            return (True, "Valid count", num)
        except ValueError:
            return (False, "Could not parse as number", None)
    
    @staticmethod
    def _validate_ratio(value: str) -> Tuple[bool, str, Any]:
        """Validate ratio values (e.g., student-faculty ratio)"""
        # Look for patterns like "15:1" or "15" or "15.5"
        match = re.search(r'(\d+(?:\.\d+)?)\s*:?\s*\d*', value)
        if not match:
            return (False, "No numeric value found", None)
        
        try:
            num = float(match.group(1))
            
            if num < 0 or num > 1000:
                return (False, f"Ratio {num} out of reasonable range", num)
            
            return (True, "Valid ratio", round(num, 2))
        except ValueError:
            return (False, "Could not parse as number", None)
    
    @staticmethod
    def _validate_text(value: str) -> Tuple[bool, str, Any]:
        """Validate text values"""
        # Convert to string if needed
        value_str = str(value) if not isinstance(value, str) else value
        cleaned = value_str.strip()
        
        if len(cleaned) < 2:
            return (False, "Text too short", cleaned)
        
        if len(cleaned) > 500:
            return (False, "Text too long", cleaned[:500])
        
        return (True, "Valid text", cleaned)
    
    @staticmethod
    def validate_evidence_length(evidence: str) -> Tuple[bool, str]:
        """Check if evidence quote is of reasonable length"""
        if not evidence:
            return (False, "No evidence provided")
        
        if len(evidence) < 10:
            return (False, "Evidence too short (< 10 chars)")
        
        if len(evidence) > 1000:
            return (False, "Evidence too long (> 1000 chars)")
        
        return (True, "Evidence length acceptable")
    
    @staticmethod
    def check_value_evidence_match(value: str, evidence: str) -> Tuple[bool, float]:
        """
        Check if the extracted value appears in the evidence quote
        
        Returns:
            (has_match, similarity_score)
        """
        if not value or not evidence:
            return (False, 0.0)
        
        # Convert to strings if needed
        value_str = str(value) if not isinstance(value, str) else value
        evidence_str = str(evidence) if not isinstance(evidence, str) else evidence
        value_clean = value_str.lower().strip()
        evidence_clean = evidence_str.lower().strip()
        
        # Direct substring match
        if value_clean in evidence_clean:
            return (True, 1.0)
        
        # Try to find numeric values in both
        value_nums = re.findall(r'\d+(?:\.\d+)?', value_str)
        evidence_nums = re.findall(r'\d+(?:\.\d+)?', evidence_str)
        
        # Check if main number from value appears in evidence
        if value_nums and evidence_nums:
            for val_num in value_nums:
                if val_num in evidence_nums:
                    return (True, 0.8)
        
        # Check for partial word matches
        value_words = set(re.findall(r'\w+', value_clean))
        evidence_words = set(re.findall(r'\w+', evidence_clean))
        
        if value_words and evidence_words:
            overlap = len(value_words & evidence_words) / len(value_words)
            if overlap >= 0.5:
                return (True, overlap)
        
        return (False, 0.0)


class ConfidenceScorer:
    """Enhanced confidence scoring system with multiple factors"""
    
    # Source priority weights
    SOURCE_WEIGHTS = {
        "official_website": 1.0,
        "nirf": 0.95,
        "government": 0.9,
        "education_portal": 0.7,
        "news": 0.5,
        "third_party": 0.3,
        "unknown": 0.2
    }
    
    # Recency weights
    RECENCY_WEIGHTS = {
        "current": 1.0,      # 2026
        "recent": 0.9,        # 2025
        "somewhat_old": 0.7,  # 2024
        "old": 0.5,           # 2023
        "very_old": 0.3,      # 2022 and older
        "unknown": 0.2
    }
    
    @staticmethod
    def calculate_system_confidence(
        source_priority: str,
        recency: str,
        value_validated: bool,
        evidence_length_ok: bool,
        value_in_evidence: bool,
        llm_confidence: str
    ) -> Tuple[str, float, Dict[str, float]]:
        """
        Calculate system confidence based on multiple factors
        
        Returns:
            (confidence_level, confidence_score, breakdown)
        """
        # Initialize score components
        scores = {
            "source_quality": ConfidenceScorer.SOURCE_WEIGHTS.get(source_priority, 0.2),
            "data_recency": ConfidenceScorer.RECENCY_WEIGHTS.get(recency, 0.2),
            "value_validation": 1.0 if value_validated else 0.3,
            "evidence_quality": 1.0 if evidence_length_ok else 0.5,
            "value_evidence_match": 1.0 if value_in_evidence else 0.4,
            "llm_confidence": ConfidenceScorer._llm_to_score(llm_confidence)
        }
        
        # Weighted average (all factors equally important)
        total_score = sum(scores.values()) / len(scores)
        
        # Determine confidence level
        if total_score >= 0.8:
            confidence_level = "high"
        elif total_score >= 0.6:
            confidence_level = "medium"
        else:
            confidence_level = "low"
        
        return (confidence_level, round(total_score, 3), scores)
    
    @staticmethod
    def _llm_to_score(llm_confidence: str) -> float:
        """Convert LLM confidence string to numeric score"""
        if not llm_confidence:
            return 0.5
        
        llm_lower = llm_confidence.lower()
        
        if "high" in llm_lower or "confident" in llm_lower:
            return 1.0
        elif "medium" in llm_lower or "moderate" in llm_lower:
            return 0.7
        elif "low" in llm_lower:
            return 0.4
        else:
            return 0.5


class EvidenceQualityScorer:
    """Score the quality of evidence quotes"""
    
    @staticmethod
    def score_evidence(
        evidence: str,
        value: str,
        source_url: str,
        kpi_name: str
    ) -> Tuple[float, Dict[str, Any]]:
        """
        Score evidence quality based on multiple criteria
        
        Returns:
            (quality_score, breakdown)
        """
        # Convert to strings if needed
        evidence = str(evidence) if not isinstance(evidence, str) else evidence
        value = str(value) if not isinstance(value, str) else value
        
        if not evidence:
            return (0.0, {"error": "No evidence provided"})
        
        scores = {}
        
        # 1. Length appropriateness (10-500 chars is ideal)
        length = len(evidence)
        if 50 <= length <= 300:
            scores["length"] = 1.0
        elif 30 <= length <= 500:
            scores["length"] = 0.8
        elif 10 <= length < 30 or 500 < length <= 1000:
            scores["length"] = 0.5
        else:
            scores["length"] = 0.2
        
        # 2. Contains numeric data (for quantitative KPIs)
        has_numbers = bool(re.search(r'\d+', evidence))
        if has_numbers:
            scores["has_numbers"] = 1.0
        else:
            scores["has_numbers"] = 0.5 if DataValidator.detect_kpi_type(kpi_name) == "text" else 0.3
        
        # 3. Value appears in evidence
        value_clean = re.sub(r'[^\w\s]', '', value.lower())
        evidence_clean = re.sub(r'[^\w\s]', '', evidence.lower())
        
        if value_clean in evidence_clean:
            scores["value_match"] = 1.0
        else:
            # Check for numeric match
            value_nums = set(re.findall(r'\d+', value))
            evidence_nums = set(re.findall(r'\d+', evidence))
            overlap = len(value_nums & evidence_nums) / max(len(value_nums), 1)
            scores["value_match"] = overlap
        
        # 4. Contains contextual keywords related to KPI
        kpi_keywords = re.findall(r'\w+', kpi_name.lower())
        evidence_words = set(re.findall(r'\w+', evidence.lower()))
        
        keyword_matches = sum(1 for kw in kpi_keywords if kw in evidence_words)
        scores["context"] = min(keyword_matches / max(len(kpi_keywords), 1), 1.0)
        
        # 5. Not generic/template text
        generic_phrases = ["not found", "not available", "n/a", "no data", "coming soon", "under construction"]
        is_generic = any(phrase in evidence.lower() for phrase in generic_phrases)
        scores["specificity"] = 0.2 if is_generic else 1.0
        
        # Calculate overall score (weighted average)
        weights = {
            "length": 0.15,
            "has_numbers": 0.20,
            "value_match": 0.35,
            "context": 0.20,
            "specificity": 0.10
        }
        
        overall_score = sum(scores[k] * weights[k] for k in scores)
        
        return (round(overall_score, 3), scores)


class ConsistencyChecker:
    """Check consistency across multiple KPI values"""
    
    @staticmethod
    def check_placement_consistency(kpis: Dict[str, Any]) -> List[str]:
        """
        Check if placement-related KPIs are consistent with each other
        
        Returns list of inconsistency warnings
        """
        warnings = []
        
        # Extract placement-related values
        total_students = ConsistencyChecker._extract_numeric(kpis.get("Total Graduate Students (2025)", {}).get("value", ""))
        placed_students = ConsistencyChecker._extract_numeric(kpis.get("Placed Students Count", {}).get("value", ""))
        placement_rate = ConsistencyChecker._extract_numeric(kpis.get("Placement Rate", {}).get("value", ""))
        
        # Check if placed > total
        if placed_students and total_students:
            if placed_students > total_students:
                warnings.append(f"Placed students ({placed_students}) exceeds total graduates ({total_students})")
            
            # Check if placement rate matches
            if placement_rate:
                calculated_rate = (placed_students / total_students) * 100
                if abs(calculated_rate - placement_rate) > 10:  # More than 10% difference
                    warnings.append(
                        f"Placement rate mismatch: stated {placement_rate}% vs calculated {calculated_rate:.1f}%"
                    )
        
        return warnings
    
    @staticmethod
    def check_year_consistency(kpis: Dict[str, Any]) -> List[str]:
        """Check if year values are consistent and recent"""
        warnings = []
        
        current_year = 2026
        
        for kpi_name, kpi_data in kpis.items():
            if "year" in kpi_name.lower():
                year = ConsistencyChecker._extract_numeric(kpi_data.get("value", ""))
                if year:
                    if year > current_year:
                        warnings.append(f"{kpi_name}: Future year {year} detected")
                    elif year < 1900:
                        warnings.append(f"{kpi_name}: Unrealistic year {year} detected")
        
        return warnings
    
    @staticmethod
    def _extract_numeric(value: str) -> Optional[float]:
        """Extract first numeric value from string"""
        if not value:
            return None
        
        match = re.search(r'(\d+(?:\.\d+)?)', str(value))
        if match:
            try:
                return float(match.group(1))
            except ValueError:
                return None
        return None


# Convenience function to validate a complete KPI result
def validate_kpi_result(result: Dict[str, Any]) -> Dict[str, Any]:
    """
    Validate and enhance a KPI result with validation flags and scores
    
    Args:
        result: KPI result dictionary with keys: kpi_name, value, evidence_quote, source_url, etc.
    
    Returns:
        Enhanced result with validation fields added
    """
    kpi_name = result.get("kpi_name", "")
    value = result.get("value", "")
    evidence = result.get("evidence_quote", "")
    source_url = result.get("source_url", "")
    source_priority = result.get("source_priority", "unknown")
    recency = result.get("recency", "unknown")
    llm_confidence = result.get("llm_confidence", "medium")
    
    # Validate value
    is_valid, validation_reason, normalized_value = DataValidator.validate_value(kpi_name, value)
    
    # Check evidence quality
    evidence_ok, evidence_reason = DataValidator.validate_evidence_length(evidence)
    
    # Check value-evidence match
    value_in_evidence, match_score = DataValidator.check_value_evidence_match(value, evidence)
    
    # Score evidence quality
    evidence_score, evidence_breakdown = EvidenceQualityScorer.score_evidence(
        evidence, value, source_url, kpi_name
    )
    
    # Calculate enhanced system confidence
    confidence_level, confidence_score, confidence_breakdown = ConfidenceScorer.calculate_system_confidence(
        source_priority=source_priority,
        recency=recency,
        value_validated=is_valid,
        evidence_length_ok=evidence_ok,
        value_in_evidence=value_in_evidence,
        llm_confidence=llm_confidence
    )
    
    # Add validation fields to result
    result["validation"] = {
        "is_valid": is_valid,
        "validation_reason": validation_reason,
        "normalized_value": normalized_value,
        "evidence_quality_ok": evidence_ok,
        "evidence_quality_reason": evidence_reason,
        "value_in_evidence": value_in_evidence,
        "value_evidence_match_score": match_score
    }
    
    result["quality_scores"] = {
        "evidence_quality": evidence_score,
        "evidence_breakdown": evidence_breakdown,
        "confidence_score": confidence_score,
        "confidence_breakdown": confidence_breakdown
    }
    
    # Override system confidence with enhanced calculation
    result["system_confidence"] = confidence_level
    result["confidence_score"] = confidence_score
    
    return result
