from django.test import TestCase

from accounts.models import Organization
from bots.bots_api_utils import validate_meeting_url_and_credentials
from bots.models import Project


class TestValidateMeetingUrlAndCredentials(TestCase):
    def setUp(self):
        # Create organization first since it's required for Project
        organization = Organization.objects.create(name="Test Organization")
        self.project = Project.objects.create(name="Test Project", organization=organization)

    def test_validate_google_meet_url(self):
        """Test Google Meet URL validation"""
        # Valid Google Meet URL
        error = validate_meeting_url_and_credentials("https://meet.google.com/abc-defg-hij", self.project)
        self.assertIsNone(error)

        # Invalid Google Meet URL format
        error = validate_meeting_url_and_credentials("http://meet.google.com/abc-defg-hij", self.project)
        self.assertEqual(error, {"error": "Google Meet URL must start with https://meet.google.com/"})

    def test_validate_zoom_url_and_credentials(self):
        """Test Zoom URL and credentials validation"""
        # Test Zoom URL without credentials
        error = validate_meeting_url_and_credentials("https://zoom.us/j/123456789", self.project)
        self.assertEqual(error, {"error": f"Zoom App credentials are required to create a Zoom bot. Please add Zoom credentials at https://app.attendee.dev/projects/{self.project.object_id}/credentials"})

    def test_validate_teams_url(self):
        """Test Teams URL validation"""
        # Teams URLs don't require specific validation
        error = validate_meeting_url_and_credentials("https://teams.microsoft.com/meeting/123", self.project)
        self.assertIsNone(error)
