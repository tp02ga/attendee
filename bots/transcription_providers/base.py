from abc import ABC, abstractmethod
from typing import Callable, Awaitable, Optional

PartialCallback = Callable[[str, int, int], Awaitable[None]]
FinalCallback = Callable[[str, int, int], Awaitable[None]]


class RealtimeASRClient(ABC):
    """Base interface for realtime ASR providers."""
    
    @abstractmethod
    async def connect(self) -> None:
        """Connect to the ASR service."""
        pass
    
    @abstractmethod
    async def send_audio(self, pcm16: bytes) -> None:
        """Send PCM16 audio data to the ASR service."""
        pass
    
    @abstractmethod
    async def close(self) -> None:
        """Close the connection to the ASR service."""
        pass
    
    @abstractmethod
    def on_partial(self, callback: PartialCallback) -> None:
        """Register callback for partial transcription results."""
        pass
    
    @abstractmethod
    def on_final(self, callback: FinalCallback) -> None:
        """Register callback for final transcription results."""
        pass