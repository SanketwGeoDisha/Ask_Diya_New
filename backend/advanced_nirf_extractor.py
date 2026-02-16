#!/usr/bin/env python3
"""
Advanced NIRF KPI Extractor v3.0
=================================
Production-grade extractor with enhanced accuracy and complete KPI coverage.

Features:
- Detailed program-wise breakdowns
- Multi-year historical data
- Enhanced pattern matching
- Comprehensive error handling
- Clean table-formatted output
"""

import re
from typing import Dict, List, Any, Optional, Tuple
from dataclasses import dataclass, field
from collections import defaultdict
import logging

logger = logging.getLogger(__name__)


@dataclass
class ProgramPlacementData:
    """Complete placement data for a program"""
    program_name: str
    year: str
    intake: int
    admitted: int
    lateral_entry: int
    graduated: int
    placed: int
    median_salary: int
    higher_studies: int
    placement_rate: float
    
    def __str__(self):
        return (f"{self.program_name} ({self.year}): "
                f"Graduated={self.graduated}, Placed={self.placed} ({self.placement_rate:.1f}%), "
                f"Salary=₹{self.median_salary:,}, Higher Ed={self.higher_studies}")


@dataclass
class FacultyMember:
    """Individual faculty data"""
    name: str
    age: int
    designation: str
    gender: str
    qualification: str
    experience_months: int
    
    @property
    def has_phd(self) -> bool:
        return 'Ph.D' in self.qualification or 'PhD' in self.qualification


@dataclass
class ComprehensiveNIRFData:
    """Complete NIRF data structure with all 12 KPIs"""
    institution_name: str = ""
    nirf_id: str = ""
    
    # KPI 1: Graduate Students (with complete breakdown)
    total_graduates: int = 0
    ug_3yr_graduates: int = 0
    ug_4yr_graduates: int = 0
    ug_5yr_graduates: int = 0
    ug_6yr_graduates: int = 0
    pg_2yr_graduates: int = 0
    pg_3yr_graduates: int = 0
    pg_integrated_graduates: int = 0
    pg_6yr_graduates: int = 0
    
    # KPI 2: Placed Students (with breakdown)
    total_placed: int = 0
    ug_placed: int = 0
    pg_placed: int = 0
    placement_details: List[ProgramPlacementData] = field(default_factory=list)
    overall_placement_rate: float = 0.0
    
    # KPI 3 & 4: Compensation
    max_compensation: int = 0
    median_compensation: int = 0
    max_comp_program: str = ""
    salary_by_program: Dict[str, int] = field(default_factory=dict)
    
    # KPI 5: Higher Education
    total_higher_education: int = 0
    ug_higher_ed: int = 0
    pg_higher_ed: int = 0
    
    # KPI 6: Gender Diversity
    total_students: int = 0
    male_students: int = 0
    female_students: int = 0
    female_percentage: float = 0.0
    ug_total: int = 0
    pg_total: int = 0
    
    # KPI 7 & 8: Faculty
    total_faculty: int = 0
    phd_faculty: int = 0
    phd_faculty_percentage: float = 0.0
    professors: int = 0
    associate_professors: int = 0
    assistant_professors: int = 0
    faculty_list: List[FacultyMember] = field(default_factory=list)
    
    # KPI 9: Teaching Experience
    avg_experience_years: float = 0.0
    avg_experience_months: float = 0.0
    min_experience: float = 0.0
    max_experience: float = 0.0
    
    # KPI 10: Accreditation
    naac_cgpa: Optional[float] = None
    naac_grade: Optional[str] = None
    naac_valid_from: Optional[str] = None
    naac_valid_upto: Optional[str] = None
    
    # KPI 11: PhD Enrollment
    phd_full_time: int = 0
    phd_part_time: int = 0
    total_phd_students: int = 0
    phd_graduated_2023: int = 0
    phd_graduated_2022: int = 0
    phd_graduated_2021: int = 0
    
    # KPI 12: Total Enrollment
    total_enrollment: int = 0
    
    # Additional useful data
    patents_published: int = 0
    patents_granted: int = 0
    sanctioned_intake_ug: int = 0
    sanctioned_intake_pg: int = 0


