# ACM — Agent Config Manager 项目初始化文档

> 版本：v0.1（初始化基线） · 状态：已决策立项
> 性质：本文档是项目的主文档与初始化基线，包含立项决策、Scope、技术选型与架构设计。
> 参考资料说明：仓库内两份前期调研报告（`agent_config_manager_deep_analysis.md`、`agent_config_manager_evaluation_v1.0_custom-2-agent.md`）仅作背景参考，不构成依据。本文档基于独立的开源生态核验（2026-08，关键事实均已验证）与第一性原理推导独立作出决策，结论与两份报告存在实质性差异之处已显式标注。

---

## 1. 一句话定位

**ACM 是"模型配置"的单一事实源（SSOT）与投影引擎：用户在 ACM 中维护一套与 Agent 无关的 Provider/模型配置，通过一条命令将其安全地投影到本机任意 Coding Agent 的配置文件中，并可精确、无损地回滚。**

它同时是 VMR（Virtual Model Router）的"最后一公里"：把 VMR 代理出的虚拟模型一键接入本机所有 Agent。但 ACM 不依赖 VMR 独立成立——直连任何 OpenAI/Anthropic 兼容端点同样是一等公民场景。

---

## 2. 背景与问题定义

### 2.1 现实痛点（需求侧）

1. **多 Agent 并存已成常态**：开发者日常同时使用 Claude Code、Codex、Gemini CLI、Pi、Aider、OpenCode 等多个 Agent，每个 Agent 的配置位置、格式、语义各不相同（JSON / YAML / TOML / 环境变量 / VSCode 私有存储）。
2. **重复配置**：同一组 endpoint + key + 模型名，要在 N 个 Agent 里手工配 N 遍，改一次切一次，易错易漏。
3. **浅层配置不够**：生产级使用中，protocol 方言（openai / anthropic / responses）、context window、max output tokens、reasoning effort/budget、vision/tool-call 能力位，配错任意一项都会导致运行期故障（404、上下文超限、输出截断、能力误判）。绝大多数切换工具只管 `base_url` + `api_key` + `model` 三个字段。
4. **切换工具不安全**：配置文件是**双向所有权**的——Agent 运行时也持续向其中写入状态（权限许可、插件启用记录、会话缓存、OAuth token）。任何"全量模板覆写"式工具都会周期性抹掉用户环境，且无可靠回滚。

### 2.2 问题的本质（第一性原理）

把"给 Agent 换模型"这个动作分解到最小：

```
用户意图（用哪个模型、走哪个端点）
   ↓ 编译（值转换 + 字段映射 + 方言适配）
目标 Agent 配置文件中的一小撮字段
   ↓ 非破坏性写入（保留其余一切字节）
可验证、可回滚的最终状态
```

由此得出三条硬约束，构成本项目的公理：

- **公理 1（SSOT）**：模型世界的描述应只有一份，Agent 只是投影目标。为每个 Agent 重复维护配置是偶发复杂度，必须消除。
- **公理 2（非破坏性）**：工具只拥有它写入的字段，不拥有整个文件。未管理字段（MCP、插件、权限、状态）必须字节级无损。
- **公理 3（可逆性）**：任何变更必须可精确撤销。回滚粒度是"ACM 管理的字段"，而非"整个文件"（因为 Agent 在此期间可能已写入新状态，整文件回滚会误伤）。

---

## 3. 市场现状与竞品分析（独立核验）

### 3.1 竞品事实卡

以下关键事实均于 2026-08 独立核验（GitHub 仓库、Issues、官方文档），非转述报告。

