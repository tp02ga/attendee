import zoom_meeting_sdk as zoom
import jwt
#from deepgram_transcriber import DeepgramTranscriber
from datetime import datetime, timedelta
import os
import numpy as np
from collections import deque

def generate_jwt(client_id, client_secret):
    iat = datetime.utcnow()
    exp = iat + timedelta(hours=24)
    
    payload = {
        "iat": iat,
        "exp": exp,
        "appKey": client_id,
        "tokenExp": int(exp.timestamp())
    }
    
    token = jwt.encode(payload, client_secret, algorithm="HS256")
    return token

def normalized_rms_audio(samples):
    return np.mean(np.abs(samples)) / 32767.0


class ZoomBot:
    class Messages:
        LEAVE_MEETING_WAITING_FOR_HOST = "Leave meeting because received waiting for host status"
        BOT_PUT_IN_WAITING_ROOM = "Bot put in waiting room"
        BOT_JOINED_MEETING = "Bot joined meeting"
        BOT_RECORDING_PERMISSION_GRANTED = "Bot recording permission granted"
        MEETING_ENDED = "Meeting ended"
        NEW_UTTERANCE = "New utterance"

    def __init__(self, *, send_message_callback, zoom_client_id, zoom_client_secret, meeting_id, meeting_password):
        self.send_message_callback = send_message_callback

        self._jwt_token = generate_jwt(zoom_client_id, zoom_client_secret)
        self.meeting_id = meeting_id
        self.meeting_password = meeting_password

        self.meeting_service = None
        self.setting_service = None
        self.auth_service = None

        self.auth_event = None
        self.recording_event = None
        self.meeting_service_event = None

        self.audio_source = None
        self.audio_helper = None

        self.audio_settings = None

        self.use_raw_recording = True

        self.reminder_controller = None

        self.recording_ctrl = None

        self.audio_raw_data_sender = None
        self.virtual_audio_mic_event_passthrough = None

        #self.deepgram_transcriber = DeepgramTranscriber()

        self.my_participant_id = None
        self.participants_ctrl = None
        self.meeting_reminder_event = None
        self.audio_print_counter = 0

        self.speaker_buffers = {}  # Add this line to store buffers per speaker
        self.first_nonsilent_audio_time = {}  # Add this line to track silence per speaker
        self.last_nonsilent_audio_time = {}  # Add this line to track silence per speaker
        self.BUFFER_SIZE_LIMIT = 38 * 1024 * 1024  # 38 MB in bytes
        self.SILENCE_THRESHOLD = 0.0125  # RMS threshold for silence detection
        self.SILENCE_DURATION_LIMIT = 3  # seconds
        self.timeline_start = None

    def cleanup(self):
        if self.meeting_service:
            zoom.DestroyMeetingService(self.meeting_service)
            print("Destroyed Meeting service")
        if self.setting_service:
            zoom.DestroySettingService(self.setting_service)
            print("Destroyed Setting service")
        if self.auth_service:
            zoom.DestroyAuthService(self.auth_service)
            print("Destroyed Auth service")

        if self.audio_helper:
            audio_helper_unsubscribe_result = self.audio_helper.unSubscribe()
            print("audio_helper.unSubscribe() returned", audio_helper_unsubscribe_result)

        print("CleanUPSDK() called")
        zoom.CleanUPSDK()
        print("CleanUPSDK() finished")

    def init(self):
        init_param = zoom.InitParam()

        init_param.strWebDomain = "https://zoom.us"
        init_param.strSupportUrl = "https://zoom.us"
        init_param.enableGenerateDump = True
        init_param.emLanguageID = zoom.SDK_LANGUAGE_ID.LANGUAGE_English
        init_param.enableLogByDefault = True

        init_sdk_result = zoom.InitSDK(init_param)
        if init_sdk_result != zoom.SDKERR_SUCCESS:
            raise Exception('InitSDK failed')
        
        self.create_services()

    def on_join(self):
        self.meeting_reminder_event = zoom.MeetingReminderEventCallbacks(onReminderNotifyCallback=self.on_reminder_notify)
        self.reminder_controller = self.meeting_service.GetMeetingReminderController()
        self.reminder_controller.SetEvent(self.meeting_reminder_event)

        if self.use_raw_recording:
            self.recording_ctrl = self.meeting_service.GetMeetingRecordingController()

            def on_recording_privilege_changed(can_rec):
                print("on_recording_privilege_changed called. can_record =", can_rec)
                if can_rec:
                    self.start_raw_recording()
                else:
                    self.stop_raw_recording()

            self.recording_event = zoom.MeetingRecordingCtrlEventCallbacks(onRecordPrivilegeChangedCallback=on_recording_privilege_changed)
            self.recording_ctrl.SetEvent(self.recording_event)

            self.start_raw_recording()

        self.participants_ctrl = self.meeting_service.GetMeetingParticipantsController()
        self.my_participant_id = self.participants_ctrl.GetMySelfUser().GetUserID()

    def on_mic_initialize_callback(self, sender):
        self.audio_raw_data_sender = sender

    def on_mic_start_send_callback(self):
        return
        with open('test_audio_16778240.pcm', 'rb') as pcm_file:
            chunk = pcm_file.read(64000*10)
            self.audio_raw_data_sender.send(chunk, 32000, zoom.ZoomSDKAudioChannel_Mono)

    def on_one_way_audio_raw_data_received_callback(self, data, node_id):
        if node_id == self.my_participant_id:
            return

        buffer_bytes = data.GetBuffer()
        numpy_buffer_bytes = np.frombuffer(buffer_bytes, dtype=np.int16)
        current_time = datetime.utcnow()
        if self.timeline_start is None:
            self.timeline_start = current_time
        volume = normalized_rms_audio(numpy_buffer_bytes)
        audio_is_silent = volume <= self.SILENCE_THRESHOLD
        
        # Initialize buffer and timing for new speaker
        if node_id not in self.speaker_buffers:
            if audio_is_silent:
                return
            self.speaker_buffers[node_id] = deque(maxlen=self.BUFFER_SIZE_LIMIT // 2)
            self.first_nonsilent_audio_time[node_id] = current_time
            self.last_nonsilent_audio_time[node_id] = current_time

        # Add new audio data to buffer
        self.speaker_buffers[node_id].extend(numpy_buffer_bytes)
        
        should_flush = False
        reason = None

        # Check buffer size
        if len(self.speaker_buffers[node_id]) >= self.BUFFER_SIZE_LIMIT // 2:
            should_flush = True
            reason = "buffer_full"
        
        # Check for silence
        if audio_is_silent:
            silence_duration = (current_time - self.last_nonsilent_audio_time[node_id]).total_seconds()
            print(f"silence_duration = {silence_duration}")
            if silence_duration >= self.SILENCE_DURATION_LIMIT:
                should_flush = True
                reason = "silence_limit"
        else:
            self.last_nonsilent_audio_time[node_id] = current_time

        # Flush buffer if needed
        if should_flush and len(self.speaker_buffers[node_id]) > 0:
            speaker_object = self.participants_ctrl.GetUserByUserID(node_id)
            self.send_message_callback({
                'message': self.Messages.NEW_UTTERANCE,
                'participant_uuid': node_id,
                'participant_user_uuid': speaker_object.GetPersistentId(),
                'participant_full_name': speaker_object.GetUserName(),
                'audio_data': np.array(self.speaker_buffers[node_id], dtype=np.int16).tobytes(),
                'timeline_ms': int((self.first_nonsilent_audio_time[node_id] - self.timeline_start).total_seconds() * 1000 + 
                                 (self.first_nonsilent_audio_time[node_id].microsecond - self.timeline_start.microsecond) / 1000),
                'flush_reason': reason
            })
            # Clear the buffer
            del self.speaker_buffers[node_id]
            del self.first_nonsilent_audio_time[node_id]
            del self.last_nonsilent_audio_time[node_id]

    def write_to_deepgram(self, data):
        try:
            buffer_bytes = data.GetBuffer()
            #self.deepgram_transcriber.send(buffer_bytes)
        except IOError as e:
            print(f"Error: failed to open or write to audio file path: {path}. Error: {e}")
            return
        except Exception as e:
            print(f"Unexpected error occurred: {e}")
            return

    def write_to_file(self, path, data):
        try:
            buffer_bytes = data.GetBuffer()          

            with open(path, 'ab') as file:
                file.write(buffer_bytes)
        except IOError as e:
            print(f"Error: failed to open or write to audio file path: {path}. Error: {e}")
            return
        except Exception as e:
            print(f"Unexpected error occurred: {e}")
            return

    def start_raw_recording(self):
        self.recording_ctrl = self.meeting_service.GetMeetingRecordingController()

        can_start_recording_result = self.recording_ctrl.CanStartRawRecording()
        if can_start_recording_result != zoom.SDKERR_SUCCESS:
            self.recording_ctrl.RequestLocalRecordingPrivilege()
            print("Requesting recording privilege.")
            return

        start_raw_recording_result = self.recording_ctrl.StartRawRecording()
        if start_raw_recording_result != zoom.SDKERR_SUCCESS:
            print("Start raw recording failed.")
            return

        self.audio_helper = zoom.GetAudioRawdataHelper()
        if self.audio_helper is None:
            print("audio_helper is None")
            return
        
        if self.audio_source is None:
            self.audio_source = zoom.ZoomSDKAudioRawDataDelegateCallbacks(onOneWayAudioRawDataReceivedCallback=self.on_one_way_audio_raw_data_received_callback)


        audio_helper_subscribe_result = self.audio_helper.subscribe(self.audio_source, False)
        print("audio_helper_subscribe_result =",audio_helper_subscribe_result)

        self.virtual_audio_mic_event_passthrough = zoom.ZoomSDKVirtualAudioMicEventCallbacks(onMicInitializeCallback=self.on_mic_initialize_callback,onMicStartSendCallback=self.on_mic_start_send_callback)
        audio_helper_set_external_audio_source_result = self.audio_helper.setExternalAudioSource(self.virtual_audio_mic_event_passthrough)
        print("audio_helper_set_external_audio_source_result =", audio_helper_set_external_audio_source_result)
        if audio_helper_set_external_audio_source_result != zoom.SDKERR_SUCCESS:
            print("Failed to set external audio source")
            return
        self.send_message_callback({'message': self.Messages.BOT_RECORDING_PERMISSION_GRANTED})

    def stop_raw_recording(self):
        rec_ctrl = self.meeting_service.StopRawRecording()
        if rec_ctrl.StopRawRecording() != zoom.SDKERR_SUCCESS:
            raise Exception("Error with stop raw recording")

    def leave(self):
        if self.meeting_service is None:
            return
        
        status = self.meeting_service.GetMeetingStatus()
        if status == zoom.MEETING_STATUS_IDLE:
            return

        self.meeting_service.Leave(zoom.LEAVE_MEETING)


    def join_meeting(self):
        display_name = "My meeting bot"

        meeting_number = int(self.meeting_id)

        join_param = zoom.JoinParam()
        join_param.userType = zoom.SDKUserType.SDK_UT_WITHOUT_LOGIN

        param = join_param.param
        param.meetingNumber = meeting_number
        param.userName = display_name
        param.psw = self.meeting_password
        param.vanityID = ""
        param.customer_key = ""
        param.webinarToken = ""
        param.isVideoOff = False
        param.isAudioOff = False

        join_result = self.meeting_service.Join(join_param)
        print("join_result =",join_result)

        self.audio_settings = self.setting_service.GetAudioSettings()
        self.audio_settings.EnableAutoJoinAudio(True)

    def on_reminder_notify(self, content, handler):
        if handler:
            handler.accept()

    def auth_return(self, result):
        if result == zoom.AUTHRET_SUCCESS:
            print("Auth completed successfully.")
            return self.join_meeting()

        raise Exception("Failed to authorize. result =", result)
    
    def meeting_status_changed(self, status, iResult):
        print("meeting_status_changed called. status =",status,"iResult=",iResult)

        if status == zoom.MEETING_STATUS_WAITINGFORHOST:
            self.send_message_callback({'message': self.Messages.LEAVE_MEETING_WAITING_FOR_HOST})

        if status == zoom.MEETING_STATUS_IN_WAITING_ROOM:
            self.send_message_callback({'message': self.Messages.BOT_PUT_IN_WAITING_ROOM})

        if status == zoom.MEETING_STATUS_INMEETING:
            self.send_message_callback({'message': self.Messages.BOT_JOINED_MEETING})

        if status == zoom.MEETING_STATUS_ENDED:
            self.send_message_callback({'message': self.Messages.MEETING_ENDED})


        if status == zoom.MEETING_STATUS_INMEETING:
            return self.on_join()
        

    def create_services(self):
        self.meeting_service = zoom.CreateMeetingService()
        
        self.setting_service = zoom.CreateSettingService()

        self.meeting_service_event = zoom.MeetingServiceEventCallbacks(onMeetingStatusChangedCallback=self.meeting_status_changed)
                
        meeting_service_set_revent_result = self.meeting_service.SetEvent(self.meeting_service_event)
        if meeting_service_set_revent_result != zoom.SDKERR_SUCCESS:
            raise Exception("Meeting Service set event failed")
        
        self.auth_event = zoom.AuthServiceEventCallbacks(onAuthenticationReturnCallback=self.auth_return)

        self.auth_service = zoom.CreateAuthService()

        set_event_result = self.auth_service.SetEvent(self.auth_event)
        print("set_event_result =",set_event_result)
    
        # Use the auth service
        auth_context = zoom.AuthContext()
        auth_context.jwt_token = self._jwt_token

        result = self.auth_service.SDKAuth(auth_context)
    
        if result == zoom.SDKError.SDKERR_SUCCESS:
            print("Authentication successful")
        else:
            print("Authentication failed with error:", result)