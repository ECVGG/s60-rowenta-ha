"""Custom exceptions for Rowenta Series 60 integration."""

from __future__ import annotations


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


class NotConnected(S60RowentaError):
    """Raised when MQTT is not connected but operation requires it."""
    def __init__(self, message: str = "Not connected to cloud") -> None:
        super().__init__(message)


class SchedulesUnavailable(S60RowentaError):
    """Raised when schedules haven't been loaded from shadow yet."""
    def __init__(self, message: str = "Schedules not available yet") -> None:
        super().__init__(message)


class InvalidInput(S60RowentaError):
    """Raised when invalid parameter passed to service/command."""
    def __init__(self, message: str = "Invalid input") -> None:
        super().__init__(message)