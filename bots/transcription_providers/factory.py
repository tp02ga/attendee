import logging
from django.conf import settings
from bots.models import TranscriptionProviders

logger = logging.getLogger(__name__)


def create_provider(
    *,
    deepgram_api_key=None,
    assemblyai_api_key=None,
    interim_results=True,
    language="en",
    model=None,
    sample_rate=16000,
    metadata=None,
    callback=None,
    redaction_settings=None
):
    """
    Factory function to create the appropriate transcription provider.
    
    Returns a streaming transcriber instance based on the configured provider.
    """
    provider = getattr(settings, "ASR_PROVIDER", "deepgram").lower()
    
    if provider == "assemblyai":
        from .assemblyai import AssemblyAIStreamingTranscriber
        logger.info("Using AssemblyAI transcription provider")
        return AssemblyAIStreamingTranscriber(
            assemblyai_api_key=assemblyai_api_key or settings.ASSEMBLYAI_API_KEY,
            interim_results=interim_results,
            language=language,
            model=model,
            sample_rate=sample_rate,
            metadata=metadata,
            callback=callback,
            redaction_settings=redaction_settings
        )
    
    elif provider == "deepgram":
        try:
            from .deepgram import DeepgramStreamingTranscriber
            logger.info("Using Deepgram transcription provider")
            return DeepgramStreamingTranscriber(
                deepgram_api_key=deepgram_api_key,
                interim_results=interim_results,
                language=language,
                model=model,
                sample_rate=sample_rate,
                metadata=metadata,
                callback=callback,
                redaction_settings=redaction_settings
            )
        except ImportError:
            logger.error("Deepgram provider not available, falling back to AssemblyAI")
            from .assemblyai import AssemblyAIStreamingTranscriber
            return AssemblyAIStreamingTranscriber(
                assemblyai_api_key=assemblyai_api_key or settings.ASSEMBLYAI_API_KEY,
                interim_results=interim_results,
                language=language,
                model=model,
                sample_rate=sample_rate,
                metadata=metadata,
                callback=callback,
                redaction_settings=redaction_settings
            )
    
    else:
        # Default to AssemblyAI if unknown provider
        logger.warning(f"Unknown ASR provider '{provider}', defaulting to AssemblyAI")
        from .assemblyai import AssemblyAIStreamingTranscriber
        return AssemblyAIStreamingTranscriber(
            assemblyai_api_key=assemblyai_api_key or settings.ASSEMBLYAI_API_KEY,
            interim_results=interim_results,
            language=language,
            model=model,
            sample_rate=sample_rate,
            metadata=metadata,
            callback=callback,
            redaction_settings=redaction_settings
        )


def get_provider_for_model(transcription_provider):
    """
    Get provider based on TranscriptionProviders model choice.
    """
    if transcription_provider == TranscriptionProviders.ASSEMBLY_AI:
        return "assemblyai"
    elif transcription_provider == TranscriptionProviders.DEEPGRAM:
        return "deepgram"
    else:
        # Use configured default
        return getattr(settings, "ASR_PROVIDER", "deepgram").lower()