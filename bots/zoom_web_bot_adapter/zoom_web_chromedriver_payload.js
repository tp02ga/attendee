// Style manager
class StyleManager {
    constructor() {
    }

    async start() {
        console.log('StyleManager start');
    }

    async stop() {
        console.log('StyleManager stop');
    }
}

// Websocket client
class WebSocketClient {
    // Message types
    static MESSAGE_TYPES = {
        JSON: 1,
        VIDEO: 2,
        AUDIO: 3,
        ENCODED_MP4_CHUNK: 4,
        PER_PARTICIPANT_AUDIO: 5
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
    }
  
    async enableMediaSending() {
      this.mediaSendingEnabled = true;
      await window.styleManager.start();
    }
  
    async disableMediaSending() {
      window.styleManager.stop();
      // Give the media recorder a bit of time to send the final data
      await new Promise(resolve => setTimeout(resolve, 2000));
      this.mediaSendingEnabled = false;
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
  
    sendClosedCaptionUpdate(item) {
      if (!this.mediaSendingEnabled)
          return;
  
      this.sendJson({
          type: 'CaptionUpdate',
          caption: item
      });
    }
    
    sendPerParticipantAudio(participantId, audioData) {
      if (this.ws.readyState !== WebSocket.OPEN) {
        console.error('WebSocket is not connected for per participant audio send', this.ws.readyState);
        return;
      }
  
      if (!this.mediaSendingEnabled) {
        return;
      }
  
      try {
          // Convert participantId to UTF-8 bytes
          const participantIdBytes = new TextEncoder().encode(participantId);
          
          // Create final message: type (4 bytes) + participantId length (1 byte) + 
          // participantId bytes + audio data
          const message = new Uint8Array(4 + 1 + participantIdBytes.length + audioData.buffer.byteLength);
          const dataView = new DataView(message.buffer);
          
          // Set message type (5 for PER_PARTICIPANT_AUDIO)
          dataView.setInt32(0, WebSocketClient.MESSAGE_TYPES.PER_PARTICIPANT_AUDIO, true);
          
          // Set participantId length as uint8 (1 byte)
          dataView.setUint8(4, participantIdBytes.length);
          
          // Copy participantId bytes
          message.set(participantIdBytes, 5);
          
          // Copy audio data after type, length and participantId
          message.set(new Uint8Array(audioData.buffer), 5 + participantIdBytes.length);
          
          // Send the binary message
          this.ws.send(message.buffer);
      } catch (error) {
          console.error('Error sending WebSocket audio message:', error);
      }
    }
  
    sendMixedAudio(timestamp, audioData) {
        if (this.ws.readyState !== WebSocket.OPEN) {
            console.error('WebSocket is not connected for audio send', this.ws.readyState);
            return;
        }
  
        if (!this.mediaSendingEnabled) {
          return;
        }
  
        try {
            // Create final message: type (4 bytes) + audio data
            const message = new Uint8Array(4 + audioData.buffer.byteLength);
            const dataView = new DataView(message.buffer);
            
            // Set message type (3 for AUDIO)
            dataView.setInt32(0, WebSocketClient.MESSAGE_TYPES.AUDIO, true);
            
            // Copy audio data after type
            message.set(new Uint8Array(audioData.buffer), 4);
            
            // Send the binary message
            this.ws.send(message.buffer);
        } catch (error) {
            console.error('Error sending WebSocket audio message:', error);
        }
    }
  }

const ws = new WebSocketClient();
window.ws = ws;
const styleManager = new StyleManager();
window.styleManager = styleManager;