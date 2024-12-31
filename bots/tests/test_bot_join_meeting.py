from django.test import TestCase
from unittest.mock import patch, MagicMock, create_autospec, PropertyMock
from bots.models import *
import os
import threading
import time
from django.db import connection
from bots.bot_controller import BotController
from django.db import transaction
from django.test.testcases import TransactionTestCase
from bots.bot_controller.streaming_uploader import StreamingUploader

def create_mock_streaming_uploader():
    mock_streaming_uploader = MagicMock(spec=StreamingUploader)
    mock_streaming_uploader.upload_part.return_value = None
    mock_streaming_uploader.complete_upload.return_value = None
    mock_streaming_uploader.start_upload.return_value = None
    mock_streaming_uploader.key = 'test-recording-key'  # Simple string attribute
    return mock_streaming_uploader

def create_mock_zoom_sdk():
    # Create mock zoom_meeting_sdk module with proper callback handling
    base_mock = MagicMock()
    
    # Create a custom AuthServiceEventCallbacks class that actually stores the callback
    class MockAuthServiceEventCallbacks:
        def __init__(self, onAuthenticationReturnCallback):
            self.stored_callback = onAuthenticationReturnCallback

        def onAuthenticationReturnCallback(self, result):
            return self.stored_callback(result)

    # Replace the mock's AuthServiceEventCallbacks with our custom version
    base_mock.AuthServiceEventCallbacks = MockAuthServiceEventCallbacks

    # Create a custom MeetingServiceEventCallbacks class that actually stores the callback
    class MockMeetingServiceEventCallbacks:
        def __init__(self, onMeetingStatusChangedCallback):
            self.stored_callback = onMeetingStatusChangedCallback

        def onMeetingStatusChangedCallback(self, status, result):
            return self.stored_callback(status, result)

    # Replace the mock's MeetingServiceEventCallbacks with our custom version
    base_mock.MeetingServiceEventCallbacks = MockMeetingServiceEventCallbacks
    
    # Set up constants
    base_mock.SDKERR_SUCCESS = 0
    base_mock.AUTHRET_SUCCESS = 1
    base_mock.MEETING_STATUS_IDLE = 2
    base_mock.MEETING_STATUS_CONNECTING = 3
    base_mock.MEETING_STATUS_INMEETING = 4
    base_mock.MEETING_STATUS_ENDED = 5
    base_mock.LEAVE_MEETING = 6
    
    # Mock SDK_LANGUAGE_ID
    base_mock.SDK_LANGUAGE_ID = MagicMock()
    base_mock.SDK_LANGUAGE_ID.LANGUAGE_English = 0
    
    # Mock SDKUserType
    base_mock.SDKUserType = MagicMock()
    base_mock.SDKUserType.SDK_UT_WITHOUT_LOGIN = 1

    # Create mock services
    mock_meeting_service = MagicMock()
    mock_auth_service = MagicMock()
    mock_setting_service = MagicMock()
    
    # Configure mock services
    mock_meeting_service.SetEvent.return_value = base_mock.SDKERR_SUCCESS
    mock_meeting_service.Join.return_value = base_mock.SDKERR_SUCCESS
    mock_meeting_service.GetMeetingStatus.return_value = base_mock.MEETING_STATUS_IDLE
    mock_meeting_service.Leave.return_value = base_mock.SDKERR_SUCCESS
    
    mock_auth_service.SetEvent.return_value = base_mock.SDKERR_SUCCESS
    mock_auth_service.SDKAuth.return_value = base_mock.SDKERR_SUCCESS
    
    # Configure service creation functions
    base_mock.CreateMeetingService.return_value = mock_meeting_service
    base_mock.CreateAuthService.return_value = mock_auth_service
    base_mock.CreateSettingService.return_value = mock_setting_service
    
    # Configure InitSDK
    base_mock.InitSDK.return_value = base_mock.SDKERR_SUCCESS

    # Add SDKError class mock with SDKERR_SUCCESS
    base_mock.SDKError = MagicMock()
    base_mock.SDKError.SDKERR_SUCCESS = 0  # Use the same value as SDKERR_SUCCESS

    return base_mock

