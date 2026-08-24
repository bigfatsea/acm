# // Ver 2026-08-24 22:05, by gemini-3.7-flash
"""Console output, rich rendering, and logging for ACM."""

import logging
import os
import sys
from collections.abc import Mapping

from rich.console import Console
from rich.table import Table

from acm.adapters import ProjectionWarning
from acm.masking import is_sensitive_key, mask_secret
from acm.state import ensure_state_dirs
from acm.status import AgentState, AgentStatusResult
from acm.util import get_env_map, get_logs_dir

_stdout_console: Console | None = None
_stderr_console: Console | None = None


def get_consoles(
    no_color: bool = False, env: Mapping[str, str] | None = None
) -> tuple[Console, Console]:
    """Get rich stdout and stderr consoles configured for color and terminal environment."""
    env_map = get_env_map(env)
    disable_color = no_color or bool(env_map.get("NO_COLOR"))

    stdout_c = Console(file=sys.stdout, no_color=disable_color, highlight=False)
    stderr_c = Console(file=sys.stderr, no_color=disable_color, highlight=False)
    return stdout_c, stderr_c


def setup_logger(verbose: bool = False, env: Mapping[str, str] | None = None) -> logging.Logger:
    """Configure standard logging to ~/.acm/logs/acm.log."""
    env_map = get_env_map(env)
    ensure_state_dirs(env_map)
    logs_dir = get_logs_dir(env_map)
    log_file = logs_dir / "acm.log"

    logger = logging.getLogger("acm")
    logger.setLevel(logging.DEBUG if verbose else logging.INFO)

    # Avoid adding multiple file handlers across calls
    if not logger.handlers:
        try:
            handler = logging.FileHandler(str(log_file), encoding="utf-8")
            handler.setFormatter(
                logging.Formatter(
                    "[%(asctime)s] [%(levelname)s] %(message)s",
                    datefmt="%Y-%m-%d %H:%M:%S",
                )
            )
            logger.addHandler(handler)
            try:
                os.chmod(log_file, 0o600)
            except OSError:
                pass
        except OSError:
            pass

    return logger


def print_status_table(
    results: list[AgentStatusResult],
    console: Console,
    verbose: bool = False,
    show_secrets: bool = False,
) -> None:
    """Render rich status table for agent states."""
    table = Table(title="ACM Agent Status", show_header=True, header_style="bold cyan")
    table.add_column("Agent", style="bold")
    table.add_column("State")
    table.add_column("Active Profile")
    table.add_column("Last Synced")
    table.add_column("Details")

    state_colors = {
        AgentState.SYNCED: "[green]SYNCED[/green]",
        AgentState.OUT_OF_SYNC: "[yellow]OUT_OF_SYNC[/yellow]",
        AgentState.DRIFTED: "[bold red]DRIFTED[/bold red]",
        AgentState.ERROR: "[bold red]ERROR[/bold red]",
        AgentState.UNMANAGED: "[dim]UNMANAGED[/dim]",
        AgentState.NOT_DETECTED: "[dim]NOT_DETECTED[/dim]",
    }

    for res in results:
        state_str = state_colors.get(res.state, str(res.state))
        active_p = res.active_profile or "(none)"
        last_synced = (
            f"{res.last_profile} ({res.last_timestamp[:14]})"
            if res.last_profile and res.last_timestamp
            else "-"
        )

        details: list[str] = []
        if res.error_message:
            details.append(f"[red]{res.error_message}[/red]")
        if res.drifts:
            for d in res.drifts:
                exp_s = (
                    mask_secret(str(d.expected), show_secrets)
                    if is_sensitive_key(d.field)
                    else str(d.expected)
                )
                fnd_s = (
                    mask_secret(str(d.found), show_secrets)
                    if is_sensitive_key(d.field)
                    else str(d.found)
                )
                details.append(f"Drift in {d.field}: expected '{exp_s}', found '{fnd_s}'")

        if verbose and not details:
            details.append(f"[dim]State: {res.state.value}[/dim]")
            if res.warnings:
                for w in res.warnings:
                    details.append(f"[yellow]Warning ({w.field}): {w.reason}[/yellow]")

        table.add_row(
            res.display_name,
            state_str,
            active_p,
            last_synced,
            "\n".join(details) if details else "-",
        )

    console.print(table)


def print_warnings(warnings: list[ProjectionWarning], console: Console) -> None:
    """Print projection warnings to stderr."""
    if not warnings:
        return
    for w in warnings:
        console.print(
            f"[yellow]⚠️  Projection warning for [{w.agent_id}]: {w.field} - {w.reason}[/yellow]"
        )
