<!-- Ver 2026-08-17 21:40, by Claude Sonnet 4.6 -->

# ACM（Agent Config Manager）项目规格说明书

> **文档性质**：项目立项规格文档（Project Spec）。覆盖背景、市场分析、立项决策、Scope 定义、技术选型、架构设计、功能规格与路线图。  
> **地位**：本文档是 ACM 项目的唯一权威设计文档，以此为准。此前两份分析报告（`agent_config_manager_deep_analysis.md`、`agent_config_manager_evaluation_v1.0_custom-2-agent.md`）仅作参考，本文档与其有若干重要分歧，以本文档为准。

---

## 1. 背景与问题陈述

### 1.1 上下文

AI Coding Agent 生态在 2025-2026 年间快速分化。开发者不再只用一个 Agent，重度用户的典型桌面是：

- 终端主力：Claude Code 或 OpenClaw（复杂多步任务）
- IDE 辅助：Cursor、Cline、Roo Code
- 轻量脚本：Aider、Codex CLI
- 国产/低成本替代：Hermes、Pi/Pimini、OpenCode

与此同时，模型供应商（Provider）同样分化：Anthropic 官方、OpenRouter、SiliconFlow、DeepSeek、本地 Ollama、企业自建网关（如 **VRM**）。

**核心矛盾**：每个 Agent 独立维护自己的配置文件，格式各异（JSON、YAML、TOML、VSCode Settings DB），且配置项不完全对称。用户需要在 N 个 Agent 与 M 个 Provider 之间频繁切换，每次都要手工逐一修改配置文件——高摩擦、高出错率、无回滚。

### 1.2 VRM 的特定需求

**VRM（Virtual Model Router）** 是本团队的另一个核心项目，定位：本地透明路由 + 模型聚合网关。VRM 将多个上游 Provider 的模型聚合为统一的虚拟模型（如 `coding`、`agent`、`claude`），暴露单一 OpenAI-compatible 端点。

VRM 面临的"最后一公里"问题：**用户已经把 VRM 跑起来了，但还得逐个手工修改 N 个 Agent 的 `base_url` 和 `api_key`**。这个摩擦点是 VRM 用户上手体验的最大瓶颈。ACM 的核心使命之一就是消除这个瓶颈。

---

## 2. 市场现状（Market Landscape）

### 2.1 现有工具审计

#### CC-Switch（`farion1231/cc-switch`，Tauri/Rust/TypeScript/SQLite）

- **覆盖**：8 款 Agent（Claude Code, Codex, Gemini CLI, OpenClaw, Hermes 等）
- **机制**：SQLite 存储 Profile 模板，切换时将整个模板结构全量写入目标配置文件
- **根本缺陷**：
  1. **全量覆写（Full Overwrite）**：不做增量 Patch，导致用户手工添加的 MCP 配置、`enabledPlugins`、`hooks`、注释全部被清除（GitHub Issue #2992，有大量用户投诉）
  2. **Scope 膨胀**：将 MCP 管理、Skills 同步、System Prompt 编写（CodeMirror 6）、云同步全部打包进一个桌面 GUI，一个"简单的 Provider 切换"变成了数百 MB 的应用
  3. **无 CLI/Headless 支持**：无法集成到脚本、CI 或自动化流程

#### Claude Code Router (CCR)（`musistudio/claude-code-router`，Node.js/TypeScript，~150K 行）

- **机制**：本地 Node.js 网关，通过 Web UI 的 "Apply" 按钮将 Agent 指向自身端口
- **根本缺陷**：配置功能强绑定于庞大的网关运行时，无法脱离使用；仅支持"指向 CCR 自身"，不支持多 Provider Profile 管理

#### claude-code-config-switcher / `ccc`（Python CLI）

- **机制**：利用 Claude Code `--settings` 启动参数注入临时配置，**不修改磁盘文件**——设计巧妙
- **根本局限**：`--settings` 是 Claude Code 专有机制，其他 Agent 无此能力

#### claude-code-profile / `ccp`（Go CLI）

- **机制**：`CLAUDE_CONFIG_DIR` + symlink hub 实现 Profile 隔离
- **根本局限**：仅限 Claude Code，解决的是 Skills 配额问题，不是 Provider 切换

