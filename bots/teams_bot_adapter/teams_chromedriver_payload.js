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

    convertUser(user) {
        return {
            deviceId: user.details.id,
            displayName: user.details.displayName,
            fullName: user.details.displayName,
            profile: '',
            status: user.state,
            humanized_status: user.state || "unknown",
        }
    }

    singleUserSynced(user) {
      const convertedUser = this.convertUser(user);
      console.log('singleUserSynced called w', convertedUser);
      // Create array with new user and existing users, then filter for unique deviceIds
      // keeping the first occurrence (new user takes precedence)
      const allUsers = [...this.currentUsersMap.values(), convertedUser];
      console.log('allUsers', allUsers);
      const uniqueUsers = Array.from(
        new Map(allUsers.map(user => [user.deviceId, convertedUser])).values()
      );
      this.newUsersListSynced(uniqueUsers);
    }

    newUsersListSynced(newUsersList) {
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
var realConsole;
// Websocket client
class WebSocketClient {
    // Message types
    static MESSAGE_TYPES = {
        JSON: 1,
        VIDEO: 2,  // Reserved for future use
        AUDIO: 3   // Reserved for future use
    };
  
    constructor() {
        const url = `ws://localhost:${window.initialData.websocketPort}`;
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
        if (this.ws.readyState !== originalWebSocket.OPEN) {
            realConsole?.error('WebSocket is not connected');
            realConsole?.error(this.ws);
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
  
    
  
    sendAudio(timestamp, streamId, audioData) {
        if (this.ws.readyState !== originalWebSocket.OPEN) {
            console.error('WebSocket is not connected for audio send', this.ws.readyState);
            return;
        }
  
  
        if (!this.mediaSendingEnabled) {
          return;
        }
  
        try {
            // Create final message: type (4 bytes) + timestamp (8 bytes) + audio data
            const message = new Uint8Array(4 + 8 + 4 + audioData.buffer.byteLength);
            const dataView = new DataView(message.buffer);
            
            // Set message type (3 for AUDIO)
            dataView.setInt32(0, WebSocketClient.MESSAGE_TYPES.AUDIO, true);
            
            // Set timestamp as BigInt64
            dataView.setBigInt64(4, BigInt(timestamp), true);
  
            // Set streamId length and bytes
            dataView.setInt32(12, streamId, true);
  
            // Copy audio data after type and timestamp
            message.set(new Uint8Array(audioData.buffer), 16);
            
            // Send the binary message
            this.ws.send(message.buffer);
        } catch (error) {
            console.error('Error sending WebSocket audio message:', error);
        }
    }
  
    sendVideo(timestamp, streamId, width, height, videoData) {
        if (this.ws.readyState !== originalWebSocket.OPEN) {
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
                    realConsole?.log('Error in WebSocket send callback:');
                    realConsole?.log(error);
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
                    realConsole?.log('Error in WebSocket message callback:');
                    realConsole?.log(error);
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

function decodeWebSocketBody(encodedData) {
    const byteArray = Uint8Array.from(atob(encodedData), c => c.charCodeAt(0));
    return JSON.parse(pako.inflate(byteArray, { to: "string" }));
}

function handleRosterUpdate(eventDataObject) {
    try {
        const decodedBody = decodeWebSocketBody(eventDataObject.body);
        console.log(decodedBody.participants);
        const participants = Object.values(decodedBody.participants);

        for (const participant of participants) {
            window.userManager.singleUserSynced(participant);
        }
    } catch (error) {
        realConsole?.error('Error handling roster update:');
        realConsole?.error(error);
    }
}

const originalWebSocket = window.WebSocket;
// Example usage:
const wsInterceptor = new WebSocketInterceptor({
    onMessage: ({ url, data }) => {
        if (data.startsWith("3:::")) {
            const eventDataObject = JSON.parse(data.slice(4));
            
            console.log('Event Data Object:', eventDataObject.url);
            if (eventDataObject.url.endsWith("rosterUpdate/") || eventDataObject.url.endsWith("rosterUpdate")) {
                handleRosterUpdate(eventDataObject);
            }
            /*
            Not sure if this is needed
            if (eventDataObject.url.endsWith("controlVideoStreaming/")) {
                handleControlVideoStreaming(eventDataObject);
            }
            */
        }
    }
});


const ws = new WebSocketClient();
window.ws = ws;
const userManager = new UserManager(ws);
window.userManager = userManager;

if (!realConsole) {
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
}