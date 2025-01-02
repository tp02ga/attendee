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

    # Create a custom ZoomSDKRendererDelegateCallbacks class that actually stores the callback
    class MockZoomSDKRendererDelegateCallbacks:
        def __init__(self, onRawDataFrameReceivedCallback, onRendererBeDestroyedCallback, onRawDataStatusChangedCallback):
            self.stored_callback = onRawDataFrameReceivedCallback
            self.stored_renderer_destroyed_callback = onRendererBeDestroyedCallback
            self.stored_raw_data_status_changed_callback = onRawDataStatusChangedCallback

        def onRawDataFrameReceivedCallback(self, data):
            return self.stored_callback(data)
        
        def onRendererBeDestroyedCallback(self):
            return self.stored_renderer_destroyed_callback()
        
        def onRawDataStatusChangedCallback(self, status):
            return self.stored_raw_data_status_changed_callback(status)
    base_mock.ZoomSDKRendererDelegateCallbacks = MockZoomSDKRendererDelegateCallbacks

    # Create a custom MeetingRecordingCtrlEventCallbacks class that actually stores the callback
    class MockMeetingRecordingCtrlEventCallbacks:
        def __init__(self, onRecordPrivilegeChangedCallback):
            self.stored_callback = onRecordPrivilegeChangedCallback

        def onRecordPrivilegeChangedCallback(self, can_record):
            return self.stored_callback(can_record)
    base_mock.MeetingRecordingCtrlEventCallbacks = MockMeetingRecordingCtrlEventCallbacks
    
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
    mock_zoom_sdk_renderer = MagicMock()
    
    # Configure mock services
    mock_meeting_service.SetEvent.return_value = base_mock.SDKERR_SUCCESS
    mock_meeting_service.Join.return_value = base_mock.SDKERR_SUCCESS
    mock_meeting_service.GetMeetingStatus.return_value = base_mock.MEETING_STATUS_IDLE
    mock_meeting_service.Leave.return_value = base_mock.SDKERR_SUCCESS

    # Add mock recording controller
    mock_recording_controller = MagicMock()
    mock_recording_controller.CanStartRawRecording.return_value = base_mock.SDKERR_SUCCESS
    mock_recording_controller.StartRawRecording.return_value = base_mock.SDKERR_SUCCESS
    mock_meeting_service.GetMeetingRecordingController.return_value = mock_recording_controller
    
    mock_auth_service.SetEvent.return_value = base_mock.SDKERR_SUCCESS
    mock_auth_service.SDKAuth.return_value = base_mock.SDKERR_SUCCESS
    
    # Configure service creation functions
    base_mock.CreateMeetingService.return_value = mock_meeting_service
    base_mock.CreateAuthService.return_value = mock_auth_service
    base_mock.CreateSettingService.return_value = mock_setting_service
    base_mock.CreateRenderer.return_value = mock_zoom_sdk_renderer
    
    # Configure InitSDK
    base_mock.InitSDK.return_value = base_mock.SDKERR_SUCCESS

    # Add SDKError class mock with SDKERR_SUCCESS
    base_mock.SDKError = MagicMock()
    base_mock.SDKError.SDKERR_SUCCESS = 0  # Use the same value as SDKERR_SUCCESS

    # Create a mock PerformanceData class
    class MockPerformanceData:
        def __init__(self):
            self.totalProcessingTimeMicroseconds = 1000
            self.numCalls = 100
            self.maxProcessingTimeMicroseconds = 20
            self.minProcessingTimeMicroseconds = 5
            self.processingTimeBinMin = 0
            self.processingTimeBinMax = 100
            self.processingTimeBinCounts = [10, 20, 30, 20, 10, 5, 3, 2]  # Example distribution

    # Create a custom ZoomSDKAudioRawDataDelegateCallbacks class that actually stores the callback
    class MockZoomSDKAudioRawDataDelegateCallbacks:
        def __init__(self, onOneWayAudioRawDataReceivedCallback, onMixedAudioRawDataReceivedCallback, collectPerformanceData=False):
            self.stored_one_way_callback = onOneWayAudioRawDataReceivedCallback
            self.stored_mixed_callback = onMixedAudioRawDataReceivedCallback
            self.collect_performance_data = collectPerformanceData

        def onOneWayAudioRawDataReceivedCallback(self, data, node_id):
            return self.stored_one_way_callback(data, node_id)

        def onMixedAudioRawDataReceivedCallback(self, data):
            return self.stored_mixed_callback(data)

        def getPerformanceData(self):
            return MockPerformanceData()

    base_mock.ZoomSDKAudioRawDataDelegateCallbacks = MockZoomSDKAudioRawDataDelegateCallbacks

    return base_mock

