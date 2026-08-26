import os
import sys
from pathlib import Path
from typing import Annotated, Any

import typer

from acm.adapters import get_adapter_by_id, get_adapters
from acm.config import load_config
from acm.errors import (
    ACMError,
    ConfigError,
    NotFoundError,
    SafetyBlockedError,
)
from acm.lock import WriteLock
from acm.masking import is_sensitive_key, mask_secret, mask_secrets_in_obj
from acm.output import get_consoles, print_status_table, print_warnings, setup_logger
from acm.resolve import resolve_profile
from acm.safety import NOT_EXIST_SENTINEL, read_file_dotpath, write_changeset
from acm.state import (
    create_snapshot,
    ensure_state_dirs,
    get_snapshots_dir,
    list_snapshots,
    load_last_write,
    read_active,
    save_last_write,
    write_active,
)
from acm.status import AgentState, compute_agent_status, is_noop
from acm.util import get_acm_home, get_config_path
from acm.vmr import generate_template_config, generate_vmr_proposal, probe_vmr
from acm.writers.json_editor import NOT_FOUND

cli_app = typer.Typer(
    name="acm",
    help="Unified, Non-Destructive Model Configuration & Snapshot Manager for AI Coding Agents.",
    no_args_is_help=True,
    add_completion=False,
)


@cli_app.command("init")
def init_cmd(
    dry_run: Annotated[
        bool, typer.Option("--dry-run", help="Preview proposed configuration without writing.")
    ] = False,
    force: Annotated[
        bool, typer.Option("--force", "-f", help="Overwrite existing config without prompting.")
    ] = False,
    no_color: Annotated[bool, typer.Option("--no-color", help="Disable color formatting.")] = False,
) -> None:
    """Scan local coding agents, probe VMR, and generate ~/.acm/config.yaml."""
    stdout_c, stderr_c = get_consoles(no_color)
    acm_home = get_acm_home()
    config_file = get_config_path()

    if config_file.exists() and not force and not dry_run:
        stdout_c.print(f"[yellow]Configuration file already exists at {config_file}[/yellow]")
        confirm = typer.confirm(
            "Overwrite existing configuration? (default: Cancel)", default=False
        )
        if not confirm:
            stdout_c.print("[dim]Initialization cancelled by user.[/dim]")
            raise typer.Exit(code=0)

    # 1. Scan installed agents
    adapters = get_adapters()
    detected_agents = [a for a in adapters if a.detect()]
    stdout_c.print(
        f"[bold]Detected {len(detected_agents)} local coding agent(s):[/bold] "
        + ", ".join(f"[cyan]{a.DISPLAY_NAME}[/cyan]" for a in detected_agents)
    )

    # 2. Probe VMR
    stdout_c.print("[dim]Probing local Virtual Model Router (VMR)...[/dim]")
    probe = probe_vmr()
    if probe and probe.detected:
        stdout_c.print(
            f"[green]✓ VMR detected at {probe.base_url} with {len(probe.models)} model(s).[/green]"
        )
        proposal_content = generate_vmr_proposal(probe)
    else:
        stdout_c.print("[dim]VMR not running. Generating standard multi-provider template.[/dim]")
        proposal_content = generate_template_config()

    # 2.5 Validate generated proposal syntax & schema
    try:
        from acm.config import parse_config_yaml

        parse_config_yaml(proposal_content)
    except Exception as e:
        stderr_c.print(f"[bold red]Error: Generated proposal failed validation: {e}[/bold red]")
        raise typer.Exit(code=1) from e

    # 3. Present proposal
    stdout_c.print(
        "\n[bold cyan]── Proposed ~/.acm/config.yaml ────────────────────────[/bold cyan]"
    )
    stdout_c.print(proposal_content.strip())
    stdout_c.print(
        "[bold cyan]──────────────────────────────────────────────────────────[/bold cyan]\n"
    )

    if dry_run:
        stdout_c.print("[yellow]Dry-run mode: no changes were written to disk.[/yellow]")
        return

    if not force:
        confirm = typer.confirm(f"Write configuration to {config_file}?", default=True)
        if not confirm:
            stdout_c.print("[dim]Initialization aborted by user.[/dim]")
            raise typer.Exit(code=0)

    try:
        with WriteLock():
            # Write configuration and initialize state directory
            acm_home.mkdir(parents=True, exist_ok=True)
            try:
                os.chmod(acm_home, 0o700)
            except OSError:
                pass

            temp_cfg = acm_home / f"config.yaml.{os.getpid()}.acm_tmp"
            temp_cfg.write_text(proposal_content, encoding="utf-8")
            try:
                os.chmod(temp_cfg, 0o600)
            except OSError:
                pass
            os.replace(temp_cfg, config_file)

            ensure_state_dirs()

            # Write .gitignore
            gitignore = acm_home / ".gitignore"
            gitignore.write_text("state/\nlogs/\n.lock\n*.acm_tmp\n", encoding="utf-8")
    except ACMError as e:
        stderr_c.print(f"[bold red]Error: {e.message}[/bold red]")
        raise typer.Exit(code=e.exit_code) from e
    except OSError as e:
        stderr_c.print(f"[bold red]I/O Error initializing ACM: {e}[/bold red]")
        raise typer.Exit(code=3) from e

    stdout_c.print(f"[bold green]✓ Successfully initialized ACM at {config_file}![/bold green]")
    stdout_c.print("Next step: Run [cyan]acm use daily[/cyan] to project models to your agents.")


