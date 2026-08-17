# ACM（Agent Config Manager）最终版项目规格说明书

<!-- Version: 1.1.0 | Status: Implementation Reference（已被 v2.0 取代治理地位）| Date: 2026-08-17 -->
<!-- ⚠️ 角色变更（2026-08-17）：本文档已降级为**实现参考**（implementation reference）。
     治理性规格（原则、边界、数据模型、命令语义）见 docs/ACM_PROJECT_SPEC_v2.0.md。
     实现可偏离本文档的实现层细节（事务步骤、数据结构字段、状态机枚举、文案、目录布局等），
     前提是不违反 v2.0 的原则；偏离积累后回写更新本文档。两者冲突时以 v2.0 为准。 -->
<!-- 本文档在其作为治理规格期间取代以下前置文档（历史沿革，裁决记录见附录 A）：
     - ACM_PROJECT_INIT_glm5.3.md（骨架来源）
     - ACM_PROJECT_SPEC_sonnet4.6.md（MVP 克制与测试方法来源）
     - ACM_INITIALIZATION_SPEC_gemini3.7flash.md（适配器与工程细节来源）
     以及《基于GLM版的ACM方案完善建议》（V1/V2/V3，裁决记录见附录 A）。
     v1.1 变更：吸收 docs/feedback-for-v1.0.md 三轮反馈（逐项处理结果见该文档末尾），
     核心升级——回滚数据模型闭环（Manifest/Journal/Snapshot 三元职责）、
     crash-safe 事务与启动恢复、pre-commit 指纹校验、Desired State 形式化、
     Agent 状态机、投影损失告警、并发锁、密钥全链路防护、退出码规范、
     环境变量引用规则、非破坏性保证等级措辞修正。 -->