class TestBotJoinMeeting(TransactionTestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        
        # Set required environment variables
        os.environ['REDIS_URL'] = 'redis://host.docker.internal:6379/5'
        os.environ['AWS_RECORDING_STORAGE_BUCKET_NAME'] = 'test-bucket'
        
        # Create test organization and project
        cls.organization = Organization.objects.create(name="Test Org")
        cls.project = Project.objects.create(
            name="Test Project",
            organization=cls.organization
        )
        
        # Create credentials
        cls.credentials = Credentials.objects.create(
            project=cls.project,
            credential_type=Credentials.CredentialTypes.ZOOM_OAUTH
        )
        cls.credentials.set_credentials({
            'client_id': 'test_client_id',
            'client_secret': 'test_client_secret'
        })

    def setUp(self):
        # Create a bot for each test
        self.bot = Bot.objects.create(
            project=self.project,
            name="Test Bot",
            meeting_url="https://zoom.us/j/123456789?pwd=password123"
        )
        
        # Create default recording
        self.recording = Recording.objects.create(
            bot=self.bot,
            recording_type=RecordingTypes.AUDIO_AND_VIDEO,
            transcription_type=TranscriptionTypes.NON_REALTIME,
            transcription_provider=TranscriptionProviders.DEEPGRAM,
            is_default_recording=True
        )

        # Try to transition the state from READY to JOINING
        BotEventManager.create_event(self.bot, BotEventTypes.JOIN_REQUESTED)

    @patch('bots.zoom_bot_adapter.zoom_bot_adapter.jwt')
    @patch('bots.zoom_bot_adapter.zoom_bot_adapter.zoom', new_callable=create_mock_zoom_sdk)
    @patch('bots.bot_controller.bot_controller.StreamingUploader')
    def test_bot_can_join_meeting(self, MockStreamingUploader, mock_zoom_sdk, mock_jwt):
        # Configure the mock class to return our mock instance
        mock_uploader = create_mock_streaming_uploader()
        MockStreamingUploader.return_value = mock_uploader
        
        # Mock the JWT token generation
        mock_jwt.encode.return_value = "fake_jwt_token"
        
        # Create bot controller
        controller = BotController(self.bot.id)
        
        # Run the bot in a separate thread since it has an event loop
        bot_thread = threading.Thread(target=controller.run)
        bot_thread.daemon = True
        bot_thread.start()
        
        # Simulate the meeting join flow
        def simulate_join_flow():
            # Get the meeting status changed callback
            meeting_callback = controller.adapter.meeting_service_event
            auth_callback = controller.adapter.auth_event
            
            # Simulate successful auth            
            rez = auth_callback.onAuthenticationReturnCallback(mock_zoom_sdk.AUTHRET_SUCCESS)
            print("AUTH RETURNED", rez)
            # Simulate connecting
            meeting_callback.onMeetingStatusChangedCallback(
                mock_zoom_sdk.MEETING_STATUS_CONNECTING, 
                mock_zoom_sdk.SDKERR_SUCCESS
            )
            
            # Simulate successful join
            meeting_callback.onMeetingStatusChangedCallback(
                mock_zoom_sdk.MEETING_STATUS_INMEETING, 
                mock_zoom_sdk.SDKERR_SUCCESS
            )
        
        # Run join flow simulation after a short delay
        threading.Timer(5, simulate_join_flow).start()
        
        # Give the bot some time to process
        time.sleep(10)
        
        # Refresh the bot from the database
        self.bot.refresh_from_db()
        
        # Check that the bot joined successfully
        latest_event = self.bot.last_bot_event()
        self.assertIsNotNone(latest_event)
        self.assertEqual(latest_event.event_type, BotEventTypes.BOT_JOINED_MEETING)
        print("LATEST EVENT", latest_event)
        
        # Verify expected SDK calls
        mock_zoom_sdk.InitSDK.assert_called_once()
        mock_zoom_sdk.CreateMeetingService.assert_called_once()
        mock_zoom_sdk.CreateAuthService.assert_called_once()
        controller.adapter.meeting_service.Join.assert_called_once()
        
        # Additional verification for StreamingUploader
        #mock_streaming_uploader.start_upload.assert_called_once()
        
        # Cleanup
        controller.cleanup()
        bot_thread.join(timeout=5)
        
        # Close the database connection since we're in a thread
        connection.close()

    # def test_bot_handles_auth_failure(self):
    #     # Similar test but simulating auth failure
    #     pass

    # def test_bot_handles_waiting_room(self):
    #     # Test for waiting room scenario
    #     pass

    def tearDown(self):
        # Clean up any bot-specific resources
        #self.bot.delete()
        pass

    @classmethod
    def tearDownClass(cls):
        # Clean up organization and project
        #cls.organization.delete()
        #super().tearDownClass() 
        pass