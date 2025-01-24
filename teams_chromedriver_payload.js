// Video track manager
class VideoTrackManager {
    constructor(ws) {
        this.videoTracks = new Map();
        this.ws = ws;
        this.trackToSendCache = null;
    }

    deleteVideoTrack(videoTrack) {
        this.videoTracks.delete(videoTrack.id);
        this.trackToSendCache = null;
    }

    upsertVideoTrack(videoTrack, streamId, isScreenShare) {
        const existingVideoTrack = this.videoTracks.get(videoTrack.id);

        // Create new object with track info and firstSeenAt timestamp
        const trackInfo = {
            originalTrack: videoTrack,
            isScreenShare: isScreenShare,
            firstSeenAt: existingVideoTrack ? existingVideoTrack.firstSeenAt : Date.now(),
            streamId: streamId
        };
 
        console.log('upsertVideoTrack for', videoTrack.id, '=', trackInfo);
        
        this.videoTracks.set(videoTrack.id, trackInfo);
        this.trackToSendCache = null;
    }

    getStreamIdToSendCached() {
        return this.getTrackToSendCached()?.streamId;
    }

    getTrackToSendCached() {
        if (this.trackToSendCache) {
            return this.trackToSendCache;
        }

        this.trackToSendCache = this.getTrackToSend();
        return this.trackToSendCache;
    }

    getTrackToSend() {
        const screenShareTracks = Array.from(this.videoTracks.values()).filter(track => track.isScreenShare);
        const mostRecentlyCreatedScreenShareTrack = screenShareTracks.reduce((max, track) => {
            return track.firstSeenAt > max.firstSeenAt ? track : max;
        }, screenShareTracks[0]);

        if (mostRecentlyCreatedScreenShareTrack) {
            return mostRecentlyCreatedScreenShareTrack;
        }

        const nonScreenShareTracks = Array.from(this.videoTracks.values()).filter(track => !track.isScreenShare);
        const mostRecentlyCreatedNonScreenShareTrack = nonScreenShareTracks.reduce((max, track) => {
            return track.firstSeenAt > max.firstSeenAt ? track : max;
        }, nonScreenShareTracks[0]);

        if (mostRecentlyCreatedNonScreenShareTrack) {
            return mostRecentlyCreatedNonScreenShareTrack;
        }

        return null;
    }
}

// Caption manager
class CaptionManager {
    constructor(ws) {
        this.captions = new Map();
        this.ws = ws;
    }

    singleCaptionSynced(caption) {
        this.captions.set(caption.captionId, caption);
        this.ws.sendJson({
            type: 'CaptionUpdate',
            caption: caption
        });
    }
}

const DEVICE_OUTPUT_TYPE = {
    AUDIO: 1,
    VIDEO: 2
}

// User manager
class UserManager {
    constructor(ws) {
        this.allUsersMap = new Map();
        this.currentUsersMap = new Map();
        this.deviceOutputMap = new Map();

        this.ws = ws;
    }


    getDeviceOutput(deviceId, outputType) {
        return this.deviceOutputMap.get(`${deviceId}-${outputType}`);
    }

    updateDeviceOutputs(deviceOutputs) {
        for (const output of deviceOutputs) {
            const key = `${output.deviceId}-${output.deviceOutputType}`; // Unique key combining device ID and output type

            const deviceOutput = {
                deviceId: output.deviceId,
                outputType: output.deviceOutputType, // 1 = audio, 2 = video
                streamId: output.streamId,
                disabled: output.deviceOutputStatus.disabled,
                lastUpdated: Date.now()
            };

            this.deviceOutputMap.set(key, deviceOutput);
        }

        // Notify websocket clients about the device output update
        this.ws.sendJson({
            type: 'DeviceOutputsUpdate',
            deviceOutputs: Array.from(this.deviceOutputMap.values())
        });
    }

    getUserByDeviceId(deviceId) {
        return this.allUsersMap.get(deviceId);
    }

    // constants for meeting status
    MEETING_STATUS = {
        IN_MEETING: 1,
        NOT_IN_MEETING: 6
    }

    getCurrentUsersInMeeting() {
        return Array.from(this.currentUsersMap.values()).filter(user => user.status === this.MEETING_STATUS.IN_MEETING);
    }

    getCurrentUsersInMeetingWhoAreScreenSharing() {
        return this.getCurrentUsersInMeeting().filter(user => user.parentDeviceId);
    }

    singleUserSynced(user) {
      // Create array with new user and existing users, then filter for unique deviceIds
      // keeping the first occurrence (new user takes precedence)
      const allUsers = [...this.currentUsersMap.values(), user];
      const uniqueUsers = Array.from(
        new Map(allUsers.map(user => [user.deviceId, user])).values()
      );
      this.newUsersListSynced(uniqueUsers);
    }

    newUsersListSynced(newUsersListRaw) {
        const newUsersList = newUsersListRaw.map(user => {
            const userStatusMap = {
                1: 'in_meeting',
                6: 'not_in_meeting',
                7: 'removed_from_meeting'
            }

            return {
                ...user,
                humanized_status: userStatusMap[user.status] || "unknown"
            }
        })
        // Get the current user IDs before updating
        const previousUserIds = new Set(this.currentUsersMap.keys());
        const newUserIds = new Set(newUsersList.map(user => user.deviceId));
        const updatedUserIds = new Set([])

        // Update all users map
        for (const user of newUsersList) {
            if (previousUserIds.has(user.deviceId) && JSON.stringify(this.currentUsersMap.get(user.deviceId)) !== JSON.stringify(user)) {
                updatedUserIds.add(user.deviceId);
            }

            this.allUsersMap.set(user.deviceId, {
                deviceId: user.deviceId,
                displayName: user.displayName,
                fullName: user.fullName,
                profile: user.profile,
                status: user.status,
                humanized_status: user.humanized_status,
                parentDeviceId: user.parentDeviceId
            });
        }

        // Calculate new, removed, and updated users
        const newUsers = newUsersList.filter(user => !previousUserIds.has(user.deviceId));
        const removedUsers = Array.from(previousUserIds)
            .filter(id => !newUserIds.has(id))
            .map(id => this.currentUsersMap.get(id));

        // Clear current users map and update with new list
        this.currentUsersMap.clear();
        for (const user of newUsersList) {
            this.currentUsersMap.set(user.deviceId, {
                deviceId: user.deviceId,
                displayName: user.displayName,
                fullName: user.fullName,
                profilePicture: user.profilePicture,
                status: user.status,
                humanized_status: user.humanized_status,
                parentDeviceId: user.parentDeviceId
            });
        }

        const updatedUsers = Array.from(updatedUserIds).map(id => this.currentUsersMap.get(id));

        if (newUsers.length > 0 || removedUsers.length > 0 || updatedUsers.length > 0) {
            this.ws.sendJson({
                type: 'UsersUpdate',
                newUsers: newUsers,
                removedUsers: removedUsers,
                updatedUsers: updatedUsers
            });
        }
    }
}

// Websocket client
class WebSocketClient {
  // Message types
  static MESSAGE_TYPES = {
      JSON: 1,
      VIDEO: 2,  // Reserved for future use
      AUDIO: 3   // Reserved for future use
  };

  constructor() {
      const url = `ws://localhost:8097`;
      console.log('WebSocketClient url', url);
      this.ws = new WebSocket(url);
      this.ws.binaryType = 'arraybuffer';
      
      this.ws.onopen = () => {
          console.log('WebSocket Connected');
      };
      
      this.ws.onmessage = (event) => {
          this.handleMessage(event.data);
      };
      
      this.ws.onerror = (error) => {
          console.error('WebSocket Error:', error);
      };
      
      this.ws.onclose = () => {
          console.log('WebSocket Disconnected');
      };

      this.mediaSendingEnabled = false;
      this.lastVideoFrameTime = performance.now();
      this.blackFrameInterval = null;
  }

  startBlackFrameTimer() {
    if (this.blackFrameInterval) return; // Don't start if already running
    
    this.blackFrameInterval = setInterval(() => {
        try {
            const currentTime = performance.now();
            if (currentTime - this.lastVideoFrameTime >= 500 && this.mediaSendingEnabled) {
                // Create black frame data (I420 format)
                const width = 1920, height = 1080;
                const yPlaneSize = width * height;
                const uvPlaneSize = (width * height) / 4;
                
                const frameData = new Uint8Array(yPlaneSize + 2 * uvPlaneSize);
                // Y plane (black = 0)
                frameData.fill(0, 0, yPlaneSize);
                // U and V planes (black = 128)
                frameData.fill(128, yPlaneSize);
                
                // Fix: Math.floor() the milliseconds before converting to BigInt
                const currentTimeMicros = BigInt(Math.floor(currentTime) * 1000);
                this.sendVideo(currentTimeMicros, '0', width, height, frameData);
            }
        } catch (error) {
            console.error('Error in black frame timer:', error);
        }
    }, 250);
  }

    stopBlackFrameTimer() {
        if (this.blackFrameInterval) {
            clearInterval(this.blackFrameInterval);
            this.blackFrameInterval = null;
        }
    }

  enableMediaSending() {
    this.mediaSendingEnabled = true;
    this.startBlackFrameTimer();
  }

  disableMediaSending() {
    this.mediaSendingEnabled = false;
    this.stopBlackFrameTimer();
  }

  handleMessage(data) {
      const view = new DataView(data);
      const messageType = view.getInt32(0, true); // true for little-endian
      
      // Handle different message types
      switch (messageType) {
          case WebSocketClient.MESSAGE_TYPES.JSON:
              const jsonData = new TextDecoder().decode(new Uint8Array(data, 4));
              console.log('Received JSON message:', JSON.parse(jsonData));
              break;
          // Add future message type handlers here
          default:
              console.warn('Unknown message type:', messageType);
      }
  }
  
  sendJson(data) {
      if (this.ws.readyState !== WebSocket.OPEN) {
          console.error('WebSocket is not connected');
          return;
      }

      try {
          // Convert JSON to string then to Uint8Array
          const jsonString = JSON.stringify(data);
          const jsonBytes = new TextEncoder().encode(jsonString);
          
          // Create final message: type (4 bytes) + json data
          const message = new Uint8Array(4 + jsonBytes.length);
          
          // Set message type (1 for JSON)
          new DataView(message.buffer).setInt32(0, WebSocketClient.MESSAGE_TYPES.JSON, true);
          
          // Copy JSON data after type
          message.set(jsonBytes, 4);
          
          // Send the binary message
          this.ws.send(message.buffer);
      } catch (error) {
          console.error('Error sending WebSocket message:', error);
          console.error('Message data:', data);
      }
  }

  

  sendAudio(timestamp, audioData) {
      if (this.ws.readyState !== WebSocket.OPEN) {
          //console.error('WebSocket is not connected for audio send', this.ws.readyState);
          return;
      }


      if (!this.mediaSendingEnabled) {
        return;
      }

      try {
          // Create final message: type (4 bytes) + timestamp (8 bytes) + audio data
          const message = new Uint8Array(4 + 8 + audioData.buffer.byteLength);
          const dataView = new DataView(message.buffer);
          
          // Set message type (3 for AUDIO)
          dataView.setInt32(0, WebSocketClient.MESSAGE_TYPES.AUDIO, true);
          
          // Set timestamp as BigInt64
          dataView.setBigInt64(4, BigInt(timestamp), true);

          // Copy audio data after type and timestamp
          message.set(new Uint8Array(audioData.buffer), 12);
          
          // Send the binary message
          this.ws.send(message.buffer);
      } catch (error) {
          console.error('Error sending WebSocket audio message:', error);
      }
  }

  sendVideo(timestamp, streamId, width, height, videoData) {
      if (this.ws.readyState !== WebSocket.OPEN) {
          console.error('WebSocket is not connected for video send', this.ws.readyState);
          return;
      }

      if (!this.mediaSendingEnabled) {
        return;
      }
      
      this.lastVideoFrameTime = performance.now();

      try {
          // Convert streamId to UTF-8 bytes
          const streamIdBytes = new TextEncoder().encode(streamId);
          
          // Create final message: type (4 bytes) + timestamp (8 bytes) + streamId length (4 bytes) + 
          // streamId bytes + width (4 bytes) + height (4 bytes) + video data
          const message = new Uint8Array(4 + 8 + 4 + streamIdBytes.length + 4 + 4 + videoData.buffer.byteLength);
          const dataView = new DataView(message.buffer);
          
          // Set message type (2 for VIDEO)
          dataView.setInt32(0, WebSocketClient.MESSAGE_TYPES.VIDEO, true);
          
          // Set timestamp as BigInt64
          dataView.setBigInt64(4, BigInt(timestamp), true);

          // Set streamId length and bytes
          dataView.setInt32(12, streamIdBytes.length, true);
          message.set(streamIdBytes, 16);

          // Set width and height
          const streamIdOffset = 16 + streamIdBytes.length;
          dataView.setInt32(streamIdOffset, width, true);
          dataView.setInt32(streamIdOffset + 4, height, true);

          // Copy video data after headers
          message.set(new Uint8Array(videoData.buffer), streamIdOffset + 8);
          
          // Send the binary message
          this.ws.send(message.buffer);
      } catch (error) {
          console.error('Error sending WebSocket video message:', error);
      }
  }
}

// Interceptors

class FetchInterceptor {
    constructor(responseCallback) {
        this.originalFetch = window.fetch;
        this.responseCallback = responseCallback;
        window.fetch = (...args) => this.interceptFetch(...args);
    }

