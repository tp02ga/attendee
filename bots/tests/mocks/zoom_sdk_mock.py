import types

# Mock Zoom SDK constants and enums
SDKERR_SUCCESS = 0
AUTHRET_SUCCESS = 0
SDK_LANGUAGE_ID = types.SimpleNamespace()
SDK_LANGUAGE_ID.LANGUAGE_English = 0

SDKUserType = types.SimpleNamespace()
SDKUserType.SDK_UT_WITHOUT_LOGIN = 1

MEETING_STATUS_IDLE = 0
MEETING_STATUS_CONNECTING = 1
MEETING_STATUS_WAITINGFORHOST = 2
MEETING_STATUS_INMEETING = 3
MEETING_STATUS_DISCONNECTING = 4
MEETING_STATUS_ENDED = 5
MEETING_STATUS_FAILED = 6
MEETING_STATUS_IN_WAITING_ROOM = 7
MEETING_STATUS_RECONNECTING = 8
MEETING_STATUS_LOCKED = 9

LEAVE_MEETING = 0

class InitParam:
    def __init__(self):
        self.strWebDomain = None
        self.strSupportUrl = None
        self.enableGenerateDump = None
        self.emLanguageID = None
        self.enableLogByDefault = None

class AuthContext:
    def __init__(self):
        self.jwt_token = None

class JoinParam:
    def __init__(self):
        self.userType = None
        self.param = types.SimpleNamespace()
        self.param.meetingNumber = None
        self.param.userName = None
        self.param.psw = None
        self.param.vanityID = ""
        self.param.customer_key = ""
        self.param.webinarToken = ""
        self.param.isVideoOff = False
        self.param.isAudioOff = False

class MockMeetingService:
    def __init__(self):
        self._status = MEETING_STATUS_IDLE
        self._event = None
        
    def SetEvent(self, event):
        self._event = event
        return SDKERR_SUCCESS

    def Join(self, join_param):
        # Simulate joining process
        self._status = MEETING_STATUS_CONNECTING
        if self._event:
            self._event.onMeetingStatusChangedCallback(self._status, SDKERR_SUCCESS)
            
        # Simulate successful join
        self._status = MEETING_STATUS_INMEETING
        if self._event:
            self._event.onMeetingStatusChangedCallback(self._status, SDKERR_SUCCESS)
        return SDKERR_SUCCESS

    def GetMeetingStatus(self):
        return self._status

    def Leave(self, leave_type):
        self._status = MEETING_STATUS_IDLE
        if self._event:
            self._event.onMeetingStatusChangedCallback(MEETING_STATUS_ENDED, SDKERR_SUCCESS)
        return SDKERR_SUCCESS

class MockAuthService:
    def __init__(self):
        self._event = None

    def SetEvent(self, event):
        self._event = event
        return SDKERR_SUCCESS

    def SDKAuth(self, auth_context):
        if self._event:
            self._event.onAuthenticationReturnCallback(AUTHRET_SUCCESS)
        return SDKERR_SUCCESS

class MockSettingService:
    def GetAudioSettings(self):
        return types.SimpleNamespace(
            EnableAutoJoinAudio=lambda x: None
        )

def InitSDK(param):
    return SDKERR_SUCCESS

def CreateMeetingService():
    return MockMeetingService()

def CreateSettingService():
    return MockSettingService()

def CreateAuthService():
    return MockAuthService()

def CleanUPSDK():
    pass

def DestroyMeetingService(service):
    pass

def DestroySettingService(service):
    pass

def DestroyAuthService(service):
    pass 