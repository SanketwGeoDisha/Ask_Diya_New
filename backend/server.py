from fastapi import FastAPI, APIRouter, HTTPException, BackgroundTasks, Request
from fastapi.responses import StreamingResponse
from dotenv import load_dotenv
from starlette.middleware.cors import CORSMiddleware
import os
import logging
import json
from pathlib import Path
from pydantic import BaseModel, Field, ConfigDict
from typing import List, Optional, Dict, Any, Tuple
import uuid
from datetime import datetime, timezone
import asyncio
import requests
from google import genai
from google.genai import types
import re
from urllib.parse import urlparse, quote
from bs4 import BeautifulSoup
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
import functools
import hashlib
from collections import OrderedDict
import urllib3
import ssl

# Import new error handling and parsing utilities
from error_handlers import (
    APIKeyRotator,
    exponential_backoff_retry,
    graceful_degradation,
    get_circuit_breaker,
    CircuitBreaker
)
from data_parsers import (
    CurrencyParser,
    YearExtractor,
    FuzzyMatcher,
    safe_html_parse,
    extract_text_from_pdf_with_fallback
)
from data_validator import (
    DataValidator,
    ConfidenceScorer,
    EvidenceQualityScorer,
    ConsistencyChecker,
    validate_kpi_result
)
from database import get_db_manager, init_database
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.util import get_remote_address
from slowapi.errors import RateLimitExceeded

# Import NIRF collector
try:
    from nirf_collector import NIRFCollector, collect_nirf_for_college
except ImportError:
    logging.warning("Could not import nirf_collector, NIRF enhanced discovery will be disabled")
    NIRFCollector = None
    collect_nirf_for_college = None

# Import Advanced NIRF Extractor
try:
    from advanced_nirf_extractor import AdvancedNIRFExtractor
except ImportError:
    logging.warning("Could not import advanced_nirf_extractor, falling back to AI-based extraction")
    AdvancedNIRFExtractor = None

ROOT_DIR = Path(__file__).parent
load_dotenv(ROOT_DIR / '.env')

# Custom exception for API key exhaustion
class APIKeyExhaustedException(Exception):
    """Raised when a Serper API key returns 400 Bad Request"""
    pass

# Selective SSL verification - only disable for known problematic domains
PROBLEMATIC_SSL_DOMAINS = [
    'some-old-college-site.ac.in',  # Add specific domains here as needed
    'amity.edu',  # Amity University domains have SSL certificate issues
]

def should_verify_ssl(url: str) -> bool:
    """Check if SSL should be verified for a given URL"""
    if not url:
        return True
    
    parsed = urlparse(url)
    domain = parsed.netloc.lower()
    
    for problematic in PROBLEMATIC_SSL_DOMAINS:
        if problematic in domain:
            return False
    
    return True  # Verify SSL by default (secure)

# Initialize database on startup
db = get_db_manager()

# Initialize rate limiter
limiter = Limiter(key_func=get_remote_address)

# ============ Intelligent Cache System ============

class LRUCache:
    """Thread-safe LRU Cache with TTL support for search results"""
    def __init__(self, max_size: int = 500, ttl_seconds: int = 3600):
        self.cache: OrderedDict = OrderedDict()
        self.max_size = max_size
        self.ttl = ttl_seconds
        self._lock = None  # Will be created lazily if needed
    
    def _get_key(self, *args) -> str:
        """Generate cache key from arguments"""
        return hashlib.md5(json.dumps(args, sort_keys=True).encode()).hexdigest()
    
    def get(self, key: str) -> Optional[Any]:
        """Get item from cache if not expired"""
        if key in self.cache:
            item, timestamp = self.cache[key]
            if time.time() - timestamp < self.ttl:
                self.cache.move_to_end(key)
                return item
            else:
                del self.cache[key]
        return None
    
    def set(self, key: str, value: Any):
        """Set item in cache with current timestamp"""
        if key in self.cache:
            del self.cache[key]
        elif len(self.cache) >= self.max_size:
            self.cache.popitem(last=False)
        self.cache[key] = (value, time.time())
    
    def clear(self):
        """Clear all cache"""
        self.cache.clear()

# Global caches
search_cache = LRUCache(max_size=1000, ttl_seconds=7200)  # 2 hours for search results
content_cache = LRUCache(max_size=200, ttl_seconds=14400)  # 4 hours for fetched content

# ============ KPI Schema with Search Keywords ============

# KPIs that can be extracted from NIRF Overall document
NIRF_EXTRACTABLE_KPIS = {
    "Total Graduate Students (2025)": {
        "nirf_field": "Total number of students graduating in minimum stipulated time",
        "nirf_location": "Student Progression section or Metric 2.6"
    },
    "Placed Students Count": {
        "nirf_field": "Number of students placed",
        "nirf_location": "Placements section or Metric 5.2"
    },
    "Median Compensation (Last Batch)": {
        "nirf_field": "Median salary of placed graduates (Amount in Rs.)",
        "nirf_location": "Placements section or Metric 5.2.1"
    },
    "Students Pursuing Higher Education": {
        "nirf_field": "Number of students selected for Higher Studies",
        "nirf_location": "Student Outcomes section or Metric 5.2"
    },
    "IP Patents Granted/Licensed (Latest Year)": {
        "nirf_field": "No. of Patents Published, No. of Patents Granted",
        "nirf_location": "IPR/Research section or Metric 3.4"
    },
    "Total Students Enrolled": {
        "nirf_field": "Total Actual Student Strength - sum of all programs and years",
        "nirf_location": "Student Enrollment section or Table showing program-wise student strength"
    },
    "Female Students Enrolled": {
        "nirf_field": "No. of Female Students from Total Student Strength table",
        "nirf_location": "Student Demographics section or Gender diversity table"
    },
    "Total Faculty": {
        "nirf_field": "Faculty Details - check last row total number",
        "nirf_location": "Faculty section or Metric 2.4, look for total count"
    },
    "PhD Faculty": {
        "nirf_field": "Faculty Details where Qualification == Ph.D",
        "nirf_location": "Faculty qualification table, count rows with PhD"
    },
    "Average Teaching Experience of Faculty": {
        "nirf_field": "Average of 'Experience (In Months)' column, convert to years",
        "nirf_location": "Faculty Details table, Experience column"
    },
    "PhD Students Enrolled": {
        "nirf_field": "Ph.D Student Details (Full Time + Part Time doctoral students till 2023-24)",
        "nirf_location": "PhD enrollment section or Metric 2.5, sum full-time and part-time"
    },
    "Program-wise Median Salary (Last 3 Years)": {
        "nirf_field": "Median salary from Placement tables for each program and year (2023-25)",
        "nirf_location": "Placement & Higher Studies section, program-wise tables showing year, graduated, placed, median salary"
    }
}

KPI_SCHEMA = {
    "college_kpis": [
        {
            "field_name": "ict_enabled_learning_infrastructure",
            "display_name": "ICT-Enabled Learning Infrastructure",
            "category": "Academic Infrastructure",
            "data_type": "boolean",
            "unit": "yes/no",
            "validation_rules": "true or false only",
            "extraction_instruction": "Set true if ICT infrastructure (smart classrooms, learning management systems, digital labs) is explicitly mentioned/implemented, false if explicitly stated as not available, null if unclear.",
            "example_value": True,
            "remarks_required": True,
            "search_keywords": ["smart classroom", "ICT infrastructure", "LMS learning management", "digital classroom", "e-learning platform", "virtual lab", "online learning"]
        },
        {
            "field_name": "digital_library_access",
            "display_name": "Digital Library Access",
            "category": "Academic Infrastructure",
            "data_type": "boolean",
            "unit": "yes/no",
            "validation_rules": "true or false only",
            "extraction_instruction": "Set true if digital/e-library access is available to students, false if not available, null if unclear.",
            "example_value": True,
            "remarks_required": True,
            "search_keywords": ["digital library", "e-library", "online library", "e-resources", "e-journals", "DELNET", "NDL", "online database"]
        },
        {
            "field_name": "male_hostels_college_managed",
            "display_name": "Male Hostels Managed by College",
            "category": "Campus Facilities",
            "data_type": "integer",
            "unit": "count",
            "validation_rules": "positive integer or 0",
            "extraction_instruction": "Count of male hostel facilities directly managed/operated by the college. If unavailable, set 0.",
            "example_value": 5,
            "remarks_required": False,
            "search_keywords": ["boys hostel", "male hostel", "men hostel", "hostel accommodation", "hostel capacity", "number of hostels"]
        },
        {
            "field_name": "female_hostels_college_managed",
            "display_name": "Female Hostels Managed by College",
            "category": "Campus Facilities",
            "data_type": "integer",
            "unit": "count",
            "validation_rules": "positive integer or 0",
            "extraction_instruction": "Count of female hostel facilities directly managed/operated by the college. If unavailable, set 0.",
            "example_value": 4,
            "remarks_required": False,
            "search_keywords": ["girls hostel", "female hostel", "women hostel", "ladies hostel", "hostel for girls", "women accommodation"]
        },
        {
            "field_name": "smart_campus_erp_implementation",
            "display_name": "Smart Campus / ERP Implementation",
            "category": "Technology Infrastructure",
            "data_type": "boolean",
            "unit": "yes/no",
            "validation_rules": "true or false only",
            "extraction_instruction": "Set true if smart campus initiatives or ERP systems are implemented, false if not, null if unclear.",
            "example_value": True,
            "remarks_required": True,
            "search_keywords": ["ERP system", "smart campus", "campus management system", "student portal", "digital campus", "automation"]
        },
        {
            "field_name": "courses_list",
            "display_name": "List of Courses",
            "category": "Academic Programs",
            "data_type": "string",
            "unit": "formatted list",
            "validation_rules": "string with grouped courses",
            "extraction_instruction": "List all courses in compact format: Group by degree type with specializations in parentheses. Format: 'B.Tech(CSE, ECE, ME), M.Tech(VLSI, AI), MBA, BBA, Ph.D'. Use standard abbreviations (CSE=Computer Science, ECE=Electronics, ME=Mechanical, EE=Electrical, CE=Civil, etc). Separate degree types with commas.",
            "example_value": "B.Tech(CSE, ECE, ME, EE, CE), M.Tech(CSE, VLSI), MBA, Ph.D",
            "remarks_required": False,
            "search_keywords": ["courses offered", "programs offered", "academic programs", "B.Tech", "M.Tech", "MBA", "departments", "branches", "specializations"]
        },
        {
            "field_name": "course_fees",
            "display_name": "Fees for Each Course",
            "category": "Academic Programs",
            "data_type": "object",
            "unit": "INR",
            "validation_rules": "key-value pairs: course_name -> annual_fee",
            "extraction_instruction": "Object mapping course names to annual tuition fees in INR. Include only tuition fees.",
            "example_value": {"Computer Science Engineering": 200000, "Mechanical Engineering": 180000},
            "remarks_required": False,
            "search_keywords": ["fee structure", "tuition fee", "course fees", "annual fee", "semester fee", "fee details", "fee per year"]
        },
        {
            "field_name": "total_graduate_students_2025",
            "display_name": "Total Graduate Students (2025)",
            "category": "Student Demographics",
            "data_type": "integer",
            "unit": "count",
            "validation_rules": "positive integer",
            "extraction_instruction": "[NIRF EXTRACTABLE] Total number of students graduating in minimum stipulated time. In NIRF document, look for 'Total number of students graduating in minimum stipulated time' or 'No. of students graduating' in Student Progression section (Metric 2.6). This is the count of students who completed their program within the prescribed duration.",
            "example_value": 1200,
            "remarks_required": False,
            "search_keywords": ["graduating batch 2025", "final year students", "outgoing batch", "students graduated", "batch size 2025", "NIRF students graduating", "minimum stipulated time"]
        },
        {
            "field_name": "placed_students_count",
            "display_name": "Placed Students Count",
            "category": "Placements",
            "data_type": "integer",
            "unit": "count",
            "validation_rules": "positive integer <= total_graduate_students",
            "extraction_instruction": "[NIRF EXTRACTABLE] Number of students placed out of graduating students. In NIRF document, look for 'No. of students placed' in Placements section (Metric 5.2). This is the actual count of students who got jobs, not percentage.",
            "example_value": 950,
            "remarks_required": False,
            "search_keywords": ["students placed", "placement statistics", "placement record", "campus placement", "students recruited", "placement percentage", "NIRF placements", "no. of students placed"]
        },
        {
            "field_name": "max_compensation_last_season",
            "display_name": "Maximum Compensation (Last Placement Season)",
            "category": "Placements",
            "data_type": "string",
            "unit": "LPA or Cr",
            "validation_rules": "formatted string with LPA or Cr suffix",
            "extraction_instruction": "Highest annual compensation offered to any student in last placement season. Format: If below 1 Crore (< 1,00,00,000), show as 'X.XX LPA' (e.g., '42 LPA', '8.5 LPA'). If 1 Crore or above, show as 'X.XX Cr' (e.g., '1.2 Cr', '2.1 Cr'). Always include the unit suffix.",
            "example_value": "42 LPA",
            "remarks_required": False,
            "search_keywords": ["highest package", "maximum salary", "top CTC", "highest CTC", "best package", "maximum compensation", "highest offer"]
        },
        {
            "field_name": "median_compensation_last_batch",
            "display_name": "Median Compensation (Last Batch)",
            "category": "Placements",
            "data_type": "string",
            "unit": "LPA or Cr",
            "validation_rules": "formatted string with LPA or Cr suffix",
            "extraction_instruction": "[NIRF EXTRACTABLE] Median salary of placed graduates (Amount in Rs.) In NIRF document, look for 'Median salary of placed graduates' in Placements section (Metric 5.2.1). The value is usually in Rupees, convert to LPA: divide by 100,000. Format: If below 1 Crore (< 1,00,00,000), show as 'X.XX LPA' (e.g., '8.5 LPA', '12 LPA'). If 1 Crore or above, show as 'X.XX Cr' (e.g., '1.2 Cr'). Always include the unit suffix.",
            "example_value": "8.5 LPA",
            "remarks_required": False,
            "search_keywords": ["median salary", "median package", "median CTC", "NIRF median salary", "median salary of placed graduates"]
        },
        {
            "field_name": "students_higher_education",
            "display_name": "Students Pursuing Higher Education",
            "category": "Student Outcomes",
            "data_type": "integer",
            "unit": "count",
            "validation_rules": "positive integer",
            "extraction_instruction": "[NIRF EXTRACTABLE] Number of students selected for Higher Studies. In NIRF document, look for 'No. of students selected for Higher Studies' in Student Outcomes or Placements section (Metric 5.2). This includes students admitted to Masters, PhD, or other postgraduate programs.",
            "example_value": 150,
            "remarks_required": False,
            "search_keywords": ["NIRF higher studies", "students admitted to higher studies", "students selected for higher studies", "pursuing masters", "postgraduate studies", "NIRF metric 5.2"]
        },
        {
            "field_name": "ip_patents_last_year",
            "display_name": "IP Patents Granted/Licensed (Latest Year)",
            "category": "Research & Innovation",
            "data_type": "integer",
            "unit": "count",
            "validation_rules": "positive integer or 0",
            "extraction_instruction": "[NIRF EXTRACTABLE] IPR - No. of Patents Published + No. of Patents Granted. In NIRF document, look for IPR section (Metric 3.4) which shows 'No. of Patents Published' and 'No. of Patents Granted'. Take the sum of both numbers or take Patents Granted as priority.",
            "example_value": 12,
            "remarks_required": False,
            "search_keywords": ["patents granted", "patents published", "intellectual property", "IPR", "NIRF patents", "NIRF IPR", "No. of patents"]
        },
        {
            "field_name": "entrance_exam_name",
            "display_name": "Entrance Exam Name",
            "category": "Admissions",
            "data_type": "string",
            "unit": "exam name",
            "validation_rules": "string value",
            "extraction_instruction": "Primary entrance examination name for undergraduate admissions.",
            "example_value": "JEE Main",
            "remarks_required": False,
            "search_keywords": ["admission through", "entrance exam", "JEE", "NEET", "admission test", "eligibility criteria", "selection process"]
        },
        {
            "field_name": "entrance_exam_cutoff",
            "display_name": "Entrance Exam Cutoff by Program",
            "category": "Admissions",
            "data_type": "object",
            "unit": "percentile/score",
            "validation_rules": "key-value pairs: course_name -> cutoff_value",
            "extraction_instruction": "Object mapping course names to entrance exam cutoff scores/percentiles for last admission cycle.",
            "example_value": {"Computer Science Engineering": 98.5, "Mechanical Engineering": 92.3},
            "remarks_required": False,
            "search_keywords": ["cutoff marks", "cutoff percentile", "closing rank", "JEE cutoff", "admission cutoff", "minimum marks required"]
        },
        {
            "field_name": "total_students_enrolled",
            "display_name": "Total Students Enrolled",
            "category": "Student Demographics",
            "data_type": "integer",
            "unit": "count",
            "validation_rules": "positive integer",
            "extraction_instruction": "[NIRF EXTRACTABLE] Total Actual Student Strength across all programs. In NIRF document, look for 'Total Actual Student Strength' table which shows program-wise student count. Sum all programs and all years (1st year, 2nd year, etc.) to get total. Usually in Student Enrollment section.",
            "example_value": 5000,
            "remarks_required": False,
            "search_keywords": ["total students", "student strength", "actual student strength", "total enrollment", "NIRF student strength", "program wise student count"]
        },
        {
            "field_name": "female_students_enrolled",
            "display_name": "Female Students Enrolled",
            "category": "Student Demographics",
            "data_type": "integer",
            "unit": "count",
            "validation_rules": "positive integer <= total_students_enrolled",
            "extraction_instruction": "[NIRF EXTRACTABLE] Number of Female Students from Total Student Strength table. In NIRF document, look for 'No. of Female Students' or 'Female/Total Students' column in the Student Strength table. Sum across all programs and years.",
            "example_value": 2200,
            "remarks_required": False,
            "search_keywords": ["female students", "girl students", "gender diversity", "NIRF female students", "no. of female students"]
        },
        {
            "field_name": "total_faculty",
            "display_name": "Total Faculty",
            "category": "Faculty",
            "data_type": "integer",
            "unit": "count",
            "validation_rules": "positive integer",
            "extraction_instruction": "[NIRF EXTRACTABLE] Total faculty count from Faculty Details table. In NIRF document, look for 'Faculty Details' table (Metric 2.4) and check the LAST ROW which typically shows the total count. Or sum all faculty rows.",
            "example_value": 300,
            "remarks_required": False,
            "search_keywords": ["total faculty", "faculty details", "NIRF faculty", "faculty strength", "teaching staff", "sanctioned faculty"]
        },
        {
            "field_name": "phd_faculty",
            "display_name": "PhD Faculty",
            "category": "Faculty",
            "data_type": "integer",
            "unit": "count",
            "validation_rules": "positive integer <= total_faculty",
            "extraction_instruction": "[NIRF EXTRACTABLE] Count of faculty with PhD qualification. In NIRF document, look at 'Faculty Details' table and find the 'Qualification' column. Count all rows where Qualification contains 'Ph.D' or 'PhD' or 'Doctorate'.",
            "example_value": 250,
            "remarks_required": False,
            "search_keywords": ["PhD faculty", "doctorate faculty", "NIRF PhD faculty", "qualification PhD", "faculty with PhD"]
        },
        {
            "field_name": "avg_teaching_experience",
            "display_name": "Average Teaching Experience of Faculty",
            "category": "Faculty",
            "data_type": "float",
            "unit": "years",
            "validation_rules": "positive number",
            "extraction_instruction": "[NIRF EXTRACTABLE] Average of 'Experience (In Months)' from Faculty Details. In NIRF document, find 'Faculty Details' table with 'Experience (In Months)' column. Calculate the average of all values in this column, then divide by 12 to convert months to years. Report as decimal (e.g., 12.5 years).",
            "example_value": 12.5,
            "remarks_required": False,
            "search_keywords": ["teaching experience", "experience in months", "NIRF faculty experience", "average experience", "faculty profile"]
        },
        {
            "field_name": "sports_infrastructure",
            "display_name": "Sports Infrastructure & Achievements",
            "category": "Campus Facilities",
            "data_type": "object",
            "unit": "description",
            "validation_rules": "object with facilities and achievements",
            "extraction_instruction": "Object containing sports facilities list and notable achievements. Format: {\"facilities\": [], \"achievements\": []}",
            "example_value": {"facilities": ["Cricket Ground", "Swimming Pool"], "achievements": ["University Champions 2024"]},
            "remarks_required": False,
            "search_keywords": ["sports facilities", "playground", "gymnasium", "sports complex", "athletics", "sports achievements", "stadium"]
        },
        {
            "field_name": "active_clubs_list",
            "display_name": "List of Active Clubs",
            "category": "Student Life",
            "data_type": "array",
            "unit": "names",
            "validation_rules": "array of strings",
            "extraction_instruction": "Array of names of currently active student clubs and societies.",
            "example_value": ["Coding Club", "Drama Society", "Music Club"],
            "remarks_required": False,
            "search_keywords": ["student clubs", "clubs and societies", "student activities", "cultural clubs", "technical clubs", "student organizations"]
        },
        {
            "field_name": "nirf_ranking",
            "display_name": "NIRF Ranking",
            "category": "Accreditations & Rankings",
            "data_type": "string",
            "unit": "rank",
            "validation_rules": "exact rank number or band string",
            "extraction_instruction": "NIRF ranking from nirfindia.org. If exact rank is available (e.g., '1', '5', '23'), show the exact number. If only band is available (e.g., '51-100', '101-150', '151-200', '201+'), show the band. Prefer exact rank over band. Use 'Not Ranked' if not in NIRF.",
            "example_value": "5",
            "remarks_required": False,
            "search_keywords": ["NIRF ranking", "NIRF 2024", "NIRF 2025", "national ranking", "NIRF rank", "nirfindia.org", "India Rankings", "engineering ranking"]
        },
        {
            "field_name": "institutional_status",
            "display_name": "Institutional Status",
            "category": "Accreditations & Rankings",
            "data_type": "string",
            "unit": "status type",
            "validation_rules": "one of: 'Autonomous', 'Deemed University', 'Private University', 'Affiliated College'",
            "extraction_instruction": "Institutional affiliation/status as per latest UGC/AICTE recognition.",
            "example_value": "Autonomous",
            "remarks_required": False,
            "search_keywords": ["autonomous status", "deemed university", "affiliated to", "university status", "NAAC accreditation", "UGC recognized"]
        },
        {
            "field_name": "phd_students_enrolled",
            "display_name": "PhD Students Enrolled",
            "category": "Student Demographics",
            "data_type": "integer",
            "unit": "count",
            "validation_rules": "positive integer or 0",
            "extraction_instruction": "[NIRF EXTRACTABLE] Ph.D Student Details - sum of Full Time and Part Time. In NIRF document, look for 'Ph.D Student Details' section (including Integrated Ph.D) showing students pursuing doctoral program till 2023-24. Add 'Full Time' + 'Part Time' students. Do NOT include students admitted in 2024-25.",
            "example_value": 85,
            "remarks_required": False,
            "search_keywords": ["PhD students", "doctoral students", "research scholars", "NIRF PhD enrollment", "Ph.D student details", "full time part time PhD"]
        }
    ],
    "metadata": {
        "version": "2.0",
        "total_kpis": 25,
        "categories": [
            "Academic Infrastructure", "Campus Facilities", "Technology Infrastructure",
            "Academic Programs", "Student Demographics", "Placements", "Student Outcomes",
            "Research & Innovation", "Admissions", "Faculty", "Student Life", "Accreditations & Rankings"
        ]
    }
}

