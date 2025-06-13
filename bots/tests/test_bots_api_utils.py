from unittest.mock import patch

from django.test import TestCase

from accounts.models import Organization
from bots.bots_api_utils import BotCreationSource, create_bot, validate_meeting_url_and_credentials
from bots.models import Bot, Project, RecordingFormats


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


class TestCreateBot(TestCase):
    def setUp(self):
        organization = Organization.objects.create(name="Test Organization")
        self.project = Project.objects.create(name="Test Project", organization=organization)

    def test_create_bot(self):
        bot, error = create_bot(data={"meeting_url": "https://meet.google.com/abc-defg-hij", "bot_name": "Test Bot"}, source=BotCreationSource.API, project=self.project)
        self.assertIsNotNone(bot)
        self.assertIsNotNone(bot.recordings.first())
        self.assertIsNone(error)

    def test_create_bot_with_image(self):
        bot, error = create_bot(data={"meeting_url": "https://teams.microsoft.com/meeting/123", "bot_name": "Test Bot", "bot_image": {"type": "image/png", "data": "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg=="}}, source=BotCreationSource.API, project=self.project)
        self.assertIsNotNone(bot)
        self.assertIsNotNone(bot.recordings.first())
        self.assertIsNotNone(bot.media_requests.first())
        self.assertIsNone(error)
        self.assertEqual(bot.bot_events.first().metadata["source"], BotCreationSource.API)

    def create_bot_with_google_meet_url_with_http(self):
        bot, error = create_bot(data={"meeting_url": "http://meet.google.com/abc-defg-hij", "bot_name": "Test Bot"}, source=BotCreationSource.DASHBOARD, project=self.project)
        self.assertIsNotNone(bot)
        self.assertIsNotNone(error)
        self.assertEqual(error, {"error": "Google Meet URL must start with https://meet.google.com/"})
        self.assertEqual(bot.bot_events.first().metadata["source"], BotCreationSource.DASHBOARD)


class TestBotCpuRequest(TestCase):
    def setUp(self):
        """Set up test data"""
        self.organization = Organization.objects.create(name="Test Organization")
        self.project = Project.objects.create(name="Test Project", organization=self.organization)

    def create_bot(self, meeting_url, recording_settings=None):
        """Helper method to create a bot with given settings"""
        settings = {}
        if recording_settings:
            settings["recording_settings"] = recording_settings

        return Bot.objects.create(
            name="Test Bot",
            project=self.project,
            meeting_url=meeting_url,
            settings=settings,
        )

    @patch("bots.models.os.getenv")
    def test_google_meet_audio_video_cpu_request(self, mock_getenv):
        """Test CPU request for Google Meet with audio and video recording"""
        # Set up environment variable mock
        mock_getenv.side_effect = lambda key, default=None: {
            "GOOGLE_MEET_AUDIO_AND_VIDEO_BOT_CPU_REQUEST": "8",
            "BOT_CPU_REQUEST": "4",
        }.get(key, default)

        bot = self.create_bot("https://meet.google.com/abc-defg-hij")

        result = bot.cpu_request()

        self.assertEqual(result, "8")
        # Verify the correct environment variable was checked
        mock_getenv.assert_any_call("GOOGLE_MEET_AUDIO_AND_VIDEO_BOT_CPU_REQUEST", "4")

    @patch("bots.models.os.getenv")
    def test_google_meet_audio_only_cpu_request(self, mock_getenv):
        """Test CPU request for Google Meet with audio only recording"""
        mock_getenv.side_effect = lambda key, default=None: {
            "GOOGLE_MEET_AUDIO_ONLY_BOT_CPU_REQUEST": "2",
            "BOT_CPU_REQUEST": "4",
        }.get(key, default)

        bot = self.create_bot("https://meet.google.com/abc-defg-hij", recording_settings={"format": RecordingFormats.MP3})

        result = bot.cpu_request()

        self.assertEqual(result, "2")
        mock_getenv.assert_any_call("GOOGLE_MEET_AUDIO_ONLY_BOT_CPU_REQUEST", "4")

    @patch("bots.models.os.getenv")
    def test_zoom_audio_video_cpu_request(self, mock_getenv):
        """Test CPU request for Zoom with audio and video recording"""
        mock_getenv.side_effect = lambda key, default=None: {
            "ZOOM_AUDIO_AND_VIDEO_BOT_CPU_REQUEST": "6",
            "BOT_CPU_REQUEST": "4",
        }.get(key, default)

        bot = self.create_bot("https://zoom.us/j/123456789")

        result = bot.cpu_request()

        self.assertEqual(result, "6")
        mock_getenv.assert_any_call("ZOOM_AUDIO_AND_VIDEO_BOT_CPU_REQUEST", "4")

    @patch("bots.models.os.getenv")
    def test_zoom_audio_only_cpu_request(self, mock_getenv):
        """Test CPU request for Zoom with audio only recording"""
        mock_getenv.side_effect = lambda key, default=None: {
            "ZOOM_AUDIO_ONLY_BOT_CPU_REQUEST": "3",
            "BOT_CPU_REQUEST": "4",
        }.get(key, default)

        bot = self.create_bot("https://zoom.us/j/123456789", recording_settings={"format": RecordingFormats.MP3})

        result = bot.cpu_request()

        self.assertEqual(result, "3")
        mock_getenv.assert_any_call("ZOOM_AUDIO_ONLY_BOT_CPU_REQUEST", "4")
