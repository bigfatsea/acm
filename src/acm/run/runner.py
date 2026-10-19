"""``acm run``: start an agent once with the configured models; nothing is written to its files."""

import os
import shutil
import signal
import subprocess
import sys
from collections.abc import Mapping
from pathlib import Path
from typing import Any, NoReturn, Protocol

from acm.adapters.base import RUN_DIR_TOKEN, LaunchContext, LaunchSpec, LaunchUnsupportedError
from acm.adapters.registry import all_adapters, find_adapter
from acm.catalog.manifest import fetch_manifest, parse_manifest, resolve_source
from acm.catalog.proposal import provider_name
from acm.catalog.resolve import (
    Catalog,
    TargetError,
    build_catalog,
    profile_providers,
    resolve_target,
)
from acm.cli.output import Out
from acm.config.load import load_config, parse_config_text
from acm.config.refs import NON_DEFAULT_ROLES, parse_ref
from acm.config.schema import CoreConfig
from acm.core.context import Ctx
from acm.core.errors import ConfigError, IOFailureError, NotFoundError
from acm.engine.active import read_active


class Executor(Protocol):
    def replace_process(self, argv: list[str], env: Mapping[str, str]) -> NoReturn: ...

    def run_child(self, argv: list[str], env: Mapping[str, str]) -> int: ...


class RealExecutor:
    def replace_process(self, argv: list[str], env: Mapping[str, str]) -> NoReturn:
        sys.stdout.flush()
        sys.stderr.flush()
        os.execvpe(argv[0], argv, dict(env))

    def run_child(self, argv: list[str], env: Mapping[str, str]) -> int:
        proc = subprocess.Popen(argv, env=dict(env))
        old_int = signal.signal(
            signal.SIGINT, signal.SIG_IGN
        )  # the terminal also signals the child
        old_term = signal.signal(signal.SIGTERM, lambda s, _f: proc.send_signal(s))
        try:
            rc = proc.wait()
        finally:
            signal.signal(signal.SIGINT, old_int)
            signal.signal(signal.SIGTERM, old_term)
        return 128 - rc if rc < 0 else rc


# ------------------------------------------------------------------ run directory


def cleanup_stale_run_dirs(ctx: Ctx) -> None:
    """Remove temp dirs of runs that were killed before they could clean up."""
    if not ctx.run_dir.is_dir():
        return
    for d in ctx.run_dir.iterdir():
        if not (d.is_dir() and d.name.isdigit()):
            continue
        try:
            os.kill(int(d.name), 0)
        except ProcessLookupError:
            shutil.rmtree(d, ignore_errors=True)
        except PermissionError:
            continue


