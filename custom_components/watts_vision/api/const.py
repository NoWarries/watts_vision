"""Constants for the Watts Vision cloud API."""

from http import HTTPStatus

AUTH_URL = (
    "https://auth.smarthome.wattselectronics.com/realms/watts/protocol/"
    "openid-connect/token"
)
API_URL = "https://smarthome.wattselectronics.com/api/v0.1/human"
REQUEST_TIMEOUT = 30
TOKEN_EXPIRY_SAFETY_MARGIN = 30.0
AUTH_REJECTION_STATUSES = frozenset(
    {
        HTTPStatus.BAD_REQUEST,
        HTTPStatus.UNAUTHORIZED,
        HTTPStatus.FORBIDDEN,
    }
)
