import unittest
from unittest.mock import patch, MagicMock
import sys, os

from autoexpress.modules import a1111_api

class TestA1111API(unittest.TestCase):

    @patch("a1111_api.requests")
    def test_interrupt(self, mock_requests):
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_requests.post.return_value = mock_response

        self.assertTrue(a1111_api.interrupt())

    @patch("a1111_api.requests")
    def test_get_extensions(self, mock_requests):
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = [{"name": "extension", "enabled": True}]
        mock_requests.get.return_value = mock_response

        extensions = a1111_api.get_extensions()
        self.assertTrue("extension" in extensions)
        self.assertTrue(extensions["extension"])

    # Write similar tests for other functions like get_loras, get_samplers, etc.

    @patch("a1111_api.requests")
    def test_img2img_api(self, mock_requests):
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_requests.post.return_value = mock_response

        json_payload = {}  # Provide valid JSON payload
        self.assertTrue(a1111_api.img2img_api(json_payload))

    @patch("a1111_api.requests")
    def test_get_image_info(self, mock_requests):
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_requests.post.return_value = mock_response

        b64_image = "valid_base64_string"
        self.assertTrue(a1111_api.get_image_info(b64_image))


if __name__ == "__main__":
    unittest.main()
