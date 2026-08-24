# ACM (Agent Config Manager)

**English** | [中文文档](./README.zh.md)

> **The unified, non-destructive model configuration & projection engine for AI coding agents.**
> A lightweight, non-destructive CLI that serves as the single source of truth (SSOT) for model/provider configuration — purpose-built for the coding-agent ecosystem — and projects it onto every agent installed on your machine.

---

## 💡 Philosophy

ACM manages **fields**, not files. There is exactly one description of your model world; agents are merely projection targets.

- **Axiom 1 (SSOT)**: You maintain one agent-agnostic declarative configuration of providers/models (`~/.acm/config.toml`) and project it onto all local coding agents in one command.
- **Axiom 2 (Non-destructive)**: ACM owns only the managed fields it writes — never the whole file. Unmanaged content (MCP servers, plugins, skills, prompt rules, session state, …) is preserved with **100% semantic fidelity**.
- **Axiom 3 (Precise reversibility)**: Rollback granularity is "the inverse operation of ACM-managed fields", not blunt whole-file replacement — agent-written state is never clobbered; physical snapshots serve as disaster-recovery backstop.

---

## 🌟 Key Features

- 🎯 **Strict Model Scope**: Manages L1 connectivity (`base_url`, `api_key` references, dialect, headers, proxy) and L2 model spec/behavior (`model`, `context_window`, `max_tokens`, reasoning effort/budget, temperature, capability flags). **Never touches MCP, plugins, permissions, or system prompts.**
- 🛡️ **Field Ownership & Lossless Mutation**: In-memory AST surgery via `ruamel.yaml`, `tomlkit`, and order-preserving JSON/JSONC editors — 100% deterministic writes for managed fields, 100% zero-damage preservation for everything else.
- 🔒 **Layered Safety Engine**:
  - Dual **allowlist + denylist** interception physically blocks sensitive paths;
  - **External drift detection**: write commands are blocked by default if managed fields were tampered with externally — no silent overwrites;
  - **Pre-write snapshot + atomic replace (`os.replace`)**: no torn/half-written file states, ever;
  - **Global non-blocking file lock** (`fcntl`/`msvcrt`): eliminates concurrent-terminal races;
  - **Credential-safe references**: only `${VAR}` environment-variable references are stored; sensitive values masked by default.
- 🔄 **Layered Recovery**:
  - Default **field-level precise rollback** (journal-based inverse operations; states written by agents in the meantime stay intact);
  - `--hard` **physical snapshot restore** as the brick-recovery fallback.
- 🔌 **Adapter Protocol (pure-function contract)**: One module per agent implementing only `detect` / `config_paths` / `plan`. All adapters ship **in-source with golden-fixture test gates** — no dynamic code reflection/loading, no supply-chain surprises.
- 🤝 **VMR Co-op**: One-command discovery of a local VMR (Virtual Model Router) with virtual-model import; without VMR, direct connections to any OpenAI / Anthropic / third-party endpoint are first-class citizens too.
- 🚪 **Zero Lock-in**: `acm release` restores the pre-ACM state in one command. Migrating away? Just uninstall ACM — config files remain in their last effective state and keep working.

---

## 📖 Official Docs & Specs

| Document | Description |
|---|---|
| 🏛️ [**ACM Project Principles & Core Spec v2.1**](./docs/ACM_PROJECT_PRINCIPLE_v2.1.md) *(Chinese)* | **Governing charter**: axioms, non-destructive boundaries, six-step safe write pipeline, adapter contract & design philosophy |
| 📋 [**ACM MVP Action Plan & Delivery Spec v1.0**](./docs/ACM_MVP_ACTION_PLAN_v1.0.md) *(Chinese)* | **Execution plan**: WP0–WP9 task breakdown, 8 hard acceptance criteria, state-machine definitions, testing & validation specs |
| 🔬 [**Config Management Deep Dive & Best Practices**](./docs/ACM_CONFIG_MANAGEMENT_DEEP_DIVE_AND_BEST_PRACTICES.md) *(Chinese)* | 40 years of configuration-management evolution, dual-ownership essence, field-ownership mechanics |

---

## 🚀 Quick Start

### 1. Install & Run

```bash
# Option A: run instantly without installing (via uvx; the CLI command stays `acm`)
uvx --from agent-config-manager acm status

# Option B: install globally
uv tool install agent-config-manager
```

> Note: the PyPI distribution name is `agent-config-manager` (the short name `acm` collides with the ACM society and other well-known uses), but the installed CLI command remains simply `acm`.

### 2. Core Workflow (≤ 3 commands)

