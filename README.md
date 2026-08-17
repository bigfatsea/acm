# ACM (Agent Config Manager)

> **The Unified, Non-Destructive Model Configuration & Snapshot Manager for AI Coding Agents.**  
> 专为 Coding Agent 生态设计的轻量、无损、聚焦于模型层（Model/Provider）的统一配置管理与版本化快照回滚 CLI 工具。

---

## 🌟 核心特性 (Key Features)

- 🎯 **聚焦模型层（Strict Model Scope）**：严格管理 Provider Base URL、API Keys、Model Identifiers、Context Window、Thinking Budget、Vision 及 Dialects，**坚决不触碰、不破坏 MCP Servers、Skills 与 Prompts**。
- 🛡️ **无损合并（Lossless AST/CST Mutation）**：基于 `ruamel.yaml`（YAML 注释与排版 100% 保持）、`tomlkit`（TOML 完美保真）与精确 JSON 更新，**彻底根绝配置覆盖损坏**。
- 🔄 **Git 级事务快照与回滚（Transaction & Snapshot）**：每次修改前自动留存 SHA-256 原生快照，支持 `acm diff` 查看行级差异与 `acm rollback` 毫秒级无损还原。
- ⚡ **现代无摩擦分发（Modern Distribution）**：支持 `uvx acm` 免装即用（类似 `npx`）、`brew install acm` 隔离分发以及 Release 单文件二进制。
- 🔌 **Code Adapter + 动态热插拔扩展（Hot-Pluggable Adapters）**：内置主流 Agent 适配器（单适配器仅需 20~40 行 Python），同时支持在 `~/.acm/adapters/` 放置自定义 Python 脚本动态热加载。
- 🤝 **VMR 协同倍增器（VMR Co-op）**：独立管理全网任意 API，亦可一键发现本地 VMR（Virtual Model Router）网关并将全部 Agent 出网流量秒级对齐。

---

## 📖 官方主文档与架构规范

- **系统架构与初始化规范说明书**：请参阅 [`ACM_INITIALIZATION_SPEC.md`](./ACM_INITIALIZATION_SPEC.md)
- **前期调研与第一性原理深度研报**：
  - [`agent_config_manager_deep_analysis.md`](./agent_config_manager_deep_analysis.md)
  - [`agent_config_manager_evaluation_v1.0_custom-2-agent.md`](./agent_config_manager_evaluation_v1.0_custom-2-agent.md)

---

## 🚀 快速上手 (Quick Start)

### 1. 运行与安装

```bash
# 方式 A: 免安装直接运行 (推荐，基于 uvx)
uvx acm status

# 方式 B: 全局安装到系统 PATH
uv tool install acm

# 方式 C: Homebrew 安装 (macOS / Linux)
brew tap vmr-project/acm
brew install acm
```

### 2. 常用操作示例

```bash
# 初始化 ACM 配置目录 (~/.acm)
acm init

# 查看当前状态与探测到的 Agent 配置文件
acm status

# 一键将全局 Profile 切换为 vmr-coding，并同步至所有 Agent
acm use vmr-coding

# 仅更新指定 Agent (如 Claude Code)
acm use deepseek-r1 --agent claude

# 一键探测本地 VMR 并将所有 Agent 出网流量对齐至 VMR
acm use-vmr coding --agent all

# 查看变更 Diff 与一键安全回滚
acm diff claude
acm rollback claude
```

---

## 🗺️ 架构总览 (Architecture Overview)

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                           ACM CLI (Typer + Rich)                            │
├─────────────────────────────────────────────────────────────────────────────┤
│ 核心引擎 (Core Engine)                                                      │
│ • Canonical Model Registry (SSOT: ~/.acm/config.yaml · Pydantic)            │
│ • Transaction Snapshot & Journal Engine (3-Phase Commit)                    │
│ • Lossless AST/CST Mutation Engine (ruamel.yaml / tomlkit / json)           │
│ • Process Safety Guard (psutil 检测活跃进程，防并发覆写)                     │
├─────────────────────────────────────────────────────────────────────────────┤
│ 适配器层 (Built-in Adapters + ~/.acm/adapters/*.py Dynamic Hot-Loader)      │
│ • Claude Code  • OpenClaw  • Pi Agent  • Hermes  • Aider  • Codex  • Cursor │
└─────────────────────────────────────────────────────────────────────────────┘
```

---

## 📄 开源协议 (License)

Apache-2.0 License.