#### claude-swap / `cswap`（Python TUI，1.7k stars）

- **定位**：Anthropic 官方账号池轮转 + 速率监控。不同赛道，不构成竞争

### 2.2 竞品对比矩阵

| 工具 | 跨 Agent | 深度参数建模 | 非破坏性 Patch | 原子回滚 | 独立于网关 | CLI/Headless |
|---|---|---|---|---|---|---|
| CC-Switch | ✅ 8 款 | ❌ 仅 URL+Key | ❌ 全量覆写 | ❌ 脆弱 | ✅ | ❌ |
| CCR | ⚠️ 10 款（强绑定） | ⚠️ 弱 | ⚠️ 部分破坏 | ❌ | ❌ | ⚠️ 有限 |
| ccc | ❌ 仅 Claude Code | ❌ | ✅ 不修改文件 | — | ✅ | ✅ |
| ccp | ❌ 仅 Claude Code | ❌ | ✅ | ⚠️ 目录级 | ✅ | ✅ |
| **ACM（目标）** | **✅ 全生态** | **✅ 完整建模** | **✅ 增量 Patch** | **✅ 事务快照** | **✅** | **✅** |

### 2.3 结构性空白

CC-Switch 是目前最接近目标的竞品，但其"全量覆写"的核心缺陷是**设计哲学层面的问题**，不是实现质量问题——修复它意味着重构整个数据层，CC-Switch 不太可能自我修正。这个空白是真实的、持久的。

---

## 3. 立项决策（Go/No-Go）

**结论：GO。**

### 理由

1. **痛点真实且高频**：多 Agent + 多 Provider 是现实场景，不是边缘用例。每次切换手工改 N 个配置文件是真实的日常摩擦。

2. **现有工具有不可修复的结构缺陷**：CC-Switch 的全量覆写问题是架构选择，不会自我修复；其他工具均只覆盖单一 Agent，不具有泛化性。

3. **VRM 的战略需求**：ACM 是 VRM 的天然配套工具。没有 ACM，VRM 的用户上手体验存在一个无法绕过的手工摩擦点。ACM 解决 VRM 自身解决不了的"最后一公里"问题。

4. **实现成本低、边际价值高**：本质是一个本地文件操作工具，无网络常驻服务，技术复杂度可控。

5. **市场时机窗口存在**：Agent 生态正在分化扩张，工具链尚未固化，现在切入边际成本最低。

---

## 4. Scope 定义

### 4.1 In Scope（管）

| 类别 | 具体内容 |
|---|---|
| **Provider 层** | `base_url`、`api_key`、`protocol`（openai / anthropic）、`org_id`、代理设置 |
| **Model 层** | `model_id`（含别名）、`context_window`、`max_output_tokens`、`temperature` |
| **能力参数** | `reasoning_effort`（low/medium/high）、`thinking_budget_tokens`、`supports_vision`、`tool_call_format`（native/xml/markdown） |
| **Profile 管理** | 多 Profile 定义、版本快照、回滚、diff |
| **VRM 集成** | 自动探测本地 VRM、读取虚拟模型列表、一键应用 |

### 4.2 Out of Scope（不管，严禁触碰）

| 类别 | 原因 |
|---|---|
| **MCP Servers** | 用户手工维护，ACM 无权干涉。CC-Switch 的最大教训就在此。 |
| **Skills / Plugins / Hooks** | 属于 Agent 运行时扩展，与模型选择正交 |
| **System Prompts / CLAUDE.md** | 项目/用户级提示词，与 Provider 切换无关 |
| **运行时状态** | 历史记录、OAuth 会话缓存、权限 allowlist —— Agent 自己写自己读，ACM 不干涉 |
| **账号额度监控** | cswap 的赛道，不重叠 |

### 4.3 边界的技术含义

Scope 边界不只是功能边界，也是技术约束：

- **ACM 只使用增量 Patch（In-place Mutation）**，只修改它声明管理的字段
- **所有其他字段字节级无损保留**，包括格式、缩进、注释、未知字段
- 这条约束是 ACM 区别于 CC-Switch 的根本性差异

