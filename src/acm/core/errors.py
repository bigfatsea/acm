"""Exception hierarchy and exit-code mapping.

Exit codes: 0 ok/no-op · 1 config error · 2 safety block · 3 I/O failure ·
4 not found · 130 SIGINT.
"""

from typing import Any


class ACMError(Exception):
    """Base class for all expected ACM failures."""

    exit_code: int = 1

    def __init__(self, message: str, *args: Any, exit_code: int | None = None) -> None:
        super().__init__(message, *args)
        self.message = message
        if exit_code is not None:
            self.exit_code = exit_code


class ConfigError(ACMError):
    """Bad configuration: syntax, schema, unresolved references, invalid Manifest. Exit 1."""

    exit_code = 1


class SafetyBlockedError(ACMError):
    """A safety rule blocked the operation: drift, lock, whitelist, validation. Exit 2."""

    exit_code = 2


class IOFailureError(ACMError):
    """I/O, permission or network failure. Exit 3."""

    exit_code = 3


class NotFoundError(ACMError):
    """Agent, profile, history entry or file not found. Exit 4."""

    exit_code = 4


class UserAbortError(ACMError):
    """The user declined or interrupted the operation. Exit 130."""

    exit_code = 130


class FormatError(ACMError):
    """A managed file could not be parsed or edited by the format layer. Exit 2."""

    exit_code = 2