| 项目 | 形态/规模 | 支持范围 | 写入机制 | 关键事实与评估 |
|---|---|---|---|---|
| **cc-switch** (farion1231) | Tauri 桌面 GUI，**127.7k★**，8.7k forks | Claude Code/Desktop、Codex、Gemini CLI、Grok Build、OpenCode、OpenClaw、Hermes | SQLite SSOT，切换时由内置模板**再生并整体写入**目标配置（官方称 atomic write + auto backup） | 事实上的品类霸主。但：① GUI-first，CLI/headless 仍是开放需求（issue #3986，另有社区 fork cc-switch-cli 补位）；② **破坏性问题被官方 FAQ 亲自确认**——"切换后插件配置消失"需用户手动配置 Shared Config Snippet 规避，属于用补丁特征补偿架构缺陷；③ Scope 持续膨胀：MCP/Prompts/Skills/会话管理/云同步/用量统计，甚至内置本地代理网关（热切换/故障转移），与"配置切换器"渐行渐远；④ 深度模型参数（context window、reasoning budget 等）建模薄弱，以 provider 预设（url/key/model 三件套）为中心 |
| **claude-code-router** (musistudio) | Node.js 网关 + Web UI | 名义上多 Agent，实际为自身网关导流 | 子进程包装注入 ENV + Web 端覆写 | 配置能力与网关运行时强耦合，无法作为独立配置工具使用 |
| **ccc** (guyskk/claude-code-config-switcher) | Python CLI | 仅 Claude Code | 利用 `--settings` 启动参数注入，**完全不触碰磁盘文件** | 机制优雅（零破坏），但依赖 Claude Code 特有参数，无法泛化到其他 Agent |
| **ccp** (claude-code-profile) | Go CLI | 仅 Claude Code | `CLAUDE_CONFIG_DIR` + 软链 Hub | 解决 Profile 隔离，无参数转换、无跨 Agent 能力 |
| **claude-swap** | Python TUI，~1.8k★ | 仅 Claude Code 官方账号 | OAuth Token Slot 轮转 | 定位是账号额度轮转，与第三方模型配置正交 |
| **cc-switch-cli** (社区 fork) | CLI | 同 cc-switch | 同 cc-switch（SQLite 再生） | 证明 CLI 需求真实存在，但未改变底层覆写架构 |

### 3.2 市场判断

- **"市场空白"的说法不成立**（两份报告的这一 claim 过时/不准确）：cc-switch 以 127.7k★ 证明需求真实且巨大，且已覆盖 8 个 Agent。
- 但生态位分化清晰：cc-switch 走的是"GUI 全家桶 + 中转生态运营"路线（其 README 的数十家 API 中转商赞助列表即证明）；**"CLI-first、模型配置专注、非破坏性、可编程、可嵌入脚本"** 这一生态位仍然是空的——这正是 ccc（不破坏文件但单 Agent）与 cc-switch-cli（CLI 但覆写架构）各自只占一半的原因。
- 需求侧结论：痛点真实、高频、且随多 Agent 使用强度单调上升。

---

## 4. 立项决策（Go/No-Go）

### 4.1 结论：**GO（做），但立项理由与两份报告不同，且必须诚实声明边界**

**理由 1（第一动因）：解决自己的问题。** 我们的核心场景是 VMR 用户（包括我们自己）需要把本机多个 Agent 一键指向 VMR 虚拟模型。cc-switch 内置了自己的本地代理（与 VMR 同类竞争），不会为 VMR 做最优集成；这个工具必须掌握在自己手里。

**理由 2（生态位真实存在）：** 见 §3.2——CLI-first × 模型专注 × 非破坏性 × 可编程，四个属性取交集，现存工具为零。"像 git/nvm 一样可信赖且可脚本化"的配置工具与"像控制面板一样的 GUI 全家桶"是不同产品，可以共存（参照 CLI Git 客户端与 GUI 客户端长期共存）。

**理由 3（成本可控）：** Scope 严格限定在模型配置（见 §5），适配面是每个 Agent 的个位数文件、十几个字段，安全引擎（快照/原子写/管理清单）是一次性框架成本。总工程量约数千行代码，MVP 以天计。

**诚实声明（何为本项目的非目标与失败条件）：**
- 不以"超越/取代 cc-switch"为目标，不拼 star 数，不做 GUI，不做 MCP/Skills/网关/用量统计。若未来发现自己在给这些功能写代码，说明项目已经跑偏。
- **若失去理由 1**（例如 VMR 项目方向变更、不再需要客户端一键接入），理由 2 单独是否足以支撑维护投入需重新评估——届时应主动重新审视立项。
- cc-switch 未来完全可能补上 CLI 与深度参数建模。我们的护城河不是功能清单，而是哲学（最小、专注、文件级尊重）与 VMR 的原生协同。

---

## 5. Scope 边界

### 5.1 判定原则

> **凡是"换了 Provider/模型之后理应保持不变的东西"，ACM 一律不碰。**

### 5.2 管什么（In Scope）