> **文档性质**：ACM 项目的实现参考（事务协议、数据结构、适配矩阵、历史裁决与核查记录）。
> **治理规格**：docs/ACM_PROJECT_SPEC_v2.0.md（原则、边界、数据模型、命令语义）。
> **生成方法**：以 GLM 版为骨架，对建议文档逐项裁决（附录 A），对 docs/feedback-for-v1.0.md 三轮反馈逐项评估吸收（处理记录见 feedback-for-v1.0.md 末尾），关键事实性 claim 全部溯源核实（附录 B），矛盾点按第一性原理独立裁决（§6）。

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
- [附录 A：前置文档逐项裁决记录](#附录-a前置文档逐项裁决记录)
- [附录 B：事实核查记录](#附录-b事实核查记录)
- [附录 C：核心术语表](#附录-c核心术语表)

---

## 1. 一句话定位

**ACM 是"模型配置"的单一事实源（SSOT）与投影引擎：用户在 ACM 中维护一套与 Agent 无关的 Provider/模型配置（Desired State 的源头），通过一条命令将其安全地投影到本机任意 Coding Agent 的配置文件中（Current State），并可精确、无损地回滚。**

它同时是 VMR（Virtual Model Router）的"最后一公里"：把 VMR 代理出的虚拟模型一键接入本机所有 Agent。但 ACM 不依赖 VMR 独立成立--直连任何 OpenAI/Anthropic 兼容端点同样是一等公民场景。

**核心架构原则（贯穿全文）**：ACM 管理的是**字段**，不是文件。所有 patch、diff、rollback 都围绕字段所有权（Field Ownership）设计；一切"ACM 不知道的事"（外部修改、无法表达的字段、并发与崩溃）都必须**显式暴露，绝不静默处理**。

---

## 2. 背景与问题定义

### 2.1 现实痛点（需求侧）

1. **多 Agent 并存已成常态**：开发者日常同时使用 Claude Code、Codex、Pi、Gemini CLI、OpenCode 等多个 Agent，每个 Agent 的配置位置、格式、语义各不相同（JSON / YAML / TOML / 环境变量 / VSCode 私有存储）。
2. **重复配置**：同一组 endpoint + key + 模型名，要在 N 个 Agent 里手工配 N 遍，改一次切一次，易错易漏。
3. **浅层配置不够**：生产级使用中，protocol 方言（openai / anthropic / openai-responses）、context window、max output tokens、reasoning effort/budget、vision/tool-call 能力位，配错任意一项都会导致运行期故障（404、上下文超限、输出截断、能力误判）。绝大多数切换工具只管 `base_url` + `api_key` + `model` 三个字段。
4. **切换工具不安全**：配置文件是**双向所有权**的--Agent 运行时也持续向其中写入状态（权限许可、插件启用记录、会话缓存、OAuth token）。任何"全量模板覆写"式工具都会周期性抹掉用户环境，且无可靠回滚。

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
| **cc-switch** (farion1231) | Tauri 桌面 GUI，**128k★ / 8.7k forks / 1.5k open issues** | Claude Code/Desktop、Codex、Gemini CLI、Grok Build、OpenCode、OpenClaw、Hermes（8 款） | SQLite SSOT，切换时由模板**再生并整体写入**目标配置 | 事实上的品类霸主。但：① **覆写破坏由官方 FAQ 亲自确认**--"切换后插件配置消失"，官方解法是让用户手动配置 "Shared Config Snippet"，属用补丁特征补偿架构缺陷；② Scope 严重膨胀：MCP/Prompts/Skills 统一管理、会话管理器、用量仪表盘、云同步、Deep Link；③ **内置本地代理网关**（热切换/故障转移/熔断），与 VMR 直接同类竞争，不可能为 VMR 做最优集成；④ GUI-first，README 主打桌面应用与系统托盘，CLI/headless 支持薄弱；⑤ 深度模型参数建模薄弱，以 provider 预设（url/key/model 三件套）为中心；⑥ README 含数十家 API 中转商赞助墙，运营方向是中转生态而非工具本身 |
| **claude-code-router** (musistudio) | Node.js 网关 + Web UI | 名义上多 Agent，实际为自身网关导流 | 子进程包装注入 ENV + Web 端覆写 | 配置能力与网关运行时强耦合，无法作为独立配置工具使用 |
| **ccc** (guyskk/claude-code-config-switcher) | Python CLI | 仅 Claude Code | 利用 `--settings` 启动参数注入，**完全不触碰磁盘文件** | 机制优雅（零破坏），但依赖 Claude Code 特有参数，无法泛化到其他 Agent |
| **ccp** (claude-code-profile) | Go CLI | 仅 Claude Code | `CLAUDE_CONFIG_DIR` + 软链 Hub | 解决 Profile 隔离，无参数转换、无跨 Agent 能力 |
| **claude-swap** | Python TUI | 仅 Claude Code 官方账号 | OAuth Token Slot 轮转 | 定位是账号额度轮转，与第三方模型配置正交 |

### 3.2 市场判断

- **"市场空白"的说法不成立**：cc-switch 以 128k★ 证明需求真实且巨大，且已覆盖 8 个 Agent。
- 但生态位分化清晰：cc-switch 走的是"GUI 全家桶 + 中转生态运营 + 内置网关"路线；**"CLI-first、模型配置专注、非破坏性、可编程、可嵌入脚本"** 这一生态位仍然为空--这正是 ccc（不破坏文件但单 Agent）与社区 CLI fork（CLI 但覆写架构）各自只占一半的原因。
- 需求侧结论：痛点真实、高频、且随多 Agent 使用强度单调上升。

---

## 4. 立项决策与退出条件

### 4.1 结论：**GO（做），但立项理由诚实声明边界**

**理由 1（第一动因）：解决自己的问题。** 我们的核心场景是 VMR 用户（包括我们自己）需要把本机多个 Agent 一键指向 VMR 虚拟模型。cc-switch 内置了自己的本地代理（与 VMR 同类竞争），不会为 VMR 做最优集成；这个工具必须掌握在自己手里。

**理由 2（生态位真实存在）**：见 §3.2--CLI-first × 模型专注 × 非破坏性 × 可编程，四个属性取交集，现存工具为零。"像 git/nvm 一样可信赖且可脚本化"的配置工具与"像控制面板一样的 GUI 全家桶"是不同产品，可以长期共存。

**理由 3（成本可控）**：Scope 严格限定在模型配置（§5），适配面是每个 Agent 的个位数文件、十几个字段，安全引擎（快照/原子写/管理清单/事务日志）是一次性框架成本。总工程量数千行，MVP 以天计。

**不以"超越/取代 cc-switch"为目标**：不拼 star 数、不做 GUI、不做 MCP/Skills/网关/用量统计、不拼 Agent 覆盖数量。ACM 的竞争维度只有五个词：**简单、可靠、可脚本化、非破坏性、模型配置 SSOT**。

### 4.2 明确的退出/降级条件（可执行）

| 触发条件 | 动作 |
|---|---|
| VMR 项目终止或方向变更 | ACM 降级为内部工具：停止新增功能，仅维护既有适配器；若社区活跃度足以独立支撑则继续，否则冻结 |
| 连续 6 个月无外部社区反馈且内部使用频次极低 | 归档项目，README 挂出迁移说明 |
| 发现自己在给 MCP/Skills/Prompt/网关/GUI 写代码 | 立即停下--这是 CC-Switch 的歧路，见 §5 铁律 |

---

## 5. Scope 边界与项目铁律

### 5.1 判定原则

> **凡是"换了 Provider/模型之后理应保持不变的东西"，ACM 一律不碰。**

### 5.2 管什么（In Scope）

| 层 | 内容 | 说明 |
|---|---|---|
| **L1 连接与凭据** | `base_url`、`protocol`（openai / anthropic / openai-responses）、`api_key`（credential 引用，规则见 §7.3.1）、自定义 headers、proxy、org_id | 含写入 Agent 支持的 env 块（如 Claude Code `settings.json` 的 `env` 字段） |
| **L2 模型规格与行为** | 模型选择（主模型 + 角色模型，如 Aider 的 main/weak/editor）、`context_window`、`max_output_tokens`、reasoning（`effort` low/medium/high + `budget_tokens`）、`temperature`、能力位（vision / tool-call 方言 native/xml/markdown / json mode） | ACM 统一建模，由适配器转换为目标 Agent 的专有字段；**无法表达的字段必须产生投影损失告警，绝不静默丢弃**（§7.4.1） |
| **Profile 管理** | 多 Profile 定义、激活态、版本快照、字段级回滚、diff | MVP 仅支持**全局单一激活 Profile**；Agent 级持久绑定（`acm bind`）为 Phase 2 规划（§12）；项目级 Profile（repo 内 `.acm/`）明确不进 MVP，作为 P3 开放问题评估 |
| **VMR 集成** | 自动探测本地 VMR、导入虚拟模型列表、一键投影 | 第一方集成，非架构依赖（§9） |

### 5.3 不管什么（Out of Scope）

- **MCP servers、Tools、Skills、Prompts（CLAUDE.md/AGENTS.md 等）、权限许可、hooks、plugins**--坚决不碰。
- 账号轮转 / OAuth token 池 / 额度监控（claude-swap 的领域）。
- 本地代理 / 网关 / 请求改写（VMR 的领域）。
- **Secret storage**：ACM 存储 credential **引用**（`${ENV}` 等），不承担密钥保管职责（§7.3.1）。
- Agent 启动包装（如 ccr 的子进程模式、ccc 的 `--settings` 注入模式）。MVP 只做持久化配置文件投影。
- GUI / TUI（核心是脚本友好的 CLI）。

### 5.4 项目铁律（Scope 的刚性约束，写入 CONTRIBUTING 与 PR 模板）

1. **绝不触碰** MCP、插件、Skills、系统提示词、权限配置、Agent 运行时状态文件。
2. **绝不写入**闭源 IDE 的私有数据库（如 Cursor/Cline 的 `state.vscdb` SQLite）。没有公开、稳定、可安全修改的配置接口，就不支持该 Agent--不为数量突破原则。
3. **任何新功能先过判定**：是否属于"模型配置层"（§5.2）？否则一律拒绝，无论需求来自谁。
4. ACM 的写入只落在**适配器声明的管理路径**上，由安全引擎强制执行（白名单 + 黑名单双重校验，§7.5.1）。

---

## 6. 关键技术决策

### D1：适配器 = 代码（Python 模块），不是 DSL

**结论：每个 Agent 一个独立的适配器模块（普通 Python 代码），共用一套 Helper 库。不引入声明式 DSL 作为扩展机制。**

论证：

1. **抽象成本核算**。Agent 配置的 field mapping 中约 60–70% 是"把 profile 字段 X 写到路径 Y"的简单映射，DSL 可以覆盖；但剩余 30–40% 包括：值转换（reasoning effort -> 各家不同的 budget 表达）、条件写入、多文件协同（Codex 的 `config.toml` + `auth.json`）、平台路径差异、格式方言、各种 Agent 特有怪癖。DSL 为了覆盖这些必须不断膨胀，最终变成一门糟糕的编程语言。**这是经典的泄漏抽象：配置语义天然图灵不完备不成立。**
2. **逃生舱的位置**。DSL 路线的实际扩展方式是"等官方更新 DSL"--那不如从一开始就把逃生舱作为正门：适配器就是代码，能力上限 = 宿主语言上限。
3. **AI 辅助维护的自然语言**。LLM 生成/修改**代码**远比生成受 DSL 语法约束的补丁文件更自然可靠。上游 schema 漂移时，"贴上官方文档让 AI 改适配器"是本项目规划中的标准维护动作。
4. **保留数据驱动的合理部分**。适配器内部当然可以用映射表（dict）描述简单字段映射--这是"代码使用数据"，与"把 DSL 产品化为外部扩展格式"有本质区别。

### D2：语言 = Python 3.12+，而非 Go

**结论：纯 Python，最小依赖（typer+rich、ruamel.yaml、tomlkit；pydantic 可选，决策标准见下），uv 生态分发与锁定。**

| 需求特征 | Go | Python |
|---|---|---|
| 适配器 = 可独立编写/可动态加载的代码（D1） | ❌ 编译进二进制，新适配器 = 发版；Go plugin 在 macOS 基本不可用 | ✅ 模块即插即用；用户适配器放 `~/.acm/adapters/*.py` 用 importlib 加载 |
| 非破坏性 round-trip 编辑 | ⚠️ yaml.v3 Node 操作繁琐，TOML round-trip 库弱 | ✅ ruamel.yaml / tomlkit 是事实标准 |
| 分发 | ✅ 单二进制（唯一显著优势） | ⚠️ 依赖 uv/pipx；但目标用户机器上 Python 几乎必然存在 |
| 迭代速度 / 上游 schema 漂移应对 | 慢 | 快 |
| 性能 | 无关紧要（纯本地文件 I/O） | 无关紧要 |

Go 的单二进制优势与 D1"适配器即代码"根本冲突，对本项目致命。**需求决定语言，而非相反。**

版本基线取 3.12+：uv 可自动安装并锁定 Python 版本，版本可用性不构成部署约束；新项目无需为旧版本承担兼容测试成本。

依赖预算与锁定（硬约束）：

- MVP 运行时依赖 ≤ 4 个：`typer`+`rich`（计 1 组）、`ruamel.yaml`、`tomlkit`，外加可选 `pydantic`。
- P1 引入 OpenCode（JSONC 注释保留）时，可放宽引入 1 个依赖（此时运行时依赖上限 ≤ 5 个）。**注意（附录 B 实证）**：现有候选 `commentjson` / `jstyleson` 均只在解析时剥离注释、写回即丢失，无法满足 §7.5.4 的注释保留硬要求（`commentjson` 还拖带 `lark-parser` 依赖且实测存在解析缺陷）；注释保留 Writer 预计需自研轻量 JSONC 编辑器（与 D1"适配器即代码"一致），放宽的名额仅用于届时评估确有必要时。
- `pydantic` 引入标准：当 Core Config 校验逻辑超过 ~200 行或校验规则开始互相组合时引入；否则用 dataclass + 显式校验函数。引入即计入依赖预算。
- 依赖以 uv lock 锁定，CI 中检查 lock 漂移；进程检测用标准库（`pgrep` / `tasklist`），**不引入 psutil**；文件锁用 `fcntl`/`msvcrt` 标准库实现。

### D3：Core Config = ACM 自有的模型世界 SSOT，格式 TOML

**结论：采纳"核心配置"概念并保持 TOML 格式（`~/.acm/config.toml`）。**

这是**所有权声明**：模型世界的事实源在 ACM 内部（providers / models / profiles 三层），Agent 端永远是投影的影子。

**否决"改为 YAML"的建议，理由：**

1. 该文件同时被用户手写和 ACM 机器读写（`acm import vmr` 会增量改写它）。TOML 无缩进语义、无类型歧义（YAML 的挪威问题/隐式类型/缩进错误），**双向读写场景下损坏概率显著更低**。
2. 实际嵌套深度只有 3 层（provider -> model -> reasoning），"TOML 深层嵌套可读性差"的论据在此深度不成立。
3. 依赖经济性：Codex 适配器是 P0，tomlkit 本来就是硬依赖，Core Config 用 TOML **零新增依赖**；与 Agent 端 YAML 文件（Aider/Hermes）在扩展名上天然区分，降低误编辑概率。
4. ruamel/tomlkit 均具备注释保留的 round-trip 能力，ACM 改写自身配置时同样保用户注释。

**配置与状态的边界（成文以防漂移）**：`config.toml` 只包含用户可版本控制的**声明式内容**（providers / models / profiles）；一切运行时状态（active profile、manifest、journal、snapshots、logs）只存在于 `~/.acm/state/` 与 `~/.acm/logs/`，**任何功能都不得把状态写回 config.toml**。

### D4：安全引擎 = 字段所有权清单为主 + 事务日志为脉 + 文件快照兜底

**结论：回滚数据模型三元分工，各司其职：**

```
Manifest（管理字段清单）  = 当前 ownership 状态：ACM 现在拥有哪些字段、当前写入值、接管前的原始值
Journal（事务日志）       = 每一次 ChangeSet 事务的完整历史（回滚的数据来源）
Snapshot（文件快照）      = 整文件灾难恢复（--hard 专用，正常操作不依赖）
```

理由（公理 3 的直接推论）：Agent 在 ACM 写入之后可能又向同一文件写入了新状态。此时若回滚整个文件快照，会把 Agent 新写的状态一起抹掉。正确语义是三层恢复体系：

```
字段级回滚（默认，基于 Journal 逆操作） -> 审计轨迹（Journal） -> 整文件快照（--hard 灾难恢复）
```

完整机制见 §7.5。

### D5：分发 = 单一主路径，其余通道按需后置

**结论：MVP 只做一个主路径--发布到 PyPI，主推 `uvx acm`（零安装试用）与 `uv tool install acm`（全局安装）。pip/pipx 随 PyPI 发布免费获得。**

Homebrew Tap 与 pyapp 打包各自需要持续 CI 维护成本，触发式后置（写进 P3 准入条件）：出现真实的非 Python 环境需求 -> 上 pyapp；出现明确的 brew 用户获取习惯需求 -> 上 brew tap。

### D6：MVP 首批适配器 = Claude Code + Codex + Pi（真实使用优先原则）

**结论：P0 = Claude Code、Codex、Pi；Aider 作为 P1 首位（架构压力测试）。**

裁决依据：

1. **第一性原则：MVP 首先要服务真实用户（我们自己）**。本机实证（附录 B）：实际在用的 Agent 是 Claude Code、Codex、Pi、Gemini CLI、OpenCode；Aider 与 OpenClaw 并未实际使用。
2. **架构覆盖充分性以矩阵检验，而非以"选最复杂的 Agent"检验**：

   | 架构能力 | 由谁验证 |
   |---|---|
   | JSON + env 块注入 + 大量非管字段保护 | Claude Code（`settings.json` 与 `~/.claude.json` 状态文件的边界） |
   | TOML round-trip + **双文件事务**（`config.toml` + `auth.json`） | Codex（本机实证：用户 config.toml 含大量带注释的 `mcp_servers` 表） |
   | Provider/Model **注册式**投影 + api 方言映射 + compat 能力位 + thinking level 映射 | Pi（其 schema 与 Core Config 概念同构度最高） |
   | YAML round-trip + 角色模型（main/weak/editor）+ 元数据文件派生 | **Aider（P1 首位，架构压力测试）**；ruamel round-trip 能力在 MVP 内以 Helper 级金样单测前置锁定 |

3. 结论：P0 三件套已覆盖 JSON/TOML 双格式、单/多文件、覆盖式/注册式两种投影形态；唯一未覆盖项由 P1 首位的 Aider 承担。**MVP 的架构验证充分性不受损，同时不做无用功。**

### D7：动态适配器热加载 = 架构预留，Phase 2 落地

**结论：MVP 不实现 `~/.acm/adapters/*.py` 热加载，但 Adapter Protocol（§7.4）从一开始就按"用户模块可实现"设计（纯 Python Protocol、无内部 API 依赖）。Phase 2 交付 importlib 加载器 + 协议文档 + 模板。**

理由：先回答"官方适配器能否稳定、安全地完成投影"，再回答"第三方能否自己写适配器"。

---

## 7. 架构设计

### 7.1 核心流水线（本架构的脊柱）

```
Core Config / SSOT              # ACM 认为模型世界是什么
        ↓
Profile Resolution              # 解析出无环境引用的 ResolvedProfile
        ↓                       #（Phase 2 起：叠加 per-agent 绑定）
Desired State                   # 该 Agent "应当处于"的字段级状态
        ↓
Adapter（语义编译）              # 目标 Agent 怎么表达--产出 ChangeSet + 投影告警，不碰文件
        ↓
ChangeSet                       # 具体要改什么（文件、路径、旧值、新值）
        ↓
Ownership / Conflict Check      # ACM 有没有资格改（白/黑名单、漂移、进程、锁）
        ↓
Pre-commit Fingerprint Check    # 磁盘自读取后未被外部改动（TOCTOU 防护）
        ↓
Format-specific Writer          # 怎么安全地改（声明保真能力的 round-trip 编辑器）
        ↓
Atomic Write（串行加锁）         # temp + os.replace
        ↓
Journal / Manifest / Snapshot   # 怎么追踪和恢复（+ 启动崩溃恢复）
```

**两个正式状态概念（CLI 语义的地基）：**

- **Desired State**：Active Profile（Phase 2 起含 per-agent 绑定）经 Adapter 编译后的字段级期望状态。
- **Current State**：各 Agent 配置文件中管理字段的实际落盘值。

由此，CLI 动作获得统一语义：`use` = 改变 Desired State（换激活 Profile）并立即收敛；`apply` = Current -> Desired 的幂等收敛；`status` / `diff` = Current vs Desired（及 vs 上次 ACM 写入值）；**drift** = Current ≠ 上次 ACM 写入值（说明有外部改动）。

**强制约束**：Adapter 只做"编译"（profile -> ChangeSet），**一切磁盘写入由 Safety Engine 统一执行**。适配器物理上无法绕过安全语义。

### 7.2 组件图

```
┌─────────────────────────────────────────────────────────────┐
│                        acm CLI（typer + rich）                │
│  init/use/apply/status/diff/history/rollback/release/        │
│  doctor/import/bind(Phase 2)                                 │
├─────────────────────────────────────────────────────────────┤
│                      Core（纯逻辑，无 I/O）                    │
│  CoreConfig 加载校验 · Profile 解析 · Desired State ·         │
│  ChangeSet 计算 · 幂等判断 · ENV 引用解析                      │
├──────────────────────────┬──────────────────────────────────┤
│      Safety Engine       │          Adapter Layer           │
│  三阶段提交 · 管理清单      │   Adapter Protocol（detect/       │
│  黑白名单 · 漂移检测        │   config_paths/plan/verify）      │
│  指纹校验 · 并发锁          ├──────────────────────────────────┤
│  崩溃恢复 · 快照保留策略     │   内置适配器（每 Agent 一个模块）    │
│  字段级回滚 · 密钥掩码      │   claude_code·codex·pi·...        │
│                          │   用户适配器 ~/.acm/adapters/*.py   │
│                          │   （Phase 2：importlib 动态加载）    │
├──────────────────────────┴──────────────────────────────────┤
│                    Format Writers（共用库，声明保真能力）        │
│  JSON 保序编辑 · ruamel round-trip · tomlkit · JSONC · .env   │
│  路径解析 Helper（env 覆盖 -> XDG -> 平台默认 -> 探测）          │
└─────────────────────────────────────────────────────────────┘
```

### 7.3 Core Config（`~/.acm/config.toml`）

```toml
version = 1                        # Schema 版本（非软件版本），迁移策略见 §7.3.2

# ── L1 供应商：端点与凭据引用 ──────────────────────────
[providers.vmr]
protocol    = "openai"                  # openai | anthropic | openai-responses
base_url    = "http://127.0.0.1:8800/v1"
api_key     = "${VMR_KEY}"              # credential 引用，规则见 §7.3.1
# headers    = { x-org-id = "..." }
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
id                 = "coding"
display_name       = "VMR Coding"
context_window     = 131072
max_output_tokens  = 16384
temperature        = 0.2                # 缺省 = 不写入，用 Agent 默认
capabilities       = { vision = false, tools = "native", json_mode = true }

[models.coding.reasoning]
effort        = "high"                  # 适配器负责换算为各家表达
budget_tokens = 16000                   # 仅目标 Agent 能表达时才投影（否则告警，§7.4.1）

[models.cheap]
provider           = "vmr"
id                 = "cheap"
context_window     = 131072
max_output_tokens  = 8192

# ── L3 Profile：命名的角色组合 ─────────────────────────
[profiles.daily]
main  = "coding"
cheap = "cheap"                          # 角色槽位：仅支持多模型的 Agent 消费

[profiles.budget]
main  = "cheap"
```

- **激活态存放于 `~/.acm/state/active`**（仅 profile 名），只能通过 `acm use` 改变（配置/状态分离，见 D3）。
- 单模型 Agent 消费 `profile.main`；多角色 Agent（如 Aider）由适配器将 Profile 中的角色槽位映射到目标字段。
- Pi 类注册式 Agent 消费完整 models 定义；覆盖式 Agent（如 Claude Code）只消费被 profile 引用的模型。

#### 7.3.1 Credential 引用规则（Core Config 不承担 secret storage）

**原则：Core Config 存的是 credential 引用，真正的 secret 永远来自外部（环境变量，未来可选 keychain）。ACM 不演变成"另一个 API key manager"。**

语法与语义（刻意最小化，杜绝注入面）：

1. 语法仅两种：`${VAR}` 与 `${VAR:-default}`。**严格采用整字段替换（Whole-value replacement）**：引用必须占据该字段的完整值，不支持字符串内子串插值（如 `http://${HOST}:8800` 不合法，动态端点请通过环境变量配置完整 URL）、不支持嵌套引用、命令替换与运算--彻底杜绝模版注入与转义歧义。
2. 任一字段只允许单一来源（引用或明文二选一），**不存在优先级问题**；同时出现视为 schema 错误。
3. **解析时机**：投影时（use/apply/doctor）实时解析，不在 config 加载时固化--环境变量变更后无需刷新。
4. **失败处理**：变量不存在且无默认值 -> **硬错误，任何文件写入发生之前整体中止**（退出码 1），doctor 列出所有未解析引用。
5. 明文存储 = 显式 escape hatch（直接写字面量），`acm doctor` 持续告警；`credential = "name"`（命名凭据，接 keychain）为预留字段，后续可选，MVP 与 Phase 2 均不实现。

#### 7.3.2 Schema 版本与迁移

- `version = 1` 是 **config schema 版本**，非 ACM 软件版本；manifest / journal / snapshot 各自携带自己的格式版本。
- ACM 启动时校验版本：低版本配置向前兼容读取；不兼容版本由 `acm doctor` 检测并提示，`acm config migrate`（Phase 2 交付）执行迁移。
- 现在 only 定义位置与语义，MVP 不实现迁移命令。

### 7.4 Adapter 契约（Python Protocol）

```python
class Adapter(Protocol):
    agent_id: str            # "claude_code"
    display_name: str        # "Claude Code"

    def detect(self) -> bool: ...
        # 本机是否安装该 Agent。判定标准（统一约定）：
        # 配置目录/文件存在 = 已安装（主判据，Agent 首次运行必建配置，
        # 而 PATH 检查会漏掉未链接的安装）；可执行文件存在为辅。
        # 探测失败的 Agent：跳过并在结果中汇总告警，不影响其他 Agent。

    def config_paths(self) -> list[Path]: ...
        # 声明本适配器管理的所有文件路径--Safety Engine 据此统一做快照。
        # 必须使用统一路径 Helper：环境变量覆盖 -> XDG -> 平台默认 -> 探测，
        # 禁止硬编码绝对路径。

    def plan(self, profile: ResolvedProfile) -> ChangeSet: ...
        # 纯函数：产出字段级变更集 + 投影告警（§7.4.1）。值转换/方言适配/
        # 多文件协同全部在这里，用普通代码写。绝不直接写文件。

    def verify(self, cs: ChangeSet) -> VerifyReport: ...
        # 落盘后断言：目标字段已正确写入、保护区域未变
```

新增一个官方 Agent = 新增约 100–300 行模块 + 一组金样 fixtures（§11）。适配器应用顺序 = 注册表固定顺序（确定性，文档化）。

**ChangeSet 及核心数据结构**（Safety Engine 的输入契约）：

```python
@dataclass
class FieldOp:
    file: Path
    path: str              # 格式专属点路径，如 "env.ANTHROPIC_BASE_URL"
    old: object | None     # 探测到的当前值（含"不存在"哨兵）
    new: object
    created: bool          # 该路径是否为本次新建

@dataclass
class ProjectionWarning:
    field: str
    agent_id: str
    reason: str

@dataclass
class VerifyReport:
    ok: bool
    errors: list[str] = field(default_factory=list)

@dataclass
class ChangeSet:
    txid: str                     # 事务 ID（journal 主键，rollback --to-tx 引用）
    agent_id: str
    profile: str                  # 来源 profile
    ops: list[FieldOp]
    warnings: list[ProjectionWarning]   # 投影损失告警（§7.4.1），可为空
    protected_paths: list[str]    # 适配器声明的禁止触碰路径（黑名单）
    managed_namespaces: list[str] # 适配器声明的合法写入命名空间（白名单）
```

#### 7.4.1 投影损失告警（Projection Loss Warning）

**原则：Desired State 中无法被目标 Agent 表达（或只能降级表达）的字段，必须显式告知用户，绝不静默丢弃。**这与"不静默覆盖外部修改"是同一哲学在两个方向上的体现。

- 适配器在 `plan()` 中对每个无法表达/需要降级的字段产出 `ProjectionWarning(field, agent_id, reason)`，进入 ChangeSet。
- CLI 在 use/apply/diff/status 输出中聚合展示，例如：
  `⚠ 1 field cannot be represented by claude_code: models.coding.reasoning.budget_tokens (projection will omit it)`
- 语义能力（Core Config 里模型是什么）与投影能力（Agent 配置能表达什么）是两个正交维度，均记录在适配矩阵（§8）中；`acm status --verbose` 展示每 Agent 的投影能力摘要。

### 7.5 Safety Engine（核心安全机制汇总）

#### 7.5.1 三阶段事务提交（所有写入的唯一通道，crash-safe）

```
[入口] 获取全局写入锁 ~/.acm/state/.lock（flock，非阻塞；
       占用中 -> 立即报错退出，绝不排队等待）

[阶段 0 · Recovery Check]
  检查 journal 中是否存在未完结事务（PREPARED / COMMITTING）：
  存在 -> 执行崩溃恢复（§7.5.7）后才继续

[阶段 1 · Prepare & Snapshot]
  1. 进程守护：按分级策略（§7.5.5）阻断或警告，--force 覆盖
  2. 逐文件读取原始字节，计算指纹 H0（文件若不存在则标记 H0 = NOT_EXIST）
  3. 保存文件快照至 ~/.acm/state/<agent>/snapshots/<ts>/（记录初始状态）
  4. 写入 journal：txid、时间、命令、ChangeSet、状态 = PREPARED
  5. 黑白名单校验：
     - 白名单：每个 op.path ∈ managed_namespaces
     - 黑名单：每个 op.path ∉ protected_paths
     - 任一违反即中止（退出码 2）

[阶段 2 · In-Memory Mutate & Verify]
  1. round-trip 解析（ruamel / tomlkit / 保序 JSON 编辑器）
  2. 仅对 op.path 赋值，内存中完成全部变更（含多文件）
  3. 语法自检：修改后文本可再次无损解析
  4. 非管字段零篡改断言：解析树 diff 确认除 op.path 外结构不变

[阶段 3 · Atomic Commit]
  1. 逐文件 pre-commit 指纹校验（重读磁盘字节，哈希必须 == H0，
     原不存在者仍须不存在；不等 = 外部并发修改 -> 整体中止并报告 drift，绝不覆盖）
  2. 预备写入：在各目标文件同目录下写入临时文件 <target>.acm_tmp
  3. 状态前置落盘：将 journal 状态更新并落盘为 COMMITTING
     （确立提交意图，此后若崩溃，恢复程序确知需从快照回滚）
  4. 逐文件原子替换：执行 os.replace(<target>.acm_tmp, <target>)
  5. 提交完成：journal 状态更新为 COMMITTED；更新 manifest；清理临时文件
  6. 任一步骤异常：用内存原始字节/快照逆向还原已替换文件，
     journal 标记为 ABORTED，中止后续（跨文件一致性）
```

#### 7.5.2 管理字段清单（Managed Manifest）与漂移检测

`~/.acm/state/<agent>/manifest.json` 记录 ACM 对该 Agent 的管理字段与所有权状态，核心记录每个管理项的：

```json
{
  "current":  "…",           // ACM 最后一次写入的值
  "pre_acm":  "…",           // ACM 首次接管该字段之前的值（release 的恢复目标）
  "existed_pre_acm": true,   // 该字段接管前是否存在
  "created_by_acm": false,   // 该字段是否为 ACM 新建
  "last_tx": "tx-…"          // 最后一次写入它的事务
}
```

**漂移检测的统一语义（适用于所有写入类命令）**：任何写入命令（use / apply / rollback / release）在执行前检查管理路径的当前磁盘值：

- 磁盘值 == ACM 最后写入值：正常继续。
- 磁盘值 ≠ ACM 最后写入值：**外部修改过，默认阻断**，要求 `--force` 或先 `acm diff` 确认。不存在任何"自动修复漂移"的路径--`apply` 的收敛也必须过这道闸门。

manifest 的三个用途：

1. **ownership 状态查询**：status / doctor / diff 判断"这个字段现在归不归我管、有没有被动过"。
2. **`release` 的精确语义**：所有管理字段恢复 `pre_acm`（ACM 接管前的状态）；ACM 新建的字段（`created_by_acm`）直接删除；完全由 ACM 创建且接管前不存在的文件（如 Pi 的 models.json 用户原本没有）整文件删除；其余情况只动管理字段，用户内容与注释保留。
3. **幂等判断**：期望值 == current 且磁盘无漂移 -> ChangeSet 为空 -> no-op。

#### 7.5.3 文件快照（Safety Net，非默认回滚机制）

- 位置：`~/.acm/state/<agent>/snapshots/<ts>/`；**保留策略：每 Agent 默认保留最近 20 份，FIFO 自动清理，数量可配置**。
- 用途：`--hard` 灾难恢复、崩溃恢复（§7.5.7）、审计。
- 正常操作不依赖整文件恢复。

#### 7.5.4 非破坏性保证等级（按格式与能力声明，诚实定义）

不使用"100% 保留"这类无法对所有输入负责的绝对承诺。保证模型分两层：

1. **语义级保证（硬承诺）**：未管理节点的语义（解析后的结构与值）不发生变化。以解析树 diff 断言，可对所有合法输入负责。
2. **词法级保证（fixture 界定的承诺）**：注释、键序、缩进、空行等 lexical 元素经 round-trip 编辑器保留。工程上无法对任意畸形输入承诺绝对保留，因此承诺方式为：**对官方支持并纳入金样 fixture 的输入形态集合，词法保留断言必须全绿**；超出集合的 corner case 按缺陷处理并扩充 fixture。

**Format Writer 能力声明契约**（每种格式的 Writer 必须声明，实现可替换、契约不变形）：

| Writer | 语义保留 | 注释保留 | 键序保留 | 空白/排版保留 |
|---|---|---|---|---|
| JSON | 保证 | n/a | 保证（保序解析） | 缩进风格自动探测匹配；末尾换行保留 |
| JSONC | 保证 | **要求**（comment-preserving 解析；无法满足则该格式适配器不得交付） | 保证 | 同 JSON + 注释位置保留 |
| YAML（ruamel rt） | 保证 | fixture 界定 | fixture 界定 | fixture 界定 |
| TOML（tomlkit） | 保证 | fixture 界定 | fixture 界定 | fixture 界定 |
| .env | 保证 | 行级（仅整行替换/追加，其余行字节不动） | 保证 | 保证 |

明确否决的主张："RFC 6902 JSON Patch = 非破坏性"。JSON Patch 若经 `json.dumps` 重序列化落盘，照样摧毁排版与键序。正确路径是 **ChangeSet + 格式专属 round-trip 编辑器**；RFC 6902 至多作为 ChangeSet 的内部表示，不作为写入机制。

#### 7.5.5 进程守护（分级策略）

写入前检测目标 Agent 活跃进程（标准库 `pgrep` / Windows `tasklist`）。分级依据 = 官方文档或实测的配置热加载行为：

| 等级 | 条件 | 行为 | 当前成员（依据） |
|---|---|---|---|
| **BLOCK**（默认） | Agent 未证实支持配置热加载 | 阻断，`--force` 覆盖 | Codex、Pi、其余全部（保守默认） |
| **WARN** | 官方证实切换热生效 | 警告但放行 | Claude Code（cc-switch 官方 FAQ 提及） |

标准文案：
`⚠️ Process '<name>' (PID <pid>) is running. Writing now may be overwritten on exit. Use --force to proceed.`

#### 7.5.6 并发锁（ACM 自身的并发安全）

- 全局独占锁：`~/.acm/state/.lock`，`fcntl`（Unix）/ `msvcrt`（Windows）标准库实现，**非阻塞**。
- 所有写入类命令（use/apply/rollback/release/import 的写路径）入口获取；占用中立即报错（退出码 2）：`⚠️ Another acm process is holding the write lock.` 不排队、不等待。
- 目标：覆盖"脚本并行调用 / 双终端同时操作"导致的清单-磁盘竞态，与进程守护（防 Agent）互补。

#### 7.5.7 崩溃恢复（Crash Recovery）

三阶段提交可处理运行期异常，但不能处理 ACM 进程在提交中途被 kill / 掉电。恢复协议：

- journal 中每个事务有显式状态机：`PREPARED -> COMMITTING -> COMMITTED / ABORTED`。
- **任何 acm 命令启动时**（以及 `acm doctor` / `acm init` 显式执行时）检查未完结事务：
  - `PREPARED`（尚未动过磁盘）-> 清理临时文件，标记 ABORTED。
  - `COMMITTING`（部分文件已 replace，内存丢失）-> 用该事务阶段 1 的**快照**把涉及文件整体还原到事务前状态，标记 ABORTED，输出报告。
- 恢复动作本身也走原子写与 journal 记录；恢复后用户可重试原命令。
- 不引入数据库级 WAL 复杂度--journal + 快照已足够闭环，复杂度刻意受控。

#### 7.5.8 密钥与敏感信息全链路防护

- **文件权限**：`~/.acm/state/`（含 manifest / journal / snapshots，因其含原始配置与明文密钥）与日志目录强制 `0700`/文件 `0600`，创建即设置。
- **输出掩码**：`diff` / `status --verbose` / `--json` 输出中，命中敏感路径规则（api_key / token / auth 类字段）的值默认掩码（仅显示首尾 3 位）；`--show-secrets` 显式 opt-in 才输出明文。
- credential 引用模型见 §7.3.1--源头上减少明文落盘。

#### 7.5.9 幂等性

重复 `acm use <同一 profile>`：ChangeSet 与清单比对后为空 -> no-op，退出码 0，不产生新快照。

### 7.6 Agent 状态机（status 的正式模型）

每个 Agent 在任一时刻处于且仅处于一个状态，CLI、`--json`、doctor、CI 共用同一枚举：

| 状态 | 定义 |
|---|---|
| `NOT_DETECTED` | 本机未检测到该 Agent |
| `UNMANAGED` | 已安装，但 ACM 从未写入过 |
| `SYNCED` | Current == Desired，无漂移 |
| `OUT_OF_SYNC` | Current == ACM 最后写入值 ≠ Desired（ACM 侧配置已改动，无外部漂移，待 `apply` 收敛） |
| `DRIFTED` | 管理字段的磁盘值 ≠ ACM 最后写入值（外部修改） |
| `CONFLICT` | 环境冲突当前生效（Agent 进程运行中 / 写入锁被占 / 上次操作被阻断待处理） |
| `ERROR` | 配置不可读/语法损坏/疑似上游 schema 漂移，需要 doctor 介入 |

多条件并存时按优先级取唯一展示态：`ERROR` > `CONFLICT` > `DRIFTED` > `OUT_OF_SYNC` > `SYNCED`（`NOT_DETECTED` / `UNMANAGED` 由安装与接管状态先行判定，不参与该优先级）。

### 7.7 目录布局

```
~/.acm/
├── config.toml                 # Core Config（SSOT；仅声明式内容，可入 dotfiles git）
├── .gitignore                  # 由 acm init 自动创建（忽略 state/、logs/、.lock）
├── adapters/                   # 用户自定义适配器（Phase 2 启用动态加载，目录先预留）
├── state/                      # 0700（含敏感内容）
│   ├── active                  # 当前激活 profile 名（仅 acm use 可改）
│   ├── .lock                   # 全局写入锁（flock）
│   └── <agent>/
│       ├── manifest.json       # 管理字段清单（ownership + pre_acm + current）
│       ├── journal.jsonl       # 事务日志（append-only，含状态机）
│       └── snapshots/<ts>/     # 文件快照（兜底，FIFO × 20）
└── logs/                       # 运行日志；--verbose = DEBUG 级入日志，默认 INFO 摘要
```

推荐用法（写入 README 与 init 自动化）：`acm init` 会默认自动生成 `~/.acm/.gitignore`（排除 `state/`、`logs/` 与 `.lock`）。用户可放心将 `~/.acm/config.toml` 纳入个人 dotfiles 仓库，明文密钥、快照与状态数据绝不会误入版本控制。

---

## 8. Agent 适配矩阵

> 标注 ✔ 的为已核实事实（本机实证或官方文档，附录 B）；其余以实现时金样校准为准。本矩阵是**活文档资产**，随适配器开发持续充实。每行记录两个维度：**投影能力**（能写什么）与**语义能力映射**（怎么转译、什么无法表达）。

### P0（Phase 1）

| Agent | 目标文件 | 格式 | ACM 写入字段 | 保护字段（黑名单） | 架构验证点 / 投影能力 |
|---|---|---|---|---|---|
| **Claude Code** | `~/.claude/settings.json` ✔ | JSON | `env.ANTHROPIC_BASE_URL`、`env.ANTHROPIC_AUTH_TOKEN`（或 `ANTHROPIC_API_KEY`）、`model`、reasoning -> `effortLevel` 类字段 ✔ | `permissions`、`hooks`、`enabledPlugins`、`statusLine`、`tui` 等一切非模型字段；**绝不碰 `~/.claude.json`** ✔ | env 块注入；高密度非管字段保护；热切换（WARN 级）✔；无法表达 reasoning budget_tokens -> 投影告警 |
| **Codex** | `~/.codex/config.toml` ✔ + `~/.codex/auth.json` ✔ | TOML + JSON | 顶层 `model`、`model_reasoning_effort` ✔、`model_providers.<id>` 表（base_url/wire_api/env_key）、auth.json 对应 key | `mcp_servers`（本机实证含大量带注释条目 ✔）、`features`、`memories`、`tui`、`notify`、`sandbox` | tomlkit round-trip（注释密集 ✔）；**双文件事务 + 崩溃恢复**的首个实战用例 |
| **Pi** | `~/.pi/agent/models.json`（用户自定义文件，官方文档 ✔；不存在则创建）+ `~/.pi/agent/settings.json` ✔ | JSON | models.json：`providers.<name>`（baseUrl / api 方言 ✔ / apiKey / models[]：id、contextWindow、maxTokens、compat、thinkingLevelMap ✔）；settings.json：`defaultProvider`、`defaultModel`、`defaultThinkingLevel` ✔ | **`models-store.json`（pi 内部注册表，绝不写入）** ✔、`trust.json`、`auth.json`、extensions/skills | 注册式投影；方言（`openai-completions`/`anthropic-messages` ✔）+ compat/thinking level 映射，与 Core Config 同构度最高 |

### P1（Phase 2）

| Agent | 目标文件 | 格式 | 要点 |
|---|---|---|---|
| **Aider**（架构压力测试） | `~/.aider.conf.yml` + `~/.aider.model.metadata.json` | YAML + JSON | 角色模型（main/weak/editor）；YAML 改动联动派生 JSON 元数据--ruamel round-trip + 跨文件派生逻辑的最难用例 |
| **Gemini CLI** | `~/.gemini/settings.json` 等 | JSON | env 块 + 模型选择；路径细节金样校准 |
| **OpenCode** | `~/.config/opencode/opencode.json` ✔（本机存在） | JSONC | provider/model 配置；**JSONC 注释保留 Writer 的验收载体**（§7.5.4） |

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
                            #   fallback 读取 ~/.vmr/ 配置）
                            #   -> 展示将要写入的内容，交互确认后才 import
                            #   （--yes 跳过确认供自动化；绝不静默修改用户 SSOT）
$ acm import vmr            # 拉取虚拟模型列表 -> 生成 providers.vmr + models.*（增量合并进 config.toml）
$ acm use daily             # 投影到本机所有已检测到的 Agent（默认全部；支持 --agent 指定）
$ acm status                # 总览：各 Agent 状态机 + 漂移
```

- **零依赖原则**：无 VMR 时一切功能照常（直连 OpenRouter / DeepSeek / SiliconFlow / Ollama / 任意兼容端点）。
- **VMR 侧零改动**：只需暴露标准的模型列表查询端点；ACM 对 VMR 的全部"感知"就是一次 import。
- **退出对等**：`acm release` 一键解除所有 Agent 与 VMR 的绑定，零残留。
- `acm use-vmr <virtual_model>`（Phase 2 薄糖层 = import-if-needed + 选 profile + `use`）与 `acm vmr status`（Phase 2）仅在真实使用中出现重复按键痛点后再做--MVP 的 `init -> use` 两步已满足"≤3 条命令"成功标准。

---

## 10. CLI 命令规格

### 10.1 命令总表

```bash
# ── 初始化与状态 ────────────────────────────────────────
acm init [--dry-run] [--yes] [--force]
                            # 首次：扫描 Agent + 探测 VMR + 展示提案 + 确认后生成 config.toml
                            # 重复执行（config 已存在）：提示 覆盖 / 增量合并 / 取消，
                            #   默认取消（绝不破坏现有配置）；--force 跳过提示重新生成
                            # VMR 探测命中：展示将写入的 providers/models，确认（或 --yes）后 import
acm status [--verbose]      # 各 Agent：状态机枚举 + 当前 profile + 漂移 + 投影告警摘要
acm doctor                  # 诊断：配置语法、文件权限、${ENV} 引用缺失、管理路径漂移、
                            # 未完结事务、进程冲突、明文密钥告警 + 修复建议

# ── 核心操作（Desired State 收敛）─────────────────────────
acm use <profile> [--agent <id|all>] [--dry-run] [--force]
                            # 设为激活 profile 并投影（默认所有已检测 Agent）；
                            # 遇漂移默认阻断（--force 覆盖）
acm apply [--agent <id|all>] [--dry-run] [--force]
                            # 幂等收敛 Current -> Desired；漂移同样默认阻断

# ── 安全与审计 ─────────────────────────────────────────
acm diff [<agent>] [--against desired|last-write|snapshot]
                            # 彩色 unified diff + 漂移专项标注（外部改动值 vs 期望值）；
                            # 若目标 Agent 为 UNMANAGED，默认执行 Dry-run 虚拟比对（展示当前
                            #   磁盘原始配置 vs 接管后的预期变更，并标注 [DRY-RUN / UNMANAGED]）
acm history [<agent>]       # 事务时间线：txid、时间、来源 profile、命令、状态
acm rollback [<agent>] [--to-tx <txid>] [--hard [--snapshot <id>]] [--force]
                            # 默认字段级回滚：逆序回滚最后一个事务（--to-tx <txid> 则逆序回滚
                            #   至该事务之后的状态）--基于 journal，粒度是字段
                            # --hard 灾难恢复：整文件快照还原（--snapshot <id> 恢复指定快照，
                            #   缺省为最新快照）
                            # 参数名显式分离（--to-tx vs --snapshot），杜绝多态混淆
acm release [<agent>] [--force]
                            # 按管理清单恢复 pre-ACM 状态（§7.5.2），清空清单，零残留

# ── VMR ────────────────────────────────────────────────
acm import vmr [--url <url>] [--dry-run]
acm vmr status              # Phase 2
acm use-vmr [<model>]       # Phase 2 薄糖层

# ── Profile / 绑定 ─────────────────────────────────────
acm profile list | show <name>          # Phase 2
acm profile create <name>               # Phase 2（交互式/模板）
acm bind <profile> --agent <id>         # Phase 2：Agent 级持久绑定（MVP 仅全局激活）

# ── 全局选项 ───────────────────────────────────────────
--dry-run                   # 只计算 ChangeSet 并展示，不写任何文件
--force                     # 覆盖漂移阻断 / 进程阻断
--verbose                   # DEBUG 级日志（stderr + ~/.acm/logs/）
--no-color                  # 输出管道友好
--json                      # Phase 2：机器可读输出（状态机枚举直出；密钥默认掩码）
--show-secrets              # 显式输出明文密钥（默认掩码）
```

### 10.2 退出码规范（脚本化是核心定位，退出码是 API）

| 退出码 | 场景 |
|---|---|
| `0` | 成功（含幂等 no-op） |
| `1` | 配置错误：语法 / schema 校验失败 / ENV 引用未解析 |
| `2` | 安全阻断：漂移阻断、进程冲突、写入锁被占、黑白名单拦截 |
| `3` | I/O 失败：权限不足、写入失败、磁盘错误 |
| `4` | 未找到：Agent / profile / txid / snapshot |
| `130` | 用户中断（SIGINT） |

流约定：正常结果走 stdout；错误、警告、日志走 stderr。

### 10.3 标准交互文案

- 进程冲突：`⚠️ Process '<name>' (PID <pid>) is running. Writing now may be overwritten on exit. Use --force to proceed.`
- 漂移阻断：`⚠️ Drift detected on <agent>: managed field '<path>' was changed externally (expected '<x>', found '<y>'). Run 'acm diff <agent>' or use --force.`
- 写入锁：`⚠️ Another acm process is holding the write lock.`
- 投影损失：`⚠ N field(s) cannot be represented by <agent>: <path>… (projection will omit them)`
- 崩溃恢复：`↻ Recovered incomplete transaction <txid> (<n> file(s) restored from snapshot). You may retry your command.`

---

## 11. 测试与质量保障

### 11.1 金样回归测试（Golden File Suite）--适配器开发的基础设施

每个适配器配套**真实感 fixtures**：带手写注释、带 MCP 配置、带私有字段、带格式怪癖的配置样本（本机实证样本脱敏后入库，如 Codex 的注释密集 config.toml ✔）。

**正向三步断言闭环**：

1. **Apply**：目标模型字段精确修改（语义断言）。
2. **Non-destructive**：按 §7.5.4 的格式保证等级分别断言--未管理节点语义级不变（解析树 diff，硬承诺）；注释/键序/空白按 fixture 界定的词法承诺断言。
3. **Rollback**：字段级回滚后管理字段恢复旧值；apply 与 rollback 之间**模拟 Agent 写入状态**后该状态仍存活；`--hard` 回滚后文件 SHA-256 与原样本一致。

**负面与故障注入用例（安全机制的刚性验证）**：

- 故意让 op 触碰保护路径 -> 断言拦截（退出码 2）且文件零变更；
- 多文件事务中途注入失败 -> 已提交文件自动回滚、无残留；
- 提交间隙 SIGKILL 进程 -> 重启后崩溃恢复还原一致性、临时文件被清理；
- 提交前外部篡改文件（指纹不匹配）-> 整体中止，无覆盖；
- ENV 引用缺失 -> 任何写入发生前硬中止；
- 双进程并发写 -> 锁竞争一方退出码 2，无交错写入；
- 磁盘满 / 权限错误（可行环境下注入）-> 原子写失败且原文件完好。

### 11.2 Schema 漂移检测

- 金样 fixtures 同时充当上游 schema 哨兵：Agent 升级后 CI 全量回归即可发现字段布局变化。
- `acm doctor` 在用户侧主动检测落盘异常（管理路径读不到期望结构 = 上游漂移信号，状态置 `ERROR`）。

### 11.3 CI 策略

- 每适配器独立测试目录（漂移不跨 Agent 传染）；
- Format Writer round-trip 单测（JSON / JSONC / YAML / TOML / .env）先于任何适配器交付；
- Safety Engine 事务测试（失败注入 / 崩溃恢复 / 锁）；
- uv lock 漂移检查。

---

## 12. 实施路线图与验收标准

### Phase 1：MVP（目标 ~1–2 周）

**实现优先级分组**（十个命令是同一引擎的十个薄入口，不是十个独立 feature）：

```
Core：    init / use / status / diff / apply
Safety：  rollback / release / doctor（含崩溃恢复入口）
Audit：   history
Integration： import vmr
```

**交付**：

- Core / Safety Engine / Format Writers / Adapter Protocol 完整框架
- Safety Engine 全量机制：三阶段提交、管理清单、漂移检测、pre-commit 指纹校验、并发锁、崩溃恢复、快照保留策略、密钥掩码
- P0 适配器：**Claude Code、Codex、Pi**
- 全命令（如上分组）+ 退出码规范
- Format Writer round-trip 单测（含 YAML 前置锁定）+ 适配器金样测试 + 负面/故障注入用例
- PyPI 发布（uvx / uv tool install / pipx 可用）

**硬验收标准（全部可量化）**：

1. 全新机器 VMR 场景：`acm init --yes` -> `acm use daily` 后，3 个 P0 Agent 全部正确指向 VMR 虚拟模型；全程 ≤ 3 条命令、零手工编辑。
2. `acm rollback` 后：管理字段恢复旧值；apply 与 rollback 之间模拟的 Agent 状态写入**存活**。
3. 金样三步断言全绿（含 `--hard` 后 SHA-256 一致）+ 全部负面用例通过（§11.1）。
4. 幂等：连续两次相同 `acm use` 第二次为 no-op（退出码 0）。
5. 黑白名单断言：任何 op 触碰 `mcp_servers` / `mcpServers` / `permissions` / `hooks` / `enabledPlugins` / `models-store.json` 即测试失败。
6. `acm release` 后：三 Agent 配置与 pre-ACM 状态一致（含"ACM 创建的文件被删除"场景），清单清空，零残留。
7. 提交间隙 kill 进程后，任一 acm 命令可自动完成崩溃恢复，配置文件回到事务前一致状态。

### Phase 2：生态扩展（目标 +1–2 周）

- 适配器：**Aider（架构压力测试）**、Gemini CLI、OpenCode（JSONC Writer 验收载体）
- 角色模型映射（main/weak/editor；primary/cheap）
- **`acm bind`：Agent 级持久绑定**（全局激活 + 每 Agent 覆盖的二级 Desired State；`use --agent` 保持一次性投影语义，两者不混淆）
- `acm profile list/show`、`acm use-vmr`、`acm vmr status`、`acm config migrate`
- 动态适配器热加载（`~/.acm/adapters/*.py` + importlib）+ 协议文档 + 模板
- `--json` 机器可读输出（状态机枚举直出）
- CI 全量金样回归 + 适配矩阵活文档充实（投影能力 / 无法表达 / 需转换清单）

### Phase 3：分发与社区（持续，触发式）

- Homebrew Tap（准入：出现明确的 macOS/Linux brew 习惯用户需求）
- pyapp 单二进制（准入：出现真实的非 Python 环境需求）
- 社区适配器贡献流程（fixtures 规范 + PR 模板 + 铁律检查清单）
- OpenClaw / Hermes；Cursor/Cline 仅公开 settings 通道评估；项目级 Profile 开放问题评估

---

## 13. 风险与对策

| 风险 | 概率 | 影响 | 对策 |
|---|---|---|---|
| **上游 Agent schema 漂移** | 高频 | 小（模型字段是稳定子集） | 适配器隔离（不跨 Agent 传染）+ 金样哨兵 + AI 辅助改适配器（贴官方文档）+ `acm doctor` 主动检测 |
| **Adapter 维护负担随 Agent 数量线性增长** | 高 | 高（ACM 长期成本主要是 Adapter，不是 Core） | 严格控制官方适配器数量（P0×3 / P1×3 起步）；每 Agent 独立模块 + 金样独立；能力矩阵文档化降低上下文成本；P2 开放社区适配器分流长尾；"支持更多 Agent"永远不作为目标本身 |
| cc-switch 补齐 CLI 与深度参数建模 | 中 | 中 | 不正面竞争；护城河是哲学（最小/专注/文件级尊重）与 VMR 原生协同，非功能清单 |
| 与其他配置管理工具共存（cc-switch / ccr 等） | 中 | 中 | **不保证共存**：同 Agent 被多个工具管理会导致互相覆盖、清单失效。README 明确风险提示：同一 Agent 只用一种配置管理工具（不做兼容检测） |
| Agent 运行中写文件覆盖 ACM 变更 | 低 | 中 | 进程守护分级 + 漂移检测 + 指纹校验 + 快照兜底（四层防御） |
| ACM 自身并发 / 崩溃导致中间状态 | 低 | 高 | 全局写入锁 + crash-safe 事务 journal + 启动恢复（§7.5.6/7.5.7）+ 故障注入测试 |
| VSCode 系扩展迁移到 SQLite 私有存储 | 中 | 高（仅 P2 Agent） | 铁律 2：没有干净通道就不支持，绝不写私有 DB |
| 密钥泄露 | 中 | 中 | credential 引用模型（§7.3.1）+ state 目录 0700 / 文件 0600 + 输出默认掩码 + doctor 明文告警；keychain 为后续可选项 |
| 多文件事务部分失败 | 低 | 中 | 指纹校验 + 跨文件按序提交 + 内存字节回滚 + 崩溃恢复 + 金样事务测试 |
| 单人项目维护连续性 | 中 | 高 | 代码量与 scope 严格受控（宁可不做，不做大）；退出条件成文（§4.2）；治理规格（v2.0）+ 实现参考（本文档）分层持续演进 |

---

## 14. 成功标准

**对内（第一优先）**：VMR 用户从"装好 VMR"到"本机 3+ 个 Agent 全部指向 VMR 虚拟模型"，全程 ≤ 3 条命令、≤ 1 分钟、零手工编辑配置文件、`acm release` 后零残留。

**对外（第二优先）**：一个不使用 VMR 的多 Agent 开发者，愿意把 ACM 纳入日常工具链的理由是--**"它只做模型配置这一件事，我从不必担心它弄坏我的配置文件，且它可以被脚本化嵌入任何工作流。"**

**非成功样貌（反面界定，出现任一即已失败）**：变成第二个 cc-switch（GUI 全家桶 / MCP 管理 / 内置网关 / 用量统计）；开始写私有数据库；适配器数量成为 KPI；Core Config 开始堆状态或密钥保管职责。

前者不达成则项目失去第一动因；后者不达成则项目退化为内部脚本。两条都成立，ACM 才值得作为独立开源仓库长期存在。**规格冻结声明：本文档之后停止继续扩充架构设计，进入工程验证阶段--下一步最有价值的信息来自把 Claude Code + Codex + Pi 三个真实适配器在 Safety Engine 上跑起来。**

---
---

## 附录 A：前置文档逐项裁决记录

> 《基于GLM版的ACM方案完善建议》V1/V2/V3 存在内部矛盾，下表为逐项独立裁决。裁决依据：第一性原理 + 事实核查（附录 B）+ 本机实证。docs/feedback-for-v1.0.md 三轮反馈的处理记录见该文档末尾，本附录不重复。

### A.1 建议文档内部四大矛盾的裁决

| 矛盾点 | V1 立场 | V2/V3 立场 | 裁决 | 关键依据 |
|---|---|---|---|---|
| MVP 首批适配器 | Claude Code + OpenClaw + Aider | Claude Code + Codex + Pi | **P0 = Claude Code + Codex + Pi；Aider 升为 P1 首位（压力测试）** | 本机实证：Aider/OpenClaw 未实际使用，第一动因是服务真实场景；架构覆盖缺口（YAML/角色模型/跨文件派生）由 P1 首位 Aider + Helper 级前置单测补齐（§6 D6） |
| Core Config 格式 | TOML -> YAML | 保持 TOML | **保持 TOML** | 双向读写场景 TOML 无歧义性更优；实际嵌套仅 3 层；Codex P0 使 tomlkit 零新增依赖（§6 D3） |
| 分发渠道 | 全通道矩阵 | 压缩为主路径 | **单一主路径（PyPI + uvx/uv tool），brew/pyapp 触发式后置 P3** | 为想象中的用户建设 CI 渠道是浪费（§6 D5） |
| 动态适配器热加载 | 尽早交付 | 推迟出 MVP | **架构预留、Phase 2 落地** | 先验证官方适配器质量，再开放第三方扩展（§6 D7） |

### A.2 V1 逐项裁决（新增补全类）

| # | 建议 | 裁决 | 说明 |
|---|---|---|---|
| 一.1 | 动态适配器热加载 | **推迟（P2）** | 见 A.1；协议层从第一天按可外部实现设计 |
| 一.2 | 全通道分发矩阵 | **拒绝进 MVP / 触发式后置** | 见 A.1 |
| 一.3 | protected_paths 黑名单 | **采纳** | 与白名单构成双重防线，进 ChangeSet 结构与阶段 1 校验 |
| 一.4 | 快照保留策略（20/Agent FIFO 可配置） | **采纳** | §7.5.3 |
| 一.5 | 三阶段事务提交标准化 | **采纳（v1.1 升级为 crash-safe）** | §7.5.1，v1.1 增加事务状态机与启动恢复 |
| 一.6 | `acm doctor` | **采纳（纳入 Phase 1 / MVP）** | §10/§12，扩展未完结事务/明文密钥/ENV 缺失检测与崩溃恢复入口 |
| 一.7 | `acm history` + 指定版本回滚 | **采纳（v1.1 修正语义）** | 显式分离为 `--to-tx`（字段级）与 `--snapshot`（`--hard`），见 §10.1 |
| 一.8 | 金样回归测试三步断言 | **采纳（强化）** | §11.1 |
| 一.9 | 进程守护交互 | **采纳（调整）** | 标准库实现不引入 psutil；v1.1 升级为分级表（§7.5.5） |
| 一.10 | 适配优先级矩阵 + 量化验收 | **采纳** | §8/§12 |
| 二.1 | Schema 表达能力升级 | **采纳** | §7.3；active_profile 存 state |
| 二.2 | Core Config 改 YAML | **拒绝** | 见 A.1 |
| 二.3 | 适配器契约标准化 | **采纳** | §7.4 |
| 二.4 | VMR 快捷指令 | **采纳（Phase 2）** | §9 |
| 二.5 | 多文件事务原子性 | **采纳（v1.1 强化）** | §7.5.1 + 崩溃恢复 §7.5.7 |
| 二.6 | Diff 输出 rich 高亮 | **采纳** | §10.1 |
| 三.1 | MVP 换 OpenClaw+Aider | **拒绝（吸收其内核）** | 见 A.1 |
| 三.2 | TOML->YAML | **拒绝** | 见 A.1 |
| 三.3 | Scope 刚性约束成铁律 | **采纳** | §5.4 |
| 三.4 | 明确退出/降级条件 | **采纳** | §4.2 |

### A.3 V2 逐项裁决

| # | 建议 | 裁决 | 说明 |
|---|---|---|---|
| 1 | 保留三层 Core Config 并明确职责边界 | **采纳** | §7.3 |
| 2 | Field Ownership 提升为核心架构原则 | **采纳（升级为全文纲领取向）** | §1 |
| 3 | 字段级回滚 + 冲突检测（不静默覆盖） | **采纳（v1.1 数据模型闭环）** | §7.5.2 |
| 4 | Adapter 只产出 ChangeSet | **采纳（强制约束）** | §7.1 |
| 5 | 适配映射矩阵为正式基准 | **采纳** | §8 |
| 6 | Agent Capability/Config Matrix | **采纳（P2 充实；v1.1 增加语义/投影双维度）** | §8/§7.4.1 |
| 7 | 金样体系为基础设施 | **采纳** | §11.1 |
| 8 | doctor/diff/dry-run 一等公民 | **采纳** | §10 |
| 9 | VMR Discovery/Import | **采纳** | §9 |
| 10 | VMR 是第一方集成非架构依赖 | **采纳（原文固化）** | §9 |
| 11–12 | 动态适配器后置 / MVP 克制 | **采纳** | D7/§12 |
| 13–14 | 弃用"市场空白" / 不拼数量与 GUI | **采纳** | §3.2/§4.1 |
| 15–16 | 非破坏性分级 / 否定 RFC 6902 | **采纳（v1.1 措辞再修正）** | §7.5.4 |
| 17–18 | 私有 DB 不碰 / 快照降级 Safety Net | **采纳（铁律化 / 三层体系）** | §5.4/D4 |
| 19–23 | 压缩分发 / 无 GUI / 热加载后置 / 无 Scope 膨胀 / 无过早插件生态 | **采纳** | D5/D7/§5 |
| 五 | 八层核心流水线 | **采纳（v1.1 扩展为十层）** | §7.1（v1.1 加入 Desired State 与指纹校验层） |
| 末 | 六件最值得做的 / 六件最应删的 | **全部覆盖 / 全部执行** | -- |

### A.4 V3 逐项裁决（仅列与上文不同或有新增信息者）

| # | 建议 | 裁决 | 说明 |
|---|---|---|---|
| 一.1 | 完整 CLI 规格 | **采纳** | §10 |
| 一.2 | P0 保持 Codex+Pi | **采纳（与独立判断一致）** | §6 D6 |
| 一.3–4 | P0 硬验收 / init 流程 | **采纳** | §12/§10 |
| 一.5–6 | 分层架构图 / init 自动化 | **采纳** | §7.2/§9 |
| 二.1 | 三阶段伪代码等安全细节 | **采纳** | §7.5 |
| 二.2 | active_profile | **采纳（一处修正：存 state）** | D3 |
| 三.2 | Python 3.11+、依赖 ≤4、锁定 uv | **采纳（基线上调至 3.12+）** | D2 |
| 三.5 | "过细伪代码不要" | **部分不采纳** | 三阶段提交与 ChangeSet 是安全语义的规范组成部分，保留 |

### A.5 从 Gemini/Sonnet 版直接吸收（需修正或未出现在建议文档）

| 来源 | 内容 | 裁决 | 说明 |
|---|---|---|---|
| Gemini | "市场绝对空白"表述及具体 issue 编号 | **拒绝** | 附录 B：star 数据核实为真，空白论被证伪；issue 编号不可考，改引官方 FAQ |
| Gemini | Claude Code 写 `~/.claude.json` | **拒绝（修正）** | 该文件为运行时状态，本机实证 ✔；只写 `settings.json` |
| Gemini/Sonnet | Pi 配置路径 | **拒绝（修正）** | 官方文档：用户文件为 `models.json`；`models-store.json` 为内部注册表绝不可写 ✔ |
| Sonnet | RFC 6902 作为非破坏写入 | **拒绝（修正）** | §7.5.4；采纳其 protected_paths 概念 |
| Sonnet | 内置 `core.yaml` 锚定 VMR | **部分吸收** | VMR 为默认初始 profile（init 生成），不内置于包内 |
| Sonnet | 快照 FIFO × 20 / Phase 验收 / init 流程 | **采纳** | §7.5.3/§12 |

---

## 附录 B：事实核查记录

核查时间：2026-08-17。方法：GitHub 仓库页实时抓取（firecrawl）+ 本机文件系统实证 + pi 官方文档。

| Claim | 来源 | 核查结果 |
|---|---|---|
| cc-switch 127.7k★ / 8.7k forks | GLM 版 | ✅ 属实（128k / 8.7k，GitHub 实时） |
| cc-switch 覆写破坏："切换后插件配置消失"，需手动配置 Shared Config Snippet 规避 | GLM 版 | ✅ **官方 FAQ 原文确认** |
| cc-switch issue #2992（Gemini 版）/ #3986（GLM 版） | 两版 | ⚠️ 不可考且互相矛盾，最终版不引用；以官方 FAQ 为准 |
| cc-switch Scope 膨胀（MCP/Prompts/Skills/会话管理/云同步/用量仪表盘） | 三版一致 | ✅ README Features 逐条证实 |
| cc-switch 内置本地代理（热切换/故障转移/熔断），与 VMR 同类竞争 | GLM 版 | ✅ README "Proxy & Failover" 节证实 |
| cc-switch GUI-first、CLI 薄弱 | GLM/Sonnet 版 | ✅ README 主打桌面应用/系统托盘/Deep Link；未见 CLI 支持 |
| cc-switch 中转商赞助墙运营 | GLM 版 | ✅ README 数十家 API 中转商赞助位 |
| Claude Code `~/.claude/settings.json` 含 `env` 块；`~/.claude.json` 为运行时状态 | GLM 版 | ✅ 本机实证；且实证存在 `effortLevel` 键 |
| Claude Code 支持 provider 热切换（无需重启） | - | ✅ cc-switch 官方 FAQ 提及（用于 WARN 级守护定级） |
| Codex 配置：顶层 `model` / `model_reasoning_effort`，`auth.json` 存 key，`mcp_servers` 表带注释 | 各版（细节不一） | ✅ 本机实证 |
| Pi 自定义 provider 文件为 `~/.pi/agent/models.json`；settings 含 defaultProvider/defaultModel/defaultThinkingLevel；`models-store.json` 为内部注册表 | GLM 版（部分） | ✅ pi 官方文档（models.md）+ 本机实证 |
| Aider / OpenClaw 在目标环境实际使用 | 各版（隐含假设） | ❌ 本机实证：非活跃使用--MVP 选型依据之一 |
| VMR（127.0.0.1:8800、虚拟模型、healthz） | 三版一致 | ⚪ 内部项目约定，视为设计输入 |
| "市场绝对空白" | Gemini 版 | ❌ 证伪；准确表述为细分生态位为空（§3.2） |
| `commentjson` / `jstyleson` 可作为 JSONC 注释保留方案 | v1.1 草案 | ❌ 实测证伪：二者解析时即剥离注释，`dumps` 写回丢失全部注释，无法满足 §7.5.4 注释保留硬要求；`commentjson` 0.9.0 依赖 `lark-parser` 且实测无法解析值后块注释 |

---

## 附录 C：核心术语表

| 术语 | 定义 |
|---|---|
| **SSOT** | Single Source of Truth。模型世界的事实描述只有一份，存于 Core Config；Agent 配置只是投影结果 |
| **Core Config** | `~/.acm/config.toml`：ACM 自有的 providers / models / profiles 三层声明式配置 |
| **Profile** | 命名的模型角色组合（main/cheap 等槽位），是投影的最小单元 |
| **Resolved Profile** | Profile 经 ENV 引用解析后的具体值集合 |
| **Desired State** | 激活 Profile（Phase 2 起含 per-agent 绑定）经编译后的字段级期望状态 |
| **Current State** | 各 Agent 配置文件中管理字段的实际落盘值 |
| **Projection / 投影** | 将 Desired State 转译写入目标 Agent 配置的动作 |
| **Adapter** | 每 Agent 一个的语义编译器：profile -> ChangeSet，不碰文件 |
| **ChangeSet** | 字段级变更集（文件、路径、旧值、新值、告警、黑白名单），Safety Engine 的唯一输入 |
| **FieldOp** | ChangeSet 中的单个字段操作 |
| **Managed Manifest** | `manifest.json`：ACM 当前拥有的字段、当前写入值、接管前原始值（pre_acm） |
| **Journal / 事务** | `journal.jsonl`：每次 ChangeSet 事务的完整历史与状态机（PREPARED/COMMITTING/COMMITTED/ABORTED），字段级回滚的数据来源 |
| **Snapshot** | 整文件快照，仅用于 `--hard` 灾难恢复、崩溃恢复与审计 |
| **Drift（漂移）** | 管理字段的磁盘值 ≠ ACM 最后写入值，说明被外部修改 |
| **OUT_OF_SYNC** | Current == ACM 最后写入值 ≠ Desired（ACM 侧配置已改动，无外部漂移，待 `apply` 收敛） |
| **Projection Loss** | Desired State 中目标 Agent 无法表达的字段，必须告警，不得静默丢弃 |
| **Round-trip** | 解析-修改-序列化过程中保留原文注释/键序/排版的能力 |
| **Format Writer** | 按格式划分的写入器，必须声明其保真能力（语义/注释/键序/空白） |
| **Release** | 按管理清单移除 ACM 注入的一切，恢复 pre-ACM 状态的退出操作 |

---

<!-- v1.1 实现参考结束。治理规格见 ACM_PROJECT_SPEC_v2.0.md；如与 v2.0 原则冲突，以 v2.0 为准，并回写修订本文档。 -->