    async interceptFetch(...args) {
        try {
            // Call the original fetch
            const response = await this.originalFetch.apply(window, args);
            
            // Clone the response since it can only be consumed once
            const clonedResponse = response.clone();
            
            // Call the callback with the cloned response
            await this.responseCallback(clonedResponse);
            
            // Return the original response to maintain normal flow
            return response;
        } catch (error) {
            console.error('Error in intercepted fetch:', error);
            throw error;
        }
    }
}
class RTCInterceptor {
    constructor(callbacks) {
        // Store the original RTCPeerConnection
        const originalRTCPeerConnection = window.RTCPeerConnection;
        
        // Store callbacks
        const onPeerConnectionCreate = callbacks.onPeerConnectionCreate || (() => {});
        const onDataChannelCreate = callbacks.onDataChannelCreate || (() => {});
        
        // Override the RTCPeerConnection constructor
        window.RTCPeerConnection = function(...args) {
            // Create instance using the original constructor
            const peerConnection = Reflect.construct(
                originalRTCPeerConnection, 
                args
            );
            
            // Notify about the creation
            onPeerConnectionCreate(peerConnection);
            
            // Override createDataChannel
            const originalCreateDataChannel = peerConnection.createDataChannel.bind(peerConnection);
            peerConnection.createDataChannel = (label, options) => {
                const dataChannel = originalCreateDataChannel(label, options);
                onDataChannelCreate(dataChannel, peerConnection);
                return dataChannel;
            };
            
            // Intercept createOffer
            const originalCreateOffer = peerConnection.createOffer.bind(peerConnection);
            peerConnection.createOffer = async function(options) {
                const offer = await originalCreateOffer(options);
                console.log('Created Offer SDP:', {
                    type: offer.type,
                    sdp: offer.sdp,
                    parsedSDP: parseSDP(offer.sdp)
                });
                return offer;
            };

            // Intercept createAnswer
            const originalCreateAnswer = peerConnection.createAnswer.bind(peerConnection);
            peerConnection.createAnswer = async function(options) {
                const answer = await originalCreateAnswer(options);
                console.log('Created Answer SDP:', {
                    type: answer.type,
                    sdp: answer.sdp,
                    parsedSDP: parseSDP(answer.sdp)
                });
                return answer;
            };
       
            

/*

how the mapping works:
the SDP contains x-source-streamid:<some value>
this corresponds to the stream id in the participants hash
So that correspondences allows us to map a participant stream to an SDP. But how do we go from SDP to the raw low level track id? 
The tracks have a streamId that looks like this mainVideo-39016. The SDP has that same streamId contained within it in the msid: header

{"sdp":"v=0\r\no=- 222351 0 IN IP4 127.0.0.1\r\ns=session\r\nc=IN IP4 172.172.100.250\r\nb=CT:10000000\r\nt=0 0\r\na=extmap-allow-mixed\r\na=msid-semantic: WMS *\r\na=group:BUNDLE 0 1 2 3 4 5 6 7 8 9 10 11 12\r\na=x-mediabw:applicationsharing-video send=8100;recv=8100\r\na=x-plaza-msi-range:3196-3295 3296-3395\r\nm=audio 3480 UDP/TLS/RTP/SAVPF 111 97 9 0 8 13 101\r\nc=IN IP4 172.172.100.250\r\na=rtpmap:111 OPUS/48000/2\r\na=rtpmap:97 RED/48000/2\r\na=rtpmap:9 G722/8000\r\na=rtpmap:0 PCMU/8000\r\na=rtpmap:8 PCMA/8000\r\na=rtpmap:13 CN/8000\r\na=rtpmap:101 telephone-event/8000\r\na=fmtp:101 0-16\r\na=fmtp:111 usedtx=1;useinbandfec=1\r\na=fmtp:97 111/111\r\na=rtcp:3480\r\na=rtcp-fb:111 transport-cc\r\na=extmap:2 http://www.webrtc.org/experiments/rtp-hdrext/abs-send-time\r\na=extmap:3 http://www.ietf.org/id/draft-holmer-rmcat-transport-wide-cc-extensions-01\r\na=setup:passive\r\na=mid:0\r\na=ptime:20\r\na=ice-ufrag:wmA+\r\na=ice-pwd:KQ5Zkcak+RPw2GY98PNWN7Bu\r\na=fingerprint:sha-256 DA:93:54:F4:88:DA:6D:8D:57:43:C2:A1:A7:77:CA:96:9A:60:DA:63:F0:9E:4E:D2:4E:24:16:69:74:AC:39:ED\r\na=candidate:1 1 UDP 54001663 172.172.100.250 3480 typ relay raddr 10.0.129.40 rport 3480\r\na=candidate:3 1 tcp 18087935 172.172.100.250 3478 typ relay raddr 10.0.129.40 rport 3478 tcptype passive\r\na=ssrc:38915 cname:1d3cac01687b45bdbe99ddf3685db9df\r\na=ssrc:38915 msid:mainAudio-38915 mainAudio-38915\r\na=rtcp-mux\r\na=x-source-streamid:3396\r\nm=video 3480 UDP/TLS/RTP/SAVPF 107 99\r\nc=IN IP4 172.172.100.250\r\nb=AS:3920\r\na=rtpmap:107 H264/90000\r\na=rtpmap:99 rtx/90000\r\na=fmtp:107 packetization-mode=1;profile-level-id=42C02A\r\na=fmtp:99 apt=107\r\na=rtcp:3480\r\na=rtcp-fb:* nack\r\na=rtcp-fb:* nack pli\r\na=rtcp-fb:* goog-remb\r\na=rtcp-fb:* ccm fir\r\na=rtcp-fb:* transport-cc\r\na=extmap:2 http://www.webrtc.org/experiments/rtp-hdrext/abs-send-time\r\na=extmap:3 http://www.ietf.org/id/draft-holmer-rmcat-transport-wide-cc-extensions-01\r\na=extmap:4 urn:ietf:params:rtp-hdrext:sdes:mid\r\na=extmap:10 urn:ietf:params:rtp-hdrext:sdes:rtp-stream-id\r\na=extmap:11 urn:ietf:params:rtp-hdrext:sdes:repaired-rtp-stream-id\r\na=extmap:9 http://www.webrtc.org/experiments/rtp-hdrext/video-layers-allocation00\r\na=setup:passive\r\na=mid:1\r\na=ice-ufrag:wmA+\r\na=ice-pwd:KQ5Zkcak+RPw2GY98PNWN7Bu\r\na=fingerprint:sha-256 DA:93:54:F4:88:DA:6D:8D:57:43:C2:A1:A7:77:CA:96:9A:60:DA:63:F0:9E:4E:D2:4E:24:16:69:74:AC:39:ED\r\na=ssrc:38916 cname:1d3cac01687b45bdbe99ddf3685db9df\r\na=ssrc:38916 msid:mainVideo-38916 mainVideo-38916\r\na=ssrc:38966 cname:1d3cac01687b45bdbe99ddf3685db9df\r\na=ssrc:38966 msid:mainVideo-38916 mainVideo-38916\r\na=ssrc-group:FID 38916 38966\r\na=rtcp-mux\r\na=rtcp-rsize\r\na=rid:1 recv\r\na=rid:2 recv\r\na=simulcast:recv ~1;~2\r\na=x-source-streamid:3397\r\nm=video 3480 UDP/TLS/RTP/SAVPF 107 99\r\nc=IN IP4 172.172.100.250\r\nb=AS:3920\r\na=rtpmap:107 H264/90000\r\na=rtpmap:99 rtx/90000\r\na=fmtp:107 packetization-mode=1;profile-level-id=42C02A\r\na=fmtp:99 apt=107\r\na=rtcp:3480\r\na=rtcp-fb:* nack\r\na=rtcp-fb:* nack pli\r\na=rtcp-fb:* goog-remb\r\na=rtcp-fb:* ccm fir\r\na=rtcp-fb:* transport-cc\r\na=extmap:2 http://www.webrtc.org/experiments/rtp-hdrext/abs-send-time\r\na=extmap:3 http://www.ietf.org/id/draft-holmer-rmcat-transport-wide-cc-extensions-01\r\na=extmap:4 urn:ietf:params:rtp-hdrext:sdes:mid\r\na=extmap:10 urn:ietf:params:rtp-hdrext:sdes:rtp-stream-id\r\na=extmap:11 urn:ietf:params:rtp-hdrext:sdes:repaired-rtp-stream-id\r\na=extmap:9 http://www.webrtc.org/experiments/rtp-hdrext/video-layers-allocation00\r\na=setup:passive\r\na=mid:2\r\na=sendonly\r\na=ice-ufrag:wmA+\r\na=ice-pwd:KQ5Zkcak+RPw2GY98PNWN7Bu\r\na=fingerprint:sha-256 DA:93:54:F4:88:DA:6D:8D:57:43:C2:A1:A7:77:CA:96:9A:60:DA:63:F0:9E:4E:D2:4E:24:16:69:74:AC:39:ED\r\na=ssrc:39016 cname:1d3cac01687b45bdbe99ddf3685db9df\r\na=ssrc:39016 msid:mainVideo-39016 mainVideo-39016\r\na=ssrc:39066 cname:1d3cac01687b45bdbe99ddf3685db9df\r\na=ssrc:39066 msid:mainVideo-39016 mainVideo-39016\r\na=ssrc-group:FID 39016 39066\r\na=rtcp-mux\r\na=rtcp-rsize\r\na=x-source-streamid:3398\r\nm=video 3480 UDP/TLS/RTP/SAVPF 107 99\r\nc=IN IP4 172.172.100.250\r\nb=AS:3920\r\na=rtpmap:107 H264/90000\r\na=rtpmap:99 rtx/90000\r\na=fmtp:107 packetization-mode=1;profile-level-id=42C02A\r\na=fmtp:99 apt=107\r\na=rtcp:3480\r\na=rtcp-fb:* nack\r\na=rtcp-fb:* nack pli\r\na=rtcp-fb:* goog-remb\r\na=rtcp-fb:* ccm fir\r\na=rtcp-fb:* transport-cc\r\na=extmap:2 http://www.webrtc.org/experiments/rtp-hdrext/abs-send-time\r\na=extmap:3 http://www.ietf.org/id/draft-holmer-rmcat-transport-wide-cc-extensions-01\r\na=extmap:4 urn:ietf:params:rtp-hdrext:sdes:mid\r\na=extmap:10 urn:ietf:params:rtp-hdrext:sdes:rtp-stream-id\r\na=extmap:11 urn:ietf:params:rtp-hdrext:sdes:repaired-rtp-stream-id\r\na=extmap:9 http://www.webrtc.org/experiments/rtp-hdrext/video-layers-allocation00\r\na=setup:passive\r\na=mid:3\r\na=sendonly\r\na=ice-ufrag:wmA+\r\na=ice-pwd:KQ5Zkcak+RPw2GY98PNWN7Bu\r\na=fingerprint:sha-256 DA:93:54:F4:88:DA:6D:8D:57:43:C2:A1:A7:77:CA:96:9A:60:DA:63:F0:9E:4E:D2:4E:24:16:69:74:AC:39:ED\r\na=ssrc:39116 cname:1d3cac01687b45bdbe99ddf3685db9df\r\na=ssrc:39116 msid:mainVideo-39116 mainVideo-39116\r\na=ssrc:39166 cname:1d3cac01687b45bdbe99ddf3685db9df\r\na=ssrc:39166 msid:mainVideo-39116 mainVideo-39116\r\na=ssrc-group:FID 39116 39166\r\na=rtcp-mux\r\na=rtcp-rsize\r\na=x-source-streamid:3399\r\nm=video 3480 UDP/TLS/RTP/SAVPF 107 99\r\nc=IN IP4 172.172.100.250\r\nb=AS:3920\r\na=rtpmap:107 H264/90000\r\na=rtpmap:99 rtx/90000\r\na=fmtp:107 packetization-mode=1;profile-level-id=42C02A\r\na=fmtp:99 apt=107\r\na=rtcp:3480\r\na=rtcp-fb:* nack\r\na=rtcp-fb:* nack pli\r\na=rtcp-fb:* goog-remb\r\na=rtcp-fb:* ccm fir\r\na=rtcp-fb:* transport-cc\r\na=extmap:2 http://www.webrtc.org/experiments/rtp-hdrext/abs-send-time\r\na=extmap:3 http://www.ietf.org/id/draft-holmer-rmcat-transport-wide-cc-extensions-01\r\na=extmap:4 urn:ietf:params:rtp-hdrext:sdes:mid\r\na=extmap:10 urn:ietf:params:rtp-hdrext:sdes:rtp-stream-id\r\na=extmap:11 urn:ietf:params:rtp-hdrext:sdes:repaired-rtp-stream-id\r\na=extmap:9 http://www.webrtc.org/experiments/rtp-hdrext/video-layers-allocation00\r\na=setup:passive\r\na=mid:4\r\na=sendonly\r\na=ice-ufrag:wmA+\r\na=ice-pwd:KQ5Zkcak+RPw2GY98PNWN7Bu\r\na=fingerprint:sha-256 DA:93:54:F4:88:DA:6D:8D:57:43:C2:A1:A7:77:CA:96:9A:60:DA:63:F0:9E:4E:D2:4E:24:16:69:74:AC:39:ED\r\na=ssrc:39216 cname:1d3cac01687b45bdbe99ddf3685db9df\r\na=ssrc:39216 msid:mainVideo-39216 mainVideo-39216\r\na=ssrc:39266 cname:1d3cac01687b45bdbe99ddf3685db9df\r\na=ssrc:39266 msid:mainVideo-39216 mainVideo-39216\r\na=ssrc-group:FID 39216 39266\r\na=rtcp-mux\r\na=rtcp-rsize\r\na=x-source-streamid:3400\r\nm=video 3480 UDP/TLS/RTP/SAVPF 107 99\r\nc=IN IP4 172.172.100.250\r\nb=AS:3920\r\na=rtpmap:107 H264/90000\r\na=rtpmap:99 rtx/90000\r\na=fmtp:107 packetization-mode=1;profile-level-id=42C02A\r\na=fmtp:99 apt=107\r\na=rtcp:3480\r\na=rtcp-fb:* nack\r\na=rtcp-fb:* nack pli\r\na=rtcp-fb:* goog-remb\r\na=rtcp-fb:* ccm fir\r\na=rtcp-fb:* transport-cc\r\na=extmap:2 http://www.webrtc.org/experiments/rtp-hdrext/abs-send-time\r\na=extmap:3 http://www.ietf.org/id/draft-holmer-rmcat-transport-wide-cc-extensions-01\r\na=extmap:4 urn:ietf:params:rtp-hdrext:sdes:mid\r\na=extmap:10 urn:ietf:params:rtp-hdrext:sdes:rtp-stream-id\r\na=extmap:11 urn:ietf:params:rtp-hdrext:sdes:repaired-rtp-stream-id\r\na=extmap:9 http://www.webrtc.org/experiments/rtp-hdrext/video-layers-allocation00\r\na=setup:passive\r\na=mid:5\r\na=sendonly\r\na=ice-ufrag:wmA+\r\na=ice-pwd:KQ5Zkcak+RPw2GY98PNWN7Bu\r\na=fingerprint:sha-256 DA:93:54:F4:88:DA:6D:8D:57:43:C2:A1:A7:77:CA:96:9A:60:DA:63:F0:9E:4E:D2:4E:24:16:69:74:AC:39:ED\r\na=ssrc:39316 cname:1d3cac01687b45bdbe99ddf3685db9df\r\na=ssrc:39316 msid:mainVideo-39316 mainVideo-39316\r\na=ssrc:39366 cname:1d3cac01687b45bdbe99ddf3685db9df\r\na=ssrc:39366 msid:mainVideo-39316 mainVideo-39316\r\na=ssrc-group:FID 39316 39366\r\na=rtcp-mux\r\na=rtcp-rsize\r\na=x-source-streamid:3401\r\nm=video 3480 UDP/TLS/RTP/SAVPF 107 99\r\nc=IN IP4 172.172.100.250\r\nb=AS:3920\r\na=rtpmap:107 H264/90000\r\na=rtpmap:99 rtx/90000\r\na=fmtp:107 packetization-mode=1;profile-level-id=42C02A\r\na=fmtp:99 apt=107\r\na=rtcp:3480\r\na=rtcp-fb:* nack\r\na=rtcp-fb:* nack pli\r\na=rtcp-fb:* goog-remb\r\na=rtcp-fb:* ccm fir\r\na=rtcp-fb:* transport-cc\r\na=extmap:2 http://www.webrtc.org/experiments/rtp-hdrext/abs-send-time\r\na=extmap:3 http://www.ietf.org/id/draft-holmer-rmcat-transport-wide-cc-extensions-01\r\na=extmap:4 urn:ietf:params:rtp-hdrext:sdes:mid\r\na=extmap:10 urn:ietf:params:rtp-hdrext:sdes:rtp-stream-id\r\na=extmap:11 urn:ietf:params:rtp-hdrext:sdes:repaired-rtp-stream-id\r\na=extmap:9 http://www.webrtc.org/experiments/rtp-hdrext/video-layers-allocation00\r\na=setup:passive\r\na=mid:6\r\na=sendonly\r\na=ice-ufrag:wmA+\r\na=ice-pwd:KQ5Zkcak+RPw2GY98PNWN7Bu\r\na=fingerprint:sha-256 DA:93:54:F4:88:DA:6D:8D:57:43:C2:A1:A7:77:CA:96:9A:60:DA:63:F0:9E:4E:D2:4E:24:16:69:74:AC:39:ED\r\na=ssrc:39416 cname:1d3cac01687b45bdbe99ddf3685db9df\r\na=ssrc:39416 msid:mainVideo-39416 mainVideo-39416\r\na=ssrc:39466 cname:1d3cac01687b45bdbe99ddf3685db9df\r\na=ssrc:39466 msid:mainVideo-39416 mainVideo-39416\r\na=ssrc-group:FID 39416 39466\r\na=rtcp-mux\r\na=rtcp-rsize\r\na=x-source-streamid:3402\r\nm=video 3480 UDP/TLS/RTP/SAVPF 107 99\r\nc=IN IP4 172.172.100.250\r\nb=AS:3920\r\na=rtpmap:107 H264/90000\r\na=rtpmap:99 rtx/90000\r\na=fmtp:107 packetization-mode=1;profile-level-id=42C02A\r\na=fmtp:99 apt=107\r\na=rtcp:3480\r\na=rtcp-fb:* nack\r\na=rtcp-fb:* nack pli\r\na=rtcp-fb:* goog-remb\r\na=rtcp-fb:* ccm fir\r\na=rtcp-fb:* transport-cc\r\na=extmap:2 http://www.webrtc.org/experiments/rtp-hdrext/abs-send-time\r\na=extmap:3 http://www.ietf.org/id/draft-holmer-rmcat-transport-wide-cc-extensions-01\r\na=extmap:4 urn:ietf:params:rtp-hdrext:sdes:mid\r\na=extmap:10 urn:ietf:params:rtp-hdrext:sdes:rtp-stream-id\r\na=extmap:11 urn:ietf:params:rtp-hdrext:sdes:repaired-rtp-stream-id\r\na=extmap:9 http://www.webrtc.org/experiments/rtp-hdrext/video-layers-allocation00\r\na=setup:passive\r\na=mid:7\r\na=sendonly\r\na=ice-ufrag:wmA+\r\na=ice-pwd:KQ5Zkcak+RPw2GY98PNWN7Bu\r\na=fingerprint:sha-256 DA:93:54:F4:88:DA:6D:8D:57:43:C2:A1:A7:77:CA:96:9A:60:DA:63:F0:9E:4E:D2:4E:24:16:69:74:AC:39:ED\r\na=ssrc:39516 cname:1d3cac01687b45bdbe99ddf3685db9df\r\na=ssrc:39516 msid:mainVideo-39516 mainVideo-39516\r\na=ssrc:39566 cname:1d3cac01687b45bdbe99ddf3685db9df\r\na=ssrc:39566 msid:mainVideo-39516 mainVideo-39516\r\na=ssrc-group:FID 39516 39566\r\na=rtcp-mux\r\na=rtcp-rsize\r\na=x-source-streamid:3403\r\nm=video 3480 UDP/TLS/RTP/SAVPF 107 99\r\nc=IN IP4 172.172.100.250\r\nb=AS:3920\r\na=rtpmap:107 H264/90000\r\na=rtpmap:99 rtx/90000\r\na=fmtp:107 packetization-mode=1;profile-level-id=42C02A\r\na=fmtp:99 apt=107\r\na=rtcp:3480\r\na=rtcp-fb:* nack\r\na=rtcp-fb:* nack pli\r\na=rtcp-fb:* goog-remb\r\na=rtcp-fb:* ccm fir\r\na=rtcp-fb:* transport-cc\r\na=extmap:2 http://www.webrtc.org/experiments/rtp-hdrext/abs-send-time\r\na=extmap:3 http://www.ietf.org/id/draft-holmer-rmcat-transport-wide-cc-extensions-01\r\na=extmap:4 urn:ietf:params:rtp-hdrext:sdes:mid\r\na=extmap:10 urn:ietf:params:rtp-hdrext:sdes:rtp-stream-id\r\na=extmap:11 urn:ietf:params:rtp-hdrext:sdes:repaired-rtp-stream-id\r\na=extmap:9 http://www.webrtc.org/experiments/rtp-hdrext/video-layers-allocation00\r\na=setup:passive\r\na=mid:8\r\na=sendonly\r\na=ice-ufrag:wmA+\r\na=ice-pwd:KQ5Zkcak+RPw2GY98PNWN7Bu\r\na=fingerprint:sha-256 DA:93:54:F4:88:DA:6D:8D:57:43:C2:A1:A7:77:CA:96:9A:60:DA:63:F0:9E:4E:D2:4E:24:16:69:74:AC:39:ED\r\na=ssrc:39616 cname:1d3cac01687b45bdbe99ddf3685db9df\r\na=ssrc:39616 msid:mainVideo-39616 mainVideo-39616\r\na=ssrc:39666 cname:1d3cac01687b45bdbe99ddf3685db9df\r\na=ssrc:39666 msid:mainVideo-39616 mainVideo-39616\r\na=ssrc-group:FID 39616 39666\r\na=rtcp-mux\r\na=rtcp-rsize\r\na=x-source-streamid:3404\r\nm=video 3480 UDP/TLS/RTP/SAVPF 107 99\r\nc=IN IP4 172.172.100.250\r\nb=AS:3920\r\na=rtpmap:107 H264/90000\r\na=rtpmap:99 rtx/90000\r\na=fmtp:107 packetization-mode=1;profile-level-id=42C02A\r\na=fmtp:99 apt=107\r\na=rtcp:3480\r\na=rtcp-fb:* nack\r\na=rtcp-fb:* nack pli\r\na=rtcp-fb:* goog-remb\r\na=rtcp-fb:* ccm fir\r\na=rtcp-fb:* transport-cc\r\na=extmap:2 http://www.webrtc.org/experiments/rtp-hdrext/abs-send-time\r\na=extmap:3 http://www.ietf.org/id/draft-holmer-rmcat-transport-wide-cc-extensions-01\r\na=extmap:4 urn:ietf:params:rtp-hdrext:sdes:mid\r\na=extmap:10 urn:ietf:params:rtp-hdrext:sdes:rtp-stream-id\r\na=extmap:11 urn:ietf:params:rtp-hdrext:sdes:repaired-rtp-stream-id\r\na=extmap:9 http://www.webrtc.org/experiments/rtp-hdrext/video-layers-allocation00\r\na=setup:passive\r\na=mid:9\r\na=sendonly\r\na=ice-ufrag:wmA+\r\na=ice-pwd:KQ5Zkcak+RPw2GY98PNWN7Bu\r\na=fingerprint:sha-256 DA:93:54:F4:88:DA:6D:8D:57:43:C2:A1:A7:77:CA:96:9A:60:DA:63:F0:9E:4E:D2:4E:24:16:69:74:AC:39:ED\r\na=ssrc:39716 cname:1d3cac01687b45bdbe99ddf3685db9df\r\na=ssrc:39716 msid:mainVideo-39716 mainVideo-39716\r\na=ssrc:39766 cname:1d3cac01687b45bdbe99ddf3685db9df\r\na=ssrc:39766 msid:mainVideo-39716 mainVideo-39716\r\na=ssrc-group:FID 39716 39766\r\na=rtcp-mux\r\na=rtcp-rsize\r\na=x-source-streamid:3405\r\nm=video 3480 UDP/TLS/RTP/SAVPF 107 99\r\nc=IN IP4 172.172.100.250\r\nb=AS:3920\r\na=rtpmap:107 H264/90000\r\na=rtpmap:99 rtx/90000\r\na=fmtp:107 packetization-mode=1;profile-level-id=42C02A\r\na=fmtp:99 apt=107\r\na=rtcp:3480\r\na=rtcp-fb:* nack\r\na=rtcp-fb:* nack pli\r\na=rtcp-fb:* goog-remb\r\na=rtcp-fb:* ccm fir\r\na=rtcp-fb:* transport-cc\r\na=extmap:2 http://www.webrtc.org/experiments/rtp-hdrext/abs-send-time\r\na=extmap:3 http://www.ietf.org/id/draft-holmer-rmcat-transport-wide-cc-extensions-01\r\na=extmap:4 urn:ietf:params:rtp-hdrext:sdes:mid\r\na=extmap:10 urn:ietf:params:rtp-hdrext:sdes:rtp-stream-id\r\na=extmap:11 urn:ietf:params:rtp-hdrext:sdes:repaired-rtp-stream-id\r\na=extmap:9 http://www.webrtc.org/experiments/rtp-hdrext/video-layers-allocation00\r\na=setup:passive\r\na=mid:10\r\na=sendonly\r\na=ice-ufrag:wmA+\r\na=ice-pwd:KQ5Zkcak+RPw2GY98PNWN7Bu\r\na=fingerprint:sha-256 DA:93:54:F4:88:DA:6D:8D:57:43:C2:A1:A7:77:CA:96:9A:60:DA:63:F0:9E:4E:D2:4E:24:16:69:74:AC:39:ED\r\na=ssrc:39816 cname:1d3cac01687b45bdbe99ddf3685db9df\r\na=ssrc:39816 msid:mainVideo-39816 mainVideo-39816\r\na=ssrc:39866 cname:1d3cac01687b45bdbe99ddf3685db9df\r\na=ssrc:39866 msid:mainVideo-39816 mainVideo-39816\r\na=ssrc-group:FID 39816 39866\r\na=rtcp-mux\r\na=rtcp-rsize\r\na=x-source-streamid:3406\r\nm=video 3480 UDP/TLS/RTP/SAVPF 107 99\r\nc=IN IP4 172.172.100.250\r\nb=AS:3920\r\na=rtpmap:107 H264/90000\r\na=rtpmap:99 rtx/90000\r\na=fmtp:107 packetization-mode=1;profile-level-id=42C02A\r\na=fmtp:99 apt=107\r\na=rtcp:3480\r\na=rtcp-fb:* nack\r\na=rtcp-fb:* nack pli\r\na=rtcp-fb:* goog-remb\r\na=rtcp-fb:* ccm fir\r\na=rtcp-fb:* transport-cc\r\na=extmap:2 http://www.webrtc.org/experiments/rtp-hdrext/abs-send-time\r\na=extmap:3 http://www.ietf.org/id/draft-holmer-rmcat-transport-wide-cc-extensions-01\r\na=extmap:4 urn:ietf:params:rtp-hdrext:sdes:mid\r\na=extmap:10 urn:ietf:params:rtp-hdrext:sdes:rtp-stream-id\r\na=extmap:11 urn:ietf:params:rtp-hdrext:sdes:repaired-rtp-stream-id\r\na=extmap:9 http://www.webrtc.org/experiments/rtp-hdrext/video-layers-allocation00\r\na=setup:passive\r\na=mid:11\r\na=sendonly\r\na=ice-ufrag:wmA+\r\na=ice-pwd:KQ5Zkcak+RPw2GY98PNWN7Bu\r\na=fingerprint:sha-256 DA:93:54:F4:88:DA:6D:8D:57:43:C2:A1:A7:77:CA:96:9A:60:DA:63:F0:9E:4E:D2:4E:24:16:69:74:AC:39:ED\r\na=ssrc:39916 cname:1d3cac01687b45bdbe99ddf3685db9df\r\na=ssrc:39916 msid:applicationsharingVideo-39916 applicationsharingVideo-39916\r\na=ssrc:39966 cname:1d3cac01687b45bdbe99ddf3685db9df\r\na=ssrc:39966 msid:applicationsharingVideo-39916 applicationsharingVideo-39916\r\na=ssrc-group:FID 39916 39966\r\na=rtcp-mux\r\na=rtcp-rsize\r\na=x-source-streamid:3407\r\nm=application 3480 UDP/DTLS/SCTP webrtc-datachannel\r\nc=IN IP4 172.172.100.250\r\na=setup:passive\r\na=mid:12\r\na=ice-ufrag:wmA+\r\na=ice-pwd:KQ5Zkcak+RPw2GY98PNWN7Bu\r\na=fingerprint:sha-256 DA:93:54:F4:88:DA:6D:8D:57:43:C2:A1:A7:77:CA:96:9A:60:DA:63:F0:9E:4E:D2:4E:24:16:69:74:AC:39:ED\r\na=sctp-port:5000\r\na=x-source-streamid:3408\r\n","type":"answer"}

{"28:bdd75849-e0a6-4cce-8fc1-d7c0d4da43e5":{"version":9,"state":"active","advancedMeetingRole":"presenter","details":{"id":"28:bdd75849-e0a6-4cce-8fc1-d7c0d4da43e5","displayName":null,"displayNameSource":"unknown","propertyBag":null,"resourceId":null,"participantType":"inTenant","endpointId":"00000000-0000-0000-0000-000000000000","participantId":null,"languageId":null,"hidden":false},"endpoints":{"dac817a0-c5cd-4bae-b8b1-4e49c2436537":{"call":{"mediaStreams":[{"type":"audio","label":"main-audio","sourceId":414,"direction":"recvonly","serverMuted":false,"notInDefaultRoutingGroup":false},{"type":"video","label":"main-video","sourceId":415,"direction":"recvonly","serverMuted":false,"notInDefaultRoutingGroup":false},{"type":"applicationsharing-video","label":"applicationsharing-video","sourceId":425,"direction":"recvonly","serverMuted":false,"notInDefaultRoutingGroup":false},{"type":"data","label":"data","sourceId":426,"direction":"sendrecv","serverMuted":false,"notInDefaultRoutingGroup":false}],"serverMuteVersion":1,"appliedInteractivityLevel":"interactive"},"endpointCapabilities":67,"participantId":"1d3b8934-0b2a-40bc-bb15-32a3744b595c","clientVersion":"appid:bdd75849-e0a6-4cce-8fc1-d7c0d4da43e5 GraphCommunicationsClient-CallRecorderBot/1.2.0.12281","endpointMetadata":{"__platform":{"ui":{"hidden":true}},"spokenLanguage":"en-us","commandUrl":"https://aks-prod-usea-p06-api.callrecorder.skype.com/v1/oncommand/849dffd0-aa84-41d5-bb9c-a338cd024dd0","joinTime":"2025-01-23T23:46:46.5946692Z","processingModes":{"recording":{"state":"Inactive","userId":""},"closedCaptions":{"state":"Active","userId":"8:guest:d07e8660-85c0-497d-9bc6-9c2807bb57c2","timestamp":"2025-01-23T23:46:47.258907Z"},"realTimeTranscript":{"state":"Inactive","timestamp":"0001-01-01T00:00:00","properties":{"lastStartReason":"Unknown"}},"meetingCoach":{"state":"Inactive","timestamp":"0001-01-01T00:00:00"},"faceStream":{"state":"Inactive","timestamp":"0001-01-01T00:00:00"},"copilot":{"state":"Inactive","timestamp":"0001-01-01T00:00:00"}},"textTracks":[{"source":"Ai","lang":"en-us","translations":[]}],"runtimeErrors":[],"product":"Teams"},"endpointJoinTime":"2025-01-23T23:46:46.7654327Z","modalityJoined":"Call","endpointMeetingRoles":["presenter"]}},"role":"admin","meetingRole":"presenter","meetingRoles":["attendee"]},"8:live:.cid.fda34a0da6d73378":{"version":119,"state":"active","advancedMeetingRole":"organizer","details":{"id":"8:live:.cid.fda34a0da6d73378","displayName":"Noah Duncan","displayNameSource":"unknown","propertyBag":null,"resourceId":null,"participantType":"inTenant","endpointId":"00000000-0000-0000-0000-000000000000","participantId":null,"languageId":null,"hidden":false},"endpoints":{"8ff21765-e2b3-4a00-a45a-4c9ce643ef1d":{"call":{"mediaStreams":[{"type":"audio","label":"main-audio","sourceId":1053,"direction":"sendrecv","serverMuted":false,"notInDefaultRoutingGroup":false},{"type":"video","label":"main-video","sourceId":1054,"direction":"recvonly","serverMuted":false,"notInDefaultRoutingGroup":false},{"type":"applicationsharing-video","label":"applicationsharing-video","sourceId":1064,"direction":"recvonly","serverMuted":false,"notInDefaultRoutingGroup":false},{"type":"data","label":"data","sourceId":1065,"direction":"sendrecv","serverMuted":false,"notInDefaultRoutingGroup":false}],"serverMuteVersion":22,"appliedInteractivityLevel":"interactive","clientEndpointCapabilities":16384},"endpointCapabilities":67,"clientEndpointCapabilities":16384,"participantId":"d8e35be2-f69e-4bc3-a243-8a86c40ac91c","clientVersion":"SkypeSpaces/1415/25010618743/os=linux; osVer=undefined; deviceType=computer; browser=chrome; browserVer=131.0.0.0/TsCallingVersion=2024.50.01.7/Ovb=2511af5bf8a88535da31c34672b6c8228e848315","endpointMetadata":{"holographicCapabilities":3},"endpointState":{"endpointStateSequenceNumber":8,"state":{"isMuted":true}},"languageId":"en-US","endpointJoinTime":"2025-01-24T00:04:00.9881348Z","modalityJoined":"Call","endpointMeetingRoles":["organizer"]}},"role":"admin","meetingRole":"organizer","meetingRoles":["attendee"]},"8:guest:8876d0cc-81be-4d7d-9cec-96e777479a91":{"version":123,"state":"active","advancedMeetingRole":"presenter","details":{"id":"8:guest:8876d0cc-81be-4d7d-9cec-96e777479a91","displayName":"Mr Bot!","displayNameSource":"unknown","propertyBag":null,"resourceId":null,"participantType":"anonymous","endpointId":"00000000-0000-0000-0000-000000000000","participantId":null,"languageId":null,"hidden":false},"endpoints":{"6ce3309e-6904-4444-ab71-26c611afce7d":{"call":{"mediaStreams":[{"type":"audio","label":"main-audio","sourceId":3396,"direction":"sendrecv","serverMuted":false,"notInDefaultRoutingGroup":false},{"type":"video","label":"main-video","sourceId":3397,"direction":"sendrecv","serverMuted":false,"notInDefaultRoutingGroup":false},{"type":"applicationsharing-video","label":"applicationsharing-video","sourceId":3407,"direction":"recvonly","serverMuted":false,"notInDefaultRoutingGroup":false},{"type":"data","label":"data","sourceId":3408,"direction":"sendrecv","serverMuted":false,"notInDefaultRoutingGroup":false}],"serverMuteVersion":1,"appliedInteractivityLevel":"interactive","clientEndpointCapabilities":16384},"endpointCapabilities":67,"clientEndpointCapabilities":16384,"participantId":"2553596a-5e36-4289-b0de-c40600d83a20","clientVersion":"SkypeSpaces/1415/24121221944/os=linux; osVer=undefined; deviceType=computer; browser=chrome; browserVer=132.0.0.0/TsCallingVersion=2024.49.01.10/Ovb=bc55abee216a6224c870e9aabe1c1867856d4403","endpointMetadata":{"holographicCapabilities":3,"transcriptionPrefs":{"closedCaptions":false}},"languageId":"en-US","endpointJoinTime":"2025-01-24T02:47:31.8829475Z","modalityJoined":"Call","endpointMeetingRoles":["presenter"]}},"role":"guest","meetingRole":"presenter","meetingRoles":["attendee"]}}




{"type":"answer","sdp":"v=0\r\no=- 222464 0 IN IP4 127.0.0.1\r\ns=session\r\nc=IN IP4 172.172.100.250\r\nb=CT:10000000\r\nt=0 0\r\na=extmap-allow-mixed\r\na=msid-semantic: WMS *\r\na=group:BUNDLE 0 1 2 3 4 5 6 7 8 9 10 11 12\r\na=x-mediabw:applicationsharing-video send=8100;recv=8100\r\na=x-plaza-msi-range:3409-3508 3509-3608\r\nm=audio 3480 UDP/TLS/RTP/SAVPF 111 97 9 0 8 13 101\r\nc=IN IP4 172.172.100.250\r\na=rtpmap:111 OPUS/48000/2\r\na=rtpmap:97 RED/48000/2\r\na=rtpmap:9 G722/8000\r\na=rtpmap:0 PCMU/8000\r\na=rtpmap:8 PCMA/8000\r\na=rtpmap:13 CN/8000\r\na=rtpmap:101 telephone-event/8000\r\na=fmtp:101 0-16\r\na=fmtp:111 usedtx=1;useinbandfec=1\r\na=fmtp:97 111/111\r\na=rtcp:3480\r\na=rtcp-fb:111 transport-cc\r\na=extmap:2 http://www.webrtc.org/experiments/rtp-hdrext/abs-send-time\r\na=extmap:3 http://www.ietf.org/id/draft-holmer-rmcat-transport-wide-cc-extensions-01\r\na=setup:passive\r\na=mid:0\r\na=ptime:20\r\na=ice-ufrag:+/j1\r\na=ice-pwd:b8lcdmba8KG0mH4KA5OzM7hw\r\na=fingerprint:sha-256 DA:93:54:F4:88:DA:6D:8D:57:43:C2:A1:A7:77:CA:96:9A:60:DA:63:F0:9E:4E:D2:4E:24:16:69:74:AC:39:ED\r\na=candidate:1 1 UDP 54001663 172.172.100.250 3480 typ relay raddr 10.0.129.40 rport 3480\r\na=candidate:3 1 tcp 18087935 172.172.100.250 3478 typ relay raddr 10.0.129.40 rport 3478 tcptype passive\r\na=ssrc:40116 cname:35cfb36690cb4d77b0aa6878fb36719f\r\na=ssrc:40116 msid:mainAudio-40116 mainAudio-40116\r\na=rtcp-mux\r\na=x-source-streamid:3609\r\nm=video 3480 UDP/TLS/RTP/SAVPF 107 99\r\nc=IN IP4 172.172.100.250\r\nb=AS:3920\r\na=rtpmap:107 H264/90000\r\na=rtpmap:99 rtx/90000\r\na=fmtp:107 packetization-mode=1;profile-level-id=42C02A\r\na=fmtp:99 apt=107\r\na=rtcp:3480\r\na=rtcp-fb:* nack\r\na=rtcp-fb:* nack pli\r\na=rtcp-fb:* goog-remb\r\na=rtcp-fb:* ccm fir\r\na=rtcp-fb:* transport-cc\r\na=extmap:2 http://www.webrtc.org/experiments/rtp-hdrext/abs-send-time\r\na=extmap:3 http://www.ietf.org/id/draft-holmer-rmcat-transport-wide-cc-extensions-01\r\na=extmap:4 urn:ietf:params:rtp-hdrext:sdes:mid\r\na=extmap:10 urn:ietf:params:rtp-hdrext:sdes:rtp-stream-id\r\na=extmap:11 urn:ietf:params:rtp-hdrext:sdes:repaired-rtp-stream-id\r\na=extmap:9 http://www.webrtc.org/experiments/rtp-hdrext/video-layers-allocation00\r\na=setup:passive\r\na=mid:1\r\na=ice-ufrag:+/j1\r\na=ice-pwd:b8lcdmba8KG0mH4KA5OzM7hw\r\na=fingerprint:sha-256 DA:93:54:F4:88:DA:6D:8D:57:43:C2:A1:A7:77:CA:96:9A:60:DA:63:F0:9E:4E:D2:4E:24:16:69:74:AC:39:ED\r\na=ssrc:40117 cname:35cfb36690cb4d77b0aa6878fb36719f\r\na=ssrc:40117 msid:mainVideo-40117 mainVideo-40117\r\na=ssrc:40167 cname:35cfb36690cb4d77b0aa6878fb36719f\r\na=ssrc:40167 msid:mainVideo-40117 mainVideo-40117\r\na=ssrc-group:FID 40117 40167\r\na=rtcp-mux\r\na=rtcp-rsize\r\na=rid:1 recv\r\na=rid:2 recv\r\na=simulcast:recv ~1;~2\r\na=x-source-streamid:3610\r\nm=video 3480 UDP/TLS/RTP/SAVPF 107 99\r\nc=IN IP4 172.172.100.250\r\nb=AS:3920\r\na=rtpmap:107 H264/90000\r\na=rtpmap:99 rtx/90000\r\na=fmtp:107 packetization-mode=1;profile-level-id=42C02A\r\na=fmtp:99 apt=107\r\na=rtcp:3480\r\na=rtcp-fb:* nack\r\na=rtcp-fb:* nack pli\r\na=rtcp-fb:* goog-remb\r\na=rtcp-fb:* ccm fir\r\na=rtcp-fb:* transport-cc\r\na=extmap:2 http://www.webrtc.org/experiments/rtp-hdrext/abs-send-time\r\na=extmap:3 http://www.ietf.org/id/draft-holmer-rmcat-transport-wide-cc-extensions-01\r\na=extmap:4 urn:ietf:params:rtp-hdrext:sdes:mid\r\na=extmap:10 urn:ietf:params:rtp-hdrext:sdes:rtp-stream-id\r\na=extmap:11 urn:ietf:params:rtp-hdrext:sdes:repaired-rtp-stream-id\r\na=extmap:9 http://www.webrtc.org/experiments/rtp-hdrext/video-layers-allocation00\r\na=setup:passive\r\na=mid:2\r\na=sendonly\r\na=ice-ufrag:+/j1\r\na=ice-pwd:b8lcdmba8KG0mH4KA5OzM7hw\r\na=fingerprint:sha-256 DA:93:54:F4:88:DA:6D:8D:57:43:C2:A1:A7:77:CA:96:9A:60:DA:63:F0:9E:4E:D2:4E:24:16:69:74:AC:39:ED\r\na=ssrc:40217 cname:35cfb36690cb4d77b0aa6878fb36719f\r\na=ssrc:40217 msid:mainVideo-40217 mainVideo-40217\r\na=ssrc:40267 cname:35cfb36690cb4d77b0aa6878fb36719f\r\na=ssrc:40267 msid:mainVideo-40217 mainVideo-40217\r\na=ssrc-group:FID 40217 40267\r\na=rtcp-mux\r\na=rtcp-rsize\r\na=x-source-streamid:3611\r\nm=video 3480 UDP/TLS/RTP/SAVPF 107 99\r\nc=IN IP4 172.172.100.250\r\nb=AS:3920\r\na=rtpmap:107 H264/90000\r\na=rtpmap:99 rtx/90000\r\na=fmtp:107 packetization-mode=1;profile-level-id=42C02A\r\na=fmtp:99 apt=107\r\na=rtcp:3480\r\na=rtcp-fb:* nack\r\na=rtcp-fb:* nack pli\r\na=rtcp-fb:* goog-remb\r\na=rtcp-fb:* ccm fir\r\na=rtcp-fb:* transport-cc\r\na=extmap:2 http://www.webrtc.org/experiments/rtp-hdrext/abs-send-time\r\na=extmap:3 http://www.ietf.org/id/draft-holmer-rmcat-transport-wide-cc-extensions-01\r\na=extmap:4 urn:ietf:params:rtp-hdrext:sdes:mid\r\na=extmap:10 urn:ietf:params:rtp-hdrext:sdes:rtp-stream-id\r\na=extmap:11 urn:ietf:params:rtp-hdrext:sdes:repaired-rtp-stream-id\r\na=extmap:9 http://www.webrtc.org/experiments/rtp-hdrext/video-layers-allocation00\r\na=setup:passive\r\na=mid:3\r\na=sendonly\r\na=ice-ufrag:+/j1\r\na=ice-pwd:b8lcdmba8KG0mH4KA5OzM7hw\r\na=fingerprint:sha-256 DA:93:54:F4:88:DA:6D:8D:57:43:C2:A1:A7:77:CA:96:9A:60:DA:63:F0:9E:4E:D2:4E:24:16:69:74:AC:39:ED\r\na=ssrc:40317 cname:35cfb36690cb4d77b0aa6878fb36719f\r\na=ssrc:40317 msid:mainVideo-40317 mainVideo-40317\r\na=ssrc:40367 cname:35cfb36690cb4d77b0aa6878fb36719f\r\na=ssrc:40367 msid:mainVideo-40317 mainVideo-40317\r\na=ssrc-group:FID 40317 40367\r\na=rtcp-mux\r\na=rtcp-rsize\r\na=x-source-streamid:3612\r\nm=video 3480 UDP/TLS/RTP/SAVPF 107 99\r\nc=IN IP4 172.172.100.250\r\nb=AS:3920\r\na=rtpmap:107 H264/90000\r\na=rtpmap:99 rtx/90000\r\na=fmtp:107 packetization-mode=1;profile-level-id=42C02A\r\na=fmtp:99 apt=107\r\na=rtcp:3480\r\na=rtcp-fb:* nack\r\na=rtcp-fb:* nack pli\r\na=rtcp-fb:* goog-remb\r\na=rtcp-fb:* ccm fir\r\na=rtcp-fb:* transport-cc\r\na=extmap:2 http://www.webrtc.org/experiments/rtp-hdrext/abs-send-time\r\na=extmap:3 http://www.ietf.org/id/draft-holmer-rmcat-transport-wide-cc-extensions-01\r\na=extmap:4 urn:ietf:params:rtp-hdrext:sdes:mid\r\na=extmap:10 urn:ietf:params:rtp-hdrext:sdes:rtp-stream-id\r\na=extmap:11 urn:ietf:params:rtp-hdrext:sdes:repaired-rtp-stream-id\r\na=extmap:9 http://www.webrtc.org/experiments/rtp-hdrext/video-layers-allocation00\r\na=setup:passive\r\na=mid:4\r\na=sendonly\r\na=ice-ufrag:+/j1\r\na=ice-pwd:b8lcdmba8KG0mH4KA5OzM7hw\r\na=fingerprint:sha-256 DA:93:54:F4:88:DA:6D:8D:57:43:C2:A1:A7:77:CA:96:9A:60:DA:63:F0:9E:4E:D2:4E:24:16:69:74:AC:39:ED\r\na=ssrc:40417 cname:35cfb36690cb4d77b0aa6878fb36719f\r\na=ssrc:40417 msid:mainVideo-40417 mainVideo-40417\r\na=ssrc:40467 cname:35cfb36690cb4d77b0aa6878fb36719f\r\na=ssrc:40467 msid:mainVideo-40417 mainVideo-40417\r\na=ssrc-group:FID 40417 40467\r\na=rtcp-mux\r\na=rtcp-rsize\r\na=x-source-streamid:3613\r\nm=video 3480 UDP/TLS/RTP/SAVPF 107 99\r\nc=IN IP4 172.172.100.250\r\nb=AS:3920\r\na=rtpmap:107 H264/90000\r\na=rtpmap:99 rtx/90000\r\na=fmtp:107 packetization-mode=1;profile-level-id=42C02A\r\na=fmtp:99 apt=107\r\na=rtcp:3480\r\na=rtcp-fb:* nack\r\na=rtcp-fb:* nack pli\r\na=rtcp-fb:* goog-remb\r\na=rtcp-fb:* ccm fir\r\na=rtcp-fb:* transport-cc\r\na=extmap:2 http://www.webrtc.org/experiments/rtp-hdrext/abs-send-time\r\na=extmap:3 http://www.ietf.org/id/draft-holmer-rmcat-transport-wide-cc-extensions-01\r\na=extmap:4 urn:ietf:params:rtp-hdrext:sdes:mid\r\na=extmap:10 urn:ietf:params:rtp-hdrext:sdes:rtp-stream-id\r\na=extmap:11 urn:ietf:params:rtp-hdrext:sdes:repaired-rtp-stream-id\r\na=extmap:9 http://www.webrtc.org/experiments/rtp-hdrext/video-layers-allocation00\r\na=setup:passive\r\na=mid:5\r\na=sendonly\r\na=ice-ufrag:+/j1\r\na=ice-pwd:b8lcdmba8KG0mH4KA5OzM7hw\r\na=fingerprint:sha-256 DA:93:54:F4:88:DA:6D:8D:57:43:C2:A1:A7:77:CA:96:9A:60:DA:63:F0:9E:4E:D2:4E:24:16:69:74:AC:39:ED\r\na=ssrc:40517 cname:35cfb36690cb4d77b0aa6878fb36719f\r\na=ssrc:40517 msid:mainVideo-40517 mainVideo-40517\r\na=ssrc:40567 cname:35cfb36690cb4d77b0aa6878fb36719f\r\na=ssrc:40567 msid:mainVideo-40517 mainVideo-40517\r\na=ssrc-group:FID 40517 40567\r\na=rtcp-mux\r\na=rtcp-rsize\r\na=x-source-streamid:3614\r\nm=video 3480 UDP/TLS/RTP/SAVPF 107 99\r\nc=IN IP4 172.172.100.250\r\nb=AS:3920\r\na=rtpmap:107 H264/90000\r\na=rtpmap:99 rtx/90000\r\na=fmtp:107 packetization-mode=1;profile-level-id=42C02A\r\na=fmtp:99 apt=107\r\na=rtcp:3480\r\na=rtcp-fb:* nack\r\na=rtcp-fb:* nack pli\r\na=rtcp-fb:* goog-remb\r\na=rtcp-fb:* ccm fir\r\na=rtcp-fb:* transport-cc\r\na=extmap:2 http://www.webrtc.org/experiments/rtp-hdrext/abs-send-time\r\na=extmap:3 http://www.ietf.org/id/draft-holmer-rmcat-transport-wide-cc-extensions-01\r\na=extmap:4 urn:ietf:params:rtp-hdrext:sdes:mid\r\na=extmap:10 urn:ietf:params:rtp-hdrext:sdes:rtp-stream-id\r\na=extmap:11 urn:ietf:params:rtp-hdrext:sdes:repaired-rtp-stream-id\r\na=extmap:9 http://www.webrtc.org/experiments/rtp-hdrext/video-layers-allocation00\r\na=setup:passive\r\na=mid:6\r\na=sendonly\r\na=ice-ufrag:+/j1\r\na=ice-pwd:b8lcdmba8KG0mH4KA5OzM7hw\r\na=fingerprint:sha-256 DA:93:54:F4:88:DA:6D:8D:57:43:C2:A1:A7:77:CA:96:9A:60:DA:63:F0:9E:4E:D2:4E:24:16:69:74:AC:39:ED\r\na=ssrc:40617 cname:35cfb36690cb4d77b0aa6878fb36719f\r\na=ssrc:40617 msid:mainVideo-40617 mainVideo-40617\r\na=ssrc:40667 cname:35cfb36690cb4d77b0aa6878fb36719f\r\na=ssrc:40667 msid:mainVideo-40617 mainVideo-40617\r\na=ssrc-group:FID 40617 40667\r\na=rtcp-mux\r\na=rtcp-rsize\r\na=x-source-streamid:3615\r\nm=video 3480 UDP/TLS/RTP/SAVPF 107 99\r\nc=IN IP4 172.172.100.250\r\nb=AS:3920\r\na=rtpmap:107 H264/90000\r\na=rtpmap:99 rtx/90000\r\na=fmtp:107 packetization-mode=1;profile-level-id=42C02A\r\na=fmtp:99 apt=107\r\na=rtcp:3480\r\na=rtcp-fb:* nack\r\na=rtcp-fb:* nack pli\r\na=rtcp-fb:* goog-remb\r\na=rtcp-fb:* ccm fir\r\na=rtcp-fb:* transport-cc\r\na=extmap:2 http://www.webrtc.org/experiments/rtp-hdrext/abs-send-time\r\na=extmap:3 http://www.ietf.org/id/draft-holmer-rmcat-transport-wide-cc-extensions-01\r\na=extmap:4 urn:ietf:params:rtp-hdrext:sdes:mid\r\na=extmap:10 urn:ietf:params:rtp-hdrext:sdes:rtp-stream-id\r\na=extmap:11 urn:ietf:params:rtp-hdrext:sdes:repaired-rtp-stream-id\r\na=extmap:9 http://www.webrtc.org/experiments/rtp-hdrext/video-layers-allocation00\r\na=setup:passive\r\na=mid:7\r\na=sendonly\r\na=ice-ufrag:+/j1\r\na=ice-pwd:b8lcdmba8KG0mH4KA5OzM7hw\r\na=fingerprint:sha-256 DA:93:54:F4:88:DA:6D:8D:57:43:C2:A1:A7:77:CA:96:9A:60:DA:63:F0:9E:4E:D2:4E:24:16:69:74:AC:39:ED\r\na=ssrc:40717 cname:35cfb36690cb4d77b0aa6878fb36719f\r\na=ssrc:40717 msid:mainVideo-40717 mainVideo-40717\r\na=ssrc:40767 cname:35cfb36690cb4d77b0aa6878fb36719f\r\na=ssrc:40767 msid:mainVideo-40717 mainVideo-40717\r\na=ssrc-group:FID 40717 40767\r\na=rtcp-mux\r\na=rtcp-rsize\r\na=x-source-streamid:3616\r\nm=video 3480 UDP/TLS/RTP/SAVPF 107 99\r\nc=IN IP4 172.172.100.250\r\nb=AS:3920\r\na=rtpmap:107 H264/90000\r\na=rtpmap:99 rtx/90000\r\na=fmtp:107 packetization-mode=1;profile-level-id=42C02A\r\na=fmtp:99 apt=107\r\na=rtcp:3480\r\na=rtcp-fb:* nack\r\na=rtcp-fb:* nack pli\r\na=rtcp-fb:* goog-remb\r\na=rtcp-fb:* ccm fir\r\na=rtcp-fb:* transport-cc\r\na=extmap:2 http://www.webrtc.org/experiments/rtp-hdrext/abs-send-time\r\na=extmap:3 http://www.ietf.org/id/draft-holmer-rmcat-transport-wide-cc-extensions-01\r\na=extmap:4 urn:ietf:params:rtp-hdrext:sdes:mid\r\na=extmap:10 urn:ietf:params:rtp-hdrext:sdes:rtp-stream-id\r\na=extmap:11 urn:ietf:params:rtp-hdrext:sdes:repaired-rtp-stream-id\r\na=extmap:9 http://www.webrtc.org/experiments/rtp-hdrext/video-layers-allocation00\r\na=setup:passive\r\na=mid:8\r\na=sendonly\r\na=ice-ufrag:+/j1\r\na=ice-pwd:b8lcdmba8KG0mH4KA5OzM7hw\r\na=fingerprint:sha-256 DA:93:54:F4:88:DA:6D:8D:57:43:C2:A1:A7:77:CA:96:9A:60:DA:63:F0:9E:4E:D2:4E:24:16:69:74:AC:39:ED\r\na=ssrc:40817 cname:35cfb36690cb4d77b0aa6878fb36719f\r\na=ssrc:40817 msid:mainVideo-40817 mainVideo-40817\r\na=ssrc:40867 cname:35cfb36690cb4d77b0aa6878fb36719f\r\na=ssrc:40867 msid:mainVideo-40817 mainVideo-40817\r\na=ssrc-group:FID 40817 40867\r\na=rtcp-mux\r\na=rtcp-rsize\r\na=x-source-streamid:3617\r\nm=video 3480 UDP/TLS/RTP/SAVPF 107 99\r\nc=IN IP4 172.172.100.250\r\nb=AS:3920\r\na=rtpmap:107 H264/90000\r\na=rtpmap:99 rtx/90000\r\na=fmtp:107 packetization-mode=1;profile-level-id=42C02A\r\na=fmtp:99 apt=107\r\na=rtcp:3480\r\na=rtcp-fb:* nack\r\na=rtcp-fb:* nack pli\r\na=rtcp-fb:* goog-remb\r\na=rtcp-fb:* ccm fir\r\na=rtcp-fb:* transport-cc\r\na=extmap:2 http://www.webrtc.org/experiments/rtp-hdrext/abs-send-time\r\na=extmap:3 http://www.ietf.org/id/draft-holmer-rmcat-transport-wide-cc-extensions-01\r\na=extmap:4 urn:ietf:params:rtp-hdrext:sdes:mid\r\na=extmap:10 urn:ietf:params:rtp-hdrext:sdes:rtp-stream-id\r\na=extmap:11 urn:ietf:params:rtp-hdrext:sdes:repaired-rtp-stream-id\r\na=extmap:9 http://www.webrtc.org/experiments/rtp-hdrext/video-layers-allocation00\r\na=setup:passive\r\na=mid:9\r\na=sendonly\r\na=ice-ufrag:+/j1\r\na=ice-pwd:b8lcdmba8KG0mH4KA5OzM7hw\r\na=fingerprint:sha-256 DA:93:54:F4:88:DA:6D:8D:57:43:C2:A1:A7:77:CA:96:9A:60:DA:63:F0:9E:4E:D2:4E:24:16:69:74:AC:39:ED\r\na=ssrc:40917 cname:35cfb36690cb4d77b0aa6878fb36719f\r\na=ssrc:40917 msid:mainVideo-40917 mainVideo-40917\r\na=ssrc:40967 cname:35cfb36690cb4d77b0aa6878fb36719f\r\na=ssrc:40967 msid:mainVideo-40917 mainVideo-40917\r\na=ssrc-group:FID 40917 40967\r\na=rtcp-mux\r\na=rtcp-rsize\r\na=x-source-streamid:3618\r\nm=video 3480 UDP/TLS/RTP/SAVPF 107 99\r\nc=IN IP4 172.172.100.250\r\nb=AS:3920\r\na=rtpmap:107 H264/90000\r\na=rtpmap:99 rtx/90000\r\na=fmtp:107 packetization-mode=1;profile-level-id=42C02A\r\na=fmtp:99 apt=107\r\na=rtcp:3480\r\na=rtcp-fb:* nack\r\na=rtcp-fb:* nack pli\r\na=rtcp-fb:* goog-remb\r\na=rtcp-fb:* ccm fir\r\na=rtcp-fb:* transport-cc\r\na=extmap:2 http://www.webrtc.org/experiments/rtp-hdrext/abs-send-time\r\na=extmap:3 http://www.ietf.org/id/draft-holmer-rmcat-transport-wide-cc-extensions-01\r\na=extmap:4 urn:ietf:params:rtp-hdrext:sdes:mid\r\na=extmap:10 urn:ietf:params:rtp-hdrext:sdes:rtp-stream-id\r\na=extmap:11 urn:ietf:params:rtp-hdrext:sdes:repaired-rtp-stream-id\r\na=extmap:9 http://www.webrtc.org/experiments/rtp-hdrext/video-layers-allocation00\r\na=setup:passive\r\na=mid:10\r\na=sendonly\r\na=ice-ufrag:+/j1\r\na=ice-pwd:b8lcdmba8KG0mH4KA5OzM7hw\r\na=fingerprint:sha-256 DA:93:54:F4:88:DA:6D:8D:57:43:C2:A1:A7:77:CA:96:9A:60:DA:63:F0:9E:4E:D2:4E:24:16:69:74:AC:39:ED\r\na=ssrc:41017 cname:35cfb36690cb4d77b0aa6878fb36719f\r\na=ssrc:41017 msid:mainVideo-41017 mainVideo-41017\r\na=ssrc:41067 cname:35cfb36690cb4d77b0aa6878fb36719f\r\na=ssrc:41067 msid:mainVideo-41017 mainVideo-41017\r\na=ssrc-group:FID 41017 41067\r\na=rtcp-mux\r\na=rtcp-rsize\r\na=x-source-streamid:3619\r\nm=video 3480 UDP/TLS/RTP/SAVPF 107 99\r\nc=IN IP4 172.172.100.250\r\nb=AS:3920\r\na=rtpmap:107 H264/90000\r\na=rtpmap:99 rtx/90000\r\na=fmtp:107 packetization-mode=1;profile-level-id=42C02A\r\na=fmtp:99 apt=107\r\na=rtcp:3480\r\na=rtcp-fb:* nack\r\na=rtcp-fb:* nack pli\r\na=rtcp-fb:* goog-remb\r\na=rtcp-fb:* ccm fir\r\na=rtcp-fb:* transport-cc\r\na=extmap:2 http://www.webrtc.org/experiments/rtp-hdrext/abs-send-time\r\na=extmap:3 http://www.ietf.org/id/draft-holmer-rmcat-transport-wide-cc-extensions-01\r\na=extmap:4 urn:ietf:params:rtp-hdrext:sdes:mid\r\na=extmap:10 urn:ietf:params:rtp-hdrext:sdes:rtp-stream-id\r\na=extmap:11 urn:ietf:params:rtp-hdrext:sdes:repaired-rtp-stream-id\r\na=extmap:9 http://www.webrtc.org/experiments/rtp-hdrext/video-layers-allocation00\r\na=setup:passive\r\na=mid:11\r\na=sendonly\r\na=ice-ufrag:+/j1\r\na=ice-pwd:b8lcdmba8KG0mH4KA5OzM7hw\r\na=fingerprint:sha-256 DA:93:54:F4:88:DA:6D:8D:57:43:C2:A1:A7:77:CA:96:9A:60:DA:63:F0:9E:4E:D2:4E:24:16:69:74:AC:39:ED\r\na=ssrc:41117 cname:35cfb36690cb4d77b0aa6878fb36719f\r\na=ssrc:41117 msid:applicationsharingVideo-41117 applicationsharingVideo-41117\r\na=ssrc:41167 cname:35cfb36690cb4d77b0aa6878fb36719f\r\na=ssrc:41167 msid:applicationsharingVideo-41117 applicationsharingVideo-41117\r\na=ssrc-group:FID 41117 41167\r\na=rtcp-mux\r\na=rtcp-rsize\r\na=x-source-streamid:3620\r\nm=application 3480 UDP/DTLS/SCTP webrtc-datachannel\r\nc=IN IP4 172.172.100.250\r\na=setup:passive\r\na=mid:12\r\na=ice-ufrag:+/j1\r\na=ice-pwd:b8lcdmba8KG0mH4KA5OzM7hw\r\na=fingerprint:sha-256 DA:93:54:F4:88:DA:6D:8D:57:43:C2:A1:A7:77:CA:96:9A:60:DA:63:F0:9E:4E:D2:4E:24:16:69:74:AC:39:ED\r\na=sctp-port:5000\r\na=x-source-streamid:3621\r\n","parsedSDP":{"media":[{"type":"audio","description":"m=audio 3480 UDP/TLS/RTP/SAVPF 111 97 9 0 8 13 101","attributes":{"rtpmap":["111 OPUS/48000/2","97 RED/48000/2","9 G722/8000","0 PCMU/8000","8 PCMA/8000","13 CN/8000","101 telephone-event/8000"],"fmtp":["101 0-16","111 usedtx=1;useinbandfec=1","97 111/111"],"rtcp":["3480"],"rtcp-fb":["111 transport-cc"],"extmap":["2 http","3 http"],"setup":["passive"],"mid":["0"],"ptime":["20"],"ice-ufrag":["+/j1"],"ice-pwd":["b8lcdmba8KG0mH4KA5OzM7hw"],"fingerprint":["sha-256 DA"],"candidate":["1 1 UDP 54001663 172.172.100.250 3480 typ relay raddr 10.0.129.40 rport 3480","3 1 tcp 18087935 172.172.100.250 3478 typ relay raddr 10.0.129.40 rport 3478 tcptype passive"],"ssrc":["40116 cname","40116 msid"],"rtcp-mux":[true],"x-source-streamid":["3609"]}},{"type":"video","description":"m=video 3480 UDP/TLS/RTP/SAVPF 107 99","attributes":{"rtpmap":["107 H264/90000","99 rtx/90000"],"fmtp":["107 packetization-mode=1;profile-level-id=42C02A","99 apt=107"],"rtcp":["3480"],"rtcp-fb":["* nack","* nack pli","* goog-remb","* ccm fir","* transport-cc"],"extmap":["2 http","3 http","4 urn","10 urn","11 urn","9 http"],"setup":["passive"],"mid":["1"],"ice-ufrag":["+/j1"],"ice-pwd":["b8lcdmba8KG0mH4KA5OzM7hw"],"fingerprint":["sha-256 DA"],"ssrc":["40117 cname","40117 msid","40167 cname","40167 msid"],"ssrc-group":["FID 40117 40167"],"rtcp-mux":[true],"rtcp-rsize":[true],"rid":["1 recv","2 recv"],"simulcast":["recv ~1;~2"],"x-source-streamid":["3610"]}},{"type":"video","description":"m=video 3480 UDP/TLS/RTP/SAVPF 107 99","attributes":{"rtpmap":["107 H264/90000","99 rtx/90000"],"fmtp":["107 packetization-mode=1;profile-level-id=42C02A","99 apt=107"],"rtcp":["3480"],"rtcp-fb":["* nack","* nack pli","* goog-remb","* ccm fir","* transport-cc"],"extmap":["2 http","3 http","4 urn","10 urn","11 urn","9 http"],"setup":["passive"],"mid":["2"],"sendonly":[true],"ice-ufrag":["+/j1"],"ice-pwd":["b8lcdmba8KG0mH4KA5OzM7hw"],"fingerprint":["sha-256 DA"],"ssrc":["40217 cname","40217 msid","40267 cname","40267 msid"],"ssrc-group":["FID 40217 40267"],"rtcp-mux":[true],"rtcp-rsize":[true],"x-source-streamid":["3611"]}},{"type":"video","description":"m=video 3480 UDP/TLS/RTP/SAVPF 107 99","attributes":{"rtpmap":["107 H264/90000","99 rtx/90000"],"fmtp":["107 packetization-mode=1;profile-level-id=42C02A","99 apt=107"],"rtcp":["3480"],"rtcp-fb":["* nack","* nack pli","* goog-remb","* ccm fir","* transport-cc"],"extmap":["2 http","3 http","4 urn","10 urn","11 urn","9 http"],"setup":["passive"],"mid":["3"],"sendonly":[true],"ice-ufrag":["+/j1"],"ice-pwd":["b8lcdmba8KG0mH4KA5OzM7hw"],"fingerprint":["sha-256 DA"],"ssrc":["40317 cname","40317 msid","40367 cname","40367 msid"],"ssrc-group":["FID 40317 40367"],"rtcp-mux":[true],"rtcp-rsize":[true],"x-source-streamid":["3612"]}},{"type":"video","description":"m=video 3480 UDP/TLS/RTP/SAVPF 107 99","attributes":{"rtpmap":["107 H264/90000","99 rtx/90000"],"fmtp":["107 packetization-mode=1;profile-level-id=42C02A","99 apt=107"],"rtcp":["3480"],"rtcp-fb":["* nack","* nack pli","* goog-remb","* ccm fir","* transport-cc"],"extmap":["2 http","3 http","4 urn","10 urn","11 urn","9 http"],"setup":["passive"],"mid":["4"],"sendonly":[true],"ice-ufrag":["+/j1"],"ice-pwd":["b8lcdmba8KG0mH4KA5OzM7hw"],"fingerprint":["sha-256 DA"],"ssrc":["40417 cname","40417 msid","40467 cname","40467 msid"],"ssrc-group":["FID 40417 40467"],"rtcp-mux":[true],"rtcp-rsize":[true],"x-source-streamid":["3613"]}},{"type":"video","description":"m=video 3480 UDP/TLS/RTP/SAVPF 107 99","attributes":{"rtpmap":["107 H264/90000","99 rtx/90000"],"fmtp":["107 packetization-mode=1;profile-level-id=42C02A","99 apt=107"],"rtcp":["3480"],"rtcp-fb":["* nack","* nack pli","* goog-remb","* ccm fir","* transport-cc"],"extmap":["2 http","3 http","4 urn","10 urn","11 urn","9 http"],"setup":["passive"],"mid":["5"],"sendonly":[true],"ice-ufrag":["+/j1"],"ice-pwd":["b8lcdmba8KG0mH4KA5OzM7hw"],"fingerprint":["sha-256 DA"],"ssrc":["40517 cname","40517 msid","40567 cname","40567 msid"],"ssrc-group":["FID 40517 40567"],"rtcp-mux":[true],"rtcp-rsize":[true],"x-source-streamid":["3614"]}},{"type":"video","description":"m=video 3480 UDP/TLS/RTP/SAVPF 107 99","attributes":{"rtpmap":["107 H264/90000","99 rtx/90000"],"fmtp":["107 packetization-mode=1;profile-level-id=42C02A","99 apt=107"],"rtcp":["3480"],"rtcp-fb":["* nack","* nack pli","* goog-remb","* ccm fir","* transport-cc"],"extmap":["2 http","3 http","4 urn","10 urn","11 urn","9 http"],"setup":["passive"],"mid":["6"],"sendonly":[true],"ice-ufrag":["+/j1"],"ice-pwd":["b8lcdmba8KG0mH4KA5OzM7hw"],"fingerprint":["sha-256 DA"],"ssrc":["40617 cname","40617 msid","40667 cname","40667 msid"],"ssrc-group":["FID 40617 40667"],"rtcp-mux":[true],"rtcp-rsize":[true],"x-source-streamid":["3615"]}},{"type":"video","description":"m=video 3480 UDP/TLS/RTP/SAVPF 107 99","attributes":{"rtpmap":["107 H264/90000","99 rtx/90000"],"fmtp":["107 packetization-mode=1;profile-level-id=42C02A","99 apt=107"],"rtcp":["3480"],"rtcp-fb":["* nack","* nack pli","* goog-remb","* ccm fir","* transport-cc"],"extmap":["2 http","3 http","4 urn","10 urn","11 urn","9 http"],"setup":["passive"],"mid":["7"],"sendonly":[true],"ice-ufrag":["+/j1"],"ice-pwd":["b8lcdmba8KG0mH4KA5OzM7hw"],"fingerprint":["sha-256 DA"],"ssrc":["40717 cname","40717 msid","40767 cname","40767 msid"],"ssrc-group":["FID 40717 40767"],"rtcp-mux":[true],"rtcp-rsize":[true],"x-source-streamid":["3616"]}},{"type":"video","description":"m=video 3480 UDP/TLS/RTP/SAVPF 107 99","attributes":{"rtpmap":["107 H264/90000","99 rtx/90000"],"fmtp":["107 packetization-mode=1;profile-level-id=42C02A","99 apt=107"],"rtcp":["3480"],"rtcp-fb":["* nack","* nack pli","* goog-remb","* ccm fir","* transport-cc"],"extmap":["2 http","3 http","4 urn","10 urn","11 urn","9 http"],"setup":["passive"],"mid":["8"],"sendonly":[true],"ice-ufrag":["+/j1"],"ice-pwd":["b8lcdmba8KG0mH4KA5OzM7hw"],"fingerprint":["sha-256 DA"],"ssrc":["40817 cname","40817 msid","40867 cname","40867 msid"],"ssrc-group":["FID 40817 40867"],"rtcp-mux":[true],"rtcp-rsize":[true],"x-source-streamid":["3617"]}},{"type":"video","description":"m=video 3480 UDP/TLS/RTP/SAVPF 107 99","attributes":{"rtpmap":["107 H264/90000","99 rtx/90000"],"fmtp":["107 packetization-mode=1;profile-level-id=42C02A","99 apt=107"],"rtcp":["3480"],"rtcp-fb":["* nack","* nack pli","* goog-remb","* ccm fir","* transport-cc"],"extmap":["2 http","3 http","4 urn","10 urn","11 urn","9 http"],"setup":["passive"],"mid":["9"],"sendonly":[true],"ice-ufrag":["+/j1"],"ice-pwd":["b8lcdmba8KG0mH4KA5OzM7hw"],"fingerprint":["sha-256 DA"],"ssrc":["40917 cname","40917 msid","40967 cname","40967 msid"],"ssrc-group":["FID 40917 40967"],"rtcp-mux":[true],"rtcp-rsize":[true],"x-source-streamid":["3618"]}},{"type":"video","description":"m=video 3480 UDP/TLS/RTP/SAVPF 107 99","attributes":{"rtpmap":["107 H264/90000","99 rtx/90000"],"fmtp":["107 packetization-mode=1;profile-level-id=42C02A","99 apt=107"],"rtcp":["3480"],"rtcp-fb":["* nack","* nack pli","* goog-remb","* ccm fir","* transport-cc"],"extmap":["2 http","3 http","4 urn","10 urn","11 urn","9 http"],"setup":["passive"],"mid":["10"],"sendonly":[true],"ice-ufrag":["+/j1"],"ice-pwd":["b8lcdmba8KG0mH4KA5OzM7hw"],"fingerprint":["sha-256 DA"],"ssrc":["41017 cname","41017 msid","41067 cname","41067 msid"],"ssrc-group":["FID 41017 41067"],"rtcp-mux":[true],"rtcp-rsize":[true],"x-source-streamid":["3619"]}},{"type":"video","description":"m=video 3480 UDP/TLS/RTP/SAVPF 107 99","attributes":{"rtpmap":["107 H264/90000","99 rtx/90000"],"fmtp":["107 packetization-mode=1;profile-level-id=42C02A","99 apt=107"],"rtcp":["3480"],"rtcp-fb":["* nack","* nack pli","* goog-remb","* ccm fir","* transport-cc"],"extmap":["2 http","3 http","4 urn","10 urn","11 urn","9 http"],"setup":["passive"],"mid":["11"],"sendonly":[true],"ice-ufrag":["+/j1"],"ice-pwd":["b8lcdmba8KG0mH4KA5OzM7hw"],"fingerprint":["sha-256 DA"],"ssrc":["41117 cname","41117 msid","41167 cname","41167 msid"],"ssrc-group":["FID 41117 41167"],"rtcp-mux":[true],"rtcp-rsize":[true],"x-source-streamid":["3620"]}},{"type":"application","description":"m=application 3480 UDP/DTLS/SCTP webrtc-datachannel","attributes":{"setup":["passive"],"mid":["12"],"ice-ufrag":["+/j1"],"ice-pwd":["b8lcdmba8KG0mH4KA5OzM7hw"],"fingerprint":["sha-256 DA"],"sctp-port":["5000"],"x-source-streamid":["3621"]}}],"attributes":{"extmap-allow-mixed":[true],"msid-semantic":[" WMS *"],"group":["BUNDLE 0 1 2 3 4 5 6 7 8 9 10 11 12"],"x-mediabw":["applicationsharing-video send=8100;recv=8100"],"x-plaza-msi-range":["3409-3508 3509-3608"]}}}
*/
            // Override setLocalDescription with detailed logging
            const originalSetLocalDescription = peerConnection.setLocalDescription;
            peerConnection.setLocalDescription = async function(description) {
                console.log('Setting Local SDP:', {
                    type: description.type,
                    sdp: description.sdp,
                    parsedSDP: parseSDP(description.sdp)
                });
                return originalSetLocalDescription.apply(this, arguments);
            };

            // Override setRemoteDescription with detailed logging
            const originalSetRemoteDescription = peerConnection.setRemoteDescription;
            peerConnection.setRemoteDescription = async function(description) {
                console.log('Setting Remote SDP:', {
                    type: description.type,
                    parsedSDP: parseSDP(description.sdp)
                });
                return originalSetRemoteDescription.apply(this, arguments);
            };

            // Helper function to parse SDP into a more readable format
            function parseSDP(sdp) {
                const parsed = {
                    media: [],
                    attributes: {},
                    version: null,
                    origin: null,
                    session: null,
                    connection: null,
                    timing: null,
                    bandwidth: null
                };
            
                const lines = sdp.split('\r\n');
                let currentMedia = null;
            
                for (const line of lines) {
                    // Handle session-level fields
                    if (line.startsWith('v=')) {
                        parsed.version = line.substr(2);
                    } else if (line.startsWith('o=')) {
                        parsed.origin = line.substr(2);
                    } else if (line.startsWith('s=')) {
                        parsed.session = line.substr(2);
                    } else if (line.startsWith('c=')) {
                        parsed.connection = line.substr(2);
                    } else if (line.startsWith('t=')) {
                        parsed.timing = line.substr(2);
                    } else if (line.startsWith('b=')) {
                        parsed.bandwidth = line.substr(2);
                    } else if (line.startsWith('m=')) {
                        // Media section
                        currentMedia = {
                            type: line.split(' ')[0].substr(2),
                            description: line,
                            attributes: {},
                            connection: null,
                            bandwidth: null
                        };
                        parsed.media.push(currentMedia);
                    } else if (line.startsWith('a=')) {
                        // Handle attributes that may contain multiple colons
                        const colonIndex = line.indexOf(':');
                        let key, value;
                        
                        if (colonIndex === -1) {
                            // Handle flag attributes with no value
                            key = line.substr(2);
                            value = true;
                        } else {
                            key = line.substring(2, colonIndex);
                            value = line.substring(colonIndex + 1);
                        }
            
                        if (currentMedia) {
                            if (!currentMedia.attributes[key]) {
                                currentMedia.attributes[key] = [];
                            }
                            currentMedia.attributes[key].push(value);
                        } else {
                            if (!parsed.attributes[key]) {
                                parsed.attributes[key] = [];
                            }
                            parsed.attributes[key].push(value);
                        }
                    } else if (line.startsWith('c=') && currentMedia) {
                        currentMedia.connection = line.substr(2);
                    } else if (line.startsWith('b=') && currentMedia) {
                        currentMedia.bandwidth = line.substr(2);
                    }
                }
            
                return parsed;
            }

            return peerConnection;
        };
    }
}