| 层 | 内容 | 说明 |
|---|---|---|
| **L1 连接与凭据** | base_url、protocol（openai / anthropic / openai-responses）、api_key（支持 `${ENV_VAR}` 引用）、自定义 headers、proxy | 含写入 Agent 支持的 env 块（如 Claude Code settings.json 的 `env` 字段） |
| **L2 模型规格与行为** | 模型选择（主模型 + 角色模型，如 Aider 的 weak/editor model、Agent 的 primary/cheap 分工）、context window、max output tokens、reasoning effort/budget、temperature、能力位（vision / tool-call 方言 / json mode） | ACM 统一建模，由适配器转换为目标 Agent 的专有字段 |

### 5.3 不管什么（Out of Scope，显式列出以防蔓延）

- **MCP servers、Tools、Skills、Prompts（CLAUDE.md/AGENTS.md 等）、权限许可、hooks** —— 坚决不碰，这正是 cc-switch 覆写事故与臃肿化的根源。ACM 的写入必须绕开这些区域（管理字段清单机制保障，见 §7.4）。
- 账号轮转 / OAuth token 池 / 额度监控（claude-swap 的领域）。
- 本地代理 / 网关 / 请求改写（VMR 的领域）。
- Agent 启动包装（如 ccr 的子进程模式、ccc 的 `--settings` 注入模式）。MVP 只做持久化配置文件投影；启动包装作为未来的可选适配器策略再评估。
- GUI / TUI（可选一个极简交互式 `acm use` 选择器，但核心是脚本友好的 CLI）。
- VSCode 系闭源私有存储（Cursor/Cline 的 `state.vscdb` SQLite）。只支持其公开的 settings.json 通道；没有干净通道就不支持，**绝不写私有数据库**。

---

## 6. 关键技术决策

以下四个决策均有独立论证，与两份参考报告存在分歧处已注明。

### D1：适配器 = 代码（Python 模块），不是 DSL

**结论：每个 Agent 一个独立的适配器模块（普通 Python 代码），共用一套 Helper 库。不引入声明式 DSL 作为扩展机制。**

论证：

1. **抽象成本核算**。Agent 配置的 field mapping 中，约 60–70% 是"把 profile 字段 X 写到路径 Y"的简单映射，DSL 可以覆盖；但剩余 30–40% 包括：值转换（reasoning effort → 各家不同的 budget 表达）、条件写入、多文件协同（Codex 的 config.toml + auth.json）、平台路径差异、格式方言处理、以及各种"此 Agent 特有"的怪癖。DSL 为了覆盖这些必须不断膨胀（条件、函数、转义……），最终变成一门糟糕的编程语言。**这是经典的泄漏抽象：配置语义天然图灵不完备不成立。**
2. **逃生舱的位置**。DSL 路线的实际扩展方式是"等官方更新 DSL"或"用户写逃逸脚本"——那不如从一开始就把逃生舱作为正门：适配器就是代码，能力上限 = 宿主语言上限。新 Agent 不适合现有 Helper？从零写一个独立模块即可，互不牵连。
3. **AI 辅助维护的自然语言**。两份报告都提出"AI 提取 Schema + 生成 DSL + CI 金样回归"流水线。但 LLM 生成/修改**代码**远比生成受 DSL 语法约束的补丁文件更自然可靠——代码本就是 LLM 的母语。报告中的 AI 流水线机制，实际是在补偿 DSL 的刚性；换成代码路线后该机制依然成立且更顺。
4. **保留数据驱动的合理部分**。每个适配器内部当然可以用一张映射表（dict）描述简单字段映射——这是"代码使用数据"，与"把 DSL 产品化为外部扩展格式"有本质区别。如果未来某类映射模式高度稳定，可以再考虑将其提炼为更高层的 Helper（函数库），而非外部 DSL。

（分歧声明：两份报告均推荐声明式 DSL 驱动。本决策否决该路线，理由如上。用户直觉方向一致，本论证为其提供了独立依据。）

### D2：语言 = Python 3.11+，而非 Go

**结论：纯 Python，最小依赖（ruamel.yaml、tomlkit、typer 或 argparse），uv/pipx 分发。**

论证（从本项目的需求特征倒推）：

