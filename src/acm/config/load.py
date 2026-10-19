"""Load and validate ``config.yaml``."""

import os
from io import StringIO
from pathlib import Path

from pydantic import ValidationError
from ruamel.yaml import YAML
from ruamel.yaml.error import YAMLError

from acm.config.schema import CoreConfig
from acm.core.context import Ctx
from acm.core.errors import ConfigError, IOFailureError


def parse_config_text(text: str, source: str = "config.yaml") -> CoreConfig:
    yaml = YAML(typ="safe")
    try:
        data = yaml.load(StringIO(text))
    except YAMLError as e:
        raise ConfigError(f"{source}: YAML syntax error: {e}") from e
    if not isinstance(data, dict):
        raise ConfigError(f"{source}: top level must be a mapping")
    try:
        return CoreConfig.model_validate(data)
    except ValidationError as e:
        raise ConfigError(f"{source}: {_format_errors(e)}") from e


def _format_errors(e: ValidationError) -> str:
    parts = []
    for err in e.errors():
        loc = ".".join(str(x) for x in err["loc"])
        msg = str(err["msg"]).removeprefix("Value error, ")
        parts.append(f"{loc}: {msg}" if loc else msg)
    return "; ".join(parts)


def load_config(ctx: Ctx) -> CoreConfig:
    path = ctx.config_path
    if not path.exists():
        raise ConfigError(f"{path} not found; run `acm init` first")
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as e:
        raise IOFailureError(f"cannot read {path}: {e}") from e
    return parse_config_text(text, str(path))


def write_config_text(path: Path, text: str) -> None:
    """Write config.yaml (0600) atomically."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".yaml.acm_tmp")
    try:
        fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(text)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, path)
    except OSError as e:
        raise IOFailureError(f"cannot write {path}: {e}") from e
