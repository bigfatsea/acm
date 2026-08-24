# // Ver 2026-08-24 22:05, by gemini-3.7-flash
"""Sensitive token masking utilities for ACM."""

import re
from typing import Any

SENSITIVE_KEYS_REGEX = re.compile(
    r"(api_?key|token|auth|secret|password|credential)", re.IGNORECASE
)


def is_sensitive_key(key: str) -> bool:
    """Determine if a key name or dot-path refers to sensitive credentials."""
    return bool(SENSITIVE_KEYS_REGEX.search(key))


def mask_secret(value: str, show_secrets: bool = False) -> str:
    """Mask a secret value by keeping first 3 and last 3 characters unless show_secrets is True."""
    if show_secrets or not value:
        return value

    # If it is an unresolved env reference like ${VAR}, don't mask the reference itself
    if value.startswith("${") and value.endswith("}"):
        return value

    if len(value) <= 6:
        return "***"

    return f"{value[:3]}...{value[-3:]}"


def mask_secrets_in_obj(obj: Any, show_secrets: bool = False) -> Any:
    """Recursively mask sensitive credential values within dict, list, or primitive values."""
    if show_secrets or obj is None:
        return obj

    if isinstance(obj, dict):
        masked_dict: dict[Any, Any] = {}
        for k, v in obj.items():
            if is_sensitive_key(str(k)):
                if isinstance(v, str):
                    masked_dict[k] = mask_secret(v, show_secrets)
                else:
                    masked_dict[k] = mask_secrets_in_obj(v, show_secrets)
            elif isinstance(v, (dict, list)):
                masked_dict[k] = mask_secrets_in_obj(v, show_secrets)
            else:
                masked_dict[k] = v
        return masked_dict

    if isinstance(obj, list):
        return [mask_secrets_in_obj(item, show_secrets) for item in obj]

    return obj