| 需求特征 | Go | Python |
|---|---|---|
| 适配器 = 可独立编写/可动态加载的代码（D1） | ❌ 编译进二进制，新适配器 = 发版；Go plugin 在 macOS 基本不可用；解释器方案（yaegi/goja）等于自造 DSL 困境 | ✅ 模块即插即用；用户自定义适配器放 `~/.acm/adapters/*.py` 用 importlib 加载，零成本 |
| 非破坏性 round-trip 编辑（YAML 保注释、TOML 保格式） | ⚠️ yaml.v3 Node 操作繁琐，TOML round-trip 库弱 | ✅ ruamel.yaml / tomlkit 是事实标准，久经考验 |
| 分发 | ✅ 单二进制（唯一显著优势） | ⚠️ 依赖 uv/pipx/pip；但目标用户（装着多个 coding agent 的开发者）机器上 Python 几乎必然存在，`uv tool install acm` 一条命令 |
| 迭代速度 / 上游 schema 漂移应对 | 慢（编译、发版） | 快 |
| 性能 | 无关紧要（纯本地文件 I/O，无热路径） | 无关紧要 |

单二进制的分发优势，是 Go 唯一的实质优势，但它的代价（编译型语言与 D1 的"适配器即代码"路线根本冲突）对本项目是致命的。**需求决定语言，而非相反。** Python 的运行时依赖风险由 uv 锁定依赖 + 最小依赖集（目标 ≤4 个运行时依赖）控制。

（分歧声明：两份报告均推荐 Go。本决策否决，核心理由是 D1 与 Go 的不兼容性。）

### D3：Core Config —— ACM 自有的模型世界 SSOT

**结论：采纳并落实"核心配置"概念：ACM 拥有一套与 Agent 完全无关的内部配置（providers / models / profiles），各 Agent 是投影目标而非配置主体。**

这是对两份报告中 "Unified Model Schema / Profile" 概念的强化与再定位：

- 报告的表述偏向"翻译层"（用户写统一 profile，工具翻译给 Agent）；Core Config 的表述则是**所有权声明**：模型世界的事实源在 ACM 内部（`~/.acm/config.toml`），包括 providers（端点/协议/密钥引用）、models（模型规格/能力/行为参数）、profiles（命名组合，如"coding 高配"、"省钱档"）。Agent 端永远是投影的影子，`acm status` 随时可回答"每个 Agent 现在投的是哪个 profile、实际落盘值与期望值是否有漂移"。
- 与 VMR 的天然衔接：VMR 上的虚拟模型组合（多供应商真实模型 → 虚拟模型）通过 `acm import vmr` 一次性导入为 Core Config 中的 provider + models，即成为可投影的 base 配置。此后一切切换都在 ACM 侧完成，Agent 侧零手工操作。
- Schema 草案见 §7.2。

### D4：安全引擎 = 管理字段清单 + 文件快照 + 原子写

**结论：以"字段级管理清单"为主、"文件级快照”为兜底，而非两份报告设计的文件级快照回滚为主。**

理由（公理 3 的直接推论）：Agent 在 ACM 写入之后可能又向同一文件写入了新状态。此时若按报告方案回滚整个文件快照，会把 Agent 新写的状态一起抹掉——这正是 CC-Switch 回滚事故的镜像。正确语义是：

1. **写入前**：适配器输出的 ChangeSet 逐字段记录（文件、路径、旧值、新值）→ 存入该 Agent 的**管理字段清单**（managed manifest）并同步保存文件快照（兜底用）。
2. **写入时**：round-trip 解析 → 仅修改管理路径 → 原子落盘（temp + `os.replace`）。未管理字段字节级不动。
3. **回滚时**：默认按清单恢复各字段的旧值（保留 Agent 后写入的其他状态）；`--hard` 才用快照整文件还原（用于文件被写坏的灾难恢复）。
4. **`acm release`**：按清单移除 ACM 注入的所有配置，恢复 pre-ACM 状态——让用户可以无残留地退坑，这是信任的基础。

---

## 7. 架构设计

### 7.1 组件图