---

## 5. 技术选型与设计决策

### 5.1 实现语言：Python（而非 Go）

两份参考报告均推荐 Go。独立评估后，**选择 Python**。

| 维度 | Go | Python | 分析 |
|---|---|---|---|
| **文件格式操作生态** | 尚可（yaml.v3 Node API 较底层） | **极成熟**（ruamel.yaml CST、jsonpatch、tomllib） | Python 在保留注释的 YAML/TOML 操作上有成熟、API 友好的库 |
| **分发便捷性** | 单二进制（优势） | `uv tool install acm`（等效体验） | 目标用户有 Python 环境，差距可忽略 |
| **开发效率** | 较慢 | **快 2-3 倍** | CLI 工具类项目，快速迭代更重要 |
| **性能** | 更快 | 足够 | I/O bound 工具，性能不是瓶颈 |
| **团队栈** | 非默认 | **默认栈（Python 3.12 + uv）** | 降低上下文切换成本 |

**核心论点**：Go 的唯一实质优势是单二进制分发，但 `uv tool install` 提供了等效体验。Python 在文件格式生态（特别是 `ruamel.yaml`，保留 YAML 注释的 CST 解析器）上的优势是实质性的，Go 生态中无同等级别替代品。

### 5.2 实现哲学：代码模块 + 共享库（而非 DSL）

两份参考报告均推荐声明式 YAML DSL + 通用引擎。**不采用这个方案。**

**DSL 方案的根本问题：**

- JSONPath `set/get` 覆盖了 80% 场景，但剩下 20% 是真实存在的边界情况。例如：
  - Aider 的 main/editor/weak model 分别对应不同的配置字段，且需要将同一个 provider 信息写入多处，还需要根据 provider 生成对应格式的 `.aider.model.metadata.json`。这种"条件写入多文件 + 派生逻辑"在 YAML DSL 里很难表达
  - 某些 Agent 的 reasoning 参数需要在多个字段中以不同形式同时写入
- 一旦为处理边界情况开始扩展 DSL 语法，就等于在维护一门自定义语言——维护成本不降反升，调试困难，无 IDE 支持

**采用方案：代码模块 + 共享核心库**

```
acm/
├── core/                   # 共享核心库
│   ├── snapshot.py         # Snapshot & Rollback Engine
│   ├── atomic_write.py     # 原子写入（Write-Temp-Rename）
│   ├── json_patch.py       # JSON 无损增量 Patch（RFC 6902 wrapper）
│   ├── yaml_patch.py       # YAML 无损增量 Patch（ruamel.yaml CST）
│   ├── toml_patch.py       # TOML 无损增量 Patch（tomlkit）
│   └── process_guard.py    # 进程存活检测
├── adapters/               # Per-agent 适配器（每个一个 Python 模块）
│   ├── base.py             # 统一接口定义（抽象基类）
│   ├── claude_code.py
│   ├── openclaw.py
│   ├── aider.py
│   ├── hermes.py
│   ├── cursor.py
│   └── ...（新 Agent：新增一个文件，实现接口即可）
├── profiles/               # Profile 存储（YAML）
│   ├── core.yaml           # 内置 Core Profile（VRM 锚定）
│   └── ...（用户自定义）
└── cli.py                  # CLI 入口（Click / Typer）
```

**关键原则：**
- 每个 Adapter 是普通 Python 模块，implement `AgentAdapter` 抽象基类
- Adapter 内部可调用 `core/` helper，可写任意条件逻辑，不受语法约束
- 统一接口（`apply` / `diff`）由基类强制约束，保证 CLI 层一致性
- Snapshot/Rollback 由框架层统一处理，Adapter 只管"如何写"，不管"如何回滚"
- 新 Agent 接入：写一个 Python 模块（预估 50-150 行），实现接口即可

### 5.3 Core Profile 设计

**Core Profile 的定位：**

ACM 内置一个 `core.yaml` Profile，专门对应 VRM 配置，是 ACM 的"默认锚点"。本质是将 **Profile 作为 SSOT**，各 Agent Adapter 将其 **Projection** 为各自的目标格式。

