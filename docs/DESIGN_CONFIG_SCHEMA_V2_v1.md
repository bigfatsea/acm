# ACM 配置 Schema V2 设计文档 —— Providers 内嵌 Models + Profile 保留子映射 `models`

> 状态：**已决策，待实施**（本文档由 `ANALYSIS_SCHEMA_V2_PROPOSAL_v1.md` 原地演进而来，
> 六项决策点已全部裁定，见 §0。经过一轮基于源码事实的独立 review 后，§0 追加了两条修正决策
> D-7/D-8，修正了原文档 §2.1 示例与 §2.6/§4/T1 数据形状之间的一处自相矛盾，以及 §3.3 中一处
> 未经确认就引入的新行为。Action Plan 见文末 §6，基于 2026-08-26 源码实况调查）。
> 治理依据：`ACM_PROJECT_PRINCIPLE_v2.1.md`（SSOT / 非破坏 / 精确可逆三公理）。

---

## §0 决策记录（已锁定）

| # | 决策点 | 裁定 |
|---|--------|------|
| D-1 | Profile 形态 | **B 形态**：单一保留子映射 `models:`（label → 模型引用）+ 显式 Opt-In 默认模型（`default: <label>` 可选行，与 `models:` 同级）。ACM 注册所有成员，但**仅当用户显式声明 `default` 时**才写 Agent 的默认模型字段。无 `default` 是正常声明态，不是缺陷，不告警。 |
| D-2 | 引用语法 | **R3**：成员值 = 模型引用；裸 `<id>` 或限定 `<provider>.<id>`。裸 id 全局唯一时可用；歧义时报错并列出候选 provider。provider 名禁止含点号。 |
| D-3 | models（provider 层）形状 | **映射（mapping），key 即上游 id**，内嵌于 `providers.<name>.models`。顶层 `models:` 表删除；模型条目中的 `id:`/`provider:` 字段随之消亡。ruamel 安全加载器天然拦截重复 key，无需额外去重机制（**已实测验证**，见 §2.2.2）。 |
| D-4 | 落地节奏 | **Proposal 1 + Proposal 2 合并为一次 schema v2 变更集**，一次性落地，不做中间形态。 |
| D-5 | capabilities.thinking | **并入 v2**：`capabilities.thinking: bool`（默认 false）作为模型目录元数据进入 v2 规格；投影语义与 `json_mode` 完全一致（有通道则投影，无通道则聚合进能力投影损失告警）。 |
| D-6 | Aider 角色名 | **忽略**：不为 Aider 的 `-m/--edit-model` 等角色槽位做任何设计预留；未来若支持走新 adapter，不占用本 schema 的语义空间。 |
| D-7 | **（修正）** Profile 成员的 YAML 形状 | 原文档 §2.1 示例将 label 与 `default` 平铺同级，但 §2.6/§4/T1 又将 `ProfileConfig` 描述为字面字段 `members: dict[str,str]` + `extra="forbid"`——两者互斥，不可能同时成立。**裁定：嵌套子映射，命名为 `models:`**（而非 `members:`，与 provider 层的 `models:` 形成对称命名——provider 下的 `models` 是模型定义，profile 下的 `models` 是模型引用）。依据：(a) v1 现有 `pool:` 就是嵌套子映射（`USER_GUIDE.md` §5.4、SPEC §7.3.3），v2 的 `models:` 是它的自然推广/改名，不是新发明；(b) V4 的 "label 不得占用保留键 `default`" 校验只有在嵌套形态下才是有意义、可达的（平铺形态下 `default:` 这个 key 会被 pydantic 命名字段直接吸收，不可能出现"某个 label 恰好叫 default"这种可区分场景——**但见下一条，V4 该分支已随此修正一并删除**）；(c) 免去 `extra="allow"` + `__pydantic_extra__` 手动过滤的既有 v1 遗留写法。 |
| D-8 | **（修正）** CC/Codex 在无 `default` 时的投影行为 | 原文档 §3.3 曾提议：无 `default` 但全体成员同属一个 provider 时，CC/Codex 新增写入连通性字段（`env.ANTHROPIC_BASE_URL/AUTH_TOKEN`、Codex `model_providers.*` 表），只是不写 `model`。**已实测确认这是 v1 没有的新行为**（现状 `claude_code.py:58-67`、`codex.py:55-64`：无 `main` 时是纯零 ops，仅一条告警）。**裁定：不做此扩展，CC/Codex 在无 `default` 时严格保持 v1 现状——零 ops，一条告警**。这不是"schema 重构的自然结果"而是独立的新功能，本轮不做；若未来需要，作为独立提案单独评估。此修正同时简化了 §3.3——原三分连通性规则收窄为两分（有 default / 无 default），不再需要"多 provider 消歧"这条分支和对应的 `_connectivity_provider` helper。 |

---

## §1 目标与非目标

### 1.1 目标

1. **消除 main/pool 二象性**：v1 中"main 驱动默认值、pool 驱动注册、registration-only 特例"三条路径合并为一条——profile 的 `models:` 就是成员集合，`main` 不再是结构上特殊的字段。
2. **注册与选型彻底分离**：ACM 把 profile 的 `models:` 成员注册进 Agent 的模型目录（凡有通道者）；Agent 内的"当前用哪个"由用户在 Agent 里选（`/model` 等），或通过显式 `default` 行委托给 ACM。
3. **消灭别名层**：不再需要 `models.coding → provider: vmr, id: coding` 这种纯转发别名；模型直接定义在 provider 下，key 即上游 id。
4. **显式 Opt-In 的默认模型**：`default: <label>` 是唯一驱动 ACM 写 Agent 默认模型字段的开关，回滚/漂移边界因此清晰。

### 1.2 非目标

- 不实现 `acm import/diff/doctor/history`（触发器未满足，Spec v2.1 §12）。
- 不为 Aider 或其他未内置 Agent 设计角色映射（D-6）。
- 不引入 `${VAR}` 语法的任何扩展；凭据引用规则原样继承（严格整字段语法）。
- 不改动 Safety Engine 六步管线、writers、锁机制、快照机制——它们与 config 形状正交（**已核对 `safety.py` 全文，六步管线不引用任何 Profile/Model 具体字段名，正交性成立**）。
- **不新增 CC/Codex 无 default 时的连通性投影**（D-8）——本轮严格保持 v1 对等行为。
- 本轮不做真机 `~/.acm/config.yaml` 迁移（T10.2 推迟，见执行范围说明）。

