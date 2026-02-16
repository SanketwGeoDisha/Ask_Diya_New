"""
Enhanced Data Parsers with Year Extraction and Currency Conversion
===================================================================
Handles complex data parsing including currency, years, and fuzzy matching.
"""

import re
import logging
from typing import Optional, Union, List

logger = logging.getLogger(__name__)


class CurrencyParser:
    """
    Unified currency parser handling all Indian currency formats.
    Converts everything to rupees (INR) for consistency.
    """
    
    # Currency conversion rates
    LAKH = 100_000
    CR = 10_000_000  # 1 Crore = 1,00,00,000
    LPA_TO_RUPEES = LAKH  # LPA means Lakhs Per Annum
    
    @classmethod
    def parse_currency(cls, text: str) -> Optional[float]:
        """
        Parse currency from text and convert to rupees.
        
        Handles:
        - "42 LPA" → 4,200,000
        - "1.2 Cr" → 12,000,000
        - "₹850000" → 850,000
        - "Rs. 5,00,000" → 500,000
        - "8.5 lakhs" → 850,000
        
        Returns:
            Amount in rupees, or None if parsing fails
        """
        if not text or not isinstance(text, str):
            return None
        
        text = text.strip().upper()
        
        # Remove common prefixes
        text = re.sub(r'^(RS\.?|INR|₹)\s*', '', text, flags=re.IGNORECASE)
        
        # Pattern 1: X.XX LPA or X.XX Lakhs Per Annum
        lpa_match = re.search(
            r'([\d,.]+)\s*(?:LPA|LAKHS?\s*PER\s*ANNUM|LAC\s*PER\s*ANNUM)',
            text,
            re.IGNORECASE
        )
        if lpa_match:
            number = cls._extract_number(lpa_match.group(1))
            if number is not None:
                return number * cls.LPA_TO_RUPEES
        
        # Pattern 2: X.XX Cr or X.XX Crore
        cr_match = re.search(r'([\d,.]+)\s*(?:CR|CRORE)', text, re.IGNORECASE)
        if cr_match:
            number = cls._extract_number(cr_match.group(1))
            if number is not None:
                return number * cls.CR
        
        # Pattern 3: X.XX Lakh or X.XX Lakhs
        lakh_match = re.search(r'([\d,.]+)\s*(?:LAKH|LAKHS|LAC)', text, re.IGNORECASE)
        if lakh_match:
            number = cls._extract_number(lakh_match.group(1))
            if number is not None:
                return number * cls.LAKH
        
        # Pattern 4: Direct rupees (with optional thousand separators)
        rupees_match = re.search(r'([\d,]+(?:\.\d{1,2})?)', text)
        if rupees_match:
            number = cls._extract_number(rupees_match.group(1))
            return number
        
        return None
    
    @staticmethod
    def _extract_number(text: str) -> Optional[float]:
        """Extract numeric value from text, handling Indian number format"""
        try:
            # Remove commas and convert to float
            cleaned = text.replace(',', '').strip()
            return float(cleaned)
        except (ValueError, AttributeError):
            return None
    
    @classmethod
    def format_currency(cls, rupees: float) -> str:
        """
        Format rupees to human-readable Indian format.
        
        Rules:
        - < 1 Cr → show as LPA
        - >= 1 Cr → show as Cr
        """
        if rupees >= cls.CR:
            crores = rupees / cls.CR
            return f"{crores:.2f} Cr"
        else:
            lpa = rupees / cls.LAKH
            return f"{lpa:.2f} LPA"