- `acm apply`（不带参数）默认使用 `core` Profile，应用到所有已检测到的 Agent
- 用户可在此基础上创建派生 Profile（如 `openrouter.yaml`、`deepseek.yaml`）
- Core Profile 中的 `base_url` 和 `api_key` 支持环境变量占位符

**`acm init` 的自动化流程：**
1. 扫描本机已安装的 Agent（`which claude`、`which aider` 等）
2. 探测本地 VRM（`http://127.0.0.1:8800/health`）
3. 如果 VRM 在运行：自动读取其暴露的虚拟模型列表，生成 `core.yaml`
4. 如果 VRM 不在运行：提示用户选择 Provider 或手动输入 endpoint，生成对应 Profile
5. `--dry-run` 模式预览变更，用户确认后执行

---

## 6. 架构设计

### 6.1 整体架构

```
┌──────────────────────────────────────────────────────────────┐
│                         acm CLI                              │
│   init | apply | rollback | diff | status | list-profiles   │
└────────────────────────────┬─────────────────────────────────┘
                             │
┌────────────────────────────▼─────────────────────────────────┐
│                     Profile Registry                         │
│          profiles/core.yaml  |  profiles/*.yaml              │
└────────────────────────────┬─────────────────────────────────┘
                             │  apply(profile)
┌────────────────────────────▼─────────────────────────────────┐
│               Agent Adapter Layer                            │
│   claude_code.py | openclaw.py | aider.py | hermes.py | …   │
│   [实现统一接口: apply(profile) / diff(profile)]              │
└────────────────────────────┬─────────────────────────────────┘
                             │  调用 helper
┌────────────────────────────▼─────────────────────────────────┐
│                    Core Library                              │
│   snapshot.py | atomic_write.py | json_patch.py             │
│   yaml_patch.py | toml_patch.py | process_guard.py          │
└────────────────────────────┬─────────────────────────────────┘
                             │
                    目标 Agent 配置文件（磁盘）
```

### 6.2 核心组件详述

#### Snapshot & Rollback Engine（`core/snapshot.py`）

- **存储位置**：`~/.acm/snapshots/<agent_id>/<timestamp>_<sha256[:8]>.bak`
- **内容**：目标配置文件的完整原始内容（非 diff，简单高效）
- **操作流程（每次 apply 前）**：
  1. 读取目标配置文件当前内容，计算 SHA256
  2. 原子写入快照（Write-Temp-Rename，防止快照自身损坏）
  3. 执行 Adapter 的 `apply` 操作
  4. 如果任意步骤抛出异常：自动从快照恢复，确保零残留
- **回滚**：读取快照，原子覆写目标文件（Adapter 不参与回滚逻辑）
- **保留策略**：每个 Agent 保留最近 20 个快照，FIFO 清理

#### In-place Patch（无损增量写入）

**JSON**（`core/json_patch.py`）：
- 使用 `python-json-patch`（RFC 6902 compliant）精确操作目标字段
- 不使用 `json.dumps` 重序列化，避免破坏字段顺序和格式
- 每个 Adapter 声明 `protected_paths`（如 `$.mcpServers`），引擎自动确保这些路径不被写入

**YAML**（`core/yaml_patch.py`）：
- 使用 `ruamel.yaml`（RoundTrip 模式），保留所有注释、缩进、空行
- 精确定位并修改目标节点，不序列化整个文档

**TOML**（`core/toml_patch.py`）：
- 使用 `tomlkit`（保留注释和格式的 TOML 库）

#### AgentAdapter 接口（`adapters/base.py`）

```python
from abc import ABC, abstractmethod
from dataclasses import dataclass
from pathlib import Path

@dataclass
class Profile:
    name: str
    provider_url: str
    api_key: str
    protocol: str              # "openai" | "anthropic"
    model_id: str
    context_window: int
    max_output_tokens: int
    reasoning_effort: str | None   # "low" | "medium" | "high"
    thinking_budget_tokens: int | None
    supports_vision: bool
    tool_call_format: str      # "native" | "xml" | "markdown"
    temperature: float | None

class AgentAdapter(ABC):
    @property
    @abstractmethod
    def agent_id(self) -> str: ...

    @abstractmethod
    def is_installed(self) -> bool: ...

    @abstractmethod
    def config_paths(self) -> list[Path]:
        """返回此 Adapter 管理的所有配置文件路径（用于 snapshot）"""
        ...

    @abstractmethod
    def apply(self, profile: Profile) -> None:
        """将 profile 写入 Agent 配置。只修改 Provider/Model 相关字段。"""
        ...

    @abstractmethod
    def diff(self, profile: Profile) -> str:
        """返回当前配置与 profile 之间的 unified diff（human-readable）"""
        ...
```

