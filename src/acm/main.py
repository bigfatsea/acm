import sys
from typing import Annotated

import typer
import typer._click as _typer_click

from acm import __version__
from acm.cli import cli_app
from acm.errors import ACMError

try:
    import typer._click as _typer_click

    _typer_click.exceptions.UsageError.exit_code = 1
except Exception:  # noqa: BLE001
    try:
        import click.exceptions as _click_exc  # type: ignore[import-not-found]

        _click_exc.UsageError.exit_code = 1
    except Exception:  # noqa: BLE001, S110
        pass


def version_callback(value: bool) -> None:
    """Print the version and exit."""
    if value:
        typer.echo(__version__)
        raise typer.Exit(code=0)


@cli_app.callback()
def main_callback(
    version: Annotated[
        bool | None,
        typer.Option(
            "--version",
            "-v",
            help="Show version and exit.",
            callback=version_callback,
            is_eager=True,
        ),
    ] = None,
) -> None:
    """Agent Config Manager."""


def main() -> int:
    """Entry point for CLI execution with error code mapping."""
    try:
        cli_app()
        return 0
    except typer.Exit as e:
        return int(e.exit_code)
    except KeyboardInterrupt:
        sys.stderr.write("\nOperation interrupted by user.\n")
        return 130
    except ACMError as e:
        sys.stderr.write(f"Error: {e.message}\n")
        return e.exit_code
    except SystemExit as e:
        return int(e.code) if isinstance(e.code, int) else 0
    except Exception as e:  # noqa: BLE001
        sys.stderr.write(f"Unexpected error: {e}\n")
        return 1


if __name__ == "__main__":
    sys.exit(main())
