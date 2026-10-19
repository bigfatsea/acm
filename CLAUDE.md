# CLAUDE.md

**ACM (Agent Config Manager)** — a CLI that is the single source of truth (SSOT) for the *model intent* of AI coding agents. It projects one declarative config (plus an optional gateway-published catalog, the "Manifest") onto locally installed agents, keeps a restorable version history of every write, and can launch an agent one-shot without touching any file.

- PyPI package: `agent-config-manager`; CLI command & import name: `acm`
- Python ≥ 3.12 · macOS/Linux only (global lock uses `fcntl`) · Apache-2.0
- Release: pushing a `v*` tag triggers build + PyPI publish via GitHub Actions. **Never create `v*` tags or push without being asked.**
- History: the v0.3 implementation is archived at git tag `legacy-v0.3.0` / branch `legacy/v0.3`. `main` is the v0.4 rebuild (config schema v4). Do not resurrect v0.3 code or v3 schema.

## Governing documents — read before non-trivial changes

| Looking for… | Open |
|---|---|
| Axioms, boundaries, iron rules, command semantics | `docs/ACM_PRINCIPLE_v3.md` (Chinese; wins on conflict) |
| Schema v4, Manifest, resolution, formats, engine, history, `run`, tests | `docs/ACM_SPEC_v3.md` |
| **Every agent's config files/keys/launch-injection rules + fact-check log** | `docs/ACM_Agent_Support_Matrix_opus-5.5.md` — the *only* place for agent config knowledge |
| Why decisions were made | `docs/ACM_Rebuild_Action_Plan_opus-5.5.md`, `docs/ACM_VMR_Manifest_Analysis_and_Design_opus-5.5.md`, `docs/ACM_Config_Safety_and_History_Design_opus-5.5.md`, `docs/ACM_Ephemeral_Run_Design_opus-5.5.md` |
| User-facing behavior, config reference, troubleshooting | `docs/USER_GUIDE.md` / `docs/USER_GUIDE.zh.md`; overview in `README.md` / `README.zh.md` |
| What was built and what is left | `docs/ACM_Execution_Summary_sonnet-5.5.md` |

## Iron rules (condensed — the Principle is authoritative)

1. **Fields, not files.** Never touch MCP/tools/skills/prompts/hooks/plugins/permissions, runtime state, or private IDE databases. Writes land only on adapter-declared paths (`is_managed`), enforced by the engine.
2. **Explicit exposure, never silent handling:** drift on managed fields blocks writes; unexpressible settings → projection-loss warning on stderr; unresolved `${ENV}` → hard error *before any disk write*; unknown upstream structure → agent ERROR, never blind-write.
3. **Every write is recoverable:** the engine stores before/after versions (content-addressed) and appends a history record; the first write of a file records a `baseline` first. Restore defaults to *managed fields only*.
4. **No secret storage:** config holds `${VAR}` references only; prefer each agent's native reference syntax; output masks secrets unless `--show-secrets`; secrets never go into argv.
5. **Scope test:** "would this stay unchanged when switching provider/model?" If yes → out of scope.
6. Adapters are plain in-source Python modules with golden fixtures. No DSL, no dynamic loading, no remote descriptors. Tiering is by code path: T1 = own code path (real-agent verified), T2 = family member = parameters only (golden only), T3 = not built in.
7. `acm run` may inject one-shot launch config but must not write agent files, persist anything, outlive the agent, bypass the resolver, or put secrets in argv.

## Architecture

Data flow: `config.yaml` → `config` (pydantic v4) → `catalog` (static + Manifest, cached) → `catalog.resolve` (role × protocol → `ResolvedTarget`) → `adapter.plan_files()` / `plan_launch()` (pure) → `engine.write` (the only disk-write path; history + objects) or `run.runner`.

```
src/acm/{core,config,catalog,formats,adapters,engine,run,cli}
```

Key invariants: adapters never touch disk; key paths are tuples (model ids contain dots); the format layer is the only code that parses/renders agent files; the engine re-parses every rendered file and asserts only managed paths changed; one agent = one transaction (multi-file failure auto-reverts).

## States & exit codes

Agent states: `SYNCED / OUT_OF_SYNC / DRIFTED / ERROR / UNMANAGED / NOT_DETECTED`. Exit codes: `0` ok/no-op · `1` config error · `2` safety block · `3` I/O failure · `4` not found · `130` SIGINT. stdout = normal output; stderr = errors/warnings.

## Development

```bash
uv sync                # deps + dev group
uv run pytest          # full suite; markers: golden / fault / e2e / real
uv run ruff check .    # lint, line-length 100
uv run mypy src        # strict — keep it green
```

- Use `uv run --no-project python` for ad-hoc scripts (plain `python3` is a `uv run` alias on the maintainer's machine and triggers a project build).
- `tests/conftest.py` isolates every test (fake HOME, PATH stripped, gateway probes pinned to a dead port). Never read/write real user files in tests; use the `fake_gateway` / `make_config` fixtures.
- `ACM_TEST_FAULT_*` env vars are fault-injection hooks — test code only.
- Real-agent tests (`-m real`) run the actual agent binaries in an isolated HOME against a local mock gateway; they are skipped when the binary is absent.
- Golden fixtures (`tests/fixtures/<agent>/`) double as upstream-schema-drift sentinels; change them only with intent, together with their tests.
