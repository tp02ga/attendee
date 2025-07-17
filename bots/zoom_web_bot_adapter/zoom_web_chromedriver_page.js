ZoomMtg.preLoadWasm()
ZoomMtg.prepareWebSDK()

var zoomInitialData = window.zoomInitialData;

var authEndpoint = ''
var sdkKey = zoomInitialData.sdkKey;
var meetingNumber = zoomInitialData.meetingNumber;
var passWord = zoomInitialData.meetingPassword;
var role = 0
var userName = 'Zoom Web Bot'
var userEmail = ''
var registrantToken = ''
var zakToken = ''
var leaveUrl = 'https://zoom.us'
var registrantToken = ''
var zakToken = ''

function joinMeeting() {
    const signature = zoomInitialData.signature;
    startMeeting(signature);
}

<div class="join-audio-by-voip"><button tabindex="0" type="button" class="zm-btn join-audio-by-voip__join-btn zm-btn--primary zm-btn__outline--white zm-btn--lg" aria-label="">Join Audio by Computer<span class="loading" style="display: none;"></span></button></div>

function startMeeting(signature) {

  document.getElementById('zmmtg-root').style.display = 'block'

    ZoomMtg.init({
    leaveUrl: leaveUrl,
    patchJsMedia: true,
    leaveOnPageUnload: true,
    disableZoomLogo: true,
    disablePreview: true,
    //disableJoinAudio: true,
    //isSupportAV: false,
    success: (success) => {
        console.log(success)
        ZoomMtg.join({
        signature: signature,
        sdkKey: sdkKey,
        meetingNumber: meetingNumber,
        passWord: passWord,
        userName: userName,
        userEmail: userEmail,
        tk: registrantToken,
        zak: zakToken,
        success: (success) => {
            console.log(success)
        },
        error: (error) => {
            console.log(error)
        },
        })
    },
    error: (error) => {
        console.log(error)
    }
    })

    ZoomMtg.inMeetingServiceListener('onJoinSpeed', function (data) {
        console.log('onJoinSpeed', data);
    });

    ZoomMtg.inMeetingServiceListener('onMeetingStatus', function (data) {
        console.log('onMeetingStatus', data);
    });

    ZoomMtg.inMeetingServiceListener('onReceiveTranscriptionMsg', function (data) {
    console.log('onReceiveTranscriptionMsg', data);
    });

    ZoomMtg.inMeetingServiceListener('onReceiveChatMsg', function (data) {
    console.log('onReceiveChatMsg', data);
    });

    ZoomMtg.inMeetingServiceListener('onUserJoin', function (data) {
    console.log('onUserJoin', data);
    });

    ZoomMtg.inMeetingServiceListener('onUserLeave', function (data) {
    console.log('onUserLeave', data);
    // reasonCode Return the reason the current user left.
    const reasonCode = {
        OTHER: 0, // Other reason.
        HOST_ENDED_MEETING: 1, // Host ended the meeting.
        SELF_LEAVE_FROM_IN_MEETING: 2, // User (self) left from being in the meeting.
        SELF_LEAVE_FROM_WAITING_ROOM: 3, // User (self) left from the waiting room.
        SELF_LEAVE_FROM_WAITING_FOR_HOST_START: 4, // User (self) left from waiting for host to start the meeting.
        MEETING_TRANSFER: 5, // The meeting was transferred to another end to open.
        KICK_OUT_FROM_MEETING: 6, // Removed from meeting by host or co-host.
        KICK_OUT_FROM_WAITING_ROOM: 7, // Removed from waiting room by host or co-host.
        LEAVE_FROM_DISCLAIMER: 8, // User click cancel in disclaimer dialog 
    };

    });

    ZoomMtg.inMeetingServiceListener('onUserUpdate', function (data) {
    console.log('onUserUpdate', data);
    });
}

// When dom loads call the joinMeeting function
document.addEventListener('DOMContentLoaded', joinMeeting);

function leaveMeeting() {
    ZoomMtg.leaveMeeting({});
}