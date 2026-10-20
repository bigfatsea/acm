# ACM (Agent Config Manager)

**English** | [中文](README.zh.md)

> One declarative file for the models your AI coding agents use — projected onto every agent on your machine, changed field by field, and always reversible.

ACM keeps `~/.acm/config.yaml` as the single source of truth for *which providers and models you use*, and writes just those fields into the config files of Claude Code, Codex CLI, Pi, OpenCode, Hermes Agent, OpenClaw and their family members. Everything else in those files — MCP servers, plugins, skills, hooks, permissions, prompts, comments, key order — is left byte-for-byte as it was.

## Why

- **One place to change a model.** Switch provider or profile once; every installed agent follows.
- **Non-destructive.** ACM owns *fields*, never whole files. Every write is re-parsed and checked: if anything outside the managed fields would change, nothing is written.
- **Every state is recoverable.** Each write is stored in a content-addressed history. `acm restore` returns managed fields to any earlier version (or the whole file with `--file`); restoring is itself undoable.
- **Honest about drift.** If a managed field was changed by hand or by the agent, ACM blocks and shows the difference instead of silently overwriting it.
- **No secrets in config.** Keys are `${VAR}` references; output is masked unless you ask otherwise.
- **Try without committing.** `acm run opencode` starts an agent once with the configured models and writes nothing to its config.

## Install

```bash
uv tool install agent-config-manager     # or: pipx install agent-config-manager
acm --version
```

Requires Python ≥ 3.12 on macOS or Linux.

## Quick start

```bash
export VMR_KEY=sk-...                      # whatever your gateway or provider uses
acm init --vmr http://127.0.0.1:8800       # detect agents + gateway, propose ~/.acm/config.yaml
acm use daily                              # pick the agents to manage, project the proposed profile "daily" (asks first)
acm status                                 # SYNCED / OUT_OF_SYNC / DRIFTED / ERROR / UNMANAGED
acm history                                # what ACM wrote, newest first
acm restore --baseline                     # go back to how the files were before ACM
```

No gateway? Write the config by hand (see [USER_GUIDE](docs/USER_GUIDE.md#configuration)) — any OpenAI-, Anthropic- or Responses-compatible endpoint works.

One-off launch, nothing written to the agent's files:

```bash
acm run claude -m vmr@reasoning            # model by role (`vmr` = the provider init named after the gateway)
acm run pi                                 # with fast/reasoning roles: Pi on acm/auto, thinking level low/medium/high picks the model
VMR_URL=https://vmr.lan VMR_KEY=sk-... acm opencode   # zero-config; `acm <agent>` is shorthand for `acm run`
```

## Supported agents

| Agent | Tier | `acm run` | Verified against the real binary |
|---|---|---|---|
| Claude Code | T1 | yes | yes |
| Codex CLI | T1 | yes | yes |
| Pi | T1 | yes | yes |
| OpenCode | T1 | yes | yes |
| Hermes Agent | T1 | yes | no (golden tests only) |
| OpenClaw | T1 | yes | no (golden tests only) |
| OmO, Prime Agent (Pi family) | T2 | not yet | no |
| MiMo Code, DevEco Code (OpenCode family) | T2 | not yet | no |

T1 agents have their own code path; T2 agents are parameter-only members of a family and are marked experimental until someone confirms them on a real machine.

## Gateway manifest

A gateway can publish `GET /manifest` — models, protocols, roles (`default`, `reasoning`, `fast`, `subagent`, `review`), limits and capabilities — so ACM learns the catalog instead of you copying it. [VMR](https://github.com/bigfatsea/vmr) implements it; any gateway can. Format: [SPEC §4](docs/ACM_SPEC_v3.md).

## Documentation

| Topic | Document |
|---|---|
| Using ACM, config reference, per-agent mapping, troubleshooting | [docs/USER_GUIDE.md](docs/USER_GUIDE.md) ([中文](docs/USER_GUIDE.zh.md)) |
| Principles and boundaries | [docs/ACM_PRINCIPLE_v3.md](docs/ACM_PRINCIPLE_v3.md) (Chinese) |
| Implementation spec | [docs/ACM_SPEC_v3.md](docs/ACM_SPEC_v3.md) (Chinese) |
| Contributing / development | [CLAUDE.md](CLAUDE.md) |

## Development

```bash
uv sync
uv run pytest                  # unit, golden, fault, e2e; real-binary tests skip when the agent is not installed
uv run ruff check . && uv run mypy src
```

## License

Apache-2.0
