"""Exceptions raised by the Watts Vision cloud API client."""


class WattsVisionError(Exception):
    """Base error raised by the Watts Vision API client."""


class WattsVisionAuthenticationError(WattsVisionError):
    """Raised when Watts Vision credentials are rejected."""


class WattsVisionConnectionError(WattsVisionError):
    """Raised when the Watts Vision service cannot be reached."""


class WattsVisionResponseError(WattsVisionError):
    """Raised when Watts Vision returns an invalid or rejected response."""