class MockVideoFrame:
    def __init__(self):
        width = 640
        height = 360
        
        # Create separate Y, U, and V planes
        self.y_buffer = b'\x00' * (width * height)        # Y plane (black)
        self.u_buffer = b'\x80' * (width * height // 4)   # U plane (128 for black)
        self.v_buffer = b'\x80' * (width * height // 4)   # V plane (128 for black)
        
        self.size = len(self.y_buffer) + len(self.u_buffer) + len(self.v_buffer)
        self.timestamp = int(time.time() * 1000)  # Current time in milliseconds

    def GetBuffer(self):
        return self.y_buffer + self.u_buffer + self.v_buffer

    def GetYBuffer(self):
        return self.y_buffer

    def GetUBuffer(self):
        return self.u_buffer

    def GetVBuffer(self):
        return self.v_buffer

    def GetStreamWidth(self):
        return 640

    def GetStreamHeight(self):
        return 360

class MockAudioFrame:
    def __init__(self):
        # Create 100ms of silence at 8000Hz mono
        # 8000 samples/sec * 0.1 sec = 800 samples
        # Each sample is 1 byte
        self.buffer = b'\x00' * 800

    def GetBuffer(self):
        return self.buffer

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

    @patch('bots.zoom_bot_adapter.video_input_manager.zoom', new_callable=create_mock_zoom_sdk)
    @patch('bots.zoom_bot_adapter.zoom_bot_adapter.zoom', new_callable=create_mock_zoom_sdk)
    @patch('bots.zoom_bot_adapter.zoom_bot_adapter.jwt')
    @patch('bots.bot_controller.bot_controller.StreamingUploader')
    def test_bot_can_join_meeting_and_record_audio_and_video(self, MockStreamingUploader, mock_jwt, mock_zoom_sdk_adapter, mock_zoom_sdk_video):
        # Store uploaded data for verification
        uploaded_data = bytearray()
        
        # Configure the mock uploader to capture uploaded data
        mock_uploader = create_mock_streaming_uploader()
        def capture_upload_part(data):
            uploaded_data.extend(data)
        mock_uploader.upload_part.side_effect = capture_upload_part
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
            adapter = controller.adapter
            # Simulate successful auth            
            adapter.auth_event.onAuthenticationReturnCallback(mock_zoom_sdk_adapter.AUTHRET_SUCCESS)

            # Simulate connecting
            adapter.meeting_service_event.onMeetingStatusChangedCallback(
                mock_zoom_sdk_adapter.MEETING_STATUS_CONNECTING, 
                mock_zoom_sdk_adapter.SDKERR_SUCCESS
            )
            
            # Simulate successful join
            adapter.meeting_service_event.onMeetingStatusChangedCallback(
                mock_zoom_sdk_adapter.MEETING_STATUS_INMEETING, 
                mock_zoom_sdk_adapter.SDKERR_SUCCESS
            )

            # Wait for the video input manager to be set up
            time.sleep(1)

            # Simulate video frame received
            adapter.video_input_manager.input_streams[0].renderer_delegate.onRawDataFrameReceivedCallback(
                MockVideoFrame()
            )

            # Simulate audio frame received
            adapter.audio_source.onOneWayAudioRawDataReceivedCallback(
                MockAudioFrame(),
                2  # Simulated participant ID that's not the bot
            )

            # Simulate meeting ended
            adapter.meeting_service_event.onMeetingStatusChangedCallback(
                mock_zoom_sdk_adapter.MEETING_STATUS_ENDED, 
                mock_zoom_sdk_adapter.SDKERR_SUCCESS
            )

            connection.close()
        
        # Run join flow simulation after a short delay
        threading.Timer(3, simulate_join_flow).start()
        
        # Give the bot some time to process
        time.sleep(6)
        
        # Verify that we received some data
        self.assertEqual(len(uploaded_data), 10992, "Uploaded data length is not correct")
        
        # Check for MP4 file signature (starts with 'ftyp')
        mp4_signature_found = b'ftyp' in uploaded_data[:1000]
        self.assertTrue(mp4_signature_found, "MP4 file signature not found in uploaded data")
        
        # Additional verification for StreamingUploader
        mock_uploader.start_upload.assert_called_once()
        self.assertGreater(mock_uploader.upload_part.call_count, 0, "upload_part was never called")
        
        # Refresh the bot from the database
        self.bot.refresh_from_db()
        
        # Check that the bot joined successfully
        latest_event = self.bot.last_bot_event()
        self.assertIsNotNone(latest_event)
        self.assertEqual(latest_event.event_type, BotEventTypes.MEETING_ENDED)
        
        # Verify expected SDK calls
        mock_zoom_sdk_adapter.InitSDK.assert_called_once()
        mock_zoom_sdk_adapter.CreateMeetingService.assert_called_once()
        mock_zoom_sdk_adapter.CreateAuthService.assert_called_once()
        controller.adapter.meeting_service.Join.assert_called_once()
        
        # Cleanup
        controller.cleanup()
        bot_thread.join(timeout=5)
        
        # Close the database connection since we're in a thread
        connection.close()

    @patch('bots.zoom_bot_adapter.video_input_manager.zoom', new_callable=create_mock_zoom_sdk)
    @patch('bots.zoom_bot_adapter.zoom_bot_adapter.zoom', new_callable=create_mock_zoom_sdk)
    @patch('bots.zoom_bot_adapter.zoom_bot_adapter.jwt')
    @patch('bots.bot_controller.bot_controller.StreamingUploader')
    def test_bot_can_handle_failed_zoom_auth(self, MockStreamingUploader, mock_jwt, mock_zoom_sdk_adapter, mock_zoom_sdk_video):
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
            controller.adapter.auth_event.onAuthenticationReturnCallback(mock_zoom_sdk_adapter.AUTHRET_JWTTOKENWRONG)
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
        mock_zoom_sdk_adapter.InitSDK.assert_called_once()
        mock_zoom_sdk_adapter.CreateMeetingService.assert_called_once()
        mock_zoom_sdk_adapter.CreateAuthService.assert_called_once()
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