---

## §2 Schema v2 完整规格

### 2.1 总览示例

```yaml
version: 2

providers:
  vmr:
    protocol: openai
    base_url: http://192.168.0.22:8800/v1
    api_key: "${VMR_KEY:-}"
    models:
      coding:
        context_window: 512000
        max_output_tokens: 16384
        temperature: 0.2             # 缺省 = 不写入，用 Agent 默认
        capabilities:
          vision: true
          tools: native              # native | xml | markdown
          json_mode: true
          thinking: true             # v2 新增：扩展思考能力标记
        reasoning:
          effort: high               # low | medium | high
          budget_tokens: 16000
      cheap:
        context_window: 128000

  anthropic-direct:
    protocol: anthropic
    base_url: https://api.anthropic.com
    api_key: "${ANTHROPIC_API_KEY}"
    headers:
      X-Custom: value
    models:
      "anthropic/claude-3.7-sonnet:thinking":
        context_window: 200000       # 含点/斜杠/冒号的 id 直接作 key，无需转义

profiles:
  daily:
    default: coder                   # 显式 Opt-In：唯一允许驱动 Agent 默认模型字段的方式
    models:                          # 保留子映射：label -> 模型引用
      coder: coding                  # 裸 id
      reviewer: anthropic-direct.anthropic/claude-3.7-sonnet:thinking   # 限定引用

  budget:
    models:
      fast: cheap                    # 无 default 行：纯注册，Agent 默认字段保持用户自管
```

行数对比：等价 v1 配置约 29 行 → v2 约 21 行；概念从四层（providers/models/profiles.main/pool）收敛为两层半（providers.models / profiles.models）。

### 2.2 providers 层（L1 + 内嵌 L2）

#### 2.2.1 ProviderConfig 字段（不变项）

| 字段 | 类型 | 说明 |
|---|---|---|
| `protocol` | `openai \| anthropic \| openai-responses` | 必填，不变 |
| `base_url` | str | 必填，http(s) 校验，不变 |
| `api_key` | str | 必填，`${VAR}` / `${VAR:-d}` 严格整字段引用，不变 |
| `headers` | dict[str,str] | 可选，不变 |
| `proxy` | str \| None | 可选，不变 |

#### 2.2.2 新增 `models` 内嵌映射（核心变更）

`providers.<name>.models` 为 **mapping，key = 上游模型 id 原文**：

- key 保留任意字符（`.` `/` `:` 等），YAML 中按需加引号；ruamel 安全加载器对重复 key 硬报错，天然满足"上游 id 在同一 provider 下唯一"。**已实测验证**：`YAML(typ="safe").load()` 对同一映射内的重复 key 抛出 `DuplicateKeyError`（继承自 `YAMLError`），会被 `parse_config_yaml` 现有的 `except YAMLError` 分支捕获并转换为 `ConfigError`，无需任何新代码。
- 每个条目即原 v1 `ModelConfig` **减去** `provider` 与 `id` 两个字段（二者分别由所在 provider 与 key 表达）。
- 其余规格字段全部原样保留：`context_window`、`max_output_tokens`、`temperature`、`capabilities`、`reasoning`。

#### 2.2.3 ModelCapabilities v2（含 D-5）

| 字段 | 类型 | 默认 | 说明 |
|---|---|---|---|
| `vision` | bool | false | 不变 |
| `tools` | `native \| xml \| markdown` | `"native"` | 不变 |
| `json_mode` | bool | false | 不变 |
| `thinking` | bool | false | **v2 新增**。语义：该模型支持扩展思考。投影规则与 `json_mode` 一致——Pi/CC/Codex 目前均无此通道，出现且非缺省时聚合进各 adapter 的能力投影损失告警。它是目录元数据：向用户和未来的 adapter 声明能力，不产生任何静默效果。 |

#### 2.2.4 命名约束（V1）

- **provider 名禁止包含 `.`** 且不得为空、不得首尾含空白。理由：(a) R3 限定引用以第一个 `.` 切分；(b) Codex 以 provider 名作 TOML 表键（`model_providers.<name>`），点号会破坏 dot-path 寻址；(c) Pi 的 `providers.<name>` JSON dot-path 同理。**当前代码未对 provider 字典 key 做任何字符集校验，这是 v2 真正新增的约束，非既有行为的文档化。**
- 模型 id（即 mapping key）**无字符限制**；但**已实测纠正一处原文档错误**：pydantic v2 的 `model_validate` 对 `dict[str, X]` 字段的**非字符串 key 不会静默强转字符串，而是直接抛出 `ValidationError`**（`Input should be a valid string [type=string_type]`）。这与原文档"pydantic 会把非字符串 key 强转为字符串"的表述相反。由于该行为是 pydantic 默认行为、v1 现有的顶层 `models:` 映射已经继承同样的特性（并非 v2 新引入），处置方式：**维持拒绝（不新增强转代码）**，YAML 中纯数字 id（如模型名恰好是 `"4"` 这种边缘情况）必须加引号。测试改为钉死"拒绝"而非"强转"。

### 2.3 profiles 层（L3）：保留子映射 `models` + Opt-In（D-7 修正后）

```yaml
profiles:
  <profile-name>:
    default: <label>        # 可选，至多一行
    models:                 # 必填，保留子映射，≥ 1 项
      <label>: <model-ref>  # label 为自定义角色/成员名
```

- **label**：非空字符串，是"这个 profile 里的成员名"，声明于 `models:` 子映射内。v1 的 `main`/`cheap`/`pool` 及 extra-role 四种通道**全部消亡**，统一为 `models:` 下的一行。`main` 不再是特殊键——它只是一个普通 label。
- **保留字段 `default`**：与 `models:` 同级，值为 `models:` 内已存在的某个 label。这是 B 形态的 Opt-In 开关：
  - 有 `default` → ACM 向具备默认模型通道的 Agent 写入该成员作为默认（Pi: settings.json 三件套; CC: `model`; Codex: `model`+`model_reasoning_effort`）。
  - 无 `default` → ACM **绝不触碰**任何 Agent 的默认模型命名空间；这些字段保持用户自管。此为正常声明态，**不产生任何告警**（取代 v1 registration-only 的显式提示——v1 提示的前提"没有 main 是特例"在 v2 不成立）。
  - `default` 的值必须等于 `models:` 内某个已存在的 label；否则报错（V4）。**（D-7 修正）** 原 V4 还包含"label 不得占用保留键 `default`"一条——嵌套形态下 `default:`（profile 顶层字段）与 `models:` 内部的 label 天然位于不同命名空间，不存在结构性冲突，该分支**已删除**，不再实现、不再测试。
