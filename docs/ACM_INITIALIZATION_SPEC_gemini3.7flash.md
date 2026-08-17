# ACM (Agent Config Manager) 项目初始化与系统架构规范说明书
<!-- Version: 1.1.0 | Status: Approved Baseline (Python Native Architecture) | Date: 2026-08-17 -->

> **文档性质**：ACM（Agent Config Manager）项目的官方主架构与初始化规范（Single Source of Truth）。  
> **核心定位**：专为 Coding Agent 生态设计的**轻量、无损、聚焦于模型层（Model/Provider）的统一配置管理与版本化快照回滚 CLI 工具**。  
> **技术基底**：基于 **Python 3.10+ / uv** 构建，结合 `ruamel.yaml` 与 `tomlkit` 顶级保真引擎，提供 `uvx` 瞬时免装运行、Homebrew 隔离分发及 Standalone 单二进制支持。  
> **协同生态**：与 VMR（Virtual Model Router）深度协同，作为其前置客户端一键配置入口，同时支持完全脱离 VMR 独立管理全网任意 LLM 供应商。

---

## 目录（Table of Contents）

1. [项目背景与核心摘要 (Executive Summary)](#1-项目背景与核心摘要-executive-summary)
2. [市场现状与现有开源项目深度审计 (Market & Open-Source Audit)](#2-市场现状与现有开源项目深度审计-market--open-source-audit)
3. [第一性原理决策分析：为什么做 (Why Build ACM)](#3-第一性原理决策分析为什么做-why-build-acm)
4. [项目范围定义与正交边界 (Scope & Orthogonal Boundaries)](#4-项目范围定义与正交边界-scope--orthogonal-boundaries)
5. [技术选型与关键架构决策 (Architecture & Tech Stack Decisions)](#5-技术选型与关键架构决策-architecture--tech-stack-decisions)
   - 5.1 语言与运行时选型：Python 3.10+ / uv 生态的第一性原理重估
   - 5.2 适配器实现模式：Code Adapter + Shared Helpers vs 纯 DSL
   - 5.3 动态插件与外部脚本热加载协议 (Dynamic Adapter Hot-Loading)
   - 5.4 现代化多通道分发矩阵 (uvx, brew, pyapp standalone)
6. [ACM 核心规范配置 (Canonical Model Registry)](#6-acm-核心规范配置-canonical-model-registry)
7. [核心系统架构与安全引擎 (System Architecture & Core Engine)](#7-核心系统架构与安全引擎-system-architecture--core-engine)
   - 7.1 无损 AST/CST 补丁引擎 (Lossless Mutation Engine)
   - 7.2 事务性快照与可逆回滚机制 (Snapshot & Journal Engine)
   - 7.3 进程安全守护 (Process Conflict Guard)
8. [主流 Agent 适配层与参数映射矩阵 (Agent Adapters Matrix)](#8-主流-agent-适配层与参数映射矩阵-agent-adapters-matrix)
9. [与 VMR (Virtual Model Router) 的协同联动 (VMR Co-op)](#9-与-vmr-virtual-model-router-的协同联动-vmr-co-op)
10. [CLI 命令与交互规范 (CLI UX & Command Specifications)](#10-cli-命令与交互规范-cli-ux--command-specifications)
11. [项目实施路线图与测试策略 (Roadmap & Testing Strategy)](#11-项目实施路线图与测试策略-roadmap--testing-strategy)

---

## 1. 项目背景与核心摘要 (Executive Summary)

当前 AI 辅助编码领域正经历从“单一 IDE 插件”向“多专业 Agent 协同”的范式转变。开发者日常在终端主力（如 Claude Code, Pi Agent）、复杂任务调度（如 OpenClaw, Hermes）、终端结对编程（如 Aider）与 IDE 环境（如 Cursor, Cline, Roo Code）之间频繁切换。

然而，各大 Agent 的配置体系高度异构、存储路径分散、参数语义各异。更严重的是，当模型底层发生变化（如在官方直连、DeepSeek、OpenRouter、本地 Ollama 以及 VMR 本地虚拟路由之间切换）时，开发者需要重复修改多个深度嵌套且格式不同的配置文件，极易导致语法错误、参数不匹配、甚至破坏 Agent 原生运行时状态。

**ACM（Agent Config Manager）** 旨在彻底解决这一痛点：
- **极简专注**：严格聚焦于**模型与供应商（Model / Provider）**配置层，杜绝范围蔓延；
- **核心标准源**：维护一套独立于具体 Agent 的 ACM Canonical Model Registry（标准模型配置库）；
- **无损投影**：通过精炼的 Python Code Adapter 与 AST 保真引擎（`ruamel.yaml`, `tomlkit`）将标准配置无损“投影”到目标 Agent 配置文件中，严格保护手写注释与未受管字段；
- **Git 级安全**：提供基于快照与事务日志的一键 `diff`、`rollback` 与故障自愈能力；
- **现代无摩擦分发**：支持 `uvx acm` 免装即用、`brew install acm` 隔离分发以及 Release 单二进制。

---

## 2. 市场现状与现有开源项目深度审计 (Market & Open-Source Audit)

| 工具 / 项目 | 技术栈 | 适配 Agent 范围 | 核心工作机制 | 致命缺陷 / 局限性 |
| :--- | :--- | :--- | :--- | :--- |
| **CC-Switch** (`farion1231/cc-switch`) | Tauri / Rust / SQLite | 8 款主流 Agent | SQLite 作为单一源，切换时根据内置模板**全量覆写**目标文件 | **破坏性覆写**：抹杀用户手写的 `enabledPlugins`、`hooks`、自定义 MCP 及所有注释（GitHub Issue #2992）；**范围严重膨胀**：将 MCP、Skills、Prompt 编辑全部捆绑，体量重达数百 MB。 |
| **Claude Code Router** (`musistudio/claude-code-router`) | TypeScript / Node.js | 10 款 Agent | 150K 行庞大本地网关进程，通过 Web UI / 子进程 ENV 注入 | **强绑定自身网关**：配置功能无法脱离其 Node.js 网关独立使用；目标仅限将流量导入 CCR，不支持配置第三方直连。 |
| **ccc** (`guyskk/claude-code-config-switcher`) | Python CLI | 仅 Claude Code (1 款) | 利用 Claude Code CLI 的 `--settings` 启动参数注入临时配置 | **单点局限**：设计巧妙（零触碰磁盘），但完全依赖 Claude Code 特有启动参数，无法迁移至其他 Agent。 |
| **ccp** (`samhvw8/claude-code-profile`) | Go CLI | 仅 Claude Code (1 款) | 利用 `CLAUDE_CONFIG_DIR` 与符号链接（Symlink Hub）切换目录 | **单点局限**：专为 Claude Code Skill 上限设计，不支持多 Agent 深度参数映射。 |
| **claude-swap** (`realiti4/claude-swap`) | Python TUI | 仅 Claude Code (1 款) | 监控 5h/7d 速率限制，轮转 Anthropic 官方 OAuth Token | **单点局限**：仅服务于官方多账号配额轮转，不解决第三方 API / 自定义模型配置。 |
| **手工配置 / Wiki 脚本** | Bash / 人工 | 理论全支持 | 人工编辑 JSON / YAML / TOML | 极易拼错参数（如漏配 `budget_tokens` 导致思考失效，漏配 `context_window` 导致 400 截断），无版本回滚。 |

### 审计结论：市场绝对空白点
当前生态中，**尚无任何一个专注于“模型层状态机”、支持“跨主流 Agent 投影”、具备“AST 级无损增量合并”与“Git 级快照回滚”的独立轻量 CLI 工具**。ACM 具有极高的立项价值与生态位壁垒。

---

## 3. 第一性原理决策分析：为什么做 (Why Build ACM)

### 3.1 决策结论：GO（立项构建独立的 ACM 开源项目）

```
                     ┌────────────────────────────────────────────────────────┐
                     │              Go / No-Go 决策推演框架                    │
                     └────────────────────────────────────────────────────────┘
                                                  │
                 ┌────────────────────────────────┴────────────────────────────────┐
                 ▼                                                                 ▼
   【方案 A：内置于 VMR 主仓 ❌】                                 【方案 B：构建独立开源工具 ACM ✅】
   - 违背 VMR 极简、单二进制与 In-Flight 路由铁律                   - 保持各自关注点纯粹：VMR 关注网络流量，ACM 关注本地文件
   - Agent Schema 频繁漂移会拖累网关核心稳定性                     - 独立服务全生态（直连公有云 / Ollama / VMR）
   - 用户不用 VMR 则无法享受配置管理能力                           - 形成自然协同：ACM 是 VMR 最佳前置上手载体
```

### 3.2 核心价值推演

1. **解决用户真实高频刚痛点**：
   - 开发者不是天天改 MCP 或重写 Prompt，但**每天都在根据任务难度与成本预算切换模型**（白天 Claude 3.7 / o3-mini，夜间 DeepSeek V3 / R1，本地离线 Ollama，开发调试走 VMR 代理）。
   - 手工维护 5+ 个配置文件属于高摩擦的“脏活”。ACM 将此操作压缩至 1 秒以内。

2. **解决“深度参数（Deep Config）”导致的隐蔽运行时崩溃**：
   - 很多开发者误以为换模型只需改 `base_url` + `api_key`。
   - 实际上：**思考预算（Thinking Budget / Reasoning Effort）、上下文窗口（Context Window）、最大输出 Tokens（Max Output）、视觉支持（Vision Flag）、协议方言（Dialect）** 必须联动变更。若不匹配，会导致模型静默截断、CoT 思考丢失或 400 ContextExceeded 崩溃。ACM 将这些参数进行统一抽象与精确转译。

3. **零风险与强安全感**：
   - 任何改动均有原子快照记录。用户可随时 `acm diff` 查看差异，或 `acm rollback` 毫秒级复原，彻底消除改坏配置的恐惧。

4. **与 VMR 的飞轮效应**：
   - ACM 完全独立，普通用户可以直接用来管理直连配置；
   - 当用户本地运行 VMR 时，ACM 提供一键发现与极速对接能力（`acm use-vmr coding --agent all`），彻底抹平 VMR 客户端接入的“最后一公里门槛”。

---

## 4. 项目范围定义与正交边界 (Scope & Orthogonal Boundaries)

ACM 成功的关键在于**克制**。必须严格画定边界，严禁重蹈 CC-Switch 的覆辙：

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                          ACM 受管范围（严格聚焦）                             │
├─────────────────────────────────────────────────────────────────────────────┤
│  ✅ Provider Base URL & Authentication Key / Env Mapping                    │
│  ✅ Model Routing & Model Identifier / Aliases (Primary, Cheap, Weak)       │
│  ✅ Context Window & Max Output Token Limits                                │
│  ✅ Reasoning / Thinking Configuration (Effort Level, Budget Tokens)        │
│  ✅ Protocol Dialect Mapping (OpenAI, Anthropic, OpenAI-Responses)          │
│  ✅ Model Capabilities Flags (Vision Support, Native Tool-Call Dialect)     │
└─────────────────────────────────────────────────────────────────────────────┘
                                      ▲
                                      │ 严格正交隔离（严禁触碰）
                                      ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                        ACM 非管范围（坚决不触碰）                             │
├─────────────────────────────────────────────────────────────────────────────┤
│  ❌ MCP (Model Context Protocol) 服务器配置与环境变量管理                    │
│  ❌ Agent Skills、Plugins、Hooks、Extensions 清单                           │
│  ❌ 用户自定义 System Prompts、Rule 指令集 (如 CLAUDE.md / .cursorrules)   │
│  ❌ Agent 运行时会话状态、OAuth 动态登录 Cache、授权白名单 (Permissions)      │
│  ❌ Agent 自定义本地工具链配置 (Linter, Test Runner, Shell sandbox)         │
└─────────────────────────────────────────────────────────────────────────────┘
```

**正交性原则**：
在向 Agent 配置文件写入模型信息时，ACM **只修改模型相关的专有键值路径**，对同文件内的 `mcpServers`、`permissions`、`plugins` 等非模型键值进行**零修改、原样透传与格式保留**。

---

## 5. 技术选型与关键架构决策 (Architecture & Tech Stack Decisions)

### 5.1 语言与运行时选型：Python 3.10+ / uv 生态的第一性原理重估

通过重新审查业务特征（文件 AST 转换、多适配器开发、保留注释需求），我们确立采用 **Python 3.10+** 作为核心开发语言，并以 **`uv`** 作为核心项目管理工具：

| 评估维度 | 传统认知误区 | 第一性原理实际现状与优势 |
| :--- | :--- | :--- |
| **安装分发门槛** | “Python 需要装环境、容易环境冲突” | **已彻底解决**：现代开发者通过 `uvx acm`（类似 npx）免装即用；通过 `brew install acm`（自动隔离 venv）；通过 `pyapp` 提供各平台单二进制 Release。 |
| **AST 注释保真度** | “Go 的库性能好” | **Python 生态具备压倒性优势**：Python 拥有行业公认顶级保真库 **`ruamel.yaml`**（完美的 Round-trip YAML 注释保留）与 **`tomlkit`**（TOML 注释格式完美保留），远胜于 Go 生态下的边缘情况表现。 |
| **适配器开发速度** | “编译型语言类型严谨” | **极速迭代**：编写/调试一个 Agent 适配器仅需 20~40 行 Python 代码，字典/AST 操作极简直观，极易在 REPL 中交互式调试。 |
| **热插拔与扩展能力** | “需通过子进程 IPC 扩展” | **原生动态模块加载**：利用 Python `importlib`，用户在 `~/.acm/adapters/` 放置 `.py` 脚本即可免编译热加载执行。 |
| **执行性能与启动开销** | “Go 启动快 (<5ms)” | Python 启动耗时约 30~50ms，对于人工手动触发的 CLI 切换命令（如 `acm use vmr`），人眼完全无感。 |

**核心依赖选型**：
- **CLI 交互框架**：`typer` + `rich`（提供精美的终端 UI、Diff 语法高亮与表格展示）；
- **数据结构校验**：`pydantic` v2（严格校验 Canonical Profile 与 Provider 规范）；
- **保真解析库**：`ruamel.yaml`（YAML 保真）、`tomlkit`（TOML 保真）、标准 `json` / `json5`。

---

### 5.2 适配器实现模式：Code Adapter + Shared Helpers vs 纯 DSL

#### 为什么纯 DSL 是不可取的抽象陷阱？
1. **跨文件事务联动**：如 Aider 需同步更新 `.aider.conf.yml`（YAML）与 `.aider.model.metadata.json`（JSON），纯 DSL 无法自然表达跨文件联动。
2. **逻辑分支与互斥处理**：不同 Agent 的参数结构存在嵌套/扁平、环境变量/文件互斥等非线性逻辑，DSL 最终会退化为一套简陋且难调试的伪代码。

#### ACM 的最优架构方案：Code Adapter Pattern with Shared Helpers

```python
# 核心适配器基类接口定义 (acm/adapters/base.py)
from abc import ABC, abstractmethod
from pathlib import Path
from acm.core.schema import CanonicalProfile

class BaseAgentAdapter(ABC):
    agent_id: str
    display_name: str

    @abstractmethod
    def detect_config_paths(self) -> list[Path]:
        """探测并返回目标 Agent 的实际配置文件路径"""
        pass

    @abstractmethod
    def project(self, profile: CanonicalProfile) -> None:
        """将标准 Profile 无损投影并写入目标 Agent 配置文件"""
        pass

    @abstractmethod
    def is_running(self) -> bool:
        """检查目标 Agent 是否正在运行以防写覆盖"""
        pass
```

- **内置适配器**：位于 `acm/adapters/`（如 `claude_code.py`, `openclaw.py`, `pi_agent.py`, `aider.py` 等）；
- **通用 Helper 工具箱**（`acm/utils/`）：
  - `yaml_helper`：封装 `ruamel.yaml` 的节点查找与原地安全更新；
  - `toml_helper`：封装 `tomlkit` 的原地更新；
  - `json_helper`：基于精准路径原地更新 JSON 并保持格式；
  - `atomic_file`：原子写操作（Temp + Rename）。

---

### 5.3 动态插件与外部脚本热加载协议 (Dynamic Adapter Hot-Loading)

为了让用户与社区可以零门槛扩展长尾 Agent，ACM 提供**原生 Python 脚本热插拔**机制：

```
~/.acm/adapters/
  ├── my_custom_agent.py      # 用户自定义的独立适配器脚本
  └── company_internal_bot.py
```

- ACM 启动时自动扫描 `~/.acm/adapters/*.py`，使用 `importlib.util.spec_from_file_location` 动态载入；
- 脚本只要继承 `BaseAgentAdapter` 并实现 `project()`，即可直接无缝参与 `acm use`、`acm diff` 与 `acm rollback`！

---

### 5.4 现代化多通道分发矩阵 (Distribution Matrix)

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                          ACM 多通道极简安装矩阵                             │
├─────────────────────────────────┬───────────────────────────────────────────┤
│  通道 1: uvx (推荐 · 零安装)     │  $ uvx acm use vmr-coding                 │
│  • 无需显式安装，毫秒级缓存执行 │  $ uv tool install acm (一键全局安装)     │
├─────────────────────────────────┼───────────────────────────────────────────┤
│  通道 2: Homebrew (macOS/Linux) │  $ brew tap vmr-project/acm               │
│  • 自动建立私有隔离 venv 环境   │  $ brew install acm                       │
├─────────────────────────────────┼───────────────────────────────────────────┤
│  通道 3: Standalone 单二进制    │  从 GitHub Releases 直接下载单可执行文件  │
│  • 基于 pyapp 封装，零 Python   │  (适用于 Windows / Linux 离线生产环境)    │
├─────────────────────────────────┼───────────────────────────────────────────┤
│  通道 4: pipx / pip             │  $ pipx install acm                       │
└─────────────────────────────────┴───────────────────────────────────────────┘
```

---

## 6. ACM 核心规范配置 (Canonical Model Registry)

ACM 内部维护一套**与 Agent 完全无关的单一天基配置（Canonical Profile SSOT）**，存储于 `~/.acm/config.yaml`。

### 6.1 核心配置 Schema 规范

```yaml
# ~/.acm/config.yaml
version: "1.0"

# 1. 供应商连接池定义 (Providers)
providers:
  anthropic-official:
    protocol: anthropic               # anthropic | openai | openai-responses
    base_url: https://api.anthropic.com
    api_key_env: ANTHROPIC_API_KEY    # 优先从环境变量读取
    # api_key: sk-ant-api03-...       # 或显式配置

  deepseek-direct:
    protocol: openai
    base_url: https://api.deepseek.com/v1
    api_key_env: DEEPSEEK_API_KEY

  vmr-local:
    protocol: openai
    base_url: http://127.0.0.1:8800/v1
    api_key: vmr-local-access-token

# 2. 规范模型画像定义 (Profiles)
profiles:
  # 场景 1: 日常主力（通过 VMR 统一路由）
  vmr-coding:
    provider: vmr-local
    models:
      primary: coding                 # 映射到 VMR 虚拟模型 coding
      cheap: cheap                    # 映射到 VMR 虚拟模型 cheap
    parameters:
      context_window: 131072          # 128k 上下文预算
      max_output_tokens: 8192
      temperature: 0.2
      reasoning:
        enabled: true
        effort: high                  # low | medium | high
        budget_tokens: 16000          # 针对 Claude 3.7 的思考预算
      capabilities:
        vision: true
        tools: native                 # native | xml | none

  # 场景 2: 官方直连模式
  claude-official:
    provider: anthropic-official
    models:
      primary: claude-3-7-sonnet-20250219
    parameters:
      context_window: 200000
      max_output_tokens: 8192
      reasoning:
        enabled: true
        effort: medium
        budget_tokens: 8192
      capabilities:
        vision: true
        tools: native

  # 场景 3: 纯代码重构与推理（DeepSeek 直连）
  deepseek-r1:
    provider: deepseek-direct
    models:
      primary: deepseek-reasoner
    parameters:
      context_window: 65536
      max_output_tokens: 8192
      reasoning:
        enabled: true
        effort: high
      capabilities:
        vision: false
        tools: native

# 3. 当前全局激活 Profile
active_profile: vmr-coding
```

---

## 7. 核心系统架构与安全引擎 (System Architecture & Core Engine)

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                           ACM 系统整体架构图                                │
├─────────────────────────────────────────────────────────────────────────────┤
│ 交互与执行层 (CLI UX Layer · Typer + Rich)                                   │
│ • switch / use  • sync / apply  • rollback  • diff  • doctor  • registry    │
├─────────────────────────────────────────────────────────────────────────────┤
│ 核心引擎层 (Core Engine)                                                     │
│ ┌───────────────────────────┐  ┌──────────────────────────────────────────┐ │
│ │  Canonical Registry SSOT  │  │  Snapshot & Journal Transaction Engine   │ │
│ │  (Pydantic Schema 解析)   │  │  (3-Phase Commit / Git-like Rollback)    │ │
│ └───────────────────────────┘  └──────────────────────────────────────────┘ │
│ ┌───────────────────────────┐  ┌──────────────────────────────────────────┐ │
│ │  Lossless Mutation Engine │  │  Process Conflict & Safety Guard         │ │
│ │  (ruamel.yaml / tomlkit)  │  │  (检测活跃进程 / psutil 冲突阻断)        │ │
│ └───────────────────────────┘  └──────────────────────────────────────────┘ │
├─────────────────────────────────────────────────────────────────────────────┤
│ 适配器层 (Built-in Adapters & Dynamic Hot-Plugin Loader)                     │
│ ┌───────────────┐ ┌───────────────┐ ┌───────────────┐ ┌───────────────────┐ │
│ │ Claude Code   │ │ OpenClaw      │ │ Pi Agent      │ │ Hermes Agent      │ │
│ └───────────────┘ └───────────────┘ └───────────────┘ └───────────────────┘ │
│ ┌───────────────┐ ┌───────────────┐ ┌───────────────┐ ┌───────────────────┐ │
│ │ Aider         │ │ Codex CLI     │ │ Cursor/Cline  │ │ Dynamic Hook .py  │ │
│ └───────────────┘ └───────────────┘ └───────────────┘ └───────────────────┘ │
└─────────────────────────────────────────────────────────────────────────────┘
```

### 7.1 无损 AST/CST 补丁引擎 (Lossless Mutation Engine)
- **YAML**：利用 `ruamel.yaml.YAML(typ='rt')`（Round-Trip 模式），以 CST 语法树方式定位目标属性节点并原地赋新值，**100% 保持用户手写的全量注释、缩进与特定段落排版**；
- **TOML**：利用 `tomlkit.parse()` 解析为保真文档，精准修改目标 Table 字段；
- **JSON / JSONC**：精准更新目标键值，对同文件未涉及的节点完全原样透传。

### 7.2 事务性快照与可逆回滚机制 (Snapshot & Journal Engine)

每次对目标 Agent 进行任何配置变更时，ACM 遵循严格的三阶段提交原则：

```
[阶段 1: Prepare & Snapshot]
  1. 读取目标配置文件当前全量内容
  2. 计算 SHA-256 哈希
  3. 将原始文件保存至 ~/.acm/snapshots/<agent_id>/<timestamp>_<hash>.orig
  4. 写入操作元数据 Journal Entry (包含来源 Profile、时间与操作者)

[阶段 2: In-Memory Mutate & Verify]
  1. 调用对应 Adapter 执行内存保真修改
  2. 校验修改后文件的语法正确性
  3. 断言非模型字段（mcpServers、plugins、permissions）零被篡改

[阶段 3: Atomic Commit]
  1. 将修改后内容写入临时文件: <target_file>.acm_tmp
  2. 执行 os.replace(<tmp>, <target>) 原子替换
  3. 更新事务完成状态
```

**回滚操作（Rollback）**：
- `acm rollback <agent>`：瞬时读取最近一次 Snapshot，执行原子还原并校验哈希；
- `acm diff <agent>`：利用 `rich` 内置的高亮渲染器打印当前磁盘文件与上次快照、或当前 Profile 与基线的精确行级差异（Colored Unified Diff）。

### 7.3 进程安全守护 (Process Conflict Guard)
- 利用 `psutil` 检查当前系统是否存在目标 Agent 活跃进程（如 `claude`、`openclaw`、`cursor`）；
- 若检测到活跃进程，默认阻断并提示：
  `⚠️ Warning: Process 'claude' (PID: 43210) is running. Writing now might be overwritten on exit. Use --force to proceed anyway.`

---

## 8. 主流 Agent 适配层与参数映射矩阵 (Agent Adapters Matrix)

| Agent 目标 | 配置文件位置 | 文件格式 | 注入目标路径与参数映射规范 | 深度参数（Reasoning/Context/Vision）映射方案 |
| :--- | :--- | :--- | :--- | :--- |
| **Claude Code** | `~/.claude.json`<br>`~/.claude/settings.json` | JSON | • `env.ANTHROPIC_BASE_URL` -> `provider.base_url`<br>• `env.ANTHROPIC_AUTH_TOKEN` -> `provider.api_key`<br>• `model` -> `models.primary` | • 将 `reasoning.budget_tokens` 映射至 `thinking.budgetTokens`；<br>• 保护 `mcpServers`、`permissions`、`plugins` 零修改。 |
| **OpenClaw** | `~/.openclaw/openclaw.json`<br>`~/.openclaw/agents/<id>/agent/models.json` | JSON | • `models.providers.<id>.baseUrl`<br>• `models.providers.<id>.apiKey`<br>• `agents.defaults.model.primary` | • 将 `context_window` 映射为 `contextWindow`；<br>• 将 `reasoning.effort` 映射为 OpenClaw 专属思考配置；<br>• 保留 `subagents` 架构。 |
| **Pi Agent** | `~/.pi/agent/config.json`<br>`~/.pi/agent/models.json` | JSON | • `providers` 列表项注册<br>• `active_provider`<br>• `model_overrides` | • 注册兼容 OpenAI / Anthropic 的自定义 Provider；<br>• 映射 Tool Call 模式；保留 Pi Extensions 与 Skills。 |
| **Hermes Agent** | `~/.hermes/config.yaml`<br>`~/.hermes/.env` | YAML | • `model.base_url`<br>• `model.api_key`<br>• `model.name` | • 使用 `ruamel.yaml` 保留所有注释与缩进；<br>• 映射 `temperature`、`max_tokens` 与本地推理格式。 |
| **Aider** | `~/.aider.conf.yml`<br>`~/.aider.model.metadata.json` | YAML + JSON | • `openai-api-base`<br>• `model`<br>• `api-key` | • **跨文件联动**：更新 YAML 的同时，自动向 JSON 元数据文件注入该模型的 `max_input_tokens` 与 `edit_format`。 |
| **Codex CLI** | `~/.codex/config.toml` | TOML | • `[model] provider`<br>• `[model] name` | • 使用 `tomlkit` 精确替换 `[model]` 表，保护 `[sandbox]` 与 `[tools]`。 |
| **Cursor** | `~/Library/Application Support/Cursor/User/settings.json` (macOS) | JSONC | • `cursor.openAI.baseUrl`<br>• `cursor.openAI.apiKey`<br>• `cursor.model` | • 仅增量修改 `cursor.*` 命名空间，完全隔离 VSCode 其它插件与主题配置。 |
| **Cline / Roo Code** | `~/.config/Code/User/globalStorage/saoudrizwan.claude-dev/settings/...` | JSON | • `apiProvider`<br>• `customBaseUrl`<br>• `customModelId` | • 精确定位 VSCode 扩展私有存储路径，增量 Patch。 |

---

## 9. 与 VMR (Virtual Model Router) 的协同联动 (VMR Co-op)

ACM 与 VMR 是**各司其职、天然互补、松耦合协同**的黄金搭档：

```
                               ┌────────────────────────────────┐
                               │            开发者               │
                               └───────────────┬────────────────┘
                                               │
                                 $ acm use-vmr coding --agent all
                                               │
                                               ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                          ACM (Agent Config Manager)                         │
│ • 自动探测本地 VMR 实例 (http://127.0.0.1:8800)                              │
│ • 自动获取 VMR 暴露的虚拟模型列表 (coding, cheap, architect)                 │
│ • 毫秒级生成 vmr-local Profile 并精准投影到 Claude Code, OpenClaw, Pi, Aider │
└──────────────────────────────────────┬──────────────────────────────────────┘
                                       │ 客户端流量对齐
                                       ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                         VMR (Virtual Model Router)                          │
│ • 本地高性能网关（处理透明故障转移、模型虚拟化路由、成本审计与字节级飞行记录）│
└─────────────────────────────────────────────────────────────────────────────┘
```

1. **自动探测机制（Discovery Protocol）**：
   - 执行 `acm vmr detect` 或 `acm use-vmr` 时，ACM 优先探测本地 `http://127.0.0.1:8800/healthz` 及 `~/.vmr/config.yaml`；
   - 自动获取 VMR 当前配置的端口、鉴权 Token 与虚拟模型别名。
2. **一键全量对齐（One-Command Sync）**：
   - `acm use-vmr coding --agent all`：一条命令将本机安装的所有 Agent 配置文件全部切至本地 VMR 网关，并将主模型设为 `coding`；
3. **安全解绑与复原**：
   - `acm rollback all`：一键切回接入 VMR 之前的官方直连状态，零残留，不伤环境。

---

## 10. CLI 命令与交互规范 (CLI UX & Command Specifications)

```bash
# ---------------------------------------------------------
# 1. 初始化与状态查看
# ---------------------------------------------------------
acm init                           # 初始化 ~/.acm 目录与默认 Canonical 配置
acm status                         # 查看当前激活的 Profile 及各个 Agent 的连接状态
acm doctor                         # 诊断各 Agent 配置文件语法、权限及环境冲突

# ---------------------------------------------------------
# 2. Profile 方案管理
# ---------------------------------------------------------
acm profile list                   # 列出所有已定义的 Canonical Profiles
acm profile show <profile>         # 查看指定 Profile 的完整模型参数定义
acm profile create <name>          # 交互式或从模板创建新 Profile

# ---------------------------------------------------------
# 3. 配置应用与切换 (核心高频操作)
# ---------------------------------------------------------
acm use <profile>                  # 切换全局 Profile，并应用至所有已探测到的 Agent
acm use <profile> --agent claude   # 仅将指定 Profile 应用于 Claude Code
acm apply                          # 重新对齐/刷新当前 active_profile 到所有 Agent

# ---------------------------------------------------------
# 4. VMR 专属联动快捷指令
# ---------------------------------------------------------
acm use-vmr [virtual_model]        # 自动探测本地 VMR 并一键对齐所有 Agent (默认 virtual_model: coding)
acm vmr status                     # 查看本地 VMR 运行状态与暴露的虚拟模型列表

# ---------------------------------------------------------
# 5. 安全回滚与差异对比
# ---------------------------------------------------------
acm diff [agent]                   # 查看当前磁盘文件与上次快照的变更 Diff
acm history [agent]                # 查看历史配置快照时间线
acm rollback [agent]               # 回滚到上一版本快照
acm rollback [agent] --to=<hash>   # 回滚到指定历史快照
```

---

## 11. 项目实施路线图与测试策略 (Roadmap & Testing Strategy)

### 11.1 阶段实施计划

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                             ACM 三阶段落地路线图                             │
├─────────────────────────────────────────────────────────────────────────────┤
│ 阶段一：MVP 核心架构构建 (Phase 1)                                            │
│ • 初始化 uv 项目骨架 (pyproject.toml, typer, rich, pydantic, ruamel.yaml)    │
│ • 实现 Snapshot & Journal 事务日志引擎                                       │
│ • 交付 Top-3 核心 Agent 适配器：Claude Code, OpenClaw, Pi Agent              │
│ • 交付基础命令：init, use, status, diff, rollback                           │
├─────────────────────────────────────────────────────────────────────────────┤
│ 阶段二：全生态覆盖与 VMR 联动 (Phase 2)                                      │
│ • 扩充 Agent 适配器：Hermes, Aider, Codex, Cursor, Cline                     │
│ • 深度参数转译：Thinking Budget / Context Window / Vision 精准适配          │
│ • 实现 VMR 自动探测与 acm use-vmr 快捷指令                                 │
│ • 实现 ~/.acm/adapters/*.py 动态模块热加载机制                               │
├─────────────────────────────────────────────────────────────────────────────┤
│ 阶段三：测试沙箱与开源分发 (Phase 3)                                         │
│ • 建立 CI 端到端金样回归测试（Golden File Test Suite）                       │
│ • 配置 GitHub Actions 自动构建 pyapp Standalone 单二进制 Release             │
│ • 构建 Homebrew Tap 分发 Formula                                             │
└─────────────────────────────────────────────────────────────────────────────┘
```

### 11.2 金样回归测试保障策略 (Golden File Testing)
1. **真实样本收集**：收集包含复杂 MCP、手写注释、私有字段的真实 Agent 配置文件；
2. **三步断言闭环**：
   - `Step 1 (Apply)`: 验证目标模型字段精确修改；
   - `Step 2 (Non-destructive)`: 验证 `mcpServers` 等非管字段及手写注释 **100% 原样保留**；
   - `Step 3 (Rollback)`: 验证回滚后文件与初始样本 **SHA-256 字节级完全一致**。

---
<!-- 规范说明书结束 -->
