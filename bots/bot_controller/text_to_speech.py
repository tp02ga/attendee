from google.cloud import texttospeech

def generate_audio_from_text(text, settings):
    """
    Generate audio from text using text-to-speech settings.
    
    Args:
        text (str): The text to convert to speech
        settings (dict): Text-to-speech configuration settings containing:
            google:
                voice_language_code (str): Language code (e.g., "en-US")
                voice_name (str): Name of the voice to use
        
    Returns:
        tuple: (bytes, int) containing:
            - Audio data in LINEAR16 format
            - Duration in milliseconds
    """
    # Create client with credentials
    client = texttospeech.TextToSpeechClient.from_service_account_file(
        "/home/nduncan/Downloads/text-to-speech-test-449821-dd6ba8df3b4c.json"
    )

    # Set up text input
    synthesis_input = texttospeech.SynthesisInput(text=text)

    # Get Google settings
    google_settings = settings.get('google', {})
    language_code = google_settings.get('voice_language_code')
    voice_name = google_settings.get('voice_name')

    # Build voice parameters
    voice = texttospeech.VoiceSelectionParams(
        language_code=language_code,
        name=voice_name
    )

    # Configure audio output as PCM (LINEAR16)
    audio_config = texttospeech.AudioConfig(
        audio_encoding=texttospeech.AudioEncoding.LINEAR16,
        sample_rate_hertz=8000  # Using 8kHz sample rate
    )

    # Perform the text-to-speech request
    response = client.synthesize_speech(
        input=synthesis_input,
        voice=voice,
        audio_config=audio_config
    )

    # Calculate duration in milliseconds
    # For LINEAR16: 2 bytes per sample, sample_rate samples per second
    bytes_per_sample = 2
    duration_ms = int((len(response.audio_content) / bytes_per_sample / 8000) * 1000)

    # Return both audio content and duration
    return response.audio_content, duration_ms 