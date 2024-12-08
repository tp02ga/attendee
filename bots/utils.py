from pydub import AudioSegment
import io

def pcm_to_mp3(pcm_data: bytes, sample_rate: int = 32000, channels: int = 1, sample_width: int = 2, bitrate: str = "128k") -> bytes:
    """
    Convert PCM audio data to MP3 format.
    
    Args:
        pcm_data (bytes): Raw PCM audio data
        sample_rate (int): Sample rate in Hz (default: 32000)
        channels (int): Number of audio channels (default: 1)
        sample_width (int): Sample width in bytes (default: 2)
        bitrate (str): MP3 encoding bitrate (default: "128k")
    
    Returns:
        bytes: MP3 encoded audio data
    """
    # Create AudioSegment from raw PCM data
    audio_segment = AudioSegment(
        data=pcm_data,
        sample_width=sample_width,
        frame_rate=sample_rate,
        channels=channels
    )

    # Create a bytes buffer to store the MP3 data
    buffer = io.BytesIO()
    
    # Export the audio segment as MP3 to the buffer with specified bitrate
    audio_segment.export(buffer, format='mp3', parameters=["-b:a", bitrate])
    
    # Get the MP3 data as bytes
    mp3_data = buffer.getvalue()
    buffer.close()
    
    return mp3_data

def mp3_to_pcm(mp3_data: bytes, sample_rate: int = 32000, channels: int = 1, sample_width: int = 2) -> bytes:
    """
    Convert MP3 audio data to PCM format.
    
    Args:
        mp3_data (bytes): MP3 audio data
        sample_rate (int): Desired sample rate in Hz (default: 32000)
        channels (int): Desired number of audio channels (default: 1)
        sample_width (int): Desired sample width in bytes (default: 2)
    
    Returns:
        bytes: Raw PCM audio data
    """
    # Create a bytes buffer from the MP3 data
    buffer = io.BytesIO(mp3_data)
    
    # Load the MP3 data into an AudioSegment
    audio_segment = AudioSegment.from_mp3(buffer)
    
    # Convert to the desired format
    audio_segment = audio_segment.set_frame_rate(sample_rate)
    audio_segment = audio_segment.set_channels(channels)
    audio_segment = audio_segment.set_sample_width(sample_width)
    
    # Get the raw PCM data
    pcm_data = audio_segment.raw_data
    buffer.close()
    
    return pcm_data