class YearExtractor:
    """
    Extract academic/calendar years from text with priority ordering.
    Prioritizes: 2025 > 2024 > 2023 > 2022 > ...
    """
    
    PRIORITY_YEARS = [2025, 2024, 2023, 2022, 2021, 2020]
    
    @classmethod
    def extract_year(
        cls,
        text: str,
        context: Optional[str] = None,
        priority_years: Optional[List[int]] = None
    ) -> Optional[int]:
        """
        Extract year from text with priority.
        
        Args:
            text: Text to extract year from
            context: Additional context (URL, title, etc.)
            priority_years: Custom priority order (defaults to PRIORITY_YEARS)
        
        Returns:
            Most relevant year, or None
        """
        if not text:
            return None
        
        priority_years = priority_years or cls.PRIORITY_YEARS
        combined_text = f"{text} {context or ''}"
        
        # Pattern 1: "NIRF 2025", "NIRF-2025", "2024-25 Batch"
        patterns = [
            r'NIRF[-\s]*(202[0-7])',
            r'(202[0-7])[-\s]*(?:20)?[0-7]{2}',  # 2024-25 or 2024-2025
            r'batch[-\s]*(202[0-7])',
            r'year[-\s]*(202[0-7])',
            r'/(202[0-7])/',  # in URLs
            r'academic[-\s]*year[-\s]*(202[0-7])',
            r'placement[-\s]*(202[0-7])',
        ]
        
        found_years = set()
        for pattern in patterns:
            matches = re.finditer(pattern, combined_text, re.IGNORECASE)
            for match in matches:
                year_str = match.group(1)
                try:
                    year = int(year_str)
                    if 2015 <= year <= 2027:  # Sanity check
                        found_years.add(year)
                except ValueError:
                    continue
        
        # Return highest priority year
        for priority_year in priority_years:
            if priority_year in found_years:
                return priority_year
        
        # If no priority year found, return most recent
        if found_years:
            return max(found_years)
        
        return None
    
    @classmethod
    def calculate_recency(cls, year: Optional[int], reference_year: int = 2025) -> str:
        """
        Calculate recency rating.
        
        Returns: 'high', 'medium', 'low', or 'unknown'
        """
        if not year:
            return 'unknown'
        
        age = reference_year - year
        if age == 0:
            return 'high'
        elif age == 1:
            return 'medium'
        elif age >= 2:
            return 'low'
        else:
            return 'unknown'


class FuzzyMatcher:
    """
    Fuzzy matching for text patterns with variations.
    Handles typos, spacing variations, and synonyms.
    """
    
    @staticmethod
    def normalize_text(text: str) -> str:
        """Normalize text for fuzzy matching"""
        if not text:
            return ""
        
        text = text.lower()
        text = re.sub(r'[^\w\s]', ' ', text)  # Remove punctuation
        text = re.sub(r'\s+', ' ', text)  # Collapse whitespace
        return text.strip()
    
    @classmethod
    def fuzzy_search(
        cls,
        pattern: str,
        text: str,
        threshold: float = 0.8
    ) -> Optional[re.Match]:
        """
        Fuzzy regex search allowing for minor variations.
        
        Args:
            pattern: Regex pattern to search for
            text: Text to search in
            threshold: Similarity threshold (0-1)
        
        Returns:
            Match object if found, None otherwise
        """
        # Normalize both pattern and text
        normalized_pattern = cls.normalize_text(pattern)
        normalized_text = cls.normalize_text(text)
        
        # Try exact match first
        match = re.search(normalized_pattern, normalized_text, re.IGNORECASE)
        if match:
            return match
        
        # Try with flexible whitespace
        flexible_pattern = re.sub(r'\s+', r'\\s*', normalized_pattern)
        match = re.search(flexible_pattern, normalized_text, re.IGNORECASE)
        
        return match
    
    @classmethod
    def extract_with_variations(
        cls,
        base_patterns: List[str],
        text: str,
        value_type: str = 'int'
    ) -> Optional[Union[int, float, str]]:
        """
        Extract value from text using multiple pattern variations.
        
        Args:
            base_patterns: List of regex patterns to try
            text: Text to extract from
            value_type: Type of value to extract ('int', 'float', 'str')
        
        Returns:
            Extracted value or None
        """
        for pattern in base_patterns:
            match = cls.fuzzy_search(pattern, text)
            if match:
                try:
                    value_str = match.group(1)
                    if value_type == 'int':
                        return int(value_str.replace(',', ''))
                    elif value_type == 'float':
                        return float(value_str.replace(',', ''))
                    else:
                        return value_str
                except (ValueError, IndexError, AttributeError):
                    continue
        
        return None