# Create the main app
app = FastAPI(title="College KPI Auditor API")

# Create a router with the /api prefix
api_router = APIRouter(prefix="/api")

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# ============ Models ============

class AuditRequest(BaseModel):
    college_name: str

class AuditResponse(BaseModel):
    model_config = ConfigDict(extra="ignore")
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    college_name: str
    status: str = "pending"
    progress: int = 0
    progress_message: str = ""
    results: List[Dict[str, Any]] = []
    summary: Dict[str, Any] = {}
    created_at: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    completed_at: Optional[str] = None

# ============ Official Source Validator ============

class OfficialSourceValidator:
    """Validates and filters results to only include official sources"""
    
    # Official source patterns - ONLY these are allowed
    OFFICIAL_PATTERNS = {
        'nirf': ['nirfindia.org', 'nirf.org'],
        'naac': ['naac.gov.in', 'assessmentonline.naac.gov.in'],
        'government': ['.gov.in', '.nic.in', '.ac.in', '.edu.in'],
        'aicte': ['aicte-india.org', 'facilities.aicte-india.org'],
        'ugc': ['ugc.ac.in', 'ugc.gov.in'],
    }
    
    # Blocked sources - these should NEVER be used
    BLOCKED_SOURCES = [
        'shiksha.com', 'collegedunia.com', 'collegedekho.com', 'careers360.com',
        'getmyuni.com', 'jagranjosh.com', 'examresults.net', 'indiatoday.in',
        'hindustantimes.com', 'timesofindia.indiatimes.com', 'ndtv.com',
        'news18.com', 'thehindu.com', 'quora.com', 'reddit.com', 'youtube.com',
        'facebook.com', 'instagram.com', 'twitter.com', 'linkedin.com'
    ]
    
    # Invalid file extensions (images, scripts, styles, etc.)
    INVALID_EXTENSIONS = [
        '.jpg', '.jpeg', '.png', '.gif', '.svg', '.webp', '.bmp', '.ico',
        '.js', '.css', '.woff', '.woff2', '.ttf', '.eot',
        '.mp4', '.mp3', '.avi', '.mov', '.wmv',
        '.zip', '.rar', '.tar', '.gz'
    ]
    
    # Invalid URL prefixes
    INVALID_PREFIXES = ['javascript:', 'mailto:', 'tel:', 'data:']
    
    @classmethod
    def is_valid_url(cls, url: str) -> bool:
        """Check if URL is structurally valid and not an asset/image"""
        if not url or not isinstance(url, str):
            return False
        
        url_lower = url.lower().strip()
        
        # Must start with http/https
        if not url_lower.startswith(('http://', 'https://')):
            # Check for invalid prefixes
            if any(url_lower.startswith(prefix) for prefix in cls.INVALID_PREFIXES):
                return False
            return False
        
        # PDFs are always valid (official documents)
        if url_lower.endswith('.pdf'):
            return True
        
        # Check if URL ends with invalid extensions (actual file types, not paths)
        # Extract just the filename from the URL
        try:
            from urllib.parse import urlparse
            parsed = urlparse(url)
            path = parsed.path.lower()
            
            # Check if it ends with an invalid extension
            if any(path.endswith(ext) for ext in cls.INVALID_EXTENSIONS):
                return False
            
            # Must have a valid domain structure
            if not parsed.netloc or not parsed.scheme:
                return False
            # Domain must have at least one dot
            if '.' not in parsed.netloc:
                return False
        except Exception:
            return False
        
        return True
    
    @classmethod
    def is_official_source(cls, url: str, college_domain: str = None) -> bool:
        """Check if URL is from an official/trusted source"""
        if not cls.is_valid_url(url):
            return False
        
        if url == "N/A":
            return False
        
        url_lower = url.lower()
        
        # Check if blocked
        for blocked in cls.BLOCKED_SOURCES:
            if blocked in url_lower:
                return False
        
        # Check official patterns
        for source_type, patterns in cls.OFFICIAL_PATTERNS.items():
            for pattern in patterns:
                if pattern in url_lower:
                    return True
        
        # Check if it's the college's official website
        if college_domain and college_domain.lower() in url_lower:
            return True
        
        # Check for common official patterns
        if any(ext in url_lower for ext in ['.ac.in', '.edu.in', '.edu', '.gov']):
            return True
        
        return False
    
    @classmethod
    def get_source_priority(cls, url: str) -> int:
        """Get priority score for source (lower = higher priority)"""
        if not url or url == "N/A":
            return 999
        
        url_lower = url.lower()
        
        # Priority 1: NIRF (most reliable for placements, rankings)
        if 'nirf' in url_lower:
            return 1
        
        # Priority 2: Official college website
        if '.ac.in' in url_lower or '.edu.in' in url_lower:
            return 2
        
        # Priority 3: NAAC
        if 'naac' in url_lower:
            return 3
        
        # Priority 4: Other government
        if '.gov.in' in url_lower or '.nic.in' in url_lower:
            return 4
        
        return 100
    
    @classmethod
    def is_quality_content(cls, content: str, min_length: int = 50) -> bool:
        """Check if content has meaningful information"""
        if not content or not isinstance(content, str):
            return False
        
        content_stripped = content.strip()
        
        # Minimum length check
        if len(content_stripped) < min_length:
            return False
        
        # Check if content is not just whitespace/newlines
        if len(content_stripped.replace('\n', '').replace('\r', '').replace(' ', '')) < 20:
            return False
        
        # Check for common error messages
        error_indicators = [
            'page not found', '404', 'error', 'access denied',
            'forbidden', '403', '500', 'server error',
            'under maintenance', 'coming soon', 'under construction'
        ]
        content_lower = content_stripped[:200].lower()
        if any(indicator in content_lower for indicator in error_indicators):
            return False
        
        return True
    
    @classmethod
    def extract_college_domain(cls, college_name: str) -> str:
        """Extract likely domain pattern from college name"""
        # Common patterns
        name_lower = college_name.lower()
        
        if 'iit' in name_lower:
            # Extract location
            parts = name_lower.split()
            for i, part in enumerate(parts):
                if 'iit' in part and i + 1 < len(parts):
                    return f"iit{parts[i+1]}"
        
        return ""


# ============ Retry Logic with Exponential Backoff ============

def retry_with_backoff(max_retries: int = 3, base_delay: float = 0.5, max_delay: float = 8.0):
    """Decorator for retry logic with exponential backoff"""
    def decorator(func):
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            last_exception = None
            for attempt in range(max_retries):
                try:
                    return func(*args, **kwargs)
                except Exception as e:
                    last_exception = e
                    if attempt < max_retries - 1:
                        delay = min(base_delay * (2 ** attempt), max_delay)
                        time.sleep(delay)
                        logging.warning(f"Retry {attempt + 1}/{max_retries} for {func.__name__}: {e}")
            raise last_exception
        return wrapper
    return decorator


# ============ Structured Data Parsers ============

class StructuredDataParser:
    """Parse structured data from NIRF PDFs, tables, and official documents"""
    
    # NIRF data patterns for extraction
    NIRF_PATTERNS = {
        'median_salary': [
            r'median\s*(?:salary|package|ctc|compensation)[:\s]*(?:rs\.?|inr|₹)?\s*([\d,]+(?:\.\d+)?)\s*(?:lpa|lakhs?|lac|per\s*annum)?',
            r'(?:rs\.?|inr|₹)\s*([\d,]+(?:\.\d+)?)\s*(?:lpa|lakhs?)?\s*median',
            r'median[:\s]*([\d.]+)\s*(?:lakh|lac)',
        ],
        'highest_salary': [
            r'(?:highest|maximum|max|top)\s*(?:salary|package|ctc)[:\s]*(?:rs\.?|inr|₹)?\s*([\d,]+(?:\.\d+)?)',
            r'(?:rs\.?|inr|₹)\s*([\d,]+(?:\.\d+)?)\s*(?:lpa|lakhs?)?\s*(?:highest|maximum)',
        ],
        'placement_percentage': [
            r'placement\s*(?:rate|percentage|%)[:\s]*([\d.]+)\s*%?',
            r'([\d.]+)\s*%\s*(?:placed|placement)',
            r'(?:placed|placement)[:\s]*([\d.]+)\s*%',
        ],
        'total_faculty': [
            r'(?:total|number\s*of)\s*faculty[:\s]*(\d+)',
            r'faculty\s*(?:strength|members|count)[:\s]*(\d+)',
            r'(\d+)\s*(?:faculty\s*members|professors)',
        ],
        'phd_faculty': [
            r'(?:faculty\s*with\s*)?ph\.?d\.?[:\s]*(\d+)',
            r'(\d+)\s*(?:faculty)?\s*with\s*ph\.?d',
            r'doctorate[:\s]*(\d+)',
        ],
        'total_students': [
            r'(?:total|enrolled)\s*students?[:\s]*(\d+)',
            r'student\s*(?:strength|enrollment)[:\s]*(\d+)',
            r'(\d+)\s*students?\s*enrolled',
        ],
        'nirf_rank': [
            r'nirf\s*(?:rank|ranking)[:\s]*#?(\d+)',
            r'ranked?\s*#?(\d+)\s*(?:in\s*)?nirf',
            r'nirf\s*(?:20\d{2})?[:\s]*#?(\d+)',
        ],
        'phd_students': [
            r'ph\.?d\.?\s*(?:students?|scholars?|enrollment|enrolled)[:\s]*(\d+)',
            r'(\d+)\s*(?:ph\.?d\.?|doctoral)\s*(?:students?|scholars?)',
            r'research\s*scholars?[:\s]*(\d+)',
            r'(\d+)\s*research\s*scholars?',
            r'doctoral\s*(?:students?|candidates?)[:\s]*(\d+)',
            r'(?:total|number\s*of)\s*ph\.?d[:\s]*(\d+)',
            r'ph\.?d\.?\s*programme?[:\s]*(\d+)\s*students?',
        ],
    }
    
    @classmethod
    def extract_numeric_data(cls, text: str, data_type: str) -> Optional[float]:
        """Extract numeric data using patterns"""
        if data_type not in cls.NIRF_PATTERNS:
            return None
        
        text_lower = text.lower()
        for pattern in cls.NIRF_PATTERNS[data_type]:
            match = re.search(pattern, text_lower, re.IGNORECASE)
            if match:
                value_str = match.group(1).replace(',', '')
                try:
                    return float(value_str)
                except ValueError:
                    continue
        return None
    
    @classmethod
    def extract_table_data(cls, html_content: str) -> List[Dict[str, Any]]:
        """Extract data from HTML tables"""
        tables_data = []
        try:
            soup = BeautifulSoup(html_content, 'html.parser')
            for table in soup.find_all('table'):
                rows = table.find_all('tr')
                if not rows:
                    continue
                
                # Extract headers
                headers = []
                header_row = rows[0]
                for th in header_row.find_all(['th', 'td']):
                    headers.append(th.get_text(strip=True))
                
                # Extract data rows
                table_data = []
                for row in rows[1:]:
                    cells = row.find_all(['td', 'th'])
                    row_data = {}
                    for i, cell in enumerate(cells):
                        key = headers[i] if i < len(headers) else f"col_{i}"
                        row_data[key] = cell.get_text(strip=True)
                    if row_data:
                        table_data.append(row_data)
                
                if table_data:
                    tables_data.append({
                        'headers': headers,
                        'rows': table_data
                    })
        except Exception as e:
            logging.warning(f"Table extraction error: {e}")
        
        return tables_data
    
    @classmethod
    def extract_all_numbers(cls, text: str) -> Dict[str, Any]:
        """Extract all structured numeric data from text"""
        extracted = {}
        for data_type in cls.NIRF_PATTERNS.keys():
            value = cls.extract_numeric_data(text, data_type)
            if value is not None:
                extracted[data_type] = value
        return extracted
    
    @classmethod
    def parse_currency_value(cls, text: str) -> Optional[float]:
        """
        Parse currency value from text using enhanced CurrencyParser.
        Returns value in rupees.
        """
        return CurrencyParser.parse_currency(text)
    
    @classmethod
    def format_currency_value(cls, rupees: float) -> str:
        """Format rupees to LPA or Cr format"""
        return CurrencyParser.format_currency(rupees)
    
    @classmethod
    def extract_year_from_context(cls, text: str, url: str = "") -> Optional[int]:
        """
        Extract year from text with context (URL).
        Prioritizes recent years: 2025 > 2024 > 2023
        """
        return YearExtractor.extract_year(text, context=url)
    
    @classmethod
    def calculate_data_recency(cls, year: Optional[int]) -> str:
        """Calculate recency rating: high, medium, low, or unknown"""
        return YearExtractor.calculate_recency(year)


# ============ Source Priority Classification ============

class SourcePriorityClassifier:
    """Classify data sources by reliability priority for dual confidence assessment"""
    
    # CRITICAL PRIORITY: NIRF documents (ALWAYS highest priority)
    NIRF_PATTERNS = [
        r'nirf.*20[0-9]{2}',  # nirf2025, nirf-2025, etc.
        r'20[0-9]{2}.*nirf',  # 2025-nirf, etc.
        r'/static/media/.*20[0-9]{6}',  # React app PDFs with YYYYMMDD dates - 8 total digits
        r'/static/media/.*(?:ropar|iit|institute).*20[0-9]{6}',  # Institute-specific NIRF PDFs
        r'20[0-9]{6}[-_\s].*(?:Ov|ov|overall|engg|engineering)',  # Date + category in filename
        r'overall.*ranking', r'engineering.*ranking',  # NIRF categories
        r'india.*ranking.*framework',
        r'nirfindia\.org'
    ]
    
    # HIGH PRIORITY: Official college websites and government portals
    HIGH_PRIORITY_DOMAINS = [
        'ac.in', 'edu.in', 'gov.in',
        'nirfindia.org', 'nrf.gov.in',
        'naac.gov.in', 'aicte-india.org',
        'ugc.ac.in', 'ugc.gov.in',
        'mhrd.gov.in', 'education.gov.in',
        'nic.in'
    ]
    
    # MEDIUM PRIORITY: Wikipedia and educational databases
    MEDIUM_PRIORITY_DOMAINS = [
        'wikipedia.org',
        'wikidata.org',
        'wikimedia.org',
        'scholar.google.com',
        'researchgate.net',
        'academia.edu'
    ]
    
    # LOW PRIORITY: Aggregator sites
    LOW_PRIORITY_DOMAINS = [
        'shiksha.com',
        'collegeduniya.com',
        'careers360.com',
        'collegepravesh.com',
        'collegedekho.com',
        'getmyuni.com',
        'studygap.com'
    ]
    
    @classmethod
    def get_source_priority(cls, url: str) -> str:
        """Classify URL into priority levels. Returns: 'critical', 'high', 'medium', or 'low'"""
        if not url or url == "N/A":
            return "low"
        
        from urllib.parse import unquote
        url_lower = url.lower()
        url_decoded = unquote(url_lower)  # Decode URL encoding (%20 -> space)
        
        # CRITICAL: Check if this is a NIRF document (HIGHEST PRIORITY)
        for pattern in cls.NIRF_PATTERNS:
            if re.search(pattern, url_decoded):
                return "critical"
        
        # Explicit NIRF indicators in filename/path
        if 'nirf' in url_decoded or 'ranking' in url_decoded:
            # But exclude newsletters and general pages
            if not any(x in url_decoded for x in ['newsletter', 'prajwalam', 'brochure', 'news', 'blog']):
                return "critical"
        
        # Check high priority domains
        for domain in cls.HIGH_PRIORITY_DOMAINS:
            if domain in url_lower:
                return "high"
        
        # Check medium priority domains
        for domain in cls.MEDIUM_PRIORITY_DOMAINS:
            if domain in url_lower:
                return "medium"
        
        # Check low priority domains
        for domain in cls.LOW_PRIORITY_DOMAINS:
            if domain in url_lower:
                return "low"
        
        # Default: if it's .ac.in or .edu.in, high priority
        if '.ac.in' in url_lower or '.edu.in' in url_lower:
            return "high"
        
        # Otherwise medium (benefit of doubt)
        return "medium"
    
    @classmethod
    def get_confidence_from_priority(cls, priority: str) -> str:
        """Map source priority to confidence level. Returns: 'high', 'medium', or 'low'"""
        priority_to_confidence = {
            'critical': 'high',  # NIRF documents get highest confidence
            'high': 'high',
            'medium': 'medium',
            'low': 'low'
        }
        return priority_to_confidence.get(priority, 'low')