// Message type definitions
const messageTypes = [
      {
        name: 'CollectionEvent',
        fields: [
            { name: 'body', fieldNumber: 1, type: 'message', messageType: 'CollectionEventBody' }
        ]
    },
    {
        name: 'CollectionEventBody',
        fields: [
            { name: 'userInfoListWrapperAndChatWrapperWrapper', fieldNumber: 2, type: 'message', messageType: 'UserInfoListWrapperAndChatWrapperWrapper' }
        ]
    },
    {
        name: 'UserInfoListWrapperAndChatWrapperWrapper',
        fields: [
            { name: 'deviceInfoWrapper', fieldNumber: 3, type: 'message', messageType: 'DeviceInfoWrapper' },
            { name: 'userInfoListWrapperAndChatWrapper', fieldNumber: 13, type: 'message', messageType: 'UserInfoListWrapperAndChatWrapper' }
        ]
    },
    {
        name: 'UserInfoListWrapperAndChatWrapper',
        fields: [
            { name: 'userInfoListWrapper', fieldNumber: 1, type: 'message', messageType: 'UserInfoListWrapper' },
            { name: 'chatMessageWrapper', fieldNumber: 4, type: 'message', messageType: 'ChatMessageWrapper', repeated: true }
        ]
    },
    {
        name: 'DeviceInfoWrapper',
        fields: [
            { name: 'deviceOutputInfoList', fieldNumber: 2, type: 'message', messageType: 'DeviceOutputInfoList', repeated: true }
        ]
    },
    {
        name: 'DeviceOutputInfoList',
        fields: [
            { name: 'deviceOutputType', fieldNumber: 2, type: 'varint' }, // Speculating that 1 = audio, 2 = video
            { name: 'streamId', fieldNumber: 4, type: 'string' },
            { name: 'deviceId', fieldNumber: 6, type: 'string' },
            { name: 'deviceOutputStatus', fieldNumber: 10, type: 'message', messageType: 'DeviceOutputStatus' }
        ]
    },
    {
        name: 'DeviceOutputStatus',
        fields: [
            { name: 'disabled', fieldNumber: 1, type: 'varint' }
        ]
    },
    // Existing message types
    {
        name: 'UserInfoListResponse',
        fields: [
            { name: 'userInfoListWrapperWrapper', fieldNumber: 2, type: 'message', messageType: 'UserInfoListWrapperWrapper' }
        ]
    },
    {
        name: 'UserInfoListResponse',
        fields: [
            { name: 'userInfoListWrapperWrapper', fieldNumber: 2, type: 'message', messageType: 'UserInfoListWrapperWrapper' }
        ]
    },
    {
        name: 'UserInfoListWrapperWrapper',
        fields: [
            { name: 'userInfoListWrapper', fieldNumber: 2, type: 'message', messageType: 'UserInfoListWrapper' }
        ]
    },
    {
        name: 'UserEventInfo',
        fields: [
            { name: 'eventNumber', fieldNumber: 1, type: 'varint' } // sequence number for the event
        ]
    },
    {
        name: 'UserInfoListWrapper',
        fields: [
            { name: 'userEventInfo', fieldNumber: 1, type: 'message', messageType: 'UserEventInfo' },
            { name: 'userInfoList', fieldNumber: 2, type: 'message', messageType: 'UserInfoList', repeated: true }
        ]
    },
    {
        name: 'UserInfoList',
        fields: [
            { name: 'deviceId', fieldNumber: 1, type: 'string' },
            { name: 'fullName', fieldNumber: 2, type: 'string' },
            { name: 'profilePicture', fieldNumber: 3, type: 'string' },
            { name: 'status', fieldNumber: 4, type: 'varint' }, // in meeting = 1 vs not in meeting = 6. kicked out = 7?
            { name: 'displayName', fieldNumber: 29, type: 'string' },
            { name: 'parentDeviceId', fieldNumber: 21, type: 'string' } // if this is present, then this is a screenshare device. The parentDevice is the person that is sharing
        ]
    },
    {
        name: 'CaptionWrapper',
        fields: [
            { name: 'caption', fieldNumber: 1, type: 'message', messageType: 'Caption' }
        ]
    },
    {
        name: 'Caption',
        fields: [
            { name: 'deviceId', fieldNumber: 1, type: 'string' },
            { name: 'captionId', fieldNumber: 2, type: 'int64' },
            { name: 'version', fieldNumber: 3, type: 'int64' },
            { name: 'text', fieldNumber: 6, type: 'string' },
            { name: 'languageId', fieldNumber: 8, type: 'int64' }
        ]
    },
    {
        name: 'ChatMessageWrapper',
        fields: [
            { name: 'chatMessage', fieldNumber: 2, type: 'message', messageType: 'ChatMessage' }
        ]
    },
    {
        name: 'ChatMessage',
        fields: [
            { name: 'messageId', fieldNumber: 1, type: 'string' },
            { name: 'deviceId', fieldNumber: 2, type: 'string' },
            { name: 'timestamp', fieldNumber: 3, type: 'int64' },
            { name: 'chatMessageContent', fieldNumber: 5, type: 'message', messageType: 'ChatMessageContent' }
        ]
    },
    {
        name: 'ChatMessageContent',
        fields: [
            { name: 'text', fieldNumber: 1, type: 'string' }
        ]
    }
];