- **成员值 = R3 模型引用**，见 §2.4。

### 2.4 R3 引用语法规则

成员值 `<model-ref>` 按以下确定性算法解析（load 时执行，失败即拒绝整个配置加载，符合"硬错误先于任何磁盘写"铁律）：

| 形式 | 解析 | 失败模式 |
|---|---|---|
| `<provider>.<id>`（限定） | 以**第一个** `.` 切分：前段必须命中某 provider 名，后段整体（可再含 `.`）为其下模型 key | provider 不存在 → 报错；该 provider 下无此模型 key → 报错 |
| `<id>`（裸） | 在**全配置范围**的所有 `providers.*.models` 中查找 key 恰好等于 `<id>` 的条目 | 命中 0 个 → 报错"unknown model"；命中 ≥2 个 → 报错并列出全部候选，要求改写为限定形式 |

示例：

```yaml
profiles:
  daily:
    models:
      coder: coding                                  # OK：全局唯一裸 id
      reviewer: anthropic-direct.claude-sonnet         # OK：限定引用
      x: vmr.gpt-4o.2                                  # OK：id 含点，首个点后整体作 id
```

歧义错误消息样例（实现须逐字对齐测试断言）：

```
Profile 'daily' member 'coder': model id 'sonnet' is ambiguous — defined in providers:
['anthropic-direct', 'vmr']. Use a qualified reference like 'vmr.sonnet'.
```

设计要点：

1. **切分点是第一个点** ⇒ provider 名禁点的 V1 约束使切分无歧义；id 含点不受影响。**已用 `anthropic-direct.anthropic/claude-3.7-sonnet:thinking` 手工验算**：provider 名本身无点，第一个点必然落在 provider 名与 id 之间，无论 id 内部还含多少个点都不受影响。
2. **裸 id 歧义检查是全局的**（而非仅限本 profile 引用到的 provider）⇒ 同一配置在任何 profile 下的解析结果一致，规则可预测、错误可在 load 时一次性穷尽。
3. 不同 profile 的成员解析到同一 (provider, id) **合法**（跨 profile 复用不受限）；同一 profile 内两个 label 解析到同一 (provider, id) **非法**（V5，避免 Agent 选择器中出现重复条目）。

### 2.5 校验规则总表（V1–V8）

| # | 规则 | 错误类型 | 替代/新增 |
|---|---|---|---|
| V1 | provider 名：非空、不含 `.`、无首尾空白；模型 key：非空 | ConfigError | 新增（R3/Codex 表键前提，**已核实当前代码无此校验**） |
| V2 | 每个 profile 的 `models:` 子映射 ≥ 1 项 | ConfigError | 替代 v1 "main or pool" 检查 |
| V3 | 每个成员引用按 §2.4 解析成功（存在性 + 歧义性） | ConfigError | 替代 v1 交叉引用检查 |
| V4 | `default` 值必须等于 `models:` 内某个成员 label | ConfigError | 新增（B 形态）；**（D-7）不再包含"标签占用保留键"分支** |
| V5 | 同一 profile 内不允许两个 label 解析到相同 `(provider, upstream_id)` | ConfigError | 继承 v1 pool 去重语义，扩大到全体成员 |
| V6 | `version == 2`；其余值报"Unsupported config schema version"并指引重新初始化 | ConfigError | 替代 v1 版本校验 |
| V7 | 凭据引用严格整字段 `${VAR}` / `${VAR:-d}` 语法（resolve 阶段，不变） | ConfigError | 不变 |
| V8 | `extra="forbid"` 全层级生效：顶层 `models:`、profile 内 `main:`/`cheap:`/`pool:` 等旧键一律拒绝 | pydantic ValidationError | 自动获得 |

> 迁移语义：**不做 v1→v2 自动迁移、不做旧结构检测**（沿用 YAML 迁移 D5 先例）。`version: 1` 的旧文件按 V6 直接拒绝，错误信息指引用户手工改写或重跑 `acm init --force`。**本轮不做真机迁移**（见执行范围说明），真实机器上的个人配置留待后续单独任务处理。

### 2.6 数据类形状（resolve.py）

```python
class ResolvedProfile(BaseModel):
    model_config = ConfigDict(extra="forbid")
    profile_name: str
    models: dict[str, ResolvedModel]       # label -> 已解析成员，保持声明顺序
    default_label: str | None = None       # 来自 Opt-In 行

    # 便捷属性（供 adapters 使用）
    # default_model: ResolvedModel | None  => models[default_label] if default_label else None
```

`ResolvedModel` 字段变化（`model_id` 与 `upstream_id` 合并为单字段 `model_id`——别名层消亡后二者恒等；provider/context_window/max_output_tokens/temperature/capabilities/reasoning 不变）。

---

## §3 语义规范

### 3.1 注册 / 选型分离原则（不变式）

- **注册**：把 profile 的 `models:` 成员登记进 Agent 的模型目录（Pi `models.json` 的 `providers.<prov>.models[]`）。CC/Codex 无注册通道 → 成员不可达，见 §3.3。
- **选型**：设定 Agent 启动时的当前默认模型。v2 中只有一条合法路径：profile 的 `default:` 行。
- 推论：切换 profile（`acm use other`）**只改变 default 所指**（若双方都有 default），已注册成员永不因切换而被撤销——累积语义与 v1 pool 相同，且不再是隐式行为而是唯一行为。

### 3.2 Opt-In 精确语义：每 Agent 行为矩阵（D-8 修正后）

记 `D = default_model`（default 行所指成员），`P_D` 为其 provider。