# ============ KPI Auditor Class ============

class CollegeKPIAuditor:
    def __init__(self):
        self.kpis_data = self._load_kpis_from_schema()
        
        # Initialize API key rotation for Serper
        serper_keys = os.environ.get("SERPER_API_KEY", "")
        if ',' in serper_keys:
            serper_keys_list = [k.strip() for k in serper_keys.split(',') if k.strip()]
        else:
            serper_keys_list = [serper_keys] if serper_keys else []
        
        self.serper_api_rotator = APIKeyRotator(serper_keys_list, cooldown_period=300)
        self.gemini_api_key = os.environ.get("GEMINI_API_KEY")
        self.validator = OfficialSourceValidator()
        self.parser = StructuredDataParser()
        
        # Initialize session with proper SSL handling
        self.session = requests.Session()
        self.session.headers.update({
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
            'Accept-Language': 'en-US,en;q=0.5',
        })
        
        # Suppress SSL warnings only (but keep verification on by default)
        urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
        
        # Circuit breakers for different services
        self.serper_circuit_breaker = get_circuit_breaker('serper', failure_threshold=5)
        self.fetch_circuit_breaker = get_circuit_breaker('fetch', failure_threshold=10)
    
    def __del__(self):
        """Cleanup session on destruction"""
        try:
            if hasattr(self, 'session'):
                self.session.close()
                logging.info("HTTP session closed")
        except Exception as e:
            logging.warning(f"Error closing session: {e}")
        
    def _load_kpis_from_schema(self) -> List[Dict]:
        """Load KPIs from KPI_SCHEMA constant"""
        kpis = []
        for kpi_item in KPI_SCHEMA["college_kpis"]:
            kpis.append({
                'name': kpi_item['display_name'],
                'field_name': kpi_item['field_name'],
                'category': kpi_item['category'],
                'data_type': kpi_item['data_type'],
                'unit': kpi_item['unit'],
                'validation_rules': kpi_item['validation_rules'],
                'extraction_instruction': kpi_item['extraction_instruction'],
                'remarks_required': kpi_item.get('remarks_required', False),
                'search_keywords': kpi_item.get('search_keywords', []),
            })
        logger.info(f"Loaded {len(kpis)} KPIs from schema")
        return kpis
    
    def _extract_location_from_name(self, college_name: str) -> Optional[str]:
        """Extract location/city from college name"""
        # Common patterns: "College Name, City" or "College Name City"
        # Extract city names and common location indicators
        location_keywords = [
            'greater noida', 'noida', 'mumbai', 'delhi', 'bangalore', 'chennai', 'kolkata', 'hyderabad', 
            'pune', 'ahmedabad', 'gurgaon', 'gurugram', 'jaipur', 'lucknow', 'kanpur',
            'nagpur', 'indore', 'bhopal', 'visakhapatnam', 'patna', 'vadodara', 'surat',
            'coimbatore', 'kochi', 'thiruvananthapuram', 'bhubaneswar', 'raipur',
            'chandigarh', 'ludhiana', 'amritsar', 'dehradun', 'ranchi', 'guwahati',
            'trichy', 'madurai', 'mysore', 'mangalore', 'vellore'
        ]
        
        college_name_lower = college_name.lower()
        
        # Check for comma-separated location
        if ',' in college_name:
            parts = college_name.split(',')
            if len(parts) > 1:
                potential_location = parts[-1].strip().lower()
                if any(loc in potential_location for loc in location_keywords):
                    # Return the most specific match
                    for loc in location_keywords:
                        if loc in potential_location:
                            return loc
        
        # Check for location keywords in name (prioritize longer matches first)
        for location in sorted(location_keywords, key=len, reverse=True):
            if location in college_name_lower:
                return location
        
        return None
    
    def _filter_urls_by_location(self, urls: List[str], target_location: Optional[str], college_name: str) -> List[str]:
        """Filter URLs to match target location and exclude conflicting locations"""
        if not target_location or not urls:
            return urls
        
        # Common location variations
        location_map = {
            'noida': ['noida', 'greater-noida', 'greater_noida'],
            'greater noida': ['noida', 'greater-noida', 'greater_noida'],
            'mumbai': ['mumbai', 'bombay'],
            'bangalore': ['bangalore', 'bengaluru'],
            'gurugram': ['gurgaon', 'gurugram'],
            'gurgaon': ['gurgaon', 'gurugram'],
        }
        
        target_variants = location_map.get(target_location.lower(), [target_location.lower()])
        
        # Define conflicting locations (cities to exclude)
        all_locations = [
            'noida', 'mumbai', 'delhi', 'bangalore', 'chennai', 'kolkata', 'hyderabad', 
            'pune', 'ahmedabad', 'gurgaon', 'gurugram', 'jaipur', 'lucknow', 'raipur',
            'greater-noida', 'greater_noida', 'bengaluru', 'bombay'
        ]
        
        # Remove target location and its variants from exclusion list
        conflicting_locations = [loc for loc in all_locations if loc not in target_variants]
        
        filtered = []
        for url in urls:
            url_lower = url.lower()
            
            # Check if URL contains conflicting location
            has_conflict = any(f'/{loc}/' in url_lower or f'/{loc}.' in url_lower or f'-{loc}' in url_lower 
                              for loc in conflicting_locations)
            
            # Check if URL contains target location
            has_target = any(loc in url_lower for loc in target_variants)
            
            # Include if: has target location OR (no conflict AND no specific location mentioned)
            if has_target:
                filtered.insert(0, url)  # Prioritize matching URLs
            elif not has_conflict:
                filtered.append(url)
        
        if filtered and len(filtered) < len(urls):
            logger.info(f"Location filter: Kept {len(filtered)}/{len(urls)} URLs for location '{target_location}'")
        
        return filtered if filtered else urls  # Return original if all filtered out

    def search_for_kpi(self, college_name: str, kpi: Dict, abbreviation: str = "", college_website_url: Optional[str] = None) -> Dict[str, Any]:
        """Search specifically for a single KPI using its keywords - ENHANCED VERSION"""
        kpi_data = {
            "kpi_name": kpi['name'],
            "search_results": [],
            "fetched_content": []
        }
        
        keywords = kpi.get('search_keywords', [])
        if not keywords:
            return kpi_data
        
        # Build targeted search queries for this KPI - MORE COMPREHENSIVE
        queries = []
        
        # Use top 2 keywords for speed
        for keyword in keywords[:2]:
            queries.append(f'"{college_name}" {keyword}')
        
        # Add site-specific search for official sources
        primary_keyword = keywords[0] if keywords else kpi['name']
        queries.append(f'site:.ac.in OR site:.edu.in "{college_name}" {primary_keyword}')
        
        seen_urls = set()
        
        # Reduced to 3 queries per KPI for speed
        for query in queries[:3]:
            result = self.search_official_sources(query, num_results=5, restrict_to_site=college_website_url)
            if result.get("official_results"):
                for r in result["official_results"]:
                    url = r.get('url', '')
                    
                    # STRICT: Filter to college domain only when available
                    if college_website_url:
                        college_domain = urlparse(college_website_url).netloc
                        result_domain = urlparse(url).netloc
                        if college_domain != result_domain:
                            continue
                    
                    if url not in seen_urls:
                        seen_urls.add(url)
                        kpi_data["search_results"].append(r)
            time.sleep(0.03)  # Minimal rate limiting
        
        # Fetch content from top 3 official URLs for speed
        urls_to_fetch = [r['url'] for r in kpi_data["search_results"][:3]]
        
        for url in urls_to_fetch:
            content = self.fetch_webpage_content(url, max_length=8000)
            if content.get('success'):
                kpi_data["fetched_content"].append(content)
        
        return kpi_data

    def search_public_disclosure(self, college_name: str, abbreviation: str = "", college_website_url: Optional[str] = None) -> Dict[str, Any]:
        """
        Search for Mandatory Public Disclosure pages (AICTE/UGC requirement).
        These pages contain standardized KPI data like faculty, infrastructure, placements, etc.
        """
        disclosure_data = {
            "pages": [],
            "pdfs": [],
            "fetched_content": []
        }
        
        # Mandatory Disclosure search queries - AICTE requires all colleges to have these
        disclosure_queries = [
            f'"{college_name}" "mandatory disclosure" site:.ac.in OR site:.edu.in',
            f'"{college_name}" "public disclosure" AICTE',
            f'"{college_name}" "mandatory disclosure" filetype:pdf',
            f'"{college_name}" AICTE approval faculty infrastructure',
        ]
        
        if abbreviation:
            disclosure_queries.append(f'"{abbreviation}" "mandatory disclosure"')
        
        seen_urls = set()
        
        # Extract college domain for filtering
        college_domain = None
        if college_website_url:
            college_domain = urlparse(college_website_url).netloc
            logger.info(f"[DISCLOSURE] Will filter to domain: {college_domain}")
        
        # Execute disclosure searches in parallel
        def run_disclosure_search(query):
            return self.search_official_sources(query, num_results=10, restrict_to_site=college_website_url)
        
        with ThreadPoolExecutor(max_workers=4) as executor:
            future_to_query = {executor.submit(run_disclosure_search, q): q for q in disclosure_queries}
            for future in as_completed(future_to_query):
                result = future.result()
                if result.get("official_results"):
                    for r in result["official_results"]:
                        url = r.get('url', '')
                        if url and url not in seen_urls:
                            # STRICT: Only accept URLs from the college domain
                            if college_domain:
                                result_domain = urlparse(url).netloc
                                if college_domain != result_domain:
                                    logger.debug(f"[DISCLOSURE] Filtering out non-college URL: {url} (not from {college_domain})")
                                    continue
                            
                            seen_urls.add(url)
                            # Check if it's a PDF
                            if url.lower().endswith('.pdf'):
                                disclosure_data["pdfs"].append(r)
                            else:
                                disclosure_data["pages"].append(r)
        
        logger.info(f"Found {len(disclosure_data['pages'])} disclosure pages and {len(disclosure_data['pdfs'])} PDFs")
        return disclosure_data

    def fetch_disclosure_page_and_pdfs(self, page_url: str, max_pdfs: int = 3, campus_path: Optional[str] = None) -> Dict[str, Any]:
        """
        Fetch a disclosure page and extract PDF links from it.
        Returns page content plus any linked PDF content.
        
        Args:
            page_url: URL of the disclosure page to fetch
            max_pdfs: Maximum number of PDFs to extract
            campus_path: If provided (e.g., 'gwalior'), only include PDFs from this campus
        """
        result = {
            "page_content": None,
            "pdf_links": [],
            "pdf_contents": []
        }
        
        try:
            # Fetch the HTML page
            response = self.session.get(page_url, timeout=30, allow_redirects=True, verify=False)
            response.raise_for_status()
            
            soup = BeautifulSoup(response.text, 'html.parser')
            
            # Extract all PDF links from the page
            base_url = '/'.join(page_url.split('/')[:3])
            pdf_links = set()
            
            for link in soup.find_all('a', href=True):
                href = link['href']
                # Check if it's a PDF link
                if '.pdf' in href.lower():
                    # Handle relative URLs
                    if href.startswith('/'):
                        full_url = base_url + href
                    elif href.startswith('http'):
                        full_url = href
                    else:
                        # Relative to current path
                        full_url = '/'.join(page_url.rsplit('/', 1)[:-1]) + '/' + href
                    
                    # Campus filtering: if campus_path is provided, only include PDFs from that campus
                    if campus_path:
                        parsed_pdf = urlparse(full_url)
                        pdf_path_lower = parsed_pdf.path.lower()
                        
                        # Skip PDFs from other campuses
                        if f"/{campus_path.lower()}/" not in pdf_path_lower and not pdf_path_lower.startswith(f"/{campus_path.lower()}"):
                            logger.debug(f"[CAMPUS FILTER] Excluding PDF from different campus: {full_url}")
                            continue
                    
                    # Filter for disclosure-related PDFs
                    href_lower = href.lower()
                    if any(kw in href_lower for kw in ['disclosure', 'faculty', 'infrastructure', 'placement', 
                                                        'admission', 'approval', 'aicte', 'mandatory', 
                                                        'annual', 'report', 'ssr', 'aqar', 'naac']):
                        pdf_links.add(full_url)
                    elif len(pdf_links) < max_pdfs:
                        # Include other PDFs if we haven't found disclosure-specific ones
                        pdf_links.add(full_url)
            
            # Remove script, style elements for text extraction
            for script in soup(["script", "style", "nav", "footer", "header", "aside"]):
                script.decompose()
            
            text = soup.get_text(separator=' ', strip=True)
            text = re.sub(r'\s+', ' ', text)
            
            result["page_content"] = {
                "url": page_url,
                "title": soup.title.string if soup.title else "Disclosure Page",
                "content": text[:15000],
                "success": True
            }
            
            result["pdf_links"] = list(pdf_links)[:max_pdfs]
            
            # Fetch PDF contents in parallel
            def fetch_single_pdf(pdf_url):
                return self._fetch_pdf_content(pdf_url, max_length=25000)
            
            if result["pdf_links"]:
                with ThreadPoolExecutor(max_workers=3) as executor:
                    future_to_pdf = {executor.submit(fetch_single_pdf, url): url for url in result["pdf_links"]}
                    for future in as_completed(future_to_pdf):
                        pdf_content = future.result()
                        if pdf_content.get("success"):
                            result["pdf_contents"].append(pdf_content)
                            logger.info(f"Extracted PDF content: {pdf_content['url']} ({len(pdf_content.get('content', ''))} chars)")
            
        except Exception as e:
            logger.warning(f"Failed to fetch disclosure page {page_url}: {e}")
        
        return result

    def _fetch_pdf_content(self, url: str, max_length: int = 20000) -> Dict[str, Any]:
        """Fetch and extract text content from a PDF file with multiple fallback strategies"""
        import io
        
        # Try HTTPS first if URL uses HTTP
        urls_to_try = []
        if url.startswith('http://'):
            https_url = url.replace('http://', 'https://', 1)
            urls_to_try = [https_url, url]  # Try HTTPS first, then HTTP
            logger.info(f"PDF uses HTTP, will try HTTPS first: {https_url}")
        else:
            urls_to_try = [url]
        
        last_error = None
        
        for attempt_url in urls_to_try:
            try:
                # Determine SSL verification
                verify_ssl = should_verify_ssl(attempt_url)
                
                logger.info(f"Fetching PDF: {attempt_url}")
                response = self.session.get(attempt_url, timeout=90, verify=verify_ssl, stream=True)
                response.raise_for_status()
                
                # Get PDF content
                pdf_bytes = response.content
                
                # Use enhanced PDF extraction with fallback
                text = extract_text_from_pdf_with_fallback(pdf_bytes, max_pages=30)
                
                if not text:
                    last_error = "Failed to extract text from PDF"
                    continue
                
                # Truncate if too long
                if len(text) > max_length:
                    text = text[:max_length] + "..."
                
                # Validate content quality
                if not self.validator.is_quality_content(text, min_length=30):
                    logger.warning(f"Poor quality PDF content from {attempt_url}: length={len(text)}")
                    last_error = "PDF content quality check failed"
                    continue
                
                logger.info(f"Successfully fetched PDF from {attempt_url} ({len(text)} chars)")
                return {
                    "url": attempt_url,
                    "title": f"PDF: {attempt_url.split('/')[-1]}",
                    "content": text,
                    "success": True
                }
                    
            except requests.exceptions.Timeout as e:
                last_error = f"Timeout after 90s: {str(e)}"
                logger.warning(f"Timeout fetching PDF from {attempt_url}: {e}")
                continue
            except Exception as e:
                last_error = str(e)
                logger.warning(f"Failed to fetch PDF from {attempt_url}: {e}")
                continue  # Try next URL
        
        # All attempts failed
        logger.error(f"Failed to fetch PDF from all URLs tried: {urls_to_try}")
        return {"url": url, "content": "", "error": last_error or "Unknown error", "success": False}

    @exponential_backoff_retry(max_retries=2, base_delay=1.0)
    def fetch_webpage_content(self, url: str, max_length: int = 20000, retry_count: int = 2) -> Dict[str, Any]:
        """Fetch and extract text content from a webpage with improved error handling and CACHING"""
        # Validate URL first
        if not self.validator.is_valid_url(url):
            logger.warning(f"Invalid URL skipped: {url}")
            return {"url": url, "content": "", "error": "Invalid URL format", "success": False}
        
        # Check cache first
        cache_key = content_cache._get_key(url, max_length)
        cached_result = content_cache.get(cache_key)
        if cached_result is not None:
            logger.debug(f"Cache hit for URL: {url[:50]}...")
            return cached_result
        
        try:
            # Handle PDF files
            if url.lower().endswith('.pdf'):
                result = self._fetch_pdf_content(url, max_length)
                if result.get("success"):
                    content_cache.set(cache_key, result)
                return result
            
            # Determine SSL verification
            verify_ssl = should_verify_ssl(url)
            if not verify_ssl:
                logger.warning(f"SSL verification disabled for: {url}")
            
            # Increased timeout to 60 seconds for slow servers
            response = self.session.get(url, timeout=60, allow_redirects=True, verify=verify_ssl)
            response.raise_for_status()
            
            # Parse HTML safely
            soup = safe_html_parse(response.text, 'html.parser')
            if not soup:
                return {"url": url, "content": "", "error": "Failed to parse HTML", "success": False}
            
            # Extract tables for structured data
            tables_data = StructuredDataParser.extract_table_data(response.text)
            
            # Remove script, style elements
            for script in soup(["script", "style", "nav", "footer", "header", "aside"]):
                script.decompose()
            
            # Get text
            text = soup.get_text(separator=' ', strip=True)
            
            # Clean up whitespace
            text = re.sub(r'\s+', ' ', text)
            
            # Append table data as structured text
            if tables_data:
                text += "\n\n=== EXTRACTED TABLES ===\n"
                for i, table in enumerate(tables_data[:3]):  # Limit to 3 tables
                    text += f"Table {i+1}: {json.dumps(table['rows'][:10])}\n"
            
            # Truncate if too long
            if len(text) > max_length:
                text = text[:max_length] + "..."
            
            # Validate content quality
            if not self.validator.is_quality_content(text, min_length=50):
                logger.warning(f"Poor quality content from {url}: length={len(text)}")
                return {"url": url, "content": "", "error": "Content quality check failed", "success": False}
            
            result = {
                "url": url,
                "title": soup.title.string.strip() if soup.title and soup.title.string else "",
                "content": text,
                "tables": tables_data[:3] if tables_data else [],
                "success": True
            }
            
            # Cache the result
            content_cache.set(cache_key, result)
            return result
            
        except requests.exceptions.Timeout as e:
            logger.warning(f"Timeout fetching {url} after 60s: {e}")
            return {"url": url, "content": "", "error": f"Timeout after 60s: {str(e)}", "success": False}
        except requests.exceptions.SSLError as e:
            logger.error(f"SSL error fetching {url}: {e}")
            return {"url": url, "content": "", "error": f"SSL Error: {str(e)}", "success": False}
        except Exception as e:
            logger.warning(f"Failed to fetch {url}: {e}")
            return {"url": url, "content": "", "error": str(e), "success": False}

    def fetch_wikipedia_content(self, college_name: str) -> Dict[str, Any]:
        """Fetch Wikipedia content using Wikipedia API"""
        try:
            # Clean and encode college name for Wikipedia search
            search_term = college_name.replace(" ", "_")
            
            # First, search for the page
            search_url = f"https://en.wikipedia.org/w/api.php?action=query&list=search&srsearch={quote(college_name)}&format=json"
            response = self.session.get(search_url, timeout=10)
            search_results = response.json()
            
            if not search_results.get('query', {}).get('search'):
                return {"url": "", "content": "", "success": False, "error": "No Wikipedia page found"}
            
            # Get the first result's title
            page_title = search_results['query']['search'][0]['title']
            
            # Now get the page content
            content_url = f"https://en.wikipedia.org/w/api.php?action=query&prop=extracts&exintro=false&explaintext=true&titles={quote(page_title)}&format=json"
            response = self.session.get(content_url, timeout=10)
            content_data = response.json()
            
            pages = content_data.get('query', {}).get('pages', {})
            for page_id, page_data in pages.items():
                if page_id != '-1':
                    content = page_data.get('extract', '')
                    wiki_url = f"https://en.wikipedia.org/wiki/{quote(page_title.replace(' ', '_'))}"
                    return {
                        "url": wiki_url,
                        "title": page_data.get('title', ''),
                        "content": content[:20000] if len(content) > 20000 else content,
                        "success": True
                    }
            
            return {"url": "", "content": "", "success": False, "error": "Page content not found"}
            
        except Exception as e:
            logger.warning(f"Wikipedia fetch failed: {e}")
            return {"url": "", "content": "", "success": False, "error": str(e)}

    def extract_institute_info(self, college_name: str, wiki_content: str) -> Dict[str, Any]:
        """Extract basic institute information from Wikipedia content"""
        institute_info = {
            "full_name": college_name,
            "short_name": "",
            "location": "",
            "city": "",
            "state": "",
            "established": "",
            "type": "",
            "motto": "",
            "website": "",
            "wikipedia_url": ""
        }
        
        if not wiki_content:
            return institute_info
        
        try:
            content = wiki_content[:5000]  # First part usually has key info
            
            # Extract location patterns
            location_patterns = [
                r'(?:located|situated|based)\s+(?:in|at)\s+([A-Z][a-z]+(?:\s+[A-Z][a-z]+)*),?\s*([A-Z][a-z]+(?:\s+[A-Z][a-z]+)*)?',
                r'(?:city|town|district)\s+(?:of|in)\s+([A-Z][a-z]+(?:\s+[A-Z][a-z]+)*)',
                r'([A-Z][a-z]+(?:\s+[A-Z][a-z]+)*),\s*([A-Z][a-z]+(?:\s+[A-Z][a-z]+)*),\s*India',
            ]
            
            for pattern in location_patterns:
                match = re.search(pattern, content)
                if match:
                    groups = match.groups()
                    if groups[0]:
                        institute_info["city"] = groups[0].strip()
                    if len(groups) > 1 and groups[1]:
                        institute_info["state"] = groups[1].strip()
                    if institute_info["city"]:
                        institute_info["location"] = f"{institute_info['city']}, {institute_info['state']}" if institute_info["state"] else institute_info["city"]
                    break
            
            # Extract establishment year
            established_patterns = [
                r'(?:established|founded|started)\s+(?:in\s+)?([12][0-9]{3})',
                r'([12][0-9]{3})\s*[-–]\s*(?:present|now)',
                r'since\s+([12][0-9]{3})',
            ]
            
            for pattern in established_patterns:
                match = re.search(pattern, content, re.IGNORECASE)
                if match:
                    institute_info["established"] = match.group(1)
                    break
            
            # Extract type of institution
            type_patterns = [
                r'(public|private|autonomous|deemed|state|central|national)\s+(?:university|institute|college)',
                r'(?:is\s+a[n]?)\s+(public|private|autonomous|deemed)\s+(?:research)?\s*(?:university|institute|institution)',
            ]
            
            for pattern in type_patterns:
                match = re.search(pattern, content, re.IGNORECASE)
                if match:
                    institute_info["type"] = match.group(1).title()
                    break
            
            # Extract motto
            motto_match = re.search(r'motto[:\s]+["\']?([^"\n]+)["\']?', content, re.IGNORECASE)
            if motto_match:
                institute_info["motto"] = motto_match.group(1).strip()[:100]
            
            # Extract website
            website_match = re.search(r'(?:website|official\s+site)[:\s]+(?:www\.)?([a-z0-9.-]+\.(?:ac\.in|edu\.in|edu|org))', content, re.IGNORECASE)
            if website_match:
                institute_info["website"] = f"https://www.{website_match.group(1)}"
            
            # Generate short name/abbreviation
            words = college_name.split()
            if len(words) > 2:
                # Check for common abbreviations in content
                abbrev_match = re.search(r'\(([A-Z]{2,10})\)', content)
                if abbrev_match:
                    institute_info["short_name"] = abbrev_match.group(1)
                else:
                    # Generate from initials of major words
                    initials = ''.join([w[0].upper() for w in words if w[0].isupper() and len(w) > 2])
                    if len(initials) >= 2:
                        institute_info["short_name"] = initials
            
        except Exception as e:
            logger.warning(f"Failed to extract institute info: {e}")
        
        return institute_info

    async def get_college_website_from_gemini(self, college_name: str, client) -> Optional[str]:
        """Ask Gemini to provide the official website URL for the college"""
        try:
            prompt = f"What is the base URL for {college_name}?"
            
            response = client.models.generate_content(
                model='gemini-2.5-flash',
                contents=prompt,
                config=types.GenerateContentConfig(
                    temperature=0.3,  # Slightly higher to avoid truncation
                    max_output_tokens=300  # Ensure full URL is returned
                )
            )
            
            # Get raw response text
            raw_text = response.text.strip()
            logger.info(f"[GEMINI] Raw response: '{raw_text}'")
            
            # Clean up the response - remove markdown, extra whitespace, etc.
            url = raw_text.replace('```', '').replace('`', '').replace('**', '').replace('*', '').strip()
            
            # Remove common prefixes if present
            for prefix in ['Official Website URL:', 'URL:', 'Website:', 'Answer:', 'The base URL for', 'is:']:
                if prefix in url:
                    url = url.split(prefix)[-1].strip()
            
            # Extract URL if it's in a sentence using regex
            import re
            
            # First try to extract complete URL with protocol
            url_match = re.search(r'https?://[a-zA-Z0-9][-a-zA-Z0-9._/]*\.[a-zA-Z]{2,}[^\s<>"{}|\\^`\[\]*]*', url)
            if url_match:
                url = url_match.group(0)
                logger.info(f"[GEMINI] Extracted URL from text: {url}")
            else:
                # Try to extract domain without protocol (e.g., "www.jntuh.ac.in" or "jntuh.ac.in")
                domain_match = re.search(r'\b(?:www\.)?[a-zA-Z0-9][-a-zA-Z0-9.]*\.[a-zA-Z]{2,}\b', url)
                if domain_match:
                    domain = domain_match.group(0)
                    # Add https:// prefix
                    url = f"https://{domain}"
                    logger.info(f"[GEMINI] Extracted domain and added protocol: {url}")
            
            # Clean trailing punctuation and markdown
            url = url.rstrip('.,;:*/')
            
            if url.startswith('http'):
                # Parse and validate URL structure
                parsed = urlparse(url)
                if parsed.netloc and '.' in parsed.netloc:
                    # Basic validation: ensure domain has at least 6 chars
                    if len(parsed.netloc) >= 6:
                        # Return the full URL as provided by Gemini (including path if present)
                        final_url = f"{parsed.scheme}://{parsed.netloc}{parsed.path}"
                        # Clean up the URL
                        final_url = final_url.rstrip('/')
                        if not final_url:
                            final_url = f"{parsed.scheme}://{parsed.netloc}"
                        
                        logger.info(f"[GEMINI] Identified official website: {final_url}")
                        return final_url
                    else:
                        logger.warning(f"[GEMINI] Domain too short: {parsed.netloc}")
                        return None
                else:
                    logger.warning(f"[GEMINI] Invalid domain: {parsed.netloc}")
                    return None
            
            logger.warning(f"[GEMINI] Could not extract valid URL from response: '{url}'")
            return None
            
        except Exception as e:
            logger.error(f"[GEMINI] Error getting college website: {e}")
            return None
    
    @exponential_backoff_retry(max_retries=3, base_delay=1.0, max_delay=16.0)
    def search_official_sources(self, query: str, num_results: int = 10, restrict_to_site: Optional[str] = None) -> Dict[str, Any]:
        """Perform web search with strict filtering for official sources only - WITH CACHING AND API KEY ROTATION"""
        
        # Get current API key
        current_key = self.serper_api_rotator.get_current_key()
        if not current_key:
            # Fallback to cache if no API keys available
            cache_key = search_cache._get_key(query, num_results, restrict_to_site)
            cached_result = search_cache.get(cache_key)
            if cached_result is not None:
                logger.warning("All API keys exhausted, using cached result")
                return cached_result
            
            logger.error("No API keys available and no cache hit")
            return {"error": "All SERPER API keys exhausted", "results": []}
        
        # Check cache first
        cache_key = search_cache._get_key(query, num_results, restrict_to_site)
        cached_result = search_cache.get(cache_key)
        if cached_result is not None:
            logger.debug(f"Cache hit for query: {query[:50]}...")
            return cached_result
        
        # Add site restriction if provided
        search_query = query
        if restrict_to_site:
            # Extract domain from URL
            parsed = urlparse(restrict_to_site)
            domain = parsed.netloc or restrict_to_site
            search_query = f"site:{domain} {query}"
            logger.debug(f"Restricting search to site: {domain}")
        
        url = "https://google.serper.dev/search"
        payload = {
            "q": search_query,
            "num": num_results,
            "gl": "in",
            "hl": "en"
        }
        headers = {
            'X-API-KEY': current_key,
            'Content-Type': 'application/json'
        }
        
        try:
            # Use circuit breaker for Serper API calls
            def make_request():
                response = requests.post(url, headers=headers, json=payload, timeout=30)
                response.raise_for_status()
                return response.json()
            
            results = self.serper_circuit_breaker.call(make_request)
            
            filtered_results = []
            
            # Process organic results - filter for official sources only
            for r in results.get("organic", []):
                link = r.get('link', '')
                
                # Validate URL structure first
                if not self.validator.is_valid_url(link):
                    logger.debug(f"Skipping invalid URL: {link}")
                    continue
                
                # Skip non-official sources
                is_blocked = any(blocked in link.lower() for blocked in self.validator.BLOCKED_SOURCES)
                if is_blocked:
                    logger.debug(f"Skipping blocked source: {link}")
                    continue
                
                # Check if official
                is_official = self.validator.is_official_source(link)
                
                if is_official:
                    # Validate snippet quality
                    snippet = r.get('snippet', '')
                    if not snippet or len(snippet.strip()) < 10:
                        logger.debug(f"Skipping result with poor snippet: {link}")
                        continue
                    
                    filtered_results.append({
                        'title': r.get('title', '').strip(),
                        'url': link,
                        'snippet': snippet,
                        'priority': self.validator.get_source_priority(link),
                        'source_type': self._identify_source_type(link)
                    })
            
            # Sort by priority (lower = better)
            filtered_results.sort(key=lambda x: x['priority'])
            
            # Process Knowledge Graph if available
            knowledge_graph = None
            if "knowledgeGraph" in results:
                kg = results["knowledgeGraph"]
                knowledge_graph = {k: v for k, v in kg.items() if isinstance(v, (str, int, float, list))}
            
            result = {
                "query": query,
                "official_results": filtered_results,
                "knowledge_graph": knowledge_graph,
                "total_found": len(filtered_results)
            }
            
            # Cache the result
            search_cache.set(cache_key, result)
            
            return result
            
        except requests.exceptions.HTTPError as e:
            if e.response.status_code == 400:
                logger.error(f"Search failed with 400 for query '{query}': {e}")
                # Mark key as exhausted and try next key
                self.serper_api_rotator.mark_key_failed(current_key, exhausted=True)
                raise APIKeyExhaustedException(f"API key exhausted: {e}")
            else:
                logger.error(f"Search failed for query '{query}': {e}")
                # Temporary failure, mark for cooldown
                self.serper_api_rotator.mark_key_failed(current_key, exhausted=False)
                return {"error": str(e), "results": []}
        except Exception as e:
            logger.error(f"Search failed for query '{query}': {e}")
            # Temporary failure
            self.serper_api_rotator.mark_key_failed(current_key, exhausted=False)
            return {"error": str(e), "results": []}
    
    def _identify_source_type(self, url: str) -> str:
        """Identify the type of official source"""
        url_lower = url.lower()
        
        if 'nirf' in url_lower:
            return "NIRF"
        elif 'naac' in url_lower:
            return "NAAC"
        elif '.ac.in' in url_lower or '.edu.in' in url_lower:
            return "Official College Website"
        elif 'aicte' in url_lower:
            return "AICTE"
        elif 'ugc' in url_lower:
            return "UGC"
        elif '.gov.in' in url_lower:
            return "Government"
        
        return "Other Official"

    async def gather_official_data(self, college_name: str, progress_callback=None, college_website_url: Optional[str] = None, nirf_available: bool = False) -> Dict[str, Any]:
        """
        Gather data ONLY from official sources with ACTUAL page content:
        1. Official College Website (fetched content)
        2. Public Disclosure (AICTE/UGC)
        3. NIRF Search Results
        4. NAAC Documents
        
        Args:
            nirf_available: If False, performs more comprehensive website search
        """
        
        clean_name = college_name.strip()
        
        # Extract location from college name for filtering
        target_location = self._extract_location_from_name(college_name)
        if target_location:
            logger.info(f"[LOCATION FILTER] Detected target location: {target_location}")
        
        # Adjust search depth based on NIRF availability
        max_pages_to_fetch = 8 if nirf_available else 15  # Fetch more pages when NIRF not available
        search_results_per_query = 8 if nirf_available else 12  # More search results when no NIRF
        
        if not nirf_available:
            logger.info(f"[COMPREHENSIVE SEARCH] NIRF not available - fetching up to {max_pages_to_fetch} pages from official website")
        
        all_data = {
            "official_website": [],
            "official_website_content": [],
            "public_disclosure": [],
            "public_disclosure_content": [],
            "nirf": [],
            "naac": [],
            "wikipedia": [],
            "wikipedia_content": [],
            "aggregator_sites": [],
            "combined_text": "",
            "fetched_urls": set(),
            "source_priority_breakdown": {
                "critical_priority": [],
                "high_priority": [],
                "medium_priority": [],
                "low_priority": []
            }
        }
        
        # Generate college abbreviation for better searches
        abbreviation = self._get_college_abbreviation(clean_name)
        search_names = [clean_name]
        if abbreviation:
            search_names.append(abbreviation)
        
        combined_text_parts = []
        
        # ============ PRIORITY 1: OFFICIAL COLLEGE WEBSITE ============
        if progress_callback:
            await progress_callback("Searching Official College Website...", 5)
        
        # Consolidated search queries for speed
        # Use college website restriction if available, otherwise fallback to .ac.in/.edu.in
        if college_website_url:
            official_queries = [
                f'"{clean_name}" official placements faculty',
                f'"{clean_name}" official courses fees infrastructure hostel',
                f'"{clean_name}" placement statistics 2024 2025',
                f'"{clean_name}" PhD research scholars doctoral students enrollment',
            ]
            # Add more comprehensive queries when NIRF not available
            if not nirf_available:
                official_queries.extend([
                    f'"{clean_name}" admissions intake students',
                    f'"{clean_name}" programs courses offered',
                    f'"{clean_name}" about history establishment',
                ])
            if abbreviation:
                official_queries.append(f'"{abbreviation}" official')
        else:
            official_queries = [
                f'site:.ac.in OR site:.edu.in "{clean_name}" official placements faculty',
                f'"{clean_name}" official courses fees infrastructure hostel',
                f'"{clean_name}" placement statistics 2024 2025',
                f'"{clean_name}" PhD research scholars doctoral students enrollment',
            ]
            if not nirf_available:
                official_queries.extend([
                    f'site:.ac.in OR site:.edu.in "{clean_name}" admissions students',
                    f'site:.ac.in OR site:.edu.in "{clean_name}" about history',
                ])
            if abbreviation:
                official_queries.append(f'site:.ac.in OR site:.edu.in "{abbreviation}" official')
        
        official_urls_to_fetch = set()
        
        # Extract campus path from college URL if it's campus-specific
        campus_path = None
        if college_website_url:
            parsed_college_url = urlparse(college_website_url)
            if parsed_college_url.path.strip('/'):
                campus_path = parsed_college_url.path.strip('/').split('/')[0]
                logger.info(f"[CAMPUS FILTER] Detected campus path: /{campus_path}/ - will filter search results")
        
        # Execute searches in parallel using ThreadPoolExecutor
        def run_search(query):
            return self.search_official_sources(query, num_results=search_results_per_query, restrict_to_site=college_website_url)
        
        with ThreadPoolExecutor(max_workers=4) as executor:
            future_to_query = {executor.submit(run_search, q): q for q in official_queries}
            for future in as_completed(future_to_query):
                result = future.result()
                if result.get("official_results"):
                    for r in result["official_results"]:
                        url = r.get('url', '')
                        
                        # STRICT: If we have college website, only accept URLs from that domain
                        if college_website_url:
                            college_domain = urlparse(college_website_url).netloc
                            result_domain = urlparse(url).netloc
                            if college_domain != result_domain:
                                logger.debug(f"Filtering out non-college URL: {url} (not from {college_domain})")
                                continue
                            
                            # If campus-specific URL, filter by campus path
                            if campus_path:
                                parsed_url = urlparse(url)
                                url_path = parsed_url.path.lower()
                                
                                # Check if URL belongs to the same campus
                                if f"/{campus_path.lower()}/" not in url_path and not url_path.startswith(f"/{campus_path.lower()}"):
                                    logger.debug(f"[CAMPUS FILTER] Excluding URL from different campus: {url}")
                                    continue
                        
                        # Add source priority classification
                        priority = SourcePriorityClassifier.get_source_priority(url)
                        r['source_priority'] = priority
                        all_data["source_priority_breakdown"][f"{priority}_priority"].append(url)
                        
                        if r['source_type'] == "Official College Website":
                            all_data["official_website"].append(r)
                            combined_text_parts.append(f"[OFFICIAL WEBSITE SEARCH]\nTitle: {r['title']}\nURL: {r['url']}\nSnippet: {r['snippet']}\n")
                            if r['url'] and not r['url'].lower().endswith('.pdf'):
                                official_urls_to_fetch.add(r['url'])
        
        if progress_callback:
            await progress_callback(f"Official website search complete", 35)
        
        # Apply location filtering to official URLs
        if target_location and official_urls_to_fetch:
            original_count = len(official_urls_to_fetch)
            filtered_official_urls = self._filter_urls_by_location(list(official_urls_to_fetch), target_location, college_name)
            official_urls_to_fetch = set(filtered_official_urls)
            logger.info(f"[LOCATION FILTER] Official pages: {len(official_urls_to_fetch)}/{original_count} URLs after filtering")
        
        # Fetch content from top official pages in parallel
        if progress_callback:
            await progress_callback("Fetching official website content...", 40)
        
        urls_to_fetch = [u for u in list(official_urls_to_fetch)[:max_pages_to_fetch] if u not in all_data["fetched_urls"]]
        
        logger.info(f"[OFFICIAL WEBSITE] Fetching {len(urls_to_fetch)} pages from college website")
        
        def fetch_url(url):
            try:
                return self.fetch_webpage_content(url, max_length=10000)
            except Exception as e:
                logger.warning(f"Failed to fetch {url}: {e}")
                return None
        
        with ThreadPoolExecutor(max_workers=6) as executor:
            future_to_url = {executor.submit(fetch_url, url): url for url in urls_to_fetch}
            for future in as_completed(future_to_url):
                url = future_to_url[future]
                page_content = future.result()
                if page_content and page_content.get("success") and page_content.get("content"):
                    page_content['source_priority'] = 'high'  # Official website is high priority
                    all_data["official_website_content"].append(page_content)
                    all_data["fetched_urls"].add(url)
                    combined_text_parts.append(f"[OFFICIAL WEBSITE PAGE CONTENT]\nURL: {url}\nTitle: {page_content.get('title', '')}\nContent: {page_content['content']}\n")
                    logger.info(f"Fetched official page: {url} ({len(page_content['content'])} chars)")
        
        # ============ PRIORITY 2.5: MANDATORY PUBLIC DISCLOSURE (AICTE/UGC) ============
        if progress_callback:
            await progress_callback("Searching Mandatory Public Disclosure pages...", 45)
        
        # Search for public disclosure pages and PDFs
        disclosure_data = self.search_public_disclosure(clean_name, abbreviation, college_website_url)
        
        # Apply campus-specific filtering when we have a branch-specific URL
        campus_path_for_filtering = None  # Store for later use
        if college_website_url:
            parsed_college_url = urlparse(college_website_url)
            campus_path = parsed_college_url.path.strip('/').split('/')[0] if parsed_college_url.path.strip('/') else None
            
            if campus_path:
                campus_path_for_filtering = campus_path  # Store for use in PDF fetching
                # This is a campus-specific URL (e.g., /gwalior/, /mumbai/)
                logger.info(f"[CAMPUS FILTER] Detected campus path: /{campus_path}/ - filtering disclosure results")
                
                # Filter pages
                original_page_count = len(disclosure_data.get("pages", []))
                filtered_pages = []
                for page in disclosure_data.get("pages", []):
                    page_url = page.get('url', '')
                    parsed_page = urlparse(page_url)
                    page_path = parsed_page.path.lower()
                    
                    # Check if page belongs to the same campus
                    if f"/{campus_path.lower()}/" in page_path or page_path.startswith(f"/{campus_path.lower()}"):
                        filtered_pages.append(page)
                    else:
                        logger.debug(f"[CAMPUS FILTER] Excluding page from different campus: {page_url}")
                
                disclosure_data["pages"] = filtered_pages
                logger.info(f"[CAMPUS FILTER] Pages: {len(filtered_pages)}/{original_page_count} after campus filtering")
                
                # Filter PDFs
                original_pdf_count = len(disclosure_data.get("pdfs", []))
                filtered_pdfs = []
                for pdf in disclosure_data.get("pdfs", []):
                    pdf_url = pdf.get('url', '')
                    parsed_pdf = urlparse(pdf_url)
                    pdf_path = parsed_pdf.path.lower()
                    
                    # Check if PDF belongs to the same campus
                    if f"/{campus_path.lower()}/" in pdf_path or pdf_path.startswith(f"/{campus_path.lower()}"):
                        filtered_pdfs.append(pdf)
                    else:
                        logger.debug(f"[CAMPUS FILTER] Excluding PDF from different campus: {pdf_url}")
                
                disclosure_data["pdfs"] = filtered_pdfs
                logger.info(f"[CAMPUS FILTER] PDFs: {len(filtered_pdfs)}/{original_pdf_count} after campus filtering")
        
        # Apply location filtering to disclosure pages
        disclosure_pages = disclosure_data.get("pages", [])
        if target_location and disclosure_pages:
            disclosure_urls = [p['url'] for p in disclosure_pages]
            filtered_urls = self._filter_urls_by_location(disclosure_urls, target_location, college_name)
            disclosure_pages = [p for p in disclosure_pages if p['url'] in filtered_urls]
            logger.info(f"[LOCATION FILTER] Disclosure: {len(disclosure_pages)}/{len(disclosure_data.get('pages', []))} pages after filtering")
        
        # Process disclosure pages - these contain standardized KPI data
        disclosure_pages_to_fetch = []
        for page in disclosure_pages[:4]:
            page['source_priority'] = 'high'  # Mandatory disclosure is high priority
            all_data["public_disclosure"].append(page)
            disclosure_pages_to_fetch.append(page['url'])
            combined_text_parts.append(f"[PUBLIC DISCLOSURE PAGE]\nTitle: {page['title']}\nURL: {page['url']}\nSnippet: {page['snippet']}\n")
        
        # Fetch disclosure pages and extract PDFs from them
        if disclosure_pages_to_fetch:
            if progress_callback:
                await progress_callback("Fetching Public Disclosure pages and PDFs...", 48)
            
            def fetch_disclosure_with_pdfs(page_url):
                return self.fetch_disclosure_page_and_pdfs(page_url, max_pdfs=2, campus_path=campus_path_for_filtering)
            
            with ThreadPoolExecutor(max_workers=4) as executor:
                future_to_page = {executor.submit(fetch_disclosure_with_pdfs, url): url for url in disclosure_pages_to_fetch[:3]}
                for future in as_completed(future_to_page):
                    page_url = future_to_page[future]
                    result = future.result()
                    
                    # Add page content
                    if result.get("page_content") and result["page_content"].get("success"):
                        result["page_content"]['source_priority'] = 'high'
                        all_data["public_disclosure_content"].append(result["page_content"])
                        all_data["fetched_urls"].add(page_url)
                        combined_text_parts.append(f"[PUBLIC DISCLOSURE PAGE CONTENT]\nURL: {page_url}\nTitle: {result['page_content'].get('title', '')}\nContent: {result['page_content']['content']}\n")
                        logger.info(f"Fetched disclosure page: {page_url}")
                    
                    # Add PDF contents - these are gold for KPIs
                    for pdf_content in result.get("pdf_contents", []):
                        pdf_content['source_priority'] = 'high'
                        all_data["public_disclosure_content"].append(pdf_content)
                        combined_text_parts.append(f"[PUBLIC DISCLOSURE PDF - HIGH VALUE KPI DATA]\nURL: {pdf_content['url']}\nTitle: {pdf_content.get('title', 'PDF Document')}\nContent: {pdf_content['content']}\n")
                        logger.info(f"Extracted disclosure PDF: {pdf_content['url']} ({len(pdf_content.get('content', ''))} chars)")
        
        # Also directly fetch any PDFs found in search results
        direct_pdfs = disclosure_data.get("pdfs", [])
        if target_location and direct_pdfs:
            pdf_urls = [p['url'] for p in direct_pdfs]
            filtered_pdf_urls = self._filter_urls_by_location(pdf_urls, target_location, college_name)
            direct_pdfs = [p for p in direct_pdfs if p['url'] in filtered_pdf_urls]
            logger.info(f"[LOCATION FILTER] Direct PDFs: {len(direct_pdfs)}/{len(disclosure_data.get('pdfs', []))} PDFs after filtering")
        
        for pdf in direct_pdfs[:3]:
            if pdf['url'] not in all_data["fetched_urls"]:
                pdf_content = self._fetch_pdf_content(pdf['url'], max_length=25000)
                if pdf_content.get("success"):
                    all_data["public_disclosure_content"].append(pdf_content)
                    all_data["fetched_urls"].add(pdf['url'])
                    combined_text_parts.append(f"[PUBLIC DISCLOSURE PDF - DIRECT]\nURL: {pdf['url']}\nTitle: {pdf.get('title', 'PDF')}\nContent: {pdf_content['content']}\n")
                    logger.info(f"Fetched direct disclosure PDF: {pdf['url']}")
        
        if progress_callback:
            disclosure_count = len(all_data.get("public_disclosure_content", []))
            await progress_callback(f"Public Disclosure complete: {disclosure_count} documents fetched", 52)
        
        # ============ PRIORITY 3: NIRF DATA (SKIPPED - USING PATTERN EXTRACTION) ============
        # NIRF documents are now handled separately in Phase 1 using pattern-based extraction
        # NO LLM is used on NIRF data, so we don't collect it here
        logger.info("[GATHER DATA] Skipping NIRF collection - handled separately with pattern extraction")
        
        if progress_callback:
            await progress_callback("NIRF handled separately, continuing...", 55)
        
        # Initialize empty NIRF data structures for compatibility
        nirf_enhanced_docs = []
        if 'nirf_url_to_year' not in all_data:
            all_data['nirf_url_to_year'] = {}
        
        # Skip to next section
        if progress_callback:
            await progress_callback("Scanning for NAAC documents...", 65)
        
        # ============ PRIORITY 4: NAAC DOCUMENTS ============
        # Only search external NAAC if we don't have college website
        if not college_website_url:
            if progress_callback:
                await progress_callback("Searching NAAC Documents...", 65)
            
            naac_query = f'site:naac.gov.in "{clean_name}" OR "{clean_name}" NAAC accreditation'
            result = self.search_official_sources(naac_query, num_results=5)
            if result.get("official_results"):
                for r in result["official_results"]:
                    if 'naac' in r['url'].lower():
                        r['source_priority'] = 'high'  # NAAC is high priority
                        all_data["naac"].append(r)
                        combined_text_parts.append(f"[NAAC]\\nTitle: {r['title']}\\nURL: {r['url']}\\nData: {r['snippet']}\\n")
        else:
            logger.info("Skipping external NAAC search - using college website only")
        
        # ============ PRIORITY 5: WIKIPEDIA (MEDIUM PRIORITY) ============
        # Skip Wikipedia if we have college website - focus on official college data
        if not college_website_url:
            if progress_callback:
                await progress_callback("Fetching Wikipedia data...", 68)
            
            wiki_data = self.fetch_wikipedia_content(clean_name)
            if wiki_data.get("success"):
                wiki_result = {
                    "title": wiki_data.get("title", ""),
                    "url": wiki_data.get("url", ""),
                    "snippet": wiki_data.get("summary", "")[:500],
                    "source_priority": "medium"  # Wikipedia is medium priority
                }
                all_data["wikipedia"].append(wiki_result)
                wiki_data['source_priority'] = 'medium'
                all_data["wikipedia_content"].append(wiki_data)
                combined_text_parts.append(f"[WIKIPEDIA]\nTitle: {wiki_result['title']}\nURL: {wiki_result['url']}\nSummary: {wiki_result['snippet']}\n")
        else:
            logger.info("Skipping Wikipedia - using college website only")
        
        # ============ PRIORITY 6: PER-KPI TARGETED SEARCH (PARALLEL) ============
        # Skip general KPI search when we have college website - we already have focused college data
        if not college_website_url:
            if progress_callback:
                await progress_callback("Searching for specific KPI data (parallel)...", 70)
            
            all_data["kpi_specific_data"] = {}
            
            # Search KPIs in parallel batches
            def search_single_kpi(kpi):
                return (kpi['name'], self.search_for_kpi(clean_name, kpi, abbreviation, college_website_url))
            
            with ThreadPoolExecutor(max_workers=8) as executor:
                future_to_kpi = {executor.submit(search_single_kpi, kpi): kpi for kpi in self.kpis_data}
                for future in as_completed(future_to_kpi):
                    kpi_name, kpi_search_data = future.result()
                    all_data["kpi_specific_data"][kpi_name] = kpi_search_data
                    
                    # Add to combined text
                    if kpi_search_data["search_results"]:
                        combined_text_parts.append(f"\n[KPI-SPECIFIC: {kpi_name}]")
                        for r in kpi_search_data["search_results"][:2]:
                            combined_text_parts.append(f"  Source: {r['url']}\\n  Snippet: {r['snippet']}")
        else:
            logger.info("Skipping per-KPI broad search - using college website only")
            all_data["kpi_specific_data"] = {}
        
        if progress_callback:
            await progress_callback(f"KPI-specific search complete", 85)
        
        all_data["combined_text"] = "\n\n".join(combined_text_parts)
        
        # Convert set to list for JSON serialization
        all_data["fetched_urls"] = list(all_data["fetched_urls"])
        
        # Log summary of data collected
        website_pages = len(all_data["official_website_content"])
        disclosure_docs = len(all_data.get("public_disclosure_content", []))
        total_sources = len(all_data["official_website"]) + len(all_data["nirf"]) + len(all_data["naac"]) + len(all_data["public_disclosure"])
        
        if not nirf_available:
            logger.info(f"[DATA COLLECTION SUMMARY - NO NIRF] Collected from official website:")
            logger.info(f"  - {website_pages} website pages fetched and parsed")
            logger.info(f"  - {disclosure_docs} disclosure documents processed")
            logger.info(f"  - {total_sources} total search results found")
        else:
            logger.info(f"[DATA COLLECTION SUMMARY] {total_sources} sources, {website_pages} pages, {disclosure_docs} disclosures")
        
        if progress_callback:
            kpi_sources = sum(len(v.get("search_results", [])) for v in all_data.get("kpi_specific_data", {}).values())
            await progress_callback(f"Data collection complete. {total_sources} sources, {disclosure_docs} disclosure docs, {website_pages} pages fetched", 98)
        
        return all_data

    def _extract_year_from_url_or_text(self, url: str, text: str = "") -> Optional[int]:
        """Extract year from URL or text content using multiple patterns"""
        import re
        
        # Check URL first (higher priority)
        if url:
            # Look for /2025/, /2024/, etc. in URL
            year_match = re.search(r'/(202[0-7])/', url)
            if year_match:
                return int(year_match.group(1))
            
            # Look for 2025, 2024, etc. anywhere in URL
            year_match = re.search(r'(202[0-7])', url)
            if year_match:
                return int(year_match.group(1))
        
        # Check text content
        if text:
            # Look for "NIRF 2025", "NIRF-2025", etc.
            year_match = re.search(r'NIRF[\s-]*(202[0-7])', text, re.IGNORECASE)
            if year_match:
                return int(year_match.group(1))
            
            # Look for any 2020-2027 year
            year_match = re.search(r'(202[0-7])', text)
            if year_match:
                return int(year_match.group(1))
        
        return None
    
    def _calculate_recency(self, year: Optional[int]) -> str:
        """Calculate recency rating based on year"""
        if not year:
            return 'unknown'
        
        if year == 2025:
            return 'high'
        elif year == 2024:
            return 'medium'
        elif year <= 2023:
            return 'low'
        else:
            return 'unknown'
    
    def _get_college_abbreviation(self, college_name: str) -> str:
        """Get common abbreviation for college name"""
        name_lower = college_name.lower()
        
        if "indian institute of technology" in name_lower:
            parts = college_name.split()
            for i, part in enumerate(parts):
                if part.lower() == "technology" and i + 1 < len(parts):
                    location = parts[i + 1]
                    return f"IIT {location}"
        elif "national institute of technology" in name_lower:
            parts = college_name.split()
            for i, part in enumerate(parts):
                if part.lower() == "technology" and i + 1 < len(parts):
                    location = parts[i + 1]
                    return f"NIT {location}"
        elif "indian institute of information technology" in name_lower:
            parts = college_name.split()
            for i, part in enumerate(parts):
                if part.lower() == "technology" and i + 1 < len(parts):
                    location = parts[i + 1]
                    return f"IIIT {location}"
        elif "indian institute of management" in name_lower:
            parts = college_name.split()
            for i, part in enumerate(parts):
                if part.lower() == "management" and i + 1 < len(parts):
                    location = parts[i + 1]
                    return f"IIM {location}"
        elif "birla institute of technology" in name_lower:
            if "science" in name_lower:
                return "BITS Pilani"
            else:
                return "BIT Mesra"
        elif "vellore institute of technology" in name_lower or "vit" in name_lower:
            return "VIT"
        elif "manipal institute of technology" in name_lower:
            return "MIT Manipal"
        elif "srm institute" in name_lower or "srm university" in name_lower:
            return "SRM"
        elif "amity university" in name_lower:
            return "Amity"
        elif "lovely professional university" in name_lower:
            return "LPU"
        elif "chandigarh university" in name_lower:
            return "CU Chandigarh"
        elif "delhi technological university" in name_lower:
            return "DTU"
        elif "netaji subhas" in name_lower and "technology" in name_lower:
            return "NSUT"
        elif "pec" in name_lower or "punjab engineering college" in name_lower:
            return "PEC Chandigarh"
        elif "thapar" in name_lower:
            return "Thapar University"
        elif "anna university" in name_lower:
            return "Anna University"
        elif "jadavpur university" in name_lower:
            return "Jadavpur University"
        
        return ""

    async def extract_kpi_with_strict_sources(self, college_name: str, kpis_batch: List[Dict], 
                                               search_data: Dict[str, Any], client) -> List[Dict]:
        """Extract KPI values using Gemini with STRICT official source validation and per-KPI data"""
        
        # Log extraction start
        kpi_names = [kpi['name'] for kpi in kpis_batch]
        logger.info(f"[KPI EXTRACTION] Calling Gemini API for {len(kpis_batch)} KPIs: {kpi_names[:3]}...")
        
        # Build structured data from official sources - prioritize FULL content
        source_sections = []
        
        # Add pre-extracted structured data if available
        if search_data.get("structured_extracted"):
            source_sections.append("=== PRE-EXTRACTED STRUCTURED DATA (VERIFIED NUMERIC VALUES) ===")
            for key, value in search_data["structured_extracted"].items():
                source_sections.append(f"{key}: {value}")
            source_sections.append("")
        
        # PRIORITY 0 (HIGHEST): PUBLIC DISCLOSURE PAGES AND PDFs (AICTE Mandatory Data)
        if search_data.get("public_disclosure_content"):
            source_sections.append("=== MANDATORY PUBLIC DISCLOSURE (HIGHEST PRIORITY - AICTE/UGC VERIFIED DATA) ===")
            source_sections.append("NOTE: This data is from mandatory disclosure documents required by AICTE/UGC. It contains verified KPIs.")
            for item in search_data["public_disclosure_content"][:6]:
                source_sections.append(f"Document URL: {item.get('url', '')}")
                source_sections.append(f"Document Title: {item.get('title', '')}")
                source_sections.append(f"Content:\n{item.get('content', '')[:12000]}")
                source_sections.append("")
        
        # PRIORITY 1: Fetched Official Website Content
        if search_data.get("official_website_content"):
            source_sections.append("=== OFFICIAL COLLEGE WEBSITE - FETCHED PAGES (HIGH PRIORITY) ===")
            for item in search_data["official_website_content"][:5]:
                source_sections.append(f"Page URL: {item['url']}")
                source_sections.append(f"Page Title: {item.get('title', '')}")
                source_sections.append(f"Page Content:\n{item['content'][:8000]}")
                source_sections.append("")
        
        # PRIORITY 3: KPI-SPECIFIC SEARCH DATA (NEW - Very Important!)
        kpi_specific_data = search_data.get("kpi_specific_data", {})
        for kpi in kpis_batch:
            kpi_name = kpi['name']
            if kpi_name in kpi_specific_data:
                kpi_data = kpi_specific_data[kpi_name]
                if kpi_data.get("search_results") or kpi_data.get("fetched_content"):
                    source_sections.append(f"=== KPI-SPECIFIC DATA FOR: {kpi_name} ===")
                    
                    # Add fetched content first (higher priority)
                    for content in kpi_data.get("fetched_content", [])[:2]:
                        source_sections.append(f"[Fetched Page] URL: {content['url']}")
                        source_sections.append(f"Content: {content['content'][:5000]}")
                        source_sections.append("")
                    
                    # Add search snippets
                    for result in kpi_data.get("search_results", [])[:4]:
                        source_sections.append(f"[Search Result] URL: {result['url']}")
                        source_sections.append(f"Snippet: {result['snippet']}")
                        source_sections.append("")
        
        # PRIORITY 4: Official Website Search Results
        if search_data.get("official_website"):
            source_sections.append("=== OFFICIAL COLLEGE WEBSITE - SEARCH SNIPPETS ===")
            for item in search_data["official_website"][:10]:
                source_sections.append(f"Title: {item['title']}")
                source_sections.append(f"URL: {item['url']}")
                source_sections.append(f"Snippet: {item['snippet']}")
                source_sections.append("")
        
        # PRIORITY 5: NIRF Data
        if search_data.get("nirf"):
            source_sections.append("=== NIRF DOCUMENTS (OFFICIAL RANKING DATA) ===")
            for item in search_data["nirf"][:8]:
                source_sections.append(f"Title: {item['title']}")
                source_sections.append(f"URL: {item['url']}")
                source_sections.append(f"Data: {item['snippet']}")
                source_sections.append("")
        
        if search_data.get("naac"):
            source_sections.append("=== NAAC DOCUMENTS (ACCREDITATION DATA) ===")
            for item in search_data["naac"][:5]:
                source_sections.append(f"Title: {item['title']}")
                source_sections.append(f"URL: {item['url']}")
                source_sections.append(f"Content: {item['snippet']}")
                source_sections.append("")
        
        search_content = "\n".join(source_sections)
        
        # Limit content size for API - smart truncation
        if len(search_content) > 120000:
            search_content = search_content[:120000] + "\n[Content truncated for processing]"
        
        # Build KPI extraction instructions with search keywords hint
        kpi_details = []
        for i, kpi in enumerate(kpis_batch, 1):
            detail = f"{i}. KPI: {kpi['name']}"
            detail += f"\n   Category: {kpi['category']}"
            detail += f"\n   Data Type: {kpi['data_type']} ({kpi['unit']})"
            detail += f"\n   Extraction Rule: {kpi['extraction_instruction']}"
            if kpi.get('search_keywords'):
                detail += f"\n   Look for keywords: {', '.join(kpi['search_keywords'][:5])}"
            kpi_details.append(detail)
        
        kpi_list_str = "\n".join(kpi_details)
        
        prompt = f"""You are an elite data extraction AI specializing in Indian educational institution KPIs. Your extraction accuracy directly impacts institutional rankings and decisions.

INSTITUTION: "{college_name}"

=== DUAL CONFIDENCE ASSESSMENT ===
For each KPI, you must assess YOUR CONFIDENCE in the extraction based on:
1. Data clarity and explicitness in source
2. Consistency across multiple mentions
3. Recency and relevance of information
4. Whether data is from verified tables/structured content
5. Need for inference or assumptions

YOUR CONFIDENCE LEVELS:
- "high": Direct quote, explicit value, from official source, clear and unambiguous, recent
- "medium": Data found but requires interpretation, from secondary source, or older data
- "low": Data inferred, unclear, requires significant assumptions, or very limited evidence

NOTE: The system will ALSO calculate a separate confidence score based on source priority:
- HIGH PRIORITY: Official college websites (.ac.in, .edu.in), Government portals (NIRF, NAAC, AICTE)
- MEDIUM PRIORITY: Wikipedia, educational databases
- LOW PRIORITY: Aggregator sites (Shiksha, CollegeDuniya, etc.)

=== EXTRACTION PHILOSOPHY ===
AGGRESSIVE EXTRACTION: Find data even from indirect mentions. "Data Not Found" is only acceptable if NO related information exists anywhere.

=== ACCURACY REQUIREMENTS ===
1. EXHAUSTIVE SEARCH: Read EVERY section of source data - data often appears in unexpected places
2. EXACT EXTRACTION: Copy numbers, percentages, and values exactly as they appear
3. SMART INFERENCE: Calculate derived values (e.g., percentage from ratio, total from sum of parts)
4. BOOLEAN LOGIC:
   - TRUE: Any mention of facility/feature existing (even partial)
   - FALSE: Explicit statement of non-existence
   - null: ONLY if topic never mentioned
5. CONTEXT CLUES: Use related data to infer missing values

=== SOURCE DATA (PRIORITIZED BY RELIABILITY) ===
{search_content}
=== END OF SOURCE DATA ===

=== KPIs TO EXTRACT ({len(kpis_batch)} items) ===
{kpi_list_str}
=== END KPIs ===

OUTPUT FORMAT - Return ONLY valid JSON array (no markdown, no explanation):
[
  {{
    "kpi_name": "exact KPI name from list",
    "category": "category from list",
    "value": "extracted/derived value OR 'Data Not Found' only if truly absent",
    "evidence_quote": "exact quote or calculation explanation (max 200 chars)",
    "source_url": "URL where found OR 'N/A'",
    "source_type": "Official Website/NIRF/NAAC/Wikipedia/Aggregator/etc",
    "llm_confidence": "high/medium/low - YOUR assessment of this extraction's reliability",
    "llm_confidence_reason": "brief reason for your confidence level (1 sentence, max 100 chars)"
  }}
]

MANDATORY: Extract ALL {len(kpis_batch)} KPIs. Provide both value AND your confidence assessment. Return ONLY the JSON array now:"""

        # Define response schema for accurate KPI extraction with dual confidence
        kpi_response_schema = {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "kpi_name": {"type": "string"},
                    "category": {"type": "string"},
                    "value": {},  # Can be string, number, boolean, array, or object
                    "evidence_quote": {"type": "string"},
                    "source_url": {"type": "string"},
                    "source_type": {"type": "string"},
                    "llm_confidence": {"type": "string", "enum": ["high", "medium", "low"]},
                    "llm_confidence_reason": {"type": "string"}
                },
                "required": ["kpi_name", "category", "value", "evidence_quote", "source_url", "source_type", "llm_confidence"]
            }
        }

        try:
            # Log prompt size for debugging
            logger.info(f"[KPI EXTRACTION] Sending prompt to Gemini (size: {len(prompt)} chars, {len(search_content)} chars of source data)")
            
            # Use modern google-genai client API with Gemini 3 Flash
            response = client.models.generate_content(
                model="gemini-3-flash-preview",
                contents=prompt,
                config=types.GenerateContentConfig(
                    temperature=0.4,  # 0.0 is optimal for extraction accuracy
                    response_mime_type="application/json",
                    response_schema=kpi_response_schema,  # Schema for accuracy
                    thinking_config=types.ThinkingConfig(thinking_budget=1024)  # Low thinking for speed
                )
            )
            
            logger.info(f"[KPI EXTRACTION] Received response from Gemini API")
            
            text = response.text.strip()
            
            # Clean markdown if present
            if "```json" in text:
                text = text.split("```json")[1].split("```")[0]
            elif "```" in text:
                text = text.split("```")[1].split("```")[0]
            
            results = json.loads(text.strip())
            
            # Add system confidence based on source priority and validate results
            validated_results = []
            nirf_url_to_year = search_data.get('nirf_url_to_year', {})
            
            for r in results:
                source_url = r.get('source_url', 'N/A')
                
                # CRITICAL: If no source URL, mark as Data Not Found
                if not source_url or source_url in ['N/A', 'Not Available', '']:
                    logger.debug(f"No source for {r.get('kpi_name', 'Unknown KPI')} - marking as Data Not Found")
                    r['value'] = 'Data Not Found'
                    r['evidence_quote'] = 'No verifiable source available'
                    r['source_url'] = 'N/A'
                    r['source_type'] = 'N/A'
                    r['system_confidence'] = 'low'
                    r['llm_confidence'] = 'low'
                    r['llm_confidence_reason'] = 'No source available'
                    r['source_priority'] = 'unknown'
                    r['confidence'] = 'low'
                    r['data_year'] = None
                    r['recency'] = 'unknown'
                    validated_results.append(r)
                    continue
                
                # Calculate SYSTEM CONFIDENCE from source priority
                source_priority = SourcePriorityClassifier.get_source_priority(source_url)
                system_confidence = SourcePriorityClassifier.get_confidence_from_priority(source_priority)
                r['source_priority'] = source_priority
                
                # Extract data year - try multiple methods
                data_year = None
                
                # Method 1: Exact match in NIRF mapping
                data_year = nirf_url_to_year.get(source_url)
                
                # Method 2: Fuzzy match in NIRF mapping (check if any NIRF URL is contained in source_url)
                if not data_year:
                    for nirf_url, year in nirf_url_to_year.items():
                        # Remove trailing slashes and compare
                        if nirf_url.rstrip('/') in source_url or source_url.rstrip('/') in nirf_url:
                            data_year = year
                            break
                
                # Method 3: Extract from URL pattern or evidence text
                if not data_year:
                    evidence = r.get('evidence_quote', '')
                    data_year = self._extract_year_from_url_or_text(source_url, evidence)
                
                # Set year and calculate recency
                if data_year:
                    r['data_year'] = data_year
                    r['recency'] = self._calculate_recency(data_year)
                else:
                    r['data_year'] = None
                    r['recency'] = 'unknown'
                
                # Add system confidence
                r['system_confidence'] = system_confidence
                
                # Ensure llm_confidence exists (fallback to medium if missing)
                if 'llm_confidence' not in r:
                    r['llm_confidence'] = 'medium'
                    r['llm_confidence_reason'] = 'Not explicitly provided by LLM'
                
                # Legacy 'confidence' field = system confidence (for backward compatibility)
                r['confidence'] = system_confidence
                
                # Note: We rely on SourcePriorityClassifier for source validation
                # No need for additional validation here as it can cause false downgrades
                
                validated_results.append(r)
            
            # Fill missing KPIs
            found_kpis = {str(r.get('kpi_name', '')).lower().strip() for r in validated_results}
            for kpi in kpis_batch:
                if kpi['name'].lower().strip() not in found_kpis:
                    validated_results.append({
                        "kpi_name": kpi['name'],
                        "category": kpi['category'],
                        "value": "Data Not Found",
                        "evidence_quote": "Not found in available sources",
                        "source_url": "N/A",
                        "source_type": "N/A",
                        "llm_confidence": "low",
                        "llm_confidence_reason": "No data available",
                        "system_confidence": "low",
                        "source_priority": "unknown",
                        "confidence": "low"
                    })
            
            # Log completion
            found_count = sum(1 for r in validated_results if r.get('value') != 'Data Not Found')
            logger.info(f"[KPI EXTRACTION] Completed: {found_count}/{len(validated_results)} KPIs found")
            
            return validated_results
            
        except json.JSONDecodeError as e:
            logger.error(f"JSON parse error: {e}")
            try:
                json_match = re.search(r'\[[\s\S]*\]', text)
                if json_match:
                    return json.loads(json_match.group())
            except:
                pass
            
            return [
                {
                    "kpi_name": kpi['name'],
                    "category": kpi['category'],
                    "value": "Data Not Found",
                    "evidence_quote": "Processing error",
                    "source_url": "N/A",
                    "source_type": "N/A",
                    "llm_confidence": "low",
                    "llm_confidence_reason": "Extraction failed",
                    "system_confidence": "low",
                    "source_priority": "unknown",
                    "confidence": "low"
                }
                for kpi in kpis_batch
            ]
        except Exception as e:
            logger.error(f"Extraction error: {e}")
            return [
                {
                    "kpi_name": kpi['name'],
                    "category": kpi['category'],
                    "value": "Data Not Found",
                    "evidence_quote": str(e),
                    "source_url": "N/A",
                    "source_type": "N/A",
                    "llm_confidence": "low",
                    "llm_confidence_reason": "Error occurred",
                    "system_confidence": "low",
                    "source_priority": "unknown",
                    "confidence": "low"
                }
                for kpi in kpis_batch
            ]

    def _extract_structured_data(self, search_data: Dict[str, Any]) -> Dict[str, Any]:
        """Extract structured numeric data from all content sources"""
        extracted = {}
        
        # Process all content sources
        all_content = []
        
        # Add official website content
        for item in search_data.get("official_website_content", []):
            if item.get("content"):
                all_content.append(item["content"])
        
        # Add public disclosure content
        for item in search_data.get("public_disclosure_content", []):
            if item.get("content"):
                all_content.append(item["content"])
        
        # Add snippets from search results
        for item in search_data.get("nirf", []):
            if item.get("snippet"):
                all_content.append(item["snippet"])
        
        # Extract structured data from all content
        combined_text = " ".join(all_content)
        extracted = StructuredDataParser.extract_all_numbers(combined_text)
        
        logger.info(f"Structured data extracted: {list(extracted.keys())}")
        return extracted
    
    def _validate_and_boost_results(self, results: List[Dict], search_data: Dict[str, Any], college_website_url: str = None) -> List[Dict]:
        """Validate results and boost confidence based on multiple source verification"""
        validated_results = []
        structured_data = search_data.get("structured_extracted", {})
        
        # Extract college domain for official source validation
        college_domain = None
        if college_website_url:
            try:
                from urllib.parse import urlparse
                college_domain = urlparse(college_website_url).netloc
            except Exception:
                pass
        
        # Map KPI names to structured data types
        kpi_to_structured = {
            "Median Compensation (Last Batch)": "median_salary",
            "Maximum Compensation (Last Placement Season)": "highest_salary",
            "Total Faculty": "total_faculty",
            "PhD Faculty": "phd_faculty",
            "Total Students Enrolled": "total_students",
            "NIRF Ranking": "nirf_rank",
            "PhD Students Enrolled": "phd_students",
        }
        
        for result in results:
            kpi_name = result.get("kpi_name", "")
            current_value = result.get("value", "")
            current_confidence = result.get("confidence", "low")
            source_url = result.get("source_url", "")
            
            # Validate source URL - skip if invalid
            if source_url and not self.validator.is_valid_url(source_url):
                logger.warning(f"Skipping result for {kpi_name}: Invalid source URL {source_url}")
                # Set to not found instead of keeping invalid data
                result["value"] = "Data Not Found"
                result["confidence"] = "low"
                result["evidence_quote"] = "Invalid source URL"
                result["source_url"] = ""
                validated_results.append(result)
                continue
            
            # Try to cross-verify with structured data
            if kpi_name in kpi_to_structured:
                structured_key = kpi_to_structured[kpi_name]
                if structured_key in structured_data:
                    structured_value = structured_data[structured_key]
                    
                    # If LLM didn't find data but structured parser did
                    if current_value in ["Data Not Found", "N/A", "", None]:
                        result["value"] = structured_value
                        result["confidence"] = "medium"
                        result["evidence_quote"] = f"Extracted via pattern matching: {structured_value}"
                        result["source_type"] = "Structured Extraction"
                    
                    # If both found similar values, boost confidence
                    elif current_value and str(current_value) != "Data Not Found":
                        try:
                            llm_val = float(str(current_value).replace(',', '').replace('₹', '').replace('Rs', ''))
                            # If values are within 20% of each other, boost confidence
                            max_val = max(llm_val, structured_value)
                            if max_val > 0 and abs(llm_val - structured_value) / max_val < 0.2:
                                result["confidence"] = "high"
                                result["evidence_quote"] += f" [Cross-verified: {structured_value}]"
                            elif max_val == 0 and llm_val == structured_value:
                                # Both are zero, they match exactly
                                result["confidence"] = "high"
                                result["evidence_quote"] += f" [Cross-verified: {structured_value}]"
                        except (ValueError, TypeError, ZeroDivisionError):
                            pass
            
            # Validate URL is from official source
            source_url = result.get("source_url", "")
            if source_url and source_url != "N/A":
                if not self.validator.is_official_source(source_url, college_domain):
                    logger.debug(f"Marking non-official source for {kpi_name}: {source_url}")
                    result["source_url"] = "N/A"
                    if result["confidence"] == "high":
                        result["confidence"] = "medium"
            
            # Ensure confidence is valid
            if result.get("confidence") not in ["high", "medium", "low"]:
                result["confidence"] = "low"
            
            # Filter out vague or empty evidence
            evidence = result.get("evidence_quote", "").strip()
            if evidence and len(evidence) < 10:
                result["evidence_quote"] = ""
            
            # Check for common vague phrases in evidence
            vague_phrases = ["not mentioned", "not specified", "not available", "unclear", "no information", "call for details"]
            if evidence and any(phrase in evidence.lower() for phrase in vague_phrases):
                if result.get("value") not in ["Data Not Found", "N/A", ""]:
                    logger.debug(f"Keeping result with vague evidence for {kpi_name} as it has a value")
                else:
                    result["value"] = "Data Not Found"
                    result["evidence_quote"] = ""
            
            validated_results.append(result)
        
        return validated_results

    def _check_website_availability(self, url: str) -> bool:
        """
        Check if the website is accessible using the quickest robust method.
        Returns True if status code is 200-299, False otherwise.
        """
        if not url:
            return False
            
        # Robust timeout for slow government websites
        # 20 seconds is a good balance between speed and reliability for slow sites like NITs
        timeout = 20
        
        try:
            headers = {
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36',
                'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
                'Accept-Language': 'en-US,en;q=0.5',
                'Connection': 'keep-alive',
                'Upgrade-Insecure-Requests': '1'
            }
            
            logger.debug(f"Checking availability (GET stream=True) for: {url}")
            
            # Single robust check: GET with stream=True
            # - stream=True: Only downloads headers, fast like HEAD
            # - GET: More compatible than HEAD (some servers block HEAD)
            # - verify=False: Ignores SSL errors common in college sites
            response = requests.get(url, headers=headers, timeout=timeout, stream=True, verify=False)
            
            # Close connection immediately
            response.close()
            
            if 200 <= response.status_code < 400:
                return True
            
            logger.warning(f"Website check failed with status code: {response.status_code} for {url}")
            return False
            
        except Exception as e:
            logger.warning(f"Website availability check failed for {url}: {e}")
            return False

    async def run_audit(self, college_name: str, progress_callback=None) -> List[Dict]:
        """Run the complete audit process with NIRF-first strategy"""
        
        if not self.gemini_api_key:
            return [{"kpi_name": "Error", "category": "Config", "value": "GEMINI_API_KEY not set", 
                    "evidence_quote": "", "source_url": "", "confidence": "low"}]
        
        if not self.serper_api_rotator or not self.serper_api_rotator.api_keys:
            return [{"kpi_name": "Error", "category": "Config", "value": "SERPER_API_KEY not set", 
                    "evidence_quote": "", "source_url": "", "confidence": "low"}]
        
        # Normalize college name using fuzzy matcher
        original_college_name = college_name
        college_name = FuzzyMatcher.normalize_text(college_name)
        
        if college_name != original_college_name:
            logger.info(f"[NORMALIZATION] Normalized college name: '{original_college_name}' -> '{college_name}'")
        
        # Initialize modern google-genai client
        client = genai.Client(api_key=self.gemini_api_key)
        
        # ======== PHASE 0: GET COLLEGE WEBSITE FROM GEMINI ========
        if progress_callback:
            await progress_callback("Identifying official college website...", 2)
        
        logger.info(f"[PHASE 0] Asking Gemini for official website of {college_name}")
        college_website_url = await self.get_college_website_from_gemini(college_name, client)
        
        # Verify Gemini URL immediately - if invalid, discard it so we fall back to search
        if college_website_url:
            if not self._check_website_availability(college_website_url):
                logger.warning(f"[PHASE 0] Gemini returned {college_website_url} but it is unreachable. Falling back to search.")
                college_website_url = None
        
        if not college_website_url:
            # Fallback: Try search with better filtering
            logger.warning(f"[PHASE 0] Gemini couldn't identify valid website, falling back to search")
            try:
                search_query = f'"{college_name}" site:.ac.in OR site:.edu.in'
                result = self.search_official_sources(search_query, num_results=10)  # No restriction - we're finding the website
                if result.get("official_results"):
                    # Filter out irrelevant domains and find best match
                    excluded_domains = ['nptel.ac.in', 'swayam.gov.in', 'aicte-india.org', 'ugc.ac.in', 
                                       'naac.gov.in', 'nirfindia.org', 'mhrd.gov.in', 'education.gov.in',
                                       'collegedunia.com', 'shiksha.com', 'careers360.com', 'getmyuni.com',
                                       'collegedekho.com', 'studyabroad.shiksha.com', 'careerpoint.ac.in',
                                       'betterstudy.in', 'universitykart.com', 'admissionhelpline24.com']
                    
                    college_name_lower = college_name.lower()
                    # Extract key words from college name for matching
                    key_words = [w.lower() for w in college_name.split() if len(w) > 3 and w.lower() not in ['college', 'university', 'institute', 'technology', 'engineering']]
                    
                    found_urls = []
                    
                    for r in result.get("official_results"):
                        url = r.get('url', '')
                        domain = urlparse(url).netloc.lower()
                        
                        # Skip excluded domains (including subdomains)
                        if any(excluded in domain for excluded in excluded_domains):
                            logger.debug(f"[PHASE 0] Skipping excluded domain: {domain}")
                            continue
                        
                        # Check if domain or URL contains college name keywords
                        if ('.ac.in' in url or '.edu.in' in url):
                            # Prefer domains that contain keywords from college name
                            domain_match = any(keyword in domain for keyword in key_words)
                            url_match = any(keyword in url.lower() for keyword in key_words)
                            
                            if domain_match or url_match:
                                potential_url = '/'.join(url.split('/')[:3])
                                found_urls.append(potential_url)
                                logger.info(f"[PHASE 0] Found potential match: {potential_url}")

                    # Test found URLs availability
                    for url in found_urls:
                        if self._check_website_availability(url):
                            college_website_url = url
                            logger.info(f"[PHASE 0] Confirmed valid website: {college_website_url}")
                            break
                    
                    # If still no website, try fallback to any .ac.in/.edu.in results
                    if not college_website_url:
                        for r in result.get("official_results"):
                            url = r.get('url', '')
                            domain = urlparse(url).netloc.lower()
                            if ('.ac.in' in url or '.edu.in' in url) and not any(excluded in domain for excluded in excluded_domains):
                                potential_url = '/'.join(url.split('/')[:3])
                                if self._check_website_availability(potential_url):
                                    college_website_url = potential_url
                                    logger.info(f"[PHASE 0] Using verified fallback website: {college_website_url}")
                                    break

            except Exception as e:
                logger.warning(f"Could not find college website: {e}")
        
        if college_website_url:
            logger.info(f"[PHASE 0] Final verified college website: {college_website_url}")
        else:
            logger.error(f"[PHASE 0] Could not determine reachable college website URL")
            
            # Return error result only if ALL attempts failed
            return [{"kpi_name": "Error", "category": "Website Status", 
                    "value": "Website Not Found or Inaccessible", 
                    "evidence_quote": f"Could not identify a reachable official website for {college_name}. Please check the college name or try manual entry.", 
                    "source_url": "N/A", 
                    "confidence": "high"}]
        
        # Check for cancellation
        if progress_callback:
            try:
                await progress_callback("Starting NIRF document search...", 3)
            except Exception as e:
                if "cancelled" in str(e).lower():
                    logger.info(f"Audit cancelled during Phase 0")
                    return []
                raise
        
        # ======== PHASE 1: NIRF OVERALL DOCUMENT FIRST ========
        if progress_callback:
            await progress_callback("Finding NIRF Overall document...", 5)
        
        logger.info(f"[PHASE 1] Searching for NIRF Overall document for {college_name}")
        
        # Extract location for filtering
        target_location = self._extract_location_from_name(college_name)
        
        nirf_results = {}
        nirf_overall_doc = None
        
        # Search for NIRF data using enhanced collector
        if NIRFCollector and collect_nirf_for_college and college_website_url:
            try:
                if progress_callback:
                    await progress_callback("Scanning for NIRF 2025 Overall document...", 10)
                
                nirf_results = await collect_nirf_for_college(college_name, college_website_url)
                
                # Apply location filtering to NIRF documents if location detected
                all_nirf_docs = nirf_results.get('all', [])
                if target_location and all_nirf_docs:
                    doc_urls = [doc.url for doc in all_nirf_docs]
                    filtered_urls = self._filter_urls_by_location(doc_urls, target_location, college_name)
                    all_nirf_docs = [doc for doc in all_nirf_docs if doc.url in filtered_urls]
                    logger.info(f"[LOCATION FILTER] NIRF: {len(all_nirf_docs)}/{len(nirf_results.get('all', []))} documents after filtering")
                    nirf_results['all'] = all_nirf_docs
                
                # Find NIRF Overall document (highest priority)
                for doc in all_nirf_docs:
                    if doc.category == 'overall' and doc.doc_type == 'pdf' and doc.year == 2025:
                        nirf_overall_doc = doc
                        logger.info(f"[PHASE 1] Found NIRF 2025 Overall: {doc.url}")
                        break
                
                # Fallback: Try 2024 or latest overall
                if not nirf_overall_doc:
                    for doc in all_nirf_docs:
                        if doc.category == 'overall' and doc.doc_type == 'pdf':
                            nirf_overall_doc = doc
                            logger.info(f"[PHASE 1] Found NIRF {doc.year} Overall: {doc.url}")
                            break
                            
            except Exception as e:
                logger.error(f"[PHASE 1] NIRF collection failed: {e}", exc_info=True)
        
        # ======== PHASE 2: EXTRACT KPIs FROM NIRF OVERALL ========
        nirf_extracted_kpis = []
        missing_kpis = []
        nirf_search_data = {}  # Initialize here so it's always available
        
        if nirf_overall_doc:
            if progress_callback:
                await progress_callback(f"Extracting KPIs from NIRF {nirf_overall_doc.year} Overall document...", 20)
            
            logger.info(f"[PHASE 2] Extracting KPIs from NIRF Overall document")
            
            # Fetch NIRF Overall PDF content
            nirf_content = self._fetch_pdf_content(nirf_overall_doc.url, max_length=50000)
            
            if nirf_content.get('success') and nirf_content.get('content'):
                # Initialize nirf_search_data for all code paths
                nirf_search_data = {
                    "nirf": [{
                        'title': nirf_overall_doc.title,
                        'url': nirf_overall_doc.url,
                        'snippet': f"NIRF {nirf_overall_doc.year} Overall document",
                        'content': nirf_content.get('content', ''),
                        'source_priority': 'high',
                        'year': nirf_overall_doc.year
                    }],
                    "official_website": [],
                    "naac": [],
                    "public_disclosure": [],
                    "official_website_content": [],
                    "public_disclosure_content": [],
                    "kpi_specific_data": {},
                    "nirf_url_to_year": {nirf_overall_doc.url: nirf_overall_doc.year},
                    "structured_extracted": {}
                }
                
                # ===== PATTERN-BASED EXTRACTION ONLY (NO LLM) =====
                if AdvancedNIRFExtractor:
                    try:
                        logger.info("[PHASE 2] Using pattern-based extraction (NO LLM)...")
                        if progress_callback:
                            await progress_callback(f"Pattern-matching KPIs from NIRF Overall...", 30)
                        
                        extractor = AdvancedNIRFExtractor(nirf_content.get('content', ''))
                        nirf_data = extractor.extract_all_kpis()
                        extracted_dict = extractor.to_dict()
                        
                        logger.info(f"[PHASE 2] Extracted dict from NIRF: {extracted_dict}")
                        
                        # Map extracted data to KPI results using correct field_name keys
                        kpi_mapping = {
                            'total_graduate_students_2025': extracted_dict.get('total_graduates', 0),
                            'placed_students_count': extracted_dict.get('total_placed', 0),
                            'max_compensation_last_season': extracted_dict.get('max_compensation', 0),
                            'median_compensation_last_batch': extracted_dict.get('median_compensation', 0),
                            'students_higher_education': extracted_dict.get('total_higher_education', 0),
                            'ip_patents_last_year': extracted_dict.get('patents_granted', 0) or extracted_dict.get('patents_published', 0),
                            'female_students_enrolled': extracted_dict.get('female_students', 0),
                            'total_students_enrolled': extracted_dict.get('total_students', 0),
                            'total_faculty': extracted_dict.get('total_faculty', 0),
                            'phd_faculty': extracted_dict.get('phd_faculty', 0),
                            'avg_teaching_experience': extracted_dict.get('avg_experience_years', 0),
                            'phd_students_enrolled': extracted_dict.get('total_phd_students', 0),
                            'program_wise_median_salary_3yr': extracted_dict.get('program_wise_salary_3yr', {}),
                        }
                        
                        # Create KPI results from pattern extraction
                        nirf_extractable_kpi_names = set(NIRF_EXTRACTABLE_KPIS.keys())
                        nirf_kpis = [kpi for kpi in self.kpis_data if kpi['name'] in nirf_extractable_kpi_names]
                        
                        for kpi in nirf_kpis:
                            kpi_field_name = kpi['field_name']
                            value = kpi_mapping.get(kpi_field_name, 0)
                            
                            formatted_value = None
                            
                            # Only create result if value is meaningful
                            # Special handling for dict/object types (program_wise_median_salary_3yr)
                            if kpi_field_name == 'program_wise_median_salary_3yr':
                                if value and isinstance(value, dict) and len(value) > 0:
                                    # Convert salary values from INR to LPA format for readability
                                    formatted_dict = {}
                                    for program, years_data in value.items():
                                        formatted_dict[program] = {}
                                        for year, salary in years_data.items():
                                            # Convert to LPA
                                            if salary >= 10000000:  # 1 Cr or more
                                                formatted_dict[program][year] = f"{salary / 10000000:.2f} Cr"
                                            else:
                                                formatted_dict[program][year] = f"{salary / 100000:.2f} LPA"
                                    
                                    import json
                                    formatted_value = json.dumps(formatted_dict, indent=2)
                            elif value and value > 0:
                                # Format the value according to KPI type
                                if kpi_field_name in ['max_compensation_last_season', 'median_compensation_last_batch']:
                                    # Convert to LPA format
                                    if value >= 10000000:  # 1 Crore or more
                                        formatted_value = f"{value / 10000000:.2f} Cr"
                                    else:
                                        formatted_value = f"{value / 100000:.2f} LPA"
                                elif kpi_field_name == 'total_graduate_students_2025':
                                    # Show breakdown for graduates
                                    breakdown_parts = []
                                    if extracted_dict.get('ug_3yr_graduates', 0) > 0:
                                        breakdown_parts.append(f"UG 3Y: {extracted_dict['ug_3yr_graduates']}")
                                    if extracted_dict.get('ug_4yr_graduates', 0) > 0:
                                        breakdown_parts.append(f"UG 4Y: {extracted_dict['ug_4yr_graduates']}")
                                    if extracted_dict.get('ug_5yr_graduates', 0) > 0:
                                        breakdown_parts.append(f"UG 5Y: {extracted_dict['ug_5yr_graduates']}")
                                    if extracted_dict.get('ug_6yr_graduates', 0) > 0:
                                        breakdown_parts.append(f"UG 6Y: {extracted_dict['ug_6yr_graduates']}")
                                    if extracted_dict.get('pg_2yr_graduates', 0) > 0:
                                        breakdown_parts.append(f"PG 2Y: {extracted_dict['pg_2yr_graduates']}")
                                    if extracted_dict.get('pg_3yr_graduates', 0) > 0:
                                        breakdown_parts.append(f"PG 3Y: {extracted_dict['pg_3yr_graduates']}")
                                    if extracted_dict.get('pg_integrated_graduates', 0) > 0:
                                        breakdown_parts.append(f"PG Integrated: {extracted_dict['pg_integrated_graduates']}")
                                    if extracted_dict.get('pg_6yr_graduates', 0) > 0:
                                        breakdown_parts.append(f"PG 6Y: {extracted_dict['pg_6yr_graduates']}")
                                    
                                    if breakdown_parts:
                                        formatted_value = f"{int(value)} [{', '.join(breakdown_parts)}]"
                                    else:
                                        formatted_value = str(int(value))
                                elif kpi_field_name == 'placed_students_count':
                                    # Show UG/PG breakdown for placements
                                    breakdown_parts = []
                                    if extracted_dict.get('ug_placed', 0) > 0:
                                        breakdown_parts.append(f"UG: {extracted_dict['ug_placed']}")
                                    if extracted_dict.get('pg_placed', 0) > 0:
                                        breakdown_parts.append(f"PG: {extracted_dict['pg_placed']}")
                                    
                                    if breakdown_parts:
                                        formatted_value = f"{int(value)} [{', '.join(breakdown_parts)}]"
                                    else:
                                        formatted_value = str(int(value))
                                elif kpi_field_name == 'students_higher_education':
                                    # Show UG/PG breakdown for higher education
                                    breakdown_parts = []
                                    if extracted_dict.get('ug_higher_ed', 0) > 0:
                                        breakdown_parts.append(f"UG: {extracted_dict['ug_higher_ed']}")
                                    if extracted_dict.get('pg_higher_ed', 0) > 0:
                                        breakdown_parts.append(f"PG: {extracted_dict['pg_higher_ed']}")
                                    
                                    if breakdown_parts:
                                        formatted_value = f"{int(value)} [{', '.join(breakdown_parts)}]"
                                    else:
                                        formatted_value = str(int(value))
                                elif kpi_field_name == 'phd_students_enrolled':
                                    # Show FT/PT breakdown for PhD students
                                    breakdown_parts = []
                                    if extracted_dict.get('phd_full_time', 0) > 0:
                                        breakdown_parts.append(f"Full Time: {extracted_dict['phd_full_time']}")
                                    if extracted_dict.get('phd_part_time', 0) > 0:
                                        breakdown_parts.append(f"Part Time: {extracted_dict['phd_part_time']}")
                                    
                                    if breakdown_parts:
                                        formatted_value = f"{int(value)} [{', '.join(breakdown_parts)}]"
                                    else:
                                        formatted_value = str(int(value))
                                else:
                                    formatted_value = str(int(value)) if isinstance(value, (int, float)) and value == int(value) else str(value)
                            
                            # Only append if we successfully formatted a value
                            if formatted_value is not None:
                                nirf_extracted_kpis.append({
                                    'kpi_name': kpi['name'],  # Display name
                                    'field_name': kpi_field_name,  # Field name for reference
                                    'category': kpi['category'],
                                    'value': formatted_value,
                                    'confidence': 'high',
                                    'source_type': 'NIRF',
                                    'source_priority': 'critical',  # CRITICAL priority for NIRF
                                    'source_url': nirf_overall_doc.url,
                                    'evidence_quote': f'Extracted from NIRF {nirf_overall_doc.year or "Overall"} document',
                                    'sources': [{
                                        'title': nirf_overall_doc.title,
                                        'url': nirf_overall_doc.url,
                                        'snippet': f'Data extracted from NIRF {nirf_overall_doc.year or "Overall"} document',
                                        'relevance': 'high',
                                        'recency': nirf_overall_doc.year if nirf_overall_doc else 'unknown'
                                    }],
                                    'reasoning': f'Direct pattern extraction from NIRF Overall document'
                                })
                        
                        logger.info(f"[PHASE 2] Pattern extraction: Found {len(nirf_extracted_kpis)} KPIs from NIRF Overall")
                            
                    except Exception as e:
                        logger.error(f"[PHASE 2] Pattern extraction failed: {e}", exc_info=True)
                        # No fallback - KPIs not found will be marked as missing
                else:
                    logger.warning("[PHASE 2] AdvancedNIRFExtractor not available - skipping NIRF extraction")
                
                
                # Identify which KPIs have data and which are missing
                found_in_nirf = []
                nirf_extractable_kpi_names = set(NIRF_EXTRACTABLE_KPIS.keys())
                for result in nirf_extracted_kpis:
                    value = str(result.get('value', '')).lower().strip()
                    kpi_name = result.get('kpi_name')
                    if value in ['data not found', 'error', 'not available', 'n/a', '', '0', '0.0']:
                        missing_kpis.append(kpi_name)
                    else:
                        found_in_nirf.append(kpi_name)
                
                # Add all non-NIRF KPIs to missing list
                all_kpi_names = [kpi['name'] for kpi in self.kpis_data]
                non_nirf_kpis = [name for name in all_kpi_names if name not in nirf_extractable_kpi_names]
                missing_kpis.extend(non_nirf_kpis)
                
                # Calculate counts for logging
                nirf_kpis_count = len([kpi for kpi in self.kpis_data if kpi['name'] in nirf_extractable_kpi_names])
                
                logger.info(f"[PHASE 2] NIRF Overall provided {len(found_in_nirf)}/{nirf_kpis_count} extractable KPIs")
                logger.info(f"[PHASE 2] Total missing KPIs: {len(missing_kpis)} (NIRF-extractable not found: {nirf_kpis_count - len(found_in_nirf)}, Non-NIRF: {len(non_nirf_kpis)})")
                
                if progress_callback:
                    await progress_callback(f"NIRF: {len(found_in_nirf)} found, {len(missing_kpis)} need search", 40)
            else:
                logger.warning(f"[PHASE 2] Could not fetch NIRF Overall PDF content")
                missing_kpis = [kpi['name'] for kpi in self.kpis_data]
        else:
            logger.warning(f"[PHASE 1] No NIRF Overall document found")
            missing_kpis = [kpi['name'] for kpi in self.kpis_data]
            logger.info(f"[PHASE 1] Will search official college website comprehensively for all {len(missing_kpis)} KPIs")
        
        # ======== PHASE 3: SEARCH FOR MISSING KPIs ========
        all_results = nirf_extracted_kpis.copy() if nirf_extracted_kpis else []
        
        # Determine if we need comprehensive website search (when NIRF not available)
        nirf_available = nirf_overall_doc is not None
        
        if missing_kpis:
            if progress_callback:
                search_mode = "official website" if not nirf_available else "additional sources"
                await progress_callback(f"Searching {search_mode} for {len(missing_kpis)} KPIs...", 45)
            
            if not nirf_available:
                logger.info(f"[PHASE 3] NIRF not available - performing comprehensive official website search for {len(missing_kpis)} missing KPIs")
            else:
                logger.info(f"[PHASE 3] Searching for {len(missing_kpis)} missing KPIs")
            
            # Gather additional data sources for missing KPIs
            try:
                search_data = await self.gather_official_data(college_name, progress_callback, college_website_url, nirf_available=nirf_available)
            except Exception as e:
                if "cancelled" in str(e).lower():
                    logger.info(f"Audit cancelled during Phase 3 data gathering")
                    return all_results  # Return NIRF data collected so far
                raise
            
            # Extract structured data
            structured_data = self._extract_structured_data(search_data)
            search_data["structured_extracted"] = structured_data
            
            # ===== REMOVE NIRF DATA - NO LLM ON NIRF =====
            # NIRF data should only be used for pattern extraction, not LLM
            logger.info(f"[PHASE 3] Removing NIRF data from search sources (NO LLM on NIRF)")
            search_data_without_nirf = {
                "nirf": [],  # Empty NIRF data
                "official_website": search_data.get("official_website", []),
                "naac": search_data.get("naac", []),
                "public_disclosure": search_data.get("public_disclosure", []),
                "official_website_content": search_data.get("official_website_content", []),
                "public_disclosure_content": search_data.get("public_disclosure_content", []),
                "kpi_specific_data": search_data.get("kpi_specific_data", {}),
                "nirf_url_to_year": search_data.get("nirf_url_to_year", {}),
                "structured_extracted": structured_data
            }
            
            # Get KPI objects for missing KPIs
            missing_kpi_objects = [kpi for kpi in self.kpis_data if kpi['name'] in missing_kpis]
            
            # Extract missing KPIs in batches (using search_data WITHOUT NIRF)
            batch_size = 5
            for i in range(0, len(missing_kpi_objects), batch_size):
                batch = missing_kpi_objects[i:i + batch_size]
                batch_num = (i // batch_size) + 1
                total_batches = (len(missing_kpi_objects) + batch_size - 1) // batch_size
                
                if progress_callback:
                    progress = 60 + int(((i + batch_size) / len(missing_kpi_objects)) * 30)
                    try:
                        await progress_callback(f"Extracting missing KPIs batch {batch_num}/{total_batches}...", min(progress, 90))
                    except Exception as e:
                        if "cancelled" in str(e).lower():
                            logger.info(f"Audit cancelled during batch {batch_num}")
                            return all_results  # Return what we have so far
                        raise
                
                # LOG START OF EXTRACTION
                kpi_names = [kpi['name'] for kpi in batch]
                logger.info(f"[PHASE 3] Starting extraction batch {batch_num}/{total_batches}: {kpi_names}")
                
                try:
                    batch_results = await self.extract_kpi_with_strict_sources(
                        college_name, batch, search_data_without_nirf, client
                    )
                except Exception as e:
                    if "cancelled" in str(e).lower():
                        logger.info(f"Audit cancelled during KPI extraction")
                        return all_results
                    raise
                
                # Replace missing KPIs in results with newly found data
                for new_result in batch_results:
                    kpi_name = new_result.get('kpi_name')
                    # Remove old "not found" result
                    all_results = [r for r in all_results if r.get('kpi_name') != kpi_name]
                    # Add new result
                    all_results.append(new_result)
                
                await asyncio.sleep(0.05)
        
        # Step 4: Validate and boost confidence
        if progress_callback:
            await progress_callback("Validating and cross-referencing results...", 95)
        
        # Build complete search data for validation (WITHOUT NIRF content for LLM)
        complete_search_data = {}
        if nirf_overall_doc:
            # Include metadata but not content for validation
            complete_search_data = {
                "nirf": [],  # No NIRF content for validation
                "official_website": nirf_search_data.get("official_website", []),
                "naac": nirf_search_data.get("naac", []),
                "public_disclosure": nirf_search_data.get("public_disclosure", []),
                "official_website_content": nirf_search_data.get("official_website_content", []),
                "public_disclosure_content": nirf_search_data.get("public_disclosure_content", []),
                "kpi_specific_data": nirf_search_data.get("kpi_specific_data", {}),
                "nirf_url_to_year": nirf_search_data.get("nirf_url_to_year", {}),
                "structured_extracted": nirf_search_data.get("structured_extracted", {})
            }
        if missing_kpis and 'search_data_without_nirf' in locals():
            # Merge with search data (which also excludes NIRF)
            for key in search_data_without_nirf:
                if key == 'nirf':
                    continue  # Skip NIRF data
                if key in complete_search_data:
                    if isinstance(complete_search_data[key], list):
                        complete_search_data[key].extend(search_data_without_nirf[key])
                    elif isinstance(complete_search_data[key], dict):
                        complete_search_data[key].update(search_data_without_nirf[key])
                else:
                    complete_search_data[key] = search_data_without_nirf[key]
        
        all_results = self._validate_and_boost_results(all_results, complete_search_data, college_website_url)
        
        # ========== DEDUPLICATION: Keep only highest priority result per KPI ==========
        logger.info(f"[DEDUPLICATION] Deduplicating {len(all_results)} results by priority")
        
        # Priority order: critical > high > medium > low
        priority_order = {'critical': 0, 'high': 1, 'medium': 2, 'low': 3}
        
        # Group results by KPI name
        kpi_groups = {}
        for result in all_results:
            kpi_name = result.get('kpi_name')
            if kpi_name not in kpi_groups:
                kpi_groups[kpi_name] = []
            kpi_groups[kpi_name].append(result)
        
        # For each KPI, keep only the highest priority result
        deduplicated_results = []
        for kpi_name, results_for_kpi in kpi_groups.items():
            if len(results_for_kpi) == 1:
                deduplicated_results.append(results_for_kpi[0])
            else:
                # Multiple results for same KPI - select by priority
                results_for_kpi.sort(key=lambda r: priority_order.get(r.get('source_priority', 'low'), 999))
                best_result = results_for_kpi[0]
                deduplicated_results.append(best_result)
                
                # Log which sources were discarded
                discarded = results_for_kpi[1:]
                logger.info(f"[DEDUPLICATION] {kpi_name}: Kept {best_result.get('source_priority', 'unknown')}-priority "
                           f"source, discarded {len(discarded)} lower-priority results")
                for disc in discarded:
                    logger.debug(f"  Discarded: {disc.get('source_priority', 'unknown')} - {disc.get('source_url', 'N/A')}")
        
        all_results = deduplicated_results
        logger.info(f"[DEDUPLICATION] After deduplication: {len(all_results)} results")
        
        # ========== PHASE 1.3: DATA VALIDATION & QUALITY SCORING ==========
        if progress_callback:
            await progress_callback("Running data validation and quality checks...", 97)
        
        logger.info(f"[DATA VALIDATION] Validating {len(all_results)} results")
        
        # Apply comprehensive validation to each result
        validated_results = []
        for result in all_results:
            try:
                # Run validation and enhance with quality scores
                enhanced_result = validate_kpi_result(result)
                validated_results.append(enhanced_result)
            except Exception as e:
                logger.error(f"Validation error for {result.get('kpi_name')}: {e}")
                # Keep original result if validation fails
                validated_results.append(result)
        
        # Check for cross-KPI consistency
        consistency_warnings = []
        kpis_by_name = {r.get('kpi_name'): r for r in validated_results}
        
        placement_warnings = ConsistencyChecker.check_placement_consistency(kpis_by_name)
        year_warnings = ConsistencyChecker.check_year_consistency(kpis_by_name)
        
        consistency_warnings.extend(placement_warnings)
        consistency_warnings.extend(year_warnings)
        
        if consistency_warnings:
            logger.warning(f"[CONSISTENCY] Found {len(consistency_warnings)} potential inconsistencies:")
            for warning in consistency_warnings:
                logger.warning(f"  - {warning}")
        
        all_results = validated_results
        
        # Final pass: Keep ALL KPIs but mark unavailable ones as N/A
        filtered_results = []
        na_count = 0
        low_quality_count = 0
        
        for result in all_results:
            source_url = str(result.get("source_url", "")).strip()
            value = str(result.get("value", "")).strip().lower()
            
            is_valid_source = source_url and source_url not in ["N/A", ""] and self.validator.is_valid_url(source_url)
            is_valid_value = value not in ["data not found", "n/a", "error", "", "not available", "none"]
            
            if not is_valid_source or not is_valid_value:
                # Mark as N/A but keep the result visible
                result["value"] = "N/A"
                result["confidence"] = "low"
                result["system_confidence"] = "low"
                if not is_valid_source:
                    result["source_url"] = ""
                na_count += 1
                logger.info(f"[FINAL] Marked N/A: {result.get('kpi_name')} (valid_source={is_valid_source}, valid_value={is_valid_value})")
            else:
                # Check validation status
                validation_info = result.get('validation', {})
                if not validation_info.get('is_valid', False):
                    logger.info(f"Low quality data for {result.get('kpi_name')}: {validation_info.get('validation_reason')}")
                    low_quality_count += 1
            
            filtered_results.append(result)
        
        logger.info(f"[FINAL FILTER] Total: {len(filtered_results)} KPIs, {na_count} marked N/A, {low_quality_count} low-quality")
        if consistency_warnings:
            logger.info(f"  - Found {len(consistency_warnings)} consistency warnings")
        
        # Log final summary
        logger.info(f"[AUDIT SUMMARY] {college_name}:")
        logger.info(f"  Total KPIs: {len(filtered_results)}")
        logger.info(f"  Data Found: {len(filtered_results) - na_count} ({round(((len(filtered_results) - na_count) / len(filtered_results)) * 100, 1)}%)")
        logger.info(f"  N/A Count: {na_count} ({round((na_count / len(filtered_results)) * 100, 1)}%)")
        
        if progress_callback:
            await progress_callback("Audit complete!", 100)
        
        return filtered_results


# Initialize auditor
auditor = CollegeKPIAuditor()

# ============ Background Task Processing ============

async def process_audit(audit_id: str, college_name: str):
    """Background task to process audit"""
    try:
        async def progress_callback(message: str, progress: int):
            # Update database instead of in-memory store
            db.update_audit_progress(audit_id, progress, message)
            
            # Check if audit was cancelled in database
            audit = db.get_audit(audit_id, include_results=False)
            if audit and audit.status == 'cancelled':
                logger.info(f"Audit {audit_id} was cancelled, stopping processing")
                raise Exception("Audit cancelled by user")
        
        results = await auditor.run_audit(college_name, progress_callback)
        
        # Calculate time taken
        audit = db.get_audit(audit_id, include_results=False)
        if audit:
            # Ensure created_at is timezone-aware for subtraction
            created_at_dt = audit.created_at
            if isinstance(created_at_dt, str):
                created_at_dt = datetime.fromisoformat(created_at_dt.replace('Z', '+00:00'))
            elif created_at_dt.tzinfo is None:
                created_at_dt = created_at_dt.replace(tzinfo=timezone.utc)
            time_taken = (datetime.now(timezone.utc) - created_at_dt).total_seconds()
        
        # Generate summary with enhanced quality metrics
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
        
        high_conf = sum(1 for r in results if r.get('system_confidence', r.get('confidence')) == 'high')
        medium_conf = sum(1 for r in results if r.get('system_confidence', r.get('confidence')) == 'medium')
        low_conf = sum(1 for r in results if r.get('system_confidence', r.get('confidence')) == 'low')
        
        # Quality metrics from validation
        validated_count = sum(1 for r in results if r.get('validation', {}).get('is_valid', False))
        high_evidence_quality = sum(1 for r in results 
                                   if r.get('quality_scores', {}).get('evidence_quality', 0) >= 0.7)
        
        # Group by source type
        sources = {}
        for r in results:
            value = str(r.get('value', '')).strip().lower()
            if value not in ['n/a', 'not available', 'data not found', 'error', '']:
                src = r.get('source_type', 'N/A')
                if src not in sources:
                    sources[src] = 0
                sources[src] += 1
        
        # Source priority breakdown
        source_priority_breakdown = {'critical': 0, 'high': 0, 'medium': 0, 'low': 0}
        for r in results:
            value = str(r.get('value', '')).strip().lower()
            if value not in ['n/a', 'not available', 'data not found', 'error', '']:
                priority = r.get('source_priority', 'unknown')
                if priority in source_priority_breakdown:
                    source_priority_breakdown[priority] += 1
        
        # Confidence comparison (LLM vs System)
        def confidence_value(level):
            return {'high': 3, 'medium': 2, 'low': 1}.get(level, 0)
        
        confidence_comparison = {
            'agreement': 0,  # LLM and System agree
            'llm_higher': 0,  # LLM more confident than system
            'system_higher': 0  # System more confident than LLM
        }
        
        for r in results:
            value = str(r.get('value', '')).strip().lower()
            if value not in ['n/a', 'not available', 'data not found', 'error', '']:
                sys_conf = r.get('system_confidence', 'low')
                llm_conf = r.get('llm_confidence', 'low')
                
                if sys_conf == llm_conf:
                    confidence_comparison['agreement'] += 1
                elif confidence_value(llm_conf) > confidence_value(sys_conf):
                    confidence_comparison['llm_higher'] += 1
                else:
                    confidence_comparison['system_higher'] += 1
        
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
        
        summary = {
            "total_kpis": total,
            "data_found": found_count,
            "data_na": na_count,
            "data_error": error_count,
            "data_not_found": na_count + error_count,  # Total unavailable
            "high_confidence": high_conf,
            "medium_confidence": medium_conf,
            "low_confidence": low_conf,
            "populated_percentage": round((found_count / total) * 100, 1) if total > 0 else 0,
            "na_percentage": round((na_count / total) * 100, 1) if total > 0 else 0,
            "sources_breakdown": sources,
            "source_priority_breakdown": source_priority_breakdown,
            "confidence_comparison": confidence_comparison,
            "categories": categories,
            "quality_metrics": {
                "validated_values": validated_count,
                "high_evidence_quality": high_evidence_quality,
                "validation_rate": round((validated_count / found_count) * 100, 1) if found_count > 0 else 0,
                "evidence_quality_rate": round((high_evidence_quality / found_count) * 100, 1) if found_count > 0 else 0
            }
        }
        
        # Save to database
        db.complete_audit(audit_id, results, summary, time_taken)
        
    except Exception as e:
        import traceback
        logger.error(f"Audit processing error: {e}")
        logger.error(f"Full traceback:\n{traceback.format_exc()}")
        audit = db.get_audit(audit_id, include_results=False)
        if audit:
            # Check if it was a cancellation
            if audit.status == 'cancelled':
                logger.info(f"Audit {audit_id} cancellation confirmed")
            else:
                db.fail_audit(audit_id, str(e))


# ============ API Routes ============

@api_router.get("/")
async def root():
    return {"message": "College KPI Auditor API", "status": "running", "version": "2.0"}

@api_router.get("/health")
async def health_check():
    return {"status": "healthy", "timestamp": datetime.now(timezone.utc).isoformat()}

@api_router.get("/kpis")
async def get_kpis():
    """Get all available KPIs"""
    return {
        "total": len(auditor.kpis_data),
        "kpis": auditor.kpis_data
    }

@api_router.get("/sources")
async def get_allowed_sources():
    """Get list of allowed official sources"""
    return {
        "allowed_sources": {
            "priority_1": "Official College Website (.ac.in, .edu.in)",
            "priority_2": "Public Disclosure (AICTE/UGC Mandatory)",
            "priority_3": "NIRF (nirfindia.org)",
            "priority_4": "NAAC (naac.gov.in)"
        },
        "blocked_sources": OfficialSourceValidator.BLOCKED_SOURCES[:10]
    }

@api_router.post("/audit/start")
@limiter.limit("10/minute")
async def start_audit(data: AuditRequest, background_tasks: BackgroundTasks, request: Request):
    """Start a new college audit"""
    audit_id = str(uuid.uuid4())
    college_name = data.college_name.strip()
    
    if not college_name:
        raise HTTPException(status_code=400, detail="College name is required")
    
    # Normalize college name
    from data_parsers import FuzzyMatcher
    college_name_normalized = FuzzyMatcher.normalize_text(college_name)
    
    # Create audit in database
    db.create_audit(audit_id, college_name, college_name_normalized)
    
    background_tasks.add_task(process_audit, audit_id, college_name)
    
    return {"audit_id": audit_id, "status": "processing", "message": f"Audit started for {college_name}"}

@api_router.post("/audit/{audit_id}/cancel")
async def cancel_audit(audit_id: str):
    """Cancel a running audit"""
    audit = db.get_audit(audit_id, include_results=False)
    
    if not audit:
        raise HTTPException(status_code=404, detail="Audit not found")
    
    current_status = audit.status
    
    # Allow cancellation if processing
    if current_status not in ['processing', '']:
        # If already completed or failed, just return success
        if current_status in ['completed', 'failed']:
            return {
                "message": f"Audit already {current_status}", 
                "audit_id": audit_id,
                "status": current_status
            }
        # If already cancelled, return success
        if current_status == 'cancelled':
            return {
                "message": "Audit already cancelled", 
                "audit_id": audit_id,
                "status": "cancelled"
            }
    
    # Mark as cancelled in database
    db.cancel_audit(audit_id)
    
    logger.info(f"Audit {audit_id} cancelled by user")
    
    return {
        "message": "Audit cancelled successfully", 
        "audit_id": audit_id,
        "status": "cancelled"
    }

@api_router.get("/audit/{audit_id}")
async def get_audit_status(audit_id: str):
    """Get audit status and results"""
    audit = db.get_audit(audit_id, include_results=True)
    
    if not audit:
        raise HTTPException(status_code=404, detail="Audit not found")
    
    return audit.to_dict(include_results=True)

@api_router.get("/audit/{audit_id}/stream")
async def stream_audit_progress(audit_id: str):
    """Stream audit progress updates via SSE"""
    async def event_generator():
        last_progress = -1
        while True:
            audit = db.get_audit(audit_id, include_results=False)
            
            if not audit:
                yield f"data: {json.dumps({'error': 'Audit not found'})}\n\n"
                break
            
            audit_dict = audit.to_dict(include_results=False)
            
            if audit.progress != last_progress or audit.status == 'completed':
                last_progress = audit.progress
                yield f"data: {json.dumps(audit_dict)}\n\n"
            
            if audit.status in ['completed', 'failed']:
                break
            
            await asyncio.sleep(1)
    
    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
        }
    )