```
┌─────────────────────────────────────────────────────────────┐
│                        acm CLI（typer）                       │
│  use / status / diff / rollback / release / import / doctor  │
├─────────────────────────────────────────────────────────────┤
│                      Core（纯逻辑，无 I/O）                    │
│  CoreConfig 加载校验 · Profile 解析 · ChangeSet 计划 · 幂等判断 │
├──────────────────────────┬──────────────────────────────────┤
│      Safety Engine       │          Adapter Layer           │
│  快照 · 管理清单 · 原子写   │   Adapter Protocol（detect/plan/  │
│  进程检测 · 字段级回滚      │   apply/verify）                  │
│                          ├──────────────────────────────────┤
│                          │ 内置适配器（每 Agent 一个模块）      │
│                          │  claude_code · codex · pi · ...   │
│                          │ 用户适配器 ~/.acm/adapters/*.py    │
├──────────────────────────┴──────────────────────────────────┤
│                    Format Helpers（共用库）                    │
│  JSON 保序合并 · ruamel round-trip · tomlkit · .env 行编辑    │
│  路径解析（XDG/macOS/Win） · keychain/env 引用                │
└─────────────────────────────────────────────────────────────┘
```

关键点：**Core 不含 I/O；适配器只做"编译"（profile → ChangeSet），写入统一由 Safety Engine 执行**。这保证所有适配器天然继承安全语义，无法绕过。

### 7.2 Core Config Schema 草案（`~/.acm/config.toml`）

```toml
[providers.vmr]
protocol = "openai"                      # openai | anthropic | openai-responses
base_url = "http://127.0.0.1:8800/v1"
api_key  = "${VMR_KEY}"                  # env 引用优先；明文存储需显式 opt-in
# headers = { x-extra = "..." }

[models.coding]
provider   = "vmr"
id         = "coding"                    # 实际请求的 model id / 虚拟模型名
context_window    = 131072
max_output_tokens = 16384
vision      = false
temperature = 0.2
[models.coding.reasoning]
effort = "high"                          # 适配器负责换算为各家 budget 表达

[profiles.daily]
main  = "coding"
cheap = "cheap"                          # 供支持角色模型的 Agent 映射

[profiles.budget]
main  = "cheap"
```

### 7.3 适配器契约（Python Protocol）

```python
class Adapter(Protocol):
    agent_id: str                          # "claude_code"
    def detect(self) -> bool: ...          # 本机是否安装该 Agent
    def plan(self, profile: ResolvedProfile) -> ChangeSet: ...
        # 纯函数：产出字段级变更集（路径、旧值探测、新值、保护区域声明）
        # 值转换/方言适配/多文件协同全部在这里，用普通代码写
    def verify(self, cs: ChangeSet) -> Report: ...  # 落盘后断言
```

适配器内部可自由使用映射表 dict、条件逻辑、调用 Helpers——它是代码，不是配置。新增 Agent = 新增一个约 100–300 行的模块 + 一组金样 fixtures。

### 7.4 安全机制汇总

| 机制 | 实现 |
|---|---|
| 非破坏性写入 | round-trip 解析（ruamel/tomlkit）；JSON 用保序 dict 合并（未知字段天然保留，键序不变） |
| 管理字段清单 | `~/.acm/state/<agent>/manifest.json`：ACM 写过的每个路径 + pre-ACM 旧值 |
| 文件快照 | `~/.acm/state/<agent>/snapshots/<ts>/`，仅灾难恢复与审计用 |
| 原子写 | temp file + `os.replace`；多文件变更按序提交，任一失败即中止后续并回滚已提交项 |
| 进程检测 | 写入前 `pgrep` 已知进程名，运行中则警告（`--force` 覆盖） |
| Dry-run & diff | `acm use --dry-run` 输出 ChangeSet；`acm diff` 展示期望态 vs 落盘态漂移 |
| 幂等 | 重复 apply 同一 profile 是 no-op（ChangeSet 与清单比对后为空） |

### 7.5 目录布局

```
~/.acm/
├── config.toml                 # Core Config（SSOT；用户可 git 管理自己的版本）
├── adapters/                   # 用户自定义适配器（动态加载，逃生舱）
├── state/<agent>/
│   ├── manifest.json           # 管理字段清单
│   └── snapshots/<ts>/         # 文件快照
└── logs/
```

---

## 8. VMR 协同（松耦合）

```
$ acm import vmr                    # 探测 127.0.0.1:8800 / ~/.vmr/，拉取虚拟模型列表
                                    # → 生成 providers.vmr + models.* 到 Core Config
$ acm use daily --all               # 将 profile 投影到本机所有已检测到的 Agent
$ acm status                        # 总览：各 Agent 当前指向 / 漂移状态
```