### 6.3 Profile 格式（YAML）

```yaml
# ~/.acm/profiles/core.yaml
# ACM Core Profile — VRM 锚定配置（内置默认）
name: core
description: "Local VRM gateway"

provider:
  base_url: "http://127.0.0.1:8800/v1"
  api_key: "${VRM_API_KEY:-vmr-local}"
  protocol: openai

model:
  primary: "coding"      # VRM 暴露的虚拟模型名
  cheap: "cheap"         # 用于轻量任务（可选，部分 Agent 支持双模型配置）

parameters:
  context_window: 128000
  max_output_tokens: 16384
  supports_vision: true
  tool_call_format: native
  reasoning:
    effort: medium
    budget_tokens: 8192
  temperature: null      # null = 使用 Agent 自身默认值
```

### 6.4 CLI 命令规格

```bash
# 初始化：扫描已安装 Agent + 探测 VRM，生成初始 core.yaml
acm init [--dry-run]

# 应用 Profile（默认：core → all installed agents）
acm apply [--agent <name>] [--profile <name>] [--dry-run]

# 回滚（默认：回滚到上一个快照）
acm rollback [--agent <name>] [--to <snapshot-id>]

# 查看当前配置 vs. 上次 apply 的 diff
acm diff [--agent <name>]

# 显示所有 Agent 的当前配置状态摘要
acm status

# Profile 与快照管理
acm list-profiles
acm list-snapshots [--agent <name>]

# VRM 专用
acm detect-vmr          # 探测本地 VRM，显示暴露的虚拟模型列表

# 全局选项
--dry-run               # 预览变更，不实际写入
--verbose               # 显示详细操作日志
--agent all             # 对所有已安装 Agent 操作
```

---

## 7. Agent 适配矩阵

| Agent | 配置路径 | 格式 | 关键写入字段 | 保护字段（禁止修改） | 优先级 |
|---|---|---|---|---|---|
| **Claude Code** | `~/.claude.json`<br>`~/.claude/settings.json` | JSON | `ANTHROPIC_BASE_URL`（env block）<br>`model`<br>`thinking.budgetTokens` | `mcpServers`<br>`permissions`<br>`projects` | **P0** |
| **OpenClaw** | `~/.openclaw/openclaw.json`<br>`~/.openclaw/agents/*/models.json` | JSON | `models.providers.<n>.baseUrl`<br>`models.providers.<n>.apiKey`<br>`contextWindow` | `agents`（非 model 字段）<br>`tools` | **P0** |
| **Aider** | `~/.aider.conf.yml`<br>`~/.aider.model.metadata.json` | YAML + JSON | `openai-api-base`<br>`model`（含 editor-model）<br>metadata context/thinking 字段 | 用户自定义 prompt 字段 | **P0** |
| **Hermes Agent** | `~/.hermes/config.yaml` | YAML | `model.base_url`<br>`model.api_key`<br>`model.name` | `permissions`<br>`tools` | P1 |
| **Codex CLI** | `~/.codex/config.toml` | TOML | `[model].provider`<br>`[model].name`<br>`[api].base_url` | `[sandbox]`<br>`[tools]` | P1 |
| **Pi / Pimini** | `~/.pi/config.json` | JSON | `provider.endpoint`<br>`provider.apiKey`<br>`model` | — | P1 |
| **Cursor** | `~/Library/Application Support/Cursor/User/settings.json` | JSON（VSCode） | `cursor.openAI.baseUrl`<br>`cursor.openAI.apiKey`<br>`cursor.models` | 所有非 `cursor.*` 字段 | P2 |
| **Cline / Roo Code** | VSCode globalStorage（JSON） | JSON | `apiProvider`<br>`customBaseUrl`<br>`customModelId` | `mcpServers` | P2 |
| **OpenCode** | `~/.config/opencode/config.json` | JSON | `provider`<br>`model` | — | P2 |