def prepare_run_dir(ctx: Ctx, spec: LaunchSpec) -> Path | None:
    cleanup_stale_run_dirs(ctx)
    if not spec.tmp_files:
        return None
    d = ctx.run_dir / str(os.getpid())
    try:
        d.mkdir(parents=True, exist_ok=True, mode=0o700)
        os.chmod(ctx.run_dir, 0o700)
        os.chmod(d, 0o700)
        for name, content in spec.tmp_files.items():
            fd = os.open(d / name, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
            with os.fdopen(fd, "wb") as f:
                f.write(content)
    except OSError as e:
        raise IOFailureError(f"cannot prepare {d}: {e}") from e
    return d


def substitute(spec: LaunchSpec, run_dir: Path | None) -> tuple[list[str], dict[str, str]]:
    token = str(run_dir) if run_dir else ""
    argv = [a.replace(RUN_DIR_TOKEN, token) for a in spec.argv]
    env = {k: v.replace(RUN_DIR_TOKEN, token) for k, v in spec.env.items()}
    return argv, env


# ------------------------------------------------------------------ target source


def zero_config(ctx: Ctx, source: str, model: str | None) -> CoreConfig:
    """A throwaway config from a gateway address alone (``VMR_URL`` / ``ACM_MANIFEST``)."""
    resolved = resolve_source(ctx, source)
    key = ctx.env.get("VMR_KEY", "")
    fetched = fetch_manifest(ctx, "run", resolved, key, {})
    m = parse_manifest(fetched.data, resolved)
    name = provider_name(m.gateway.kind)
    roles = {r for mm in m.models for r in mm.roles}
    if model is None:
        default = f"{name}@default" if "default" in roles else f"{name}.{m.models[0].id}"
    elif "@" in model:
        default = model if not model.startswith("@") else f"{name}{model}"
    elif "." in model.split("@")[0] and model.split(".", 1)[0] == name:
        default = model
    else:
        default = f"{name}.{model}"
    prof: dict[str, Any] = {"default": default}
    extra = {r: f"{name}@{r}" for r in NON_DEFAULT_ROLES if r in roles}
    if extra:
        prof["roles"] = extra
    text = (
        "version: 4\nproviders:\n"
        f'  {name}:\n    manifest: {resolved!r}\n    api_key: "${{VMR_KEY:-}}"\n'
        "profiles:\n  run:\n"
        f"    default: {default!r}\n"
        + (
            "    roles:\n" + "".join(f"      {r}: {v!r}\n" for r, v in extra.items())
            if extra
            else ""
        )
    )
    return parse_config_text(text, "(from VMR_URL / ACM_MANIFEST)")


def run_config(
    ctx: Ctx, model: str | None, profile: str | None, manifest: str | None
) -> tuple[CoreConfig, str]:
    """Pick the config and profile name: command line > environment > config.yaml."""
    env_source = ctx.env.get("ACM_MANIFEST") or (
        ctx.env["VMR_URL"].rstrip("/") + "/manifest" if ctx.env.get("VMR_URL") else None
    )
    source = manifest or (None if profile else env_source)
    if source:
        return zero_config(ctx, source, model), "run"
    if not ctx.config_path.exists():
        raise ConfigError(
            "nothing to start from: pass --manifest, set VMR_URL (and VMR_KEY), or run `acm init`"
        )
    config = load_config(ctx)
    name = profile or read_active(ctx)
    if not name:
        raise ConfigError("no profile selected: pass --profile or run `acm use <profile>` first")
    if name not in config.profiles:
        raise NotFoundError(f"profile '{name}' not found (available: {', '.join(config.profiles)})")
    if model:
        parse_ref(model, config.providers)  # syntax check with a clear message
        config = config.model_copy(
            update={
                "profiles": {
                    **config.profiles,
                    name: config.profiles[name].model_copy(update={"default": model}),
                }
            }
        )
        config = CoreConfig.model_validate(config.model_dump())
    return config, name


# ------------------------------------------------------------------------ entry


def run_agent(
    ctx: Ctx,
    out: Out,
    agent: str,
    *,
    model: str | None,
    profile: str | None,
    manifest: str | None,
    passthrough: list[str],
    executor: Executor | None = None,
) -> int:
    adapter = find_adapter(agent)
    if adapter is None:
        known = ", ".join(a.id for a in all_adapters())
        raise NotFoundError(f"unknown agent '{agent}' (known: {known})")
    bin_path = adapter.find_bin(ctx)
    if bin_path is None:
        raise NotFoundError(f"{adapter.name} was not found on PATH ({', '.join(adapter.bins)})")
    config, name = run_config(ctx, model, profile, manifest)
    catalog: Catalog = build_catalog(ctx, config, profile_providers(config, name))
    if catalog.errors:
        raise next(iter(catalog.errors.values()))
    try:
        target = resolve_target(config, catalog, name, adapter.protocols, adapter.id)
        spec = adapter.plan_launch(target, ctx, LaunchContext(passthrough, bin_path))
    except TargetError as e:
        raise ConfigError(str(e)) from e
    except LaunchUnsupportedError as e:
        raise ConfigError(str(e)) from e
    for note in catalog.notes():
        out.warn(note)
    for n in spec.notes:
        out.warn(f"[{adapter.id}] {n}")
    run_dir = prepare_run_dir(ctx, spec)
    argv, extra_env = substitute(spec, run_dir)
    env = {**ctx.env, **extra_env}
    ex = executor or RealExecutor()
    if spec.mode == "exec" and run_dir is None:
        ex.replace_process(argv, env)
    try:
        return ex.run_child(argv, env)
    finally:
        if run_dir is not None:
            shutil.rmtree(run_dir, ignore_errors=True)
