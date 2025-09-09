import logging
import queue
import time

import numpy as np
import webrtcvad

from bots.models import Credentials, TranscriptionProviders
from bots.transcription_providers.factory import create_provider, get_provider_for_model
try:
    from bots.transcription_providers.deepgram.deepgram_streaming_transcriber import DeepgramStreamingTranscriber
except ImportError:
    DeepgramStreamingTranscriber = None

logger = logging.getLogger(__name__)


def calculate_normalized_rms(audio_bytes):
    samples = np.frombuffer(audio_bytes, dtype=np.int16)
    rms = np.sqrt(np.mean(np.square(samples)))
    # Normalize by max possible value for 16-bit audio (32768)
    return rms / 32768


class PerParticipantStreamingAudioInputManager:
    def __init__(self, *, save_utterance_callback, get_participant_callback, sample_rate, transcription_provider, bot):
        self.queue = queue.Queue()

        self.save_utterance_callback = save_utterance_callback
        self.get_participant_callback = get_participant_callback

        self.utterances = {}
        self.sample_rate = sample_rate

        self.last_nonsilent_audio_time = {}

        self.SILENCE_DURATION_LIMIT = 10  # seconds

        self.vad = webrtcvad.Vad()
        self.transcription_provider = transcription_provider
        self.streaming_transcribers = {}
        self.last_nonsilent_audio_time = {}

        self.project = bot.project
        self.bot = bot
        self.deepgram_api_key = self.get_deepgram_api_key()
        self.assemblyai_api_key = self.get_assemblyai_api_key()

    def silence_detected(self, chunk_bytes):
        if calculate_normalized_rms(chunk_bytes) < 0.0025:
            return True
        return not self.vad.is_speech(chunk_bytes, self.sample_rate)

    def get_deepgram_api_key(self):
        deepgram_credentials_record = self.project.credentials.filter(credential_type=Credentials.CredentialTypes.DEEPGRAM).first()
        if not deepgram_credentials_record:
            return None

        deepgram_credentials = deepgram_credentials_record.get_credentials()
        return deepgram_credentials["api_key"]
    
    def get_assemblyai_api_key(self):
        # First check for credentials in database
        assemblyai_credentials_record = self.project.credentials.filter(credential_type=Credentials.CredentialTypes.ASSEMBLY_AI).first()
        if assemblyai_credentials_record:
            assemblyai_credentials = assemblyai_credentials_record.get_credentials()
            return assemblyai_credentials.get("api_key")
        
        # Fall back to environment variable
        from django.conf import settings
        return getattr(settings, "ASSEMBLYAI_API_KEY", None)

    def create_streaming_transcriber(self, speaker_id, metadata):
        logger.info(f"Creating streaming transcriber for speaker {speaker_id}")
        
        metadata_list = [f"{key}:{value}" for key, value in metadata.items()] if metadata else None
        
        if self.transcription_provider == TranscriptionProviders.DEEPGRAM:
            if DeepgramStreamingTranscriber:
                return DeepgramStreamingTranscriber(
                    deepgram_api_key=self.deepgram_api_key,
                    interim_results=True,
                    language=self.bot.deepgram_language(),
                    model=self.bot.deepgram_model(),
                    callback=self.bot.deepgram_callback(),
                    sample_rate=self.sample_rate,
                    metadata=metadata_list,
                    redaction_settings=self.bot.deepgram_redaction_settings(),
                )
            else:
                logger.warning("Deepgram not available, falling back to factory")
                return create_provider(
                    deepgram_api_key=self.deepgram_api_key,
                    interim_results=True,
                    language=self.bot.deepgram_language(),
                    model=self.bot.deepgram_model(),
                    callback=self.bot.deepgram_callback(),
                    sample_rate=self.sample_rate,
                    metadata=metadata_list,
                    redaction_settings=self.bot.deepgram_redaction_settings(),
                )
        
        elif self.transcription_provider == TranscriptionProviders.ASSEMBLY_AI:
            return create_provider(
                assemblyai_api_key=self.assemblyai_api_key,
                interim_results=True,
                language=self.bot.deepgram_language(),  # Can use same language settings
                model=self.bot.deepgram_model(),
                callback=self.bot.deepgram_callback(),
                sample_rate=self.sample_rate,
                metadata=metadata_list,
                redaction_settings=self.bot.deepgram_redaction_settings(),
            )
        
        else:
            # Use factory for other providers or default
            provider = get_provider_for_model(self.transcription_provider)
            logger.info(f"Using factory for provider: {provider}")
            return create_provider(
                deepgram_api_key=self.deepgram_api_key,
                assemblyai_api_key=self.assemblyai_api_key,
                interim_results=True,
                language=self.bot.deepgram_language(),
                model=self.bot.deepgram_model(),
                callback=self.bot.deepgram_callback(),
                sample_rate=self.sample_rate,
                metadata=metadata_list,
                redaction_settings=self.bot.deepgram_redaction_settings(),
            )

    def find_or_create_streaming_transcriber_for_speaker(self, speaker_id):
        if speaker_id not in self.streaming_transcribers:
            metadata = {"bot_id": self.bot.object_id, **(self.bot.metadata or {}), **self.get_participant_callback(speaker_id)}
            self.streaming_transcribers[speaker_id] = self.create_streaming_transcriber(speaker_id, metadata)
        return self.streaming_transcribers[speaker_id]

    def add_chunk(self, speaker_id, chunk_time, chunk_bytes):
        # Check if we have necessary API keys based on provider
        if self.transcription_provider == TranscriptionProviders.DEEPGRAM and not self.deepgram_api_key:
            return
        elif self.transcription_provider == TranscriptionProviders.ASSEMBLY_AI and not self.assemblyai_api_key:
            return

        audio_is_silent = self.silence_detected(chunk_bytes)

        if not audio_is_silent:
            self.last_nonsilent_audio_time[speaker_id] = time.time()

        if audio_is_silent and speaker_id not in self.streaming_transcribers:
            return

        streaming_transcriber = self.find_or_create_streaming_transcriber_for_speaker(speaker_id)
        streaming_transcriber.send(chunk_bytes)

    def monitor_transcription(self):
        speakers_to_remove = []
        for speaker_id, streaming_transcriber in self.streaming_transcribers.items():
            if time.time() - self.last_nonsilent_audio_time[speaker_id] > self.SILENCE_DURATION_LIMIT:
                streaming_transcriber.finish()
                speakers_to_remove.append(speaker_id)
                logger.info(f"Speaker {speaker_id} has been silent for too long, stopping streaming transcriber")

        for speaker_id in speakers_to_remove:
            del self.streaming_transcribers[speaker_id]

        # If Number of streaming transcibers is greater than 4, then stop the oldest one
        if len(self.streaming_transcribers) > 4:
            oldest_transcriber = min(self.streaming_transcribers.values(), key=lambda x: x.last_send_time)
            oldest_transcriber.finish()
            del self.streaming_transcribers[oldest_transcriber.speaker_id]
            logger.info(f"Stopped oldest streaming transcriber for speaker {oldest_transcriber.speaker_id}")