```bash
# 1. Initialize: scan locally installed agents + probe a local VMR,
#    then interactively generate the SSOT configuration
acm init

# 2. Converge: project the active profile onto all detected agents (or a specific one)
acm use daily
# Or target a single agent: acm use daily claude_code

# 3. Status: per-agent config state machine, external drift flags, projection-loss warnings
acm status

# 4. Diff: on-disk config vs desired state (or vs snapshot)
acm diff claude_code

# 5. Precise rollback: field-level rollback of the last transaction
#    (permissions/plugins written by agents meanwhile are untouched)
acm rollback claude_code

# 6. Release: fully restore the pre-ACM state after an evaluation period
acm release
```

> **On migration & uninstall**:
> ACM follows an absolutely non-intrusive philosophy. If you decide to move to another tool, there is **no need to run any release command** — just uninstall ACM and delete the `~/.acm/` directory; all agent config files remain intact and fully functional.

---

## 🗺️ Architecture Overview

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                           acm CLI (typer + rich)                            │
│   init / status / doctor / use / apply / diff / history / rollback / release│
├─────────────────────────────────────────────────────────────────────────────┤
│                    Core Engine (pure logic, no I/O)                         │
│  CoreConfig loading/validation · Profile resolution · Desired-State compute │
│              idempotent convergence · ENV reference resolution              │
├──────────────────────────┬──────────────────────────────────────────────────┤
│     Safety Engine        │                  Adapter Layer                   │
│  Atomic write-back       │  Adapter Protocol (detect / config_paths / plan) │
│  (os.replace)            ├──────────────────────────────────────────────────┤
│  Ownership-derived views │  Built-in adapters (in-source + golden tests,    │
│  Allow/Denylist · drift  │  dynamic reflection loading rejected)            │
│  detection               │   • Claude Code (JSON / env)  • Codex (TOML+JSON)│
│  Exclusive write lock ·  │   • Pi (JSON registry)        • Aider (YAML roles)│
│  append-only snapshots · │                                                  │
│  field-level rollback ·  │                                                  │
│  secret masking          │                                                  │
├──────────────────────────┴──────────────────────────────────────────────────┤
│           Format Writers (lossless declarative writers)                     │
│   Order-preserving JSON · ruamel.yaml round-trip · tomlkit · JSONC · .env   │
└─────────────────────────────────────────────────────────────────────────────┘
```

---

## ⚙️ Core Configuration Example (`~/.acm/config.toml`)

```toml
version = 1

# ── L1 providers: endpoints & credential references ──────────────
[providers.vmr]
protocol    = "openai"
base_url    = "http://127.0.0.1:8800/v1"
api_key     = "${VMR_KEY}"               # env-var reference; no plaintext secrets on disk

[providers.anthropic-official]
protocol    = "anthropic"
base_url    = "https://api.anthropic.com"
api_key     = "${ANTHROPIC_API_KEY}"

# ── L2 models: spec, behavior & capabilities ─────────────────────
[models.coding]
provider           = "vmr"
id                 = "coding"
context_window     = 131072
max_output_tokens  = 16384
temperature        = 0.2
capabilities       = { vision = false, tools = "native", json_mode = true }

[models.coding.reasoning]
effort        = "high"                   # adapters translate this into agent-specific fields
budget_tokens = 16000                    # projection-loss warning if the target can't express it

# ── L3 profiles: named role bundles ──────────────────────────────
[profiles.daily]
main  = "coding"                         # single-model agents consume main;
                                         # multi-role agents consume matching slots
```

---

## 🎯 Adapter Matrix

- **P0 (Phase 1 / MVP)**:
  - **Claude Code**: `~/.claude/settings.json` (JSON + env-block injection + dense unmanaged-field protection; never touches `~/.claude.json` runtime state)
  - **Codex**: `~/.codex/config.toml` + `~/.codex/auth.json` (dual-file atomic transaction across TOML + JSON; commented `mcp_servers` faithfully preserved)
  - **Pi**: `~/.pi/agent/models.json` + `settings.json` (registry-style projection + dialect/thinking-level mapping; never touches `models-store.json`. *Note: Pi uses incremental multi-provider registration — switching profiles keeps existing providers in `models.json` for historical session reuse; delete unused entries manually or run `acm rollback` if cleanup is needed.*)
- **P1 (Phase 2)**:
  - **Aider**: `~/.aider.conf.yml` + `~/.aider.model.metadata.json` (YAML round-trip + role models main/weak/editor)
  - **Gemini CLI**, **OpenCode** (JSONC comment preservation)
- **P2 (Phase 3 / community contributions)**:
  - OpenClaw, Hermes, Cursor/Cline (public settings channels only)

---

## 📄 License

[Apache-2.0 License](./pyproject.toml)
