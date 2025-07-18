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

function startMeeting(signature) {

  document.getElementById('zmmtg-root').style.display = 'block'

    ZoomMtg.init({
    leaveUrl: leaveUrl,
    patchJsMedia: true,
    leaveOnPageUnload: true,
    disableZoomLogo: true,
    disablePreview: true,
    //isSupportCC: true,
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
            console.log(success);
            /*
            We don't need to do this because user events include the self attribute.
            ZoomMtg.getCurrentUser({
                success: (currentUser) => {
                    console.log('ZoomMtg.getCurrentUser()', currentUser);
                    currentUser = currentUser.result.currentUser;
                },
                error: (error) => {
                    console.log('ZoomMtg.getCurrentUser() error', error);
                }
            })
            */
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

    ZoomMtg.inMeetingServiceListener('onReceiveTranscriptionMsg', function (item) {
        console.log('onReceiveTranscriptionMsg', item);

        const itemConverted = {
            deviceId: item.userId,
            captionId: item.msgId,
            text: item.text,
            isFinal: !!item.done
        };
        
        window.ws.sendClosedCaptionUpdate(itemConverted);
    });

    ZoomMtg.inMeetingServiceListener('onReceiveChatMsg', function (data) {
    console.log('onReceiveChatMsg', data);
    });

    ZoomMtg.inMeetingServiceListener('onUserJoin', function (data) {
        console.log('onUserJoin', data);
        if (!data.userId) {
            console.log('onUserJoin: no userId, skipping');
            return;
        }
        const dataWithState = {
            ...data,
            state: 'active'
        }
        window.userManager.singleUserSynced(dataWithState);
    });

    ZoomMtg.inMeetingServiceListener('onUserLeave', function (data) {
        console.log('onUserLeave', data);
        if (!data.userId) {
            console.log('onUserLeave: no userId, skipping');
            return;
        }
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

        const dataWithState = {
            ...data,
            state: 'inactive'
        }
        window.userManager.singleUserSynced(dataWithState);
    });

    ZoomMtg.inMeetingServiceListener('onUserUpdate', function (data) {
        console.log('onUserUpdate', data);
        if (!data.userId) {
            console.log('onUserUpdate: no userId, skipping');
            return;
        }
        const dataWithState = {
            ...data,
            state: 'active'
        }
        window.userManager.singleUserSynced(dataWithState);
    });
}

function leaveMeeting() {
    ZoomMtg.leaveMeeting({});
}