@api_router.get("/audits")
async def list_audits(
    limit: int = 20,
    offset: int = 0,
    college_name: Optional[str] = None,
    status: Optional[str] = None
):
    """List recent audits with optional filtering"""
    audits = db.list_audits(
        college_name=college_name,
        status=status,
        limit=limit,
        offset=offset
    )
    return {
        "audits": [audit.to_dict(include_results=False) for audit in audits],
        "count": len(audits),
        "limit": limit,
        "offset": offset
    }

@api_router.delete("/audit/{audit_id}")
async def delete_audit(audit_id: str):
    """Delete an audit"""
    audit = db.get_audit(audit_id, include_results=False)
    if not audit:
        raise HTTPException(status_code=404, detail="Audit not found")
    
    # Delete from database (cascade will delete results too)
    session = db.get_session()
    try:
        session.delete(audit)
        session.commit()
    finally:
        session.close()
    
    return {"message": "Audit deleted", "id": audit_id}

# ===== Batch Processing Endpoints =====

class BatchAuditRequest(BaseModel):
    """Request model for batch audit"""
    college_names: List[str] = Field(..., min_length=1, max_length=10, description="List of college names (max 10)")

@api_router.post("/audit/batch")
@limiter.limit("3/hour")
async def start_batch_audit(data: BatchAuditRequest, background_tasks: BackgroundTasks, request: Request):
    """Start audits for multiple colleges"""
    if len(data.college_names) > 10:
        raise HTTPException(status_code=400, detail="Maximum 10 colleges per batch")
    
    batch_id = str(uuid.uuid4())
    audit_ids = []
    
    for college_name in data.college_names:
        if not college_name.strip():
            continue
        
        audit_id = str(uuid.uuid4())
        from data_parsers import FuzzyMatcher
        college_name_normalized = FuzzyMatcher.normalize_text(college_name.strip())
        
        # Create audit in database
        db.create_audit(audit_id, college_name.strip(), college_name_normalized)
        background_tasks.add_task(process_audit, audit_id, college_name.strip())
        
        audit_ids.append({
            "audit_id": audit_id,
            "college_name": college_name.strip(),
            "status": "processing"
        })
    
    return {
        "batch_id": batch_id,
        "audits": audit_ids,
        "total": len(audit_ids),
        "message": f"Started {len(audit_ids)} audits"
    }

