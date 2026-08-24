# // Ver 2026-08-24 22:05, by gemini-3.7-flash
"""Exception hierarchy and exit code mappings for ACM."""

from typing import Any


class ACMError(Exception):
    """Base exception for all ACM errors."""

    exit_code: int = 1

    def __init__(self, message: str, *args: Any, exit_code: int | None = None) -> None:
        super().__init__(message, *args)
        self.message = message
        if exit_code is not None:
            self.exit_code = exit_code


class ConfigError(ACMError):
    """Configuration error (syntax, schema, unparsed ENV references, uninitialized config).

    Exit code: 1
    """

    exit_code = 1


class SafetyBlockedError(ACMError):
    """Safety block error (drift detected, write lock contention, whitelist violations).

    Exit code: 2
    """

    exit_code = 2


class IOFailureError(ACMError):
    """I/O or permission failures.

    Exit code: 3
    """

    exit_code = 3


class NotFoundError(ACMError):
    """Resource not found (Agent, Profile, Snapshot, Transaction).

    Exit code: 4
    """

    exit_code = 4


class UserAbortError(ACMError):
    """Operation aborted by user or interrupted (SIGINT).

    Exit code: 130
    """

    exit_code = 130
