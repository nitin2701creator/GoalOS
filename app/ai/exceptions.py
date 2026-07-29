"""Exceptions raised by the shared GoalOS AI infrastructure."""


class LLMError(Exception):
    """Base exception for language-model communication failures."""


class LLMTimeoutError(LLMError):
    """Raised when the language-model service does not respond in time."""


class LLMAuthenticationError(LLMError):
    """Raised when language-model authentication is rejected."""


class LLMConnectionError(LLMError):
    """Raised when the language-model service cannot be reached."""


class LLMResponseError(LLMError):
    """Raised when the language-model service returns an invalid response."""