def safe_html_parse(html: str, parser: str = 'html.parser'):
    """
    Safely parse HTML with error handling.
    
    Args:
        html: HTML string to parse
        parser: BeautifulSoup parser to use
    
    Returns:
        BeautifulSoup object or None if parsing fails
    """
    if not html:
        return None
    
    try:
        from bs4 import BeautifulSoup
        return BeautifulSoup(html, parser)
    except Exception as e:
        logger.error(f"HTML parsing failed with {parser}: {e}")
        
        # Try alternative parser
        if parser != 'lxml':
            try:
                from bs4 import BeautifulSoup
                logger.info("Retrying with lxml parser")
                return BeautifulSoup(html, 'lxml')
            except Exception as e2:
                logger.error(f"Alternative parser also failed: {e2}")
        
        # Last resort: html.parser
        if parser != 'html.parser':
            try:
                from bs4 import BeautifulSoup
                logger.info("Retrying with html.parser")
                return BeautifulSoup(html, 'html.parser')
            except Exception as e3:
                logger.error(f"All parsers failed: {e3}")
        
        return None


def extract_text_from_pdf_with_fallback(pdf_path_or_bytes, max_pages: int = 50) -> Optional[str]:
    """
    Extract text from PDF with multiple fallback strategies.
    
    Tries in order:
    1. pdfplumber (best for structured PDFs)
    2. PyPDF2 (fallback for simpler PDFs)
    3. OCR with pytesseract (for scanned PDFs)
    
    Args:
        pdf_path_or_bytes: Path to PDF file or bytes
        max_pages: Maximum pages to extract
    
    Returns:
        Extracted text or None
    """
    import io
    
    # Convert to bytes if necessary
    if isinstance(pdf_path_or_bytes, str):
        try:
            with open(pdf_path_or_bytes, 'rb') as f:
                pdf_bytes = f.read()
        except Exception as e:
            logger.error(f"Failed to read PDF file: {e}")
            return None
    else:
        pdf_bytes = pdf_path_or_bytes
    
    # Strategy 1: pdfplumber
    try:
        import pdfplumber
        text_parts = []
        
        with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
            for i, page in enumerate(pdf.pages[:max_pages]):
                text = page.extract_text()
                if text:
                    text_parts.append(text)
        
        if text_parts:
            result = "\n".join(text_parts)
            logger.info(f"PDF extracted successfully with pdfplumber ({len(result)} chars)")
            return result
    except Exception as e:
        logger.warning(f"pdfplumber extraction failed: {e}")
    
    # Strategy 2: PyPDF2
    try:
        from PyPDF2 import PdfReader
        text_parts = []
        
        pdf_reader = PdfReader(io.BytesIO(pdf_bytes))
        for i, page in enumerate(pdf_reader.pages[:max_pages]):
            text = page.extract_text()
            if text:
                text_parts.append(text)
        
        if text_parts:
            result = "\n".join(text_parts)
            logger.info(f"PDF extracted successfully with PyPDF2 ({len(result)} chars)")
            return result
    except Exception as e:
        logger.warning(f"PyPDF2 extraction failed: {e}")
    
    # Strategy 3: OCR (only if previous methods failed)
    try:
        from PIL import Image
        import pytesseract
        from pdf2image import convert_from_bytes
        
        logger.info("Attempting OCR extraction (this may take time)...")
        images = convert_from_bytes(pdf_bytes, first_page=1, last_page=min(max_pages, 10))
        text_parts = []
        
        for i, image in enumerate(images):
            text = pytesseract.image_to_string(image)
            if text:
                text_parts.append(text)
        
        if text_parts:
            result = "\n".join(text_parts)
            logger.info(f"PDF extracted successfully with OCR ({len(result)} chars)")
            return result
    except ImportError:
        logger.warning("OCR libraries not available (pytesseract, pdf2image)")
    except Exception as e:
        logger.warning(f"OCR extraction failed: {e}")
    
    logger.error("All PDF extraction methods failed")
    return None
