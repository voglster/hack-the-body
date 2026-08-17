"""WhisperLive client. The protocol lands in Task 3."""
from __future__ import annotations


class WhisperLiveTranscriber:
    def __init__(self, *, host: str, port: int, model: str, timeout: float,
                 language: str = "en") -> None:
        self._host = host
        self._port = port
        self._model = model
        self._timeout = timeout
        self._language = language
