# ACM（Agent Config Manager）最终版项目规格说明书

<!-- Version: 1.0.0-FINAL | Status: Approved Baseline | Date: 2026-08-17 -->
<!-- 本文档取代以下三份前置文档，成为 ACM 项目的唯一权威规格：
     - ACM_PROJECT_INIT_glm5.3.md（骨架来源）
     - ACM_PROJECT_SPEC_sonnet4.6.md（MVP 克制与测试方法来源）
     - ACM_INITIALIZATION_SPEC_gemini3.7flash.md（适配器与工程细节来源）
     以及《基于GLM版的ACM方案完善建议》（V1/V2/V3，逐项裁决记录见附录 A） -->

> **文档性质**：ACM 项目的 Single Source of Truth。
> **生成方法**：以 GLM 版为骨架，对建议文档逐项裁决（附录 A），关键事实性 claim 全部溯源核实（附录 B），对建议文档内部的矛盾点（Core Config 格式、MVP 适配器选型、分发策略、热加载时机）按第一性原理独立裁决（§6.6、D5、D6）。

---

## 目录

1. [一句话定位](#1-一句话定位)
2. [背景与问题定义](#2-背景与问题定义)
3. [市场现状与竞品分析（已核实）](#3-市场现状与竞品分析已核实)
4. [立项决策与退出条件](#4-立项决策与退出条件)
5. [Scope 边界与项目铁律](#5-scope-边界与项目铁律)
6. [关键技术决策](#6-关键技术决策)
7. [架构设计](#7-架构设计)
8. [Agent 适配矩阵](#8-agent-适配矩阵)
9. [VMR 协同](#9-vmr-协同)
10. [CLI 命令规格](#10-cli-命令规格)
11. [测试与质量保障](#11-测试与质量保障)
12. [实施路线图与验收标准](#12-实施路线图与验收标准)
13. [风险与对策](#13-风险与对策)
14. [成功标准](#14-成功标准)
- [附录 A：建议文档逐项裁决记录](#附录-a建议文档逐项裁决记录)
- [附录 B：事实核查记录](#附录-b事实核查记录)

---

## 1. 一句话定位

**ACM 是"模型配置"的单一事实源（SSOT）与投影引擎：用户在 ACM 中维护一套与 Agent 无关的 Provider/模型配置，通过一条命令将其安全地投影到本机任意 Coding Agent 的配置文件中，并可精确、无损地回滚。**

它同时是 VMR（Virtual Model Router）的"最后一公里"：把 VMR 代理出的虚拟模型一键接入本机所有 Agent。但 ACM 不依赖 VMR 独立成立——直连任何 OpenAI/Anthropic 兼容端点同样是一等公民场景。

**核心架构原则（贯穿全文）**：ACM 管理的是**字段**，不是文件。所有 patch、diff、rollback 都围绕字段所有权（Field Ownership）设计。

---

## 2. 背景与问题定义

### 2.1 现实痛点（需求侧）

1. **多 Agent 并存已成常态**：开发者日常同时使用 Claude Code、Codex、Pi、Gemini CLI、OpenCode 等多个 Agent，每个 Agent 的配置位置、格式、语义各不相同（JSON / YAML / TOML / 环境变量 / VSCode 私有存储）。
2. **重复配置**：同一组 endpoint + key + 模型名，要在 N 个 Agent 里手工配 N 遍，改一次切一次，易错易漏。
3. **浅层配置不够**：生产级使用中，protocol 方言（openai / anthropic / openai-responses）、context window、max output tokens、reasoning effort/budget、vision/tool-call 能力位，配错任意一项都会导致运行期故障（404、上下文超限、输出截断、能力误判）。绝大多数切换工具只管 `base_url` + `api_key` + `model` 三个字段。
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

由此得出三条公理，构成本项目的根基：

- **公理 1（SSOT）**：模型世界的描述应只有一份，Agent 只是投影目标。为每个 Agent 重复维护配置是偶发复杂度，必须消除。
- **公理 2（非破坏性）**：工具只拥有它写入的字段，不拥有整个文件。未管理字段（MCP、插件、权限、状态）必须无损保留。
- **公理 3（可逆性）**：任何变更必须可精确撤销。回滚粒度是"ACM 管理的字段"，而非"整个文件"（因为 Agent 在此期间可能已写入新状态，整文件回滚会误伤）。

---

## 3. 市场现状与竞品分析（已核实）

> 关键事实已于 2026-08-17 溯源核实（GitHub 仓库页与官方 README/FAQ 抓取、本机环境实证），核查记录见附录 B。不可考的具体 issue 编号一律不引用。

### 3.1 竞品事实卡

| 项目 | 形态/规模 | 支持范围 | 写入机制 | 核实过的关键事实与评估 |
|---|---|---|---|---|
| **cc-switch** (farion1231) | Tauri 桌面 GUI，**128k★ / 8.7k forks / 1.5k open issues** | Claude Code/Desktop、Codex、Gemini CLI、Grok Build、OpenCode、OpenClaw、Hermes（8 款） | SQLite SSOT，切换时由模板**再生并整体写入**目标配置 | 事实上的品类霸主。但：① **覆写破坏由官方 FAQ 亲自确认**——"切换后插件配置消失"，官方解法是让用户手动配置 "Shared Config Snippet"，属用补丁特征补偿架构缺陷；② Scope 严重膨胀：MCP/Prompts/Skills 统一管理、会话管理器、用量仪表盘、云同步、Deep Link；③ **内置本地代理网关**（热切换/故障转移/熔断），与 VMR 直接同类竞争，不可能为 VMR 做最优集成；④ GUI-first，README 主打桌面应用与系统托盘，CLI/headless 支持薄弱；⑤ 深度模型参数建模薄弱，以 provider 预设（url/key/model 三件套）为中心；⑥ README 含数十家 API 中转商赞助墙，运营方向是中转生态而非工具本身 |
| **claude-code-router** (musistudio) | Node.js 网关 + Web UI | 名义上多 Agent，实际为自身网关导流 | 子进程包装注入 ENV + Web 端覆写 | 配置能力与网关运行时强耦合，无法作为独立配置工具使用 |
| **ccc** (guyskk/claude-code-config-switcher) | Python CLI | 仅 Claude Code | 利用 `--settings` 启动参数注入，**完全不触碰磁盘文件** | 机制优雅（零破坏），但依赖 Claude Code 特有参数，无法泛化到其他 Agent |
| **ccp** (claude-code-profile) | Go CLI | 仅 Claude Code | `CLAUDE_CONFIG_DIR` + 软链 Hub | 解决 Profile 隔离，无参数转换、无跨 Agent 能力 |
| **claude-swap** | Python TUI | 仅 Claude Code 官方账号 | OAuth Token Slot 轮转 | 定位是账号额度轮转，与第三方模型配置正交 |

### 3.2 市场判断

- **"市场空白"的说法不成立**：cc-switch 以 128k★ 证明需求真实且巨大，且已覆盖 8 个 Agent。
- 但生态位分化清晰：cc-switch 走的是"GUI 全家桶 + 中转生态运营 + 内置网关"路线；**"CLI-first、模型配置专注、非破坏性、可编程、可嵌入脚本"** 这一生态位仍然为空——这正是 ccc（不破坏文件但单 Agent）与社区 CLI fork（CLI 但覆写架构）各自只占一半的原因。
- 需求侧结论：痛点真实、高频、且随多 Agent 使用强度单调上升。

---

## 4. 立项决策与退出条件

### 4.1 结论：**GO（做），但立项理由诚实声明边界**

**理由 1（第一动因）：解决自己的问题。** 我们的核心场景是 VMR 用户（包括我们自己）需要把本机多个 Agent 一键指向 VMR 虚拟模型。cc-switch 内置了自己的本地代理（与 VMR 同类竞争），不会为 VMR 做最优集成；这个工具必须掌握在自己手里。

**理由 2（生态位真实存在）**：见 §3.2——CLI-first × 模型专注 × 非破坏性 × 可编程，四个属性取交集，现存工具为零。"像 git/nvm 一样可信赖且可脚本化"的配置工具与"像控制面板一样的 GUI 全家桶"是不同产品，可以长期共存。

**理由 3（成本可控）**：Scope 严格限定在模型配置（§5），适配面是每个 Agent 的个位数文件、十几个字段，安全引擎（快照/原子写/管理清单）是一次性框架成本。总工程量数千行，MVP 以天计。

**不以"超越/取代 cc-switch"为目标**：不拼 star 数、不做 GUI、不做 MCP/Skills/网关/用量统计、不拼 Agent 覆盖数量。ACM 的竞争维度只有五个词：**简单、可靠、可脚本化、非破坏性、模型配置 SSOT**。

### 4.2 明确的退出/降级条件（可执行）

| 触发条件 | 动作 |
|---|---|
| VMR 项目终止或方向变更 | ACM 降级为内部工具：停止新增功能，仅维护既有适配器；若社区活跃度足以独立支撑则继续，否则冻结 |
| 连续 6 个月无外部社区反馈且内部使用频次极低 | 归档项目，README 挂出迁移说明 |
| 发现自己在给 MCP/Skills/Prompt/网关/GUI 写代码 | 立即停下——这是 CC-Switch 的歧路，见 §5 铁律 |

---

## 5. Scope 边界与项目铁律

### 5.1 判定原则

> **凡是"换了 Provider/模型之后理应保持不变的东西"，ACM 一律不碰。**

### 5.2 管什么（In Scope）

| 层 | 内容 | 说明 |
|---|---|---|
| **L1 连接与凭据** | `base_url`、`protocol`（openai / anthropic / openai-responses）、`api_key`（支持 `${ENV_VAR}` 与 `${ENV_VAR:-default}` 引用）、自定义 headers、proxy、org_id | 含写入 Agent 支持的 env 块（如 Claude Code `settings.json` 的 `env` 字段） |
| **L2 模型规格与行为** | 模型选择（主模型 + 角色模型，如 Aider 的 main/weak/editor、Agent 的 primary/cheap 分工）、`context_window`、`max_output_tokens`、reasoning（`effort` low/medium/high + `budget_tokens`）、`temperature`、能力位（vision / tool-call 方言 native/xml/markdown / json mode） | ACM 统一建模，由适配器转换为目标 Agent 的专有字段 |
| **Profile 管理** | 多 Profile 定义、激活态、版本快照、字段级回滚、diff | |
| **VMR 集成** | 自动探测本地 VMR、导入虚拟模型列表、一键投影 | 第一方集成，非架构依赖（§9） |

### 5.3 不管什么（Out of Scope）

- **MCP servers、Tools、Skills、Prompts（CLAUDE.md/AGENTS.md 等）、权限许可、hooks、plugins**——坚决不碰。
- 账号轮转 / OAuth token 池 / 额度监控（claude-swap 的领域）。
- 本地代理 / 网关 / 请求改写（VMR 的领域）。
- Agent 启动包装（如 ccr 的子进程模式、ccc 的 `--settings` 注入模式）。MVP 只做持久化配置文件投影。
- GUI / TUI（核心是脚本友好的 CLI）。

### 5.4 项目铁律（Scope 的刚性约束，写入 CONTRIBUTING 与 PR 模板）

1. **绝不触碰** MCP、插件、Skills、系统提示词、权限配置、Agent 运行时状态文件。
2. **绝不写入**闭源 IDE 的私有数据库（如 Cursor/Cline 的 `state.vscdb` SQLite）。没有公开、稳定、可安全修改的配置接口，就不支持该 Agent——不为数量突破原则。
3. **任何新功能先过判定**：是否属于"模型配置层"（§5.2）？否则一律拒绝，无论需求来自谁。
4. ACM 的写入只落在**适配器声明的管理路径**上，由安全引擎强制执行（白名单 + 黑名单双重校验，§7.5）。

---

## 6. 关键技术决策

### D1：适配器 = 代码（Python 模块），不是 DSL

**结论：每个 Agent 一个独立的适配器模块（普通 Python 代码），共用一套 Helper 库。不引入声明式 DSL 作为扩展机制。**

论证：

1. **抽象成本核算**。Agent 配置的 field mapping 中约 60–70% 是"把 profile 字段 X 写到路径 Y"的简单映射，DSL 可以覆盖；但剩余 30–40% 包括：值转换（reasoning effort → 各家不同的 budget 表达）、条件写入、多文件协同（Codex 的 `config.toml` + `auth.json`）、平台路径差异、格式方言、各种 Agent 特有怪癖。DSL 为了覆盖这些必须不断膨胀，最终变成一门糟糕的编程语言。**这是经典的泄漏抽象：配置语义天然图灵不完备不成立。**
2. **逃生舱的位置**。DSL 路线的实际扩展方式是"等官方更新 DSL"——那不如从一开始就把逃生舱作为正门：适配器就是代码，能力上限 = 宿主语言上限。
3. **AI 辅助维护的自然语言**。LLM 生成/修改**代码**远比生成受 DSL 语法约束的补丁文件更自然可靠。上游 schema 漂移时，"贴上官方文档让 AI 改适配器"是本项目规划中的标准维护动作。
4. **保留数据驱动的合理部分**。适配器内部当然可以用映射表（dict）描述简单字段映射——这是"代码使用数据"，与"把 DSL 产品化为外部扩展格式"有本质区别。

### D2：语言 = Python 3.11+，而非 Go

**结论：纯 Python，最小依赖（typer+rich、ruamel.yaml、tomlkit；pydantic 可选，见下），uv 生态分发。**

| 需求特征 | Go | Python |
|---|---|---|
| 适配器 = 可独立编写/可动态加载的代码（D1） | ❌ 编译进二进制，新适配器 = 发版；Go plugin 在 macOS 基本不可用 | ✅ 模块即插即用；用户适配器放 `~/.acm/adapters/*.py` 用 importlib 加载 |
| 非破坏性 round-trip 编辑 | ⚠️ yaml.v3 Node 操作繁琐，TOML round-trip 库弱 | ✅ ruamel.yaml / tomlkit 是事实标准 |
| 分发 | ✅ 单二进制（唯一显著优势） | ⚠️ 依赖 uv/pipx；但目标用户机器上 Python 几乎必然存在 |
| 迭代速度 / 上游 schema 漂移应对 | 慢 | 快 |
| 性能 | 无关紧要（纯本地文件 I/O） | 无关紧要 |

Go 的单二进制优势与 D1"适配器即代码"根本冲突，对本项目致命。**需求决定语言，而非相反。**

依赖预算（硬约束）：运行时依赖 ≤ 4 个——`typer`+`rich`（计 1 组）、`ruamel.yaml`、`tomlkit`，外加可选 `pydantic`（仅 Core Config 严格校验；若引入则计入预算，实现时以"手写 dataclass 校验"为 fallback 评估）。进程检测用标准库（`pgrep` / `tasklist`），**不引入 psutil**。

### D3：Core Config = ACM 自有的模型世界 SSOT，格式 TOML

**结论：采纳"核心配置"概念并保持 TOML 格式（`~/.acm/config.toml`）。**

这是**所有权声明**：模型世界的事实源在 ACM 内部（providers / models / profiles 三层），Agent 端永远是投影的影子。`acm status` 随时可回答"每个 Agent 现在投的是哪个 profile、实际落盘值与期望值是否有漂移"。

**否决"改为 YAML"的建议（建议文档 V1-二.2），理由：**

1. 该文件同时被用户手写和 ACM 机器读写（`acm import vmr` 会增量改写它）。TOML 无缩进语义、无类型歧义（YAML 的挪威问题/隐式类型/缩进错误），**双向读写场景下损坏概率显著更低**。
2. 实际嵌套深度只有 3 层（provider → model → reasoning），V1 声称的"TOML 深层嵌套可读性差"在此深度不成立。
3. 依赖经济性：Codex 适配器是 P0（§6.6），tomlkit 本来就是硬依赖，Core Config 用 TOML **零新增依赖**；与 Agent 端 YAML 文件（Aider/Hermes）在扩展名上天然区分，降低误编辑概率。
4. ruamel/tomlkit 均具备注释保留的 round-trip 能力，ACM 改写自身配置时同样保用户注释。

### D4：安全引擎 = 字段所有权清单为主 + 文件快照兜底

**结论：以"字段级管理清单（Managed Manifest）"为核心回滚机制，"文件级快照"降级为审计与灾难恢复的 Safety Net。**

理由（公理 3 的直接推论）：Agent 在 ACM 写入之后可能又向同一文件写入了新状态。此时若回滚整个文件快照，会把 Agent 新写的状态一起抹掉——这正是 CC-Switch 覆写事故的镜像。正确语义是三层恢复体系：

```
ChangeSet / 字段级回滚（默认） → Journal（审计轨迹） → 全文件快照（--hard 灾难恢复）
```

完整机制见 §7.5。

### D5：分发 = 单一主路径，其余通道按需后置

**结论：MVP 只做一个主路径——发布到 PyPI，主推 `uvx acm`（零安装试用）与 `uv tool install acm`（全局安装）。pip/pipx 随 PyPI 发布免费获得，零成本顺带支持。**

**否决"全通道分发矩阵进 MVP"的建议（建议文档 V1-一.2 / V3-一.1），理由：**

1. 目标用户（装着多个 coding agent 的开发者）机器上 Python + uv 几乎必然存在，单二进制是锦上添花而非刚需。
2. Homebrew Tap 与 pyapp 打包各自需要持续的 CI 维护成本，在没有任何真实用户反馈之前建设它们是典型的"为想象中的用户做功能"。
3. 触发式后置（写进路线图 P3 的准入条件）：出现真实的非 Python 环境需求 → 上 pyapp；出现明确的 macOS/Linux 用户获取习惯需求 → 上 brew tap。

### D6：MVP 首批适配器 = Claude Code + Codex + Pi（真实使用优先原则）

**结论：P0 = Claude Code、Codex、Pi；Aider 作为 P1 首位（架构压力测试）；OpenClaw/Hermes 随后。**

**裁决过程**（此点在建议文档中自相矛盾：V1-三.1 主张换成 Claude Code+OpenClaw+Aider，V3-一.3 主张保持 Codex+Pi）：

1. **第一性原则：MVP 首先要服务真实用户（我们自己）**。本机实证（附录 B）：实际在用的 Agent 是 Claude Code、Codex、Pi、Gemini CLI、OpenCode；**Aider 与 OpenClaw 并未实际使用**。第一动因是"把 VMR 一键接进我们在用的 Agent"——为验证架构而把没人用的 Agent 塞进 MVP，是本末倒置。
2. **V1 的合理内核（架构覆盖充分性）必须吸收**——但换一种满足方式。检验 P0 三件套的架构覆盖矩阵：

   | 架构能力 | 由谁验证 |
   |---|---|
   | JSON + env 块注入 + 大量非管字段保护 | Claude Code（`settings.json` 与 `~/.claude.json` 状态文件的边界） |
   | TOML round-trip + **双文件事务**（`config.toml` + `auth.json`） | Codex（本机实证：用户 config.toml 含大量带注释的 `mcp_servers` 表，tomlkit round-trip 是刚需） |
   | Provider/Model **注册式**投影 + api 方言映射（`openai-completions` / `anthropic-messages`）+ compat 能力位 + thinking level 映射 | Pi（其 schema 与 Core Config 概念同构度最高） |
   | YAML round-trip + 角色模型（main/weak/editor）+ 元数据文件派生 | **Aider（P1 首位，作为架构压力测试）**；ruamel round-trip 能力本身在 P1 就以 Helper 级金样单测覆盖，不依赖适配器存在 |

3. 结论：P0 三件套已覆盖 JSON/TOML 双格式、单/多文件、覆盖式/注册式两种投影形态、env 注入与方言映射；唯一的未覆盖项（YAML + 角色模型）由 P1 首位的 Aider 承担，且其 Helper 级能力提前在 MVP 内以单元测试锁定。**MVP 的架构验证充分性不受损，同时不做无用功。**

### D7：动态适配器热加载 = 架构预留，P2 落地

**结论：MVP 不实现 `~/.acm/adapters/*.py` 热加载，但 Adapter Protocol（§7.4）从一开始就按"用户模块可实现"设计（纯 Python Protocol、无内部 API 依赖）。P2 交付 importlib 加载器 + 协议文档 + 模板。**

理由：先回答"官方适配器能否稳定、安全地完成投影"，再回答"第三方能否自己写适配器"。顺序颠倒会拖慢第一版且分散验证焦点。

---

## 7. 架构设计

### 7.1 八层核心流水线（本架构的脊柱）

```
Core Config / SSOT          # ACM 认为模型世界是什么
        ↓
Profile Resolution          # 解析出一份具体的、无环境引用的 ResolvedProfile
        ↓
Adapter（语义编译）          # 目标 Agent 怎么表达——产出 ChangeSet，不碰文件
        ↓
ChangeSet                   # 具体要改什么（文件、路径、旧值、新值）
        ↓
Ownership / Conflict Check  # ACM 有没有资格改（白名单/黑名单/漂移检测）
        ↓
Format-specific Writer      # 怎么安全地改（round-trip 编辑器）
        ↓
Atomic Write                # temp + os.replace
        ↓
Journal / Snapshot          # 怎么追踪和恢复（清单 + 审计 + 兜底）
```

**强制约束**：Adapter 只做"编译"（profile → ChangeSet），**一切磁盘写入由 Safety Engine 统一执行**。适配器物理上无法绕过安全语义（white-box 代码审查 + 框架层唯一写入口）。

### 7.2 组件图

```
┌─────────────────────────────────────────────────────────────┐
│                        acm CLI（typer + rich）                │
│  init/use/apply/status/diff/history/rollback/release/        │
│  doctor/import                                             │
├─────────────────────────────────────────────────────────────┤
│                      Core（纯逻辑，无 I/O）                    │
│  CoreConfig 加载校验 · Profile 解析 · ChangeSet 计算 · 幂等判断 │
├──────────────────────────┬──────────────────────────────────┤
│      Safety Engine       │          Adapter Layer           │
│  三阶段提交 · 管理清单      │   Adapter Protocol（detect/       │
│  黑白名单校验 · 冲突检测     │   config_paths/plan/verify）      │
│  快照 + 保留策略 · 原子写    ├──────────────────────────────────┤
│  进程检测 · 字段级回滚       │   内置适配器（每 Agent 一个模块）    │
│                          │   claude_code·codex·pi·...        │
│                          │   用户适配器 ~/.acm/adapters/*.py   │
│                          │   （P2：importlib 动态加载）         │
├──────────────────────────┴──────────────────────────────────┤
│                    Format Helpers（共用库）                    │
│  JSON 保序编辑 · ruamel round-trip · tomlkit · .env 行编辑    │
│  路径解析（XDG/macOS/Win） · ${ENV} 引用解析                   │
└─────────────────────────────────────────────────────────────┘
```

### 7.3 Core Config Schema（`~/.acm/config.toml`）

```toml
version = 1

# ── L1 供应商：端点与凭据 ──────────────────────────────
[providers.vmr]
protocol    = "openai"                  # openai | anthropic | openai-responses
base_url    = "http://127.0.0.1:8800/v1"
api_key     = "${VMR_KEY}"              # env 引用优先；${VAR:-default} 支持默认值
# api_key    = "sk-..."                  # 明文存储需显式 opt-in 并警告（acm doctor 检测）
# headers    = { x-org-id = "..." }      # 自定义 headers
# proxy      = "http://127.0.0.1:7890"

[providers.anthropic-official]
protocol    = "anthropic"
base_url    = "https://api.anthropic.com"
api_key     = "${ANTHROPIC_API_KEY}"

[providers.deepseek]
protocol    = "openai"
base_url    = "https://api.deepseek.com/v1"
api_key     = "${DEEPSEEK_API_KEY}"

# ── L2 模型：规格、行为与能力 ──────────────────────────
[models.coding]
provider           = "vmr"
id                 = "coding"           # 实际请求的 model id / VMR 虚拟模型名
display_name       = "VMR Coding"
context_window     = 131072
max_output_tokens  = 16384
temperature        = 0.2                # 缺省 = 不写入，用 Agent 默认
capabilities       = { vision = false, tools = "native", json_mode = true }

[models.coding.reasoning]
effort       = "high"                   # low | medium | high；适配器负责换算为各家表达
budget_tokens = 16000                   # 仅 anthropic 系模型需要时映射

[models.cheap]
provider           = "vmr"
id                 = "cheap"
context_window     = 131072
max_output_tokens  = 8192
capabilities       = { vision = false, tools = "native" }

# ── L3 Profile：命名的角色组合 ─────────────────────────
[profiles.daily]
main  = "coding"
cheap = "cheap"                          # 角色模型：仅支持多模型的 Agent 会消费此槽位

[profiles.budget]
main  = "cheap"

[profiles.claude-official]
main  = "claude-official-sonnet"
```

- **激活态存放于 `~/.acm/state/active`**（仅 profile 名），不写入 config.toml——config 是模型世界的事实源，"当前选了谁"是可变状态，只能通过 `acm use` 改变。
- Pi 类注册式 Agent 会消费完整 models 定义；覆盖式 Agent（如 Claude Code）只消费被 profile 引用的模型。

### 7.4 Adapter 契约（Python Protocol）

```python
class Adapter(Protocol):
    agent_id: str            # "claude_code"
    display_name: str        # "Claude Code"

    def detect(self) -> bool: ...
        # 本机是否安装该 Agent（可执行文件/配置目录探测）

    def config_paths(self) -> list[Path]: ...
        # 声明本适配器管理的所有文件路径——Safety Engine 据此统一做快照，
        # 适配器不重复实现快照逻辑

    def plan(self, profile: ResolvedProfile) -> ChangeSet: ...
        # 纯函数：产出字段级变更集。值转换/方言适配/多文件协同全部在这里，
        # 用普通代码写。绝不直接写文件。

    def verify(self, cs: ChangeSet) -> Report: ...
        # 落盘后断言：目标字段已正确写入、保护区域未变
```

**ChangeSet 结构**（Safety Engine 的输入）：

```python
@dataclass
class FieldOp:
    file: Path
    path: str              # 格式专属路径记法，如 "env.ANTHROPIC_BASE_URL"
    old: object | None     # 探测到的当前值（含"不存在"哨兵）
    new: object
    created: bool          # 该路径是否为本次新建

@dataclass
class ChangeSet:
    agent_id: str
    profile: str
    ops: list[FieldOp]
    protected_paths: list[str]   # 适配器声明的禁止触碰路径（黑名单）
    managed_namespaces: list[str] # 适配器声明的合法写入命名空间（白名单）
```

新增一个官方 Agent = 新增约 100–300 行模块 + 一组金样 fixtures（§11）。

### 7.5 Safety Engine（核心安全机制汇总）

#### 7.5.1 三阶段事务提交（所有写入的唯一通道）

```
[阶段 1 · Prepare & Snapshot]
  1. 进程守护：检测目标 Agent 活跃进程 → 默认阻断，--force 覆盖（§7.5.5）
  2. 逐文件读取原始字节，计算 SHA-256
  3. 保存文件快照至 ~/.acm/state/<agent>/snapshots/<ts>/
  4. 追加 Journal Entry（时间、profile、ChangeSet、来源命令）
  5. 黑白名单校验：
     - 白名单：每个 op.path ∈ managed_namespaces
     - 黑名单：每个 op.path ∉ protected_paths
     - 双重防线，任一违反即中止

[阶段 2 · In-Memory Mutate & Verify]
  1. round-trip 解析（ruamel / tomlkit / 保序 JSON 编辑器）
  2. 仅对 op.path 赋值，内存中完成全部变更（含多文件）
  3. 语法自检：修改后文本可再次无损解析
  4. 非管字段零篡改断言：解析树 diff 确认除 op.path 外结构不变；
     YAML/TOML 额外断言注释区间字节不变

[阶段 3 · Atomic Commit]
  1. 逐文件写临时文件 <target>.acm_tmp → os.replace 原子替换
  2. 多文件按序提交；任一失败 → 立即用内存中的原始字节回滚已提交文件，
     中止后续（跨文件事务一致性）
  3. 成功后更新管理清单 manifest.json（每个 op.path 的写入值）与 Journal 状态
```

#### 7.5.2 管理字段清单（Managed Manifest）

`~/.acm/state/<agent>/manifest.json`：记录 ACM 写过的每个（file, path）及最后一次写入值。三个用途：

1. **字段级回滚**（默认）：按清单恢复旧值，Agent 在此期间写入的其他状态完好无损。
2. **漂移检测（Conflict Detection）**：apply/diff/status 时，若某管理路径的当前磁盘值 ≠ 清单记录值，说明 Agent 或用户改过它——**绝不静默覆盖**，标记 drift 并要求 `--force` 或先 `acm diff` 确认。
3. **`acm release` 的精确语义**：按清单移除所有 ACM 注入的配置（ACM 新建的路径直接删除，改写过的路径恢复 pre-ACM 旧值），清空清单，快照可选保留——让用户可以无残留退坑，这是信任的基础。

#### 7.5.3 文件快照（Safety Net，非默认回滚机制）

- 位置：`~/.acm/state/<agent>/snapshots/<ts>/`；**保留策略：每 Agent 默认保留最近 20 份，FIFO 自动清理，数量可配置**。
- 用途：`--hard` 灾难恢复（文件被写坏）、审计。
- 正常操作不依赖整文件恢复。

#### 7.5.4 非破坏性保证等级（按格式诚实定义，不笼统承诺"无损"）

| 格式 | 保证等级 |
|---|---|
| YAML（ruamel round-trip） | 注释、缩进、空行、键序 100% 保留；未管理节点结构级不变 |
| TOML（tomlkit） | 注释、缩进、键序、表序 100% 保留；未管理表零触碰 |
| JSON / JSONC | **语义级 + 排版级**：键序不变、缩进风格自动探测匹配（2/4 空格/Tab）、末尾换行风格保留；带注释的 JSONC（如 opencode.json）用注释保留解析器 |
| .env（如需） | 仅整行替换/追加，其余行字节不动 |

明确否决的主张："RFC 6902 JSON Patch = 非破坏性"。JSON Patch 若经 `json.dumps` 重序列化落盘，照样摧毁排版与键序。正确路径是 **ChangeSet + 格式专属 round-trip 编辑器**，RFC 6902 至多作为 ChangeSet 的内部表示，不作为写入机制。

#### 7.5.5 进程守护

- 写入前检测目标 Agent 活跃进程（标准库 `pgrep` / Windows `tasklist`，不引入 psutil）。
- 检测到活跃进程：默认阻断并提示标准文案：
  `⚠️ Process 'claude' (PID 43210) is running. Writing now may be overwritten on exit. Use --force to proceed.`
- 已核实的缓解事实：Claude Code 官方 FAQ 称其支持 provider 切换热生效（无需重启）——该 Agent 的守护等级可放宽为警告；其余 Agent 默认阻断。

#### 7.5.6 幂等性

重复 `acm use <同一 profile>`：ChangeSet 与清单比对后为空 → no-op，退出码 0，不产生新快照。

### 7.6 目录布局

```
~/.acm/
├── config.toml                 # Core Config（SSOT；用户可 git 管理自己的版本）
├── adapters/                   # 用户自定义适配器（P2 启用动态加载，目录先预留）
├── state/
│   ├── active                  # 当前激活 profile 名（仅 acm use 可改）
│   └── <agent>/
│       ├── manifest.json       # 管理字段清单（字段级回滚 + 漂移检测 + release）
│       ├── journal.jsonl       # 审计日志（append-only）
│       └── snapshots/<ts>/     # 文件快照（兜底，FIFO × 20）
└── logs/
```

---

## 8. Agent 适配矩阵

> 标注 ✔ 的为已核实事实（本机实证或官方文档，附录 B）；其余以实现时金样校准为准。本矩阵是**活文档资产**，随适配器开发持续充实（含"哪些字段无法表达、哪些需转换"），是适配器质量的核心资产。

### P0（Phase 1）

| Agent | 目标文件 | 格式 | ACM 写入字段 | 保护字段（黑名单，绝不触碰） | 架构验证点 |
|---|---|---|---|---|---|
| **Claude Code** | `~/.claude/settings.json` ✔ | JSON | `env.ANTHROPIC_BASE_URL`、`env.ANTHROPIC_AUTH_TOKEN`（或 `ANTHROPIC_API_KEY`）、`model`、reasoning → `effortLevel` 类字段 ✔ | `permissions`、`hooks`、`enabledPlugins`、`statusLine`、`tui` 等一切非模型字段；**绝不碰 `~/.claude.json`（运行时状态）** ✔ | env 块注入 + 高密度非管字段保护；FAQ 证实可热切换 ✔ |
| **Codex** | `~/.codex/config.toml` ✔ + `~/.codex/auth.json` ✔ | TOML + JSON | 顶层 `model`、`model_reasoning_effort` ✔、`model_providers.<id>` 表（base_url/wire_api/env_key）、auth.json 对应 key | `mcp_servers`（本机实证含大量带注释条目 ✔）、`features`、`memories`、`tui`、`notify`、`sandbox` | tomlkit round-trip（用户注释密集 ✔）+ **双文件事务** |
| **Pi** | `~/.pi/agent/models.json`（用户自定义文件，官方文档 ✔；不存在则创建）+ `~/.pi/agent/settings.json` ✔ | JSON | models.json：`providers.<name>`（baseUrl / api 方言 ✔ / apiKey / models[]：id、contextWindow、maxTokens、compat 能力位、thinkingLevelMap ✔）；settings.json：`defaultProvider`、`defaultModel`、`defaultThinkingLevel` ✔ | **`models-store.json`（pi 内部注册表，绝不写入）** ✔、`trust.json`、`auth.json`、extensions/skills 目录 | 注册式投影 + api 方言（`openai-completions`/`anthropic-messages` ✔）+ compat/thinking level 映射，与 Core Config 同构度最高 |

### P1（Phase 2）

| Agent | 目标文件 | 格式 | 要点 |
|---|---|---|---|
| **Aider**（架构压力测试） | `~/.aider.conf.yml` + `~/.aider.model.metadata.json` | YAML + JSON | 角色模型（main/weak/editor）；YAML 改动联动派生 JSON 元数据（max_input_tokens / edit_format）——ruamel round-trip + 跨文件派生逻辑的最难用例 |
| **Gemini CLI** | `~/.gemini/settings.json` 等 | JSON | env 块 + 模型选择；路径细节金样校准 |
| **OpenCode** | `~/.config/opencode/opencode.json` ✔（本机存在） | JSONC | provider/model 配置；注释保留解析器 |

### P2（Phase 3 / 社区）

| Agent | 说明 |
|---|---|
| OpenClaw、Hermes | 全局 + per-agent 两级配置，注意保护 `subagents` 架构 |
| Cursor / Cline / Roo Code | **仅公开 settings.json 通道**；`state.vscdb` 等私有数据库绝不写入（铁律 2） |
| 长尾 Agent | 用户适配器 `~/.acm/adapters/*.py`（P2 热加载） |

---

## 9. VMR 协同

**定位：VMR 是第一方集成，不是架构依赖。ACM 因 VMR 而诞生，但脱离 VMR 仍然是完整产品。**

```
$ acm init                  # 扫描本机 Agent + 探测 VMR（127.0.0.1:8800/healthz，
                            #   fallback 读取 ~/.vmr/ 配置）；在运行则自动 import
$ acm import vmr            # 拉取虚拟模型列表 → 生成 providers.vmr + models.*（增量合并进 config.toml）
$ acm use daily --all       # 投影到本机所有已检测到的 Agent
$ acm status                # 总览：各 Agent 当前指向 / 漂移状态
```

- **零依赖原则**：无 VMR 时一切功能照常（直连 OpenRouter / DeepSeek / SiliconFlow / Ollama / 任意兼容端点）。
- **VMR 侧零改动**：只需暴露标准的模型列表查询端点；ACM 对 VMR 的全部"感知"就是一次 import。
- **退出对等**：`acm release` 一键解除所有 Agent 与 VMR 的绑定，零残留。
- `acm use-vmr <virtual_model>`（P2 薄糖层 = import-if-needed + 选 profile + `use --all`）与 `acm vmr status`（P2）仅在真实使用中出现重复按键痛点后再做——MVP 的 `init → use` 两步已满足"≤3 条命令"成功标准。

---

## 10. CLI 命令规格

```bash
# ── 初始化与状态 ────────────────────────────────────────
acm init [--dry-run]        # 扫描已安装 Agent；探测 VMR（在运行则自动 import）；
                            # 无 VMR 时 fallback：选择预设 Provider / 手动输入 endpoint；
                            # 生成 ~/.acm/config.toml 与默认 profile
acm status [--verbose]      # 各 Agent：当前指向的 profile / 漂移 / 上次操作时间
acm doctor                  # 诊断：配置语法、文件权限、${ENV} 引用缺失、
                            # 管理路径漂移、进程冲突、明文密钥告警 + 修复建议

# ── 核心操作 ───────────────────────────────────────────
acm use <profile> [--agent <id|all>] [--dry-run] [--force]
                            # 切换激活 profile 并投影（默认所有已检测 Agent）
acm apply [--agent <id|all>] [--dry-run]
                            # 重新对齐当前激活 profile（幂等；修复漂移）

# ── 安全与审计 ─────────────────────────────────────────
acm diff [<agent>] [--against snapshot|profile]
                            # 彩色 unified diff：磁盘 vs 上次快照，或磁盘 vs 期望态
acm history [<agent>]       # 变更时间线：快照哈希、来源 profile、命令
acm rollback [<agent>] [--to <snapshot-id>] [--hard] [--force]
                            # 默认字段级回滚（保留 Agent 新写状态）；
                            # --hard 才整文件快照还原（灾难恢复）
acm release [<agent>] [--force]
                            # 按管理清单移除 ACM 注入的一切，恢复 pre-ACM 状态

# ── VMR ────────────────────────────────────────────────
acm import vmr [--url <url>] [--dry-run]
acm vmr status              # P2
acm use-vmr [<model>]       # P2 薄糖层

# ── Profile 管理 ───────────────────────────────────────
acm profile list | show <name>          # P1
acm profile create <name>               # P2（交互式/模板）

# ── 全局选项 ───────────────────────────────────────────
--dry-run                   # 只计算 ChangeSet 并展示，不写任何文件
--force                     # 覆盖进程守护/漂移阻断
--verbose                   # 详细操作日志
--no-color                  # 输出管道友好
--json                      # P2：机器可读输出（脚本嵌入场景）
```

**标准交互文案**（一致性约定）：

- 进程冲突：`⚠️ Process '<name>' (PID <pid>) is running. Writing now may be overwritten on exit. Use --force to proceed.`
- 漂移检测：`⚠️ Drift detected on <agent>: managed field '<path>' was changed externally (expected '<x>', found '<y>'). Run 'acm diff <agent>' or use --force.`

---

## 11. 测试与质量保障

### 11.1 金样回归测试（Golden File Suite）——适配器开发的基础设施，不是后期测试

每个适配器配套**真实感 fixtures**：带手写注释、带 MCP 配置、带私有字段、带格式怪癖的配置样本（本机实证样本脱敏后入库，如 Codex 的注释密集 config.toml ✔）。

**三步断言闭环**：

1. **Apply**：目标模型字段精确修改（语义断言）。
2. **Non-destructive**：非管字段、注释、键序、缩进**字节级/结构级原样保留**（按 §7.5.4 的格式保证等级分别断言）。
3. **Rollback**：字段级回滚后，管理字段恢复旧值；在 apply 与 rollback 之间**模拟 Agent 写入状态**后，该状态仍存活；`--hard` 回滚后文件 SHA-256 与原样本完全一致。

### 11.2 Schema 漂移检测

- 金样 fixtures 同时充当上游 schema 的哨兵：Agent 升级后，CI 中跑全量金样回归即可发现字段布局变化。
- `acm doctor` 在用户侧主动检测落盘异常（管理路径读不到期望结构 = 上游漂移信号）。

### 11.3 CI 策略

- 每适配器独立测试目录（漂移不跨 Agent 传染）；
- Helper 级 round-trip 单测（JSON/YAML/TOML/.env）先于任何适配器交付；
- 安全引擎的事务测试：注入写入失败，断言跨文件回滚完整性。

---

## 12. 实施路线图与验收标准

### Phase 1：MVP（目标 ~1–2 周）

**交付**：

- Core / Safety Engine / Format Helpers / Adapter Protocol 完整框架
- P0 适配器：**Claude Code、Codex、Pi**
- 全命令：`init / use / apply / status / diff / history / rollback / release / doctor / import vmr`
- 三阶段提交、管理清单、漂移检测、进程守护、快照保留策略
- Helper 级 + 适配器级金样测试（含 YAML round-trip 单测前置锁定）
- PyPI 发布（uvx / uv tool install / pipx 可用）

**硬验收标准（全部可量化）**：

1. 全新机器 VMR 场景：`acm init` → `acm use daily --all` 后，3 个 P0 Agent 全部正确指向 VMR 虚拟模型；全程 ≤ 3 条命令、零手工编辑。
2. `acm rollback` 后：管理字段恢复旧值；apply 与 rollback 之间模拟的 Agent 状态写入**存活**。
3. 金样三步断言全绿：包括"回滚（--hard）后 SHA-256 与原样本一致"。
4. 幂等：连续两次相同 `acm use` 第二次为 no-op。
5. 黑白名单断言：任何 op 触碰 `mcpServers` / `permissions` / `hooks` / `enabledPlugins` / `models-store.json` 即测试失败。
6. `acm release` 后：三 Agent 配置与 pre-ACM 状态一致，清单清空，零残留。

### Phase 2：生态扩展（目标 +1–2 周）

- 适配器：**Aider（架构压力测试）**、Gemini CLI、OpenCode
- 角色模型映射（main/weak/editor；primary/cheap）
- `acm profile list/show`、`acm use-vmr`、`acm vmr status`
- 动态适配器热加载（`~/.acm/adapters/*.py` + importlib）+ 协议文档 + 模板
- `--json` 机器可读输出
- CI 全量金样回归 + 适配矩阵活文档充实（无法表达/需转换字段清单）

### Phase 3：分发与社区（持续，触发式）

- Homebrew Tap（准入：出现明确的 macOS/Linux brew 习惯用户需求）
- pyapp 单二进制（准入：出现真实的非 Python 环境需求）
- 社区适配器贡献流程（fixtures 规范 + PR 模板 + 铁律检查清单）
- OpenClaw / Hermes；Cursor/Cline 仅公开 settings 通道评估

---

## 13. 风险与对策

| 风险 | 概率 | 影响 | 对策 |
|---|---|---|---|
| 上游 Agent schema 漂移 | 高频 | 小（模型字段是稳定子集） | 适配器隔离（不跨 Agent 传染）+ 金样哨兵 + AI 辅助改适配器（贴官方文档）+ `acm doctor` 主动检测 |
| cc-switch 补齐 CLI 与深度参数建模 | 中 | 中 | 不正面竞争；护城河是哲学（最小/专注/文件级尊重）与 VMR 原生协同，非功能清单 |
| Agent 运行中写文件覆盖 ACM 变更 | 低 | 中 | 进程守护默认阻断 + 清单漂移检测 + 快照兜底 |
| VSCode 系扩展迁移到 SQLite 私有存储 | 中 | 高（仅 P2 Agent） | 铁律 2：没有干净通道就不支持，绝不写私有 DB |
| 密钥安全 | 中 | 中 | 默认 `${ENV}` 引用；明文需显式 opt-in 且 doctor 告警；keychain 集成为后续可选项 |
| 多文件事务部分失败 | 低 | 中 | 跨文件按序提交 + 内存原始字节回滚已提交项（§7.5.1 阶段 3）+ 金样事务测试 |
| 单人项目维护连续性 | 中 | 高 | 代码量与 scope 严格受控（宁可不做，不做大）；退出条件成文（§4.2）；本文档为唯一权威持续演进 |

---

## 14. 成功标准

**对内（第一优先）**：VMR 用户从"装好 VMR"到"本机 3+ 个 Agent 全部指向 VMR 虚拟模型"，全程 ≤ 3 条命令、≤ 1 分钟、零手工编辑配置文件、`acm release` 后零残留。

**对外（第二优先）**：一个不使用 VMR 的多 Agent 开发者，愿意把 ACM 纳入日常工具链的理由是——**"它只做模型配置这一件事，我从不必担心它弄坏我的配置文件，且它可以被脚本化嵌入任何工作流。"**

前者不达成则项目失去第一动因；后者不达成则项目退化为内部脚本。两条都成立，ACM 才值得作为独立开源仓库长期存在。

---
---

## 附录 A：建议文档逐项裁决记录

> 《基于GLM版的ACM方案完善建议》V1/V2/V3 存在内部矛盾，下表为逐项独立裁决。裁决依据：第一性原理 + 事实核查（附录 B）+ 本机实证。

### A.1 建议文档内部四大矛盾的裁决

| 矛盾点 | V1 立场 | V2/V3 立场 | 裁决 | 关键依据 |
|---|---|---|---|---|
| MVP 首批适配器 | Claude Code + OpenClaw + Aider | Claude Code + Codex + Pi | **P0 = Claude Code + Codex + Pi；Aider 升为 P1 首位（压力测试）** | 本机实证：Aider/OpenClaw 未实际使用，第一动因是服务真实场景；架构覆盖缺口（YAML/角色模型/跨文件派生）由 P1 首位 Aider + Helper 级前置单测补齐（§6.6） |
| Core Config 格式 | TOML → YAML | 保持 TOML | **保持 TOML** | 双向读写场景 TOML 无歧义性更优；实际嵌套仅 3 层；Codex P0 使 tomlkit 零新增依赖；与 Agent 端 YAML 文件天然区分（§6 D3） |
| 分发渠道 | 全通道矩阵（uvx+brew+pyapp+pipx） | 压缩为主路径 | **单一主路径（PyPI + uvx/uv tool），brew/pyapp 触发式后置 P3** | 为想象中的用户建设 CI 渠道是浪费；pip/pipx 随 PyPI 免费获得（§6 D5） |
| 动态适配器热加载 | 尽早交付 | 推迟出 MVP | **架构预留、P2 落地** | 先验证官方适配器质量，再开放第三方扩展（§6 D7） |

### A.2 V1 逐项裁决（新增补全类）

| # | 建议 | 裁决 | 说明 |
|---|---|---|---|
| 一.1 | 动态适配器热加载 | **推迟（P2）** | 见 A.1；协议层从第一天按可外部实现设计 |
| 一.2 | 全通道分发矩阵 | **拒绝进 MVP / 触发式后置** | 见 A.1 |
| 一.3 | protected_paths 黑名单 | **采纳** | 与白名单构成双重防线，进 ChangeSet 结构与阶段 1 校验（§7.4/7.5.1） |
| 一.4 | 快照保留策略（20/Agent FIFO 可配置） | **采纳** | §7.5.3 |
| 一.5 | 三阶段事务提交标准化 | **采纳** | 统一为 §7.5.1，含跨文件失败回滚 |
| 一.6 | `acm doctor` | **采纳（P1）** | §10，扩展了明文密钥与漂移检测 |
| 一.7 | `acm history` + `rollback --to/--hard` | **采纳** | §10；默认仍为字段级回滚 |
| 一.8 | 金样回归测试三步断言 | **采纳（强化）** | §11.1，第三步增加"模拟 Agent 写入状态后仍存活"断言 |
| 一.9 | 进程守护交互（默认阻断 + --force） | **采纳（调整）** | 用标准库 pgrep/tasklist，不引入 psutil；Claude Code 依据官方 FAQ 热切换事实放宽为警告 |
| 一.10 | 适配优先级矩阵 + 量化验收 | **采纳** | §8/§12，验收标准全部量化 |
| 二.1 | Schema 表达能力升级（protocol 枚举/headers/proxy/能力位/env 默认值） | **采纳** | §7.3；`active_profile` 改存 state（配置与状态分离） |
| 二.2 | Core Config 改 YAML | **拒绝** | 见 A.1 |
| 二.3 | 适配器契约标准化（agent_id/display_name/config_paths/diff 统一渲染） | **采纳** | §7.4；diff 由 CLI 层统一渲染，适配器只产出 ChangeSet |
| 二.4 | VMR 快捷指令（use-vmr/vmr status/探测 fallback） | **采纳（P2）** | §9；MVP 的 init→use 已满足成功标准 |
| 二.5 | 多文件事务原子性 | **采纳** | §7.5.1 阶段 3 + §11.3 事务测试 |
| 二.6 | Diff 输出 rich 高亮 | **采纳（成本近零）** | rich 本就是依赖 |
| 三.1 | MVP 换 OpenClaw+Aider | **拒绝（吸收其内核）** | 见 A.1——架构覆盖关切以 P1 压力测试 + 前置单测满足 |
| 三.2 | TOML→YAML | **拒绝** | 见 A.1 |
| 三.3 | Scope 刚性约束成铁律 | **采纳** | §5.4 四条铁律，写入 CONTRIBUTING/PR 模板 |
| 三.4 | 明确退出/降级条件 | **采纳** | §4.2 |

### A.3 V2 逐项裁决

| # | 建议 | 裁决 | 说明 |
|---|---|---|---|
| 1 | 保留三层 Core Config 并明确职责边界 | **采纳** | §7.3 providers/models/profiles 各层职责显式注释 |
| 2 | Field Ownership 提升为核心架构原则 | **采纳（升级为全文纲领取向）** | §1 "管理字段而非文件" + §7.1 流水线独立层 |
| 3 | 字段级回滚 + 冲突检测（不静默覆盖） | **采纳** | §7.5.2 漂移检测 |
| 4 | Adapter 只产出 ChangeSet，写入归 Safety Engine | **采纳（强制约束）** | §7.1 |
| 5 | 吸收 Gemini 适配映射矩阵为正式基准 | **采纳** | §8 升级为带核实标记的活文档 |
| 6 | Agent Capability/Config Matrix（含"无法表达/需转换"） | **采纳（P2 充实）** | §8 |
| 7 | 金样体系为基础设施 | **采纳** | §11.1 |
| 8 | doctor/diff/dry-run 为一等公民 | **采纳** | §10 |
| 9 | VMR Discovery/Import | **采纳** | §9 |
| 10 | VMR 是第一方集成非架构依赖 | **采纳（原文固化）** | §9 开篇 |
| 11 | 动态适配器后置 | **采纳** | D7 |
| 12 | MVP 克制、做深少数 Agent | **采纳** | §12 |
| 13 | 弃用"市场空白"表述 | **采纳（GLM 原已如此）** | §3.2 |
| 14 | 不以 Agent 数量/GUI 竞争 | **采纳** | §4.1 |
| 15 | 非破坏性分级定义 | **采纳** | §7.5.4 |
| 16 | 否定 RFC 6902 即无损 | **采纳** | §7.5.4 末段 |
| 17 | VSCode 私有 DB 不碰 | **采纳（铁律化）** | §5.4 |
| 18 | 快照降级为 Safety Net | **采纳（GLM 原方案即如此，进一步明确三层）** | D4 |
| 19 | 压缩分发方案 | **采纳** | D5 |
| 20 | 不做 GUI/TUI | **采纳** | §5.3 |
| 21 | 动态适配器不进 MVP | **采纳** | D7 |
| 22 | 不扩展 MCP/Skills/Prompt | **采纳（铁律化）** | §5.4 |
| 23 | 不为 Adapter 数量过早建插件生态 | **采纳** | D7/§12 |
| 五 | 八层核心流水线 | **采纳（作为架构脊柱）** | §7.1 |
| 末 | 六件最值得做的事 | **全部覆盖** | Field Ownership/D4、ChangeSet/§7.4、映射矩阵/§8、金样+漂移检测/§11、VMR Import/§9、安全型 CLI/§10 |
| 末 | 六件最应删除的 | **全部执行** | 整文件回滚默认✘、私有 DB✘、多渠道✘、GUI✘、Scope 膨胀✘、"市场空白"✘ |

### A.4 V3 逐项裁决（仅列与上文不同或有新增信息者）

| # | 建议 | 裁决 | 说明 |
|---|---|---|---|
| 一.1 | 多通道分发"必须补上" | **拒绝其优先级**（同 A.1） | uvx 主路径进 MVP，其余触发式 |
| 一.2 | 完整 CLI 命令规格与标准警告文案 | **采纳** | §10 全量落地 |
| 一.3 | P0 保持 Claude Code+Codex+Pi | **采纳（与本方案独立判断一致）** | §6.6 补齐了它未给出的架构覆盖论证 |
| 一.4 | Phase 1 硬验收 + 金样细化 | **采纳** | §12 |
| 一.5 | 分层架构图 + "Adapter 只产出 ChangeSet"强制约束 | **采纳** | §7.1/7.2 |
| 一.6 | `acm init` 自动化流程（含 fallback） | **采纳** | §10/§9 |
| 二.1 | 三阶段伪代码/多文件策略/快照保留/release 语义 | **采纳** | §7.5 |
| 二.2 | Schema 补全 + `${ENV}` 优先 + active_profile | **采纳（一处修正）** | active_profile 存 state 而非 config（配置/状态分离，见 A.2 二.1） |
| 三.2 | Python 3.11+、依赖 ≤4、锁定 uv | **采纳** | D2 |
| 三.5 | "过细的实现伪代码不要" | **部分不采纳** | 三阶段提交与 ChangeSet 结构保留至伪代码/接口级——它们是安全语义的规范组成部分，非实现细节 |

### A.5 从 Gemini/Sonnet 版直接吸收（未出现在建议文档或需要修正后吸收）

| 来源 | 内容 | 裁决 | 说明 |
|---|---|---|---|
| Gemini | "市场绝对空白"表述及具体 issue 编号 | **拒绝** | 附录 B：star 数据核实为真，但空白论被证伪；issue 编号不可考，改引官方 FAQ |
| Gemini | Claude Code 写 `~/.claude.json` | **拒绝（修正）** | 该文件为运行时状态，本机实证 ✔；只写 `~/.claude/settings.json` |
| Gemini/Sonnet | Pi 配置写 `~/.pi/agent/config.json` / `~/.pi/config.json` | **拒绝（修正）** | 官方文档：用户自定义文件为 `models.json`；`models-store.json` 为 pi 内部注册表绝不可写 ✔ |
| Sonnet | `python-json-patch`（RFC 6902）作为 JSON 非破坏写入 | **拒绝（修正）** | 见 §7.5.4；采纳其 protected_paths 概念 |
| Sonnet | Core Profile 内置 `core.yaml` 锚定 VRM | **部分吸收** | VMR 为默认初始 profile（init 自动生成），但不内置于包内——Core Config 属用户所有 |
| Sonnet | 每 Agent 快照 FIFO × 20 | **采纳** | §7.5.3 |
| Sonnet | Phase 验收标准 / P0-P1-P2 分层 / init 流程 | **采纳** | §12 |
| 三份共同 | 金样测试 | **采纳（强化）** | §11 |

---

## 附录 B：事实核查记录

核查时间：2026-08-17。方法：GitHub 仓库页实时抓取（firecrawl）+ 本机文件系统实证 + pi 官方文档。

| Claim | 来源 | 核查结果 |
|---|---|---|
| cc-switch 127.7k★ / 8.7k forks | GLM 版 | ✅ 属实（128k / 8.7k，GitHub 实时） |
| cc-switch 覆写破坏："切换后插件配置消失"，需手动配置 Shared Config Snippet 规避 | GLM 版 | ✅ **官方 FAQ 原文确认**（"My plugin configuration disappeared after switching providers"） |
| cc-switch issue #2992（Gemini 版）/ #3986（GLM 版） | 两版 | ⚠️ 不可考且互相矛盾，最终版不引用；以官方 FAQ 为准 |
| cc-switch Scope 膨胀（MCP/Prompts/Skills/会话管理/云同步/用量仪表盘） | 三版一致 | ✅ README Features 逐条证实 |
| cc-switch 内置本地代理（热切换/故障转移/熔断），与 VMR 同类竞争 | GLM 版 | ✅ README "Proxy & Failover" 节证实 |
| cc-switch GUI-first、CLI 薄弱 | GLM/Sonnet 版 | ✅ README 主打桌面应用/系统托盘/Deep Link；未见 CLI 支持 |
| cc-switch 中转商赞助墙运营 | GLM 版 | ✅ README 数十家 API 中转商赞助位 |
| Claude Code `~/.claude/settings.json` 含 `env` 块；`~/.claude.json` 为运行时状态 | GLM 版 | ✅ 本机实证（settings.json 键清单见核查底稿）；且实证存在 `effortLevel` 键 |
| Claude Code 支持 provider 热切换（无需重启） | — | ✅ cc-switch 官方 FAQ 提及（用于放宽该 Agent 的进程守护等级） |
| Codex 配置：顶层 `model` / `model_reasoning_effort`，`auth.json` 存 key，`mcp_servers` 表带注释 | 各版（细节不一） | ✅ 本机实证 `~/.codex/config.toml` + `auth.json`；注释密集的 mcp_servers 证实 tomlkit round-trip 刚需 |
| Pi 自定义 provider 文件为 `~/.pi/agent/models.json`；settings.json 含 `defaultProvider/defaultModel/defaultThinkingLevel`；`models-store.json` 为内部注册表 | GLM 版（部分） | ✅ pi 官方文档（models.md）+ 本机实证；models-store.json 的 provider 条目结构（api 方言/compat/thinkingLevelMap）已实证 |
| Aider / OpenClaw 在目标环境实际使用 | 各版（隐含假设） | ❌ 本机实证：仅有 `~/.aider-desk/skills`、`~/.openclaw/skills` 残留，非活跃使用——MVP 选型依据之一 |
| VMR（127.0.0.1:8800、虚拟模型、healthz） | 三版一致 | ⚪ 内部项目约定，视为设计输入而非外部事实 |
| "市场绝对空白" | Gemini 版 | ❌ 证伪（cc-switch 128k★ 占据 GUI 全家桶生态位）；准确表述为细分生态位为空（§3.2） |

---

<!-- 最终版规格结束。本文件为 ACM 项目唯一权威文档；如与任何前置文档冲突，以本文件为准。 -->