| Agent | 注册行为（无条件） | 选型行为（有 default） | 选型行为（无 default） |
|---|---|---|---|
| **Pi** | 全体成员按 provider 分组注册进 `models.json` 的 `providers.<prov>`（每组成员带 label 作 `name`、contextWindow/maxTokens/input 按 L2 规格展开） | 写 `settings.json`：`defaultProvider = P_D.name`、`defaultModel = D.model_id`；若 `D.reasoning.effort` 则加写 `defaultThinkingLevel` | **零 ops 触及 settings.json**；不告警 |
| **Claude Code** | 无通道（成员不可达，见 §3.3） | `env.ANTHROPIC_BASE_URL/AUTH_TOKEN` ← P_D 连通性；`model = D.model_id`；若 effort 则 `effortLevel` | **零 ops（与 v1 registration-only 完全一致）**；一条告警："profile declares no default; nothing to project" |
| **Codex** | 无通道 | `model_provider`、`model_providers.<P_D>.*`（name/base_url/wire_api/env_key）、`model = D.model_id`；若 effort 则 `model_reasoning_effort` | **零 ops（与 v1 registration-only 完全一致）**；一条告警，同上 |

L2 规格投影损失告警跟随**每个成员的实际表达通道**：

- Pi：对全体成员逐个检查 temperature/capabilities.tools/json_mode/**thinking**/reasoning（budget_tokens 仅对 D 成员查，因其只在 settings 语境有意义），field 前缀 `models.<label>.*`。
- CC/Codex：仅当有 default 时对 D 成员检查 budget_tokens/context_window/temperature/capabilities/provider.headers/proxy（沿用现词汇表）；无 default 时无 L2 检查对象（提前返回）。
- `check_unsupported_profile_specs()` 中 v1 的 cheap/extra_roles 分支**删除**（角色概念消亡）；函数收缩为"对给定单一 ResolvedModel 的规格检查"，由各 adapter 对相应成员调用。

### 3.3 可达性投影规则（D-8 修正后：二分，不再有"多 provider 消歧"分支）

CC/Codex 只能指向一个端点。规则（两 adapter 共享，helper 置于 `adapters/__init__.py`）：

1. **有 default** → 连通性提供方 = `P_D`。其余成员一律不可达：若存在与 `P_D` 不同 `(provider, upstream_id)` 的其他成员，发**一条聚合告警**（field=`models.unreachable`）列出 `label(upstream_id@provider)` 清单。
   - 协议方言告警（CC 非 anthropic / Codex anthropic→chat 回退）按 P_D 判定，逻辑不变。
2. **无 default** → **零 ops，一条告警**（"profile has no default; nothing to project for this agent"），与 v1 registration-only 完全一致。**不再区分"全体成员是否同属一个 provider"**——该区分对应的连通性专属投影已在 D-8 中裁定不做。

> Pi 永不受本节影响：它按 provider 分组全量注册，不存在"选一个 provider"的问题。

### 3.4 告警词汇变更清单

| v1 词汇 | v2 处置 |
|---|---|
| `profile.main`（registration-only 提示，Pi/CC/Codex 三处） | Pi 侧删除（无 default 是正常态，不告警）；CC/Codex 侧保留同等语义的"无 default，零投影"告警，措辞去掉"main"字样 |
| `pool`（CC/Codex aggregate skipped-members） | 更名语义化为 `models.unreachable`，比较键仍为 `(provider, model_id)`（v2 中 `upstream_id` 已并入 `model_id`，见 §2.6） |
| `pool.<label>.reasoning` / `pool.provider.<prov>.proxy`（Pi） | 前缀改 `models.<label>.*` / `models.provider.<prov>.proxy`；语义不变 |
| `roles.cheap` / `roles.extra`（check_unsupported_profile_specs） | **删除** |
| capabilities 能力损失告警 | 扩展覆盖 `capabilities.thinking`（措辞与 json_mode 同款："no thinking-capability channel … not projected"） |
| E2/E5（resolve.py 的 implicit-main / pool 冲突文案） | E5 语义升级为 V5 全成员去重（文案改 `models` 术语）；implicit-main 相关分支随 main 特殊地位消亡而消失 |

### 3.5 漂移检测兼容规则（关键机制）

**问题**：`last_write.json` 记录的是"上一次投影实际管理的字段"。v2 上线后，用户把带 default 的 profile 改成无 default 再投影，Pi 的 `settings.json::defaultModel` 等旧记录仍在 last_write 里；此后用户在 Pi 里自行 `/model` 切换即被误判 DRIFTED，阻塞后续 `use`。v1→v2 升级窗口同理。

**机制调查结论**（源码实况，**已逐行核对 `safety.py` L255-265**）：`write_changeset()` 第 6 步是**整体替换** last_write（`last_write_fields = {f"{op.file.name}::{op.path}": op.new for op in ops}`，每次都是全新 dict，不与旧 `last_write.fields` 合并），所以只要用户在改配置后跑过一次 `use`，陈旧记录即消失。风险窗口仅在"改配置之后、下次 use 之前"的 status 检查。**同时核实**：`op.new` 恒为期望值，从不为 `NOT_EXIST_SENTINEL`——该哨兵值只在 `rollback_cmd` 重建 `last_write.fields` 时才可能出现（`cli.py` L526），与 `write_changeset()` 无关；`status.py` 中对哨兵分支的处理对两种来源都成立，managed_paths 过滤不会破坏这条防御性代码。

**规则**：漂移比较范围 = *last_write 记录 ∩ 当前 plan() 将产出的 op 路径集合*。

- 实现：`detect_agent_drift(adapter, env, managed_paths: set[str] | None = None)` 增加可选参数；`compute_agent_status()` 已持有 resolved_profile，先算一次 `ops, _ = adapter.plan(...)`，把 `{f"{op.file.name}::{op.path}" for op in ops}` 传入。`managed_paths is None` 时保持现行为（向后兼容既有调用与测试）。
- **实现注意**（本轮review补充）：`compute_agent_status()` 当前的执行顺序是"3. last_write 检查 → 4. drift 检查 → 5. resolved_profile is None 检查 → 6. 计算 ops"，即 drift 检查（第4步）目前发生在"resolved_profile 是否为 None"的判断（第5步）**之前**——意味着即使当前没有激活 profile，也仍会做 drift 检查（这是现状的既有行为，不应破坏）。因此第4步预计算 `ops` 时必须做空值防御：`managed_paths = None if resolved_profile is None else {...adapter.plan(resolved_profile, env)...}`；`resolved_profile is None` 时退化为现行为（不过滤），不能因为要传参而提前把"无激活 profile"也判成别的状态。
- 该规则同时修正一个 v1 期既有的边角瑕疵：跨 profile 切换后，旧 profile 独有字段的磁盘变化不再计入漂移——与公理三"rollback 粒度 = 当前管理字段的逆"完全一致。
- `LastWrite` 数据格式**不变**（无需版本戳）。

