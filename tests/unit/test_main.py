# // Ver 2026-08-24 22:05, by gemini-3.7-flash
"""Unit tests for main() entrypoint and exit code mappings."""

from unittest.mock import patch

import typer

from acm.errors import SafetyBlockedError
from acm.main import main


def test_main_success() -> None:
    """Test main returns 0 on successful run."""
    with patch("acm.main.cli_app") as mock_cli:
        mock_cli.return_value = None
        assert main() == 0


def test_main_safety_blocked_exit_2() -> None:
    """Test main returns 2 on SafetyBlockedError."""
    with patch("acm.main.cli_app", side_effect=SafetyBlockedError("blocked")):
        assert main() == 2


def test_click_usage_error_exit_code_configured_to_1() -> None:
    """Test typer/click UsageError default exit_code is configured to 1."""
    import typer._click as _typer_click

    err = _typer_click.exceptions.UsageError("invalid syntax")
    assert err.exit_code == 1


def test_main_typer_exit_preserved() -> None:
    """Test main preserves explicit typer.Exit codes (like 2, 4)."""
    with patch("acm.main.cli_app", side_effect=SystemExit(2)):
        assert main() == 2
    with patch("acm.main.cli_app", side_effect=typer.Exit(code=4)):
        assert main() == 4
