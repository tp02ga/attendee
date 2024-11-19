import queue
import webrtcvad
from datetime import datetime

class AudioProcessingQueue:
    def __init__(self, *, save_utterance_callback, get_participant_callback):
        self.queue = queue.Queue()

        self.save_utterance_callback = save_utterance_callback
        self.get_participant_callback = get_participant_callback

        self.utterances = {}
        self.sample_rate = 32000

        self.first_nonsilent_audio_time = {}
        self.last_nonsilent_audio_time = {}

        self.BUFFER_SIZE_LIMIT = 38 * 1024 * 1024  # 38 MB in bytes ten minutes of continuous audio
        self.SILENCE_DURATION_LIMIT = 3  # seconds
        self.timeline_start = None
        self.vad = webrtcvad.Vad()

    def add_chunk(self, speaker_id, chunk_time, chunk_bytes):
        if self.timeline_start is None:
            self.timeline_start = chunk_time

        self.queue.put((speaker_id, chunk_time, chunk_bytes))

    def process_chunks(self):
        while not self.queue.empty():
            speaker_id, chunk_time, chunk_bytes = self.queue.get()
            self.process_chunk(speaker_id, chunk_time, chunk_bytes)

        for speaker_id in list(self.first_nonsilent_audio_time.keys()):
            self.process_chunk(speaker_id, datetime.utcnow(), None)

    def process_chunk(self, speaker_id, chunk_time, chunk_bytes):
        audio_is_silent = not self.vad.is_speech(chunk_bytes, self.sample_rate) if chunk_bytes else True
        
        # Initialize buffer and timing for new speaker
        if speaker_id not in self.utterances or len(self.utterances[speaker_id]) == 0:
            if audio_is_silent:
                return
            self.utterances[speaker_id] = bytearray()
            self.first_nonsilent_audio_time[speaker_id] = chunk_time
            self.last_nonsilent_audio_time[speaker_id] = chunk_time

        # Add new audio data to buffer
        if chunk_bytes:
            self.utterances[speaker_id].extend(chunk_bytes)
        
        should_flush = False
        reason = None

        # Check buffer size
        if len(self.utterances[speaker_id]) >= self.BUFFER_SIZE_LIMIT // 2:
            should_flush = True
            reason = "buffer_full"
        
        # Check for silence
        if audio_is_silent:
            silence_duration = (chunk_time - self.last_nonsilent_audio_time[speaker_id]).total_seconds()
            print(f"silence_duration = {silence_duration}")
            if silence_duration >= self.SILENCE_DURATION_LIMIT:
                should_flush = True
                reason = "silence_limit"
        else:
            self.last_nonsilent_audio_time[speaker_id] = chunk_time

        # Flush buffer if needed
        if should_flush and len(self.utterances[speaker_id]) > 0:
            self.save_utterance_callback({
                'message': "New utterance",
                **self.get_participant_callback(speaker_id),
                'audio_data': bytes(self.utterances[speaker_id]),
                'timeline_ms': int((self.first_nonsilent_audio_time[speaker_id] - self.timeline_start).total_seconds() * 1000),
                'flush_reason': reason
            })
            # Clear the buffer
            self.utterances[speaker_id] = bytearray()
            del self.first_nonsilent_audio_time[speaker_id]
            del self.last_nonsilent_audio_time[speaker_id]
