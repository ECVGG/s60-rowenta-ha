"""Custom exceptions for Rowenta Series 60 integration."""

from __future__ import annotations

from homeassistant.exceptions import HomeAssistantError

from .const import DOMAIN


class S60RowentaError(Exception):
    """Base exception for S60 Rowenta integration."""


class AuthFailed(S60RowentaError):
    """Raised when authentication fails."""
    def __init__(self, message: str = "Authentication failed") -> None:
        super().__init__(message)


class CloudUnreachable(S60RowentaError):
    """Raised when cloud communication fails."""
    def __init__(self, message: str = "Cloud unreachable") -> None:
        super().__init__(message)


class ProtocolMismatch(S60RowentaError):
    """Raised when cloud returns unexpected data format."""
    def __init__(self, message: str = "Protocol mismatch") -> None:
        super().__init__(message)


class NotConnected(HomeAssistantError):
    """Raised when MQTT is not connected but operation requires it."""

    def __init__(self) -> None:
        super().__init__(translation_domain=DOMAIN, translation_key="no_connection")


class SchedulesUnavailable(HomeAssistantError):
    """Raised when schedules haven't been loaded from shadow yet."""

    def __init__(self) -> None:
        super().__init__(translation_domain=DOMAIN, translation_key="sched_unavailable")
