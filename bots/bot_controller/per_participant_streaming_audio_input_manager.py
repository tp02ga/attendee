import logging
import queue
import time

import numpy as np
import webrtcvad

from bots.models import Credentials
from bots.transcription_providers.deepgram.deepgram_streaming_transcriber import DeepgramStreamingTranscriber

logger = logging.getLogger(__name__)


def calculate_normalized_rms(audio_bytes):
    samples = np.frombuffer(audio_bytes, dtype=np.int16)
    rms = np.sqrt(np.mean(np.square(samples)))
    # Normalize by max possible value for 16-bit audio (32768)
    return rms / 32768


class PerParticipantStreamingAudioInputManager:
    def __init__(self, *, save_utterance_callback, get_participant_callback, sample_rate, transcription_provider, project):
        self.queue = queue.Queue()

        self.save_utterance_callback = save_utterance_callback
        self.get_participant_callback = get_participant_callback

        self.utterances = {}
        self.sample_rate = sample_rate

        self.first_nonsilent_audio_time = {}
        self.last_nonsilent_audio_time = {}

        self.SILENCE_DURATION_LIMIT = 10  # seconds

        self.vad = webrtcvad.Vad()
        self.transcription_provider = transcription_provider
        self.streaming_transcriber_class = DeepgramStreamingTranscriber
        self.streaming_transcribers = {}
        self.chunks_buffers = {}

        self.project = project

        self.deepgram_api_key = self.get_deepgram_api_key()

    def silence_detected(self, chunk_bytes):
        if calculate_normalized_rms(chunk_bytes) < 0.0005:
            return True
        return not self.vad.is_speech(chunk_bytes, self.sample_rate)

    def get_deepgram_api_key(self):
        deepgram_credentials_record = self.project.credentials.filter(credential_type=Credentials.CredentialTypes.DEEPGRAM).first()
        if not deepgram_credentials_record:
            raise Exception("Deepgram credentials record not found")

        deepgram_credentials = deepgram_credentials_record.get_credentials()
        return deepgram_credentials["api_key"]

    def find_or_create_streaming_transcriber_for_speaker(self, speaker_id):
        if speaker_id not in self.streaming_transcribers:
            self.streaming_transcribers[speaker_id] = self.streaming_transcriber_class(deepgram_api_key=self.deepgram_api_key, sample_rate=self.sample_rate)
        return self.streaming_transcribers[speaker_id]

    def add_chunk(self, speaker_id, chunk_time, chunk_bytes):
        if self.silence_detected(chunk_bytes):
            return

        streaming_transcriber = self.find_or_create_streaming_transcriber_for_speaker(speaker_id)
        streaming_transcriber.send(chunk_bytes)

    def monitor_transcription(self):
        speakers_to_remove = []
        for speaker_id, streaming_transcriber in self.streaming_transcribers.items():
            if time.time() - streaming_transcriber.last_send_time > self.SILENCE_DURATION_LIMIT:
                streaming_transcriber.finish()
                speakers_to_remove.append(speaker_id)
                
        for speaker_id in speakers_to_remove:
            del self.streaming_transcribers[speaker_id]