@api_router.get("/audit/batch/{batch_id}")
async def get_batch_status(batch_id: str):
    """Get status of a batch audit (placeholder - requires batch tracking)"""
    return {
        "batch_id": batch_id,
        "message": "Batch tracking requires additional implementation",
        "suggestion": "Use /audits endpoint to list recent audits"
    }

# ===== Historical Comparison Endpoints =====

@api_router.get("/college/{college_name}/history")
async def get_college_history(college_name: str, limit: int = 5):
    """Get audit history for a specific college"""
    audits = db.get_audit_history(college_name, limit=limit)
    
    if not audits:
        return {
            "college_name": college_name,
            "audits": [],
            "count": 0,
            "message": "No audit history found for this college"
        }
    
    return {
        "college_name": college_name,
        "audits": [audit.to_dict(include_results=False) for audit in audits],
        "count": len(audits)
    }

@api_router.get("/compare/{audit_id_1}/{audit_id_2}")
async def compare_audits(audit_id_1: str, audit_id_2: str):
    """Compare two audits and show differences"""
    comparison = db.compare_audits(audit_id_1, audit_id_2)
    
    if "error" in comparison:
        raise HTTPException(status_code=404, detail=comparison["error"])
    
    return comparison

@api_router.get("/college/{college_name}/latest")
async def get_latest_audit(college_name: str):
    """Get the most recent completed audit for a college"""
    audits = db.get_audit_history(college_name, limit=1)
    
    if not audits:
        raise HTTPException(
            status_code=404,
            detail=f"No completed audits found for {college_name}"
        )
    
    latest = audits[0]
    return latest.to_dict(include_results=True)