class AdvancedNIRFExtractor:
    """Advanced extractor with comprehensive pattern matching"""
    
    # Enhanced program patterns
    PROGRAM_PATTERNS = {
        'UG_3Y': r'UG\s*\[3.*?Year',
        'UG_4Y': r'UG\s*\[4.*?Year',
        'UG_5Y': r'UG\s*\[5.*?Year',
        'UG_6Y': r'UG\s*\[6.*?Year',
        'PG_2Y': r'PG\s*\[2.*?Year',
        'PG_3Y': r'PG\s*\[3.*?Year',
        'PG_INT': r'PG-Integrated',
        'PG_6Y': r'PG\s*\[6.*?Year',
    }
    
    def __init__(self, text_content: str):
        """Initialize with extracted text"""
        self.text = text_content
        self.lines = text_content.split('\n')
        self.data = ComprehensiveNIRFData()
        # Track all placement records to pick latest later
        self.all_placement_records = []
        # Track all PhD graduation records
        self.all_phd_grad_records = []
        
    def extract_all_kpis(self) -> ComprehensiveNIRFData:
        """Extract all 12 KPIs with maximum detail"""
        logger.info("Starting comprehensive KPI extraction...")
        
        # Extract metadata
        self._extract_institution_info()
        
        # Extract all KPIs
        self._extract_sanctioned_intake()
        self._extract_student_strength()
        self._extract_placement_data()
        self._extract_phd_enrollment()
        self._extract_faculty_details()
        self._extract_naac_accreditation()
        self._extract_patents()
        
        # New: Select latest year data from collected records
        self._select_latest_year_data()
        
        # Calculate derived metrics
        self._calculate_derived_metrics()
        
        logger.info("Extraction complete!")
        return self.data
    
    def _extract_institution_info(self):
        """Extract institution name and NIRF ID"""
        # Pattern: Institute Name: XYZ [IR-O-C-12345]
        pattern = r'Institute Name:\s*([^\[]+)\s*\[([^\]]+)\]'
        match = re.search(pattern, self.text, re.IGNORECASE)
        
        if match:
            self.data.institution_name = match.group(1).strip()
            self.data.nirf_id = match.group(2).strip()
            logger.info(f"Institution: {self.data.institution_name} [{self.data.nirf_id}]")
    
    def _extract_sanctioned_intake(self):
        """Extract sanctioned intake capacity"""
        # Find the Sanctioned Intake section
        section_match = re.search(
            r'Sanctioned.*?Intake.*?Academic Year.*?(?=Total Actual|$)',
            self.text,
            re.IGNORECASE | re.DOTALL
        )
        
        if not section_match:
            return
        
        section_text = section_match.group(0)
        
        # Extract UG intake
        ug_match = re.search(r'UG\s*\[4\s*Years?\s*Program.*?(\d+)', section_text)
        if ug_match:
            self.data.sanctioned_intake_ug = int(ug_match.group(1))
        
        # Extract PG intake
        pg_match = re.search(r'PG\s*\[2\s*Years?\s*Program.*?(\d+)', section_text)
        if pg_match:
            self.data.sanctioned_intake_pg = int(pg_match.group(1))
    
    def _extract_student_strength(self):
        """Extract complete student strength with gender breakdown"""
        section_match = re.search(
            r'Total Actual Student Strength.*?(?=Placement|Ph\.D|Financial|$)',
            self.text,
            re.IGNORECASE | re.DOTALL
        )
        
        if not section_match:
            # Fallback: look for just the table header
            section_match = re.search(
                r'\(All programs of all years\).*?(?=Placement|Ph\.D|Financial|$)',
                self.text,
                re.IGNORECASE | re.DOTALL
            )
        
        if not section_match:
            logger.warning("Student strength section not found")
            return
        
        section_text = section_match.group(0)
        
        # Extract data for each program type
        for prog_key, prog_pattern in self.PROGRAM_PATTERNS.items():
            # Pattern: Program Type | Male | Female | Total
            # Made more robust to handle messy text/newlines between tokens
            pattern = f'{prog_pattern}.*?(\\d+)\\s+.*?(\\d+)\\s+.*?(\\d+)'
            match = re.search(pattern, section_text, re.IGNORECASE | re.DOTALL)
            
            if match:
                male = int(match.group(1))
                female = int(match.group(2))
                total = int(match.group(3))
                
                self.data.male_students += male
                self.data.female_students += female
                self.data.total_students += total
                
                # Track UG vs PG
                if 'UG' in prog_key:
                    self.data.ug_total += total
                elif 'PG' in prog_key:
                    self.data.pg_total += total
        
        logger.info(f"Student Strength: Total={self.data.total_students}, "
                   f"Male={self.data.male_students}, Female={self.data.female_students}")
    
    def _extract_placement_data(self):
        """Extract all placement tables from the document globally"""
        logger.info("Starting global placement table discovery...")
        
        # Find all "Placement & Higher Studies" headers as anchors
        # Pattern handles fragmentation like "Placement & Higher Stu"
        anchors = list(re.finditer(r'Placement\s*&\s*Higher\s*Stu', self.text, re.IGNORECASE))
        
        if not anchors:
            logger.warning("No placement table anchors found!")
            return

        for i, anchor in enumerate(anchors):
            # Determine end of this table (either the next anchor or some other big section)
            end_pos = anchors[i+1].start() if i < len(anchors)-1 else len(self.text)
            table_text = self.text[anchor.end():end_pos]
            
            # Find the program label *above* this anchor (look back ~200 chars)
            lookback_text = self.text[max(0, anchor.start()-300):anchor.start()]
            
            # Identify which program this table belongs to
            prog_key = 'UNKNOWN'
            for key, pattern in self.PROGRAM_PATTERNS.items():
                if re.search(pattern, lookback_text, re.IGNORECASE | re.DOTALL):
                    prog_key = key
                    break
            
            if prog_key == 'UNKNOWN':
                # Try searching in the anchor text itself (sometimes label is inside)
                for key, pattern in self.PROGRAM_PATTERNS.items():
                    if re.search(pattern, table_text[:100], re.IGNORECASE | re.DOTALL):
                        prog_key = key
                        break
            
            logger.info(f"Found placement table for: {prog_key}")
            self._extract_program_placement_content(prog_key, table_text)
        
        logger.info(f"Placement: Total Graduates={self.data.total_graduates}, "
                   f"Placed={self.data.total_placed}, Rate={self.data.overall_placement_rate:.1f}%")

    def _extract_program_placement_content(self, prog_key: str, section_text: str):
        """Extract rows from a pre-identified placement section"""
        
        # Robust token-based parsing: Find any year '20XX-YY' and then extract following numbers
        # This handles the messy format where NIRF columns are mangled in text
        tokens = re.split(r'(\d{4}-\d{2})', section_text)
        
        # tokens[0] is pre-first-year text
        # tokens[1] is '20XX-YY', tokens[2] is text between years
        for i in range(1, len(tokens)-1, 2):
            year = tokens[i]
            data_text = tokens[i+1]
            
            # Find all numbers in data_text
            # We filter for numbers that look like counts or salaries
            nums = [int(n.replace(',', '')) for n in re.findall(r'\d[\d,]*', data_text)]
            
            if not nums:
                continue

            # In NIRF, a placement row for a year usually has:
            # [Graduated, Placed, Median Salary, Higher Education]
            # Sometimes preceded by lateral entry or intake.
            
            # Anchor: Find the salary (usually the largest number > 10000)
            salary = 0
            salary_idx = -1
            for idx, n in enumerate(nums):
                if n > 50000: # Typical minimum median salary in INR
                    salary = n
                    salary_idx = idx
                    break
            
            if salary > 0:
                # We found a salary row!
                # Graduated and Placed should be the two numbers immediately preceding the salary
                graduated = nums[salary_idx-2] if salary_idx >= 2 else 0
                placed = nums[salary_idx-1] if salary_idx >= 1 else 0
                higher_ed = nums[salary_idx+1] if salary_idx < len(nums)-1 else 0
                
                # Validation: Placed cannot be > Graduated
                if placed > graduated and graduated > 0:
                    # Maybe the order is different? [Grad, Lateral, Placed, Salary, HigherEd]
                    if salary_idx >= 3:
                         graduated = nums[salary_idx-3]
                         placed = nums[salary_idx-1]

                if graduated > 0 or placed > 0:
                    placement = ProgramPlacementData(
                        program_name=prog_key,
                        year=year,
                        intake=0,
                        admitted=0,
                        lateral_entry=0,
                        graduated=graduated,
                        placed=placed,
                        median_salary=salary,
                        higher_studies=higher_ed,
                        placement_rate=round((placed / graduated * 100) if graduated > 0 else 0, 2)
                    )
                    self.all_placement_records.append(placement)
                    self.data.placement_details.append(placement)
                    logger.info(f"  EXTRACTED: {placement}")


    def _select_latest_year_data(self):
        """Pick the latest available year for each program and aggregate"""
        logger.info("Selecting latest year data across all programs...")
        
        # 1. Handle Placement / Graduates
        program_latest = {} # prog_name -> latest_placement_obj
        
        for p in self.all_placement_records:
            prog = p.program_name
            # Compare years like '2022-23' > '2021-22'
            if prog not in program_latest or p.year > program_latest[prog].year:
                program_latest[prog] = p
        
        # Now aggregate from the "winners"
        for prog, p in program_latest.items():
            self.data.total_graduates += p.graduated
            self.data.total_placed += p.placed
            self.data.total_higher_education += p.higher_studies
            
            # Track by program type
            if 'UG' in prog:
                self.data.ug_placed += p.placed
                self.data.ug_higher_ed += p.higher_studies
                if '3Y' in prog: self.data.ug_3yr_graduates += p.graduated
                elif '4Y' in prog: self.data.ug_4yr_graduates += p.graduated
                elif '5Y' in prog: self.data.ug_5yr_graduates += p.graduated
                elif '6Y' in prog: self.data.ug_6yr_graduates += p.graduated
            elif 'PG' in prog:
                self.data.pg_placed += p.placed
                self.data.pg_higher_ed += p.higher_studies
                if '2Y' in prog: self.data.pg_2yr_graduates += p.graduated
                elif '3Y' in prog: self.data.pg_3yr_graduates += p.graduated
                elif 'INT' in prog: self.data.pg_integrated_graduates += p.graduated
                elif '6Y' in prog: self.data.pg_6yr_graduates += p.graduated
            
            # Track salaries
            self.data.salary_by_program[prog] = p.median_salary
            if p.median_salary > self.data.max_compensation:
                self.data.max_compensation = p.median_salary
                self.data.max_comp_program = prog
        
        # 2. Handle PhD Graduates
        # PhD section populates phd_graduated_2023/22/21. 
        # But we need to pick 'latest' to avoid showing older data if newer exists.
        if self.data.phd_graduated_2023 > 0:
             self.data.total_phd_graduates = self.data.phd_graduated_2023
        elif self.data.phd_graduated_2022 > 0:
             self.data.total_phd_graduates = self.data.phd_graduated_2022
        elif self.data.phd_graduated_2021 > 0:
             self.data.total_phd_graduates = self.data.phd_graduated_2021
    
    def _extract_faculty_details(self):
        """Extract comprehensive faculty data"""
        # Find faculty section
        section_match = re.search(
            r'Faculty Details.*?(?=PCS Facilities|Sustainability|Accreditation|$)',
            self.text,
            re.IGNORECASE | re.DOTALL
        )
        
        if not section_match:
            logger.warning("Faculty section not found")
            return
        
        section_text = section_match.group(0)
        
        # Pattern for faculty rows: Srno Name Age Designation Gender Qualification Experience
        faculty_pattern = r'(\d+)\s+([A-Z][A-Za-z\s]+?)\s+(\d{2})\s+(Professor|Associate Professor|Assistant Professor|Lecturer)\s+(Male|Female)\s+(Ph\.D|M\.Tech|M\.Sc\.|MBA|M\.E\.|M\. Phil|B\.Tech|LLB|MCA|MP\.Ed\.|M\.A)\s+(\d+)\s+Yes'
        
        for match in re.finditer(faculty_pattern, section_text):
            try:
                faculty = FacultyMember(
                    name=match.group(2).strip(),
                    age=int(match.group(3)),
                    designation=match.group(4),
                    gender=match.group(5),
                    qualification=match.group(6),
                    experience_months=int(match.group(7))
                )
                
                self.data.faculty_list.append(faculty)
                self.data.total_faculty += 1
                
                if faculty.has_phd:
                    self.data.phd_faculty += 1
                
                # Count by designation
                if 'Professor' in faculty.designation and 'Associate' not in faculty.designation and 'Assistant' not in faculty.designation:
                    self.data.professors += 1
                elif 'Associate Professor' in faculty.designation:
                    self.data.associate_professors += 1
                elif 'Assistant Professor' in faculty.designation:
                    self.data.assistant_professors += 1
                
            except (ValueError, IndexError):
                continue
        
        logger.info(f"Faculty: Total={self.data.total_faculty}, PhD={self.data.phd_faculty}, "
                   f"Professors={self.data.professors}, Assoc={self.data.associate_professors}, "
                   f"Asst={self.data.assistant_professors}")
    
    def _extract_phd_enrollment(self):
        """Extract PhD student details"""
        section_match = re.search(
            r'Ph\.D Student Details.*?(?=PG \(Student|Online Education|Financial|$)',
            self.text,
            re.IGNORECASE | re.DOTALL
        )
        
        if not section_match:
            logger.warning("PhD section not found")
            return
        
        section_text = section_match.group(0)
        
        # Extract enrollment
        ft_match = re.search(r'Full Time\s+(\d+)', section_text)
        pt_match = re.search(r'Part Time\s+(\d+)', section_text)
        
        if ft_match:
            self.data.phd_full_time = int(ft_match.group(1))
        if pt_match:
            self.data.phd_part_time = int(pt_match.group(1))
        
        self.data.total_phd_students = self.data.phd_full_time + self.data.phd_part_time
        
        # Extract graduation data
        grad_pattern = r'(\d{4}-\d{2}).*?Full Time\s+(\d+).*?Part Time\s+(\d+)'
        for match in re.finditer(grad_pattern, section_text, re.DOTALL):
            year = match.group(1)
            ft_grad = int(match.group(2))
            pt_grad = int(match.group(3))
            total_grad = ft_grad + pt_grad
            
            # Store year-based graduation
            if '2023-24' in year or '2024' in year: self.data.phd_graduated_2023 = total_grad
            elif '2022-23' in year or '2023' in year: self.data.phd_graduated_2023 = total_grad # Handle offset
            elif '2021-22' in year: self.data.phd_graduated_2022 = total_grad
            elif '2020-21' in year: self.data.phd_graduated_2021 = total_grad
        
        logger.info(f"PhD Students: FT={self.data.phd_full_time}, PT={self.data.phd_part_time}")
    
    def _extract_naac_accreditation(self):
        """Extract NAAC accreditation details"""
        section_match = re.search(
            r'NAAC Accreditation.*?Valid from\s+Valid upto\s+CGPA.*?(\d{2}-\d{2}-\d{4})\s+(\d{2}-\d{2}-\d{4})\s+([\d.]+)',
            self.text,
            re.IGNORECASE | re.DOTALL
        )
        
        if section_match:
            self.data.naac_valid_from = section_match.group(1)
            self.data.naac_valid_upto = section_match.group(2)
            self.data.naac_cgpa = float(section_match.group(3))
            
            # Determine grade
            cgpa = self.data.naac_cgpa
            if cgpa >= 3.51:
                self.data.naac_grade = 'A++'
            elif cgpa >= 3.26:
                self.data.naac_grade = 'A+'
            elif cgpa >= 3.01:
                self.data.naac_grade = 'A'
            elif cgpa >= 2.76:
                self.data.naac_grade = 'B++'
            elif cgpa >= 2.51:
                self.data.naac_grade = 'B+'
            else:
                self.data.naac_grade = 'B'
            
            logger.info(f"NAAC: Grade={self.data.naac_grade}, CGPA={self.data.naac_cgpa}")
    
    def _extract_patents(self):
        """Extract patent data"""
        ipr_match = re.search(
            r'IPR.*?Calendar year\s+2022.*?No\. of Patents Published\s+(\d+).*?No\. of Patents Granted\s+(\d+)',
            self.text,
            re.IGNORECASE | re.DOTALL
        )
        
        if ipr_match:
            self.data.patents_published = int(ipr_match.group(1))
            self.data.patents_granted = int(ipr_match.group(2))
    
    def _calculate_derived_metrics(self):
        """Calculate derived metrics"""
        # Gender diversity
        if self.data.total_students > 0:
            self.data.female_percentage = round(
                (self.data.female_students / self.data.total_students) * 100, 2
            )
        
        # Placement rate
        if self.data.total_graduates > 0:
            self.data.overall_placement_rate = round(
                (self.data.total_placed / self.data.total_graduates) * 100, 2
            )
        
        # PhD faculty percentage
        if self.data.total_faculty > 0:
            self.data.phd_faculty_percentage = round(
                (self.data.phd_faculty / self.data.total_faculty) * 100, 2
            )
        
        # Average experience
        if self.data.faculty_list:
            experiences = [f.experience_months for f in self.data.faculty_list]
            self.data.avg_experience_months = round(sum(experiences) / len(experiences), 2)
            self.data.avg_experience_years = round(self.data.avg_experience_months / 12, 2)
            self.data.min_experience = round(min(experiences) / 12, 2)
            self.data.max_experience = round(max(experiences) / 12, 2)
        
        # Median compensation
        if self.data.salary_by_program:
            salaries = sorted(self.data.salary_by_program.values())
            self.data.median_compensation = salaries[len(salaries) // 2]
        
        # Total enrollment
        self.data.total_enrollment = self.data.total_students + self.data.total_phd_students
    
    def get_program_wise_salary_3yr(self) -> Dict[str, Dict[str, int]]:
        """
        Extract last 3 years of median salary data for each program.
        Returns nested dict: {program: {year: salary}}
        Example: {"Computer Science": {"2025": 1219000, "2024": 1150000, "2023": 1103000}}
        """
        program_year_salary = {}
        
        # Process all placement records
        for record in self.data.placement_details:
            program = record.program_name
            year_str = record.year  # e.g., "2023-24"
            salary = record.median_salary
            
            # Extract the ending year from "2023-24" format (→ 2024)
            # or "2024" format (→ 2024)
            year_match = re.search(r'(\d{4})$', year_str)
            if year_match:
                year = year_match.group(1)
            else:
                continue  # Skip if year format is unclear
            
            # Only include last 3 years (2023, 2024, 2025)
            if year not in ['2023', '2024', '2025']:
                continue
            
            if salary > 0:  # Only include meaningful salary data
                if program not in program_year_salary:
                    program_year_salary[program] = {}
                program_year_salary[program][year] = salary
        
        return program_year_salary
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert extracted data to dictionary format"""
        return {
            "institution_name": self.data.institution_name,
            "nirf_id": self.data.nirf_id,
            "total_graduates": self.data.total_graduates,
            "ug_3yr_graduates": self.data.ug_3yr_graduates,
            "ug_4yr_graduates": self.data.ug_4yr_graduates,
            "ug_5yr_graduates": self.data.ug_5yr_graduates,
            "ug_6yr_graduates": self.data.ug_6yr_graduates,
            "pg_2yr_graduates": self.data.pg_2yr_graduates,
            "pg_3yr_graduates": self.data.pg_3yr_graduates,
            "pg_integrated_graduates": self.data.pg_integrated_graduates,
            "pg_6yr_graduates": self.data.pg_6yr_graduates,
            "total_placed": self.data.total_placed,
            "ug_placed": self.data.ug_placed,
            "pg_placed": self.data.pg_placed,
            "max_compensation": self.data.max_compensation,
            "median_compensation": self.data.median_compensation,
            "total_higher_education": self.data.total_higher_education,
            "ug_higher_ed": self.data.ug_higher_ed,
            "pg_higher_ed": self.data.pg_higher_ed,
            "total_students": self.data.total_students,
            "female_students": self.data.female_students,
            "female_percentage": self.data.female_percentage,
            "total_faculty": self.data.total_faculty,
            "phd_faculty": self.data.phd_faculty,
            "phd_faculty_percentage": self.data.phd_faculty_percentage,
            "avg_experience_years": self.data.avg_experience_years,
            "naac_cgpa": self.data.naac_cgpa,
            "naac_grade": self.data.naac_grade,
            "total_phd_students": self.data.total_phd_students,
            "phd_full_time": self.data.phd_full_time,
            "phd_part_time": self.data.phd_part_time,
            "total_enrollment": self.data.total_enrollment,
            "patents_published": self.data.patents_published,
            "patents_granted": self.data.patents_granted,
            "program_wise_salary_3yr": self.get_program_wise_salary_3yr(),
        }