// Generic message decoder factory
function createMessageDecoder(messageType) {
    return function decode(reader, length) {
        if (!(reader instanceof protobuf.Reader)) {
            reader = protobuf.Reader.create(reader);
        }

        const end = length === undefined ? reader.len : reader.pos + length;
        const message = {};

        while (reader.pos < end) {
            const tag = reader.uint32();
            const fieldNumber = tag >>> 3;
            
            const field = messageType.fields.find(f => f.fieldNumber === fieldNumber);
            if (!field) {
                reader.skipType(tag & 7);
                continue;
            }

            let value;
            switch (field.type) {
                case 'string':
                    value = reader.string();
                    break;
                case 'int64':
                    value = reader.int64();
                    break;
                case 'varint':
                    value = reader.uint32();
                    break;
                case 'message':
                    value = messageDecoders[field.messageType](reader, reader.uint32());
                    break;
                default:
                    reader.skipType(tag & 7);
                    continue;
            }

            if (field.repeated) {
                if (!message[field.name]) {
                    message[field.name] = [];
                }
                message[field.name].push(value);
            } else {
                message[field.name] = value;
            }
        }

        return message;
    };
}

const ws = new WebSocketClient();
window.ws = ws;
const userManager = new UserManager(ws);
const captionManager = new CaptionManager(ws);
const videoTrackManager = new VideoTrackManager(ws);

