# CLAUDE.md

**ACM (Agent Config Manager)** — a CLI that is the single source of truth (SSOT) for model/provider configuration of AI coding agents. It projects one declarative config onto locally installed agents (Claude Code, Codex CLI, Pi Agent) and rolls back precisely. Non-destructive by design: it manages *fields*, never whole files.

- PyPI package: `agent-config-manager`; CLI command & import name: `acm`
- Python ≥ 3.12 · macOS/Linux only (global lock uses `fcntl`) · Apache-2.0
- Release: pushing a `v*` tag triggers build + PyPI publish via GitHub Actions (Trusted Publishing)

## Governing Principles — never violate

Authoritative source: `docs/ACM_PROJECT_PRINCIPLE_v2.1.md` (Chinese). On any conflict, principles win over implementation docs.

**Three axioms:**

1. **SSOT** — `~/.acm/config.yaml` (providers L1, with embedded models L2 → profiles L3) is the only description of the model world; agents are projection targets.
2. **Non-destructive** — ACM owns managed *fields*, never whole files. Unmanaged content (MCP servers, plugins, skills, prompts, hooks, permissions, session state) must be preserved losslessly (AST-level).
3. **Precise reversibility** — rollback granularity is "inverse of ACM-managed fields"; physical snapshots are the disaster-recovery backstop.

**Iron rules:**

- Never touch MCP/tools/skills/prompts/hooks/plugins/permissions, agent runtime-state files, or private IDE databases.
- All writes land only on adapter-declared file paths & dot-path namespaces — enforced by the Safety Engine whitelist (files + namespaces).
- **Explicit exposure, never silent handling**: external drift of managed fields → block writes by default; settings unexpressible by a target agent → projection-loss warning on stderr; unresolved `${ENV}` → hard error *before any disk write*.
- No secret storage: config stores `${VAR}` / `${VAR:-default}` references only (strict whole-field syntax, no interpolation/nesting). Output masks secrets unless `--show-secrets`.
- Scope test for any new feature: *"would this stay unchanged when switching provider/model?"* If no → out of scope, reject regardless of who asks.
- Adapters are plain Python modules compiled in-source with golden-fixture gates. No DSL, no dynamic code loading/reflection.
- Unknown/breaking upstream agent schema → set ERROR state and block; never blind-write.

## Implementation Status (MVP v0.3.x, config schema v3)