@cli_app.command("status")
def status_cmd(
    agent: Annotated[
        str | None, typer.Argument(help="Optional specific agent ID to inspect.")
    ] = None,
    verbose: Annotated[
        bool, typer.Option("--verbose", "-v", help="Display verbose details.")
    ] = False,
    show_secrets: Annotated[
        bool, typer.Option("--show-secrets", help="Display secrets in plaintext.")
    ] = False,
    no_color: Annotated[bool, typer.Option("--no-color", help="Disable color output.")] = False,
) -> None:
    """Display configuration alignment, active profile, and drift for coding agents."""
    stdout_c, stderr_c = get_consoles(no_color)
    config_file = get_config_path()

    try:
        if not config_file.exists():
            raise ConfigError(
                f"ACM configuration not found at {config_file}. Run 'acm init' first."
            )

        config = load_config(config_file)
        active_profile_name = read_active()

        resolved = None
        if active_profile_name:
            try:
                resolved = resolve_profile(active_profile_name, config)
            except Exception as e:  # noqa: BLE001
                stderr_c.print(
                    f"[yellow]Notice: Active profile '{active_profile_name}' could not be resolved in current environment: {e}[/yellow]"
                )
                resolved = None

        adapters = [get_adapter_by_id(agent)] if agent else get_adapters()
        if agent and not adapters[0]:
            raise NotFoundError(f"Agent '{agent}' is not a recognized built-in adapter.")

        results: list[Any] = []
        all_warnings: list[Any] = []
        for a in adapters:
            if a:
                res = compute_agent_status(a, resolved)
                results.append(res)
                all_warnings.extend(res.warnings)

        print_status_table(results, stdout_c, verbose=verbose, show_secrets=show_secrets)
        print_warnings(all_warnings, stderr_c)
    except ACMError as e:
        stderr_c.print(f"[bold red]Error: {e.message}[/bold red]")
        raise typer.Exit(code=e.exit_code) from e


