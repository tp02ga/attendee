import asyncio
import base64
import json
import logging
import time
from typing import Optional, Dict, Any

import websockets
from django.conf import settings

logger = logging.getLogger(__name__)


class AssemblyAIStreamingTranscriber:
    """AssemblyAI realtime WebSocket transcription client."""
    
    def __init__(
        self,
        *,
        assemblyai_api_key: Optional[str] = None,
        interim_results: bool = True,
        language: str = "en",
        model: Optional[str] = None,
        sample_rate: int = 16000,
        metadata: Optional[list] = None,
        callback: Optional[str] = None,
        redaction_settings: Optional[Dict[str, Any]] = None
    ):
        self.api_key = assemblyai_api_key or settings.ASSEMBLYAI_API_KEY
        self.url = settings.ASSEMBLYAI_REALTIME_URL
        self.interim_results = interim_results
        self.language = language
        self.model = model
        self.sample_rate = sample_rate
        self.metadata = metadata
        self.callback = callback
        self.redaction_settings = redaction_settings
        
        self.ws = None
        self.last_send_time = time.time()
        self.session_begins_sent = False
        self._running = False
        self._receive_task = None
        
        # Callbacks
        self.on_message_callback = None
        self.on_error_callback = None
        
    def on(self, event_type: str, callback):
        """Register event callbacks compatible with Deepgram interface."""
        if event_type == "Transcript" or event_type == "LiveTranscriptionEvents.Transcript":
            self.on_message_callback = callback
        elif event_type == "Error" or event_type == "LiveTranscriptionEvents.Error":
            self.on_error_callback = callback
    
    async def _connect(self) -> None:
        """Establish WebSocket connection to AssemblyAI."""
        headers = {
            "Authorization": self.api_key
        }
        
        # Build URL with parameters
        url = self.url
        if '?' not in url:
            url += f"?sample_rate={self.sample_rate}"
        
        try:
            self.ws = await websockets.connect(url, extra_headers=headers)
            self._running = True
            logger.info("Connected to AssemblyAI realtime transcription")
            
            # Start receive task
            self._receive_task = asyncio.create_task(self._receive_messages())
            
            # Send session begins
            await self._send_session_begins()
            
        except Exception as e:
            logger.error(f"Failed to connect to AssemblyAI: {e}")
            if self.on_error_callback:
                self.on_error_callback(self, str(e))
            raise
    
    async def _send_session_begins(self) -> None:
        """Send session configuration to AssemblyAI."""
        if self.session_begins_sent:
            return
            
        config = {
            "message_type": "SessionBegins",
            "encoding": "pcm_s16le",
            "sample_rate": self.sample_rate
        }
        
        # Add optional parameters
        if self.language:
            config["language_code"] = self.language
        if self.redaction_settings:
            config.update(self.redaction_settings)
            
        await self.ws.send(json.dumps(config))
        self.session_begins_sent = True
        logger.debug("Sent SessionBegins message to AssemblyAI")
    
    async def _receive_messages(self) -> None:
        """Receive and process messages from AssemblyAI."""
        while self._running:
            try:
                message = await self.ws.recv()
                data = json.loads(message)
                
                if data.get("message_type") == "FinalTranscript":
                    text = data.get("text", "")
                    if text and self.on_message_callback:
                        # Create result object compatible with Deepgram
                        result = type('obj', (object,), {
                            'channel': type('obj', (object,), {
                                'alternatives': [
                                    type('obj', (object,), {
                                        'transcript': text
                                    })()
                                ]
                            })()
                        })()
                        self.on_message_callback(self, result)
                        logger.info(f"AssemblyAI transcription: {text}")
                        
                elif data.get("message_type") == "PartialTranscript":
                    if self.interim_results:
                        text = data.get("text", "")
                        if text and self.on_message_callback:
                            # Create result object compatible with Deepgram
                            result = type('obj', (object,), {
                                'channel': type('obj', (object,), {
                                    'alternatives': [
                                        type('obj', (object,), {
                                            'transcript': text
                                        })()
                                    ]
                                })()
                            })()
                            self.on_message_callback(self, result)
                            logger.debug(f"AssemblyAI partial: {text}")
                            
                elif data.get("error"):
                    error_msg = data.get("error")
                    logger.error(f"AssemblyAI error: {error_msg}")
                    if self.on_error_callback:
                        self.on_error_callback(self, error_msg)
                        
            except websockets.exceptions.ConnectionClosed:
                logger.info("AssemblyAI WebSocket connection closed")
                break
            except Exception as e:
                logger.error(f"Error receiving AssemblyAI message: {e}")
                if self.on_error_callback:
                    self.on_error_callback(self, str(e))
                break
    
    def start(self, options=None):
        """Start the transcription session (synchronous wrapper for compatibility)."""
        # Since original Deepgram uses synchronous start, we create event loop if needed
        try:
            loop = asyncio.get_event_loop()
        except RuntimeError:
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
        
        if loop.is_running():
            # If loop is already running, schedule the coroutine
            asyncio.create_task(self._connect())
        else:
            # If loop is not running, run until complete
            loop.run_until_complete(self._connect())
    
    def send(self, audio_data: bytes) -> None:
        """Send audio data to AssemblyAI (synchronous wrapper)."""
        if not self.ws or not self._running:
            logger.warning("Cannot send audio - not connected to AssemblyAI")
            return
            
        # Base64 encode the audio data
        encoded = base64.b64encode(audio_data).decode('utf-8')
        message = json.dumps({
            "message_type": "AudioData",
            "audio_data": encoded
        })
        
        # Send asynchronously
        try:
            loop = asyncio.get_event_loop()
            if loop.is_running():
                asyncio.create_task(self.ws.send(message))
            else:
                loop.run_until_complete(self.ws.send(message))
            self.last_send_time = time.time()
        except Exception as e:
            logger.error(f"Error sending audio to AssemblyAI: {e}")
    
    def finish(self) -> None:
        """Finish the transcription session and close connection."""
        if self.ws and self._running:
            self._running = False
            
            # Send terminate stream message
            terminate_msg = json.dumps({"message_type": "TerminateStream"})
            
            try:
                loop = asyncio.get_event_loop()
                if loop.is_running():
                    asyncio.create_task(self._finish_async(terminate_msg))
                else:
                    loop.run_until_complete(self._finish_async(terminate_msg))
            except Exception as e:
                logger.error(f"Error finishing AssemblyAI session: {e}")
    
    async def _finish_async(self, terminate_msg: str) -> None:
        """Async helper to finish the session."""
        try:
            await self.ws.send(terminate_msg)
            await asyncio.sleep(0.5)  # Give time for final messages
            await self.ws.close()
            if self._receive_task:
                self._receive_task.cancel()
        except Exception as e:
            logger.error(f"Error in _finish_async: {e}")
        finally:
            self.ws = None
            self._running = False