// Create decoders for all message types
const messageDecoders = {};
messageTypes.forEach(type => {
    messageDecoders[type.name] = createMessageDecoder(type);
});

function base64ToUint8Array(base64) {
    const binaryString = atob(base64);
    const bytes = new Uint8Array(binaryString.length);
    for (let i = 0; i < binaryString.length; i++) {
        bytes[i] = binaryString.charCodeAt(i);
    }
    return bytes;
}

const userMap = new Map();
new FetchInterceptor(async (response) => {
    console.log('fetch intercepted', response.url);
    const responseText = await response.text();
    console.log('responseText', responseText);
});

const handleCollectionEvent = (event) => {
  const decodedData = pako.inflate(new Uint8Array(event.data));
  //console.log(' handleCollectionEventdecodedData', decodedData);
  // Convert decoded data to base64
  const base64Data = btoa(String.fromCharCode.apply(null, decodedData));
  //console.log('Decoded collection event data (base64):', base64Data);

  const collectionEvent = messageDecoders['CollectionEvent'](decodedData);
  
  const deviceOutputInfoList = collectionEvent.body.userInfoListWrapperAndChatWrapperWrapper?.deviceInfoWrapper?.deviceOutputInfoList;
  if (deviceOutputInfoList) {
    userManager.updateDeviceOutputs(deviceOutputInfoList);
  }

  const chatMessageWrapper = collectionEvent.body.userInfoListWrapperAndChatWrapperWrapper?.userInfoListWrapperAndChatWrapper?.chatMessageWrapper;
  if (chatMessageWrapper) {
    console.log('chatMessageWrapper', chatMessageWrapper);
  }

  //console.log('deviceOutputInfoList', JSON.stringify(collectionEvent.body.userInfoListWrapperAndChatWrapperWrapper?.deviceInfoWrapper?.deviceOutputInfoList));
  //console.log('usermap', userMap.allUsersMap);
  //console.log('userInfoList And Event', collectionEvent.body.userInfoListWrapperAndChatWrapperWrapper.userInfoListWrapperAndChatWrapper.userInfoListWrapper);
  const userInfoList = collectionEvent.body.userInfoListWrapperAndChatWrapperWrapper.userInfoListWrapperAndChatWrapper.userInfoListWrapper?.userInfoList || [];
  console.log('userInfoList in collection event', userInfoList);
  // This event is triggered when a single user joins (or leaves) the meeting
  // generally this array only contains a single user
  // we can't tell whether the event is a join or leave event, so we'll assume it's a join
  // if it's a leave, then we'll pick it up from the periodic call to syncMeetingSpaceCollections
  // so there will be a lag of roughly a minute for leave events
  for (const user of userInfoList) {
    userManager.singleUserSynced(user);
  }
};

