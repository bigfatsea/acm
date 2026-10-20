"""Secret masking for all user-visible output."""

import re
from typing import Any

_SENSITIVE_KEY = re.compile(r"(api_?key|token|auth|secret|password|credential)", re.IGNORECASE)
_COUNT = re.compile(r"tokens(_|$)", re.IGNORECASE)  # MAX_CONTEXT_TOKENS, maxTokens: sizes
_REFERENCE = re.compile(r"^\$\{[A-Za-z_][A-Za-z0-9_]*(?::-[^}]*)?\}$")


def is_sensitive_key(key: str) -> bool:
    # "apiKeyHelper" holds a command line, not a credential
    if "helper" in key.lower() or _COUNT.search(key):
        return False
    return bool(_SENSITIVE_KEY.search(key))


def mask_secret(value: str, show_secrets: bool = False) -> str:
    """Keep the first and last 3 characters; ``${VAR}`` references are not secrets."""
    if show_secrets or not value or _REFERENCE.match(value):
        return value
    if len(value) <= 8:
        return "***"
    return f"{value[:3]}...{value[-3:]}"


def mask_in_obj(obj: Any, show_secrets: bool = False) -> Any:
    """Recursively mask values whose key looks sensitive."""
    if show_secrets or obj is None:
        return obj
    if isinstance(obj, dict):
        out: dict[Any, Any] = {}
        for k, v in obj.items():
            if is_sensitive_key(str(k)) and isinstance(v, str):
                out[k] = mask_secret(v)
            else:
                out[k] = mask_in_obj(v)
        return out
    if isinstance(obj, list):
        return [mask_in_obj(i) for i in obj]
    return obj


def mask_value_at(path: tuple[str | int, ...], value: Any, show_secrets: bool = False) -> Any:
    """Mask ``value`` if the last string segment of ``path`` looks sensitive."""
    if show_secrets:
        return value
    for seg in reversed(path):
        if isinstance(seg, str):
            if is_sensitive_key(seg) and isinstance(value, str):
                return mask_secret(value)
            break
    return mask_in_obj(value)