# ===== Statistics & Analytics Endpoints =====

@api_router.get("/stats/overview")
async def get_statistics_overview():
    """Get overall statistics"""
    session = db.get_session()
    try:
        from sqlalchemy import func
        from database import Audit
        
        total_audits = session.query(func.count(Audit.id)).scalar()
        completed = session.query(func.count(Audit.id)).filter(Audit.status == "completed").scalar()
        processing = session.query(func.count(Audit.id)).filter(Audit.status == "processing").scalar()
        failed = session.query(func.count(Audit.id)).filter(Audit.status == "failed").scalar()
        
        # Average time taken for completed audits
        avg_time = session.query(func.avg(Audit.time_taken_seconds)).filter(
            Audit.status == "completed",
            Audit.time_taken_seconds.isnot(None)
        ).scalar()
        
        return {
            "total_audits": total_audits or 0,
            "completed": completed or 0,
            "processing": processing or 0,
            "failed": failed or 0,
            "average_time_seconds": round(float(avg_time), 2) if avg_time else None,
            "database": "Connected"
        }
    finally:
        session.close()

@api_router.post("/maintenance/cleanup")
async def cleanup_old_data(days: int = 30):
    """Clean up old audits and rate limit entries (admin only)"""
    # In production, add authentication/authorization here
    
    deleted_audits = db.delete_old_audits(days=days, keep_completed=True)
    db.cleanup_old_rate_limits(hours=24)
    
    return {
        "message": "Cleanup completed",
        "deleted_audits": deleted_audits,
        "kept_completed": True
    }


# Include router
app.include_router(api_router)

# Add rate limiting
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

# CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_credentials=True,
    allow_origins=os.environ.get('CORS_ORIGINS', '*').split(','),
    allow_methods=["*"],
    allow_headers=["*"],
)

if __name__ == "__main__":
    import uvicorn
    init_database()
    uvicorn.run(app, host="0.0.0.0", port=8000)