// the stream ID, not the track id in the TRACK appears in the payload of the protobuf message somewhere

const handleCaptionEvent = (event) => {
  const decodedData = new Uint8Array(event.data);
  const captionWrapper = messageDecoders['CaptionWrapper'](decodedData);
  const caption = captionWrapper.caption;
  captionManager.singleCaptionSynced(caption);
}

const handleMediaDirectorEvent = (event) => {
  console.log('handleMediaDirectorEvent', event);
  const decodedData = new Uint8Array(event.data);
  //console.log(' handleCollectionEventdecodedData', decodedData);
  // Convert decoded data to base64
  const base64Data = btoa(String.fromCharCode.apply(null, decodedData));
  console.log('Decoded media director event data (base64):', base64Data);
}

const handleMainChannelEvent = (event) => {
    realConsole?.log('handleMainChannelEvent', event);
    const decodedData = new Uint8Array(event.data);
    
    // Find the start of the JSON data (looking for '[' or '{' character)
    let jsonStart = 0;
    for (let i = 0; i < decodedData.length; i++) {
        if (decodedData[i] === 91 || decodedData[i] === 123) { // ASCII code for '[' or '{'
            jsonStart = i;
            break;
        }
    }
    
    // Extract and parse the JSON portion
    const jsonString = new TextDecoder().decode(decodedData.slice(jsonStart));
    try {
        const parsedData = JSON.parse(jsonString);
        console.log('parsedData', parsedData);
        // When you see this parsedData [{"history":[1053,2331],"type":"dsh"}]
        // it corresponds to active speaker
    } catch (e) {
        console.error('Failed to parse main channel data:', e);
    }
}

