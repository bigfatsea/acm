# ACM 用户指南

**ACM（Agent Config Manager）完整使用手册** —— 面向 AI Coding Agent 的统一、非破坏性模型配置与投影引擎。

> 🌐 本文档另有 [English / 英文版](USER_GUIDE.md)。
>
> 覆盖 ACM `0.1.x`（MVP）。配套文档：[README](../README.zh.md) · [项目指导原则与核心规格 v2.1](ACM_PROJECT_PRINCIPLE_v2.1.md) · [实现参考规格 v2.1](ACM_PROJECT_SPEC_v2.1.md)

---

## 目录

- [1. 简介](#1-简介)
- [2. 安装](#2-安装)
- [3. 核心概念](#3-核心概念)
- [4. 快速上手](#4-快速上手)
- [5. 配置完全参考（~/.acm/config.yaml）](#5-配置完全参考-acmconfigyaml)
- [6. 命令参考](#6-命令参考)
- [7. Agent 适配器详解](#7-agent-适配器详解)
- [8. VMR 协同](#8-vmr-协同)
- [9. 安全机制详解](#9-安全机制详解)
- [10. 状态目录与内部机制](#10-状态目录与内部机制)
- [11. 常见工作流手册（Recipes）](#11-常见工作流手册recipes)
- [12. 故障排查与 FAQ](#12-故障排查与-faq)
- [附录 A. 术语表](#附录-a-术语表)
- [附录 B. 文件位置速查表](#附录-b-文件位置速查表)
- [附录 C. 退出码速查表](#附录-c-退出码速查表)
- [附录 D. 环境变量速查表](#附录-d-环境变量速查表)

---

## 1. 简介

### 1.1 ACM 是什么？

如果你同时使用多个 AI Coding Agent（Claude Code、Codex CLI、Pi Agent……），你一定体会过这种痛苦：每个 Agent 有自己的配置文件、自己的格式（JSON / TOML / YAML）、自己指定"用哪个模型、连哪个端点"的方式。切换模型或供应商意味着手动编辑多个文件——与此同时 Agent 运行时还在不停地往这些文件里写自己的状态。

**ACM 就是为解决这个问题而生**：你在单一声明式文件（`~/.acm/config.yaml`）里把模型世界描述**一遍**，ACM 用一条命令把它安全地投影到你机器上所有已装的 Coding Agent；改主意时还能精准回滚。

### 1.2 三条公理

ACM 的一切行为都源于三条公理：

| 公理 | 含义 |
|---|---|
| **公理 1 —— SSOT** | 模型世界的描述只有一份，Agent 只是投影目标。 |
| **公理 2 —— 非破坏性** | ACM 只拥有它管理的*字段*，绝不拥有整个文件。其余一切（MCP Servers、插件、Skills、权限、会话状态……）语义级无损保留。 |
| **公理 3 —— 精准可逆** | 回滚粒度是"ACM 受管字段的逆操作"，而非整文件粗暴替换。Agent 在此期间写入的新状态绝不被误伤；物理快照作为灾难恢复兜底。 |

贯穿性原则：**ACM 管理的是字段，不是文件。** 一切 ACM 不知道的事（外部修改、无法表达的字段、并发、崩溃）都必须**显式暴露**——绝不静默处理。

### 1.3 管什么 / 绝不碰什么

**管辖范围内：**

- **L1 —— 连接与凭据**：`base_url`、协议方言、`api_key`（仅存环境变量*引用*）、自定义 headers、proxy。
- **L2 —— 模型规格与行为**：选哪个模型、context window、最大输出 tokens、推理力度/预算、temperature、能力位。
- **Profile**：命名的模型组合（如 `daily`、`cheap`），激活与回滚。

**管辖范围外（坚决不碰）：**

- MCP servers、Tools、Skills、Prompts、权限、hooks、插件。
- 账号轮转 / OAuth token 池 / 额度监控。
- 本地代理 / 请求改写（那是 VMR 的领域）。
- Secret storage（只存 `${ENV}` 引用，不做密钥保管库）。
- 闭源 IDE 私有数据库；没有公开稳定配置通道的内部结构。

### 1.4 为什么"字段所有权"如此重要

Agent 配置文件（比如 `~/.claude/settings.json`）同时被*两个权力实体*支配：你/ACM 希望 `model`、`base_url` 这些字段按你的意图演进，而 Agent 运行时又持续往同一个文件写会话状态、OAuth token 和插件记录。朴素的整文件版本控制会陷入**双向控制权死锁**：恢复旧快照会摧毁 Agent 刚写入的新状态。

ACM 采用 Kubernetes Server-Side Apply 的洞见——*字段级所有权*：

```
┌─ ACM 强力控制区 ──────────────────┬─ 宿主自治保护区 ──────────────────┐
│ model / base_url / api_key / …    │ permissions / hooks / history / … │
│ 100% 确定性写入                   │ 零破坏保留（AST 级保护）           │
│ 幂等收敛                          │ 允许外部自由修改，绝不触碰         │
│ 外部修改 = 漂移 → 阻断            │ 只读快照作为审计证据留存           │
└───────────────────────────────────┴───────────────────────────────────┘
```

### 1.5 当前成熟度

本指南覆盖 **MVP 版本（0.1.x）**。已实现命令：`acm init`、`acm status`、`acm use`、`acm rollback`。内置适配器：**Claude Code**、**Codex CLI**、**Pi Agent**。其余命令（`apply`、`diff`、`doctor`、`history`、`release`、`import vmr`）与适配器（Aider、Gemini CLI、OpenCode……）为规划中的升级项——参见 [§6.6](#66-规划中命令与当前的等价做法) 与 [§7.5](#75-路线图适配器)。

---

## 2. 安装

### 2.1 前置要求

- **Python ≥ 3.12**
- macOS 或 Linux（全局写锁使用 `fcntl`；暂不支持 Windows）
- [`uv`](https://docs.astral.sh/uv/)（推荐）或任意 Python ≥ 3.12 环境

### 2.2 方式 A —— 免安装直接运行（uvx）

```bash
uvx --from agent-config-manager acm status
```

无需安装步骤；`uvx` 会自动拉取包并运行 `acm` CLI。

### 2.3 方式 B —— 全局安装

```bash
uv tool install agent-config-manager
acm --version
```

> **命名说明**：PyPI 分发名为 `agent-config-manager`（短名 `acm` 与著名的 ACM 学会冲突且有抢注风险），但安装后的 CLI 命令名就是 **`acm`**。

### 2.4 验证

```bash
$ acm --version
0.1.2
```

---

## 3. 核心概念

掌握以下八个概念，ACM 的其余一切都顺理成章。

### 3.1 三层配置模型

你的整个模型世界住在一个 YAML 文件里，分三层：

```
providers:    L1 —— 端点与凭据引用          （"API 在哪里"）
    ↓ 被引用
models:       L2 —— 模型规格与行为          （"模型是什么"）
    ↓ 被引用
profiles:     L3 —— 命名的角色组合          （"什么场景用哪个模型"）
```

### 3.2 Desired State vs Current State

- **Desired State（期望状态）**：激活 Profile 经适配器编译后*应当*呈现的字段级目标（纯内存计算）。
- **Current State（当前状态）**：受管字段此刻在磁盘上的实际值。
- 写入命令将 Current **收敛**到 Desired，幂等执行。若已一致则为 **no-op**（退出码 0）。

### 3.3 受管字段 vs 未受管字段

每个适配器声明一份它所管理的 *dot-path namespace 白名单*（如 Claude Code：`model`、`env.ANTHROPIC_BASE_URL`……）。只有这些路径会被写入。文件中的其他一切属于宿主 Agent 并被原样保留——注释、键序、排版在格式能力允许范围内一并保真（见 [§9.6](#96-密钥安全与掩码)）。

### 3.4 漂移（Drift）

**漂移** = 磁盘上的受管字段值 ≠ ACM 最后写入的值（你或 Agent 运行时绕过 ACM 改了它）。检测到漂移时任何写入命令**默认阻断**。不存在自动修复路径：你要么检查后手工调和，要么显式传 `--force` 覆盖。绝不静默收敛。

### 3.5 投影损失告警（Projection Loss）

某些期望设置并非每个 Agent 都能表达（例如 Codex 的 `config.toml` 没有 temperature 槽位）。当目标 Agent 无法表达 Desired State 的某部分时，ACM 在 stderr 上发出 **ProjectionWarning**——该设置被*大声地*跳过，绝不静默丢弃。

### 3.6 凭据引用（Credential References）

`config.yaml` 中密钥只以环境变量引用的形式存储：

- `${VAR}` —— 从环境解析；未设置则硬错误。
- `${VAR:-default}` —— 带默认值兜底。

语法规则：**仅支持整字段替换**——不支持子串插值（`foo-${VAR}-bar` 非法），不支持嵌套。投影时若引用的环境变量缺失，ACM 以退出码 1 中止，且发生在**触碰任何文件之前**。

`config.yaml` 里写明文密钥技术上允许（单用户机器上的合法选择），但强烈推荐 `${VAR}` 引用；某些投影场景下引用形式工作得更好（见 [§7.2](#72-codex-cli)）。

### 3.7 六态状态机

每个 Agent 始终处于恰好一个状态（由 `acm status` 展示）：

| 状态 | 含义 |
|---|---|
| `SYNCED` | 落盘受管字段与激活 Profile 完全一致，无漂移。 |
| `OUT_OF_SYNC` | Profile 在 ACM 侧已变更（或从未投影）——磁盘尚未匹配 Desired State。 |
| `DRIFTED` | 受管字段在上次 ACM 写入后被外部修改。 |
| `ERROR` | 目标配置文件语法损坏或不可读。 |
| `UNMANAGED` | 检测到 Agent，但 ACM 从未写过其配置。 |
| `NOT_DETECTED` | 本机未安装该 Agent。 |

多条件同时成立时的优先级：`ERROR > DRIFTED > OUT_OF_SYNC > SYNCED`。

### 3.8 幂等性

连续执行两次 `acm use daily`：第二次检测到一切已一致，对每个 Agent 报告 `no-op`，退出码 0。可放心重跑、可放心进脚本。

### 3.9 Profile 是角色绑定方案，不是运行期自动分流

Profile 是一套**命名的“角色→模型”绑定表**，而不是运行期规则引擎。例如：

```yaml
profiles:
  daily:
    main: sonnet      # 主模型——必填，每个 profile 都必须有
    cheap: haiku      # 经济模型——可选
    review: o3        # 自定义角色——可选，键名任意
```

关键事实：

- **`main` 是保留项、必填项。** `ProfileConfig` 定义 `main: str` 且无默认值，schema 校验会拒绝没有 `main` 的 profile。这保证了即使最简陋的 Agent 也能消费该 profile。
- **Agent 消费哪些角色由 Agent 的能力决定，不由 profile 决定。** 当前三个适配器（Claude Code、Codex、Pi）都会读取 `profile.main` 作为默认/激活模型。profile 里的 `cheap`/自定义角色目前**不会**投影进任何一个——而是在 stderr 上以投影损失告警（`roles.cheap`、`roles.extra`）明确报告并跳过。绝不静默丢弃。
- **“不同情况用不同模型”靠切换 Profile 实现，不是运行期自动分流。** Agent 不会按任务自动选模型；而是*你*（或脚本）切换激活 Profile：

  ```bash
  acm use daily     # 所有 Agent 现在都用 daily.main
  acm use budget    # 所有 Agent 现在都用 budget.main
  ```

  各 Agent 的配置文件被重写指向新的 main 模型。（对 Pi：`settings.json` 的 `defaultProvider`/`defaultModel` 被更新；旧 provider 按设计保留在 `models.json` 注册表中——见 §7.3。）
- **今天想让不同 Agent 用不同模型**，请按 Agent 分别投影（目前没有全局绑定命令）：

  ```bash
  acm use daily claude_code    # Claude Code ← daily.main
  acm use budget pi            # Pi ← budget.main
  ```

- **将来谁会消费 `cheap` / 自定义角色？** 规划中的多角色适配器（Aider，含 main/weak/editor 槽位）会自动映射它们——`cheap` → weak 槽位，自定义角色 → 对应角色名。在那之前，在 profile 里定义它们没有任何代价：当前适配器只会给出告警，且未来适配器上线时你的 `config.yaml` 无需改动。
- **另有一个独立、正交的机制——profile 下的 `pool:` 键——用于声明可选模型池**，供那些原生支持"在多个已注册模型间选择"的 Agent 使用。与 `cheap`/自定义角色（当前仅告警的单槽位角色绑定）不同，只要目标 Agent 具备注册通道，pool 成员会被真正*注册*进它自己的模型目录。语法见 §5.4，各 Agent 支持情况见 §7.4。

> **💡 `/model` 切换与 ACM 的分工。** 多数 Agent（Claude Code `/model`、Codex `/model`、Pi `/model`……）都支持在会话中交互切换模型。那个可选模型池属于 **Agent 自己的机制**（内置目录、它自己的配置文件、或 Pi 的 `models.json`/extensions）。对没有注册通道的 Agent（Claude Code、Codex），ACM 只投影**默认/激活模型**外加连接层，`/model` 的候选列表完全是 Agent 自己的事。对 Pi 而言，ACM *可以*把整个 `pool:` 注册进 `models.json`，让它们全部出现在 `/model` 里——见 §7.3。

---

## 4. 快速上手

### 4.1 最小工作流

```bash
# 1. 初始化：扫描已装 Agent + 探测本地 VMR，
#    交互确认后生成 ~/.acm/config.yaml
acm init

# 2. 将 "daily" Profile 投影到所有检测到的 Agent
acm use daily

# 3. 查看各 Agent 对齐状态
acm status
```

整个闭环就这三步。下文所有内容都是对它们的展开。

### 4.2 本机跑着 VMR 的场景

如果本地跑着 [VMR](https://github.com/bigfatsea/vmr)（Virtual Model Router），`acm init` 会在 `http://127.0.0.1:8800`（可用 `$ACM_VMR_PROBE_URL` 改）自动探测到它，导入虚拟模型列表并生成开箱即用的提案——通常零手工编辑。

### 4.3 无 VMR（直连）场景

没有 VMR 时，`acm init` 生成带注释的模板（含 Anthropic/OpenAI 直连示例）。编辑 `~/.acm/config.yaml`，填入真实模型 ID，并确保引用的环境变量已导出（见第 5 章）。直连任何 OpenAI-/Anthropic-兼容端点都是一等公民。

### 4.4 验证结果

运行 `acm status` —— 所有检测到的 Agent 应显示 `SYNCED`。也可以直接看文件：

```bash
cat ~/.claude/settings.json     # model + env.ANTHROPIC_BASE_URL + env.ANTHROPIC_AUTH_TOKEN 已更新
cat ~/.codex/config.toml        # model + model_providers 已更新，注释原样保留
cat ~/.pi/agent/models.json     # provider 已注册；settings.json defaultProvider/defaultModel 已设置
```

---

## 5. 配置完全参考 (`~/.acm/config.yaml`)

SSOT 文件的完整 schema。校验非常严格：未知键直接拒绝、交叉引用强制检查、文件损坏会让所有命令快速失败（退出码 1）。

### 5.1 顶层

```yaml
version: 1         # 必须恰好为 1（否则提示升级）
```

至少必须定义一个 `profiles:` 条目。

### 5.2 `providers.<name>` —— L1 连接层

| 字段 | 类型 | 必填 | 约束 |
|---|---|---|---|
| `protocol` | string | ✅ | `openai` \| `anthropic` \| `openai-responses` 三选一 |
| `base_url` | string | ✅ | 必须以 `http://` 或 `https://` 开头 |
| `api_key` | string | ✅ | `${VAR}`、`${VAR:-default}` 或明文（不推荐） |
| `headers` | string 映射 | ❌ | 额外 HTTP 头，如 `{ x-org-id: org-123 }` |
| `proxy` | string | ❌ | 代理 URL |

> ⚠️ `providers.*` 下出现未知多余键属于校验错误。

### 5.3 `models.<name>` —— L2 模型规格层

映射键名（`<name>`）是你本地的别名；`id` 是发给供应商的上游模型标识符。

| 字段 | 类型 | 必填 | 约束 |
|---|---|---|---|
| `provider` | string | ✅ | 必须指向已定义的 provider |
| `id` | string | ✅ | 上游模型 ID（如 `claude-sonnet-4-5`、`gpt-4o`） |
| `context_window` | int | ❌ | > 0 |
| `max_output_tokens` | int | ❌ | > 0 |
| `temperature` | float | ❌ | 0.0 – 2.0 |
| `capabilities` | mapping | ❌ | 见下 |
| `reasoning` | mapping | ❌ | 见下 |

`models.<name>.capabilities`：

| 字段 | 类型 | 默认值 | 取值 |
|---|---|---|---|
| `vision` | bool | `false` | |
| `tools` | string | `"native"` | `native` \| `xml` \| `markdown` |
| `json_mode` | bool | `false` | |

`models.<name>.reasoning`：

| 字段 | 类型 | 约束 |
|---|---|---|
| `effort` | string | `low` \| `medium` \| `high` |
| `budget_tokens` | int | > 0 |

### 5.4 `profiles.<name>` —— L3 角色组合层

| 字段 | 类型 | 必填 | 说明 |
|---|---|---|---|
| `main` | string | ⚠️ | 除非声明了非空 `pool`（见下文），否则必填。单模型 Agent 使用的模型（多角色 Agent 的主角色） |
| `cheap` | string | ❌ | 次要/经济角色；仅被拥有对应槽位的 Agent 消费（否则成为投影损失告警） |
| `pool` | 映射（label → 模型别名） | ❌ | 可选模型池——见下文 |
| *（任意自定义键）* | string | ❌ | 自定义角色槽位（如 `review: o3`）——仅被支持自定义角色的 Agent 消费 |

#### `profiles.<name>.pool` —— 可选模型池

`pool` 子映射用自由文本 `label` 声明一组模型，供能注册"可选模型清单"的 Agent 使用（目前：Pi）。它与 `cheap`/自定义角色相互独立，二者之间不做任何隐式转换。

```yaml
profiles:
  daily:
    main: coding
    pool:
      budget: cheap     # label -> models.* 别名
      longctx: agent
      review: o3        # 可以指向不同的 provider
```

规则：

- `main` 是可选的，**前提是**声明了非空 `pool`（见下文）；两者皆缺的 profile 会被拒绝。
- 声明了 `main` 时，它始终隐式作为池成员（若未显式列出，以 label `main` 自动补入）——保证默认项永远可选。
- **仅池 profile（省略 `main`）是 registration-only**：模型会注册进具备池通道的 Agent（Pi），但该 Agent 的默认模型字段（`defaultProvider`/`defaultModel`/`defaultThinkingLevel`）完全不动、所有权仍在用户手中。ACM 会发一条显式投影警告说明这一点；在没有池通道的 Agent 上（Claude Code、Codex）则无可投影内容，会有专门的告警说明。
- 每个 label 必须非空，且引用的别名必须在 `models:` 下有定义；
- 两个 label 不能指向同一个模型别名（`Duplicate model alias '...' in pool`）；
- 两个不同别名也不能解析到同一个 `(provider, upstream id)` 组合——即便别名不同，若最终发给上游的模型 id 相同，会在 Pi 的 `models[]` 数组里产生无法区分的重复条目（`both resolve to upstream model id '...'`）；
- 空 pool 映射等同于未声明 `pool`；
- 保留 label `main`/`default`/`weak`/`editor` 对具有角色化模型槽位的 Agent（如规划中的 Aider 适配器）有特殊含义；其余 label 是自由显示名，大小写原样保留；
- 在没有池注册通道的 Agent 上（Claude Code、Codex），只有 `main` 会被投影；其余成员合并为一条聚合投影损失告警，绝不静默丢弃。

### 5.5 交叉引用完整性

加载时即校验（先于一切动作）：

- 每个 `models.*.provider` 必须存在于 `providers:` 下；
- 每个 `profiles.*.main` / `.cheap` / 自定义角色值 / pool 成员值必须存在于 `models:` 下;
- 至少定义一个 profile。

### 5.6 完整示例集

**a) VMR 中心型（探测到 VMR 时 `acm init` 自动生成）：**

```yaml
version: 1

providers:
  vmr:
    protocol: openai
    base_url: http://127.0.0.1:8800/v1
    api_key: "${VMR_KEY:-}"   # 本地 VMR 无鉴权可留空

models:
  coding:
    provider: vmr
    id: coding

profiles:
  daily:
    main: coding
```

**b) Anthropic 官方直连：**

```yaml
version: 1

providers:
  anthropic-official:
    protocol: anthropic
    base_url: https://api.anthropic.com
    api_key: "${ANTHROPIC_API_KEY}"

models:
  sonnet:
    provider: anthropic-official
    id: claude-sonnet-4-5
    context_window: 200000
    max_output_tokens: 8192
    temperature: 0.2
    reasoning:
      effort: high

profiles:
  daily:
    main: sonnet
```

**c) 多供应商、多 Profile：**

```yaml
version: 1

providers:
  anthropic-direct:
    protocol: anthropic
    base_url: https://api.anthropic.com
    api_key: "${ANTHROPIC_API_KEY}"

  openai-direct:
    protocol: openai
    base_url: https://api.openai.com/v1
    api_key: "${OPENAI_API_KEY}"

models:
  sonnet:
    provider: anthropic-direct
    id: claude-sonnet-4-5
    context_window: 200000

  haiku:
    provider: anthropic-direct
    id: claude-haiku-4-5

  gpt-4o:
    provider: openai-direct
    id: gpt-4o

profiles:
  daily:
    main: sonnet
    cheap: haiku

  budget:
    main: haiku

  experimental:
    main: gpt-4o
    review: sonnet        # 自定义角色槽位
```

切换方式：`acm use daily`、`acm use budget`、`acm use experimental`。

**d) 第三方 OpenAI 兼容中转：**

```yaml
version: 1

providers:
  relay:
    protocol: openai          # 与中转端点实际说的线协议保持一致
    base_url: https://relay.example.com/v1
    api_key: "${RELAY_KEY}"

models:
  flagship:
    provider: relay
    id: their-flagship-model-name

profiles:
  daily:
    main: flagship
```

### 5.7 常见校验错误对照

| 消息片段 | 原因 | 修复 |
|---|---|---|
| `Unsupported config schema version` | `version ≠ 1` | 改为 `version: 1` |
| `references non-existent provider` | model → provider 引用断裂 | 定义该 provider 或修正名字 |
| `is not defined under models` | profile → model 引用断裂 | 定义该 model 或修正名字 |
| `Configuration must define at least one profile` | 没有 `profiles:` 条目 | 补一个 |
| `base_url must start with http(s)://` | 端点格式错误 | 修正 URL scheme |
| `Invalid credential reference syntax` | 如 `pre-${VAR}-post` | 仅用整字段 `${VAR}` |
| `Extra inputs are not permitted` | 严格表中出现拼写错误的键 | 修正键名 |
| `pool label '...' references non-existent model` | pool 值不在 `[models]` 下 | 定义该模型或修正别名 |
| `Duplicate model alias '...' in pool` | 两个 label 指向同一模型 | 让每个池成员指向不同的模型 |
| `both resolve to upstream model id '...' on provider '...'` | 两个不同别名解析到同一 `(provider, id)` | 改用不同的上游模型，或删掉重复的一个 |
| `Pool label must be non-empty` | pool 表里出现 `"" = "alias"` | 用一个真实的 label |

---

## 6. 命令参考

### 6.0 全局选项

| 选项 | 适用命令 | 效果 |
|---|---|---|
| `--dry-run` | `init`、`use`、`rollback` | 预览操作，不写任何内容 |
| `--force`，`-f` | `init`、`use`、`rollback` | `init`：不提示直接覆盖已有配置 · `use`：越过漂移/损坏安全阻断 · `rollback`：免提示确认归档新建文件 |
| `--verbose`，`-v` | `status`、`use` | 详细日志（同时写入 `~/.acm/logs/acm.log`） |
| `--show-secrets` | `status`、`use` | 明文显示密钥而非掩码（**显式 opt-in**） |
| `--no-color` | 全部 | 关闭彩色输出（同时尊重 `NO_COLOR` 环境变量） |
| `--version`，`-v` | 顶层 | 打印版本并退出 |

> ⚠️ 注意 `-v` 的歧义：在**顶层**（`acm -v`）表示 `--version`；在子命令内（`acm use daily -v`）表示 `--verbose`。

### 6.1 `acm init`

```bash
acm init [--dry-run] [--force] [--no-color]
```

扫描本机已装 Agent、探测本地 VMR、生成 `~/.acm/config.yaml` 提案、校验并在确认后写入。

详细流程：

1. 探测已装 Agent（各适配器规则见 §7：`PATH` 上的知名可执行文件，或其家目录如 `~/.claude`）。
2. 探测 VMR（见 §8.2）。探测到 → 生成导入已发现模型的 VMR 定制提案；未探测到 → 生成带注释的直连模板。
3. 写入前先对提案做校验（语法 + schema）——校验失败以退出码 1 中止。
4. 打印提案。`--dry-run` 到此为止（什么都不写）。
5. 请求确认（默认 Yes）后写入：
   - `~/.acm/config.yaml`（权限 `0600`）
   - `~/.acm/state/`、`~/.acm/logs/`（权限 `0700`）
   - `~/.acm/.gitignore`（忽略 `state/`、`logs/`、`.lock` 及临时文件）

**配置文件已存在时的行为：** 提示 "Overwrite existing configuration?" 且**默认为 Cancel**——交互模式下绝不静默清掉现有 SSOT。确需覆盖请显式加 `--force`。（加 `--dry-run` 时完全跳过该提示，所以已有配置时也可以放心预览。）

典型输出：

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

打印所有检测到的 Agent（或经适配器 ID 指定的单个：`claude_code`、`codex`、`pi`）的对齐状态表：

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

- **State** —— 见 §3.7。
- **Details** 显示语法错误信息（ERROR）以及漂移明细 `expected '…', found '…'`。敏感值默认掩码，除非加 `--show-secrets`。
- 加 `--verbose` 还会列出当前投影告警。
- 若激活 Profile 无法解析（如其 `${VAR}` 未导出），打印黄色 `Notice:` 行，并在无期望 Profile 的状态下评估各 Agent。
- `[agent]` 必须是内置适配器 ID（`claude_code`、`codex`、`pi`）——未知 ID 以退出码 4 结束。`status` 本身绝不修改任何内容，除非配置无法加载，否则退出码为 0。

### 6.3 `acm use`

```bash
acm use <profile> [agent] [--dry-run] [--force] [--show-secrets] [--verbose] [--no-color]
```

**语义：切换 Desired State 并立即收敛。**

执行顺序：

1. 加载并校验 `config.yaml`，结合当前环境解析 `<profile>`。Profile 不存在 ⇒ 退出码 4 并列出所有可用 Profile；`${VAR}` 缺失 ⇒ 硬错误、退出码 1——两种情况都零写盘。
2. 将 `<profile>` 记录为激活态（`~/.acm/state/active`）。¹
3. 对每个检测到的 Agent（或仅指定者）：
   - `ERROR` 态 → **安全阻断**（除非 `--force`，此时以 ACM 受管字段重建文件——损坏内容无法保留）。
   - `DRIFTED` → **安全阻断**，逐字段列出 `expected vs found`（除非 `--force`）。特例：尽管有漂移、但所有字段已等于期望状态时，报告为 no-op 而非阻断。
   - `SYNCED` → 报告 `no-op`，跳过。
   - 其余情况经适配器编译操作并交由 Safety Engine 执行（§9.1）。
4. 投影损失告警聚合后输出到 stderr。
5. 退出码取全程最高严重级别（0 正常 / 2 阻断 / 3 I/O 错误）。

¹ *值得了解的细节：* 激活 Profile 在逐 Agent 投影之前就已记录。若某 Agent 随后被阻断，`status` 将显示新 Profile 为激活态而该 Agent 处于 `DRIFTED`/`ERROR`——意图已被记住，只是那个 Agent 尚未收敛。

**Agent 选择语义：** `[agent]` 必须是内置适配器 ID（`claude_code`、`codex`、`pi`）：
- 未知 ID ⇒ 退出码 4。
- 指定的 Agent 存在但**本机未检测到安装** ⇒ 报错，退出码 4。
- 批量模式（不传 `[agent]`）下，未检测到的 Agent 被静默跳过——只投影检测到的。

**批处理语义：** 各 Agent 独立处理。某个 Agent 被阻断不会撤销其他 Agent 已成功的投影；失败者在 stderr 上被点名，最终退出码非零。

注意 `--dry-run` 连第 2 步也会跳过——包括激活 Profile 记录在内，什么都不会写。

`--dry-run` 按 Agent 打印计划操作，形如：

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

**语义：把每个目标 Agent 的配置恢复到 ACM 最后一次写入之前捕获的状态**（基于快照的还原——MVP 的回滚机制；基于 Journal 的字段级精准回滚将在后续里程碑到来）。

对每个 Agent：

1. 确定还原目标：`last_write.json` 记录的 `backup_id`；缺失则兜底取最新快照（附警告）。
2. **先打新快照** —— 回滚本身也可撤销（undo-undo 链）。
3. 用原子替换恢复快照中捕获的文件。
4. ACM 写入前**不存在**的文件（以 `.not_exist_*` 哨兵标记）不做删除而是归档——重命名为原位置旁的 `<file>.acm_orphaned.<snapshot-id>`。
5. 依据还原后的磁盘状态重建 `last_write.json`。

**归档新建文件的确认：** 若存在将被归档的现存文件（即 ACM 投影时创建的），交互会话会请求确认；**非交互（管道/脚本）运行则直接以安全阻断错误中止，除非传入 `--force`。**

无快照历史（该 Agent 从未投影）→ 相应提示；若显式指定了 `[agent]` 参数则为退出码 4。

### 6.5 退出码

ACM 为脚本化而生——退出码就是 API：

| 码 | 含义 | 典型成因 |
|---|---|---|
| `0` | 成功（含幂等 no-op） | |
| `1` | 配置错误 | YAML 语法/schema 错误；`${VAR}` 未解析；无配置（提示 `run acm init first`）；用法错误 |
| `2` | 安全阻断 | 外部漂移；损坏配置未加 `--force`；写锁竞争；白名单违规 |
| `3` | I/O / 权限失败 | 投影/init 过程中的磁盘错误 |
| `4` | 资源未找到 | 未知的 agent ID；Agent 未安装；指定 Agent 无快照 |
| `130` | 中断 | SIGINT（Ctrl-C） |

正常输出走 stdout；错误与警告走 stderr。

### 6.6 规划中命令（与当前的等价做法）

治理规格中的若干命令将在后续里程碑交付。在此之前：

| 规划命令 | 用途 | 今天可以怎么做 |
|---|---|---|
| `acm apply` | 不改变激活 Profile 的前提下收敛 | `acm use <当前激活Profile>` 即可实现同样的收敛 |
| `acm diff <agent>` | 当前 vs 期望/快照的差异展示 | 看 `acm status` 的漂移明细；手动对比 `~/.acm/state/<agent>/snapshots/<最新>/` |
| `acm doctor` | 全面诊断 | `acm status --verbose` + 查看 `~/.acm/logs/acm.log` |
| `acm history` | 事务日志 | 浏览 `~/.acm/state/<agent>/last_write.json` 与 `snapshots/`（时间戳命名目录） |
| `acm release` | 解除托管并恢复接管前旧值 | 先 `acm rollback <agent>`（恢复投影前快照）；或干脆直接卸载 ACM——文件保持最后生效状态继续可用 |
| `acm import vmr` | 增量合并新的 VMR 模型 | 重跑 `acm init --force`（重新生成 SSOT），或手编 `config.yaml` |

---

## 7. Agent 适配器详解

### 7.0 适配器如何工作

每个 Agent 由一个内置 Python 模块支撑，实现极小的纯函数契约：

- `detect()` —— Agent 是否已安装？
- `config_paths()` —— ACM 可能触碰的封闭文件白名单；
- `managed_namespaces()` —— 文件内的 dot-path 白名单；
- `plan(profile)` —— 把解析后的 Profile 编译成字段级期望操作 + 投影告警。**适配器绝不碰磁盘**，所有写入都经由 Safety Engine。

所有适配器以源码内置交付并配金样 fixture 测试门禁——无动态代码加载，无供应链意外。CLI 参数用的适配器 ID：`claude_code`、`codex`、`pi`。

每个适配器的探测规则（"该 Agent 是否已安装？"）：只要其 CLI 可执行文件出现在 `PATH` 上（**`claude`** / **`codex`** / **`pi`**），**或者**其家目录存在（分别为 `~/.claude` / `~/.codex` / `~/.pi/agent`），即报告为*已检测到*。

### 7.1 Claude Code

- **受管文件**：`~/.claude/settings.json`（JSON）。绝不触碰 `~/.claude.json` 运行时状态。
- **受管 namespace**：`model`、`env.ANTHROPIC_BASE_URL`、`env.ANTHROPIC_AUTH_TOKEN`、`env.ANTHROPIC_API_KEY`、`effortLevel`。

投影映射：

| 你的配置 | 写入 `settings.json` |
|---|---|
| `profiles.<p>.main` → `models[m].id` | `model` |
| provider `base_url` | `env.ANTHROPIC_BASE_URL` |
| provider `api_key`（解析后的值） | `env.ANTHROPIC_AUTH_TOKEN` |
| `reasoning.effort` | `effortLevel` |

注意事项：

- Claude Code 说的是 Anthropic Messages 协议。若所选 provider 的 protocol 不是 `anthropic`，ACM 照常投影但会发告警提醒：该端点必须 Anthropic 兼容（或经 VMR 代理）。
- 由于 Claude Code 运行时要消费真实 token，**解析后的凭据值**会写进 `settings.json` 的 env 块（这是 Claude Code 自身设计使然——它不支持在那里做 `${VAR}` 间接引用）。
- 投影损失（告警）：`budget_tokens`、`context_window`、`temperature`、`capabilities`、自定义 headers/proxy、`cheap`/自定义角色。

`acm use daily` 后的结果示例：

```json
{
  "model": "claude-sonnet-4-5",
  "env": {
    "ANTHROPIC_BASE_URL": "https://api.anthropic.com",
    "ANTHROPIC_AUTH_TOKEN": "sk-ant-…"
  },
  "effortLevel": "high",
  "permissions": { "...你自己的设置原封不动...": true }
}
```

### 7.2 Codex CLI

- **受管文件**：`~/.codex/config.toml`（TOML，round-trip 编辑——你的注释，包括注释掉的 `mcp_servers`，都会保真保留）。
- **受管 namespace**：`model`、`model_provider`、`model_reasoning_effort`、`model_providers`。
- ℹ️ 早期项目文档描述过含 `~/.codex/auth.json` 的双文件事务设计；**当前实现仅管理 `config.toml`**，绝不触碰 `auth.json`。

投影映射：

| 你的配置 | 写入 `config.toml` |
|---|---|
| `models[m].id` | `model` |
| provider 名 | `model_provider` |
| `reasoning.effort` | `model_reasoning_effort` |
| provider `base_url` | `model_providers.<name>.base_url` |
| protocol `openai`/`openai-responses` → `responses`；`anthropic` → `chat`（+告警） | `model_providers.<name>.wire_api` |
| 从 `${VAR}` 提取的环境变量名 | `model_providers.<name>.env_key` |

注意事项：

- Codex 自己从环境变量读 API key（`env_key`）。因此 **`api_key` 应当写成 `${VAR}` 引用**——ACM 只把变量*名*写进 `env_key`。若你配的是明文 key，ACM 回退为 `env_key = "OPENAI_API_KEY"` 并告警提醒你导出它。
- `anthropic` 协议的 provider 会触发方言告警（Codex 原生说 OpenAI 线协议；Anthropic 模型请走兼容端点或 VMR）。
- 投影损失（告警）：`budget_tokens`、`context_window`、`temperature`、`capabilities`、headers/proxy、`cheap`/自定义角色。

结果示例：

```toml
model = "gpt-4o"
model_provider = "openai-direct"
model_reasoning_effort = "high"

[model_providers.openai-direct]
name = "openai-direct"
base_url = "https://api.openai.com/v1"
wire_api = "responses"
env_key = "OPENAI_API_KEY"

# 你注释掉的 mcp_servers 以及其余一切原样保留
```

### 7.3 Pi Agent

- **受管文件**：`~/.pi/agent/models.json` + `~/.pi/agent/settings.json`。**绝不触碰 `models-store.json`**（Pi 的内部存储），也不碰 `extensions/`、`skills/`、`sessions/`。
- **受管 namespace**：`providers`、`defaultProvider`、`defaultModel`、`defaultThinkingLevel`。

**Pi 注册 provider 的两套并存通道（官方均支持，且为*叠加*关系——不是互斥）：**

| 通道 | 机制 | 适用场景 | ACM 的角色 |
|---|---|---|---|
| `~/.pi/agent/models.json` | 声明式 provider+模型条目；Pi 每次打开 `/model` 都会重新加载 | 静态端点/代理，OpenAI/Anthropic 兼容 API | **ACM 写这里**（`providers.<name>` 条目） |
| `extensions/*.ts` + `pi.registerProvider(...)` | 启动时编程式注册；支持自定义 API、OAuth 流、动态 `refreshModels` | 自定义端点、代理、团队级配置、自定义认证 | ACM 绝不触碰 `extensions/` |

按官方文档，extension 注册的 provider 是组合底座，**`models.json` 的覆盖仍在其之上生效**——两通道的模型会一起出现在 `/model` 选择器中。

投影映射：

| 你的配置 | 写入位置 |
|---|---|
| provider → 完整条目 `{ baseUrl, api, apiKey, models: [{id, contextWindow?, maxTokens?}] }` | `models.json` 的 `providers.<name>` |
| `models[m].context_window` / `max_output_tokens` | 模型条目内的 `contextWindow` / `maxTokens` |
| protocol：`anthropic`→`anthropic-messages`；`openai-responses`→`openai-responses`；`openai`→`openai-completions` | `api` 字段 |
| provider 名 / 模型 id | `settings.json` 的 `defaultProvider` / `defaultModel` |
| `reasoning.effort` | `settings.json` 的 `defaultThinkingLevel` |

`models.json` 中的凭据处理：若你的 `api_key` 是 `${VAR}` 引用且 `VAR` 已导出，ACM 写入 Pi 风格的 `"$VAR"`，由 Pi 运行时展开；否则写入解析后的值（无钥 provider 则写 `dummy` + 告警）。

**注册式增量投影（重要）：** Pi 会在 Profile 切换间累积 provider——从 Profile A（provider X）切到 Profile B（provider Y）时，X 仍保留在 `models.json` 中，因为历史会话可能还引用它。后果：

- 旧 provider 不会造成破坏，只是留存；
- 要清理，可手动删除不再使用的 `providers.<name>` 条目，或运行 `acm rollback` 恢复投影前快照。

投影损失（告警）：`budget_tokens`、`temperature`、`capabilities.tools`（非 native 方言）/ `capabilities.json_mode`、`proxy`、未被 `pool` 覆盖的 `cheap`/自定义角色（见下文）。与 Claude Code/Codex 不同，Pi **能**消费 `context_window`、`max_output_tokens`，也**能**消费 provider 级 `headers`（会写进 `providers.<name>.headers`，Pi 官方文档确认支持该字段），还**能**消费 `capabilities.vision`（写进模型条目的 `input: ["text", "image"]` 字段）。Pi 本可通过 openai 系方言下的模型级 `samplingParams` 表达每模型 temperature，但 ACM 尚未投影——因此声明了 temperature 仍会告警，且告警文案如实说明这一点。Pi 没有独立的 `proxy` 概念，因此这一项仍是真实投影损失。

**通过 `pool` 原生支持多模型 `/model`（推荐）：** Pi 是当前唯一具备真实注册通道的适配器，因此在 profile 下声明 `pool`（见 §5.4）会让 ACM 把*全部*池成员注册进 `models.json`，而不只是 `main`：

```yaml
profiles:
  daily:
    main: coding
    pool:
      budget: cheap
      longctx: agent
      review: o3          # 可以在另一个 provider 上
```

- 成员按 provider 分组；每个 provider 生成一条 `providers.<name>` 条目，其 `models[]` 数组承载整组成员。`main` 始终包含在内；
- pool 的 `label` 会成为每个模型的 `name` 字段——**订正**：Pi 官方文档明确 `/model`、`--list-models` 与交互式 footer **按 `id` 展示条目**，`name` 只用于 `--model` 模式匹配和**次要详情文本**，并不是选择器里的主显示名；
- `id` 始终是发给上游 API 的真实模型标识，label 只影响次要详情文本，不影响选择器主展示；
- `settings.json` 的 `defaultProvider`/`defaultModel`/`defaultThinkingLevel` 仍然只由 `main` 决定，与池的其余部分无关；
- 池内非 main 成员的 `reasoning` 不投影，声明会产生各自告警；`capabilities.vision` **会**被投影进模型条目的 `input` 字段；`temperature` 与确实无通道的能力子字段（`tools` 非 native 方言 / `json_mode`）各自单独告警——temperature 的告警会注明 Pi 本可经模型级 `samplingParams`（openai 系方言）表达，只是 ACM 尚未写入；provider 级 `headers` 无论是否 main 都会正常投影进 `providers.<name>.headers`；`proxy` 是 Pi 没有的概念，仅被非 main 池成员使用的 provider 若配了 `proxy` 会产生告警（不会静默丢失）；
- `acm use`/`status`/`rollback` 对待多模型的 `providers.<name>` payload 与单模型完全一样——同一个 op、同一套白名单、同一套漂移/回滚语义。

**不声明 `pool`——手写 `models.json` 或 extension：** 若不声明 pool，ACM 的 Pi 投影仍然在每个 provider 条目中只写**一个模型**（`models: [main]`）并设置 `defaultModel`；`/model` 选择器仍会显示 provider 暴露的其余模型——来自内置目录、手写的 `models.json` 条目、以及 extension。想要把 ACM 的默认值与手工维护的模型池组合起来：

1. 让 ACM 拥有默认值：`acm use <profile> pi`（写 `defaultProvider`/`defaultModel`）。
2. 模型池另行提供——手写 `models.json` 或 extension（`pi.registerProvider(...)`）二选一。ACM 绝不触碰 `extensions/`，也绝不删除它没写过的额外条目。
3. ⚠️ 命名：ACM 每次投影会**覆盖同名**的 `providers.<name>` 条目，所以请给 ACM 的 provider 与你手写的 provider/extension 取**不同的名字**（例如 ACM 用 `vmr`、extension 用 `vmr_openai`），避免互相覆盖。

### 7.4 能力矩阵（哪些会被投影、哪些告警）

| 期望设置 | Claude Code | Codex CLI | Pi |
|---|---|---|---|
| 模型 id（`main`） | ✅ `model` | ✅ `model` | ✅ `defaultModel` + 注册表 |
| base_url | ✅ `env.ANTHROPIC_BASE_URL` | ✅ `model_providers.*.base_url` | ✅ `baseUrl` |
| api_key | ✅ 解析值 → `env.ANTHROPIC_AUTH_TOKEN` | ✅ 环境变量*名* → `env_key` | ✅ `$VAR` 或解析值 → `apiKey` |
| `reasoning.effort` | ✅ `effortLevel` | ✅ `model_reasoning_effort` | ✅ `defaultThinkingLevel` |
| `reasoning.budget_tokens` | ⚠️ 告警 | ⚠️ 告警 | ⚠️ 告警 |
| `context_window` | ⚠️ 告警 | ⚠️ 告警 | ✅ `contextWindow` |
| `max_output_tokens` | ⚠️ 告警 | ⚠️ 告警 | ✅ `maxTokens` |
| `temperature` | ⚠️ 告警 | ⚠️ 告警 | ⚠️ 告警（Pi 本可经 openai 方言下的模型级 `samplingParams` 表达，ACM 尚未投影） |
| `capabilities.vision` | ⚠️ 告警 | ⚠️ 告警 | ✅ 模型条目 `input: ["text", "image"]` |
| `capabilities.tools` / `.json_mode` | ⚠️ 告警 | ⚠️ 告警 | ⚠️ 告警（Pi 无通道） |
| provider `headers` | ⚠️ 告警 | ⚠️ 告警 | ✅ `providers.<name>.headers` |
| provider `proxy` | ⚠️ 告警 | ⚠️ 告警 | ⚠️ 告警（Pi 无此概念） |
| 模型池（`profiles.*.pool`） | ⚠️ 聚合告警，仅 main 生效 | ⚠️ 聚合告警，仅 main 生效 | ✅ 全员注册进 `models.json`，label→`name`（次要详情文本，选择器主展示为 `id`） |
| `cheap` 角色 | ⚠️ 告警 | ⚠️ 告警 | ⚠️ 告警 |
| 自定义角色 | ⚠️ 告警 | ⚠️ 告警 | ⚠️ 告警 |

✅ = 会投影 · ⚠️ 告警 = 跳过并在 stderr 上给出明确的投影损失告警。

### 7.5 路线图适配器

- **P1**：Aider（`~/.aider.conf.yml` + 模型元数据 JSON；角色模型 main/weak/editor）、Gemini CLI、OpenCode（JSONC 注释保留）。
- **P2（社区贡献）**：OpenClaw、Hermes、Cursor/Cline（仅公开 settings 通道）。

---

## 8. VMR 协同

### 8.1 VMR 是什么？

VMR（Virtual Model Router）是配套的本地路由器，通过一个 OpenAI 风格端点暴露多个上游模型。ACM 与它的集成是**一等公民级的便利功能，而非架构依赖**——没有 VMR 一切照常工作。

### 8.2 探测序列（`acm init`）

1. `GET $ACM_VMR_PROBE_URL/v1/models`（默认主机 `http://127.0.0.1:8800`）——主证据+数据源；发现的模型 ID（及可选 `vmr_protocol` 提示）变成 `models:` 下的条目。若有凭据可用（见下方"鉴权"）会随请求携带。返回 `401`/`403` 本身就是"VMR 在线但要求鉴权"的证据，会被立即显式上报，绝不静默吞掉。
2. `GET $ACM_VMR_PROBE_URL/health`（无鉴权存活检查——VMR `/healthz` 的替代者；`/healthz` 已从 VMR 路由表永久移除）——仅在步骤 1 因 401/403 *以外* 的原因失败时才会执行。返回 `200` 说明 VMR 存活但 `/v1/models` 本身不可达，此时会生成带占位模型的提案。

探测容错且快速超时；没有 VMR 的机器（两步都失败）直接进入直连模板流程。

#### 鉴权

若 VMR 配置了 `api_keys:`，`/v1/models` 需要凭据。设置 `VMR_KEY` 即可——生成提案的 `providers.vmr.api_key` 引用的正是 `${VMR_KEY:-}`，同一个变量同时覆盖探测和后续 `acm use` 投影。

没有有效凭据时，`acm init` 会在 stderr 打印明确警告("VMR detected ... but requires authentication")——而不是误导性的"VMR not running"——并降级为直连模板以确保命令仍然完整跑完（`exit 0`）。凭据只会进入请求头，绝不出现在 ACM 的任何输出中。

### 8.3 生成的提案

探测到 VMR 后，`acm init` 产出：一个指向 `<host>/v1` 的 `providers.vmr` 条目、每个发现模型在 `models:` 下一个条目（键名即模型自身 id，原样保留，不做任何净化改名），以及一个 `profiles.daily` profile——其 `main` 优先取名为 `coding` 的模型，否则取第一个发现的模型。`base_url` 由 ACM 探测时使用的主机拼接 `/v1` 得到——与 VMR 自身 `/status.instance.base_urls` 对同一主机的回显语义等价，只是独立推导而非经该端点回传。

### 8.4 跟上 VMR 的变化

VMR 模型列表后续发生变化时，可手编 `~/.acm/config.yaml`（增删 `models:` 下条目），或重跑 `acm init --force` 重新生成。（专用的增量 `acm import vmr` 属于触发式升级规划。）

---

## 9. 安全机制详解

理解本章，是你放心让 ACM 经手 Agent 配置的前提。

### 9.1 六步写入流水线

无论哪条命令，每次物理写入都要经过唯一入口（Safety Engine），依次执行：

1. **白名单校验** —— 每个操作的目标文件必须在适配器声明的路径集合内，dot-path 必须落在声明 namespace 内。越界即 `SafetyBlockedError`（退出码 2）。ACM 物理上不可能写到别处。
2. **写前快照 + 操作扩展** —— 所有受影响文件的完整字节副本进入 append-only 快照目录（不存在的文件打 `.not_exist_*` 哨兵标记）。所有将被触碰字段的旧值被捕获。
3. **内存修改 + 语法自检 + AST 断言** —— 新内容在内存中生成；先解析证明语法合法；再对*修改前后*的解析树做 diff，断言**零个未受管路径发生变化**。任何意外变动都会中止写入。
4. **提交前指纹校验** —— 重新计算每个目标文件的 SHA-256 并与快照前哈希比对。事务中途若有并发方改动文件 ⇒ 中止，零提交。
5. **原子替换** —— 内容写入临时文件（`*.acm_tmp`，权限 `0600`）后逐文件以 `os.replace` 原子换入。永远不会出现"写一半"的状态。
6. **落账** —— 更新 `last_write.json`（profile、时间戳、backup id、受管字段值、新建文件）。它是漂移检测与回滚的数据基础。

多文件 Agent（Pi 管理两个文件）在同一把锁内顺序提交；快照链保证恢复的确定性。

### 9.2 白名单强制

两层：文件边界（适配器声明的绝对路径，resolve 后比对）与 namespace 边界（dot-path 前缀，如 `env.` 下仅特定键）。这就是为什么 ACM 即使有 bug 也*永远*不可能抹掉你的 MCP servers——那些路径根本不可写。

### 9.3 快照体系

- 位置：`~/.acm/state/<agent>/snapshots/<时间戳ID>/`（UTC、字典序可排序 ID）。
- Append-only：绝不自动清理。Agent 配置通常只有几 KB，增长有限。
- 同时充当只读审计证据（"ACM 动它之前这文件长什么样？"）。

### 9.4 并发控制

全局非阻塞排他文件锁（`~/.acm/state/.lock` 上的 `fcntl.flock`）串行化所有变更类命令。第二个并发 `acm` 进程立即失败：

```
⚠️ Another acm process is holding the write lock. Operation aborted.   （退出码 2）
```

崩溃残留的孤儿临时文件会在下次写入开始时自动清扫。

### 9.5 漂移检测与阻断

每次 `status`/`use` 都会把每个受管字段的磁盘值与最后写入记录比对。不一致 ⇒ `DRIFTED`，写入被阻断并给出逐字段 `expected vs found` 报告。你的选择：

1. 检查（`acm status`、与最新快照对比），判断谁对谁错；
2. 手工调和（把 Agent 文件改回去，或更新 `config.yaml` 采纳新现实）；
3. 或者深思熟虑后用 `acm use --force` 覆盖（外部改动将被冲掉）。

特例：磁盘值与 last-write 不同、但*已经等于*期望状态时，`use` 视其为 no-op 成功而非阻断。

### 9.6 密钥安全与掩码

- `config.yaml` 存引用（`${VAR}`）不存密钥——可以放心入库。
- 任何展示场景（漂移明细、dry-run 计划）中，敏感命名（`api_key`、`token`、`auth`、`secret`、`password`、`credential`——大小写不敏感）的值一律掩码：前 3 字符 + `...` + 后 3 字符（短值变 `***`）。`${VAR}` 引用形式原样显示。
- 传 `--show-secrets` 显式选择明文显示。
- 文件系统卫生：`~/.acm` 的 state/log 目录 `0700`；生成的文件 `0600`。
- 保真度的诚实细则：未受管内容的保留在**语义级**是硬承诺；注释/键序/排版的保留程度按格式以金样 fixture 界定——JSON 保序且保留缩进风格，TOML（tomlkit）round-trip 保留注释/表顺序/空行。

### 9.7 崩溃与中断韧性

原子替换保证崩溃绝不可能留下半写的配置。故障注入测试（替换间隙 SIGKILL、并发篡改、注入磁盘故障、锁竞争）为这些承诺背书。崩溃留下的孤儿 `*.acm_tmp` 文件会在下一事务前自动清扫；快照允许手动恢复任意历史状态。

---

## 10. 状态目录与内部机制

### 10.1 目录布局

```
~/.acm/
├── config.yaml                  # SSOT（由你编辑与版本管理）
├── .gitignore                   # 忽略 state/、logs/、.lock、临时文件
├── logs/
│   └── acm.log                  # 操作日志（INFO；--verbose 时 DEBUG）
└── state/
    ├── .lock                    # 全局写锁文件
    ├── active                   # 激活 Profile 名（纯文本）
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

配置与状态严格分离：ACM 绝不把运行时状态写回 `config.yaml`。

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

- `fields`："文件::dotpath" → ACM 写入的值（漂移检测依据）；
- `backup_id` 指向本次写入前打的快照（回滚依据）；
- `created_files` 列出 ACM 新建的文件（回滚时归档而非还原）。

### 10.3 快照

`state/<agent>/snapshots/<snapshot-id>/<原文件名>` 存字节级精确副本；`.not_exist_<文件名>` 标记记录写入前该文件尚不存在。

### 10.4 环境变量

| 变量 | 默认值 | 用途 |
|---|---|---|
| `ACM_HOME` | `~/.acm` | 重定位 ACM 的整个家目录（配置+状态） |
| `ACM_VMR_PROBE_URL` | `http://127.0.0.1:8800` | `acm init` 使用的 VMR 探测端点 |
| `NO_COLOR` | — | 关闭彩色输出 |

（`ACM_TEST_FAULT_*` 变量仅供测试套件注入故障——生产环境切勿设置。）

---

## 11. 常见工作流手册（Recipes）

### R1 · 首次接入：官方 API → 所有 Agent

```bash
export ANTHROPIC_API_KEY=sk-ant-…
acm init                       # 无 VMR → 模板；按需编辑 providers/models
${EDITOR:-vi} ~/.acm/config.yaml
acm use daily
acm status                     # 期望全部 SYNCED
```

### R2 · 日常/省钱 Profile 之间切换

先定义好两个 Profile（见 §5.6c），然后：

```bash
acm use daily && acm status    # 日常配置
acm use budget                 # 全部切到便宜模型
acm use daily                  # ……再切回来；重复执行则是 no-op
```

### R3 · 全部指向本地网关/中转

要么跑 VMR（`acm init` 自动接上），要么声明一个 `base_url` 指向你中转的 provider（§5.6d），然后 `acm use daily`。

### R4 · 我手动改了 Agent 配置，怎么办？

```bash
acm status                     # 该 Agent 显示 DRIFTED 及 expected/found 明细
```

决策：想保留手改 → 把它同步录入 `config.yaml`（让 ACM 的期望状态与新现实一致），再 `acm use daily` 干净收敛；想丢弃 → `acm use daily --force` 恢复 ACM 的值。

### R5 · 撤销最近一次投影

```bash
acm rollback --dry-run         # 预览将还原/归档什么
acm rollback                   # 恢复写前快照；归档 ACM 创建的文件
acm status                     # 验证
```

回滚过头了？快照 append-only——去 `~/.acm/state/<agent>/snapshots/` 取任意更早的文件即可。

### R6 · 只针对单个 Agent 操作

```bash
acm use daily codex            # 只投影 Codex
acm rollback pi                # 只回滚 Pi
acm status claude_code         # 只查看 Claude Code
```

### R7 · SSOT 入版本库（团队基线）

`config.yaml` 只含 `${ENV}` 引用，`.gitignore` 也已排除 state/logs——所以 `~/.acm`（或仓库里的 `config.yaml` 副本）可以放心提交。团队成员各自在本地导出自己的凭据。

### R8 · 脚本 & CI

```bash
acm use production --no-color --force
case $? in
  0) echo converged ;;
  2) echo "blocked (drift/lock)"; exit 2 ;;
  *) echo "failed"; exit 1 ;;
esac
```

要点：依赖退出码（§6.5）；记住非 TTY 的 `rollback` 在需要归档文件时必须加 `--force`；用 `--dry-run` 预览计划。

### R9 · 彻底离开 ACM

ACM 绝对非侵入。停用只需卸载（`uv tool uninstall agent-config-manager`）并可选择性删除 `~/.acm/`。各 Agent 配置原地保持最后投影状态继续正常工作。无需任何 "release"。 （若想先把配置还原到接管前旧值，卸载前对每个 Agent 跑 `acm rollback`。）

---

## 12. 故障排查与 FAQ

**❓ ACM 与 `/model` 切换、多模型配置（如 Pi extension）是什么关系？**
`/model` 是各 Agent 的运行期能力——可选模型池来自 Agent 自身（内置目录；对 Pi 还包括 `models.json` 条目和 `pi.registerProvider()` 扩展）。ACM 管理的是另一层：投影**默认/激活模型**外加连接层，让所有 Agent 对齐 SSOT。两者干净地组合：`acm use <profile>` 设默认；`/model` 会话内临时覆盖。对 Pi 甚至可以组合使用——ACM 管默认模型，extension 或手写 `models.json` 提供完整多模型池（用不同的 provider 名避免互相覆盖）。见 §3.9 与 §7.3。

**❓ Profile 是怎么工作的？每个 Agent 实际得到哪个模型？**
Profile 是一套命名的“角色→模型”绑定表（`main` 必填；`cheap` 和自定义角色可选）。当前三个适配器只消费 **`main`** 角色；`cheap`/自定义角色会以显式的投影损失告警（`roles.cheap`、`roles.extra`）跳过——绝不静默丢弃。切换使用场景 = 切换 Profile（`acm use daily` / `acm use budget`），这会重新把所有 Agent 的配置指向新的 `main` 模型。不存在运行期自动分流。要让不同 Agent 用不同模型，请按 Agent 分别投影（`acm use <profile> <agent>`）。多角色适配器（规划中：Aider）将自动消费 `cheap`/自定义角色。详见 §3.9。

**❓ `Unresolved environment variables in configuration: ${ANTHROPIC_API_KEY}`**
在 shell（或 shell 配置文件）里 export 该变量，或在 config 中给兜底（`${VAR:-default}`）。此检查发生在任何文件 I/O 之前——什么都没写。

**❓ `Safety Block: external drift detected in [...]`**
某个受管字段在 ACM 之外被改了。见 R4。搞清楚改动内容之后才考虑用 `--force` 覆盖。

**❓ `Safety Block: agent configuration file is corrupted`（ERROR 态）**
目标文件无法解析（JSON/TOML 坏了，可能是编辑器事故）。手工修复语法；或接受重建：`acm use <profile> --force`——注意警告：损坏内容无法保留，只会重建 ACM 受管字段。可去 `~/.acm/state/<agent>/snapshots/` 找更早的可恢复版本。

**❓ `Another acm process is holding the write lock`**
另一个 ACM 实例正在操作（锁不跨进程存续，持锁进程崩溃后锁自动消失，所以这一般意味着真实竞争）。稍等重试；必要时排查残留进程。

**❓ `Whitelist violation`**
正常使用中不应出现——它意味着出现了操作指向非白名单路径/文件的内部不一致。请提 issue。

**❓ Pi 的 `models.json` 里旧 provider 越积越多**
这是设计使然（注册式增量投影；§7.3）。手动删除失效的 `providers.*` 条目，或 `acm rollback pi`。

**❓ 我的密钥到底存在哪里？**
用 `${VAR}` 引用时不在 `config.yaml`——在你的环境变量里。Claude Code 因自身设计必然在 `settings.json` 中拿到解析后的 token。除非传 `--show-secrets`，ACM 所有输出均掩码敏感值；state 文件有权限限制（0600/0700）。

**❓ `acm use` 显示成功，但 Agent 行为不对**
检查：(a) 是否重启了 Agent 会话——多数 Agent 在启动时读配置；(b) 该 Agent 是否真的读取 ACM 管理的那个文件（见 §7）；(c) `acm status` 里该 Agent 是否 SYNCED。

**❓ 支持 Windows 吗？**
暂不支持——全局写锁依赖 `fcntl`（POSIX）。目前 macOS/Linux。

**❓ 升级 ACM 会动我的配置吗？**
不会。升级只影响工具行为；在你执行写命令前，`config.yaml` 和 Agent 文件都不会被碰。schema 保持 `version: 1`（新旧 schema 不匹配会明确报错而非静默迁移）。

**❓ 我还能继续手动编辑 Agent 配置吗？**
可以——未受管字段随时可以。受管字段的手改会产生漂移（会被刻意暴露出来，绝不静默覆盖）。更好的做法是更新 SSOT，让 ACM 去收敛。

---

## 附录 A. 术语表

| 术语 | 定义 |
|---|---|
| **SSOT** | Single Source of Truth，单一事实源——`~/.acm/config.yaml`，模型世界的唯一描述。 |
| **Desired State** | 激活 Profile 经适配器编译出的字段级期望状态。 |
| **Current State** | 受管字段在磁盘上的实际值。 |
| **收敛（Convergence）** | 幂等地使 Current 等于 Desired。 |
| **漂移（Drift）** | Current ≠ 最后写入值（被外部修改）；默认阻断写入。 |
| **投影损失（Projection Loss）** | 目标 Agent 无法表达的期望设置；必告警，绝不静默丢弃。 |
| **ChangeSet / Ops** | 适配器产出的字段级操作集合；Safety Engine 的唯一输入。 |
| **受管 namespace** | 适配器声明拥有的 dot-path 前缀。 |
| **快照（Snapshot）** | `state/<agent>/snapshots/` 下写字节的写前完整副本；append-only 的审计与恢复证据。 |
| **Last-write 记录** | 每 Agent 一份 JSON，记录 ACM 最近写了什么（字段、profile、backup id）。 |
| **Journal** | 未来引入的 append-only 事务日志，支撑字段级逆操作回滚（规划升级项）。 |
| **适配器（Adapter）** | 每 Agent 一个的纯函数模块：detect / config_paths / plan。 |
| **VMR** | Virtual Model Router——本地模型路由器；可选的集成伙伴。 |

## 附录 B. 文件位置速查表

| 路径 | 角色 |
|---|---|
| `~/.acm/config.yaml` | SSOT 配置（编辑这个） |
| `~/.acm/state/active` | 当前激活 Profile 名 |
| `~/.acm/state/<agent>/last_write.json` | 最近投影记录（漂移依据、回滚指针） |
| `~/.acm/state/<agent>/snapshots/<ts>/` | 写前字节级备份 |
| `~/.acm/state/.lock` | 全局写锁 |
| `~/.acm/logs/acm.log` | 操作日志 |
| `~/.claude/settings.json` | Claude Code 配置（仅受管字段） |
| `~/.codex/config.toml` | Codex CLI 配置（仅受管字段） |
| `~/.pi/agent/models.json` + `settings.json` | Pi Agent 配置（仅受管字段；绝不碰 `models-store.json`） |

## 附录 C. 退出码速查表

`0` 成功/no-op · `1` 配置错误 · `2` 安全阻断（漂移/写锁/白名单/损坏未加 force） · `3` I/O 失败 · `4` 未找到 · `130` 用户中断。

## 附录 D. 环境变量速查表

`ACM_HOME`（默认 `~/.acm`）· `ACM_VMR_PROBE_URL`（默认 `http://127.0.0.1:8800`）· `NO_COLOR` · 以及你自己的 config 所引用的标准凭据环境变量。

---

*许可证：Apache-2.0。ACM 在 PyPI 上的分发名为 [`agent-config-manager`](https://pypi.org/project/agent-config-manager/)。*