---

## §4 各组件行为规格摘要

| 组件 | v2 行为 |
|---|---|
| `config.py` | `CoreConfig.version==2`；顶层 `providers/profiles` 两表；`ProviderConfig.models: dict[str, ModelSpecConfig]`；`ModelSpecConfig`=原 ModelConfig 去 provider/id；`ModelCapabilities.thinking`；`ProfileConfig{models: dict[str,str], default: str\|None}`（extra=forbid）；交叉校验重写为 V1–V5（V4 无"保留键"分支，见 D-7）；`parse_config_yaml`/loader 契约不动 |
| `resolve.py` | `resolve_profile` 重写：可达 provider = 全体成员引用之 provider 并集；逐成员凭据解析（任一缺失 → 整体硬错，不变）；产出 `ResolvedProfile(models, default_label)`；V5 全成员去重复核保留（防御纵深） |
| `adapters/__init__.py` | 新增共享 helper：`_effective_default(profile)`、`_unreachable_members(profile, default_label)`（D-8 修正后只需二分逻辑，**不需要** `_connectivity_provider` 三分 helper）；`check_unsupported_profile_specs` 收缩为单成员规格检查 |
| `adapters/pi.py` | 双路径（main/pool）合并为单路径：分组注册全体成员；settings 三件套 ops 仅当 `default_label` 存在；删除 registration-only 告警；成员级 L2 告警遍历全体成员 |
| `adapters/claude_code.py` | 有 default → 现有逻辑改用 `profile.models[default_label]`；无 default → **保持现有零 ops + 单条告警的代码路径不变**（D-8），只是措辞去掉"main"字样；unreachable 聚合告警更名 |
| `adapters/codex.py` | 同上对称改造 |
| `status.py` | §3.5 managed_paths 过滤（含空值防御） |
| `safety.py` / `state.py` / `lock.py` / `writers/*` / `masking.py` / `errors.py` | **零改动** |
| `vmr.py` | `generate_vmr_proposal` / `generate_template_config` 输出 v2 形状（嵌套 models；`profiles.daily.models` 子映射；模板中给出注释掉的 `# default: coder` 示例行）；探测逻辑本身不变 |
| `cli.py` | init 横幅措辞更新（提及 v2 结构与 default 用法）；use/status/rollback 流程零改动 |

---

## §5 源码影响面调查（2026-08-26 实况，本轮 review 补充了缺漏项）

逐文件清单，含精确锚点。"行号"为撰写时快照，仅供定位参考，以符号名为准。

| 文件 | 改动性质 | 具体位置 |
|---|---|---|
| `src/acm/config.py` | **重写核心段** | `ProviderConfig` +`models` 字段；`ModelCapabilities` +`thinking`；`ModelConfig`→改名/瘦身（去 provider/id）；`ProfileConfig` 整体重塑（main/cheap/pool→models/default，extra=allow→forbid）；`CoreConfig.validate_version` 改 ==2；`validate_cross_references` 按 V1–V5 重写；`parse_config_yaml`/`load_config` 不动 |
| `src/acm/resolve.py` | **重写主体** | `ResolvedModel` 合并 model_id/upstream_id；`ResolvedProfile` 重塑（`models`/`default_label`）；`resolve_profile` 可达性收集、`_resolve_model`、V5 复核全部替换为 models 解析 + 复核；ENV_REF_PATTERN/evaluate_credential 不动 |
| `src/acm/adapters/__init__.py` | 中改 | `check_unsupported_profile_specs` 收缩签名 `(member: ResolvedModel \| None, agent_id, supported_fields)`；新增 `_effective_default`/`_unreachable_members` 两个共享 helper（D-8 后不需要三分 helper）；Protocol 不变 |
| `src/acm/adapters/pi.py` | **重写 plan()** | 现 L142–L312 双路径合一；`_pi_model_entry`/`_pi_api_dialect`/`_resolve_pi_api_key`/`_pi_member_unsupported_warnings`(扩 thinking) 留用微调；`managed_namespaces` 不变 |
| `src/acm/adapters/claude_code.py` | 小改（比原方案更小，因 D-8） | plan() L47 起：`profile.main` → `profile.models[default_label]`；无 default 分支代码结构基本不变，只改措辞；pool aggregate→`models.unreachable`；managed_namespaces 不变 |
| `src/acm/adapters/codex.py` | 小改，同上对称 |
| `src/acm/status.py` | 小改 | `detect_agent_drift` 加 `managed_paths` 参数与过滤（含 §3.5 补充的空值防御）；`compute_agent_status` 预计算 ops 并传参；六态机/优先级/出口码不变 |
| `src/acm/safety.py` | 零改动 | 已核对全文确认 |
| `src/acm/vmr.py` | 小改 | `generate_vmr_proposal`(L140)、`generate_template_config`(L186) 输出形状；probe/`_q` 不动 |
| `src/acm/cli.py` | 微改 | init 横幅文案；命令流程零改动 |
| `util/errors/masking/output/state/lock/projection/main` | 零改动 | — |
| `tests/conftest.py` | 改 | `sample_config_yaml` 重写为 v2 样例（含一个 default 行 profile + 一个无 default profile，覆盖双形态）；`MockAdapter` 不变 |
| golden 测试 ×4 | 改 | 直接构造 `ResolvedProfile(main=…, pool=…)` → `ResolvedProfile(models=…, default_label=…)`；断言的 op 路径大多存活；`test_adapters_pool_only.py` 更名/改写为 registration-only 场景 |
| integration 测试 | 改 | **本轮补充遗漏项**：原文档 §5/§6 清单未列出 `tests/integration/test_cli_pi.py`——已实测确认该文件内嵌 2 处 `version: 1` 的 v1 形状 YAML（含 `main:`/`pool:`/`cheap:`），会在 v2 落地后直接破坏，需与 `test_cli_claude.py`/`test_cli_codex.py`/`test_cli_use.py`/`test_cli_status.py`/`test_cli_rollback.py`/`test_e2e_acceptance.py`/`test_exit_codes.py` 一并翻新 |
| `tests/unit/test_projection.py` | 改 | 适配收缩后的 check_unsupported_profile_specs |
| 文档 | 改 | USER_GUIDE.md/.zh.md（§5 配置参考、§7 映射矩阵、pool 章节）、README×2、CLAUDE.md（Schema Essentials/架构行/Implementation Status）、SPEC §7.3+A.1+D3 关联句、PRINCIPLE 三层叙述改两层、DESIGN_MODEL_POOL_v1.md 冻结归档（历史特征文档，正文不再被活文档引用） |