//{"version":"1.1","recognitionResults":[{"speechRecognitionServiceLatency":720.7131,"source":"Ai","duration":8400000,"userId":"8:guest:1565c9e6-7816-49d5-8270-733b8a2d92bf","id":"7dec128d-711a-4dca-9539-14bda6fac3f8/164","spokenLanguage":"en-us","trackLanguage":"en-us","text":"There's no","isFinal":false,"timestampAudioSent":39465874128118696}]}

const handleVideoTrack = async (event) => {  
  try {
    // Create processor to get raw frames
    const processor = new MediaStreamTrackProcessor({ track: event.track });
    const generator = new MediaStreamTrackGenerator({ kind: 'video' });
    
    // Add track ended listener
    event.track.addEventListener('ended', () => {
        console.log('Video track ended:', event.track.id);
        videoTrackManager.deleteVideoTrack(event.track);
    });
    
    // Get readable stream of video frames
    const readable = processor.readable;
    const writable = generator.writable;

    const firstStreamId = event.streams[0]?.id;

    // Check if of the users who are in the meeting and screensharers
    // if any of them have an associated device output with the first stream ID of this video track
    const isScreenShare = userManager
        .getCurrentUsersInMeetingWhoAreScreenSharing()
        .some(user => firstStreamId && userManager.getDeviceOutput(user.deviceId, DEVICE_OUTPUT_TYPE.VIDEO).streamId === firstStreamId);
    if (firstStreamId) {
        videoTrackManager.upsertVideoTrack(event.track, firstStreamId, isScreenShare);
    }

    // Add frame rate control variables
    const targetFPS = 24;
    const frameInterval = 1000 / targetFPS; // milliseconds between frames
    let lastFrameTime = 0;

    // Create iframe only when document is ready
    var realConsole;
    if (document.readyState === 'complete') {
        createIframe();
    } else {
        document.addEventListener('DOMContentLoaded', createIframe);
    }
    function createIframe() {
        const iframe = document.createElement('iframe');
        iframe.src = 'about:blank';
        document.body.appendChild(iframe);
        realConsole = iframe.contentWindow.console;
    }

    const transformStream = new TransformStream({
        async transform(frame, controller) {
            if (!frame) {
                return;
            }

            try {
                // Check if controller is still active
                if (controller.desiredSize === null) {
                    frame.close();
                    return;
                }

                const currentTime = performance.now();

                // Add SSRC logging
                if (event.track.getSettings) {
                    console.log('Track settings:', event.track.getSettings());
                }
                console.log('Track ID:', event.track.id);
                if (event.streams && event.streams[0]) {
                    console.log('Stream ID:', event.streams[0].id);
                    event.streams[0].getTracks().forEach(track => {
                        if (track.getStats) {
                            track.getStats().then(stats => {
                                stats.forEach(report => {
                                    if (report.type === 'outbound-rtp' || report.type === 'inbound-rtp') {
                                        console.log('RTP Stats (including SSRC):', report);
                                    }
                                });
                            });
                        }
                    });
                }

                if (Math.random() < 0.01) {
                    realConsole?.log('frame', frame);
                    realConsole?.log('handleVideoTrack', event);
                }
                

                if (firstStreamId && firstStreamId === videoTrackManager.getStreamIdToSendCached()) {
                    // Check if enough time has passed since the last frame
                    if (currentTime - lastFrameTime >= frameInterval) {
                        // Copy the frame to get access to raw data
                        const rawFrame = new VideoFrame(frame, {
                            format: 'I420'
                        });

                        // Get the raw data from the frame
                        const data = new Uint8Array(rawFrame.allocationSize());
                        rawFrame.copyTo(data);

                        /*
                        const currentFormat = {
                            width: frame.displayWidth,
                            height: frame.displayHeight,
                            dataSize: data.length,
                            format: rawFrame.format,
                            duration: frame.duration,
                            colorSpace: frame.colorSpace,
                            codedWidth: frame.codedWidth,
                            codedHeight: frame.codedHeight
                        };
                        */
                        // Get current time in microseconds (multiply milliseconds by 1000)
                        const currentTimeMicros = BigInt(Math.floor(currentTime * 1000));
                        ws.sendVideo(currentTimeMicros, firstStreamId, frame.displayWidth, frame.displayHeight, data);

                        rawFrame.close();
                        lastFrameTime = currentTime;
                    }
                }
                
                // Always enqueue the frame for the video element
                controller.enqueue(frame);
            } catch (error) {
                console.error('Error processing frame:', error);
                frame.close();
            }
        },
        flush() {
            console.log('Transform stream flush called');
        }
    });

    // Create an abort controller for cleanup
    const abortController = new AbortController();

    try {
        // Connect the streams
        await readable
            .pipeThrough(transformStream)
            .pipeTo(writable, {
                signal: abortController.signal
            })
            .catch(error => {
                if (error.name !== 'AbortError') {
                    console.error('Pipeline error:', error);
                }
            });
    } catch (error) {
        console.error('Stream pipeline error:', error);
        abortController.abort();
    }

  } catch (error) {
      console.error('Error setting up video interceptor:', error);
  }
};

