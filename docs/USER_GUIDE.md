# ACM User Guide

**The complete handbook for ACM (Agent Config Manager)** — the unified, non-destructive model configuration & projection engine for AI coding agents.

> 🌐 This document is also available in [Chinese / 中文版](USER_GUIDE.zh.md).
>
> Covers ACM `0.3.x` (config schema v2). Companion documents: [README](../README.md) · [Project Principles & Core Spec v2.1](ACM_PROJECT_PRINCIPLE_v2.1.md) · [Implementation Spec v2.1](ACM_PROJECT_SPEC_v2.1.md)

---

## Table of Contents

- [1. Introduction](#1-introduction)
- [2. Installation](#2-installation)
- [3. Core Concepts](#3-core-concepts)
- [4. Quick Start](#4-quick-start)
- [5. Configuration Reference (`~/.acm/config.yaml`)](#5-configuration-reference-acmconfigyaml)
- [6. Command Reference](#6-command-reference)
- [7. Agent Adapters](#7-agent-adapters)
- [8. VMR Integration](#8-vmr-integration)
- [9. The Safety Model](#9-the-safety-model)
- [10. State Directory & Internals](#10-state-directory-internals)
- [11. Recipes (Common Workflows)](#11-recipes-common-workflows)
- [12. Troubleshooting & FAQ](#12-troubleshooting--faq)
- [Appendix A. Glossary](#appendix-a-glossary)
- [Appendix B. File Locations Quick Reference](#appendix-b-file-locations-quick-reference)
- [Appendix C. Exit Codes Quick Reference](#appendix-c-exit-codes-quick-reference)
- [Appendix D. Environment Variables Quick Reference](#appendix-d-environment-variables-quick-reference)

---

## 1. Introduction

### 1.1 What is ACM?

If you use more than one AI coding agent (Claude Code, Codex CLI, Pi Agent, …), you already know the pain: every agent has its own config file, its own format (JSON / TOML / YAML), and its own way of specifying *which model* and *which API endpoint* to use. Switching models or providers means hand-editing several files — while the agents themselves keep writing their own state into those very same files.

**ACM solves this**: you describe your model world **once**, in a single declarative file (`~/.acm/config.yaml`), and ACM safely projects it onto every coding agent installed on your machine with one command. It can also roll back precisely when you change your mind.

### 1.2 Three axioms

Everything ACM does derives from three axioms:

| Axiom | Meaning |
|---|---|
| **Axiom 1 — SSOT** | There is exactly one description of your providers/models. Agents are merely projection targets. |
| **Axiom 2 — Non-destructive** | ACM owns only the *fields it manages*, never whole files. Everything else (MCP servers, plugins, skills, permissions, session state…) is preserved with semantic fidelity. |
| **Axiom 3 — Precise reversibility** | Rollback granularity is "the inverse of ACM-managed fields", not blunt whole-file replacement. State written by agents in the meantime is never clobbered; physical snapshots serve as disaster-recovery backstop. |

The unifying principle: **ACM manages fields, not files.** Anything ACM doesn't know about (external edits, unexpressible settings, concurrency, crashes) is *explicitly exposed* — never silently handled.

### 1.3 What ACM manages — and what it never touches

**In scope:**

- **L1 — Connectivity & credentials**: `base_url`, protocol dialect, `api_key` (stored only as an environment-variable *reference*), custom headers, proxy.
- **L2 — Model spec & behavior** (embedded under its provider): which model, context window, max output tokens, reasoning effort/budget, temperature, capability flags.
- **Profiles**: named member sets (e.g. `daily`, `budget`) with an optional opt-in default, activation and rollback.

**Out of scope (never touched):**

- MCP servers, tools, skills, prompts, permissions, hooks, plugins.
- Account rotation / OAuth token pools / quota monitoring.
- Local proxying / request rewriting (that's VMR's job).
- Secret storage (only `${ENV}` references are stored — no vault).
- Private IDE databases; closed-source internals without a public, stable config channel.

### 1.4 Why "field ownership" matters

Your agent config file (say `~/.claude/settings.json`) is governed by *two authorities at once*: you/ACM want fields like `model` and `base_url` to follow your intent, while the agent runtime continuously writes session state, OAuth tokens, and plugin records into the same file. Naive whole-file version control hits a **dual-authority deadlock**: restoring an old snapshot destroys whatever the agent wrote meanwhile.

ACM applies the Kubernetes Server-Side Apply insight — *field-level ownership*:

```
┌─ ACM-managed zone ─────────────────┬─ Host-autonomous zone ─────────────┐
│ model / base_url / api_key / …     │ permissions / hooks / history / … │
│ 100% deterministic writes          │ preserved zero-damage (AST-level) │
│ idempotent convergence             │ externally modifiable, untouched  │
│ external edits = Drift → blocked   │ read-only snapshots kept as audit │
└────────────────────────────────────┴───────────────────────────────────┘
```

### 1.5 Current maturity

This guide covers the **MVP release (0.3.x, config schema v2)**. Implemented commands: `acm init`, `acm status`, `acm use`, `acm rollback`. Built-in adapters: **Claude Code**, **Codex CLI**, **Pi Agent**. Additional commands (`apply`, `diff`, `doctor`, `history`, `release`, `import vmr`) and adapters (Aider, Gemini CLI, OpenCode…) are planned upgrades — see [§6.6](#66-planned-commands-and-todays-equivalents) and [§7.5](#75-roadmap-adapters).

---

## 2. Installation

### 2.1 Requirements

- **Python ≥ 3.12**
- macOS or Linux (the global write lock uses `fcntl`; Windows support is not yet provided)
- [`uv`](https://docs.astral.sh/uv/) (recommended) or any Python ≥ 3.12 environment

### 2.2 Option A — run instantly without installing (uvx)

```bash
uvx --from agent-config-manager acm status
```

No installation step at all; `uvx` fetches the package and runs the `acm` CLI.

### 2.3 Option B — install globally

```bash
uv tool install agent-config-manager
acm --version
```

> **Naming note**: the PyPI distribution name is `agent-config-manager` (the short name `acm` collides with the well-known ACM society and was at squatting risk), but the installed CLI command is simply **`acm`**.

### 2.4 Verify

```bash
$ acm --version
0.3.0
```

---

## 3. Core Concepts

Master these eight concepts and everything else in ACM follows.

### 3.1 The two-layer configuration model

Your entire model world lives in one YAML file with two layers:

```
providers:            L1 — endpoints & credential references     ("where the API is")
  <name>.models:       ↳ L2 — model specs & behavior, embedded    ("what the model is")
    ↓ referenced by
profiles:             L3 — named member sets + opt-in default     ("which models, for which purpose")
```

A provider embeds its own models directly (`providers.<name>.models.<upstream-id>`) — there is no separate top-level `models:` table and no alias layer. A profile's `models:` map then references those upstream ids by label, either bare (`coding`) when the id is globally unique, or qualified (`vmr.coding`) when it isn't.

### 3.2 Desired State vs Current State

- **Desired State**: what the active profile *should* look like when compiled into a specific agent's config (computed purely in memory by an adapter).
- **Current State**: what managed fields actually say on disk right now.
- A write command **converges** Current → Desired, idempotently. If they already match, the command is a **no-op** (exit code 0).

### 3.3 Managed vs unmanaged fields

Each adapter declares a whitelist of *dot-path namespaces* it manages (e.g. Claude Code: `model`, `env.ANTHROPIC_BASE_URL`, …). Only these paths are ever written. Everything else in the file belongs to the host agent and is preserved byte-semantically — comments, key order, and formatting included where the format allows (see [§9.6](#96-secret-handling-and-masking)).

### 3.4 Drift

**Drift** = a managed field on disk differs from what ACM last wrote (someone — you or the agent runtime — changed it behind ACM's back). Any write command **blocks by default** when drift is detected. There is no automatic repair path; you either inspect and reconcile manually, or explicitly pass `--force` to overwrite. No silent convergence, ever.

### 3.5 Projection loss warnings

Some desired settings cannot be expressed by every agent (e.g. Codex has no `temperature` slot in `config.toml`). When a target agent can't express part of the Desired State, ACM emits a **ProjectionWarning** on stderr — the setting is skipped *loudly*, never silently dropped.

### 3.6 Credential references

Secrets are stored in `config.yaml` only as environment-variable references:

- `${VAR}` — resolve from env; hard error if unset.
- `${VAR:-default}` — fall back to a default value.

Syntax rules: **whole-field replacement only** — no substring interpolation (`foo-${VAR}-bar` is invalid), no nesting. If a referenced variable is missing at projection time, ACM aborts with exit code 1 **before any file is touched**.

Plaintext keys in `config.yaml` are technically allowed (a legitimate choice on a single-user machine), but `${VAR}` references are strongly recommended; some projections work better with them (see [§7.2](#72-codex-cli)).

### 3.7 The six-state machine

Every agent is always in exactly one state (shown by `acm status`):

| State | Meaning |
|---|---|
| `SYNCED` | On-disk managed fields exactly match the active profile; no drift. |
| `OUT_OF_SYNC` | Profile changed in ACM (or never projected) — disk doesn't match Desired State yet. |
| `DRIFTED` | Managed fields were modified externally after ACM's last write. |
| `ERROR` | Target config file is syntactically corrupted or unreadable. |
| `UNMANAGED` | Agent detected, but ACM has never written its config. |
| `NOT_DETECTED` | Agent not installed on this machine. |

Priority when multiple conditions hold: `ERROR > DRIFTED > OUT_OF_SYNC > SYNCED`.

### 3.8 Idempotency

Running `acm use daily` twice in a row: the second run detects everything already matches and reports `no-op` per agent, exit code 0. Safe to re-run, safe to script.

### 3.9 Profiles are member sets with an opt-in default, not runtime dispatch

A profile is a **named set of models** (`models: {label: model-ref}`), plus an *optional* `default` label — not a runtime rule engine. Example:

```yaml
# excerpt — assumes `providers:` already defines models `sonnet`/`o3` (see §5.6 for a complete file)
profiles:
  daily:
    default: coder      # opt-in: the only thing that drives an agent's default-model field
    models:
      coder: sonnet      # label -> model reference (bare id or provider.id)
      review: o3         # any other label — just another member, no special status
```

Key facts:

- **Registration and selection are independent.** `models:` is the full member set (≥ 1 entry required); `default`, when present, is the *only* signal that makes ACM write an agent's default-model field. There is no reserved "primary" label — a member named `coder` or `main` or anything else is just a label like any other; nothing is structurally special about it.
- **No `default` is a normal, valid declaration** — a "registration-only" profile. ACM never touches an agent's default-model namespace for such a profile — it's not a degraded state, just a different one. This is **zero warnings on Pi** (registration alone is the complete story there); Claude Code and Codex still emit **one explicit warning** that there's nothing to project for them, since they have no registry channel to fall back on — see §7.4.
- **Which members an agent can actually use depends on the agent's capability, not on the profile.** Claude Code and Codex have no model-registry channel: they can only ever project the opted-in `default` member; every other member produces one aggregate projection warning (`models.unreachable`) listing what was skipped — never silently dropped. Pi *does* have a registry channel: it registers **every** member into `models.json` regardless of whether `default` is set, and only uses `default` to drive `settings.json`'s `defaultProvider`/`defaultModel`. See §7.4.
- **"Different models for different situations" is achieved by switching profiles, not by automatic runtime dispatch.** The agent does not decide per task which model to use; *you* (or a script) switch the active profile:

  ```bash
  acm use daily     # every agent's default (if any) now points at daily's default member
  acm use budget    # ...and now budget's
  ```

  For Claude Code/Codex the config file's `model`/etc. fields are rewritten to point at the new default. For Pi: `settings.json` `defaultProvider`/`defaultModel` are updated; previously-registered providers remain in `models.json` by design — see §7.3.
- **To give different agents different models today**, project per agent (there is no global binding command yet):

  ```bash
  acm use daily claude_code    # Claude Code <- daily's default member
  acm use budget pi            # Pi <- budget's default member
  ```

> **💡 `/model` switching vs ACM — the division of labor.** Most agents (Claude Code `/model`, Codex `/model`, Pi `/model`, …) let you switch models interactively mid-session. That pool of selectable models belongs to the **agent's own mechanism** (built-in catalogs, its config files, or Pi's `models.json`/extensions). For agents with no registration channel (Claude Code, Codex), ACM projects only the **default member** plus connectivity — the `/model` candidate list stays entirely the agent's own. For Pi, ACM registers *every* declared member into `models.json` so they all show up in `/model` — see §7.3.

---

## 4. Quick Start

### 4.1 The minimal workflow

```bash
# 1. Initialize: scan installed agents + probe local VMR,
#    then interactively generate ~/.acm/config.yaml
acm init

# 2. Project the "daily" profile onto all detected agents
acm use daily

# 3. Check everyone's alignment state
acm status
```

That's the whole loop. Everything below elaborates on these steps.

### 4.2 With a local VMR running

If you run [VMR](https://github.com/bigfatsea/vmr) (Virtual Model Router) locally, `acm init` auto-detects it at `http://127.0.0.1:8800` (configurable via `$ACM_VMR_PROBE_URL`), imports its virtual model list, and generates a ready-to-use proposal — typically zero manual editing required.

### 4.3 Without VMR (direct connections)

Without VMR, `acm init` generates a commented template with example Anthropic/OpenAI direct providers. Edit `~/.acm/config.yaml`, fill in real model IDs, and make sure the referenced environment variables are exported (see §5). Direct connections to any OpenAI-/Anthropic-compatible endpoint are first-class citizens.

### 4.4 Verify the result

Run `acm status` — all detected agents should show `SYNCED`. You can also peek at the files themselves:

```bash
cat ~/.claude/settings.json     # model + env.ANTHROPIC_BASE_URL + env.ANTHROPIC_AUTH_TOKEN updated
cat ~/.codex/config.toml        # model + model_providers section updated, comments intact
cat ~/.pi/agent/models.json     # provider registered; settings.json defaultProvider/defaultModel set
```

---

## 5. Configuration Reference (`~/.acm/config.yaml`)

Full schema of the SSOT file. Validation is strict: unknown keys are rejected, cross-references are checked, and a broken file means every command fails fast with exit code 1.

### 5.1 Top level

```yaml
version: 2         # must be exactly 2 (upgrade notice otherwise)
```

At least one `providers:` entry with at least one embedded model, and at least one `profiles:` entry, are mandatory.

### 5.2 `providers.<name>` — L1 connectivity + embedded L2 models

| Field | Type | Required | Constraints |
|---|---|---|---|
| `protocol` | string | ✅ | One of `openai` \| `anthropic` \| `openai-responses` |
| `base_url` | string | ✅ | Must start with `http://` or `https://` |
| `api_key` | string | ✅ | `${VAR}`, `${VAR:-default}`, or plaintext (not recommended) |
| `headers` | mapping of strings | ❌ | Extra HTTP headers, e.g. `{ x-org-id: org-123 }` |
| `proxy` | string | ❌ | Proxy URL |
| `models` | mapping (see §5.3) | ❌ | Models offered by this provider, keyed by their upstream id |

> ⚠️ Unknown extra keys under `providers.*` are a validation error. Provider names may not contain `.` (it's the qualified-reference separator, §5.4) and must be non-empty with no leading/trailing whitespace.

### 5.3 `providers.<name>.models.<id>` — L2 model spec

The mapping key **is** the upstream model id verbatim, sent to the provider as-is (`claude-sonnet-4-5`, `gpt-4o`, even ids containing `.`/`/`/`:`) — there is no separate alias layer.

| Field | Type | Required | Constraints |
|---|---|---|---|
| `context_window` | int | ❌ | > 0 |
| `max_output_tokens` | int | ❌ | > 0 |
| `temperature` | float | ❌ | 0.0 – 2.0 |
| `capabilities` | table | ❌ | See below |
| `reasoning` | table | ❌ | See below |

`providers.<name>.models.<id>.capabilities`:

| Field | Type | Default | Values |
|---|---|---|---|
| `vision` | bool | `false` | |
| `tools` | string | `"native"` | `native` \| `xml` \| `markdown` |
| `json_mode` | bool | `false` | |
| `thinking` | bool | `false` | Model supports extended thinking — catalog metadata; projected like `json_mode` (warn where no agent channel exists) |

`providers.<name>.models.<id>.reasoning`:

| Field | Type | Constraints |
|---|---|---|
| `effort` | string | `low` \| `medium` \| `high` |
| `budget_tokens` | int | > 0 |

### 5.4 `profiles.<name>` — L3 member set + opt-in default

| Field | Type | Required | Notes |
|---|---|---|---|
| `models` | table (label → model reference) | ✅ | ≥ 1 entry. The profile's full member set — every label is a peer, nothing is structurally special |
| `default` | string | ❌ | Must name an existing label in `models:`. The *only* thing that drives ACM to write an agent's default-model field |

**Model reference syntax** (the value side of each `models:` entry):

| Form | Resolution | Failure |
|---|---|---|
| `<id>` (bare) | Looked up across every provider's `models:`; usable when the id is globally unique | 0 matches → unknown model; ≥2 matches → ambiguous, error lists every candidate provider |
| `<provider>.<id>` (qualified) | Split on the **first** `.` — provider names never contain a dot, so this is always unambiguous even when the id itself contains dots | provider or id not found → error |

> Any reference containing a `.` is *always* treated as qualified — the resolver never falls back to a bare lookup for it. In practice this means a model id that itself contains a dot can only be referenced in qualified form (`<provider>.<id>`), never bare, even if that id happens to be globally unique. It also means a bare-looking reference that happens to match `<some-provider-name>.<some-model-key>` resolves as qualified, not as a literal bare id — so avoid naming a provider such that `<provider>.<id>` collides with an id you meant to reference bare. `acm init`'s generated proposals always use qualified references to sidestep this entirely.

```yaml
# excerpt — assumes `providers:` already defines `coding`/`cheap` under some provider
# and `anthropic-direct` with model id `claude-sonnet` (see §5.6 for a complete file)
profiles:
  daily:
    default: coder                          # opt-in: only "coder" drives agent defaults
    models:
      coder: coding                         # bare id — OK if globally unique
      reviewer: anthropic-direct.claude-sonnet   # qualified — provider.id
      x: vmr.gpt-4o.2                       # id itself contains a dot: still OK, split on first dot only

  budget:
    models:
      fast: cheap                           # no `default` line: pure registration, agent defaults stay user-owned
```

Rules:

- `models:` must have at least one entry; an empty or missing map is rejected.
- `default`, if present, must equal one of the labels declared in `models:`.
- **No `default` is a normal, valid state (registration-only)**: members are still registered into agents with a registry channel (Pi), but no agent's default-model fields are touched. On Pi this produces **zero warnings**, since nothing is going unexpressed — unlike v1's `pool`-only profiles. Claude Code and Codex have no registry channel to fall back on, so they still emit one explicit warning that there's nothing to project (§5.4 table below and §7.4).
- Two labels in the same profile may not resolve to the same `(provider, upstream id)` pair, even via different reference strings (`both resolve to upstream model id '...' on provider '...'`) — that would produce indistinguishable duplicate entries in an agent's model selector.
- On agents with no registry channel (Claude Code, Codex): only the `default` member is ever projected; every other member is reported once as a single aggregate `models.unreachable` projection-loss warning — never silently dropped. With no `default` at all, these agents get zero ops and one explicit warning that there's nothing to project.

### 5.5 Cross-reference integrity

Validated on load, before anything happens:

- Provider names: non-empty, no leading/trailing whitespace, no `.`. Model ids (provider `models:` keys): non-empty.
- Every `profiles.*.models.*` reference resolves per §5.4's algorithm (existence + non-ambiguity).
- Every `profiles.*.default` (if set) names an existing label in that profile's `models:`.
- Every profile's `models:` has ≥ 1 entry; at least one profile must be defined.

### 5.6 Complete examples

**a) VMR-centric (auto-generated by `acm init` when VMR is detected):**

```yaml
version: 2

providers:
  vmr:
    protocol: openai
    base_url: http://127.0.0.1:8800/v1
    api_key: "${VMR_KEY:-}"   # leave empty for a keyless local VMR
    models:
      coding: {}

profiles:
  daily:
    default: coding
    models:
      coding: vmr.coding
```

**b) Anthropic official direct:**

```yaml
version: 2

providers:
  anthropic-official:
    protocol: anthropic
    base_url: https://api.anthropic.com
    api_key: "${ANTHROPIC_API_KEY}"
    models:
      claude-sonnet-4-5:
        context_window: 200000
        max_output_tokens: 8192
        temperature: 0.2
        reasoning:
          effort: high

profiles:
  daily:
    default: sonnet
    models:
      sonnet: claude-sonnet-4-5
```

**c) Multi-provider, multi-profile:**

```yaml
version: 2

providers:
  anthropic-direct:
    protocol: anthropic
    base_url: https://api.anthropic.com
    api_key: "${ANTHROPIC_API_KEY}"
    models:
      claude-sonnet-4-5:
        context_window: 200000
      claude-haiku-4-5: {}

  openai-direct:
    protocol: openai
    base_url: https://api.openai.com/v1
    api_key: "${OPENAI_API_KEY}"
    models:
      gpt-4o: {}

profiles:
  daily:
    default: sonnet
    models:
      sonnet: claude-sonnet-4-5
      cheap: claude-haiku-4-5

  budget:
    default: cheap
    models:
      cheap: claude-haiku-4-5

  experimental:
    default: flagship
    models:
      flagship: gpt-4o
      review: claude-sonnet-4-5        # any other member — just a label, no special status
```

Switch with `acm use daily`, `acm use budget`, `acm use experimental`.

**d) Third-party OpenAI-compatible relay:**

```yaml
version: 2

providers:
  relay:
    protocol: openai          # match the wire protocol the relay speaks
    base_url: https://relay.example.com/v1
    api_key: "${RELAY_KEY}"
    models:
      their-flagship-model-name: {}

profiles:
  daily:
    default: flagship
    models:
      flagship: their-flagship-model-name
```

### 5.7 Common validation errors

| Message fragment | Cause | Fix |
|---|---|---|
| `Unsupported config schema version` | `version ≠ 2` | Set `version: 2` |
| `must not contain '.'` | a provider name has a dot in it | Rename the provider (dots are reserved for `provider.id` references) |
| `unknown model id '...'` | bare id not defined under any provider | Define the model, or fix the id |
| `model id '...' is ambiguous` | bare id defined under ≥2 providers | Qualify the reference as `<provider>.<id>` |
| `is not defined under provider '...'` | qualified reference's id doesn't exist under that provider | Define the model, or fix the provider/id |
| `must define at least one entry under 'models'` | a profile's `models:` is empty or missing | Add at least one member |
| `is not a member defined under 'models'` | `default:` names a label that doesn't exist | Fix the label, or add it as a member |
| `Configuration must define at least one profile` | no `profiles:` entries | Add one |
| `base_url must start with http(s)://` | malformed endpoint | Fix URL scheme |
| `both resolve to upstream model id '...' on provider '...'` | two labels in one profile resolve to the same `(provider, id)` | Use a distinct upstream model, or drop the duplicate label |
| `Invalid credential reference syntax` | e.g. `pre-${VAR}-post` | Use whole-field `${VAR}` only |
| `Extra inputs are not permitted` | typo'd key in a strict table (e.g. leftover v1 `main:`/`cheap:`/`pool:`, or a top-level `models:`) | Correct the key name — see §5.4 |

---

## 6. Command Reference

### 6.0 Global options

| Option | Applies to | Effect |
|---|---|---|
| `--dry-run` | `init`, `use`, `rollback` | Preview operations without writing anything |
| `--force`, `-f` | `init`, `use`, `rollback` | `init`: overwrite existing config without prompting · `use`: override drift/corruption safety blocks · `rollback`: confirm archiving of newly created files without prompting |
| `--verbose`, `-v` | `status`, `use` | Detailed logging (also written to `~/.acm/logs/acm.log`) |
| `--show-secrets` | `status`, `use` | Display secrets in plaintext instead of masked (**opt-in**) |
| `--no-color` | all | Disable colored output (also honors `NO_COLOR` env) |
| `--version`, `-v` | top level | Print version and exit |

> ⚠️ Note the `-v` collision: at the **top level** (`acm -v`) it means `--version`; inside subcommands (`acm use daily -v`) it means `--verbose`.

### 6.1 `acm init`

```bash
acm init [--dry-run] [--force] [--no-color]
```

Scans locally installed agents, probes for a local VMR, generates a proposed `~/.acm/config.yaml`, validates it, and (after confirmation) writes it.

Flow in detail:

1. Detects installed agents (per-adapter rules, see §7: a well-known executable on `PATH`, or the agent's home directory such as `~/.claude`).
2. Probes VMR (see §8.2). Detected → generates a VMR-tailored proposal importing discovered models; not detected → generates a commented direct-connect template.
3. Validates the proposal (syntax + schema) before showing it — a validation failure aborts with exit code 1.
4. Prints the proposal. With `--dry-run`, stops here (nothing is ever written).
5. Asks for confirmation (default Yes) and writes:
   - `~/.acm/config.yaml` (mode `0600`)
   - `~/.acm/state/`, `~/.acm/logs/` (mode `0700`)
   - `~/.acm/.gitignore` (ignoring `state/`, `logs/`, `.lock`, temp files)

**Behavior when config already exists:** prompts "Overwrite existing configuration?" with **default = Cancel** — interactive runs never silently clobber your existing SSOT. Use `--force` to overwrite deliberately. (With `--dry-run` the prompt is skipped entirely, so you can safely preview even with an existing config.)

Typical output:

```
Detected 3 local coding agent(s): Claude Code, Codex CLI, Pi Agent
Probing local Virtual Model Router (VMR)...
✓ VMR detected at http://127.0.0.1:8800/v1 with 4 model(s).

── Proposed ~/.acm/config.yaml ────────────────────────
...
Write configuration to /Users/you/.acm/config.yaml? [Y/n]:
✓ Successfully initialized ACM at ~/.acm/config.yaml!
Next step: Run acm use daily to project models to your agents.
```

### 6.2 `acm status`

```bash
acm status [agent] [--verbose] [--show-secrets] [--no-color]
```

Prints the alignment table for all detected agents (or one, via its adapter ID: `claude_code`, `codex`, `pi`):

```
                              ACM Agent Status
┏━━━━━━━━━━━━━┳━━━━━━━━━━━━━┳━━━━━━━━━━━━━━━━┳━━━━━━━━━━━━━━━┳━━━━━━━━━━━━━┓
┃ Agent       ┃ State       ┃ Active Profile ┃ Last Synced   ┃ Details     ┃
┡━━━━━━━━━━━━━╇━━━━━━━━━━━━━╇━━━━━━━━━━━━━━━━╇━━━━━━━━━━━━━━━╇━━━━━━━━━━━━━┩
│ Claude Code │ SYNCED      │ daily          │ daily (20260… │ -           │
│ Codex CLI   │ DRIFTED     │ daily          │ daily (20260… │ Drift in    │
│             │             │                │               │ model: …    │
└─────────────┴─────────────┴────────────────┴───────────────┴─────────────┘
```

- **State** — see §3.7.
- **Details** shows syntax error messages (ERROR) and drift entries as `expected '…', found '…'`. Sensitive values are masked unless `--show-secrets`.
- With `--verbose`, also lists current projection warnings.
- If the active profile fails to resolve (e.g. its `${VAR}` is unset), a yellow `Notice:` line is printed and agents are assessed without a desired profile.
- `[agent]` must be a built-in adapter ID (`claude_code`, `codex`, `pi`) — an unknown ID exits with code 4. `status` itself never modifies anything and exits 0 unless the config can't be loaded.

### 6.3 `acm use`

```bash
acm use <profile> [agent] [--dry-run] [--force] [--show-secrets] [--verbose] [--no-color]
```

**Semantics: switch the Desired State and converge immediately.**

Execution order:

1. Loads & validates `config.yaml`, resolves `<profile>` against the current environment. Unknown profile ⇒ exit code 4 with a list of available profiles; missing `${VAR}` ⇒ hard error, exit 1 — both before anything is written.
2. Records `<profile>` as active (`~/.acm/state/active`).¹
3. For each detected agent (or only the given one):
   - `ERROR` state → **safety block** (unless `--force`, which reconstructs the file with ACM-managed fields — corrupted content cannot be preserved).
   - `DRIFTED` → **safety block** listing each drifted field as `expected vs found` (unless `--force`). Special case: if all fields already match the desired state despite drift, it's reported as a no-op rather than blocking.
   - `SYNCED` → reported as `no-op`, skipped.
   - Otherwise compiles ops via the adapter and executes them through the Safety Engine (§9.1).
4. Projection-loss warnings are aggregated and printed to stderr.
5. Exit code = highest severity encountered (0 ok / 2 blocked / 3 I/O error).

¹ *Detail worth knowing:* the active profile is recorded before per-agent projection. If an agent is subsequently blocked, `status` will show the new profile as active with that agent `DRIFTED`/`ERROR` — the intent is remembered even though that agent didn't converge.

**Agent selection semantics:** `[agent]` must be a built-in adapter ID (`claude_code`, `codex`, `pi`):
- Unknown ID ⇒ exit code 4.
- Named agent exists but is **not detected on this machine** ⇒ error, exit code 4.
- In batch mode (no `[agent]`), undetected agents are silently skipped — only detected ones are projected.

**Batch semantics:** agents are processed independently. One blocked agent doesn't undo successful projections of others; the failing agents are named on stderr and the final exit code is non-zero.

Note that `--dry-run` skips step 2 as well — nothing at all is written, including the active-profile record.

`--dry-run` prints planned operations per agent, e.g.:

```
[Dry-run] Planned operations for Claude Code:
  • settings.json :: model -> claude-sonnet-4-5
  • settings.json :: env.ANTHROPIC_BASE_URL -> https://api.anthropic.com
  • settings.json :: env.ANTHROPIC_AUTH_TOKEN -> sk-a...xyz
```

### 6.4 `acm rollback`

```bash
acm rollback [agent] [--dry-run] [--force] [--no-color]
```

**Semantics: restore each target agent's config to the state captured just before ACM's last write** (snapshot-based restore — the MVP rollback mechanism; journal-based field-level rollback arrives in a later milestone).

Per agent:

1. Determines the restore target: the `backup_id` recorded in `last_write.json`, falling back to the latest snapshot (with a warning) if missing.
2. Takes a **new snapshot first** — rollbacks themselves are undoable (an undo-undo chain).
3. Restores files captured in that snapshot via atomic replace.
4. Files that **did not exist** before ACM's write (recorded via `.not_exist_*` sentinels) are archived — renamed next to their original location as `<file>.acm_orphaned.<snapshot-id>` — rather than deleted.
5. Rebuilds `last_write.json` from the restored disk state.

**Confirmation for archiving newly created files:** if any currently-existing file would be archived (i.e. ACM created it during projection), interactive sessions ask for confirmation; **non-interactive (piped/scripted) runs abort with a safety-block error unless `--force` is passed.**

No snapshot history (agent never projected) → reports accordingly; with an explicit `[agent]` argument this is exit code 4.

### 6.5 Exit codes

ACM is designed for scripting — the exit code *is* the API:

| Code | Meaning | Typical causes |
|---|---|---|
| `0` | Success (including idempotent no-op) | |
| `1` | Configuration error | YAML syntax/schema error; unresolved `${VAR}`; no config (`run acm init first`); usage error |
| `2` | Safety block | External drift; corrupted config (ERROR) without `--force`; lock contention; whitelist violation |
| `3` | I/O / permission failure | Disk errors during projection/init |
| `4` | Resource not found | Unknown agent ID; agent not installed; no snapshot for requested agent |
| `130` | Interrupted | SIGINT (Ctrl-C) |

Normal output goes to stdout; errors and warnings go to stderr.

### 6.6 Planned commands (and today's equivalents)

Several commands from the governing spec ship in later milestones. Until then:

| Planned | Purpose | What you can do today |
|---|---|---|
| `acm apply` | Converge without changing the active profile | `acm use <active-profile>` achieves the same convergence |
| `acm diff <agent>` | Show current vs desired/snapshot differences | Compare `acm status` drift details; inspect `~/.acm/state/<agent>/snapshots/<latest>/` manually |
| `acm doctor` | Full diagnostics | `acm status --verbose` + check `~/.acm/logs/acm.log` |
| `acm history` | Transaction log | Browse `~/.acm/state/<agent>/last_write.json` and `snapshots/` (timestamp-named directories) |
| `acm release` | Un-manage and restore pre-ACM values | Run `acm rollback <agent>` (restores pre-projection snapshot); or simply uninstall ACM — files stay in their last effective state and keep working |
| `acm import vmr` | Incrementally merge new VMR models | Re-run `acm init --force` (regenerates SSOT), or edit `config.yaml` by hand |

---

## 7. Agent Adapters

### 7.0 How adapters work

Each agent is supported by one built-in Python module implementing a tiny pure-function contract:

- `detect()` — is the agent installed?
- `config_paths()` — the closed whitelist of files ACM may touch;
- `managed_namespaces()` — the dot-path whitelist within those files;
- `plan(profile)` — compile a resolved profile into field-level desired ops + projection warnings. **Adapters never touch the disk**; all writes flow through the Safety Engine.

All adapters are compiled-in source with golden-fixture test gates — no dynamic code loading, no supply-chain surprises. Adapter IDs for CLI arguments: `claude_code`, `codex`, `pi`.

Detection rule per adapter ("is this agent installed?"): an adapter reports *detected* if its CLI executable is found on `PATH` (**`claude`** / **`codex`** / **`pi`**) **or** its home directory exists (`~/.claude` / `~/.codex` / `~/.pi/agent` respectively).

### 7.1 Claude Code

- **Managed file**: `~/.claude/settings.json` (JSON). Never touches `~/.claude.json` runtime state.
- **Managed namespaces**: `model`, `env.ANTHROPIC_BASE_URL`, `env.ANTHROPIC_AUTH_TOKEN`, `env.ANTHROPIC_API_KEY`, `effortLevel`.

Projection mapping (only the profile's `default` member is ever projected — see §3.9):

| Your config | Written to `settings.json` |
|---|---|
| default member's upstream id | `model` |
| default member's provider `base_url` | `env.ANTHROPIC_BASE_URL` |
| default member's provider `api_key` (resolved value) | `env.ANTHROPIC_AUTH_TOKEN` |
| default member's `reasoning.effort` | `effortLevel` |

Notes & caveats:

- Claude Code speaks the Anthropic Messages protocol. If the selected provider's protocol isn't `anthropic`, ACM still projects but emits a warning reminding you the endpoint must be Anthropic-compatible (or proxied via VMR).
- Because Claude Code consumes the actual token at runtime, the **resolved credential value** is written into `settings.json`'s env block (this is inherent to how Claude Code works — it doesn't support `${VAR}` indirection there).
- No `default` declared: zero ops, one explicit warning — nothing to project.
- Projection losses (warnings): `budget_tokens`, `context_window`, `temperature`, `capabilities`, custom headers/proxy, other (non-default) members (aggregated as `models.unreachable`).

Example result after `acm use daily`:

```json
{
  "model": "claude-sonnet-4-5",
  "env": {
    "ANTHROPIC_BASE_URL": "https://api.anthropic.com",
    "ANTHROPIC_AUTH_TOKEN": "sk-ant-…"
  },
  "effortLevel": "high",
  "permissions": { "...your own settings stay untouched..." : true }
}
```

### 7.2 Codex CLI

- **Managed file**: `~/.codex/config.toml` (TOML, round-trip edited — your comments, including commented-out `mcp_servers`, are preserved).
- **Managed namespaces**: `model`, `model_provider`, `model_reasoning_effort`, `model_providers`.
- ℹ️ Earlier project documents describe a future dual-file transaction including `~/.codex/auth.json`; **the current implementation manages `config.toml` only** and never touches `auth.json`.

Projection mapping (only the profile's `default` member is ever projected — see §3.9):

| Your config | Written to `config.toml` |
|---|---|
| default member's upstream id | `model` |
| default member's provider name | `model_provider` |
| default member's `reasoning.effort` | `model_reasoning_effort` |
| default member's provider `base_url` | `model_providers.<name>.base_url` |
| protocol `openai`/`openai-responses` → `responses`; `anthropic` → `chat` (+warning) | `model_providers.<name>.wire_api` |
| ENV var name extracted from `${VAR}` | `model_providers.<name>.env_key` |

Notes & caveats:

- Codex reads the API key from the environment itself (`env_key`). Therefore **the `api_key` should be a `${VAR}` reference** — ACM writes just the variable *name* into `env_key`. If you configured a plaintext key instead, ACM falls back to `env_key = "OPENAI_API_KEY"` with a warning telling you to export it.
- An `anthropic`-protocol provider triggers a dialect warning (Codex natively speaks OpenAI wire protocols; route Anthropic models through a compatible endpoint or VMR).
- No `default` declared: zero ops, one explicit warning — nothing to project.
- Projection losses (warnings): `budget_tokens`, `context_window`, `temperature`, `capabilities`, headers/proxy, other (non-default) members (aggregated as `models.unreachable`).

Example result:

```toml
model = "gpt-4o"
model_provider = "openai-direct"
model_reasoning_effort = "high"

[model_providers.openai-direct]
name = "openai-direct"
base_url = "https://api.openai.com/v1"
wire_api = "responses"
env_key = "OPENAI_API_KEY"

# your commented mcp_servers and everything else remain exactly as-is
```

### 7.3 Pi Agent

- **Managed files**: `~/.pi/agent/models.json` + `~/.pi/agent/settings.json`. **Never touches `models-store.json`** (Pi's internal store), nor `extensions/`, `skills/`, `sessions/`.
- **Managed namespaces**: `providers`, `defaultProvider`, `defaultModel`, `defaultThinkingLevel`.

**Two coexisting ways to register providers in Pi (both officially supported, *stacking* — not mutually exclusive):**

| Channel | Mechanism | When to use | ACM's role |
|---|---|---|---|
| `~/.pi/agent/models.json` | Declarative provider+model entries; Pi reloads it every time you open `/model` | Static endpoints/proxies with OpenAI/Anthropic-compatible APIs | **ACM writes here** (`providers.<name>` entry) |
| `extensions/*.ts` + `pi.registerProvider(...)` | Programmatic registration at startup; supports custom APIs, OAuth flows, dynamic `refreshModels` | Custom endpoints, proxies, team-wide configs, custom auth | ACM never touches `extensions/` |

Per the official docs, an extension-registered provider is the composition base and **`models.json` overrides still apply above it** — both channels appear together in the `/model` picker.

Projection mapping — **registration and selection are independent** (§3.9): every profile member is registered unconditionally; `settings.json` is only touched when `default` is set.

| Your config | Written to |
|---|---|
| every member, grouped by provider → full entry `{ baseUrl, api, apiKey, models: [{id, name, contextWindow?, maxTokens?}] }` | `models.json` `providers.<name>` |
| member's `context_window` / `max_output_tokens` | `contextWindow` / `maxTokens` inside the model entry |
| protocol: `anthropic`→`anthropic-messages`; `openai-responses`→`openai-responses`; `openai`→`openai-completions` | `api` field |
| default member's provider name / upstream id | `settings.json` `defaultProvider` / `defaultModel` (only if `default` is set) |
| default member's `reasoning.effort` | `settings.json` `defaultThinkingLevel` |

Credential handling in `models.json`: if your `api_key` is a `${VAR}` reference and `VAR` is exported, ACM writes Pi-style `"$VAR"` so Pi expands it at runtime; otherwise it writes the resolved value (or `dummy` + warning for a keyless provider).

**Registry-style incremental registration (important):** Pi accumulates providers across profile switches — switching from profile A (provider X) to profile B (provider Y) *keeps X* registered in `models.json`, because historical sessions may still reference it. Consequences:

- Old providers don't break anything; they just linger.
- To clean up, delete unused `providers.<name>` entries manually, or run `acm rollback` to restore a pre-projection snapshot.

Projection losses (warnings): `budget_tokens` (default member only), `temperature`, `capabilities.tools` (non-native dialect) / `capabilities.json_mode` / `capabilities.thinking`, `proxy`. Unlike Claude Code/Codex, Pi **does** consume `context_window`, `max_output_tokens`, provider-level `headers` (written to `providers.<name>.headers` — confirmed supported by Pi's own docs), and **does** consume `capabilities.vision` (written to the model entry's `input: ["text", "image"]` field). Pi can express per-model temperature via model-level `samplingParams` on OpenAI-compatible dialects, which ACM does not project yet — so a declared temperature still warns, with wording that says exactly that. Pi has no separate `proxy` concept, so that one remains a genuine projection loss.

**Multi-model `/model` support (native, always on):** Pi is the only current adapter with a real registration channel, so ACM registers *every* declared member into `models.json`, not just the default:

```yaml
# excerpt — assumes `providers:` already defines models `coding`/`cheap`/`agent`/`o3` (see §5.6)
profiles:
  daily:
    default: coding
    models:
      coding: coding
      budget: cheap
      longctx: agent
      review: o3          # may live on a different provider
```

- Members are grouped by provider; each provider gets one `providers.<name>` entry whose `models[]` array carries the whole group.
- Each member's `label` becomes its model entry's `name` field — per Pi's own docs, `/model`, `--list-models`, and the interactive footer display entries **by `id`**; `name` is used only for `--model` pattern matching and as **secondary detail text**, not the picker's primary label.
- `id` is always the real upstream model id sent to the API; the label only affects the secondary detail text, not the picker's primary display.
- `defaultProvider`/`defaultModel`/`defaultThinkingLevel` in `settings.json` are driven purely by the opted-in `default` member (and are simply not written at all if there is no `default`), independent of every other registered member.
- Per-member `reasoning` is not projected; declaring it on a non-default member produces its own warning. `capabilities.vision` **is** projected into the model entry's `input` field; `temperature` and the genuinely unexpressible capability sub-fields (`tools` non-native dialect / `json_mode` / `thinking`) warn individually — temperature's warning notes that Pi itself could express it via model-level `samplingParams` (OpenAI-compatible dialects), ACM just does not write that yet. Provider-level `headers` is projected into `providers.<name>.headers` regardless of whether the provider is the default's; `proxy` is a concept Pi doesn't have, so a non-default provider's `proxy` setting still warns (nothing is silently dropped).
- `acm use` / `status` / `rollback` treat a multi-model `providers.<name>` payload exactly like a single-model one — same op, same whitelist, same drift/rollback semantics.

**Combining ACM's registration with a hand-written `models.json` or an extension:** ACM's per-provider entries coexist with anything you (or an extension) register separately; the `/model` picker shows the union.

1. Let ACM own the default and registration: `acm use <profile> pi`.
2. Provide additional models separately — either a hand-written `models.json` entry or an extension (`pi.registerProvider(...)`). ACM never touches `extensions/` and never deletes extra entries it didn't write.
3. ⚠️ Naming: ACM overwrites the *same-named* `providers.<name>` entry on each projection, so give ACM's provider a distinct name from any extension/provider you author by hand (e.g. ACM `vmr` vs extension `vmr_openai`) to avoid mutual overwrites.

### 7.4 Capability matrix (what gets projected, what warns)

| Desired setting | Claude Code | Codex CLI | Pi |
|---|---|---|---|
| default member's upstream id | ✅ `model` | ✅ `model` | ✅ `defaultModel` (all members also registered) |
| base_url | ✅ `env.ANTHROPIC_BASE_URL` | ✅ `model_providers.*.base_url` | ✅ `baseUrl` |
| api_key | ✅ resolved value → `env.ANTHROPIC_AUTH_TOKEN` | ✅ env-var *name* → `env_key` | ✅ `$VAR` or resolved value → `apiKey` |
| `reasoning.effort` | ✅ `effortLevel` | ✅ `model_reasoning_effort` | ✅ `defaultThinkingLevel` |
| `reasoning.budget_tokens` | ⚠️ warn | ⚠️ warn | ⚠️ warn |
| `context_window` | ⚠️ warn | ⚠️ warn | ✅ `contextWindow` |
| `max_output_tokens` | ⚠️ warn | ⚠️ warn | ✅ `maxTokens` |
| `temperature` | ⚠️ warn | ⚠️ warn | ⚠️ warn (Pi itself could express it via model-level `samplingParams` on OpenAI dialects; ACM does not project it yet) |
| `capabilities.vision` | ⚠️ warn | ⚠️ warn | ✅ model entry `input: ["text", "image"]` |
| `capabilities.tools` / `.json_mode` / `.thinking` | ⚠️ warn | ⚠️ warn | ⚠️ warn (no Pi channel) |
| provider `headers` | ⚠️ warn | ⚠️ warn | ✅ `providers.<name>.headers` |
| provider `proxy` | ⚠️ warn | ⚠️ warn | ⚠️ warn (Pi has no such concept) |
| non-default members | ⚠️ aggregate `models.unreachable` warn, only `default` projected | ⚠️ aggregate `models.unreachable` warn, only `default` projected | ✅ every member registered into `models.json`, label → `name` (secondary detail text; the picker's primary display is `id`) |
| no `default` declared | ⚠️ one warn, zero ops | ⚠️ one warn, zero ops | zero warnings — members still registered, `settings.json` untouched |

✅ = projected · ⚠️ warn = skipped with an explicit projection-loss warning on stderr.

### 7.5 Roadmap adapters

- **P1**: Aider (`~/.aider.conf.yml` + model metadata JSON; role models main/weak/editor), Gemini CLI, OpenCode (JSONC comment preservation).
- **P2 (community contributions)**: OpenClaw, Hermes, Cursor/Cline (public settings channels only).

---

## 8. VMR Integration

### 8.1 What is VMR?

VMR (Virtual Model Router) is a companion local router that exposes many upstream models through one OpenAI-style endpoint. ACM integrates with it as a **first-class convenience, not an architectural dependency** — everything works identically without it.

### 8.2 Probe sequence (`acm init`)

1. `GET $ACM_VMR_PROBE_URL/v1/models` (default host `http://127.0.0.1:8800`) — primary source and evidence; discovered model IDs (and optional `vmr_protocol` hints) become entries under `models:`. Sent with a bearer credential when one is available (see Authentication below). A `401`/`403` response is itself proof VMR is running and gated — reported immediately, never silently swallowed.
2. `GET $ACM_VMR_PROBE_URL/health` (unauthenticated liveness — VMR's `/healthz` successor; `/healthz` was permanently removed from VMR's routing table) — only consulted when step 1 failed for a reason *other than* 401/403. A `200` there means VMR is up but `/v1/models` itself is unreachable; the proposal is generated with a placeholder model in that case.

Probes are fault-tolerant and time out quickly; a machine without VMR (both steps fail) proceeds straight to the direct-connect template.

#### Authentication

If VMR is configured with `api_keys:`, `/v1/models` requires a credential. Set `VMR_KEY` — the same variable the generated proposal's `providers.vmr.api_key` references (`${VMR_KEY:-}`), so one variable covers both probing and later `acm use` projection.

Without a valid credential, `acm init` prints an explicit stderr warning ("VMR detected ... but requires authentication") — never the misleading "VMR not running" — and falls back to the direct-connect template so the command still completes (`exit 0`). The credential is only ever sent in the request header; it never appears in any ACM output.

### 8.3 Generated proposal

When VMR is detected, `acm init` produces: a `providers.vmr` entry pointing at `<host>/v1` with one entry under its embedded `models:` per discovered model (keyed by the model's own id, verbatim — no name sanitization), and a `profiles.daily` profile whose `models:` registers every discovered model (referenced by qualified `vmr.<id>`, avoiding any bare-id ambiguity) with `default` set to a model named `coding` if present, else the first discovered model — so a fresh `acm init && acm use daily` points every detected agent at VMR out of the box. The `base_url` is built by appending `/v1` to the host ACM used to probe VMR — semantically equivalent to what VMR's own `/status.instance.base_urls` would echo back for that same host, just derived independently rather than round-tripped through that endpoint.

### 8.4 Keeping up with VMR changes

If VMR's model list changes later, either edit `~/.acm/config.yaml` by hand (add/remove entries under the provider's `models:`) or re-run `acm init --force` to regenerate. (A dedicated incremental `acm import vmr` is a planned trigger-based upgrade.)

---

## 9. The Safety Model

Understanding this chapter is what lets you trust ACM with your agent configs.

### 9.1 The six-step write pipeline

Every physical write — regardless of command — passes through one choke point (the Safety Engine) executing:

1. **Whitelist validation** — every op's target file must be in the adapter's declared path set, and its dot-path within declared namespaces. Anything else ⇒ `SafetyBlockedError` (exit 2). ACM physically cannot write elsewhere.
2. **Pre-write snapshot + op expansion** — full byte copies of every affected file go into an append-only snapshot directory (files that don't exist get `.not_exist_*` sentinel markers). Original values of all touched fields are captured.
3. **In-memory mutation + self-check + AST assertion** — the new content is produced in memory; parsed to prove valid syntax; then the parse trees *before vs after* are diffed, asserting that **zero unmanaged paths changed**. Any unexpected mutation aborts the write.
4. **Pre-commit fingerprint check** — SHA-256 of every target file is re-verified against the pre-snapshot hash. If anything modified the file concurrently mid-transaction ⇒ abort, nothing committed.
5. **Atomic replace** — content is written to a temp file (`*.acm_tmp`, mode `0600`) then swapped in with `os.replace` per file. No torn/half-written states, ever.
6. **Record** — `last_write.json` is updated (profile, timestamp, backup id, managed-field values, created files). This powers drift detection and rollback.

Multi-file agents (Pi manages two files) are committed sequentially inside one lock; the snapshot chain makes recovery deterministic.

### 9.2 Whitelist enforcement

Two layers: the file boundary (adapter-declared absolute paths, resolved and compared) and the namespace boundary (dot-path prefixes such as `env.` for specific keys only). This is why ACM can *never* develop a bug that wipes your MCP servers — those paths aren't writable, period.

### 9.3 Snapshots

- Location: `~/.acm/state/<agent>/snapshots/<timestamp-id>/` (UTC, lexicographically sortable IDs).
- Append-only: never pruned automatically. Agent configs are small (KBs), so growth is modest.
- Also serve as read-only audit evidence ("what did this file look like before ACM touched it?").

### 9.4 Concurrency control

A global non-blocking exclusive file lock (`fcntl.flock` on `~/.acm/state/.lock`) serializes all mutating commands. A second concurrent `acm` process fails fast:

```
⚠️ Another acm process is holding the write lock. Operation aborted.   (exit 2)
```

Orphaned temp files from crashed runs are cleaned up automatically at the start of the next write.

### 9.5 Drift detection & blocking

On every `status`/`use`, ACM compares each managed field's disk value with the value recorded at last write. Mismatches ⇒ `DRIFTED`, and writes are blocked with a field-by-field `expected vs found` report. Your options:

1. Inspect (`acm status`, compare with the latest snapshot), decide who's right;
2. Reconcile manually (edit the agent file back, or update `config.yaml` to adopt the new reality);
3. Or override deliberately with `acm use --force` (external changes are overwritten).

Special case: if the disk differs from last-write but *already equals* the desired state, `use` treats it as a no-op success instead of blocking.

### 9.6 Secret handling and masking

- `config.yaml` stores references (`${VAR}`), not secrets — commit-friendly.
- Wherever values are displayed (drift details, dry-run plans), sensitive-looking values (`api_key`, `token`, `auth`, `secret`, `password`, `credential` — case-insensitive) are masked: first 3 + `...` + last 3 characters (short values become `***`). `${VAR}` reference forms are shown as-is.
- Pass `--show-secrets` to opt into plaintext display.
- Filesystem hygiene: `~/.acm` state/log dirs `0700`; generated files `0600`.
- Format fidelity note (honest fine print): unmanaged content preservation is guaranteed at the **semantic** level (hard promise); retention of comments/key order/whitespace is defined per format by golden fixtures — JSON preserves key order & indentation style, TOML (tomlkit) round-trips comments/order/blank lines.

### 9.7 Crash & interruption resilience

Atomic replaces mean a crash can never leave a half-written config. Fault-injection tests (SIGKILL between replaces, concurrent tampering, injected disk failures, lock contention) back these guarantees. If a crash left orphaned `*.acm_tmp` files, they're swept automatically before the next transaction; snapshots allow manual restoration of any prior state.

---

## 10. State Directory & Internals

### 10.1 Layout

```
~/.acm/
├── config.yaml                  # SSOT (yours to edit/version)
├── .gitignore                   # ignores state/, logs/, .lock, tmp files
├── logs/
│   └── acm.log                  # operation log (INFO; DEBUG with --verbose)
└── state/
    ├── .lock                    # global write-lock file
    ├── active                   # name of the active profile (plain text)
    ├── claude_code/
    │   ├── last_write.json
    │   └── snapshots/<ts>/…
    ├── codex/
    │   ├── last_write.json
    │   └── snapshots/<ts>/…
    └── pi/
        ├── last_write.json
        └── snapshots/<ts>/…
```

Configuration and state are strictly separated: ACM never writes runtime state back into `config.yaml`.

### 10.2 `state/<agent>/last_write.json`

```json
{
  "profile": "daily",
  "timestamp": "20260825014320123456",
  "backup_id": "20260825014320123456",
  "fields": {
    "settings.json::model": "claude-sonnet-4-5",
    "settings.json::env.ANTHROPIC_BASE_URL": "https://api.anthropic.com"
  },
  "created_files": []
}
```

- `fields` maps `"file::dotpath"` → the value ACM wrote (basis for drift detection);
- `backup_id` points at the snapshot taken just before that write (basis for rollback);
- `created_files` lists files ACM newly created (archived rather than restored on rollback).

### 10.3 Snapshots

`state/<agent>/snapshots/<snapshot-id>/<original-filename>` holds byte-exact copies; a `.not_exist_<filename>` marker records that the file did not exist before the write.

### 10.4 Environment variables

| Variable | Default | Purpose |
|---|---|---|
| `ACM_HOME` | `~/.acm` | relocate ACM's entire home (config + state) |
| `ACM_VMR_PROBE_URL` | `http://127.0.0.1:8800` | VMR probe endpoint used by `acm init` |
| `NO_COLOR` | — | disable colored output |

(`ACM_TEST_FAULT_*` variables exist solely for the test suite's fault injection — never set them in production.)

---

## 11. Recipes (Common Workflows)

### R1 · First-time setup: official API → all agents

```bash
export ANTHROPIC_API_KEY=sk-ant-…
acm init                       # no VMR → template; edit providers/models to taste
${EDITOR:-vi} ~/.acm/config.yaml
acm use daily
acm status                     # expect all SYNCED
```

### R2 · Switch between daily and economy profiles

Define both profiles (see §5.6c), then:

```bash
acm use daily && acm status    # working setup
acm use budget                 # flip everything to the cheap model
acm use daily                  # ...and back; second run would be a no-op
```

### R3 · Point everything at a local gateway / relay

Either run VMR (then `acm init` picks it up automatically), or declare a provider whose `base_url` targets your relay (§5.6d) and `acm use daily`.

### R4 · I hand-edited my agent's config — now what?

```bash
acm status                     # agent shows DRIFTED with expected/found details
```

Decide: keep your manual change → also record it in `config.yaml` (make ACM's desired state match), then `acm use daily` converges cleanly; discard it → `acm use daily --force` restores ACM's values.

### R5 · Undo the last projection

```bash
acm rollback --dry-run         # preview what will be restored/archived
acm rollback                   # restores pre-write snapshot; archives ACM-created files
acm status                     # verify
```

Rolled back too far? Snapshots are append-only — grab any older file from `~/.acm/state/<agent>/snapshots/`.

### R6 · Operate on a single agent

```bash
acm use daily codex            # project to Codex only
acm rollback pi                # roll back only Pi
acm status claude_code         # inspect only Claude Code
```

### R7 · Version-control the SSOT (team baseline)

`config.yaml` contains only `${ENV}` references, and `.gitignore` already excludes state/logs — so `~/.acm` (or a copy of `config.yaml` in your repo) is safe to commit. Team members export their own credentials locally.

### R8 · Scripting & CI

```bash
acm use production --no-color --force
case $? in
  0) echo converged ;;
  2) echo "blocked (drift/lock)"; exit 2 ;;
  *) echo "failed"; exit 1 ;;
esac
```

Tips: rely on exit codes (§6.5); remember non-TTY `rollback` needs `--force` when files would be archived; use `--dry-run` for plan previews.

### R9 · Leaving ACM

ACM is absolutely non-intrusive. To stop using it: just uninstall (`uv tool uninstall agent-config-manager`) and optionally delete `~/.acm/`. Agent configs remain in their last projected state and keep working. Nothing to "release". (If you want configs reverted to their pre-ACM values first, run `acm rollback` per agent before uninstalling.)

---

## 12. Troubleshooting & FAQ

**❓ How does ACM relate to `/model` switching and multi-model setups (e.g. Pi extensions)?**
`/model` is each agent's runtime capability — the pool of selectable models comes from the agent itself (built-in catalogs; for Pi additionally `models.json` entries and `pi.registerProvider()` extensions). ACM manages a different layer: it registers your declared members and projects the **default member** plus connectivity, aligning all agents with your SSOT. They compose cleanly: `acm use <profile>` sets the default; `/model` overrides per session. For Pi, ACM registers every member you declare, so they all already show up in `/model` — no separate extension needed unless you want models ACM doesn't know about. See §3.9 and §7.3.

**❓ How do profiles work? Which model does each agent actually get?**
A profile is a named member set (`models: {label: ref}`, ≥ 1 entry) plus an optional `default` label. Claude Code and Codex only ever consume the **`default`** member — every other member is skipped with an explicit aggregate projection warning (`models.unreachable`), never silently dropped. Pi registers **every** member regardless of `default`. Switching situations = switching profiles (`acm use daily` / `acm use budget`), which re-points every agent's default at the new profile's default member. There is no runtime auto-dispatch. To give agents different models, project per agent (`acm use <profile> <agent>`). See §3.9.

**❓ `Unresolved environment variables in configuration: ${ANTHROPIC_API_KEY}`**
Export the variable in your shell (or shell profile), or provide a fallback in config (`${VAR:-default}`). Nothing was written — this check fires before any file I/O.

**❓ `Safety Block: external drift detected in [...]`**
A managed field changed outside ACM. See recipe R4. Override only with `--force` after understanding what changed.

**❓ `Safety Block: agent configuration file is corrupted` (ERROR state)**
The target file isn't parseable (bad JSON/TOML, maybe an editor mishap). Fix the syntax by hand, or accept reconstruction via `acm use <profile> --force` — note the warning: corrupted content cannot be preserved; only ACM-managed fields will be rebuilt. Check `~/.acm/state/<agent>/snapshots/` for recoverable earlier versions.

**❓ `Another acm process is holding the write lock`**
Another ACM instance is mid-operation (or crashed while holding the lock — locks don't survive process death, so this usually means genuine contention). Wait and retry; investigate stray processes otherwise.

**❓ `Whitelist violation`**
Should never happen in normal use — it means an internal inconsistency where an operation targeted a non-whitelisted path/file. Please file a bug.

**❓ Pi's `models.json` keeps old providers around**
By design (registry-style incremental registration; §7.3). Delete stale `providers.*` entries manually or `acm rollback pi`.

**❓ Where do my secrets live?**
Not in `config.yaml` if you use `${VAR}` references — they live in your environment. Claude Code necessarily receives the resolved token in `settings.json` (its own design). All ACM output masks sensitive values unless `--show-secrets`; state files are permission-restricted (0600/0700).

**❓ `acm use` said success but the agent behaves differently**
Check that (a) you restarted the agent session — most agents read config at startup; (b) the agent actually reads the file ACM manages (see §7); (c) `acm status` shows SYNCED for that agent.

**❓ Windows support?**
Not yet — the global write lock relies on `fcntl` (POSIX). macOS/Linux today.

**❓ Will upgrading ACM change my configs?**
No. Upgrades affect tool behavior only; neither `config.yaml` nor agent files are touched until you run a write command. Schema stays `version: 2` (older/newer schemas produce a clear error instead of silent migration — a `version: 1` file must be rewritten by hand or regenerated with `acm init --force`).

**❓ Can I keep editing agent configs by hand?**
Yes — for unmanaged fields, always. For managed fields, hand edits create drift (deliberately surfaced, never silently overwritten). Update the SSOT instead and let ACM converge.

---

## Appendix A. Glossary

| Term | Definition |
|---|---|
| **SSOT** | Single Source of Truth — `~/.acm/config.yaml`, the one description of your model world. |
| **Desired State** | Field-level target computed by compiling the active profile through an adapter. |
| **Current State** | Actual on-disk values of managed fields. |
| **Convergence** | Idempotently making Current equal Desired. |
| **Drift** | Current ≠ last-written value (externally modified); blocks writes by default. |
| **Projection Loss** | Desired setting the target agent cannot express; always warned, never silently dropped. |
| **ChangeSet / Ops** | Field-level operations produced by an adapter; the sole input of the Safety Engine. |
| **Managed namespace** | Dot-path prefix an adapter declares ownership over. |
| **Snapshot** | Byte-exact pre-write copy under `state/<agent>/snapshots/`; append-only audit + recovery evidence. |
| **Last-write record** | Per-agent JSON recording what ACM wrote last (fields, profile, backup id). |
| **Journal** | Future append-only transaction log enabling field-level inverse rollback (planned upgrade). |
| **Adapter** | Per-agent pure-function module: detect / config_paths / plan. |
| **VMR** | Virtual Model Router — local model router; optional integration partner. |

## Appendix B. File locations quick reference

| Path | Role |
|---|---|
| `~/.acm/config.yaml` | SSOT configuration (edit me) |
| `~/.acm/state/active` | Currently active profile name |
| `~/.acm/state/<agent>/last_write.json` | Last projection record (drift basis, rollback pointer) |
| `~/.acm/state/<agent>/snapshots/<ts>/` | Pre-write byte-exact backups |
| `~/.acm/state/.lock` | Global write lock |
| `~/.acm/logs/acm.log` | Operation log |
| `~/.claude/settings.json` | Claude Code config (managed fields only) |
| `~/.codex/config.toml` | Codex CLI config (managed fields only) |
| `~/.pi/agent/models.json` + `settings.json` | Pi Agent config (managed fields only; never `models-store.json`) |

## Appendix C. Exit codes quick reference

`0` success/no-op · `1` config error · `2` safety block (drift/lock/whitelist/corrupt-without-force) · `3` I/O failure · `4` not found · `130` interrupted.

## Appendix D. Environment variables quick reference

`ACM_HOME` (default `~/.acm`) · `ACM_VMR_PROBE_URL` (default `http://127.0.0.1:8800`) · `NO_COLOR` · plus the standard credential vars your own config references.

---

*License: Apache-2.0. ACM is distributed on PyPI as [`agent-config-manager`](https://pypi.org/project/agent-config-manager/).*