**明确不动**：golden fixtures 目录（`tests/fixtures/`）、Codex 目标文件 TOML 性质、VMR fallback `~/.vmr/config.toml`、Safety Engine/writers/锁/快照、fault 测试。

---

## §6 Action Plan（可执行细节）

> 执行顺序即依赖顺序；每个 Task 结束跑 `uv run pytest`（相关子集）+ `uv run ruff check .` + `uv run mypy src`，三者绿才算完成。
> **执行范围（本轮已与用户确认）**：只改仓库内文件，不做 git commit（工作区改完由用户自行 review/commit）；不做 T10.2 真机 `~/.acm/config.yaml` 迁移（推迟到 repo 侧稳定之后另行决定）；T1–T9 + T10.1（版本号）一次性做完。

### T1 — Schema 核心（config.py）

1. `ProviderConfig` 增加 `models: dict[str, ModelSpecConfig] = Field(default_factory=dict)`。
2. `ModelConfig` 更名 `ModelSpecConfig`，删除 `provider`、`id` 字段；`ModelCapabilities` 增 `thinking: bool = False`。
3. 新建 `ProfileConfig`：`models: dict[str, str]`（声明序）、`default: str | None`；`extra="forbid"`。
4. `CoreConfig`：删顶层 `models`；`version` 校验改 `!= 2`（错误文案含 "re-run 'acm init' or rewrite to version: 2"）。
5. `validate_cross_references` 按 V1–V5 重写（含 R3 解析器 `_resolve_ref(ref, core) -> tuple[str, str]`，歧义错误文案按 §2.4 样例逐字实现）。
6. **（本轮修正）** `default` 与成员 label 的"保留键冲突"校验**不再需要**（D-7：嵌套形态下命名空间天然不冲突）；只需校验 `default` 值存在于 `models` 内。
7. 测试：`test_config.py` 全面翻新（V1–V8 各至少 1 正 1 负；歧义/未知/限定引用三分支；int-key **拒绝**钉子——**本轮修正**：pydantic 实测会 `ValidationError` 拒绝非字符串 key，不是强转，测试断言方向相反；thinking 默认值）；`test_yaml_loader.py` 中涉及旧形状的内嵌样例同步更新。

**Done**: 单测绿；旧版 `version: 1` 样例被拒且有专属测试。

### T2 — resolve.py

1. `ResolvedModel` 合并 `model_id`（删 `upstream_id`）；`ResolvedProfile` 重塑为 `models`/`default_label` + `default_model` property。
2. `resolve_profile`：成员引用复用 T1 的 `_resolve_ref`；可达 provider 并集解析凭据（缺失变量聚合报错，文案不变）；构造 `models`（保序）；V5 复核（错误文案改 `models` 术语）。
3. 测试：`test_resolve.py` 翻新——双 provider 歧义、`${VAR:-d}` 缺失聚合、V5、空 profile（应被 T1 的 V2 拦截，反向验证）、保序性。

**Done**: 单测绿；`ResolvedProfile` 无 main/cheap/pool/members 残留（grep 断言入 CI 心智，不入代码）。

### T3 — 共享 helper 与告警收缩（adapters/__init__.py + test_projection.py）

1. 实现 `_effective_default(profile) -> tuple[str, ResolvedModel] | None`、`_unreachable_members(profile, default_label) -> list[tuple[str, ResolvedModel]]`（D-8 后只需二分，不实现三分 `_connectivity_provider`）。
2. `check_unsupported_profile_specs(member: ResolvedModel | None, agent_id, supported_fields) -> list[ProjectionWarning]`：仅保留 temperature/capabilities(+thinking)/headers/proxy/budget_tokens/context_window 的单成员检查。
3. 测试：`test_projection.py` 翻新；有 default / 无 default 正负例。

### T4 — Pi adapter

1. plan() 合并双路径：分组注册全体成员（每组一个 `providers.<prov>` op，组内 entry 由 `_pi_model_entry` 生成）；`_pi_member_unsupported_warnings` 扩 `thinking` 分支；对全体成员施加。
2. settings 三件套 ops 包在 `if profile.default_label:` 内；删除 registration-only 告警分支；`reasoning.budget_tokens` 告警仅对 D 成员。
3. proxy 告警判定改为 §3.4 新语义（`models.provider.<prov>.proxy`）。
4. 测试：golden/test_adapters_pi.py 构造方式翻新；`test_adapters_pool_only.py` → registration-only（无 default）断言：models.json 有 ops、settings.json 零 ops、零相关告警；新增 opt-in 场景断言三件套 ops 存在；**`tests/integration/test_cli_pi.py` 内嵌 YAML 同步翻新（本轮补充遗漏）**。

### T5 — Claude Code / Codex adapters

1. 两 adapter 对称落地 §3.2/§3.3（D-8 后的二分版本）：`model`/effort 类 ops 条件化；aggregate `models.unreachable` 告警（比较键 `(provider, upstream_id)`）；方言告警按 P_D；无 default 分支代码结构基本保持现状，只改措辞去掉"main"字样。
2. 测试：golden/test_adapters_claude.py、test_adapters_codex.py 翻新；integration test_cli_claude/codex 内嵌 YAML 翻新 + 各加 opt-in/no-opt-in 双案例；断言 exit code 不变。

### T6 — 漂移过滤（status.py）

1. `detect_agent_drift` 加 `managed_paths: set[str] | None = None`，过滤逻辑 §3.5；`compute_agent_status` 预计算 ops 并传入，**含 resolved_profile 为 None 时的空值防御**（见 §3.5 实现注意）。
2. 测试：test_status.py 新增负例——stale defaultModel 记录 + 用户已改默认 + 当前 plan 不含该路径 → 不判 DRIFTED；无激活 profile 时 drift 检查仍正常工作（回归现状行为）；正例回归既有全部漂移测试。

