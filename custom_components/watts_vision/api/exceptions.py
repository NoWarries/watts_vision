"""Exceptions raised by the Watts Vision cloud API client."""


class WattsVisionError(Exception):
    """Base error raised by the Watts Vision API client."""


class WattsVisionAuthenticationError(WattsVisionError):
    """Raised when Watts Vision credentials are rejected."""


class WattsVisionConnectionError(WattsVisionError):
    """Raised when the Watts Vision service cannot be reached."""


class WattsVisionCommunicationStaleError(WattsVisionError):
    """Raised when a central unit is too stale to accept a command."""

    def __init__(self, age_seconds: int) -> None:
        """Initialize the stale communication error."""
        self.age_seconds = age_seconds
        super().__init__(
            f"Watts Vision central unit last communicated {age_seconds} seconds ago"
        )


class WattsVisionResponseError(WattsVisionError):
    """Raised when Watts Vision returns an invalid or rejected response."""
