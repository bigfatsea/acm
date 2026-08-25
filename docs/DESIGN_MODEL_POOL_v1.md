# ACM 设计方案：Profile 模型池（Model Pool）投影

<!-- 版本: v1.0 | 状态: 已实施（见 §12 执行记录） | 日期: 2026-08-25 -->
<!-- 关联文档: ACM_PROJECT_PRINCIPLE_v2.1.md §2.2(L2) · ACM_PROJECT_SPEC_v2.1.md §7/§8 · USER_GUIDE.md §3.9/§7.3 -->

---

## 目录

- [0. TL;DR](#0-tldr)
- [1. 需求与背景](#1-需求与背景)
- [2. 现状核实（代码事实与本机实证）](#2-现状核实代码事实与本机实证)
- [3. 设计目标与原则对齐](#3-设计目标与原则对齐)
- [4. 配置设计](#4-配置设计)
- [5. 三类 Agent 的适配逻辑](#5三类-agent-的适配逻辑)
- [6. 使用全流程走查](#6-使用全流程走查)
- [7. 数据流与不变量分析](#7-数据流与不变量分析)
- [8. 实现方案（逐文件）](#8-实现方案逐文件)
- [9. 测试计划](#9-测试计划)
- [10. 边界情况与决策记录](#10-边界情况与决策记录)
- [11. 方案复核结论](#11-方案复核结论)
- [12. 执行记录（2026-08-25 落地）](#12-执行记录2026-08-25-落地)
- [13. 独立复核（2026-08-25，第二轮全面审查）](#13-独立复核2026-08-25第二轮全面审查)
- [14. 复核问题处置与第三轮复核（2026-08-25）](#14-复核问题处置与第三轮复核2026-08-25)
- [15. 13.8 的重新处置：实现 Pi headers 投影（2026-08-25）](#15-138-的重新处置实现-pi-headers-投影2026-08-25)
- [16. 第四轮全面复核（2026-08-25）](#16-第四轮全面复核2026-08-25)
- [17. §16 三项中高严重度问题的处置与收尾复核（2026-08-25）](#17-16-三项中高严重度问题的处置与收尾复核2026-08-25)

---

## 0. TL;DR

**需求**：在一个 profile 中声明多个模型；投影后，支持多模型的 Agent（如 Pi）的 `/model` 选择器中出现全部模型供用户手工切换；不支持多模型的 Agent 只配 `main`；本身具备语义角色、会自动在角色间切换的 Agent（如 Aider）按 label 自动分配到对应角色槽位。

**方案核心**：在 profile 下引入 **`[profiles.<name>.pool]` 子表**，用 **map（label → 模型别名）** 表达模型池。label 是语义标签，承担双重职责：

| Agent 能力类型 | label 的用途 | 投影行为 |
|---|---|---|
| **I. 扁平模型池**（Pi） | 次要详情文本（`name` 字段）；`/model` 列表本身按 `id` 展示（见 §13.1 事实核实） | 全部成员注册进 `models.json` |
| **II. 无池能力**（Claude Code / Codex） | 无处安放 | 仅投影 `main`；其余成员产生聚合投影损失告警 |
| **III. 语义角色型**（Aider，P1） | 映射到角色槽位：`main→model`、`weak→weak-model`、`editor→editor-model` | 按 label 写入对应角色字段；未识别 label 告警 |

**改动面**：config 校验、resolve、pi 适配器 plan()、金样 fixtures；**Safety Engine / state / status / CLI / 退出码零改动**（op 粒度是整个 provider 条目，天然兼容）。

---

## 1. 需求与背景

### 1.1 原始诉求（用户原话归纳）

> 所有 Agent 系统都有 `/model` 指令可以切换不同模型。……我们希望的是，在一个 profile 下面有多种不同的模型，配进去之后，比如配到 Pi Agent，通过 `/model` 切换的时候这几个模型都能出现并由用户手工选择。而不是像现在只能配一个 main。
>
> 对于 Aider 这种本身支持多模型、而且它的模型是有语义的（会自动在多模型之间 switch）的情况，是不是我们的模型池可以用 **map** 来表达？给每一个模型赋予一个合理的标签 label。这样对会自动根据 label 去 switch 的系统就成立了；对于不支持的，就直接用 label 作为它的名字。

### 1.2 为什么这是设计阶段缺口

规格 v2.1 的 L2 定义（§2.2）只覆盖"主模型 + 角色模型"，profile 语义是"角色绑定"而非"可选集合"。当前三个适配器全部只消费 `profile.main`；`cheap`/自定义角色被定义为"无法表达 → 投影损失告警"。**没有任何机制把一组模型整体注册进 Agent 的可选列表。**

### 1.3 目标场景

```
                     ┌─ Pi:        /model 里出现 coding/cheap/agent 三个，手选
acm use daily ───────┼─ Claude Code: 只有 coding 生效（main），其余告警
(profile 含 3 模型)  ├─ Codex:      只有 coding 生效（main），其余告警
                     └─ Aider(未来): model=coding, weak-model=cheap,
                                     editor-model=review（按 label 自动分流）
```

---

## 2. 现状核实（代码事实与本机实证）

> 本章所有论断均有可复查的证据来源。

### 2.1 ACM 当前实现的事实

| # | 事实 | 证据位置 |
|---|---|---|
| F1 | Pi 适配器每个 provider 条目只写 1 个模型 | `src/acm/adapters/pi.py:85-92`：`provider_payload = {..., "models": [model_entry]}` |
| F2 | 三个适配器只消费 `profile.main` | `claude_code.py:57`、`codex.py:54`、`pi.py:85,108` —— 无任何一行读取 `cheap`/extra_roles 用于投影 |
| F3 | cheap/extra roles 一律产生投影损失告警 | `adapters/__init__.py:51-59`（`check_unsupported_profile_specs`） |
| F4 | op 粒度 = 整个 provider 条目（dot-path `providers.<name>` 整体替换） | `safety.py` Step 3 + `pi.py:100-107` |
| F5 | 白名单 namespace 为 `providers` 整体 | `pi.py managed_namespaces()` |
| F6 | ProfileConfig 允许任意额外键，但仅字符串值被当作角色解析；**非字符串值（如 list/dict）当前被静默忽略** | `config.py:74`（`extra="allow"`）+ `config.py` 校验循环 `isinstance(extra_val, str)` + `resolve.py:180-182` 同样的 isinstance 守卫 |
| F7 | 漂移检测比对 last_write 记录的整个 payload 值（dict 相等比较），敏感键递归掩码 | `status.py:detect_agent_drift` + `masking.py:mask_secrets_in_obj` |

**F6 的推论（重要）**：今天在 config.toml 里写 `[profiles.daily.pool]` 子表不会报错也不会生效——它作为非字符串 extra 被**静默跳过**。这意味着引入 pool 语义**不存在语法冲突**，且是平滑"转正"；但过渡期语义变化必须在发布说明中告知（见 §10-D8）。

### 2.2 各 Agent 配置通道的本机实证与文档核实

#### Pi Agent —— ✅ 扁平模型池，完全可行

证据（本地包内官方文档 `@earendil-works/pi-coding-agent@0.84.1/docs/`）：

- `docs/models.md`："Add custom providers and models … via `~/.pi/agent/models.json`"；Full Example 展示 provider 条目含 `models: [{id, name?, reasoning?, input?, contextWindow?, maxTokens?, cost?}]` **数组**；`name` 为可选显示名字段。
- `docs/models.md`："The file reloads each time you open `/model`. Edit during session; no restart needed." —— `/model` 列表直接由该文件驱动。
- `docs/extensions.md` + `docs/custom-provider.md`：extension `pi.registerProvider()` 与 models.json 叠加（"models.json overrides still apply above it"）；两通道并存。
- 本机实证：`~/.pi/agent/settings.json` 存在 `defaultProvider`/`defaultModel`/`defaultThinkingLevel`；用户的 `extensions/vmr.ts` 用 registerProvider 注册了 3 个模型（cheap/agent/coding）并在 `/model` 可见 —— 即"多模型池 + 手选"在 Pi 上已被用户手工跑通。

#### Codex CLI —— ❌ 无公开的模型池注册通道（本类 II）

本机实证（codex 0.148.0）：

- `~/.codex/models_cache.json`：`{"fetched_at": ..., "etag": ..., "client_version": ..., "models": [{"slug": "gpt-5.6-terra", "display_name": ...}]}` —— **`/model` 的候选目录是从服务端拉取并缓存的**，不由 config.toml 注册。
- `~/.codex/config.toml`：顶层 `model = "gpt-5.6-terra"` 仅为默认选中项。
- `codex --help`：存在 `-p, --profile <CONFIG_PROFILE_V2>`（分层叠加 `$CODEX_HOME/<name>.config.toml`）——那是**配置文件分层**，不是模型池。

结论：ACM 对 Codex 只能设默认模型（现状即正确做法）；强行注册模型目录没有公开稳定通道（违反铁律 2：没有公开、稳定、可安全修改的配置接口就不扩展该能力）。

#### Claude Code —— ❌ 无模型注册通道（本类 II）

本机实证：`~/.claude/settings.json` 全部键为 `env`/`permissions`/`hooks`/`effortLevel` 等，**无任何模型目录/注册表字段**；`model` 字段仅为默认值。`/model` 列表来自内置目录。

#### Aider —— ⚠️ 语义角色型（本类 III，P1 交付时金样校准）

证据等级说明：本机未安装 aider（`which aider` 未命中），以下基于两处来源交叉：

1. ACM 规格文档（`ACM_PROJECT_SPEC_v2.1.md` §8 P1 表 + §2.2）："`~/.aider.conf.yml` + `~/.aider.model.metadata.json`；角色模型（main/weak/editor）"；L2 定义明确举例"Aider 的 main/weak/editor"。
2. Aider 公开文档的稳定常识：`--model` / `--weak-model` / `--editor-model` 三个角色槽位；`weak-model` 被 aider 自动用于 git commit message 等轻任务，`editor-model` 用于 editor 工作流；用户可用 `/model` 手动切主模型。

> ⚠️ 标注：aider 适配器属 P1，本文给出设计契约；**具体字段名与派生 JSON 行为在 P1 实施时以官方文档 + 金样 fixtures 校准**（规格既定流程）。

### 2.3 Agent 能力分类学（本方案的分类基础）

| 类型 | 定义 | 本方案中的 Agent |
|---|---|---|
| **I. 扁平模型池** | 配置文件原生支持"一个 provider 下多个并列模型"，且运行期选择器消费该列表 | **Pi**（models.json `models[]`） |
| **II. 单默认模型** | 公开配置通道只有"默认模型"一个槽位，候选目录内置或服务端下发 | **Claude Code**、**Codex** |
| **III. 语义角色型** | 配置文件含多个具名角色槽位，Agent 运行期**自动**在不同角色间分流 | **Aider**（main/weak/editor，P1） |

---

## 3. 设计目标与原则对齐

| 原则 | 本方案如何满足 |
|---|---|
| 公理 2 非破坏性 | pool 只写入适配器声明的受管 namespace（`providers.*`），不新增可写路径 |
| 显式暴露 | 类型 II Agent 无法表达 pool 成员时，必须产生聚合告警，绝不静默丢弃 |
| 精准可逆 | op 粒度不变（整条 payload），快照/回滚/Journal 机制零改动 |
| SSOT | 模型池的唯一描述仍在 `config.toml`；各 Agent 只是投影目标 |
| 零破坏升级 | 不写 pool 的既有配置行为逐字节不变（金样回归保证） |
| 幂等 | payload 相等比较天然覆盖多模型数组 |

---

## 4. 配置设计

### 4.1 语法

在 profile 下新增保留子表 `pool`，**map 形式**（label → 模型别名）：

```toml
version = 1

[providers.vmr]
protocol = "openai"
base_url = "http://127.0.0.1:8800/v1"
api_key  = "${VMR_KEY:-}"

# ── L2：池中的每个成员仍是完整的单模型规格 ──────────────
[models.coding]
provider        = "vmr"
id              = "coding"
context_window  = 512000
max_output_tokens = 128000

[models.cheap]
provider       = "vmr"
id             = "cheap"
context_window = 256000
max_output_tokens = 96000

[models.agent]
provider        = "vmr"
id              = "agent"
context_window  = 512000
max_output_tokens = 128000

[models.o3]
provider = "openai-direct"
id       = "o3"

# ── L3：profile + 模型池 ────────────────────────────────
[profiles.daily]
main = "coding"                    # 默认选中（必填，语义不变）

[profiles.daily.pool]
default = "coding"                 # label → [models.*] 别名
budget  = "cheap"
longctx = "agent"
review  = "o3"
```

### 4.2 语义规则

| 规则 | 内容 | 理由 |
|---|---|---|
| R1 | `pool` 是 **map**（label → 模型别名），不是数组 | label 承担语义标签职责（§5 类型 III 的角色映射 + 类型 I 的显示名） |
| R2 | **`main` 隐式入池**：即使 pool 未显式列出 `main` 引用的模型，也以 label `main` 自动补入池首 | 保证"默认项永远在池中"；显式列出亦可（去重） |
| R3 | **保留 label 词表**：`main`、`default`（二者同义，均指主模型）、`weak`、`editor` | 与已知语义角色型 Agent（Aider）的槽位名对齐；其余 label 为自由标签 |
| R4 | 同一 pool 内**禁止两个 label 指向同一模型别名**（校验错误） | 避免 Pi models 数组出现重复 id 的歧义 |
| R5 | pool 值引用的 `[models.*]` 别名**必须存在**（复用现有交叉引用校验模式，错误信息风格一致） | 一致性 |
| R6 | pool 成员可跨 provider（分组投影，见 §5-I）；`main` 所属 provider 决定 `defaultProvider` | 真实场景（主力走 VMR、审查走直连） |
| R7 | `pool = {}` 空表视同未声明 | 便于注释掉内容而保留结构 |
| R8 | **`cheap` 角色键语义完全不变**（仍为角色槽位，在当前三适配器上照旧告警）；pool 与 roles 是相互独立的两个特性，不做隐式转换 | 避免"同一配置在不同 Agent 上行为分裂"的心智负担；向后兼容 |

### 4.3 校验规则汇总（实现于 `CoreConfig.model_validator`）

```
E1 pool 值引用不存在的 model 别名           → ValueError（风格同现有 "is not defined under [models]"）
E2 同一 pool 内重复引用同一别名             → ValueError "duplicate model alias 'X' in pool"
E3 label 为空字符串                          → ValueError
E4 pool 值非字符串（如写成嵌套表）           → ValueError（pydantic dict[str,str] 天然拦截）
E5 label 使用保留词 main/default 以外的保留词（当前仅 weak/editor，为自由标签预留空间，不作硬限制）
   —— 注意：weak/editor 不禁止自由使用；它们只在类型 III Agent 上有特殊含义
```

### 4.4 解析后的内部形态

```python
ResolvedProfile(
    profile_name="daily",
    main=ResolvedModel(upstream_id="coding", ...),
    cheap=None,
    extra_roles={},
    pool={                       # 新增：有序 dict（Python 3.7+ 保序）
        # 订正（§13.5-2）：本例的 "default" 是 §4.1 配置里用户显式写的 label，不是隐式补入——
        # 因为其别名 "coding" 已等于 main，resolve_profile() 判定"main 已在池中"而不会再插入。
        # 若用户在 §4.1 省略这一行，隐式补入的 label 固定为字面量 "main"（非 "default"），
        # 与 R2/resolve.py:192-197 及测试 test_resolve_pool_implicit_main_prepended 一致。
        "default": ResolvedModel(upstream_id="coding", provider=vmr, ...),
        "budget":  ResolvedModel(upstream_id="cheap",  provider=vmr, ...),
        "longctx": ResolvedModel(upstream_id="agent",  provider=vmr, ...),
        "review":  ResolvedModel(upstream_id="o3",     provider=openai_direct, ...),
    },
)
```

---

## 5. 三类 Agent 的适配逻辑

### 5.1 类型 I —— 扁平模型池（首发：Pi）

#### 怎么配（用户视角）

见 §4.1 示例。要点：pool 里放你想在 `/model` 里看到的**全部**模型；`main` 指定默认选中。

#### 怎么投影（ACM 行为）

`plan()` 编译规则：

1. **按 provider 分组**：遍历 pool（保序），把成员按其所属 provider 分组；
2. 每个 provider 生成一条 `providers.<name>` op，payload：

```jsonc
{
  "baseUrl": "<provider.base_url>",
  "api": "<方言映射，规则不变>",
  "apiKey": "<凭据解析，规则不变：$VAR / 解析值 / dummy+告警>",
  "models": [
    { "id": "<upstream_id>", "name": "<label>", "contextWindow": ..., "maxTokens": ... },
    ...
  ]
}
```

   **label 落点：模型条目的 `name` 字段**（Pi 的可选人类可读标签字段）——这是"不支持的就用 label 作为它的名字"的落地；`id` 始终是发给上游 API 的真实模型标识，不受 label 影响。**表述订正（见 §13.1）**：经重新核对 Pi 官方文档（`docs/models.md` L202/L236-237），`/model`、`--list-models` 与交互式 footer **按 `id` 展示条目**，`name` 仅用于 `--model` 模式匹配和**次要详情文本**，并不替换主展示位。功能内核不变——池内全部模型仍会出现在 `/model` 供手选——但用户看到的主要是 upstream `id`（如 `cheap`），label（如 `budget`）只是辅助信息，而非"选择器里显示的名字"。
3. `settings.json`：`defaultProvider` = main 所属 provider 名；`defaultModel` = `main.upstream_id`；`defaultThinkingLevel` = `main.reasoning.effort`（如有）。规则与现状一致；
4. **排序确定性**：池内顺序 = pool 声明序；`main` 若为隐式补入则置于首位，若显式声明则保持声明位置（保证幂等输出稳定）；
5. **告警策略**：pool 存在时，pool 成员不再触发 `roles.cheap`/`roles.extra` 类告警（它们已被表达）；`temperature`/`capabilities`/`budget_tokens`/`proxy` 等 Pi 确实无法表达的项照旧逐项告警。**`headers` 例外**（见 §15 订正）：Pi 官方文档确认支持 provider 级 `headers` 字段，因此 ACM 会将其**投影**进 `providers.<name>.headers`（main 与 pool 成员的 provider 分组均适用），不再告警。**后续再订正两处（见 §17）**：`capabilities.vision` 经核实可由模型级 `input` 字段表达，改为投影而非告警；`temperature` 的告警措辞改为"ACM 未投影（Pi 本可经 openai 方言下的模型级 samplingParams 表达）"，消除事实性错误。

#### 会话内怎么切（Agent 行为，非 ACM 职责）

- 用户打开 `/model` → Pi 重载 models.json → 列表**按 upstream id 展示**（如 `coding`、`cheap`、`agent`），label（`default`/`budget`/`longctx`）作为次要详情文本辅助辨识，及 extension 注册的其他条目 → 手选即生效（见 §13.1 表述订正）；
- `acm use <另一profile>` → ACM 重写 payload → 下次打开 `/model` 生效；
- 二者互不干扰：`/model` 的临时选择存于 Pi 会话状态，不改文件；ACM 改的是文件里的默认与池。

#### 与 extension 的共存

不变（见 USER_GUIDE §7.3）：ACM 绝不触碰 `extensions/`；建议命名隔离避免同名 provider 条目互相覆盖。

### 5.2 类型 II —— 无池能力（Claude Code / Codex，及未来同类）

#### 怎么配

无需特殊处理：同一个 config.toml、同一个 profile。pool 写一次，全 Agent 通用。

#### 怎么投影（ACM 行为）

1. 与现状完全相同：只投影 `main`（连接层 + 默认模型 + effort）；
2. **聚合告警**（新增逻辑）：对该 Agent 输出一条投影损失告警，列出被跳过的池成员：

```
⚠️  Projection warning for [claude_code]: pool - Claude Code has no model-pool channel;
    skipped pool members: budget(cheap), longctx(agent), review(o3). Only main is projected.
```

   采用**一条聚合告警**而非逐成员 N 条：信息完整且不刷屏；字段名统一为 `pool`；
3. 幂等/no-op/漂移判断不受影响（ops 集合与现状同构）。

#### 会话内怎么切

`/model` 仍可用，但候选来自 Agent 内置/服务端目录（Codex 的 `models_cache.json`、Claude Code 内置清单）——这是 Agent 自身能力，与 ACM 无关，也不受 pool 影响。用户切 profile 时用 `acm use`。

### 5.3 类型 III —— 语义角色型（Aider，P1 契约）

#### 怎么配

同一个 pool。**label 就是角色语义**：

```toml
[profiles.daily]
main = "coding"

[profiles.daily.pool]
main   = "coding"      # 或省略（R2 隐式补入）
weak   = "cheap"       # aider 自动用于 git commit 等轻任务
editor = "o3"          # aider editor 工作流
```

#### 怎么投影（P1 适配器契约，实施时金样校准）

| pool label | 写入 `~/.aider.conf.yml` 的键 | 说明 |
|---|---|---|
| `main` / `default` | `model:` | 主模型（`/model` 手切的也是它） |
| `weak` | `weak-model:` | aider 自动分流：commit message、简单任务 |
| `editor` | `editor-model:` | editor 工作流自动使用 |
| 其他自由 label | —— | **投影损失告警**：`aider has no role slot for label '<label>'` |

- YAML round-trip（ruamel）+ 元数据 JSON 派生逻辑按规格 §8 P1 既定设计执行；
- **这就是 map 表达的价值**：同一份 pool，Pi 把 label 当显示名，Aider 把 label 当角色名——**语义跟着 label 走，而不是跟着 Agent 走**。

#### 会话内怎么切

Aider 的自动分流是其运行期能力（weak/editor 由 aider 按任务类型自动选用）；用户 `/model` 手切的永远是主模型。ACM 负责"这套角色组合的整体切换"（`acm use`）。

### 5.4 能力矩阵（新增一行）

| Desired setting | Claude Code | Codex CLI | Pi | Aider(P1) |
|---|---|---|---|---|
| **model pool（`[profiles.*.pool]`）** | ⚠️ 聚合告警，仅 main 生效 | ⚠️ 聚合告警，仅 main 生效 | ✅ 全员注册进 models.json，label→`name` | ✅ label→角色槽位映射 |

---

## 6. 使用全流程走查

以"VMR 三模型（coding/cheap/agent）+ 直连 o3 审查"为例：

```bash
# ① 初始化（D7 设计的"探测到 ≥2 模型时 init 提案自动生成带 pool 的 daily"尚未实施，
#    见 §12.6；当前 acm init 生成的提案不含 pool，需按 ② 手工添加）
acm init

# ② 编辑确认池成员（本例假设已按 §4.1 配好）

# ③ 一次性投影到所有 Agent
export VMR_KEY=sk-xxx OPENAI_API_KEY=sk-yyy
acm use daily
#   Pi:          providers.vmr 注册 4 条目中 vmr 组 3 模型(coding/cheap/agent) +
#                openai-direct 组 1 模型(o3)；defaultModel=coding
#   Claude Code: 仅 coding；告警列出跳过的 budget/longctx/review
#   Codex:       仅 coding；同上告警

# ④ 会话内
#   Pi 里 /model → 选 cheap（本次会话生效，文件不动）
#   下次启动 Pi → 回到 defaultModel=coding

# ⑤ 整体换场景
acm use budget        # 所有 Agent 默认切到 budget.main；Pi 池同步换成 budget.pool
acm status            # 全绿

# ⑥ 反悔
acm rollback pi       # Pi 恢复投影前快照（含旧池 payload）
```

漂移场景：用户手动从 `models.json` 删掉一个池成员 → `providers.vmr` payload ≠ last_write → `DRIFTED` → `use` 阻断 → `--force` 恢复。机制零变化。

---

## 7. 数据流与不变量分析

沿数据流逐环节验证 pool 的侵入面：

```
config.toml ──load/validate──▶ CoreConfig ──resolve──▶ ResolvedProfile
                                                            │ adapter.plan()（纯函数）
                                                            ▼
                                                     [PlannedOp] ──Safety Engine──▶ 磁盘
                                                            │                        │
                                            last_write.json ◀────── Step 6 ──────────┘
                                                            │
                                              drift 检测 / rollback ◀─ snapshots/
```

| 环节 | 是否受影响 | 分析 |
|---|---|---|
| load/validate | ✅ 改 | 新增 pool 校验（§4.3 E1–E4） |
| resolve | ✅ 改 | `ResolvedProfile.pool`；**reachable 集合必须纳入 pool 成员**（否则跨 provider 成员的 `${ENV}` 缺失不会被提前发现——复核时发现的遗漏点，详见 §11-R2） |
| plan() | ✅ 改 | 仅 pi.py（本轮）+ 未来 aider.py；claude_code/codex 仅加聚合告警 |
| PlannedOp 结构 | ❌ 不变 | 仍是 `{file, path, new}`，path 仍为 `providers.<name>` |
| Safety Engine 六步 | ❌ 不变 | payload 变大不影响任何步骤；AST tree-diff 断言按 managed namespace 忽略 `providers.*` 整域 |
| last_write | ❌ 不变 | `fields` 键仍是 `"models.json::providers.vmr"` → 整个新 payload 作 value |
| drift 检测 | ❌ 不变 | dict 相等比较；掩码递归覆盖 `apiKey` |
| rollback | ❌ 不变 | 快照整文件还原；last_write 从磁盘按 dot-path 重建（读回整条 provider payload） |
| status 六态机 | ❌ 不变 | 经 plan() ops 比较，自动适应 |
| CLI/退出码 | ❌ 不变 | 无新命令、无新选项 |

**架构结论：本特性是纯"编译层"（schema + resolve + plan）扩展，执行层与状态层天然兼容。** 这是当初"adapter 产出 ChangeSet、Safety Engine 统一执行"契约带来的红利。

**已知盲区（D11，§13.7 补记）**：op 模型只有 upsert 没有 tombstone——跨 provider 池收缩/切换后，磁盘上不再被新 plan() 覆盖的旧 `providers.<name>` 条目会累积残留，且 ACM 对其完全失明（drift/status 均检测不到）。这是当前架构下的有意识取舍，非本轮遗漏；细节与理由见 §10-D11。

---

## 8. 实现方案（逐文件）

> 本轮只交付设计，不动代码。以下为实施蓝图。

### 8.1 `src/acm/config.py` —— schema 与校验

```python
class ProfileConfig(BaseModel):
    model_config = ConfigDict(extra="allow")
    main: str
    cheap: str | None = None
    pool: dict[str, str] | None = None      # 新增；label -> [models.*] 别名
```

在 `CoreConfig.validate_cross_references` 中追加：

```python
for profile_name, profile_cfg in self.profiles.items():
    if profile_cfg.pool is not None:
        seen_aliases: set[str] = set()
        for label, alias in profile_cfg.pool.items():
            if not label.strip():
                raise ValueError(f"Pool label must be non-empty in profile '{profile_name}'.")
            if alias not in self.models:
                raise ValueError(
                    f"Profile '{profile_name}' pool label '{label}' references "
                    f"non-existent model '{alias}'."
                )
            if alias in seen_aliases:
                raise ValueError(
                    f"Duplicate model alias '{alias}' in pool of profile '{profile_name}' "
                    f"(each pool member must be unique)."
                )
            seen_aliases.add(alias)
```

**为什么**：复用既有校验位置与错误风格；R2 的"main 隐式入池"放在 resolve 层而非校验层——校验只管"声明合法性"，"补全默认"是解析语义。

### 8.2 `src/acm/resolve.py`

```python
class ResolvedProfile(BaseModel):
    ...
    pool: dict[str, ResolvedModel] = Field(default_factory=dict)   # 新增，保序
```

`resolve_profile()` 改动三点：

1. **reachable 集合纳入 pool 成员**（关键正确性修复，否则跨 provider 的 `${VAR}` 缺失检测失效）：
   ```python
   if profile_cfg.pool:
       reachable_model_keys.update(a for a in profile_cfg.pool.values() if a in core_config.models)
   ```
2. 构造 `pool` dict：先按声明序放入显式成员；若 main 别名不在其中，以 label `"main"` 插入队首；
3. pool 成员经 `_resolve_model()` 解析，ENV 硬失败语义与现有完全一致（缺失变量 ⇒ 整体中止、零写盘）。

**为什么**：pool 成员与角色成员同为"可达模型"，凭据解析必须一视同仁。

### 8.3 `src/acm/adapters/pi.py` —— plan() 重写投影段

```python
def plan(profile, env=None):
    ...
    if profile.pool:
        groups: dict[str, list[tuple[str, ResolvedModel]]] = {}   # provider_name -> [(label, model)]
        for label, m in profile.pool.items():                     # 保序
            groups.setdefault(m.provider.name, []).append((label, m))
        for prov_name, members in groups.items():
            m0 = members[0][1]
            api_key_val, warn = _resolve_pi_api_key(m0.provider, env_map)  # 抽出既有逻辑复用
            models_arr = [
                _pi_model_entry(label, m)          # {"id": m.upstream_id, "name": label,
                                                   #  "contextWindow"?: ..., "maxTokens"?: ...}
                for label, m in members
            ]
            ops.append(PlannedOp(file=models_file,
                                 path=f"providers.{prov_name}",
                                 new={"baseUrl": m0.provider.base_url,
                                      "api": _dialect(m0.provider.protocol),
                                      "apiKey": api_key_val,
                                      "models": models_arr}))
            warnings.extend(warn)
        # settings.json 三键逻辑不变，仍取 profile.main
    else:
        ...  # 现有单模型路径原样保留
    # 告警调整：pool 非空时不再对 cheap/extra_roles 发 roles.* 告警（已表达）
```

`_pi_model_entry(label, m)`：`id`=upstream_id；`name`=label；`contextWindow`/`maxTokens` 取自该成员自己的 L2 规格（**每个池成员携带各自的 context_window/max_output_tokens**——这是比现状更强的能力，现状连单模型的这两个字段都写，保持）。

**为什么按 provider 分组而不是限制单 provider**：§4.2-R6 场景真实存在；分组后每条 op 依然是"整条 provider payload 替换"，白名单/幂等/回滚全部免改。

### 8.4 `src/acm/adapters/claude_code.py` / `codex.py` —— 聚合告警

在各自 plan() 尾部追加：

```python
if profile.pool:
    skipped = [f"{lbl}({m.upstream_id})" for lbl, m in profile.pool.items()
               if m.upstream_id != profile.main.upstream_id]
    if skipped:
        warnings.append(ProjectionWarning(
            field="pool", agent_id=AGENT_ID,
            reason=f"{DISPLAY_NAME} has no model-pool configuration channel; "
                   f"skipped pool members: {', '.join(skipped)}. Only main is projected."
        ))
```

同时调整这两处对 `check_unsupported_profile_specs` 的调用为**精确豁免**：仅当某角色的目标模型别名已被本 profile 的 pool 表达（即 pool 中存在指向同一别名的成员）时，才豁免对应的 `roles.cheap` / `roles.extra` 告警；未被 pool 表达的角色照旧告警。temperature 等其余检查不变。

**为什么是精确条件而不是"pool 非空即豁免"**：D4 决策下 cheap 与 pool 相互独立——若用户声明了 `cheap = "haiku"` 但池中并无 haiku，该角色仍未被任何通道表达，静默吞掉告警将违反显式暴露原则。

**为什么聚合为一条**：显式暴露原则要求"不静默"，但 N 条同质告警损害信噪比；一条列全名单信息等价。

### 8.5 `src/acm/adapters/__init__.py`

> **本节已被 §12.3-2 取代**（保留作历史设计记录，请勿按本节字面实施）：实际交付未使用下方的布尔开关，改为 `pool_covered_model_ids: set[str] | None` 精确豁免（按模型别名而非布尔全豁免），原因见 §12.3-2。

`check_unsupported_profile_specs()` 增加 `skip_role_warnings: bool = False` 参数（或等价地由调用方条件调用），服务于 8.4 的去重逻辑。AdapterProtocol **不新增方法**——pool 是 plan() 内部编译细节，协议面保持最小。

### 8.6 测试资产

| 文件 | 改动 |
|---|---|
| `tests/unit/test_config.py` | E1–E4 校验用例；pool={} 视同未声明；pool 与 cheap 并存 |
| `tests/unit/test_resolve.py` | pool 解析、隐式 main 补入与排序、跨 provider reachable/ENV 缺失中止 |
| `tests/golden/test_adapters_pi.py` + `tests/fixtures/pi/models.golden.json` | 新增多模型双 provider 金样；正向三步断言（Apply 正确 / 非管字段无损 / 回滚存活）沿用 |
| `tests/integration/test_cli_use.py` / `test_cli_pi.py` | 带 pool 的 use 幂等（二次 no-op）、status SYNCED、drift→force 流 |
| `tests/golden/test_adapters_claude.py` / codex | pool 聚合告警断言 |

### 8.7 文档

README（特性列表+示例）、USER_GUIDE 双语（§3.9 补 pool、§4.3 校验表、§5.4 profile 参考、§7.3 配方更新为"原生 pool"、§7.4 矩阵行）、规格修订建议（Principle §2.2 L2 措辞补"可选模型池"；Spec §7 触发表新增一行：*"pool 投影 —— 触发条件：用户需要在支持多模型的 Agent 中批量维护可选模型（已触发，随 Pi 适配器增强交付）"*）。

### 8.8 明确不做的（防蔓延）

- 不给 Claude Code/Codex 寻找 hack 通道注册模型池（违反铁律 2）；
- 不改 AdapterProtocol 契约面；
- 不在本轮引入 `acm bind`（per-agent 差异化 profile 绑定是另一个触发式特性）；
- 不做 pool 的跨 profile 继承/复用（YAGNI，出现真实需求再说）。

---

## 9. 测试计划

| 层级 | 用例要点 |
|---|---|
| 单元·config | §4.3 E1–E4 全覆盖；`pool` 与 `cheap` 并存合法；空 pool 合法 |
| 单元·resolve | 隐式 main 补入次序；跨 provider reachable；ENV 缺失 → ConfigError 且 exit 1 |
| 金样·pi | (a) 双 provider 四成员 payload 精确匹配；(b) 未管字段（注释、其他 provider 条目）无损；(c) 投影→篡改→rollback 后 Agent 期间写入的状态存活 |
| 金样·claude/codex | pool 聚合告警文案断言；主模型投影与现状逐字节一致（回归保证） |
| 集成 | `use` 幂等二次 no-op；`status` SYNCED；外部删池成员 → DRIFTED → force 收敛 |
| 故障注入 | 沿用现有矩阵（SIGKILL/锁竞争/并发篡改）——执行层未变，预期全绿，作回归门禁 |

---

## 10. 边界情况与决策记录

| # | 决策 | 结论 | 理由 |
|---|---|---|---|
| D1 | pool 用数组还是 map | **map** | label 需同时服务类型 I（显示名）与类型 III（角色映射）；数组无法承载语义 |
| D2 | main 与 pool 的关系 | main 必填不变；隐式入池 | 向后兼容；"默认项必在池中"是健全性约束 |
| D3 | 保留 label 词表 | `main`/`default`/`weak`/`editor`；其余自由 | 与已知类型 III Agent 槽位对齐；不禁止自由使用（类型 I 上都是显示名） |
| D4 | pool 与 cheap 角色的关系 | 相互独立，不隐式转换 | 防止同一配置跨 Agent 行为分裂；cheap 维持现状 |
| D5 | 跨 provider pool | 支持，按 provider 分组投影 | 真实需求；op 粒度天然兼容 |
| D6 | 重复别名 | 校验错误 E2（本行原写"E4"系笔误，E4 指池值非字符串；已订正，见 §13.5-1） | 生成重复 id 会在 Pi 侧产生歧义条目；E5（新增，见 §13.3 修复）进一步拦截"不同别名指向同一 upstream id"的歧义 |
| D7 | `acm init` VMR 提案 | 探测到 ≥2 个模型时自动生成带 pool 的 daily（全部 discovered 模型入池，首个为 main） | 直接兑现"≤3 命令零手工编辑"；用户删减即可 |
| D8 | 过渡语义告知 | 发布说明必须写明：此前版本 pool 子表被静默忽略，升级后开始生效 | F6 事实决定的诚实义务 |
| D9 | label 大小写 | 原样保留、区分大小写 | Pi 显示名与 aider 槽位均大小写敏感；不做隐式归一 |
| D10 | pool 成员的 reasoning.effort | **不投影**（Pi 无 per-model thinking level；defaultThinkingLevel 仍取 main 的） | 与现状一致，避免发明 Pi 不存在的字段；成员级 reasoning 声明产生常规告警 |
| D11 | 跨 provider 池收缩/切换后旧 provider 条目的处理（§13.7 补记） | **累积不清理**：`op` 模型只有 upsert，没有 tombstone；切到不含该 provider 的新 profile 后，磁盘上的旧 `providers.<name>` 条目原样保留，且 ACM 对其失明（last_write 被新 profile 覆写，drift/status 均不可见，回滚也还原不了——回滚目标快照本身已含残留） | 无 tombstone op 是当前架构的结构性约束（引入需要新 op 类型与幂等/回滚语义的联动设计，超出本轮 MVP 范围）；避免误删用户/extension 手工维护的同名 provider 内容；清理责任显式移交用户（USER_GUIDE §7.3 已给出手工清理指引）。P2 可评估 `doctor`（尚未实现）加一条"managed-by-acm 但当前不可达"的提示性检查 |

---

## 11. 方案复核结论

> 复核方法：对照 §2 事实清单逐条重走 §4–§8 的每个设计决定；重点攻击"数据流盲区""向后兼容""外部系统事实"三个方向。

### 发现并已修正的问题

| # | 复核发现 | 修正 |
|---|---|---|
| R1 | 初稿遗漏：`resolve_profile` 的 reachable 集合若不含 pool 成员，**跨 provider 池成员的 `${VAR}` 缺失不会被提前拦截**，违反"凭据硬失败零写盘"承诺 | 已补入 §8.2 第 1 点，并列为关键正确性修复；测试计划补充对应用例 |
| R2 | 初稿让 Pi 对每个池成员单独发 op——会使 last_write fields 碎片化、回滚重建复杂化 | 改为维持"整条 provider payload 一个 op"（与 F4 一致），payload 内含多模型数组；§7 表格相应澄清 |
| R3 | 初稿打算 pool 存在时把 `roles.cheap` 告警逻辑整体删除——但 cheap 角色可能存在于 pool 之外（D4 独立性决策），静默吞掉违反显式暴露 | 改为精确条件：仅当 cheap/roles 的目标模型已被 pool 表达时才豁免对应告警；§8.4/§8.5 修正 |
| R4 | 初稿假设 Codex 可经 `model_providers` 注册多个模型进入 `/model`——本机实证推翻：`/models_cache.json` 是服务端目录缓存 | Codex 定型为类型 II，仅投 main + 聚合告警；杜绝了违反铁律 2 的设计 |
| R5 | Aider 证据仅有规格文档背书，直接写死字段名有风险 | §2.2 加注置信度声明，字段映射标记"P1 实施时金样校准"，符合规格既定流程 |
| R6 | 隐式补入 main 时插入位置不定会导致幂等输出不稳定 | §5.1 第 4 点固定排序规则（声明序 + 隐式成员置于队首） |

### 复核确认无问题的关键点

- ✅ 执行层零改动论断成立：op 结构、白名单粒度、last_write 键格式、drift dict 比较、rollback dot-path 重建，逐一核对源码确认对多模型 payload 天然透明；
- ✅ 向后兼容成立：无 pool 配置走原路径，金样回归把关；今日写 pool 被忽略（F6）→ 升级后生效，无语法冲突，仅需 D8 告知义务；
- ✅ 外部事实链完整：Pi（官方文档+本机 extension 实证）、Codex（本机 0.148.0 models_cache 实证）、Claude Code（本机 settings.json 实证）、Aider（规格背书+标注置信度）；
- ✅ 公理对齐：非破坏（不扩白名单）、显式暴露（类型 II 聚合告警）、精准可逆（机制零改动）、SSOT（池唯一描述在 config.toml）。

### 遗留开放项（不阻塞评审）

1. Pi 对 `cost` 字段的缺省表现（ACM 不写 cost，Pi 按未知计费处理还是 0？）——实施时以金样实测确认是否需要补 `cost: {input:0,...}`；
2. Gemini CLI / OpenCode（P1/P2）届时归类（初判：OpenCode 的 provider/model 配置可能属类型 I，需查证其 JSONC schema）；
3. 规格 v2.1 → v2.2 的正式修订文本（本方案 §8.7 已给修订要点）。

---

## 12. 执行记录（2026-08-25 落地）

> 授权范围：用户明确要求"审查文档 + 直接实现代码"（非仅设计评审）。本节记录对照代码事实的复核结论、按 §8 蓝图落地的实际改动、实施中发现并修正的偏差、以及有意保留的开放项。所有改动留在工作区，未 commit。

### 12.1 复核结论：设计与代码一致，无需推翻重来

对照 §2 事实清单（F1–F7）逐条重新核实当前代码（`config.py`/`resolve.py`/`pi.py`/`claude_code.py`/`codex.py`/`safety.py`/`status.py`/`tree_diff.py`），全部仍成立；§7 的"执行层零改动"架构结论同样成立（`write_changeset`/`detect_agent_drift`/`is_noop` 均对 `op.new` 的具体形状无感知，多模型 payload 天然透明）。设计方案本身合理，按 §8 蓝图直接实施，未发现需要推翻重做的结构性问题。

### 12.2 代码改动（对照 §8 蓝图，逐文件）

| 文件 | 改动 | 与 §8 蓝图的差异 |
|---|---|---|
| `config.py` | `ProfileConfig.pool: dict[str,str] \| None`；`validate_cross_references` 增加 E1–E3 校验（E4 由 pydantic 类型系统天然拦截，无需手写） | 与蓝图一致 |
| `resolve.py` | `ResolvedProfile.pool: dict[str, ResolvedModel]`；`reachable_model_keys` 纳入 pool 别名（R1 修复）；构造 pool 时按声明序 + main 隐式补队首（R2） | 与蓝图一致 |
| `adapters/__init__.py` | `check_unsupported_profile_specs` 新增 `pool_covered_model_ids: set[str] \| None = None` 参数，按**模型别名**（`ResolvedModel.model_id`）精确豁免 `roles.cheap`/`roles.extra` | **优于蓝图**：§8.5 原设想是 `skip_role_warnings: bool` 粗粒度豁免；实现改为按别名集合精确豁免，且对不传参的旧调用方 100% 向后兼容 |
| `adapters/pi.py` | `plan()` 分 `profile.pool` 有/无两条路径；有池时按 provider 分组、每组一个 `providers.<name>` op，`label`→`name`；非 main 成员的 `reasoning` 按 D10 不投影 + 告警 | 抽出 `_pi_api_dialect`/`_resolve_pi_api_key`/`_pi_model_entry` 三个小函数复用；无池路径逐字节保持原样（回归安全） |
| `adapters/claude_code.py` / `codex.py` | 追加聚合 `pool` 告警（按 `upstream_id` 判定跳过成员，见 §12.3-3）；`check_unsupported_profile_specs` 调用传入 `pool_covered_model_ids` | 与蓝图一致 |

### 12.3 实施中发现并修正的问题（超出 §11 原复核范围的新发现）

1. **真实 bug（已被测试捕获）**：`pi.py` 首版实现中，pool 分组循环内复用了与"设置 `defaultProvider`/`defaultModel`"代码段相同的变量名 `prov`。循环结束后该变量残留为**最后一个 provider 分组**的值，导致 `defaultProvider`/`defaultModel` 被错误地设成非 main 的 provider，而不是 `profile.main.provider`。被新增的 `test_pi_pool_multi_provider_registers_all_members` 金样测试当场断言失败捕获；修复为显式使用 `profile.main.provider.name`，并将循环内变量改名为 `group_prov` 以绝后患。
2. **精确豁免逻辑重新设计**：§8.4/§8.5 原设想是给 `check_unsupported_profile_specs` 加一个 `skip_role_warnings: bool` 开关。复核后认为布尔开关无法表达"cheap 的模型在池中、但另一个 extra role 的模型不在池中"这种**部分覆盖**场景，会导致要么误报要么误吞。改为 `pool_covered_model_ids: set[str]`，按 `ResolvedModel.model_id`（配置层别名，而非上游 `upstream_id`）精确比对，新增测试 `test_claude_code_pool_exempts_role_warning_for_covered_cheap` 覆盖"部分覆盖仍应告警"的分支。
3. **确认 §8.4 聚合告警的 skipped-members 判定沿用 `upstream_id` 比较是正确的**（而非误用 `model_id`）：Type II Agent（Claude Code/Codex）关心的是"最终落盘的上游模型字符串是否已经被表达"，而不是 ACM 侧的别名身份——两个不同别名若指向同一个 `upstream_id`，对 Agent 而言就是同一个模型，不应重复告警。这与 12.3-2 的"精确豁免"是两个不同维度的判定，未混淆。
4. `_pi_model_entry` 在草稿阶段带了一个未使用的 `is_main: bool` 参数（本打算用于未来扩展），实现时判断用不到即删除，避免死代码。

### 12.4 测试

新增/扩展用例，覆盖 §9 测试计划的全部层级：`tests/unit/test_config.py`（E1–E4 + 空 pool + pool/cheap 并存）、`tests/unit/test_resolve.py`（隐式 main 补入排序、跨 provider reachable、ENV 缺失硬失败）、`tests/golden/test_adapters_pi.py`（多 provider 分组投影 + Safety Engine 全流程非破坏性）、`tests/golden/test_adapters_claude.py` / `test_adapters_codex.py`（聚合告警 + 精确豁免的覆盖/未覆盖两分支）、`tests/integration/test_cli_pi.py`（`use` 幂等二次 no-op、`status` SYNCED、外部删除池成员触发 DRIFTED）。

验收结果：`pytest` 116 passed（原 99 + 新增 17）；`ruff check .` 全绿；`mypy src` 严格模式全绿。

### 12.5 文档同步

- `docs/USER_GUIDE.md` / `USER_GUIDE.zh.md`：§3.9（澄清 pool 是独立机制）、§5.4（pool 语法与规则表）、§5.5（交叉引用增补）、§5.7（新增三条校验错误对照）、§7.3（Pi 章节改写：pool 原生投影 + 无 pool 时的旧配方）、§7.4（能力矩阵新增 pool 行）。
- `CLAUDE.md`（项目级）：Implementation Status 中"parked design, do not start without explicit instruction"改为"已实现"，指向本文档本节。
- `docs/ACM_PROJECT_PRINCIPLE_v2.1.md`：§2.2 L2 措辞补充"可选模型池"；§7 触发式升级表新增一行，标注"已触发并交付"。这是本次唯一触及治理性文档的改动——依据文档自身"触发表随触发状态更新"的既定机制，未改动任何公理/铁律表述。

### 12.6 明确未做（与 §8.8 防蔓延边界一致）

- 未实现 Aider 适配器本体（仍是 P1 契约设计，未到交付里程碑）。
- **未实现 D7**（`acm init` 探测到 ≥2 模型时自动生成带 pool 的提案）：`src/acm/vmr.py:generate_vmr_proposal()` 与 `src/acm/cli.py` 均无 pool 生成逻辑（`grep -rn pool src/acm/{vmr,cli}.py` 零命中）。本节此前遗漏声明这一点，属执行记录疏漏，已在 §13.4 复核中发现并在此订正；§6 走查第①步已同步改写为如实描述当前行为。范围裁剪本身合理（本轮聚焦 Pi 投影编译层），但需与 Aider 一样被显式记录为未做，而非隐含"已实现"。
- 未新增 `acm bind`、未做 pool 跨 profile 继承/复用。
- §11 遗留开放项（Pi `cost` 字段缺省表现、OpenCode/Gemini CLI 归类、Principle→v2.2 正式修订文本）按原样保留为开放项，未在本轮处理。
- `README.md`/`README.zh.md` 未改动：其"Key Features"是市场化文案而非精确的实现状态描述（例如已将尚未实现的 `acm release` 写作既有特性），这是与本次 pool 任务无关的既存不一致，未顺手处理，仅在此提请关注。

### 12.7 遗留给用户复核的点

- §12.3-2 的"精确豁免"实现方式（`pool_covered_model_ids` 按别名集合而非布尔开关）与设计文档原文字面表述有出入，是复核后的主动改进，建议重点复核 `adapters/__init__.py` 的 diff。
- Principle v2.1 是治理性文档，本次做了两处措辞级改动（§2.2、§7），未改动公理/铁律，但仍建议单独复核这两处 diff。

---

## 13. 独立复核（2026-08-25，第二轮全面审查）

> 复核方法：不信任 §2/§11/§12 的任何既有结论，从原始证据重新出发——逐行阅读全部改动源码与 diff、重跑 `pytest`（116 passed）/`ruff`/`mypy`（均复现全绿）、并**重新打开 Pi 官方文档原文核对 §2.2 引用的外部事实**。以下按严重度列出发现；每条均附可复查的证据位置。

### 13.0 复核确认无误的部分（先说结论）

- ✅ `config.py` E1–E4 校验、`resolve.py` reachable 纳入 pool / 隐式 main 补入及排序规则（声明序 + 队首），与 §8 蓝图一致；隐式补入的去重判定（`any(m.model_id == profile_cfg.main)`）正确，不会产生重复成员。
- ✅ §12.3-1 所述 `prov` 变量残留 bug 已确实修复：现版本循环内用 `group_prov`，settings 三键显式取 `profile.main.provider.name`（`pi.py:117-123, 165-170`）。
- ✅ 执行层零改动论断经直接读码确认：`write_changeset` 对同文件多 op（跨 provider 池 = 同一 models.json 上两条 `providers.*` op）天然支持（Step 3 按 `unique_files` 分组、tree_diff 以本次全部 op path 为 managed 集）；`detect_agent_drift` / `is_noop` 均为 dict 全等比较，对多模型 payload 透明。掩码 `mask_secrets_in_obj` 递归覆盖 list/dict，池 payload 内的 `apiKey` 在 drift 输出中会被掩码。
- ✅ 聚合告警 + 精确豁免的实现与 §12.3-2/§12.3-3 描述相符：Type II 用 `upstream_id` 判定 skipped 名单、用 `model_id` 判定角色告警豁免，两个维度未混淆，且有覆盖/未覆盖双分支测试。
- ✅ Principle v2.1 改动经 diff 核实确为措辞级（§2.2 L2 一句 + §7 触发表一行），未触碰公理/铁律。
- ✅ 测试计数自洽：新增 17 个（config 7 + resolve 4 + pi 金样 2 + claude 金样 2 + codex 金样 1 + 集成 1），99+17=116 与实跑一致。

### 13.1 【高 · 外部事实偏差】Pi `/model` 并不以 `name` 作为主显示名 —— 本方案的核心卖点表述过强

这是本轮复核最重要的发现，且**直接命中方案的需求承诺**。

本设计文档 §2.2 自己引用的证据源（pi-coding-agent@0.84.1 `docs/models.md`）原文写明：

> L202: `name` | No | `id` | Human-readable model label. **Used for matching (`--model` patterns) and shown as secondary model detail text.**
> L236-237: **`/model`, `--list-models`, and the interactive footer display entries by model `id`.** The configured `name` is used for model matching and secondary model detail text. It does not replace the footer/status-bar model id.

即：`/model` 选择器**按 `id` 展示条目**，`name` 仅用于 `--model` 模式匹配和**次要详情文本**，不是列表里的主显示名。据此对照：

| 位置 | 声称 | 实际 |
|---|---|---|
| §0 TL;DR 表格 | "显示名（`name` 字段），出现在 `/model` 列表" | 过强：出现的是 `id`，label 只是次要详情 |
| §5.1 第 2 点 | "Pi 的可选显示名字段，`/model` 列表中展示" | 同上 |
| §6 走查 | "列表显示 coding(default)、cheap(budget)…" | 实际按 id 显示 coding/cheap/agent，label 为辅助信息 |
| USER_GUIDE 双语 §7.3 | "label … 这正是 Pi `/model` 选择器里显示的名字" | 同上 |

**影响评估**：需求的**功能内核仍然成立**——池内全部模型确实会出现在 `/model` 中供手选（靠 id 驱动），`defaultModel`/`defaultProvider` 投影不受影响，`acm use`/幂等/drift/rollback 全链路照旧。受损的是"label 即选择器中的名字"这一表述，以及由此带来的用户辨识体验预期：选择器里看到的主要是 `cheap` 这样的上游 id，label（budget）只是辅助文本。

**处置建议**：(a) 修订本文档 §0/§5.1/§6 及 USER_GUIDE 双语对应句子，如实描述为"id 为主展示、label 为次要详情文本"；(b) 在真机上实测一次渲染效果留档（§11 开放项 1 的 cost 问题同样要求实测，可一并做）；(c) 注意此事实与 13.3 叠加后的后果——若两个池成员 id 相同，用户在 `/model` 里几乎无法区分二者。

### 13.2 【中 · 实现 vs 设计缺口】池路径下非 main 成员的 temperature/capabilities/headers/proxy 被静默丢弃，违反显式暴露原则

§5.1 第 5 点明确要求："temperature/capabilities/headers/proxy/budget_tokens 等其他不可表达项**照旧逐项告警**"。但实现中：

- `pi.py:128-141` 池路径对非 main 成员只检查了 `reasoning` 一项；
- `check_unsupported_profile_specs`（`adapters/__init__.py:78-105`）只检查 **main** 的 temperature/capabilities 和 **main provider** 的 headers/proxy。

后果：池成员（或仅被池成员使用的非 main provider）声明的 `temperature`、`capabilities`、`headers`、`proxy` 会**无任何告警地消失**。例如 `[models.cheap] temperature = 0.3`，或 `openai-direct` provider 配了 `proxy` 而 main 在 vmr 上——投影到 Pi 时全部静默丢失。这违反公理 2 的"显式暴露，绝不静默"，且与本文档 §5.1 第 5 点直接矛盾。

**处置建议**：在 `pi.py` 池路径的成员循环中补齐 per-member 的 temperature/capabilities 检查与 per-provider（非 main 组）的 headers/proxy 检查；或至少在 §10 增加决策记录说明为何豁免（当前没有这样的决策记录，属于实现时的遗漏而非有意取舍）。同理需检查 Claude Code/Codex 路径是否存在同类静默（其池成员不可表达，已由聚合告警整体覆盖，问题不大，但 cheap 角色模型的 temperature 同样从未被检查过——先于本特性存在的盲区，可一并记录）。

### 13.3 【低 · 校验缺口】E2 只查别名重复，未落实 R4 声称的"避免重复 id 歧义"

R4/E2 的理由栏写着"避免 Pi models 数组出现重复 id 的歧义"，但校验的是 **config 别名**唯一性，而 Pi 侧的歧义来自 **upstream_id** 重复。构造：`[models.a] id="gpt-x"`、`[models.b] id="gpt-x"`（同 provider），pool 写 `la="a" lb="b"`——校验通过，投影出的 `models[]` 却含两个 `{id:"gpt-x"}`。叠加 13.1（Pi 按 id 展示/匹配），这两条在 `/model` 中不可区分。

**处置建议**：二选一——(a) 校验升级：同一 profile 池内（同 provider 分组内）出现相同 upstream_id 时报错或告警；(b) 若认为该场景过于边缘，则修正 R4 的理由文字，承认校验的是别名身份而非上游 id 唯一性。

### 13.4 【中 · 执行记录遗漏】D7（init 自动生成带 pool 的提案）未实施，且 §12.6 未声明

§10-D7 决策"探测到 ≥2 个模型时 init 提案自动生成带 pool 的 daily"、§6 走查第①步（"init 提案将自动生成带 pool 的 daily"）——经查 `src/acm/vmr.py:generate_vmr_proposal()` 与 `src/acm/cli.py`，**没有任何 pool 生成逻辑**（`grep -rn pool src/acm/{vmr,cli}.py` 零命中）。这本身可以是合理的范围裁剪，但 §12.6 "明确未做"清单**没有列入 D7**，导致执行记录与本节声称的"对照 §8 蓝图落地"产生偏差——§8 蓝图虽未详述 init 改动，但 D7 是 §10 明确决策、§6 明确走查步骤，其未实施必须像 Aider 一样被显式声明。

**处置建议**：将 D7 补入 §12.6 未做清单（或作为遗留开放项），并在 USER_GUIDE 的 init 相关章节确认没有暗示该行为已存在。

### 13.5 【低 · 文档内部矛盾】三处细节不一致

1. **§10-D6 引用错误号错误**：D6 写"校验错误 E4"，但重复别名是 **E2**（E4 是池值非字符串）。疑为 §4.3 校验编号在复核修订（§11-R3 等）轮次间错位所致。
2. **§4.4 示例与 R2 冲突**：§4.4 的 ResolvedProfile 示例把隐式补入的 main 写作 label `"default"`（注释"隐式补入"），而 R2 与实现均为 label `"main"`（`resolve.py:192-197`）。
3. **§8.5 蓝图已被取代但未加注**：§8.5 仍是 `skip_role_warnings: bool` 的原始设计，实际交付为 §12.3-2 的 `pool_covered_model_ids`。作为历史记录保留可以接受，但应加一行"已被 §12.3-2 取代"的指引，避免后来者按蓝图误改。

### 13.6 【低 · 测试计划偏差】金样·pi 第 (c) 项"投影→篡改→rollback 存活"未在池变体上执行

§9 要求 pi 金样包含三步断言（Apply 正确 / 非管字段无损 / 回滚存活）。实际新增的 `test_pi_pool_apply_golden_non_destructive` 只覆盖了前两步；回滚存活依赖既有单模型 ABC 测试（`test_pi_golden_abc`）所验证的同一整文件快照机制。因回滚粒度是物理快照、与 payload 形状无关，风险很低，但与 §9 的字面承诺不符，应如实记录（或补一个池变体的 rollback 断言）。

### 13.7 【低 · 设计盲区】跨 provider 池收缩后的残留条目：语义已被 USER_GUIDE 事后追认，但设计文档本体缺失这条决策

场景：profile A 的池含 openai-direct 成员 → 投影写入 `providers.openai-direct`；切到 profile B（池不含该 provider）→ 新 plan 不再产出该 op → **磁盘上的 `providers.openai-direct` 永久残留**且仍出现在 `/model` 中；同时 last_write 被 B 的字段覆写，ACM 对该残留彻底失明（drift/status 均不可见，rollback 也还原不掉——快照是 B 写入前的状态，本身含残留）。op 模型只有 upsert 没有 tombstone，这是结构性约束。

USER_GUIDE §7.3 已把它作为"registry-style 累积"语义显式写明并给出清理指引（含"rollback 可恢复快照"的提示），这个事后追认是合理的；但本文档 §7 数据流分析与 §10 决策记录对此**完全没有着墨**——"切换 profile 不清理旧 provider 条目、ACM 对其失明"应当是一条有意识做出的、被记录的决策，而不是只在用户手册里顺带出现。

**处置建议**：在 §10 补一条决策记录（D11）：池收缩/切换时旧行为=累积不清理，理由=无 tombstone op、避免误删用户/extension 内容，清理责任归用户（与 USER_GUIDE 对齐）；P2 可评估引入"managed-by-acm 且当前不可达"的提示性 doctor 检查（doctor 未实现，届时一并考虑）。

### 13.8 【附 · 先于本特性存在，与 pool 无关】Pi headers 告警文案与事实不符

`check_unsupported_profile_specs` 会对 main provider 的 headers 发出"{agent_id} does not configure custom provider headers in config file"告警；但 Pi 的 models.json **明确支持 provider 级 `headers` 字段**（models.md Provider Configuration 表）。即该告警对 Pi 是事实性错误的——Pi 不是"不支持"而是 ACM 尚未投影。属存量问题，本特性未使其恶化，建议另行开票处理（要么补投影，要么改文案）。

### 13.9 复核总结论

- **架构判断成立**：§7"纯编译层扩展、执行层零改动"经独立读码再次确认；实现与 §8 蓝图的整体吻合度高，§12.3 的两处主动改进（bug 修复、精确豁免）方向正确。
- **需要行动的**：13.1（修订 label 显示名表述，双语文档联动）、13.2（补齐池路径投影损失告警，属原则性缺口）、13.4（执行记录补列 D7）。三者均不动摇方案结构，修复成本低。
- **建议择机处理的**：13.3（校验或措辞二选一）、13.5（文档勘误）、13.6（补测试或记录偏差）、13.7（补决策记录 D11）、13.8（另开票）。
- 本方案"label 双重职责"的核心抽象（类型 I 显示名 / 类型 III 角色名）在 13.1 的事实面前依然成立，但类型 I 一侧的价值需要更诚实的表述：label 在 Pi 当前版本是辅助信息而非主标识。

---

## 14. 复核问题处置与第三轮复核（2026-08-25）

> 方法：不采信 §13 的任何结论，逐条对照当前代码（`config.py`/`resolve.py`/`pi.py`/`claude_code.py`/`codex.py`/`adapters/__init__.py`）与本机 Pi 官方文档包（`@earendil-works/pi-coding-agent@0.84.1/docs/models.md`，pnpm store 内直接定位到文件，非转述）重新核实；核实后对判定为成立且值得处理的问题动手修改；随后对**整个工作区未 commit 的改动**（含 §13 未覆盖的文件）做独立的第三轮审查，发现 1 项新问题并一并修复。全部改动均已跑 `pytest`/`ruff`/`mypy` 验证。

### 14.1 §13 各项发现的核实结论与处置

| # | 核实结论 | 处置 |
|---|---|---|
| 13.1 | **成立，证据确凿**。直接打开本机 `models.md` 源文件核对 L202/L236-237/L384：`/model`、`--list-models`、交互式 footer 均按 `id` 展示，`name` 仅用于 `--model` 匹配与次要详情文本。原文档表述确实过强。 | **已修复（文档）**：改写 DESIGN 文档 §0 表格、§5.1 第 2 点、§6 走查；USER_GUIDE 双语 §7.3 对应段落；`pi.py::_pi_model_entry` 的 docstring；`CLAUDE.md` 顶层 pool 说明。均改为"id 为主展示、label/name 为次要详情文本"。 |
| 13.2 | **成立，直接读码确认**：`pi.py` 池路径仅检查非 main 成员的 `reasoning`；`check_unsupported_profile_specs` 只看 `profile.main`。池成员的 temperature/capabilities、非 main 池 provider 的 headers/proxy 确实无声消失，违反 §5.1 第 5 点自己的承诺与显式暴露公理。 | **已修复（代码+测试）**：`pi.py` 池路径新增 (a) 每个非 main 成员的 `temperature`/`capabilities` 检查，(b) 每个非 main provider 分组的 `proxy` 检查（`headers` 一项在 §15 中从"补告警"升级为"直接投影"，不再需要告警，见 §15）——用独立 `ProjectionWarning`，措辞明确为"ACM 未投影"而非"Pi 不支持"（避免重蹈 13.8 的事实性错误）。新增 2 个金样测试（headers 部分已在 §15 中随投影实现替换重写）。 |
| 13.3 | **成立**。R4/E2 理由栏写"避免重复 id 歧义"，但 E2 实际只查别名；构造两个不同别名指向同一 `(provider, id)` 可绕过。采纳复核建议的选项 (a)：升级校验而非仅改措辞，因为叠加 13.1（按 id 展示）后这是真实可复现的用户可见 bug，成本又低。 | **已修复（代码+测试）**：`config.py` 新增 E5——同一 pool 内两个别名若解析到同一 `(provider, upstream id)` 即报错。新增 2 个单测（拒绝用例 + "不同 provider 上同名 id 允许"的正例，避免过度收紧）。 |
| 13.4 | **成立，`grep -rn pool src/acm/{vmr,cli}.py` 复现零命中**。D7 确未实施，且 §12.6 未做清单原先确实没有列出。 | **已修复（文档）**：§12.6 补一条 D7 未实施的显式声明；§6 走查步骤①改写为如实描述当前行为（不含 pool 自动生成）。 |
| 13.5-1（D6 引用错误） | **成立**，笔误 E4→应为 E2。 | **已修复（文档）**：订正引用并注明 E5（13.3 新增）进一步覆盖的场景。 |
| 13.5-2（§4.4 示例矛盾） | **成立，但根因与复核原文略有出入**：不是"隐式补入的 main 被错标为 default"，而是 §4.1 示例中 `default = "coding"` **本来就是用户显式声明**（其别名等于 main），resolve.py 判定"main 已在池中"从而不再插入——即该示例根本不是隐式补入案例，注释"隐式补入"本身就是错的。若真的省略该行，隐式补入的 label 才固定为字面量 `"main"`。 | **已修复（文档）**：改写为准确描述："default" 是显式声明，非隐式；补充"若省略则隐式补入 label 固定为 main"并附测试引用。 |
| 13.5-3（§8.5 已被取代未加注） | **成立**。 | **已修复（文档）**：§8.5 顶部加注"已被 §12.3-2 取代，请勿按本节字面实施"。 |
| 13.6（rollback 断言未覆盖池变体） | **成立**，`test_pi_pool_apply_golden_non_destructive` 原先确实只有 a/b 两步。 | **已修复（代码测试）**：为该测试补齐 Step c（读 `last_write` → 定位快照 → 恢复字节 → SHA-256 比对），与 claude_code/codex 的 abc 三步金样模式对齐。 |
| 13.7（D11 决策记录缺失） | **成立**。USER_GUIDE 确有"registry-style 累积"说明，但设计文档本体 §10 此前确实没有对应决策记录。 | **已修复（文档）**：§10 补 D11；§7 数据流分析补一段"已知盲区"引用 D11。 |
| 13.8（Pi headers 告警文案事实错误） | **成立，且经本机文档核实**：`models.md` Provider Configuration 表第 5 行明确 provider 级 `headers` 字段存在（`docs/models.md:140`）；但同一张表**没有** `proxy` 字段（Pi 用重定义 `baseUrl` 而非独立 `proxy` 概念达成路由）——这意味着现有 `provider.proxy` 告警文案实际是准确的，只有 `provider.headers` 告警文案错误。 | **本节原判断"不修复、另开票"已被 §15 推翻并实际修复**——用户明确指出"存量 bug 该处理还是要处理，不因新旧项目区别对待"。真正的修复是实现 headers 投影（而非仅改文案），已在 §15 落地：`pi.py` 的 main 路径与 pool 分组路径均已把非空 `headers` 写入 `providers.<name>.headers`，`check_unsupported_profile_specs` 调用处的 `supported_fields` 加入 `"headers"`。详见 §15。 |

### 14.2 第三轮独立复核：新发现（超出 §13 范围）

在验证 13.3 时，用真实配置尝试复现"是否所有重复 upstream id 场景都会被新校验拦下"，发现一个 §13 未提及的缺口：

**14.2.1【中 · 校验缺口，已修复】E5 校验只覆盖 `profile_cfg.pool` 中显式声明的成员，未覆盖 R2 隐式补入的 main**

`config.py` 的 E5（新增）与 §4.3 全部 E1-E4 校验都发生在 `validate_cross_references()`，此时只能看到用户在 TOML 里显式写的 `profile_cfg.pool` 字典——而 R2"main 隐式入池"要到 `resolve.py::resolve_profile()` 才会真正插入 `pool["main"]`。构造反例可实测复现：

```toml
[models.coding]
provider = "vmr"
id = "same-id"
[models.replica]
provider = "vmr"
id = "same-id"          # 与 coding 同一 upstream id、同一 provider，但不同别名

[profiles.daily]
main = "coding"
[profiles.daily.pool]
replica_label = "replica"   # 未显式包含 main，未被 E2/E5 判定为冲突
```

`parse_config_toml()` 全部校验通过；但 `resolve_profile("daily", cfg, {})` 组装出的最终 `pool` 是 `{"main": coding(same-id), "replica_label": replica(same-id)}`——两个不同 label 指向同一 upstream id，本机实测复现（`python3` 直接调用两个函数验证，输出确认冲突存在）。这正是 13.3 想拦截的问题类别，只是绕过路径是"通过隐式 main 而非显式声明"。

**修复**：在 `resolve.py::resolve_profile()` 组装完整 `pool`（含隐式 main）后，新增一次 defense-in-depth 重新校验，与 config.py 的 E5 逻辑同构但作用于最终 `ResolvedModel` 集合，捕获 config-time 看不到的隐式插入冲突。保留 config.py 的 E5 而非删除——它能在无需解析 `${ENV}` 的更早阶段（`acm init`/纯 parse 时）就捕获显式声明的常见情形，两层校验互补而非冗余。新增单测 `test_resolve_pool_implicit_main_collision_with_explicit_alias_rejected` 复现并验证修复。

**14.2.2【低 · 文档内部矛盾，已修复】新增 `CLAUDE.md`（项目级，本次 diff 的一部分）自相矛盾**

`CLAUDE.md`"Implementation Status"一节称 pool "**已实现**"，但同一文件"Doc Map"表格仍把 `docs/DESIGN_MODEL_POOL_v1.md` 标注为"Model-pool feature design **(parked)**"——同一份新文件内两处状态描述互相矛盾。属 §13 复核未覆盖的文件（`CLAUDE.md` 是纯新增的 untracked 文件，不在 §13 review 的源码 diff 范围内）。

**修复**：Doc Map 行改为"(implemented)"；Implementation Status 段落同时补充 13.1（label 是次要详情文本非主展示）与 13.4（D7 未实现）两条事实，避免读者从 CLAUDE.md 得到与本文档不一致的印象。

**14.2.3 复核确认无新问题的部分**

- `status.py`/`safety.py`/`masking.py` 二次核实（`grep -rn pool` 零命中）确认执行层与状态层代码字面零改动，与 §7/§13.0 的论断一致；
- `tests/unit/test_config.py`、`tests/unit/test_resolve.py`、`tests/golden/test_adapters_claude.py`、`tests/golden/test_adapters_codex.py`、`tests/integration/test_cli_pi.py` 的既有新增用例逐条读过，断言与场景描述相符，未发现假阳性或测试掩盖的问题；
- `ProfileConfig.pool: dict[str, str] | None` 与 `CoreConfig(extra="forbid")` 的交互核实正确：`pool` 是具名字段而非 extra，不受 `extra="allow"` 的字符串-only 过滤影响（这与 F6 描述的"pool 转正前被静默忽略"机制是两回事，未见混淆）。

### 14.3 验证记录

修复全部完成后：

```
uv run pytest -q      → 121 passed（原 116 + 本轮新增 5：E5 拒绝/正例各 1、隐式 main 冲突 1、pi 池 temperature/capabilities 1、pi 池 headers/proxy 1；13.6 的 rollback 断言是扩展既有测试而非新增函数，不计入增量）
uv run ruff check .   → All checks passed
uv run mypy src       → Success: no issues found in 24 source files
```

### 14.4 第三轮复核总结论

- §13 提出的 8 项发现全部核实为事实成立（含对 13.5-2 根因的一处小订正、对 13.8 的补充证据）；其中 13.2/13.3/13.6 属于代码/测试层面的真实缺口，已随本轮一并修复并配测试；13.1/13.4/13.5/13.7 属于文档表述/记录缺失，已订正；13.8 本轮曾判断"另开票"，**该判断已在 §15 被推翻并实际修复**——不应以"存量 bug/新功能范围外"为由搁置真实缺口，详见 §15。
- 第三轮独立复核额外发现 1 项代码缺口（14.2.1，E5 校验的隐式 main 绕过路径）与 1 项新增文档自相矛盾（14.2.2，`CLAUDE.md` 内部不一致），均判定为事实清楚、方案明确、低风险，已直接修复。
- 至此，架构结论（§7"纯编译层扩展、执行层零改动"）与 §13.9 的整体判断保持不变：本方案的核心设计成立，本轮处理的全部问题都是实现细节的收口，未发现需要推翻重做的结构性缺陷。

---

## 15. 13.8 的重新处置：实现 Pi headers 投影（2026-08-25）

> 触发：用户明确指出 §14.1 对 13.8"不修复、另开票"的判断依据是"存量 bug"这个身份标签，而不是缺陷本身的严重度——这个判断标准不成立："我们整个项目都是新的，不存在说以前存量的问题"。已收回该判断，重新走"调查研究 → 方案分析 → 结合代码给出方案 → 动手处理 → 记录过程"的流程。

### 15.1 重新调查：这到底是"文案问题"还是"功能缺口"

复核 §14.1 原判断时给出的理由是"真正修复需要新增功能面……超出本轮授权边界"——重新调查后发现这个理由站不住脚，本质上是把"工作量"和"是否该修"混为一谈：

1. **Pi 端能力已确认**（本机 `@earendil-works/pi-coding-agent@0.84.1/docs/models.md` Provider Configuration 表，`headers` 一行，`docs/models.md:140`）：provider 级 `headers` 是 Pi 原生支持的字段，且有明确的取值语义（支持字面量 / `!command` shell 执行 / `$VAR`、`${VAR}` 环境变量插值，`docs/models.md:149-159`）。
2. **ACM 端数据已就绪**：`headers` 早在 Principle §2.2 就被列为 L1 受管字段；`ProviderConfig.headers: dict[str, str]`（`config.py:25`）与 `ResolvedProvider.headers`（`resolve.py:73`）已经贯通到 `resolve_profile()` 的输出——`prov.headers` 在 `pi.py` 里本来就可以直接取到，此前只是**没有把它塞进 payload dict**，一行代码的事。
3. **不存在需要新设计决策的分叉**：不需要新增 `${VAR}` 校验规则（headers 的取值已经是普通字符串，直接透传给 Pi，由 Pi 自己按其文档规则做 `$VAR`/`${VAR}` 插值——与 ACM 现有的"api_key 用 `$VAR` 字面量交给 Pi 运行时展开"是同一套哲学，零新概念）；不需要扩白名单（`providers` 整域已经是白名单 namespace，`headers` 只是该 payload 内的一个新 key，Safety Engine 六步、AST tree-diff、幂等比较、掩码递归全部对新 key 天然透明——这与本方案 §7 反复验证过的"payload 内部结构变化对执行层零影响"是同一个论断的又一次应用）。

**结论**：13.8 从来就不是"新功能"，是一个"该消费的已解析字段没有被消费"的普通投影缺口，和 §13.2 修复的 temperature/capabilities 缺口是同一类问题，只是方向相反（那边是漏告警，这边是漏投影）。此前"超出授权边界"的判断是错的，收回。

### 15.2 方案与实现

在 `src/acm/adapters/pi.py` 的两条 payload 构造路径中，`prov.headers`/`group_prov.headers` 非空时写入 `"headers"` 键：

- **单模型路径**（无 pool）：`provider_payload["headers"] = prov.headers`（`pi.py` 约 200 行附近）。
- **池路径**（按 provider 分组）：`group_payload["headers"] = group_prov.headers`，对 main 所在分组与其余分组一视同仁。
- **告警调整**：`check_unsupported_profile_specs()` 调用处的 `supported_fields` 集合加入 `"headers"`，使共享的"provider.headers 不支持"告警不再对 Pi 触发（该告警对 Claude Code/Codex 依旧生效——未改动，因为没有证据表明它们支持）。§13.2 修复中为"非 main 池 provider"新增的 headers 告警随之**移除**（不再需要，直接投影即可）；同一处的 **proxy 告警保留**——重新核对 `models.md` 的 Provider Configuration 字段表（`baseUrl`/`api`/`apiKey`/`oauth`/`headers`/`authHeader`/`models`/`modelOverrides`）确认 Pi **没有** `proxy` 字段，Pi 走"重定义 `baseUrl`"而非独立代理概念达成路由——所以 `provider.proxy` 告警对 Pi 从一开始就是准确的，无需改动。

### 15.3 风险评估

- **执行层零影响**：与 §7/§13.0 反复验证的结论一致——新增的 `headers` 只是 `providers.<name>` payload 内的一个新 key，白名单、AST 非破坏性断言、指纹校验、幂等比较（dict 全等）、drift 检测全部对任意 payload 内部结构透明，不需要改动。
- **掩码行为核实**：`masking.py::is_sensitive_key` 用正则 `api_?key|token|auth|secret|password|credential`（大小写不敏感）递归匹配 dict 的每一层 key；常见的认证类 header 名（`Authorization`、`X-Api-Key`、`X-Auth-Token` 等）都会命中 `auth`/`key`/`token` 子串从而在 `acm status`/dry-run/drift 输出中被掩码。非常规命名的 header（如自定义签名头）若本身携带敏感值则不会被这套启发式覆盖——但这是 `headers` 字段本身（早于本次改动、Principle §2.2 就已列为 L1 字段）的既有特征，config.toml 源文件本来就以明文保存这类值，不是本次投影改动新引入的暴露面，不在本次修复范围内重新设计。
- **不影响既有金样测试**：`conftest.py::make_mock_profile` 与所有既有 fixture 均未设置 `headers`，因此现有金样断言的 payload 形状不受影响（已用 `pytest` 全量验证）。

### 15.4 遗留的公开问题（需要用户确认，非本次擅自处理）

**Codex CLI 是否也支持 provider 级自定义 headers 尚未证实。** 本机环境有 `codex` 可执行文件但没有找到其配置 schema 的官方文档缓存（不同于 Pi 有本地 npm 包文档可直接核对源文），凭现有证据不能像 Pi 一样给出确定结论。`check_unsupported_profile_specs` 对 Codex 的调用同样没有把 `"headers"` 加入 `supported_fields`，所以 Codex 侧目前维持原有告警文案不变。**没有动这一处**，因为没有同等强度的证据支撑——这与"存量 bug 也要修"的原则不冲突，而是"没证据不能瞎改"（铁律 2：没有公开、稳定、可安全修改的配置接口就不支持）。如果需要确认，建议下次找到 Codex 官方 `config.toml` schema 文档（如 `codex --help config` 或其 GitHub 仓库的 docs/config.md）后再评估是否需要同样修复。

### 15.5 验证记录

```
uv run pytest -q      → 122 passed（在 §14 的 121 基础上净增 1：
                          - 重写 test_pi_pool_non_main_provider_headers_proxy_warn 为
                            test_pi_pool_non_main_provider_headers_projected_proxy_warns
                            （headers 从"断言告警"改为"断言已投影"，proxy 告警断言保留）
                          - 新增 test_pi_main_provider_headers_projected（单模型路径 headers 投影）
uv run ruff check .   → All checks passed
uv run mypy src       → Success: no issues found in 24 source files
```

### 15.6 结论

13.8 从"另开票搁置"改为"本轮直接修复"：Pi 的 provider `headers` 现在会被正确投影，不再有事实错误的告警，也不再有静默丢失。`proxy` 告警维持不变（核实后确认对 Pi 仍然准确）。Codex 是否同样存在该问题标记为待证实的公开问题，未擅自处理。本次调整再次印证 §7 的架构判断：payload 内部字段的增减对 Safety Engine/状态层/回滚/漂移检测全部零影响，这正是"adapter 产出 ChangeSet、Safety Engine 统一执行"契约设计初衷的红利。

---

## 16. 第四轮全面复核（2026-08-25）

> 方法：不采信 §12–§15 的任何结论，从原始证据重新出发——逐行阅读全部工作区改动源码（`git diff` + 全文重读）、重跑 `pytest`（122 passed）/`ruff`/`mypy`（均复现全绿）、重新打开本机 Pi 官方文档包（`@earendil-works/pi-coding-agent@0.84.1/docs/models.md`）逐条核对全部外部事实断言、并用可运行脚本实测可疑场景（非纸面推演）。以下先列确认无误的部分，再按严重度列新发现；每条附可复查的证据位置。

### 16.0 复核确认无误的部分

- ✅ 质量门禁与计数声明属实：`uv run pytest -q` → 122 passed；`ruff check .` 全绿；`mypy src` 严格模式全绿，与 §14.3/§15.5 记录一致。测试增量的算术自洽（config 池用例 9 = 首轮 7 + E5 两例；resolve 池用例 5 = 首轮 4 + 隐式 main 冲突 1）。
- ✅ 执行层零改动论断第四次独立读码成立：`safety.py::write_changeset` Step 3 按 `unique_files` 分组处理同文件多 op 并把全部 op path 传入 tree_diff 作 managed 集；Step 6 以 `{file.name}::{path}` 为键写 last_write，池的双 provider op 天然落账。`status.py::detect_agent_drift`/`is_noop` 均为 dict/list 全等比较，多模型数组透明。
- ✅ 回滚链路直接读码核实：`cli.py::rollback_cmd` 整文件字节还原 + 按 last_write 既有键集从磁盘重建 fields（读回整条 provider payload），与 §13.0 描述一致；`test_pi_pool_apply_golden_non_destructive` 的三步断言（含 §13.6 补的回滚存活步）真实存在且通过。
- ✅ 掩码行为核实：`masking.py::mask_secrets_in_obj` 对 dict/list 递归，池 payload 内嵌套的 `apiKey` 及认证类 header 键（命中 `auth|key|token` 子串）在 drift/dry-run 输出中会被掩码，§15.3 的判断准确。
- ✅ D7 未实现声明属实：`grep -rn pool src/acm/{vmr,cli}.py` 复现零命中；USER_GUIDE 双语未发现暗示 init 会生成 pool 提案的表述。
- ✅ USER_GUIDE 双语一致性良好：§5.4 规则清单已包含 E5（同 `(provider, upstream id)` 冲突拒绝）规则，§5.7 错误对照表双语均收录对应报错片段，中英内容对齐。
- ✅ Principle v2.1 改动经 diff 核实确为两处措辞级（§2.2 L2 + §7 触发表一行），未触碰公理/铁律。

### 16.1 【高 · 显式暴露缺口，已实测复现】Type II 聚合告警按裸 `upstream_id` 判定 skipped，跨 provider 同名 id 的池成员被整体静默

这是本轮最重要的发现，属原则性缺口（违反公理 2），且有可运行的反例。

**位置**：`claude_code.py:120` 与 `codex.py:151` 的 skipped 过滤条件均为 `if m.upstream_id != profile.main.upstream_id`。

**反例（本机实测复现，输出为零告警）**：main 在 provider `vmr` 上（upstream id `coding`），池另含 provider `direct` 上的成员（不同 `[models]` 别名，upstream id 同为字符串 `coding`）。该构造合法——config.py 的 E5 按 `(provider, id)` 二元组判重，跨 provider 同名 id 明确放行（R6/D5 支持跨 provider 池，且有专门的正例测试）。但对 Claude Code 执行 `plan()` 后 `warnings == []`：聚合告警因 id 相等把该成员排除出 skipped 名单，用户得不到任何提示。

**连带放大**：若再把 `cheap`（或自定义角色）绑定到该成员的别名，则 `check_unsupported_profile_specs` 的角色告警也因 `pool_covered_model_ids` 按别名豁免而被抑制（`adapters/__init__.py:59,68`）——两条告警通道同时静默，一个完全不可表达的设置零提示。实测复现确认。

**根因分析**：§12.3-3 为该判定给出的理由是"两个别名指向同一 upstream_id，对 Agent 而言就是同一个模型"。这个推理只在**同一 provider 端点内**成立。Type II Agent 只投影 main 的连接层（`env.ANTHROPIC_BASE_URL` 指向 vmr），`direct` 上的同名 id 成员经投影后的连接根本不可达——它是不同的端点、不同的上游模型，不是"同一个模型"。判定应当比较的是 `(provider, upstream_id)` 二元组，而非裸 id 字符串。（Pi 不受影响：全部成员都被真实注册。）

**处置建议**：skipped 判定改为比较 `(m.provider.name, m.upstream_id) != (profile.main.provider.name, profile.main.upstream_id)`（或更简单地按与 main 的别名身份比较），claude_code/codex 两处同步修改，并补"跨 provider 同名 id 必须出现在 skipped 名单"的金样测试。

### 16.2 【中 · 事实性错误，与 13.8 同类】Pi 的 temperature 告警文案与官方文档不符：模型级 `samplingParams` 原生支持 temperature

§13.2/§14 修复补入的池成员告警（`pi.py:164`："Pi models.json does not configure per-model temperature; ... is not projected."）与共享检查中的同主题文案，都断言 Pi 无法表达每模型 temperature。但本机 `models.md` 明确：

- L209：模型条目字段表含 `samplingParams`（"Sampling parameters merged verbatim into every request body"）；
- L241–255："a `temperature` key here **beats the request-level temperature**"，即模型级温度覆盖请求级；适用于 `openai-completions`/`openai-responses`/`azure-openai-responses`，其余 API 忽略。

即对 openai 系方言，Pi **有**表达每模型 temperature 的公开通道，ACM 只是尚未投影——这与 13.8（headers）被定性为事实性错误并当场修复的情形同类，不应以"告警总比静默好"为由保留失实措辞（anthropic-messages 方言下确实无通道，告警在该场景下才准确）。

**处置选项**：(a) 按 dialect 条件投影 `samplingParams.temperature`（openai 系方言写入，语义为原始 body 合并且键优先，需一个小设计决定）；(b) 最低限度修正两处文案为"ACM 未投影；Pi 可经模型级 samplingParams 表达（仅 openai 系方言生效）"，消除事实性错误。

### 16.3 【中 · 同类】capabilities.vision 可经 Pi 的模型级 `input` 字段表达，"capabilities 不支持"一刀切文案部分失实

`models.md` L206：模型条目字段 `input` 取值 `["text"]` 或 `["text", "image"]`——这正是 vision 能力位的表达通道。因此 `pi.py:173` 与共享检查（`adapters/__init__.py:91`）的"capabilities flags not projected"对 vision 维度不准确（`tools` 方言与 `json_mode` 确无 Pi 通道，该部分告警成立）。处置可与 16.2 合并考虑：(a) `vision=true` 时投影 `input: ["text", "image"]`；(b) 至少拆分措辞，只对真正无通道的子字段告警。

### 16.4 【低 · 文档自相矛盾】本文档 §4.3 的 E5 行是陈旧定义，与全文其余各处冲突

§4.3 校验汇总中 E5 写作"label 使用保留词……不作硬限制"（一段关于 weak/editor 是自由标签的说明），但全文其余所有引用处——§10-D6（"E5（新增，见 §13.3 修复）进一步拦截'不同别名指向同一 upstream id'的歧义"）、§13.3、实现（`config.py` 的 upstream_key 校验）、测试（`test_pool_e5_duplicate_upstream_id_rejected`）——E5 均指"同 `(provider, upstream id)` 冲突校验"。§4.3 是在 §13.3 给 E5 赋予新含义时漏改的残留。应将 §4.3 的 E5 行改写为 upstream id 冲突校验，原保留词说明可并入注记。

### 16.5 【低 · 文档引用错位】§8.7 所称"Spec §7 触发表新增一行"未发生，且引用对象本身有误

触发表实际位于 **Principle §7**（Spec §12 明确写明"按 PRINCIPLE v2.1 §7 触发式升级表执行"），本次实际更新也在 Principle（diff 已核实）；Spec 本体未改动，其 §5.2 的 L2 定义仍是"主模型 + 角色模型"旧措辞。结果可接受（触发表的权威位置已被更新），但 §8.7 蓝图的文档引用（"Spec §7"）是错的，且 Spec §5.2 措辞与 Principle §2.2 现在不一致。建议：或在 Spec §5.2 L2 行补"（含可选模型池）"四字对齐；或在本节记录该偏差为有意取舍。

### 16.6 【信息 · 遗留开放项可直接关闭】§11 开放项 1（Pi `cost` 缺省表现）无需实测即可回答

`models.md` Model Configuration 字段表明示：`cost | No | all zeros`。即 ACM 不写 cost 时 Pi 按全零计费处理——无功能性问题，仅 `/cost` 类展示记为零。该开放项可据此关闭；若在意用量展示准确性，可另行评估把 ACM 未来新增的成本字段投影为 `cost`（当前 L2 无此字段，不属本轮范围）。

### 16.7 【低 · 措辞精确化】D10 的理由"Pi 无 per-model thinking level"不够准确

Pi 模型条目具备 `reasoning`（bool 能力位，L204）与 `thinkingLevelMap`（级别映射，L205/L269–298），所缺的只是"每模型默认思考级别"通道——`defaultThinkingLevel` 是 settings.json 的全局设置。D10"成员级 effort 不投影"的决策本身依然成立（确实没有每模型默认级别的落点），但决策理由应精确化，以免后来者据"Pi 无 per-model reasoning 字段"的误读做出错误推断（例如误删 thinkingLevelMap 相关的未来设计）。`pi.py` 中 reasoning 告警文案同理。

### 16.8 【信息 · UX 知情确认】`acm use` 的 SYNCED no-op 路径不打印任何投影损失告警

`cli.py::use_cmd` 在 `st.state == SYNCED` 分支直接 continue，`compute_agent_status` 返回的 `st.warnings` 被丢弃——首次 `use daily` 会打印 pool 聚合告警，第二次（no-op）不再打印。对幂等安静语义而言可以接受，但意味着"显式暴露"只在发生实际写入的那一次兑现。如认为告警应常驻，可在 no-op 分支补打 `st.warnings`；至少应在本文档知情留档（即为本条目的目的）。

### 16.9 复核总结论

- **架构与核心设计第四次复核后依然成立**：编译层扩展、执行层零改动的判断，pool 的 schema/resolve/plan 实现与 §8 蓝图及 §12–§15 修订记录的一致性，均经独立读码与实测确认。
- **需要行动的**：16.1（Type II skipped 判定的裸 id 比较，原则性缺口，修复成本低）；16.2/16.3（Pi temperature/capabilities-vision 的事实性告警文案，与 13.8 同类——按 §15 确立的先例，"该修还是要修"，最低限度也应修正文案）。
- **文档收口类**：16.4（§4.3 陈旧 E5 定义）、16.5（§8.7 引用错位与 Spec 措辞同步）、16.7（D10 理由精确化）。
- **可关闭/留档**：16.6（cost 开放项依据文档关闭）、16.8（no-op 告警行为知情留档）。
- 本轮再次验证了前几轮确立的两条方法论：外部事实必须回到官方文档原文核对（16.2/16.3 都是纸面推演过关、原文核对露馅）；一切"不可能发生"的判断都要用可运行反例攻击一次（16.1 由脚本实测复现，非推测）。

---

## 17. §16 三项中高严重度问题的处置与收尾复核（2026-08-25）

> 触发：用户对 §16.1–§16.3 的处置建议逐条提出异议；经逐条评估（评估结论：16.1 的异议建立在对场景的误读上——池成员在 ACM 管辖范围内而非"Agent 自动忽略"的外部配置，修复仅 5 行且场景是本特性明确服务的合法构造；16.2 的"MVP 不加投影"范围取舍成立，但不能覆盖事实错误的告警文案——与 §15 立下的"存量事实错误该修还是要修"先例矛盾；16.3 按用户自己的判据"有对应字段就映射"应走向映射而非忽略），最终授权按建议方案处理：**16.1 修比较符；16.2 只改文案不加投影；16.3 做 vision→input 映射**。§16.4–§16.8 按用户指示暂不处理。

### 17.1 代码修复

| # | 文件 | 改动 |
|---|---|---|
| 16.1 | `claude_code.py` / `codex.py` | 聚合告警的 skipped 判定由裸 `upstream_id` 相等改为 `(provider.name, upstream_id)` 二元组比较；跨 provider 同名 id 的池成员现在必然出现在 skipped 名单中。连带效应：此前"cheap 角色绑定到该成员时双通道全静默"的放大链随之闭合——成员被列入 pool 告警后，`roles.cheap` 的豁免重新变得正当（角色确已被 pool 告警覆盖）。两个适配器各补一个金样测试断言 `review(coding)` 出现在告警文案中 |
| 16.2 | `pi.py` | 新增 `_pi_member_unsupported_warnings(m, field_prefix)` 辅助函数，统一产出 temperature 与 capabilities 子字段的诚实措辞告警：temperature 文案为"ACM does not project per-model temperature into Pi models.json; Pi can express it via model-level samplingParams on OpenAI-compatible dialects, but ACM does not write that yet."——明确区分"Pi 不支持"与"ACM 未投影"。共享检查对 Pi 加入 `"temperature"`/`"capabilities"` 到 supported_fields，使其一刀切的事实性错误文案（"does not configure temperature/capabilities in config file"）对 Pi 永不触发，改由 pi.py 自身的诚实文案接管（main 与非 main 池成员一视同仁） |
| 16.3 | `pi.py` | `capabilities.vision=true` 时在模型条目写入 `"input": ["text", "image"]`（models.md L206 确认的原生字段），单模型路径与池路径（`_pi_model_entry`）均生效；capabilities 一刀切告警拆除，改为仅对真正无 Pi 通道的子字段分别告警：`capabilities.tools`（非 native 方言）、`capabilities.json_mode` |

### 17.2 文档同步

- `USER_GUIDE.md` / `USER_GUIDE.zh.md`：§7.3 Pi 投影损失清单与池成员行为 bullet 改写（vision 投影、temperature/tools/json_mode 分项告警及诚实措辞）；§7.4 能力矩阵将 `capabilities` 行拆为 `.vision`（Pi ✅ input）/ `.tools`/`.json_mode`（⚠️ 无通道），temperature 行的 Pi 列加注"samplingParams 可表达、ACM 未投影"。

### 17.3 验证记录

```
uv run pytest -q      → 126 passed（122 + 净增 4：
                          原 test_pi_pool_non_main_member_temperature_capabilities_warn
                            拆分为 temperature-warns-vision-projected + unexpressible-capabilities 两例；
                          新增 pi main 路径 temperature/vision 一例；
                          claude_code / codex 各新增跨 provider 同名 id 金样一例）
uv run ruff check .   → All checks passed
uv run mypy src       → Success: no issues found in 24 source files
```

### 17.4 遗留与边界确认

- §16.4–§16.8（文档收口类与留档类）按用户指示本轮未处理，维持开放。
- temperature **投影**本身（openai 方言下写 `samplingParams.temperature`）按用户的 MVP 范围决定不做，仅在文案中如实注明 Pi 具备该通道；未来如做，属增量改动，不影响本轮结构。
- 本节记录的行为变更均不触及 Safety Engine / status / state 层：`input` 只是 `providers.<name>.models[]` 条目内的新 key，幂等/drift/回滚对其透明（§7 论断的又一次应用）。
