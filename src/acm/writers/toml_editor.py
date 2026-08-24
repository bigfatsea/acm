# // Ver 2026-08-24 22:05, by gemini-3.7-flash
"""Round-trip TOML editor using tomlkit with dot-path support."""

from typing import Any

import tomlkit
from tomlkit.items import Item, Table

from acm.writers.json_editor import NOT_FOUND


def read_toml_path(content: str, dot_path: str, default: Any = NOT_FOUND) -> Any:
    """Read a value at a dot_path from a TOML string."""
    if not content.strip():
        return default

    try:
        doc = tomlkit.parse(content)
    except tomlkit.exceptions.TOMLKitError:
        return default

    parts = [p.strip() for p in dot_path.split(".") if p.strip()]
    curr: Any = doc
    for part in parts:
        if isinstance(curr, (dict, Table)) and part in curr:
            curr = curr[part]
        else:
            return default

    # Convert tomlkit primitive items to python types if applicable
    if isinstance(curr, Item):
        return curr.unwrap()
    return curr


def set_toml_path(content: str, dot_path: str, value: Any) -> str:
    """Set a value at a dot_path in a TOML string, creating tables as necessary and preserving formatting."""
    if content.strip():
        try:
            doc = tomlkit.parse(content)
        except (tomlkit.exceptions.TOMLKitError, ValueError, IndexError):
            doc = tomlkit.document()
    else:
        doc = tomlkit.document()

    parts = [p.strip() for p in dot_path.split(".") if p.strip()]
    if not parts:
        raise ValueError("dot_path cannot be empty")

    curr: Any = doc
    for part in parts[:-1]:
        if part not in curr or not isinstance(curr[part], (dict, Table)):
            new_table = tomlkit.table()
            curr[part] = new_table
            curr = new_table
        else:
            curr = curr[part]

    curr[parts[-1]] = value
    return tomlkit.dumps(doc)


def delete_toml_path(content: str, dot_path: str) -> str:
    """Delete a key at dot_path if it exists in TOML string."""
    if not content.strip():
        return content

    doc = tomlkit.parse(content)
    parts = [p.strip() for p in dot_path.split(".") if p.strip()]
    if not parts:
        return content

    curr: Any = doc
    for part in parts[:-1]:
        if isinstance(curr, (dict, Table)) and part in curr:
            curr = curr[part]
        else:
            return content

    if isinstance(curr, (dict, Table)) and parts[-1] in curr:
        del curr[parts[-1]]

    return tomlkit.dumps(doc)