### T7 — vmr 生成器与 init

1. `generate_vmr_proposal`：输出嵌套 models 映射；profile 给 `daily`（`models:` 子映射=探测到的模型，注释掉的 `# default: ...` 行）；`generate_template_config` 同步 v2 并含 capabilities.thinking 示例。
2. cli init 横幅措辞更新；test_cli_init 的横幅断言与 0600 权限测试照旧适配。

### T8 — 横切集成测试收口

conftest `sample_config_yaml` 重写（双形态 profile）；test_cli_use/status/rollback/e2e_acceptance/exit_codes **以及 test_cli_pi**（本轮补充）内嵌 YAML 全面翻新；新增集成场景：

1. use 带 default 的 profile → Pi settings 三件套 + CC model + Codex model 均写入；
2. 切到无 default 的 profile → 再次 use 后上述字段**不被触碰**且 status 无 DRIFTED（§3.5 端到端验证）；
3. 无 default profile（无论成员是否跨 provider）→ CC/Codex 零 ops + 单条告警，exit code 仍 0（D-8：不再有"多 provider connectivity 告警"这个新场景）。

**Done**: 全量 pytest 绿。

### T9 — 文档同步（活文档 as-if-v2，零修订注记）

USER_GUIDE×2（配置参考整章、§7 矩阵、告警词汇、故障排查）、README×2 示例、CLAUDE.md（三层→两层叙述、Schema Essentials、Implementation Status 的 pool 行改写）、SPEC（§7.3 示例与规则、A.1、D3 关联句、§7.3.3 删除）、PRINCIPLE（分层叙述）。`DESIGN_MODEL_POOL_v1.md` 头部加冻结标注（历史文档），移除活文档中对它的指向。本设计文档（`DESIGN_CONFIG_SCHEMA_V2_v1.md`）在 T9 完成后也应视为历史文档，正文内容折叠进 SPEC/PRINCIPLE 后冻结。

### T10 — 版本、冒烟与收尾

1. 版本三元组 → **0.3.0**（pyproject / `__init__` / test_version）。
2. ~~真机迁移~~ **本轮推迟，不执行**。
3. 全量门禁 + repo 级 grep 收尾（`grep -rn "pool\|\bmain\b\|cheap\|members" src/ tests/` 应仅剩无关命中）；本文档勾掉执行记录。

---

## §7 风险登记

| # | 风险 | 缓解 |
|---|---|---|
| R-b | 裸 id 歧义在用户增删 provider 后行为变化 | 歧义是 load 时硬错误，永远不会静默改变投影目标；报错列出候选 |
| R-c | 升级窗口误报 DRIFTED（§3.5） | managed_paths 过滤 + T8 场景 2 端到端回归钉死；+ resolved_profile=None 空值防御 |
| R-e | golden fixtures 作为上游 schema 哨兵的地位 | 本计划不触碰 fixtures 目录；adapter 断言变化全部落在测试代码侧 |
| R-f | 大规模测试翻新引入回归 | 每 Task 独立绿；T8 全量收口；e2e_acceptance 除目标文件内容外流程断言不动 |

（原 R-a"保留键冲突"、R-d"CC/Codex 连通性投影困惑"随 D-7/D-8 修正而消失，不再是风险。）

## §8 验收标准

1. 三门禁全绿；测试总数 ≥ 原 150 + 新增。
2. §2.1 总览样例可被 `load_config` 接受并通过三 adapter plan() 产出 §3.2 矩阵所述 ops/告警（做成 golden 式断言测试）。
3. V1–V8 每条有正负测试；R3 歧义文案逐字匹配。
4. 无 default 时三 agent 对默认模型命名空间**零 ops、零告警**（negative test 钉死；D-8 后 CC/Codex 与 Pi 一致，无例外分支）。
5. `version: 1` 输入被拒；仓库内无 v1 形状残留（活文档 grep 干净）。
6. （真机冒烟推迟到真机迁移任务时再做，本轮不作为验收项。）

---

## 附录 R：落地实施复核报告（2026-08-26，独立复核，本轮零代码改动）

> 复核原则：只信源码与实测运行，不采信执行方总结与本档前文描述。工具链独立复测：
> `uv run pytest` = **177 passed**；`ruff check .` = All checks passed；`mypy src` = Success (24 files)。
> 改动全部在工作区未提交（34 文件，+1724/−1600）；golden fixtures 零触碰（git diff tests/fixtures/ 为空）。

### R.1 对七项过程调整的逐一独立裁定

| # | 调整 | 裁定 | 独立证据 |
|---|---|---|---|
| 1 | D-7 嵌套 `models:` 子块 | **正确且必要**。原稿 §2.1 平铺示例与 §2.6 字面 `members` 字段互斥；嵌套方案在 config/resolve/adapters/generators/tests/SPEC 全链路一致，且使 V4 保留键分支自然消解 | `ProfileConfig{models, default}`(config.py)；SPEC §7.3 与实现逐字段吻合 |
| 2 | D-8 CC/Codex 无 default = 零 ops + 一条显式告警 | **正确**。符合“显式暴露”铁律，且诚实承认为 v1 对等而非新功能；golden 测试钉死 `profile.default` 告警（test_adapters_claude.py L142、test_adapters_codex.py L143） | 两 adapter plan() 早退分支；冒烟实测 `use reg` 零 ops、exit 0 |
| 3 | pydantic 拒绝非字符串 key（原文档写反） | **属实**。本复核独立复现：int key 报 `providers.vmr.models.2024.[key] Input should be a valid string` | uv run python 实测 |
| 4 | test_cli_pi.py 原计划遗漏后补上 | **属实**，T8 清单确实漏列该文件 | git diff tests/integration/test_cli_pi.py |
| 5 | init 提案默认激活 `default:` | **正确**。“注册但永不选型”的全新安装使 CC/Codex 完全不可用，违背验收承诺 #1；提案经用户确认后才落盘，激活行不违反 opt-in 原则。已有测试钉死：test_vmr.py L183/L204/L215 + e2e acceptance #1 断言 3×SYNCED | vmr.py generate_vmr_proposal 注释与实现一致 |
| 6 | 删除 resolve.py 的 V5 防御性复核 | **推理成立**。config.py 用同一个 `_resolve_ref()` 在加载时对全体 profile 执行 V3+V5；v2 无隐式成员插入机制，resolve 阶段重推导必得相同结果，二次检查确属死代码。保留的 `_resolve_ref` 重调用仅防手构造 CoreConfig，定位清晰 | config.py validate_cross_references 内 seen_upstream 循环 |
| 7 | 文档 fork 假动作后改亲做 | 过程问题非代码问题；终态文档已抽查（R.3），无法也不必追溯中间过程 |

