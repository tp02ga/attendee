import time
from .text_to_speech import generate_audio_from_text

class AudioOutputManager:
    def __init__(self, currently_playing_audio_media_request_finished_callback, play_raw_audio_callback):
        self.currently_playing_audio_media_request = None
        self.currently_playing_audio_media_request_started_at = None
        self.currently_playing_audio_media_request_duration_ms = None
        self.currently_playing_audio_media_request_finished_callback = currently_playing_audio_media_request_finished_callback
        self.play_raw_audio_callback = play_raw_audio_callback

    def start_playing_audio_media_request(self, audio_media_request):
        if audio_media_request.media_blob:
            # Handle raw audio blob case
            self.play_raw_audio_callback(mp3_to_pcm(audio_media_request.media_blob.blob, sample_rate=8000))
            self.currently_playing_audio_media_request_duration_ms = audio_media_request.media_blob.duration_ms
        else:
            # Handle text-to-speech case
            audio_blob, duration_ms = generate_audio_from_text(
                text=audio_media_request.text_to_speak,
                settings=audio_media_request.text_to_speech_settings
            )
            self.play_raw_audio_callback(audio_blob)
            self.currently_playing_audio_media_request_duration_ms = duration_ms

        self.currently_playing_audio_media_request = audio_media_request
        self.currently_playing_audio_media_request_started_at = time.time()

    def currently_playing_audio_media_request_is_finished(self):
        if not self.currently_playing_audio_media_request or not self.currently_playing_audio_media_request_started_at:
            return False
        elapsed_ms = (time.time() - self.currently_playing_audio_media_request_started_at) * 1000
        if elapsed_ms > self.currently_playing_audio_media_request_duration_ms:
            return True
        return False
    
    def clear_currently_playing_audio_media_request(self):
        self.currently_playing_audio_media_request = None
        self.currently_playing_audio_media_request_started_at = None

    def monitor_currently_playing_audio_media_request(self):
        if self.currently_playing_audio_media_request_is_finished():
            temp_currently_playing_audio_media_request = self.currently_playing_audio_media_request
            self.clear_currently_playing_audio_media_request()
            self.currently_playing_audio_media_request_finished_callback(temp_currently_playing_audio_media_request)
