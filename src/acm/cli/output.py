"""Terminal output: stdout for results, stderr for warnings and errors."""

import sys
from pathlib import Path
from typing import Any

from rich.console import Console

from acm.core.masking import mask_value_at
from acm.formats.base import MISSING, KeyPath, fmt_path, leaf_changes

_STYLES = {
    "SYNCED": "green", "OUT_OF_SYNC": "yellow", "DRIFTED": "red", "ERROR": "bold red",
    "UNMANAGED": "dim", "NOT_DETECTED": "dim", "written": "green", "noop": "dim",
    "dry_run": "cyan", "blocked": "red", "error": "bold red", "unmanaged": "yellow",
}  # fmt: skip


class Out:
    def __init__(self, *, no_color: bool = False) -> None:
        self._out = Console(
            file=sys.stdout, no_color=no_color, highlight=False, soft_wrap=True, markup=False
        )
        self._err = Console(
            file=sys.stderr, no_color=no_color, highlight=False, soft_wrap=True, markup=False
        )

    def line(self, text: str = "") -> None:
        self._out.print(text)

    def styled(self, text: str, style_key: str) -> None:
        self._out.print(text, style=_STYLES.get(style_key, ""))

    def err(self, text: str) -> None:
        self._err.print(text)

    def warn(self, text: str) -> None:
        self._err.print(f"warning: {text}", style="yellow")

    def tag(self, key: str, width: int = 12) -> str:
        return key.ljust(width)


def show_value(path: KeyPath, value: Any, show_secrets: bool) -> str:
    if value is MISSING:
        return "(absent)"
    return repr(mask_value_at(path, value, show_secrets))


def field_line(path: KeyPath, before: Any, after: Any, show_secrets: bool) -> str:
    return (
        f"{fmt_path(path)}: {show_value(path, before, show_secrets)} -> "
        f"{show_value(path, after, show_secrets)}"
    )


def field_lines(
    path: KeyPath, before: Any, after: Any, show_secrets: bool, file: Path | None = None
) -> list[str]:
    """One line per changed leaf, so a managed subtree (a whole provider entry) does not print
    as two near-identical dumps. An empty path is a whole file acm owns."""
    if path == ():
        name = file.name if file is not None else "file"
        what = "created" if before is MISSING else "removed" if after is MISSING else "replaced"
        return [f"{name}: {what}"]
    return [field_line(p, a, b, show_secrets) for p, a, b in leaf_changes(path, before, after)]
