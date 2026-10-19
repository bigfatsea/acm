"""Entry point: Typer app, error-to-exit-code mapping, and the ``acm <agent>`` shorthand."""

import sys
from typing import Annotated

import typer

from acm import __version__
from acm.core.errors import ACMError

app = typer.Typer(
    name="acm",
    help="Agent Config Manager — declarative, non-destructive model config for AI coding agents.",
    no_args_is_help=True,
    add_completion=False,
    pretty_exceptions_enable=False,
)


def _version_callback(value: bool) -> None:
    if value:
        typer.echo(__version__)
        raise typer.Exit(code=0)


@app.callback()
def _root(
    version: Annotated[
        bool | None,
        typer.Option(
            "--version",
            "-V",
            help="Show version and exit.",
            callback=_version_callback,
            is_eager=True,
        ),
    ] = None,
) -> None:
    """Agent Config Manager."""


def _register_commands() -> None:
    # Imported for their side effect of registering commands on ``app``.
    from acm.cli import commands  # noqa: F401


def _apply_agent_shorthand(argv: list[str]) -> list[str]:
    """Rewrite ``acm <agent> ...`` into ``acm run <agent> ...`` for agent names."""
    from acm.adapters.registry import find_adapter

    if len(argv) < 2 or argv[1].startswith("-"):
        return argv
    known = {
        c.name or c.callback.__name__.replace("_", "-")
        for c in app.registered_commands
        if c.callback
    }
    if argv[1] in known:
        return argv
    if find_adapter(argv[1]) is not None:
        return [argv[0], "run", *argv[1:]]
    return argv


def main(argv: list[str] | None = None) -> int:
    """CLI entry point; returns the process exit code."""
    args = list(sys.argv if argv is None else argv)
    _register_commands()
    args = _apply_agent_shorthand(args)
    try:
        app(args=args[1:], standalone_mode=False)
        return 0
    except typer.Exit as e:
        return int(e.exit_code)
    except KeyboardInterrupt:
        sys.stderr.write("\ninterrupted\n")
        return 130
    except ACMError as e:
        sys.stderr.write(f"error: {e.message}\n")
        return e.exit_code
    except SystemExit as e:
        return int(e.code) if isinstance(e.code, int) else 0
    except Exception as e:
        name = type(e).__name__
        if name in {"UsageError", "BadParameter", "MissingParameter", "NoSuchOption"}:
            sys.stderr.write(f"error: {e}\n")
            return 1
        sys.stderr.write(f"unexpected error: {name}: {e}\n")
        return 1


if __name__ == "__main__":
    sys.exit(main())