@cli_app.command("use")
def use_cmd(
    profile: Annotated[str, typer.Argument(help="Profile name to activate and project.")],
    agent: Annotated[
        str | None, typer.Argument(help="Optional specific agent ID to project to.")
    ] = None,
    dry_run: Annotated[
        bool, typer.Option("--dry-run", help="Preview projection operations without writing.")
    ] = False,
    force: Annotated[
        bool, typer.Option("--force", "-f", help="Override external drift detection.")
    ] = False,
    show_secrets: Annotated[
        bool, typer.Option("--show-secrets", help="Display secrets in plaintext.")
    ] = False,
    verbose: Annotated[
        bool, typer.Option("--verbose", "-v", help="Display detailed logs.")
    ] = False,
    no_color: Annotated[bool, typer.Option("--no-color", help="Disable color formatting.")] = False,
) -> None:
    """Change desired profile and project model configurations to local agents."""
    stdout_c, stderr_c = get_consoles(no_color)
    setup_logger(verbose)
    config_file = get_config_path()

    try:
        if not config_file.exists():
            raise ConfigError(
                f"ACM configuration not found at {config_file}. Run 'acm init' first."
            )

        core_config = load_config(config_file)
        resolved = resolve_profile(profile, core_config)

        if not dry_run:
            write_active(profile)

        adapters = [get_adapter_by_id(agent)] if agent else get_adapters()
        if agent and not adapters[0]:
            raise NotFoundError(f"Agent '{agent}' is not a recognized built-in adapter.")

        highest_exit_code = 0
        all_warnings: list[Any] = []

        for adapter in adapters:
            if not adapter:
                continue

            agent_id = adapter.AGENT_ID
            display_name = adapter.DISPLAY_NAME

            if not adapter.detect():
                if agent:  # If user specifically asked for this agent
                    stderr_c.print(
                        f"[bold red]Error: Agent '{display_name}' is not installed or not detected on this system.[/bold red]"
                    )
                    raise typer.Exit(code=4)
                continue

            # Check status before projection
            st = compute_agent_status(adapter, resolved)

            if st.state == AgentState.ERROR and not force:
                stderr_c.print(
                    f"[bold red]⚠️  Safety Block: agent configuration file is corrupted in [{display_name}].[/bold red]"
                )
                if st.error_message:
                    stderr_c.print(f"   Reason: {st.error_message}")
                stderr_c.print(
                    "   Use [cyan]--force[/cyan] to reconstruct with ACM-managed fields (corrupted content cannot be preserved).\n"
                )
                highest_exit_code = max(highest_exit_code, 2)
                continue

            if st.state == AgentState.DRIFTED and not force:
                if is_noop(adapter, resolved):
                    stdout_c.print(
                        f"[yellow]⚠  {display_name}: external drift detected, but all fields already match desired state (no-op).[/yellow]"
                    )
                    continue

                stderr_c.print(
                    f"[bold red]⚠️  Safety Block: external drift detected in [{display_name}].[/bold red]"
                )
                for d in st.drifts:
                    if is_sensitive_key(d.field) and isinstance(d.expected, str):
                        exp_s = mask_secret(d.expected, show_secrets=show_secrets)
                    else:
                        exp_s = mask_secrets_in_obj(d.expected, show_secrets=show_secrets)

                    if is_sensitive_key(d.field) and isinstance(d.found, str):
                        fnd_s = mask_secret(d.found, show_secrets=show_secrets)
                    else:
                        fnd_s = mask_secrets_in_obj(d.found, show_secrets=show_secrets)

                    stderr_c.print(f"   Field '{d.field}': expected '{exp_s}', found '{fnd_s}'")
                stderr_c.print(
                    "   Use [cyan]--force[/cyan] to overwrite external changes or [cyan]acm diff[/cyan] to inspect.\n"
                )
                highest_exit_code = max(highest_exit_code, 2)
                continue

            # Check idempotency no-op
            if st.state == AgentState.SYNCED:
                stdout_c.print(f"[dim]• {display_name}: already in desired state (no-op)[/dim]")
                continue

            # Plan operations
            ops, warnings = adapter.plan(resolved)
            all_warnings.extend(warnings)

            if dry_run:
                stdout_c.print(
                    f"[cyan][Dry-run][/cyan] Planned operations for [bold]{display_name}[/bold]:"
                )
                if not ops:
                    stdout_c.print("  (no changes required - already synced)")
                for op in ops:
                    if is_sensitive_key(op.path) and isinstance(op.new, str):
                        new_s = mask_secret(op.new, show_secrets=show_secrets)
                    else:
                        new_s = mask_secrets_in_obj(op.new, show_secrets=show_secrets)
                    stdout_c.print(f"  • {op.file.name} :: {op.path} -> {new_s}")
                continue

            # Execute write through Safety Engine
            try:
                res = write_changeset(
                    agent_id=agent_id,
                    profile_name=profile,
                    allowed_paths=adapter.config_paths(),
                    allowed_namespaces=adapter.managed_namespaces(),
                    ops=ops,
                )
                if res.noop:
                    stdout_c.print(f"[dim]• {display_name}: already in desired state (no-op)[/dim]")
                else:
                    stdout_c.print(
                        f"[green]✓ Successfully projected profile '{profile}' to {display_name}[/green]"
                    )
            except SafetyBlockedError as e:
                stderr_c.print(f"[red]✗ Failed to project to {display_name}: {e}[/red]")
                highest_exit_code = max(highest_exit_code, 2)
            except (OSError, ValueError) as e:
                stderr_c.print(f"[red]✗ Disk I/O error projecting to {display_name}: {e}[/red]")
                highest_exit_code = max(highest_exit_code, 3)

        print_warnings(all_warnings, stderr_c)

        if highest_exit_code != 0:
            raise typer.Exit(code=highest_exit_code)
    except ACMError as e:
        stderr_c.print(f"[bold red]Error: {e.message}[/bold red]")
        raise typer.Exit(code=e.exit_code) from e