> **P0**：Phase 1 必须支持。**P1**：Phase 2。**P2**：Phase 3 或社区贡献。

---

## 8. 路线图

### Phase 1：核心 MVP（目标：2 周）

- `acm` Python package，`uv tool install acm` 可用
- Core Library：snapshot engine + atomic write + json/yaml/toml patch helpers
- CLI：`init`、`apply`、`rollback`、`diff`、`status`，支持 `--dry-run`
- Agent 支持：**Claude Code、OpenClaw、Aider**（P0 三个）
- Core Profile 自动生成（含 VRM 探测）
- Golden test 套件：每个 Adapter 验证注释保留、未知字段零损坏、rollback 字节一致

**MVP 验收标准：**
- `acm init` → `acm apply` 后，三个 Agent 均正确指向 VRM
- `acm rollback` 后，三个 Agent 配置文件与修改前字节级一致
- 不触碰任何 MCP / Skills / Hooks 字段

### Phase 2：生态扩展（目标：+1 周）

- 新增 Adapter：Hermes、Codex、Pi
- `acm detect-vmr` + 虚拟模型自动读取
- 完整的 reasoning_effort → 各 Agent 字段映射矩阵
- `acm list-snapshots` + 指定快照回滚
- Process Guard（写入前检测目标 Agent 进程）

### Phase 3：分发与社区（持续）

- Homebrew Tap 发布（`brew install acm`）
- Cursor、Cline/Roo Code Adapter（P2）
- AI 辅助新 Adapter 生成工作流（输入 Agent 配置文档 → 输出 Adapter 骨架）
- VRM 官方文档集成（`acm init` 作为 VRM Quick Start 的推荐步骤）

---

## 9. 关键风险与开放问题

| 风险 | 概率 | 影响 | 应对 |
|---|---|---|---|
| **Agent 配置格式变更** | 中 | 中 | Golden test 套件 + CI 检测；每个 Adapter 独立更新，互不影响 |
| **VSCode 扩展迁移到 SQLite 存储** | 中 | 高（P2 Agent 受影响） | P1 优先支持纯文本配置文件的 Agent；P2 评估通过 VSCode Settings API 注入 |
| **VRM 未运行时 Core Profile 生成失败** | 低 | 低 | `acm init` 提供 fallback：手动输入 endpoint 或选择预设 Provider |
| **并发写入冲突**（Agent 正在运行时修改文件） | 低 | 中 | Process Guard 警告 + snapshot 兜底；无法完全避免但大幅降低风险 |

### 开放问题（暂不做，待后续决策）

1. **是否支持项目级 Profile？**（`.acm/profile.yaml` 在 repo 级别覆盖全局）—— MVP 阶段只做全局
2. **是否暴露 Python API（非 CLI）？**—— 先稳定 CLI 接口
3. **Profile 云同步？**—— 明确超出 scope；用户可自行 git 管理 `~/.acm/profiles/`

---

## 10. 与参考文档的分歧说明

| 议题 | 参考报告观点 | 本文档决策 | 决策依据 |
|---|---|---|---|
| **语言选型** | Go（单二进制、性能） | **Python** | 文件格式操作生态更成熟；`uv tool install` 解决分发问题；团队默认栈；性能对此场景无关紧要 |
| **实现方式** | 声明式 YAML DSL + 通用引擎 | **代码模块 + 共享库** | DSL 表达能力有天花板；边界情况处理困难；调试性差。代码模块更灵活、可测、易维护 |
| **Scope** | 覆盖 MCP + Skills + Prompt | **仅 Provider + Model** | MCP/Skills 是用户私有配置；CC-Switch 最大教训就是 Scope 膨胀导致覆写破坏 |
| **VRM 定位** | "可选的一种 backend" | **Core Profile 的锚点** | VRM 是首要场景，Core Profile 使 VRM 集成更自然，不是二等公民 |