- 零依赖原则：无 VMR 时一切功能照常（直连 OpenRouter/DeepSeek/SiliconFlow/Ollama/任意兼容端点）。
- VMR 侧不需任何代码改动，只需暴露标准的模型列表查询；ACM 对 VMR 的全部"感知"就是一次 import。

---

## 9. 首批适配器与字段映射要点

| Agent | 目标文件 | 投影要点（实现时以金样 fixture 校准为准） |
|---|---|---|
| **Claude Code** | `~/.claude/settings.json`（env 块、model）；**不碰** `~/.claude.json`（运行时状态文件） | `env.ANTHROPIC_BASE_URL/AUTH_TOKEN`、`model`；reasoning 映射为 Max-compatible 表达；保护 mcpServers/permissions/hooks/plugins |
| **Codex** | `~/.codex/config.toml`（+ auth.json 仅限 key 类） | provider/base_url/model 表；tomlkit round-trip 保注释；保护 sandbox/notification 等无关表 |
| **Pi** | `~/.pi/agent/models.json`（provider+model 注册，含 compat 能力位）+ `settings.json`（defaultProvider/defaultModel/defaultThinkingLevel） | Pi 的 schema 与 Core Config 概念同构度最高（api 方言、reasoning、compat 开关），映射最直接 |
| Gemini CLI / OpenCode / Aider / OpenClaw | Phase 2 | Aider 注意多角色模型（main/weak/editor）；OpenClaw 注意全局与 per-agent 两级配置 |

---

## 10. 实施路线

| 阶段 | 周期 | 交付 |
|---|---|---|
| **P1 MVP** | ~1 周 | 框架（Core/Safety/Helpers/Adapter Protocol）+ claude_code / codex / pi 三适配器 + `import vmr` + `use/status/diff/rollback/release/doctor` 全命令 + 各适配器金样测试（含带 MCP/注释/怪癖的真实样本） |
| **P2 扩展** | ~1–2 周 | gemini-cli / opencode / aider / openclaw；角色模型映射；`--all` 批量投影；CI 全量金样回归 |
| **P3 生态** | 持续 | 用户适配器协议文档与模板；社区适配器贡献流程；Homebrew pipx 分发渠道；VSCode 系公开 settings 通道支持（不碰私有 DB） |

---

## 11. 风险与对策

| 风险 | 评估 | 对策 |
|---|---|---|
| 上游 Agent schema 漂移 | 高频但影响面小（模型字段是稳定子集） | 适配器隔离（漂移不跨 Agent 传染）+ 金样 fixtures + AI 辅助更新适配器代码 + `acm doctor` 主动检测落盘异常 |
| 与 cc-switch 竞争 | 不正面竞争 | 哲学差异化（CLI/专注/非破坏/可编程）；服务 VMR 生态为第一动因；不拼功能清单 |
| 闭源 IDE 私有存储 | Cursor/Cline 部分状态在 SQLite | 原则：没有干净通道就不支持，绝不写私有 DB |
| 密钥安全 | 中 | 默认 `${ENV}` 引用；明文存储显式 opt-in 并警告；keychain 集成为后续可选 |
| Python 运行时分发摩擦 | 低（目标受众） | uv/pipx 一条命令安装；依赖 ≤4 个并锁定 |
| 单人项目维护连续性 | 中 | 代码量与 scope 严格受控（公理：宁可不做，不做大）；文档即本项目主文档持续演进 |

---

## 12. 成功标准

**对内（第一优先）**：VMR 用户从"装好 VMR"到"本机 3+ 个 Agent 全部指向 VMR 虚拟模型"，全程 ≤ 3 条命令、≤ 1 分钟、零手工编辑配置文件、`acm release` 后零残留。

**对外（第二优先）**：一个不使用 VMR 的多 Agent 开发者，愿意把 ACM 纳入日常工具链的理由是——"它只做模型配置这一件事，我从不必担心它弄坏我的配置文件，且它可被脚本化嵌入任何工作流。"

两条标准中，前者不达成则项目失去第一动因，后者不达成则项目退化为内部脚本——两者都成立时，项目才值得作为独立开源仓库长期存在。