@cli_app.command("rollback")
def rollback_cmd(
    agent: Annotated[
        str | None, typer.Argument(help="Optional specific agent ID to rollback.")
    ] = None,
    dry_run: Annotated[
        bool, typer.Option("--dry-run", help="Preview rollback without writing.")
    ] = False,
    force: Annotated[
        bool, typer.Option("--force", "-f", help="Confirm rollback of ACM-created files.")
    ] = False,
    no_color: Annotated[bool, typer.Option("--no-color", help="Disable color formatting.")] = False,
) -> None:
    """Revert agent configurations to pre-projection snapshot."""
    stdout_c, stderr_c = get_consoles(no_color)
    try:
        adapters = [get_adapter_by_id(agent)] if agent else get_adapters()
        if agent and not adapters[0]:
            raise NotFoundError(f"Agent '{agent}' is not a recognized built-in adapter.")

        restored_any = False
        with WriteLock():
            # Pre-flight check: if not dry_run and not force, verify no files need archiving without confirmation
            if not dry_run and not force:
                all_files_to_archive: list[Path] = []
                for adapter in adapters:
                    if not adapter:
                        continue
                    agent_id = adapter.AGENT_ID
                    last_write = load_last_write(agent_id)
                    target_backup_id = (
                        last_write.backup_id if (last_write and last_write.backup_id) else None
                    )
                    if not target_backup_id:
                        all_snaps = list_snapshots(agent_id)
                        target_backup_id = all_snaps[-1] if all_snaps else None
                    if target_backup_id:
                        snap_dir = get_snapshots_dir(agent_id) / target_backup_id
                        if snap_dir.exists():
                            all_files_to_archive.extend(
                                cf
                                for cf in adapter.config_paths()
                                if (snap_dir / f".not_exist_{cf.name}").exists() and cf.exists()
                            )

                if all_files_to_archive:
                    archive_names = ", ".join(
                        f"{cf.parent.name}/{cf.name}" for cf in all_files_to_archive
                    )
                    if sys.stdin.isatty():
                        confirm = typer.confirm(
                            f"Rollback will archive newly created file(s): {archive_names}. Proceed?",
                            default=True,
                        )
                        if not confirm:
                            stdout_c.print("[dim]Rollback aborted by user.[/dim]")
                            raise typer.Exit(code=0)
                    else:
                        raise SafetyBlockedError(
                            f"Rollback will archive newly created file(s): {archive_names}. Use --force to confirm."
                        )

            for adapter in adapters:
                if not adapter:
                    continue

                agent_id = adapter.AGENT_ID
                display_name = adapter.DISPLAY_NAME
                last_write = load_last_write(agent_id)

                target_backup_id = (
                    last_write.backup_id if (last_write and last_write.backup_id) else None
                )
                if not target_backup_id:
                    all_snaps = list_snapshots(agent_id)
                    if all_snaps:
                        target_backup_id = all_snaps[-1]
                        stderr_c.print(
                            f"[yellow]Warning: backup_id missing in last_write for {display_name}; falling back to latest snapshot {target_backup_id}[/yellow]"
                        )
                    else:
                        if agent:
                            raise NotFoundError(f"No snapshot record found for {display_name}.")
                        continue

                snap_dir = get_snapshots_dir(agent_id) / target_backup_id
                if not snap_dir.exists():
                    if agent:
                        raise NotFoundError(
                            f"Snapshot directory {target_backup_id} not found for {display_name}."
                        )
                    continue

                files_to_archive = [
                    cf
                    for cf in adapter.config_paths()
                    if (snap_dir / f".not_exist_{cf.name}").exists() and cf.exists()
                ]
                files_to_restore = [
                    cf for cf in adapter.config_paths() if (snap_dir / cf.name).exists()
                ]

                if dry_run:
                    stdout_c.print(
                        f"[cyan][Dry-run][/cyan] Rollback target for [bold]{display_name}[/bold]: snapshot {target_backup_id}"
                    )
                    for f in files_to_restore:
                        stdout_c.print(f"  • Will restore {f.name} from snapshot")
                    for f in files_to_archive:
                        stdout_c.print(f"  • Will archive ACM-created {f.name}")
                    continue

                # Pre-rollback snapshot (undo-undo chain)
                pre_rollback_snap_id = create_snapshot(agent_id, adapter.config_paths())

                # Perform restore
                for cf in adapter.config_paths():
                    sentinel = snap_dir / f".not_exist_{cf.name}"
                    snap_file = snap_dir / cf.name

                    if sentinel.exists():
                        # ACM created this file originally -> archive it
                        if cf.exists():
                            archived_path = (
                                cf.parent / f"{cf.name}.acm_orphaned.{pre_rollback_snap_id}"
                            )
                            cf.rename(archived_path)
                            stdout_c.print(
                                f"[yellow]• Archived ACM-created file {cf.name} to {archived_path.name}[/yellow]"
                            )
                    elif snap_file.exists():
                        # Restore original file content via atomic replace
                        cf.parent.mkdir(parents=True, exist_ok=True)
                        temp_f = cf.parent / f"{cf.name}.{os.getpid()}.acm_tmp"
                        temp_f.write_bytes(snap_file.read_bytes())
                        try:
                            os.chmod(temp_f, 0o600)
                        except OSError:
                            pass
                        os.replace(temp_f, cf)
                        stdout_c.print(
                            f"[green]✓ Restored {cf.name} from snapshot {target_backup_id}[/green]"
                        )

                # Reconstruct last_write fields from restored disk state for previously managed keys only
                restored_fields: dict[str, Any] = {}
                keys_to_reconstruct = (
                    list(last_write.fields.keys()) if (last_write and last_write.fields) else []
                )
                for key in keys_to_reconstruct:
                    if "::" in key:
                        cf_name, dot_path = key.split("::", 1)
                        cf = next((f for f in adapter.config_paths() if f.name == cf_name), None)
                    else:
                        cf_name, dot_path = None, key
                        cf = adapter.config_paths()[0] if adapter.config_paths() else None

                    if not cf or not cf.exists() or (snap_dir / f".not_exist_{cf.name}").exists():
                        restored_fields[key] = NOT_EXIST_SENTINEL
                    else:
                        val = read_file_dotpath(cf, dot_path)
                        restored_fields[key] = val if val is not NOT_FOUND else NOT_EXIST_SENTINEL

                from acm.state import LastWrite

                if last_write is None:
                    last_write = LastWrite(
                        profile=read_active() or "",
                        timestamp=pre_rollback_snap_id,
                        backup_id=pre_rollback_snap_id,
                        fields=restored_fields,
                    )
                else:
                    last_write.backup_id = pre_rollback_snap_id
                    last_write.timestamp = pre_rollback_snap_id
                    last_write.fields = restored_fields

                save_last_write(agent_id, last_write)
                restored_any = True

        if not restored_any and not dry_run:
            stdout_c.print("[dim]No active snapshot available to restore.[/dim]")
    except ACMError as e:
        stderr_c.print(f"[bold red]Error: {e.message}[/bold red]")
        raise typer.Exit(code=e.exit_code) from e
