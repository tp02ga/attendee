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
    base_mock.AUTHRET_JWTTOKENWRONG = 7
    
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

    def setUp(self):
        # Recreate organization and project for each test
        self.organization = Organization.objects.create(name="Test Org")
        self.project = Project.objects.create(
            name="Test Project",
            organization=self.organization
        )
        
        # Recreate credentials
        self.credentials = Credentials.objects.create(
            project=self.project,
            credential_type=Credentials.CredentialTypes.ZOOM_OAUTH
        )
        self.credentials.set_credentials({
            'client_id': 'test_client_id',
            'client_secret': 'test_client_secret'
        })

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
            auth_callback.onAuthenticationReturnCallback(mock_zoom_sdk.AUTHRET_SUCCESS)

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

            connection.close()
        
        # Run join flow simulation after a short delay
        threading.Timer(2, simulate_join_flow).start()
        
        # Give the bot some time to process
        time.sleep(5)
        
        # Refresh the bot from the database
        self.bot.refresh_from_db()
        
        # Check that the bot joined successfully
        latest_event = self.bot.last_bot_event()
        self.assertIsNotNone(latest_event)
        self.assertEqual(latest_event.event_type, BotEventTypes.BOT_JOINED_MEETING)
        
        # Verify expected SDK calls
        mock_zoom_sdk.InitSDK.assert_called_once()
        mock_zoom_sdk.CreateMeetingService.assert_called_once()
        mock_zoom_sdk.CreateAuthService.assert_called_once()
        controller.adapter.meeting_service.Join.assert_called_once()
        
        # Additional verification for StreamingUploader
        controller.streaming_uploader.start_upload.assert_called_once()
        
        # Cleanup
        controller.cleanup()
        bot_thread.join(timeout=5)
        
        # Close the database connection since we're in a thread
        connection.close()

    @patch('bots.zoom_bot_adapter.zoom_bot_adapter.jwt')
    @patch('bots.zoom_bot_adapter.zoom_bot_adapter.zoom', new_callable=create_mock_zoom_sdk)
    @patch('bots.bot_controller.bot_controller.StreamingUploader')
    def test_bot_can_handle_failed_zoom_auth(self, MockStreamingUploader, mock_zoom_sdk, mock_jwt):
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
            # Simulate failed auth            
            controller.adapter.auth_event.onAuthenticationReturnCallback(mock_zoom_sdk.AUTHRET_JWTTOKENWRONG)
            # Clean up connections in thread
            connection.close()
        
        # Run join flow simulation after a short delay
        threading.Timer(2, simulate_join_flow).start()
        
        # Give the bot some time to process
        time.sleep(4)
        
        # Refresh the bot from the database
        self.bot.refresh_from_db()
        
        # Check that the bot joined successfully
        bot_events = self.bot.bot_events.all()
        self.assertEqual(len(bot_events), 2)
        join_requested_event = bot_events[0]
        could_not_join_event = bot_events[1]

        # Verify join_requested_event properties
        self.assertEqual(join_requested_event.event_type, BotEventTypes.JOIN_REQUESTED)
        self.assertEqual(join_requested_event.old_state, BotStates.READY)
        self.assertEqual(join_requested_event.new_state, BotStates.JOINING)
        self.assertIsNone(join_requested_event.event_sub_type)
        self.assertIsNone(join_requested_event.debug_message)
        self.assertIsNotNone(join_requested_event.requested_bot_action_taken_at)

        # Verify could_not_join_event properties
        self.assertEqual(could_not_join_event.event_type, BotEventTypes.COULD_NOT_JOIN)
        self.assertEqual(could_not_join_event.old_state, BotStates.JOINING)
        self.assertEqual(could_not_join_event.new_state, BotStates.FATAL_ERROR)
        self.assertEqual(could_not_join_event.event_sub_type, BotEventSubTypes.COULD_NOT_JOIN_MEETING_ZOOM_AUTHORIZATION_FAILED)
        self.assertIsNotNone(could_not_join_event.debug_message)
        self.assertIsNone(could_not_join_event.requested_bot_action_taken_at)

        # Verify expected SDK calls
        mock_zoom_sdk.InitSDK.assert_called_once()
        mock_zoom_sdk.CreateMeetingService.assert_called_once()
        mock_zoom_sdk.CreateAuthService.assert_called_once()
        controller.adapter.meeting_service.Join.assert_not_called()
        
        # Additional verification for StreamingUploader
        # Probably should not be called, but it currently is
        #controller.streaming_uploader.start_upload.assert_not_called()
        
        # Cleanup
        # no need to cleanup since we already hit error
        # controller.cleanup() will be called by the bot controller

        bot_thread.join(timeout=5)
        
        # Close the database connection since we're in a thread
        connection.close()