- Implemented commands: `init`, `status`, `use`, `rollback` (+ global `--dry-run --force --verbose --show-secrets --no-color`).
- `apply / diff / doctor / history / release / import vmr` are **not implemented** — they are trigger-based upgrades (Spec v2.1 §12). Do not implement them without checking the trigger table and getting explicit direction.
- Built-in adapters: `claude_code`, `codex`, `pi` only. A new adapter = new module + golden fixtures, merged in-source.
- Profile member registration + opt-in default is **implemented**, per Spec v2.1 §7.3.3 (schema v3). A profile has two orthogonal axes: an optional `default: <R3-ref>` (the only thing that drives an agent's default-model field; resolved directly like a member value, NOT a member label) and an optional `models: {label: <R3-ref>}` (member catalog registration, consumed by Pi). At least one must be declared. Pi always registers the default model into `models.json` (as a single-entry group if not among `models:` members, named by its model_id) so `settings.json`'s `defaultProvider`/`defaultModel` are never dangling. Claude Code/Codex have no registry channel — with a `default`, they project only that model (aggregate `models.unreachable` projection-loss warning for other registered members); without one, they project nothing and emit one explicit warning that there's nothing to project. `acm init`'s generated VMR proposal auto-sets `default` to the primary detected model so a fresh install works out of the box.

## Architecture

Data flow: `config.yaml` → load/validate (pydantic) → `resolve_profile()` (live `${ENV}` resolution) → `adapter.plan()` (pure function → ops + warnings) → `write_changeset()` (Safety Engine — **the only disk-write path**) → last_write.json.

```
src/acm/
├── cli.py        # typer commands: init / status / use / rollback
├── main.py       # entry point; exit-code mapping
├── config.py     # CoreConfig schema (pydantic, extra=forbid) + validation
├── resolve.py    # credential refs → ResolvedProfile; hard-fails on missing vars
├── status.py     # 6-state machine, drift detection, idempotency check
├── safety.py     # Safety Engine: 6-step write pipeline
├── state.py      # ~/.acm/state: active, last_write.json, append-only snapshots
├── lock.py       # global non-blocking flock (~/.acm/state/.lock)
├── masking.py    # secret masking for all output
├── vmr.py        # VMR probe (/v1/models w/ optional bearer cred → /health) + proposal gen
├── util.py errors.py output.py
├── adapters/     # __init__: Protocol + registry; claude_code.py codex.py pi.py (pure plan())
└── writers/      # order-preserving JSON/TOML editors + AST tree-diff assertion
```

**Key invariants:**
- Adapters never touch disk — `plan()` is pure; every write goes through the 6-step pipeline: whitelist validation → pre-write snapshot + op expansion → in-memory edit + syntax self-check + AST non-destructive assertion → SHA-256 fingerprint recheck → atomic `os.replace` → last_write update.
- Config and runtime state are strictly separated: state lives under `~/.acm/state/`, never written back into `config.yaml`.
- Idempotent: desired == current && no drift → no-op, exit 0.
- Batch operations process agents independently; one blocked agent doesn't undo others' successes; final exit code reflects the highest severity.

## Config Schema Essentials

- `version: 3` required; ≥ 1 entry under `providers:` (each embedding its own `models:`) and `profiles:`; cross-references enforced via R3 reference resolution (bare id, globally unique, or `<provider>.<id>`); unknown keys rejected (v1's top-level `models:` and profile `main:`/`cheap:`/`pool:` are gone).
- `protocol` ∈ `openai | anthropic | openai-responses`; `base_url` must be http(s); a profile declares at least one of `default: <R3-ref>` (drives agent default model) or `models: {label: <R3-ref>}` (member registration for Pi) — registration and selection are orthogonal.
- Projection mapping per agent (which fields land where, dialect conversion, what warns) → USER_GUIDE §7 / adapters' `plan()`.

## States & Exit Codes

Agent states: `SYNCED / OUT_OF_SYNC / DRIFTED / ERROR / UNMANAGED / NOT_DETECTED` (priority: ERROR > DRIFTED > OUT_OF_SYNC > SYNCED).

Exit codes: `0` ok/no-op · `1` config error · `2` safety block (drift/corrupt-without-force/lock/whitelist) · `3` I/O failure · `4` not found · `130` SIGINT. stdout = normal output; stderr = errors/warnings.

## Development

```bash
uv sync                # deps + dev group (pytest/ruff/mypy)
uv run pytest          # full suite; markers: @pytest.mark.golden / fault / e2e
uv run ruff check .    # lint, line-length 100
uv run mypy src        # strict mode — keep it green
```

- conftest auto-isolates every test (fake HOME, PATH stripped, VMR probe pinned to a dead port). Never read/write real user files in tests; use `fake_vmr_server` / `make_config` fixtures.
- `ACM_TEST_FAULT_*` env vars are fault-injection hooks — test code only, never elsewhere.
- Golden fixtures (`tests/fixtures/`) double as upstream-schema-drift sentinels; change them only with intent, together with their tests.
- Quality gates (Principle §6): format-writer round-trip tests precede any adapter work; every safety mechanism needs negative/fault-injection coverage.

## Doc Map

| Looking for… | Open |
|---|---|
| Principles, boundaries, command semantics | `docs/ACM_PROJECT_PRINCIPLE_v2.1.md` |
| Implementation details, data structures, acceptance criteria, roadmap slices | `docs/ACM_PROJECT_SPEC_v2.1.md` |
| User-facing behavior, config reference, troubleshooting | `docs/USER_GUIDE.md` / `USER_GUIDE.zh.md` |
| Project overview / quick start | `README.md` / `README.zh.md` |
| Adapter field mappings, safety pipeline internals | adapters' `plan()` docstrings; `safety.py` step comments; USER_GUIDE ch. 7 & 9 |