const handleAudioTrack = async (event) => {
  let lastAudioFormat = null;  // Track last seen format
  
  try {
    // Create processor to get raw frames
    const processor = new MediaStreamTrackProcessor({ track: event.track });
    const generator = new MediaStreamTrackGenerator({ kind: 'audio' });
    
    // Get readable stream of audio frames
    const readable = processor.readable;
    const writable = generator.writable;

    // Transform stream to intercept frames
    const transformStream = new TransformStream({
        async transform(frame, controller) {
            if (!frame) {
                return;
            }

            try {
                // Check if controller is still active
                if (controller.desiredSize === null) {
                    frame.close();
                    return;
                }

                // Copy the audio data
                const numChannels = frame.numberOfChannels;
                const numSamples = frame.numberOfFrames;
                const audioData = new Float32Array(numChannels * numSamples);
                
                // Copy data from each channel
                for (let channel = 0; channel < numChannels; channel++) {
                    frame.copyTo(audioData.subarray(channel * numSamples, (channel + 1) * numSamples), 
                              { planeIndex: channel });
                }

                // console.log('frame', frame)
                // console.log('audioData', audioData)

                // Check if audio format has changed
                const currentFormat = {
                    numberOfChannels: frame.numberOfChannels,
                    numberOfFrames: frame.numberOfFrames,
                    sampleRate: frame.sampleRate,
                    format: frame.format,
                    duration: frame.duration
                };

                // If format is different from last seen format, send update
                if (!lastAudioFormat || 
                    JSON.stringify(currentFormat) !== JSON.stringify(lastAudioFormat)) {
                    lastAudioFormat = currentFormat;
                    ws.sendJson({
                        type: 'AudioFormatUpdate',
                        format: currentFormat
                    });
                }

                // If the audioData buffer is all zeros, then we don't want to send it
                if (audioData.every(value => value === 0)) {
                    return;
                }

                // Send audio data through websocket
                const currentTimeMicros = BigInt(Math.floor(performance.now() * 1000));
                ws.sendAudio(currentTimeMicros, audioData);

                // Pass through the original frame
                controller.enqueue(frame);
            } catch (error) {
                console.error('Error processing frame:', error);
                frame.close();
            }
        },
        flush() {
            console.log('Transform stream flush called');
        }
    });

    // Create an abort controller for cleanup
    const abortController = new AbortController();

    try {
        // Connect the streams
        await readable
            .pipeThrough(transformStream)
            .pipeTo(writable, {
                signal: abortController.signal
            })
            .catch(error => {
                if (error.name !== 'AbortError') {
                    console.error('Pipeline error:', error);
                }
            });
    } catch (error) {
        console.error('Stream pipeline error:', error);
        abortController.abort();
    }

  } catch (error) {
      console.error('Error setting up audio interceptor:', error);
  }
};

// LOOK FOR https://api.flightproxy.skype.com/api/v2/cpconv

// LOOK FOR https://teams.live.com/api/chatsvc/consumer/v1/threads?view=msnp24Equivalent&threadIds=19%3Ameeting_Y2U4ZDk5NzgtOWQwYS00YzNjLTg2ODktYmU5MmY2MGEyNzJj%40thread.v2
new RTCInterceptor({
    onPeerConnectionCreate: (peerConnection) => {
        console.log('New RTCPeerConnection created:', peerConnection);
        peerConnection.addEventListener('datachannel', (event) => {
            console.log('datachannel', event);
            console.log('datachannel label', event.channel.label);

            if (event.channel.label === "collections") {               
                event.channel.addEventListener("message", (messageEvent) => {
                    console.log('RAWcollectionsevent', messageEvent);
                    handleCollectionEvent(messageEvent);
                });
            }
        });

        peerConnection.addEventListener('track', (event) => {
            // Log the track and its associated streams

            if (event.track.kind === 'audio') {
                handleAudioTrack(event);
            }
            if (event.track.kind === 'video') {
                handleVideoTrack(event);
            }
        });

        // Log the signaling state changes
        peerConnection.addEventListener('signalingstatechange', () => {
            console.log('Signaling State:', peerConnection.signalingState);
        });

        // Log the SDP being exchanged
        const originalSetLocalDescription = peerConnection.setLocalDescription;
        peerConnection.setLocalDescription = function(description) {
            console.log('Local SDP:', description);
            return originalSetLocalDescription.apply(this, arguments);
        };

        const originalSetRemoteDescription = peerConnection.setRemoteDescription;
        peerConnection.setRemoteDescription = function(description) {
            console.log('Remote SDP:', description);
            return originalSetRemoteDescription.apply(this, arguments);
        };

        // Log ICE candidates
        peerConnection.addEventListener('icecandidate', (event) => {
            if (event.candidate) {
                console.log('ICE Candidate:', event.candidate);
            }
        });
    },
    onDataChannelCreate: (dataChannel, peerConnection) => {
        console.log('New DataChannel created:', dataChannel);
        console.log('On PeerConnection:', peerConnection);
        console.log('Channel label:', dataChannel.label);
        console.log('Channel keys:', typeof dataChannel);

        //if (dataChannel.label === 'collections') {
          //  dataChannel.addEventListener("message", (event) => {
         //       console.log('collectionsevent', event)
        //    });
        //}


      if (dataChannel.label === 'main-channel') {
        dataChannel.addEventListener("message", (mainChannelEvent) => {
            handleMainChannelEvent(mainChannelEvent);
        });
      }
    }
});

class XHRInterceptor {
    constructor(callbacks = {}) {
        this.originalXHR = window.XMLHttpRequest;
        this.callbacks = {
            onSend: callbacks.onSend || (() => {}),
            onResponse: callbacks.onResponse || (() => {}),
            onError: callbacks.onError || (() => {})
        };
        
        // Replace the global XMLHttpRequest with our interceptor
        window.XMLHttpRequest = this.createXHRProxy();
    }

    createXHRProxy() {
        const callbacks = this.callbacks;
        const OriginalXHR = this.originalXHR;
        
        return function() {
            const xhr = new OriginalXHR();
            const originalOpen = xhr.open;
            const originalSend = xhr.send;
            
            // Intercept open
            xhr.open = function(...args) {
                xhr._method = args[0];
                xhr._url = args[1];
                return originalOpen.apply(xhr, args);
            };
            
            // Intercept send
            xhr.send = function(data) {
                // Call onSend callback before sending
                callbacks.onSend({
                    method: xhr._method,
                    url: xhr._url,
                    data: data,
                    xhr: xhr
                });
                
                // Intercept response
                xhr.addEventListener('load', function() {
                    try {
                        callbacks.onResponse({
                            method: xhr._method,
                            url: xhr._url,
                            status: xhr.status,
                            response: xhr.response,
                            responseType: xhr.responseType,
                            responseHeaders: xhr.getAllResponseHeaders(),
                            xhr: xhr
                        });
                    } catch (error) {
                        console.error('Error in XHR response interceptor:', error);
                    }
                });
                
                // Intercept errors
                xhr.addEventListener('error', function() {
                    callbacks.onError({
                        method: xhr._method,
                        url: xhr._url,
                        status: xhr.status,
                        error: new Error('XHR request failed'),
                        xhr: xhr
                    });
                });
                
                return originalSend.apply(xhr, arguments);
            };
            
            return xhr;
        };
    }
    
    // Method to restore original XMLHttpRequest
    restore() {
        window.XMLHttpRequest = this.originalXHR;
    }
}


const xhrInterceptor = new XHRInterceptor({
    onSend: ({ method, url, data }) => {
        //console.log('XHR Request:', method, url, data);
    },
    onResponse: ({ method, url, status, response }) => {
        //if (JSON.stringify(response).includes("roster") || JSON.stringify(response).includes("participants")) {
          //  console.log('XHR Response:', method, url, status, response);
        //}
    },
    onError: ({ method, url, error }) => {
        //console.error('XHR Error:', method, url, error);
    }
});

function decodeWebSocketBody(encodedData) {
    const byteArray = Uint8Array.from(atob(encodedData), c => c.charCodeAt(0));
    return JSON.parse(pako.inflate(byteArray, { to: "string" }));
}

class WebSocketInterceptor {
    constructor(callbacks = {}) {
        this.originalWebSocket = window.WebSocket;
        this.callbacks = {
            onSend: callbacks.onSend || (() => {}),
            onMessage: callbacks.onMessage || (() => {}),
            onOpen: callbacks.onOpen || (() => {}),
            onClose: callbacks.onClose || (() => {}),
            onError: callbacks.onError || (() => {})
        };
        
        window.WebSocket = this.createWebSocketProxy();
    }

    createWebSocketProxy() {
        const OriginalWebSocket = this.originalWebSocket;
        const callbacks = this.callbacks;
        
        return function(url, protocols) {
            const ws = new OriginalWebSocket(url, protocols);
            
            // Intercept send
            const originalSend = ws.send;
            ws.send = function(data) {
                try {
                    callbacks.onSend({
                        url,
                        data,
                        ws
                    });
                } catch (error) {
                    console.error('Error in WebSocket send callback:', error);
                }
                
                return originalSend.apply(ws, arguments);
            };
            
            // Intercept onmessage
            ws.addEventListener('message', function(event) {
                try {
                    callbacks.onMessage({
                        url,
                        data: event.data,
                        event,
                        ws
                    });
                } catch (error) {
                    console.error('Error in WebSocket message callback:', error);
                }
            });
            
            // Intercept connection events
            ws.addEventListener('open', (event) => {
                callbacks.onOpen({ url, event, ws });
            });
            
            ws.addEventListener('close', (event) => {
                callbacks.onClose({ 
                    url, 
                    code: event.code, 
                    reason: event.reason,
                    event,
                    ws 
                });
            });
            
            ws.addEventListener('error', (event) => {
                callbacks.onError({ url, event, ws });
            });
            
            return ws;
        };
    }
}

let participantsMap = {};

function handleRosterUpdate(eventDataObject) {
    try {
        const decodedBody = decodeWebSocketBody(eventDataObject.body);
        participantsMap = {...participantsMap, ...decodedBody.participants};
        console.log('Participants Map:', Object.values(participantsMap).map(participant => participant.details.displayName));
    } catch (error) {
        console.error('Error handling roster update:', JSON.stringify(error));
        console.error('Event data:', eventDataObject);
    }
}

function handleControlVideoStreaming(eventDataObject) {
    console.log('Control Video Streaming:', eventDataObject);

    /*
    {"id":-2111465519,"method":"POST","url":"/v4/f/9w9ydfvA-0mP6oOTKm2guQ/callAgent/bdc8f7cb-6066-4e2d-ad1d-4bec95f8cbfd/5160d38d/call/controlVideoStreaming/","headers":{"Content-Length":"513","Content-Type":"application/vnd.skype.mc.v2.0+json","Host":"pub-ent-usnc-17.trouter.teams.microsoft.com","X-Microsoft-Skype-Chain-ID":"4915f618-17d0-4387-9d6c-007fd73d1eae","X-Microsoft-Skype-Message-ID":"7e1f9c49-3292-4a86-a8af-f30ee42925b6","Trouter-Timeout":"12298","X-Microsoft-Skype-Original-Message-ID":"50248f0e-5d87-4c2b-82ea-1955b26b0410","MS-CV":"A4seYNtli0Gesn4V4HCakg.1","trouter-request":"{\"id\":\"5e430968-e7b2-4e6a-9298-d7287a90033b\",\"src\":\"10.128.19.24\",\"port\":3443}","Trouter-TimeoutMs":"12798"},"body":"{\"controlVideoStreaming\":{\"sequenceNumber\":3,\"globalTimeStamp\":\"1/24/2025 1:04:00 AM\",\"controlInfo\":[{\"control\":0,\"sourceId\":2758,\"fmtParams\":\"KeyFrame=0;max-br=2083;max-fps=3000.000000;max-fs=3600;max-mbps=108000;rid=1;ssrc=3420776487;vla-debug=960x540@30x897;profile-level-id=42C02A;packetization-mode=1\",\"fmtParamsList\":[\"KeyFrame=0;max-br=2083;max-fps=3000.000000;max-fs=3600;max-mbps=108000;rid=1;ssrc=3420776487;vla-debug=960x540@30x897;profile-level-id=42C02A;packetization-mode=1\"]}]},\"debugContent\":null}"}
    */
}

// Example usage:
const wsInterceptor = new WebSocketInterceptor({
    onMessage: ({ url, data }) => {
        if (data.startsWith("3:::")) {
            const eventDataObject = JSON.parse(data.slice(4));
            
            console.log('Event Data Object:', eventDataObject.url);
            if (eventDataObject.url.endsWith("rosterUpdate/") || eventDataObject.url.endsWith("rosterUpdate")) {
                handleRosterUpdate(eventDataObject);
            }
            if (eventDataObject.url.endsWith("controlVideoStreaming/")) {
                handleControlVideoStreaming(eventDataObject);
            }
        }
    }
});


