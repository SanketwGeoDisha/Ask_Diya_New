import unittest
from unittest.mock import patch, MagicMock
import requests

# We will implement this function in server.py, but for now we define it here to test the logic
# or we can import it after we implement it.
# To allow TDD, I will define a standalone version here that mirrors the intended implementation,
# then we will move/adapt it to the class.

def check_website_availability(url):
    """
    Check if the website is accessible.
    Returns True if status code is 200-299, False otherwise.
    """
    if not url:
        return False
        
    try:
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
        }
        
        # Try HEAD first
        try:
            response = requests.head(url, headers=headers, timeout=5, allow_redirects=True)
            if 200 <= response.status_code < 300:
                return True
        except requests.RequestException:
            # If HEAD fails or times out, try GET
            pass
            
        # Try GET if HEAD failed
        response = requests.get(url, headers=headers, timeout=10, stream=True)
        # Close connection immediately
        response.close()
        
        return 200 <= response.status_code < 300
        
    except Exception as e:
        print(f"Website check failed for {url}: {e}")
        return False

class TestWebsiteAvailability(unittest.TestCase):
    
    @patch('requests.head')
    def test_successful_head(self, mock_head):
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_head.return_value = mock_response
        
        self.assertTrue(check_website_availability("https://www.example.com"))
        
    @patch('requests.head')
    @patch('requests.get')
    def test_failed_head_successful_get(self, mock_get, mock_head):
        # HEAD fails with 405 Method Not Allowed
        mock_head_response = MagicMock()
        mock_head_response.status_code = 405
        mock_head.return_value = mock_head_response
        
        # GET succeeds
        mock_get_response = MagicMock()
        mock_get_response.status_code = 200
        mock_get.return_value = mock_get_response
        
        self.assertTrue(check_website_availability("https://www.example.com"))
        
    @patch('requests.head')
    @patch('requests.get')
    def test_website_down(self, mock_get, mock_head):
        # Both fail with connection error
        mock_head.side_effect = requests.ConnectionError("Connection refused")
        mock_get.side_effect = requests.ConnectionError("Connection refused")
        
        self.assertFalse(check_website_availability("https://www.down-site.com"))

    @patch('requests.head')
    @patch('requests.get')
    def test_404_not_found(self, mock_get, mock_head):
        # HEAD returns 404
        mock_head_response = MagicMock()
        mock_head_response.status_code = 404
        mock_head.return_value = mock_head_response
        
        # GET also returns 404
        mock_get_response = MagicMock()
        mock_get_response.status_code = 404
        mock_get.return_value = mock_get_response
        
        self.assertFalse(check_website_availability("https://www.example.com/nonexistent"))

if __name__ == '__main__':
    unittest.main()