### R.2 独立验证通过的关键机制（第一性原理逐条过）

1. **§3.5 漂移过滤端到端有效**：临时 HOME 冒烟——`use daily`（有 default）后外部把 Pi `settings.json::defaultModel` 改为 `user-picked`，切到无 default 的 `reg` 再 `acm status`，三 agent 均 SYNCED（陈旧字段被 managed_paths 排除）；`use reg` 对 Pi 不触碰 settings.json（cat 实证）。`detect_agent_drift` 全仓唯一调用点已同步；`managed_paths=None` 回退旧行为且有专测（test_status.py L144）。
2. **空 ops 不会误清 last_write**：compute_agent_status 对空 ops 返回 SYNCED，use_cmd 的 SYNCED 快捷分支先于 write_changeset，空集永远到不了第 6 步整体替换——不存在“切到 registration-only 抹掉漂移基线”的路径。
3. **V1–V8 全数有正负测试**；R3 歧义文案逐字匹配且候选列表排序确定（test_config.py L277–302）；跨 provider 同名 id 不误判歧义（test_config.py L364）。
4. **安全不变区完好**：Safety Engine 六步管线/writers/锁/快照零 diff；e2e 中 Codex 目标 TOML 区域零改动（唯一 hunk 在 L198 config.yaml 区）；init 先 parse 后确认再写入的次序未破坏，0600 权限测试存活。
5. **无 v1 符号残留**（src 仅两处解释性 docstring 提及旧术语）；版本三元组 0.3.0 一致；loader 契约 pin 全保留并新增 provider 作用域重复 key 测试；未列入改动清单的 5 个集成测试经 grep 证实均依赖 conftest fixture，无需改是正确的。
6. **生成器防御到位**：VMR 提案恒用限定引用 `vmr.<id>`（规避下述 R.3-E），label/id 全部 `_q` 引号化，含点/斜杠/冒号 id 有专测（test_vmr.py L218）。
7. **本文档同步度良好**：D-7/D-8 已入 §0，§2.1/§2.3/§2.5-V4/§2.6/§3.2/§3.3/§3.4/§4/§5/T3/T9 均已回改，仅剩一处术语残留（见 R.3-D'）。

### R.3 发现的问题（本轮新发现，按严重度分级，均未处理）

**【中】活文档与实现矛盾三处（建议修完再提交）**

- **R.3-A PRINCIPLE L95 仍是 v1 语义**：“L2 模型规格与行为：模型选择（主模型 + 角色模型 + 可选模型池；池非空时主模型可省略，即 registration-only profile…）”。同文件架构图(L123)已改两层嵌套，但 L2 定义这条漏改——治理文档自相矛盾。
- **R.3-B USER_GUIDE.md/.zh.md 内部矛盾**：L204 与 L348 断言 no-default profile “produces zero warnings / 不产生任何告警”，但同文件 L821 行为矩阵正确写明 CC/Codex 是 “⚠️ one warn, zero ops”（与实现一致）。散文以偏概全（只对 Pi 成立）。
- **R.3-C CLAUDE.md L34 同一 bullet 自相矛盾**：前半句 “No `default` is a normal, non-warning state”，后半句 “…without one, they project nothing and warn explicitly”。两句各自对不同 agent 成立，并置成无限定词的总断言。

**【低】行为边界未记录与打磨项**

- **R.3-D' 本文档微残留**：L253 “比较键仍为 `(provider, upstream_id)`”——`upstream_id` 字段已在 v2 合并入 `model_id`（§2.6 自述），应改为 `model_id`。
- **R.3-E R3 裸引用隐含“不得含点”约束未写入文档**：凡含 `.` 的引用一律按限定形式首个点切分，故含点上游 id 只能以 `<provider>.<id>` 引用；理论上存在“模型 id 字面等于 `<provider名>.<另一key>` 时裸引用被静默按限定解析”的可能。生成器已用恒定限定引用规避，但规则本身应补入 USER_GUIDE 与本文档 §2.4。
- **R.3-F SYNCED 快捷分支吞掉 plan 告警（既有行为被 v2 放大）**：从带 default 切到无 default profile 时，CC/Codex 打印 “already in desired state (no-op)” 而不出示 “nothing to project” 告警（use_cmd 仅在未走 SYNCED 快捷分支时收集 warnings）。“无可做”被表述成“无需做”。status 不受影响（结果携带 warnings）。纯 UX 打磨项。
- **R.3-G Pi 无 default 时非默认成员的 reasoning 告警措辞失准**：文案称 “only the default's defaultThinkingLevel is projected”，该场景下不存在 default、什么都没投影。
- **R.3-H USER_GUIDE 三个 profile-only YAML 片段不能独立解析**（约 L192/L330/L780，中英版同）：省略 providers 段，照抄即报 unknown model id。宜标注片段或补全。
- **R.3-I SPEC A.1 历史裁决表 L954 出现 “pool 子键”**：冻结历史记录可容忍；求洁可加脚注。
- **R.3-J `version` 键缺省时静默取 2**：沿袭 v1 默认值做法可接受；更严可要求显式声明。记录备查。

**【操作提醒，非代码缺陷】R.3-K 真机配置尚未迁移**：真实 `~/.acm/config.yaml` 仍为 `version: 1`，工作区代码一经采用（uv run 即生效）所有命令将按 V6 拒绝之。前次迁移备份仍在（config.toml.migrated-20260826-130652.bak）。建议随合入一并完成真机 v2 改写 + 冒烟。

### R.4 结论

实现质量高：七项调整方向全部正确、论证扎实；三门禁独立复测全绿；条件化投影、漂移过滤、空集保护等核心机制经源码推演与端到端冒烟均成立；D-7/D-8 的文档回改覆盖面完整（仅一词残留）。**无阻断性问题。** 建议合入前处理 R.3-A/B/C 三处文档矛盾与 R.3-K 真机迁移；其余低级别项可择机。
