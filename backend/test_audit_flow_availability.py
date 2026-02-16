import unittest
from unittest.mock import patch, MagicMock, AsyncMock
import asyncio
import sys
import os

# Add local directory to path to import server
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from server import CollegeKPIAuditor

class TestAuditFlowAvailability(unittest.TestCase):
    
    def setUp(self):
        # Mock dependencies
        self.mock_db = MagicMock()
        self.mock_gemini_key = "fake_key"
        self.mock_serper_rotator = MagicMock()
        self.mock_serper_rotator.api_keys = ["fake_serper"]
        
        self.auditor = CollegeKPIAuditor()
        self.auditor.gemini_api_key = self.mock_gemini_key
        self.auditor.serper_api_rotator = self.mock_serper_rotator

    @patch('server.genai.Client')
    def test_gemini_bad_url_falls_back_to_search(self, mock_client):
        # Setup mocks
        # 1. Gemini returns a bad URL
        self.auditor.get_college_website_from_gemini = AsyncMock(return_value="https://down-site.com")
        
        # 2. _check_website_availability returns False for down-site, True for up-site
        def check_avail(url):
            if "down-site" in url:
                return False
            if "up-site" in url:
                return True
            return False
        self.auditor._check_website_availability = MagicMock(side_effect=check_avail)
        
        # 3. Search returns a good URL
        self.auditor.search_official_sources = MagicMock(return_value={
            "official_results": [{"url": "https://up-site.ac.in/home"}]
        })
        
        # 4. Mock NIRF to stop execution
        with patch('server.collect_nirf_for_college', new_callable=AsyncMock) as mock_nirf:
            mock_nirf.return_value = {}
            
            # Run audit
            try:
                asyncio.run(self.auditor.run_audit("Test College"))
            except Exception:
                pass
            
            # Verify:
            # 1. Gemini was called
            self.auditor.get_college_website_from_gemini.assert_called()
            
            # 2. Availability checked for bad URL
            self.auditor._check_website_availability.assert_any_call("https://down-site.com")
            
            # 3. Search was called (because Gemini URL failed)
            self.auditor.search_official_sources.assert_called()
            
            # 4. Availability checked for search result
            self.auditor._check_website_availability.assert_any_call("https://up-site.ac.in")

if __name__ == '__main__':
    unittest.main()
