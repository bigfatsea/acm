# // Ver 2026-08-24 22:05, by gemini-3.7-flash
"""Order-preserving JSON editor with format detection and dot-path navigation."""

import json
import re
from collections import OrderedDict
from typing import Any

# Sentinel value for missing keys
NOT_FOUND = object()


def detect_json_formatting(content: str) -> tuple[int | str, bool, bool]:
    """Detect indentation, trailing newline, and non-ASCII representation from JSON content.

    Returns:
        (indent, has_trailing_newline, ensure_ascii)
    """
    has_trailing_newline = content.endswith("\n")
    has_non_ascii = any(ord(c) > 127 for c in content)
    ensure_ascii = not has_non_ascii

    # Detect indentation
    lines = content.splitlines()
    indent: int | str = 2  # default

    for line in lines:
        match = re.match(r"^([ \t]+)\S", line)
        if match:
            ws = match.group(1)
            if "\t" in ws:
                indent = "\t"
                break
            indent_len = len(ws)
            if indent_len in (2, 4, 8):
                indent = indent_len
                break

    return indent, has_trailing_newline, ensure_ascii


def read_json_path(content: str, dot_path: str, default: Any = NOT_FOUND) -> Any:
    """Read a value at a dot_path from a JSON string.

    Returns default (or NOT_FOUND) if path does not exist.
    """
    if not content.strip():
        return default

    try:
        data = json.loads(content, object_pairs_hook=OrderedDict)
    except (json.JSONDecodeError, UnicodeDecodeError):
        return default

    parts = [p.strip() for p in dot_path.split(".") if p.strip()]
    curr: Any = data
    for part in parts:
        if isinstance(curr, dict) and part in curr:
            curr = curr[part]
        else:
            return default

    return curr


def set_json_path(content: str, dot_path: str, value: Any) -> str:
    """Set a value at a dot_path in a JSON string, preserving key order and formatting."""
    indent, trailing_newline, ensure_ascii = (
        detect_json_formatting(content) if content.strip() else (2, True, True)
    )

    if content.strip():
        try:
            data = json.loads(content, object_pairs_hook=OrderedDict)
        except (json.JSONDecodeError, UnicodeDecodeError, ValueError):
            data = OrderedDict()
    else:
        data = OrderedDict()

    if not isinstance(data, dict):
        raise TypeError(f"Root JSON element must be an object/dict (got: {type(data)})")

    parts = [p.strip() for p in dot_path.split(".") if p.strip()]
    if not parts:
        raise ValueError("dot_path cannot be empty")

    curr = data
    for part in parts[:-1]:
        if part not in curr or not isinstance(curr[part], dict):
            curr[part] = OrderedDict()
        curr = curr[part]

    curr[parts[-1]] = value

    output = json.dumps(data, indent=indent, ensure_ascii=ensure_ascii)
    if trailing_newline and not output.endswith("\n"):
        output += "\n"
    return output


def delete_json_path(content: str, dot_path: str) -> str:
    """Delete a key at dot_path if it exists in JSON string."""
    if not content.strip():
        return content

    indent, trailing_newline, ensure_ascii = detect_json_formatting(content)
    data = json.loads(content, object_pairs_hook=OrderedDict)

    if not isinstance(data, dict):
        return content

    parts = [p.strip() for p in dot_path.split(".") if p.strip()]
    if not parts:
        return content

    curr = data
    for part in parts[:-1]:
        if isinstance(curr, dict) and part in curr:
            curr = curr[part]
        else:
            return content

    if isinstance(curr, dict) and parts[-1] in curr:
        del curr[parts[-1]]

    output = json.dumps(data, indent=indent, ensure_ascii=ensure_ascii)
    if trailing_newline and not output.endswith("\n"):
        output += "\n"
    return output
