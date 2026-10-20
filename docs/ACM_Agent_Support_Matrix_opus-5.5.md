<!-- // Ver 2026-10-20 17:25, by Opus 5.5 -->

# ACM Agent 支持矩阵：配置细节、核实结论与三梯队决策

> **意图复述**：盘点"常见 Coding Agent 的模型配置如何调整"，以 Magpie 的实现为线索（逻辑可借鉴、代码不照抄），逐个回到 Agent 官方文档/源码核实；据此把 Agent 分为三个梯队，并回答"第二梯队用插件/Marketplace 加载"这一设想是否把问题复杂化。
>
> **范围**：In —— Magpie 支持的全部 Agent（源码 `builtins()` 中 62 个内建适配器）+ Magpie 未覆盖但重要的 Agent；第一、二梯队的配置规格卡；梯队与扩展机制决策；对 ACM 工程的影响。Out —— 适配器实现代码本身；GUI。
>
> **配套文档**：`docs/ACM_VMR_Manifest_Analysis_and_Design_opus-5.5.md`（下称"Manifest 方案"）；`docs/ACM_Rebuild_Action_Plan_opus-5.5.md`（下称"Action Plan"）；`docs/ACM_Ephemeral_Run_Design_opus-5.5.md`（临时启动的命令与机制设计）。
>
> **rev.3（2026-10-20）**：本文成为**所有 Agent 配置知识的唯一集中处**——除"改配置文件"（`acm use`）外，新增每个 Agent 的"临时启动注入"（`acm run`）规则（各规格卡中的"临时启动"段落与 §7 总表），全部经独立事实核查，核查记录见 §7.4；同时更新了 T1 各 Agent 已核实的非交互调用命令，并修正 Claude Code 的密钥策略（§6.3）。本文的角色槽位映射是 Manifest 方案 §5.5.4 的扩展版。
>
> **rev.2（2026-10-19）梯队重组**：按"代码路径"重新定义梯队——**T1 = 拥有独立代码路径的 Agent（含家族族长），必须真机实测；T2 = 与某个 T1 族长共用同一代码路径、只差参数（目录、文件名、环境变量、二进制名、个别额外槽位）的家族成员，只做金样不做真机实测，按反馈调整；T3 = 不内建**。原 T2 的 9 个独立 Agent（Gemini CLI、Qwen Code 等）因各自需要独立代码路径，移入"T3 候选"（按需求晋升为 T1，晋升即须真机实测）。家族归属以 Magpie 源码中**真实共用的构造函数**为准：`openCodeLike()` 被 OpenCode、MiMo Code、DevEco Code 共用；`piLike()`/`piLikeKeyed()` 被 Pi、OmO、Prime Agent 共用；OpenChamber、MothX、StepCode、Aside、oh-my-pi 虽同源，但在 Magpie 中各有独立实现，属"家族变体"，不进 T2。

---

## 0. 结论摘要

**关于三梯队 + Marketplace 的设想：梯队划分是对的，Marketplace 是把问题复杂化了。** 决断如下：

| 梯队 | 你的设想 | 本文决断（rev.2） | 质量承诺 |
|---|---|---|---|
| **T1 必须支持** | 内建；每个实测；家族族长放这里 | **内建，各有独立代码路径**：Claude Code、Codex、OpenCode（OpenCode 族长）、Pi（Pi 族长）、OpenClaw、Hermes Agent（6 个） | 金样 + 故障注入 + **每次发版真机端到端实测** |
| **T2 可选支持** | 家族成员：借族长能力，配置一下即可扩展；不做真机测试，按反馈调整 | **内建，复用族长代码路径，只声明参数**：MiMo Code、DevEco Code（OpenCode 族）；OmO、Prime Agent（Pi 族）（4 个） | 金样（每个成员一份 fixture）；不做真机实测；`acm status` 标注 `experimental` |
| **T3 不支持** | 交给社区；不做 Marketplace | **不内建**。分两组：**T3 候选**（需独立代码路径、但值得按需求做的 Agent，晋升时直接进 T1）与 **T3 不支持**（无法指向自定义端点、私有存储、长尾） | 无 |

**为什么不做 Marketplace**（详见 §2）：

1. **证据**：Magpie 已经有"Agent 插件"机制（`internal/agentplug`：声明式描述 + JS `connect()`），拥有 16.5k stars 的用户基数，但社区注册表里 `kind: agent` 的插件只有 **3 个**（Aider、Type4Me、Kimi 桌面版）；其余 60+ 个 Agent 全部由维护者在源码内实现。社区供给在比 ACM 大得多的用户规模下都接近零，在 ACM 的规模下是零。
2. **安全**：Agent 适配器的本质是"往哪个文件的哪个键写什么值"——其中必然包含 `base_url`。一份从远端拉取的描述文件只要把 `base_url` 指向别处，就能把用户的 API key 和全部代码上下文导走。ACM 的核心价值（Safety Engine 白名单）恰恰是"写入路径由受审查的源码决定"；远端描述等于把白名单交给未审查的来源。这也直接违反现行铁律"无 DSL、无动态加载"。
3. **成本倒挂**：能被声明式描述覆盖的 Agent 恰好是最简单的那批（一个文件、两三个键），在源码里写一个只要半天；而真正难的 T1（Claude Code 在 Magpie 中 2556 行、Codex 1911 行 + 一个专门的 catalog 生成包）根本无法声明式描述。Marketplace 的注册表、签名、版本兼容、审核流程，比把整个 T2 写进源码还贵。
4. **更便宜的替代**：大量长尾 Agent 是少数几个"格式家族"的分叉（OpenCode 系、Pi 系、Claude Code 系）。在源码里做"家族适配器 + 路径参数"，就能低成本覆盖它们，不需要任何运行时扩展机制。

**最简可行路线**：T1 与 T2 一起交付——T2 只是族长适配器上的参数表，边际成本极低；T3 候选按真实需求逐个晋升为 T1；其余冻结。若未来出现 §2.6 的触发条件，第一步也只是"本地、纯数据、受限键集"的自定义描述文件，而不是远端 Marketplace。

**本次调研中对 ACM 影响最大的 5 个事实**（均已核实）：

1. **Codex 只支持 Responses 协议**：`model_providers.<id>.wire_api` 的唯一合法值是 `responses`（官方 config-reference）。VMR 要服务 Codex，必须提供 `openai-responses` 入口。
2. **Codex 对未知模型名使用写死的兜底元数据**：272K 窗口、无推理档位、无 `apply_patch` 工具类型；且 `model_context_window` 会被**截断**到这个 272K 上限（`codex-rs/models-manager/src/model_info.rs`，HEAD `89461ea6`）。要正确描述 VMR 的 `coding` 这类别名，只能生成 `model_catalog_json` 文件——Magpie 正是这样做的（`internal/codexcat`）。
3. **Claude Code 的 `ANTHROPIC_DEFAULT_HAIKU_MODEL` "也用于后台功能"**（官方 env-vars 文档原文）——基本证实 Manifest 方案中假设 A1：不写这个槽位，后台任务会以官方 haiku id 打到 VMR。
4. **格式写入器才是真正的门槛**：T1 需要 JSON、TOML（已有）、YAML round-trip（依赖已有，写路径未实现）、**JSONC**（OpenCode，保留注释）、**JSON5**（OpenClaw）。ACM 现有的 stdlib JSON 写入器会丢注释。
5. **Magpie 不支持 OpenClaw**（只在导入 CC Switch 数据时识别它），而 OpenClaw 是本次统计中星数最高的 Agent（392k）。这是 ACM 少有的"别人没做、自己正好要用"的空位。

---

## 1. 方法与来源

### 1.1 来源与版本

| 来源 | 版本 / 时间 | 用途 |
|---|---|---|
| Magpie 源码 `yetone/magpie` | commit `33dbdcc`（2026-10-19），`internal/agent`（365 个文件、约 87k 行）、`internal/agentplug`、`internal/codexcat`、`docs/reference.md`、`docs/integrating.md` | 每个 Agent 写哪个文件、哪些键、有哪些坑（Magpie 源码注释里大量引用了上游源文件路径与 issue 编号） |
| Magpie 社区注册表 `magpie-community/plugins/registry.json` | 2026-10-19 | 社区 Agent 插件的实际供给量 |
| Claude Code 官方文档 | code.claude.com：model-config、llm-gateway-protocol、env-vars、settings（2026-10-19 抓取） | 槽位环境变量、未知模型行为 |
| Codex 官方 config-reference + 源码 `openai/codex` | developers.openai.com（2026-10-19）；源码 HEAD `89461ea6` | `wire_api`、槽位键、未知模型兜底 |
| Pi 官方仓库 `earendil-works/pi` | HEAD `e28e7080`，`packages/coding-agent/docs/{models-configuration,settings,extensions}.md` | `models.json` / `settings.json` 字段 |
| OpenCode 官方文档 | opencode.ai/docs：config、providers（2026-10-19） | provider / model / small_model / 变量替换 |
| OpenClaw 官方仓库文档 `openclaw/openclaw` | `docs/gateway/configuration.md`、`config-agents/models.md`、`config-secrets-env.md`、`concepts/model-providers/custom-providers.md` 等（2026-10-19） | JSON5 配置、模型槽位、`${VAR}` |
| Hermes Agent 官方仓库 `NousResearch/hermes-agent` | `website/docs/user-guide/configuring-models.md`、`cli-config.yaml.example`（main，2026-10-19） | `model` / `providers` / `auxiliary` / `delegation` |
| T2 官方文档 | Gemini CLI `docs/reference/configuration.md` + 源码检索；Qwen Code 设置文档；Kimi Code 配置文档；Aider `aider_conf`；Crush README；Goose config-files；Factory BYOK | T2 规格卡 |
| GitHub stars | GitHub API，2026-10-19 | 流行度依据之一 |

### 1.2 核实等级标记（文中统一使用）

- **[官方]**：已对照 Agent 官方文档或官方源码核实。
- **[Magpie 源码]**：来自 Magpie 源码及其注释（注释中通常引用了上游源文件或 issue），未独立核实。
- **[Magpie 表]**：仅来自 Magpie `docs/reference.md` 的 Agents 表，未核实。

T1 全部达到 [官方]；T2 的关键键达到 [官方]，细节标注来源；T3 只到 [Magpie 表]，因为不打算支持，核实没有回报。

---

## 2. 三梯队与扩展机制：分析与决断

### 2.1 你的设想（复述）

- T1：必须支持，ACM 发版时内建，每个都实测有效。
- T2：可选支持，ACM 不内建；用户用到时，ACM 自动去一个类似 Marketplace 的地方查找社区配置并加载使用。
- T3：不预先支持，交给社区开发者自行贡献。
- 并自问：这是否把问题复杂化了？是否应该只做 T1、其他先搁置？

### 2.2 证据一：Magpie 的插件机制与真实社区供给

Magpie 在代码层面已经实现了你设想中的 T2 机制。`internal/agentplug/agentplug.go` 的包文档描述了它：

```js
// 一个 Agent 插件模块导出：
export const agent = {
  id: "aider", name: "Aider",
  config: "~/.aider.conf.yml",   // magpie 编辑的那个文件
  model: "model",                // 模型在文件中的键路径
  prefix: "openai/",
}
export function connect({ gateway, model, models }) {
  return { "openai-api-base": gateway.v1, "openai-api-key": gateway.key }
}
```

设计要点：插件只声明"一个文件 + 模型键 + 一组要写的键值"，**所有写入由 Magpie 自己完成**，且只写插件声明的那一个文件（json / yaml / env 三种格式）；JS 在进程内的 moejs 沙箱里运行，加载限时 1 秒。

然而社区实际产出（`registry.json`，2026-10-19）：32 个插件中，`kind: agent` 的只有 **3 个**——Aider、Type4Me（macOS 语音输入）、Kimi 桌面版。其余是 provider 插件（订阅登录）和网关中间件。更值得注意的是，Magpie 自己的 `docs/integrating.md` 仍写着"There is no runtime registration: a row is added by a pull request to this repository"——**主路径始终是源码 PR**，插件机制是边缘补充。

解读：一个 16.5k stars、发版极快、社区活跃的项目，把"社区贡献 Agent 适配"的门槛降到了"写一个对象 + 一个函数"，换来的是 3 个插件。供给瓶颈不在机制，而在于**愿意持续维护某个 Agent 适配的人本来就少**——Agent 配置格式每几周就变一次，一次性贡献很快过期。

### 2.3 证据二：难的部分无法被声明式描述

对比 Magpie 中各适配器的规模：`claude.go` 2556 行、`codex.go` 1911 行（另有 `internal/codexcat` 专门生成 Codex 模型目录）、`dsh.go` 2205 行；而 `fx`、`empryo` 这类简单 Agent 只有几十到一两百行。复杂度来自：

- **Claude Code**：Opus 5.5 之后的模型只读 `modelSettings.<model>.effortLevel`，更早的读顶层 `effortLevel`（Magpie 源码注释，官方 settings 文档确认 `modelSettings` 按模型解析）；未知模型的窗口、自动压缩窗口、最大输出各有独立环境变量与默认值；`/model` 切换后各槽位需要跟随。
- **Codex**：第三方模型必须自带 catalog 条目（含系统提示词）才能获得正确窗口、推理档位与工具类型。
- **OpenClaw**：JSON5、`$include` 分文件、运行时自己会原子重写配置文件、启动迁移。

这些都是"条件逻辑"，不是"键值对"。所以声明式插件**只能覆盖本来就简单的 Agent**——而简单 Agent 在源码里实现的成本本来就低。机制的收益区间和需求区间不重叠。

### 2.4 证据三：安全模型冲突

ACM 的 Safety Engine 第一步是"白名单路径/命名空间校验"，白名单由**源码中的适配器**声明，经过金样测试审查。远端描述文件意味着：

- 白名单本身来自远端——校验形同虚设；
- 即使把写入限制在"Agent 自己的配置文件"，描述文件只要写 `base_url = https://attacker.example`，用户的 key（无论是明文写入还是 `${VAR}` 在运行时展开）和全部对话上下文都会流向攻击者。这不是理论风险：它与 npm 生态里反复发生的供应链攻击同构；
- "自动查找并加载"让用户在不知情时执行了第三方决定的写入，与 ACM"显式暴露、绝不静默"的原则相反。

Magpie 能接受这个风险，是因为它的请求本来就经过它自己的网关（攻击面不同）；ACM 让 Agent 直连目标端点，`base_url` 的正确性就是安全边界本身。

### 2.5 证据四：长尾的真实形态是"家族"

从 Magpie 的 Agents 表与源码注释可以看出，相当多的长尾 Agent 是少数几个上游的分叉或换皮：

| 家族 | 母体 | 成员（Magpie 中的写法相同或高度相似） |
|---|---|---|
| OpenCode 系 | OpenCode（`opencode.json(c)`） | OpenChamber、MiMo Code、DevEco Code、JetBrains Air（通过 `opencode acp`）；Kilo Code 的 CLI 亦基于 OpenCode（未核实） |
| Pi 系 | Pi（`settings.json` + `models.json`） | OmO、Prime Agent、MothX、StepCode（`+models.json`）、Aside、oh-my-pi（同源但改用 YAML） |
| Gemini CLI 系 | Gemini CLI | Qwen Code（Gemini CLI 分叉）、Antigravity CLI（同在 `~/.gemini` 下） |
| Claude Code 系 | Claude Code 的 env 槽位 | T3 Code（以 Claude Code 为 provider 实例）、Claude Desktop 的 Code 标签页（读同一 settings.json） |

**家族适配器 = 一份写法 + 多组路径参数**，在源码里实现，金样按家族共享。这把"支持一个长尾 Agent"的边际成本降到"加一组路径 + 一份 fixture"，比任何运行时插件都便宜，且完全在白名单审查之内。

### 2.6 决断

1. **T1 内建，真机实测**（§3、§4）。
2. **T2 = 家族成员，内建于源码**：在族长模块的成员参数表中声明（目录、配置文件名、环境变量覆盖、二进制名、成员特有槽位）；每个成员一份金样 fixture；不做真机实测；`acm status` 标注 `experimental`；按用户反馈修正参数。**判定规则**：只要实现某成员需要改动族长的映射逻辑（而不只是加参数），它就不是 T2，而是 T3 候选。
3. **T3 候选 → T1**：独立代码路径的 Agent 一旦因真实需求被实现，就按 T1 标准（含真机实测）交付——理由是 T2 免除真机实测的前提是"代码路径已被族长的真机实测覆盖"，独立代码路径不具备这个前提。
4. **T3 不支持**：在支持矩阵中写明原因；欢迎源码 PR（需带金样与真机实测记录）。
5. **不做 Marketplace / 远端描述加载**。保留一个触发项写入 PRINCIPLE §7 触发表：
   - **触发条件**：90 天内出现 ≥ 3 个独立用户请求同一类我们明确不打算内建的 Agent，且无人愿意提交源码 PR。
   - **触发后的第一步（也是唯一允许的形态）**：本地、纯数据的自定义描述文件（如 `~/.acm/agents/<id>.yaml`），只能声明：一个位于该 Agent 自身目录下的配置文件、格式（json / toml / yaml）、模型键、base_url 键、key 引用键；首次使用时完整展示其将写入的路径与键并要求确认；不执行任何代码；不联网获取。
   - 远端分发只有在本地机制被真实使用后才重新评估。

### 2.7 对"是否复杂化"的直接回答

是的，Marketplace 部分复杂化了，原因是它解决的是一个不存在的供给问题，同时引入了一个真实存在的安全问题。梯队划分本身是正确且必要的——它决定了**测试投入**怎么分配，这才是有限精力下最需要做的取舍。最简单的版本就是：**T1 做完并实测，T2 作为族长的参数表随 T1 一起交付；T3 候选按需晋升；其余冻结。**

---

## 3. 支持矩阵总表

### 3.1 梯队判定标准

**梯队由代码路径决定，流行度与场景相关性决定"是否值得有一条代码路径"**：

1. **可投影（前提）**：有公开、稳定、可安全编辑的配置文件，且能指向**任意** OpenAI / Anthropic 兼容端点。不满足 → T3 不支持（范围测试不过：换不了 provider，ACM 无事可做）。
2. **值得拥有独立代码路径**（进入 T1 的条件，满足其一）：流行度处于头部（参考：CC Switch 这一 146k stars 的切换器支持的 8 个应用——Claude Code、Claude Desktop、Codex、Gemini CLI、OpenCode、OpenClaw、Pi、Hermes，据 Magpie `internal/provider/importapps.go` 的 `ccSwitchApps`）；或本人日常使用；或是家族族长（一条代码路径能覆盖多个成员）。
3. **共用代码路径**：与某个 T1 族长只差参数 → T2。
4. 满足 1 但不满足 2、3 → T3 候选（有需求时晋升 T1）。

### 3.2 总表

流行度为 2026-10-19 的 GitHub stars（"—"表示闭源或未统计）。"端点"列指能否指向任意兼容端点及其协议。

**第一梯队（T1，内建 + 真机实测）**

| Agent | Stars | 配置文件 | 端点 / 协议 | 核实 | 入选理由 |
|---|---|---|---|---|---|
| Claude Code | 152k | `~/.claude/settings.json` | 任意 Anthropic Messages 端点（`ANTHROPIC_BASE_URL`） | [官方] | 头部；角色槽位最丰富。读取同一 settings.json 的 Claude Desktop Code 标签页等会**自动跟随**，无需单独适配 |
| Codex CLI | 130k | `~/.codex/config.toml`（+ 可选 `model_catalog_json` 文件） | 任意端点，**仅 Responses** | [官方] | 头部 |
| OpenCode（**族长**） | 217k | `~/.config/opencode/opencode.json(c)` | 任意（AI SDK 包：openai-compatible / anthropic / openai） | [官方] | 头部；OpenCode 族长（覆盖 MiMo Code、DevEco Code）；字段与 models.dev 同构 |
| Pi（**族长**） | 116k | `~/.pi/agent/models.json` + `settings.json` | 任意（`api`: openai-completions / openai-responses / anthropic-messages 等） | [官方] | 头部；Pi 族长（覆盖 OmO、Prime Agent）；可加扩展做动态路由 |
| OpenClaw | 392k | `~/.openclaw/openclaw.json`（JSON5） | 任意（`api`: openai-completions / anthropic-messages 等） | [官方] | 星数第一；本人在用；**Magpie 不支持**（差异化空位） |
| Hermes Agent | 255k | `~/.hermes/config.yaml`（`$HERMES_HOME`） | 任意（`api_mode`: chat_completions / codex_responses / anthropic_messages） | [官方] | 头部；本人在用；辅助任务槽位丰富 |

**第二梯队（T2，家族成员：复用族长代码路径，只声明参数；仅金样）**

| 成员 | 家族 | 配置位置 | 与族长的差异（全部是参数） | 核实 |
|---|---|---|---|---|
| MiMo Code（小米） | OpenCode | `~/.config/mimocode/mimocode.json(c)`；认证文件 `~/.local/share/mimocode/auth.json`（不碰） | 目录名、文件名、二进制 `mimo` | [Magpie 源码]：`mimocode()` 直接调用 `openCodeLike(...)` |
| DevEco Code（华为） | OpenCode | `~/.config/deveco/deveco.json(c)`（`$DEVECO_CONFIG_DIR`） | 目录名、环境变量、二进制 `deveco` | [Magpie 源码]：`deveco()` 直接调用 `openCodeLike(...)` |
| OmO（omo-ai） | Pi | `~/.omo/agent/settings.json` + `models.json`（`$OMO_CODING_AGENT_DIR`、`$SENPI_CODING_AGENT_DIR`） | 目录、环境变量 | [Magpie 源码]：`omoIn()` 调用 `piLike(...)` |
| Prime Agent | Pi | `~/.prime/agent/settings.json` + `models.json`（`$PRIME_AGENT_CODING_AGENT_DIR`） | 目录、环境变量；成员特有键 `subagentDefaultModel`（可映射 subagent 角色，作为成员槽位参数声明；Magpie 对它与 `allowedModels` 保持不动） | [Magpie 源码]：`primeAgentIn()` 调用 `piLikeKeyed(...)` |

T2 成员的官方文档核实放在其实现任务中（Action Plan P6），以"族长写法在该成员上是否成立"为核对目标；任何一处需要改族长映射逻辑，即按规则降为 T3 候选。

**第三梯队候选（T3 候选：需独立代码路径；有真实需求时晋升 T1）**

| Agent | Stars | 配置文件 | 端点 / 协议 | 核实 | 价值 / 限制 |
|---|---|---|---|---|---|
| Gemini CLI | 107k | `~/.gemini/settings.json` + `~/.gemini/.env` | **只说 Gemini API**；`GOOGLE_GEMINI_BASE_URL` 可改端点 | [官方] | 流行，但协议门槛：VMR 无 Gemini 入口，仅对直连 Google 或 Gemini 格式中转有意义 |
| Qwen Code | 28.6k | `~/.qwen/settings.json`（`$QWEN_HOME`） | 任意 OpenAI 兼容（`modelProviders.openai[]`） | [官方] + [Magpie 源码] | 中国大陆重要；Gemini CLI 分叉 |
| Kimi Code | 11.4k | `~/.kimi-code/config.toml`（新）/ `~/.kimi/config.toml`（旧 kimi-cli） | 任意（`[providers.*]` + `[models.*]`） | [官方]（旧路径）+ [Magpie 源码]（新路径） | 中国大陆重要；官方文档与 Magpie 对路径的描述不一致，见 §5 |
| Aider | 49.6k | `~/.aider.conf.yml` + `.aider.model.metadata.json` | 任意 OpenAI 兼容（`openai-api-base`） | [官方] | 老牌高质量；`model / weak-model / editor-model` 三角色；最近一次推送 2026-05-22，活跃度下降 |
| Crush | 28.7k | `~/.config/crush/crush.json` + 数据文件 `~/.local/share/crush/crush.json` | 任意（provider `type`: openai / openai-compat / anthropic） | [官方] + [Magpie 源码] | Charm 出品，质量高；`large / small` 两角色 |
| Goose | 55k | `~/.config/goose/config.yaml` + `custom_providers/<id>.json` | 任意（声明式 custom provider） | [官方] + [Magpie 源码] | Block 出品（现属 aaif-goose）；**API key 不进 config.yaml**（官方文档原文） |
| oh-my-pi（omp） | 35.9k | `~/.omp/agent/config.yml` + `models.yml` | 同 Pi | [Magpie 源码] | Pi 系，星数高；YAML 形态 |
| Droid（Factory） | — | `~/.factory/settings.json`（`customModels[]`） | 任意（provider: anthropic / openai[Responses] / generic-chat-completion-api） | [官方] + [Magpie 源码] | 商业产品，BYOK 文档完整 |
| Cline CLI | 70.5k（含 VS Code 扩展） | `~/.cline/data/settings/providers.json` + `models.json` | OpenAI 兼容（内建 openai-compatible provider） | [Magpie 源码] | 用户面广；**只支持 CLI**，VS Code 扩展的状态在 `globalState.json`，属私有状态（铁律排除） |
| OpenChamber | — | `~/.config/openchamber/preferences.json` + OpenCode 的配置 | 同 OpenCode | [Magpie 表] | OpenCode 族**变体**：模型默认值写在自己的 preferences 文件，provider 写在 OpenCode 配置——需要改族长映射，非纯参数 |
| MothX | — | `~/.mothx/settings.json`（`$MOTHX_DIR`） | Pi 风格（`defaultProvider/defaultModel/defaultThinkingLevel`） | [Magpie 表] | Pi 族**变体**：Magpie 中独立实现 |
| StepCode | — | `~/.stepcode/config.toml` + `models.json` | Pi 风格 | [Magpie 表] | Pi 族**变体**：设置改为 TOML |
| Kilo Code CLI | 27.7k（含扩展） | 待核 | 待核 | 未核 | 据称基于 OpenCode；若核实为纯参数差异可直接进 T2 |

**第三梯队（T3 不支持）——按原因分组**

| 原因 | Agent（配置位置据 [Magpie 表]） |
|---|---|
| **A. 不能指向自定义端点**（只能在厂商自有模型间切换，范围测试不过） | Cursor CLI（`~/.cursor/cli-config.json` 的 `model.modelId`）、Copilot CLI（`~/.copilot/settings.json` 的 `model`）——Magpie 对二者也只做"在厂商模型间切换"，见其 `agents.go` |
| **B. IDE / 桌面 App 内部配置、私有数据库或导入链接** | Claude Desktop、Claude Science、Cursor Private Inference、Zed、VS Code Chat / Insiders / VSCodium、Copilot（JetBrains，`byok.json`，且需 Copilot 付费计划）、JetBrains Air、Raycast、OpenPencil、Pencil、T3 Code、Grok App、Aside、Alma（本地 API）、Lody（导入链接）、Cindy（SQLite 数据库）、Kilo Code / Roo Code 的 VS Code 扩展（扩展存储） |
| **D. 长尾 / 区域性 / 小众** | Qoder、Qoder CN、CodeBuddy Code、WorkBuddy、WorkBuddy AI、ZCode、MiniMax Code、AtomCode、Snow CLI、jcode、fx、Command Code、Mister Morph、Muse Code、Empryo、Ante、AstrBot、OpenHanako、DeepSeek Harness（dsh）、Reasonix Studio、Antigravity CLI（Gemini 协议）、Grok Build、Devin |

（原 C 组"家族衍生"已拆分：纯参数成员进入 T2，变体进入 T3 候选。）

---

## 4. 第一梯队规格卡

每张卡的结构：文件与格式 → 连接字段（端点、key、协议）→ 角色槽位映射（对应 Manifest 方案的 `default / reasoning / fast / subagent / review` 与窗口）→ 密钥引用能力 → 生效方式 → 坑 → ACM 现状与差距 → 端到端实测方式。

### 4.1 Claude Code [官方]

**文件与格式**：`~/.claude/settings.json`（JSON；`CLAUDE_CONFIG_DIR` 可改目录）。项目级 `.claude/settings.json`、managed settings 优先级更高——ACM 只写用户级，且应在 `status` 中提示"存在更高优先级来源设置了同一键"（官方 settings 文档专门列了"某个键为什么不生效"的几种原因）。

**连接字段**（均在 `env` 对象下）：

| 用途 | 键 | 备注 |
|---|---|---|
| 端点 | `env.ANTHROPIC_BASE_URL` | 只支持 Anthropic Messages 格式 |
| 凭据 | `env.ANTHROPIC_AUTH_TOKEN`（作为 `Authorization: Bearer`）或 `env.ANTHROPIC_API_KEY`（`x-api-key`） | 也可用 `apiKeyHelper`（一条命令，输出作为 bearer）——可避免明文落盘，见"密钥引用" |

**角色槽位映射**：

| 角色 | 键 | 官方依据 |
|---|---|---|
| default | `model`；同时写 `env.ANTHROPIC_DEFAULT_SONNET_MODEL` | `/model sonnet` 别名解析 |
| reasoning | `env.ANTHROPIC_DEFAULT_OPUS_MODEL`、`env.ANTHROPIC_DEFAULT_FABLE_MODEL` | `opusplan` 在 plan 模式用 opus 槽 |
| fast | `env.ANTHROPIC_DEFAULT_HAIKU_MODEL` | "Model ID that the `haiku` alias resolves to, **also used for background functionality**" |
| subagent | `env.CLAUDE_CODE_SUBAGENT_MODEL` | 子代理、agent team、workflow 的默认模型 |
| review | 无 | — |
| 窗口 | `env.CLAUDE_CODE_MAX_CONTEXT_TOKENS` | 网关别名默认按 200K 处理 |
| 自动压缩 | `env.CLAUDE_CODE_AUTO_COMPACT_WINDOW`（100000–1000000，只接受纯整数） | 可选；Magpie 用它把 1M 模型的工作窗口压到更小以控制延迟 |
| 最大输出 | `env.CLAUDE_CODE_MAX_OUTPUT_TOKENS` | 未识别 id 的默认 32000、上限 128000 |
| effort | 顶层 `effortLevel`；**Opus 5.5 及之后的模型读 `modelSettings.<model>.effortLevel`** | 后半句来自 Magpie 源码注释（Claude Code 2.1.251 起），官方 settings 文档确认 `modelSettings` 按模型解析 |

不写：`ANTHROPIC_SMALL_FAST_MODEL`（官方标记 DEPRECATED）；`modelOverrides`（理由见 Manifest 方案 §8.2 风险 4）。

**密钥引用能力**：settings.json 的 `env` 值是字面量（官方原文 "Values here are plain text in the settings file"），官方建议 API 凭据改用 `apiKeyHelper`。ACM 采用 `apiKeyHelper` 写入固定模板 `printenv <VAR>`，文件中不出现 key（见 §6.3、§7.4 #3）。

**生效方式**：新会话读取；已开会话不受影响。

**坑**：
- 官方 gateway 文档：未识别的 model id 只发送保守的请求字段（固定 budget thinking，无 effort / context management）——VMR 别名天然如此，ACM 写 `effortLevel` 对它可能无效。
- 原生网关发现只保留 id 含 `claude`/`anthropic` 的条目，VMR 别名不会出现在 `/model` 选择器中（槽位写入不受影响）。
- 更高优先级的 settings 来源（项目级 / managed）会静默覆盖用户级。

**ACM 现状与差距**：现受管命名空间为 `model`、`env.ANTHROPIC_BASE_URL`、`env.ANTHROPIC_AUTH_TOKEN`、`env.ANTHROPIC_API_KEY`、`effortLevel`。需新增：四个别名槽位、`CLAUDE_CODE_SUBAGENT_MODEL`、`CLAUDE_CODE_MAX_CONTEXT_TOKENS`；可选 `CLAUDE_CODE_MAX_OUTPUT_TOKENS`、`CLAUDE_CODE_AUTO_COMPACT_WINDOW`、`modelSettings.<model>.effortLevel`。

**临时启动（`acm run`）** [官方]：`claude --settings '<内联 JSON>' [透传参数]`，以 `exec` 方式替换进程，**不产生任何临时文件**。内联 JSON 内容：`env` 块写 `ANTHROPIC_BASE_URL`、四个别名槽位、`CLAUDE_CODE_SUBAGENT_MODEL`、`CLAUDE_CODE_MAX_CONTEXT_TOKENS`，并把 `ANTHROPIC_AUTH_TOKEN`、`ANTHROPIC_API_KEY` 置为 `""` 以屏蔽用户 settings.json 中的同名值；凭据用 `"apiKeyHelper": "printenv VMR_KEY"`（变量名取自引用），因此 JSON 中不含任何密钥。
- 依据 1：`--settings` "Path to a settings JSON file or an inline JSON string. Values you set here override the same keys in your settings.json files for this session"（CLI reference）。
- 依据 2：settings 中的 `env` 值 "overwrites the same variable exported in your shell"（settings-reference "How env values interact with your shell"）——**所以不能只给子进程设环境变量**，用户 settings.json 里的同名值会把它盖掉；必须经 `--settings` 注入。
- 依据 3：`apiKeyHelper` 经 `/bin/sh` 执行，输出同时作为 `X-Api-Key` 与 `Authorization: Bearer` 发送；官方明确建议 "for API credentials, use apiKeyHelper"（settings-reference）。`ANTHROPIC_AUTH_TOKEN` 存在时 Authorization 头优先用它（llm-gateway-protocol），故需置空。
- 待真机确认：`env` 中置 `""` 的 `ANTHROPIC_AUTH_TOKEN` 是否被视为未设置从而回落到 `apiKeyHelper`（官方只写明空值对 "provider selection" 视为未设置）。

**真机实测**：`acm use team` → `claude -p "reply with OK"` → VMR audit 中出现该请求且 model 字段为 default 角色解析出的名字；再触发一次会产生后台调用的操作（如新会话标题生成），确认 audit 中出现 fast 角色模型名而非官方 haiku id → `acm rollback claude_code` 后 settings.json 中其他键（hooks、permissions、enabledPlugins）完全不变。

### 4.2 Codex CLI [官方]

**文件与格式**：`~/.codex/config.toml`（TOML；`CODEX_HOME` 可改）。`profile` / profile 文件可覆盖顶层值（Magpie 源码处理了 `profile` 键）。

**连接字段**：

| 用途 | 键 | 备注 |
|---|---|---|
| 选择 provider | `model_provider` | 内建 id `openai`、`ollama`、`lmstudio` 保留不可覆盖 |
| provider 定义 | `model_providers.<id>.{name, base_url, env_key, wire_api, http_headers, ...}` | |
| 协议 | `model_providers.<id>.wire_api` | **`responses` 是唯一支持的值**（官方原文） |
| 凭据 | `model_providers.<id>.env_key`（推荐）；`experimental_bearer_token`（不推荐）；`auth` 命令 | `env_key` 是原生的变量引用 |

**角色槽位映射**：

| 角色 | 键 |
|---|---|
| default | `model`（+ `model_provider`） |
| reasoning | 无模型槽位（`plan_mode_reasoning_effort` 只管 effort）→ 投影损失告警 |
| fast | 无 → 告警 |
| subagent | `agents.default_subagent_model`（+ `agents.default_subagent_reasoning_effort`） |
| review | `review_model` |
| 窗口 | `model_context_window`（**被模型元数据的 `max_context_window` 截断**）、`model_auto_compact_token_limit` |
| 模型目录 | `model_catalog_json`（文件路径，启动时加载）或 `model_providers.<id>.model_catalog_url`（Codex 原生 catalog 格式的 URL） |
| effort | `model_reasoning_effort` |

**关键发现：未知模型的兜底元数据**（`codex-rs/models-manager/src/model_info.rs::model_info_from_slug`）：遇到不认识的模型名时打印 "Unknown model … will use fallback model metadata"，并使用：`context_window = max_context_window = 272_000`、`supported_reasoning_levels = []`、`apply_patch_tool_type = None`、`supports_reasoning_effort_updates = false` 等。而 `with_config_overrides` 中 `model_context_window` 取 `min(配置值, max_context_window)`——**配置更大的窗口会被静默截到 272K**。Magpie 的对策是为每个第三方模型生成 catalog 条目（`internal/codexcat`，并内嵌 Codex 的通用系统提示词，注释原文："Third-party models need one because the bundled catalog only carries prompts for OpenAI models"）。

**对 ACM 的含义**：要让 Codex 正确使用 VMR 别名，ACM 需要生成并拥有一个 catalog 文件（例如 `~/.acm/state/codex/catalog.json`，或 Codex 目录下 ACM 创建的独立文件），并写 `model_catalog_json` 指向它。catalog 条目内容来自 Manifest（窗口、推理能力）。这是 ACM 第一次需要"生成一个完整文件"——它是 ACM 新建、ACM 独占的文件，不违反"只管字段"原则（原则针对的是与 Agent 共享的文件），但需要在 PRINCIPLE 中明确写出。catalog 的精确 JSON 结构需以 Codex 源码 `protocol/src/openai_models.rs` 为准，实现前单独核对。

**生效方式**：新会话；`model_catalog_json` 仅启动时加载。

**ACM 现状与差距**：现受管 `model`、`model_provider`、`model_reasoning_effort`、`model_providers`。需新增 `review_model`、`agents.default_subagent_model`、`model_context_window`、`model_catalog_json`（+ catalog 文件生成）；确认现有实现写的是 `env_key` 而非明文 token。

**临时启动（`acm run`）** [官方 + 源码]：`codex -c 'model_provider="vmr"' -c 'model_providers.vmr={name="vmr", base_url="<VMR>/v1", env_key="VMR_KEY", wire_api="responses"}' -c 'model="<default>"' [-c 'review_model=...'] [-c 'agents.default_subagent_model=...'] [-c 'model_catalog_json="<临时 catalog>"']`。key 经 `env_key` 留在环境变量中。需要 catalog 时（VMR 别名），catalog 写入 ACM 私有目录的临时文件，ACM 作为父进程运行并在退出后删除；否则 `exec`。
- 依据：`-c, --config key=value` "Override configuration values. Values parse as TOML if possible"（CLI reference）；点分路径覆盖嵌套值见源码 `codex-rs/utils/cli/src/config_override.rs` 文档注释（"Use a dotted path (`foo.bar.baz`) to override nested values"）；`model_catalog_json` "applied on startup only"（`codex-rs/config/src/config_toml.rs`）。

**真机实测**：`codex exec "reply with OK"` → audit 命中 Responses 入口与 default 模型名；`codex` 启动日志中**不应**出现 "Unknown model … fallback model metadata" 警告（验证 catalog 生效）。

### 4.3 OpenCode [官方]

**文件与格式**：`~/.config/opencode/opencode.json` 或 `opencode.jsonc`（**支持注释**；`OPENCODE_CONFIG` 指定文件、`OPENCODE_CONFIG_DIR` 指定目录；项目级 `opencode.json` 优先级更高）。

**连接字段**：

```jsonc
{
  "provider": {
    "team": {
      "npm": "@ai-sdk/openai-compatible",     // Anthropic 协议用 @ai-sdk/anthropic
      "name": "Team VMR",
      "options": { "baseURL": "https://vmr.team.lan/v1", "apiKey": "{env:VMR_KEY}" },
      "models": {
        "coding": { "name": "Coding", "limit": { "context": 200000, "output": 32000 } }
      }
    }
  },
  "model": "team/coding",
  "small_model": "team/cheap"
}
```

**角色槽位映射**：default → `model`（`provider/model` 形式）；fast → `small_model`（官方："lightweight tasks like title generation"）；subagent / review → 无全局槽位（`agent.<name>.model` 属于用户定义的 agent，ACM 不碰）；窗口 → `provider.<id>.models.<id>.limit.context/output`（与 models.dev 字段同构，可直接由 Manifest 卡片生成）。

**密钥引用能力**：原生支持 `{env:VAR}` 与 `{file:path}`——ACM 可完全不落明文。

**坑**：
- JSONC：用户文件可能有注释，ACM 需要保留注释的写入器（Magpie 用 `tidwall/jsonc` 读、AST 级文本替换写）。
- `auth.json`（`~/.local/share/opencode/auth.json`）存放 OpenCode 自己的登录凭据，属运行时状态，ACM 不碰（Magpie 读取它但这是 Magpie 的订阅共享需求）。
- 项目级 `opencode.json` 会覆盖用户级。

**ACM 现状与差距**：无适配器，需新建；同时是 OpenCode 家族适配器的母体。

**临时启动（`acm run`）** [官方 + 源码]：环境变量 `OPENCODE_CONFIG_CONTENT='{"provider":{"vmr":{"npm":"@ai-sdk/openai-compatible","options":{"baseURL":"<VMR>/v1","apiKey":"{env:VMR_KEY}"},"models":{...}}},"model":"vmr/<default>","small_model":"vmr/<fast>"}'`，可加 `-m vmr/<model>`；`exec`，零临时文件，key 只在环境变量中。
- 依据 1：配置优先级中 "Inline config (`OPENCODE_CONFIG_CONTENT` env var) - runtime overrides" 位于全局、自定义、项目配置之后，只低于管理员托管配置（config 文档 "Precedence order"）。
- 依据 2：内联内容与配置文件经过同一变量替换（`packages/core/src/config.ts` 中以 `source: "OPENCODE_CONFIG_CONTENT"` 调用 `ConfigVariable.substitute`），所以 `{env:VMR_KEY}` 有效。
- 依据 3：`--model / -m` "Model to use in the form of provider/model"（CLI 文档）。

**真机实测**：`opencode run "reply with OK"` → audit 命中；`small_model` 的使用通过一次会触发标题生成的会话验证。

### 4.4 Pi [官方]

**文件与格式**：`~/.pi/agent/models.json` + `~/.pi/agent/settings.json`（JSON；`PI_CODING_AGENT_DIR` 可改目录）。

**连接字段**（`models.json` → `providers.<id>`）：`baseUrl`、`api`（`openai-completions` / `openai-responses` / `anthropic-messages` / `google-generative-ai` 等）、`apiKey`、`headers`、`compat`、`authHeader`、`models[]`。

**模型条目**：`id`（必填）、`name`、`api`、`baseUrl`、`reasoning`（默认 false）、`input`（默认 `["text"]`）、`contextWindow`（默认 **128000**）、`maxTokens`（默认 **16384**）、`cost.*`。

**角色槽位映射**：default → `settings.json` 的 `defaultProvider` / `defaultModel`（+ `defaultThinkingLevel`）；其他角色 → 注册进 `models.json`（可被 `/model`、`enabledModels` 循环与扩展使用）；运行期动态路由由 `pi.registerVirtualModel()` 扩展承担（官方 extensions 文档已列出该 API——Manifest 方案的待核项 A4 已解决）。

**密钥引用能力**：`apiKey` 支持字面量、`"$NAME"` 环境变量插值、`"!command"` 命令输出——原生支持引用。

**坑**：
- **`compat` 的若干字段（`thinkingFormat`、`maxTokensField`、`supportsReasoningEffort` 等）默认"按 provider URL 自动探测"**。指向 VMR 时 URL 不是任何已知厂商，自动探测失效；而 VMR 一个别名背后可能是 DeepSeek（`reasoning_content`）、GLM、Gemini 等异构上游，没有单一正确的 `thinkingFormat`。这是"网关后异构候选"在客户端的真实代价，需要在 Manifest 中由运维为别名声明期望的思考格式，或接受默认 `openai`。
- `contextWindow` 默认 128000 偏小：不写窗口会让 Pi 过早压缩。

**ACM 现状与差距**：已支持（providers / defaultProvider / defaultModel / defaultThinkingLevel）。需补：从 Manifest 生成 `contextWindow`、`maxTokens`、`reasoning`、`input`；评估是否写 `compat.thinkingFormat`。

**临时启动（`acm run`）** [官方]：`pi -e <ACM 随包附带的固定扩展> --model vmr/<default>`；扩展从环境变量读取本次的目标描述（端点、模型卡片、key 的变量名），在加载时 `registerProvider("vmr", { apiKey: "$VMR_KEY", ... })`；`exec`，零临时文件。不使用 `--api-key`（会出现在命令行参数中）。
- 依据 1：`-e, --extension <path>`（`docs/cli.md`）。
- 依据 2："Call `pi.registerProvider()` from the extension factory. Pi waits for asynchronous factories before startup continues, so providers registered there are available to startup model selection"（`docs/custom-provider.md`）——因此同一条命令里的 `--model` 能选中扩展注册的 provider。
- 依据 3：provider 的 key 支持 `$NAME` / `${NAME}` 环境变量插值（同上）。
- **档位路由（2026-10-20，Pi 1.2.0 真机确认）**：profile 有与 default 不同的 `fast` / `reasoning` 模型且未用 `-m` 时，同一个扩展再调用 `pi.registerVirtualModel({provider: "acm", id: "auto", thinkingLevels: ["low","medium","high"], route})`，启动参数改为 `--model acm/auto --thinking medium`。档位对应角色：`low` 对应 fast，`medium` 对应 default，`high` 对应 reasoning。`continuation` / `retry` 沿用 `request.previous` / `request.failed`；`direct` 只在 fast 窗口足够时走 fast。
  - 依据：Pi 包内 `docs/virtual-models.md`：虚拟模型可被 `--model` 选中；`route()` 在每次请求前调用；`reason` 取 `user` / `continuation` / `retry` / `direct` 之一；沿用 `previous` / `failed` 可保住 prompt cache。
  - 实测：`acm run pi --profile daily -- -p … --thinking low|high` 分别打到 fast / reasoning 模型；Agent 参数里后出现的 `--thinking` 覆盖 ACM 给的 `medium`。
  - 持久写入（`acm use`）不做：虚拟模型只能由扩展代码注册，持久化即安装插件，越过 PRINCIPLE §2.3。

**真机实测**：`pi -p "reply with OK"`（`-p, --print`：运行提示后输出结果并退出，已核实 `docs/cli.md`）→ audit 命中。

### 4.5 OpenClaw [官方]

**文件与格式**：`~/.openclaw/openclaw.json`，**JSON5**（允许注释与尾逗号）。官方说明：Gateway 监听该文件并**热加载**；OpenClaw 自己的写入以原子 rename 替换该文件；支持 `$include` 拆分多文件；启动时可能执行自动迁移并留 `.bak` 轮转备份；配置无效时热加载被跳过、启动失败。

**连接字段**（`models.providers.<id>`）：`baseUrl`、`apiKey`、`api`（如 `openai-completions`、`anthropic-messages`）、`models[]`（`id`、`name`、`contextWindow`、`maxTokens`、`reasoning`、`input`、`compat`）；`models.mode: "merge"` 表示与内建 catalog 合并。

**角色槽位映射**（`agents.defaults.*`，官方 `config-agents/models.md`）：

| 角色 | 键 |
|---|---|
| default | `agents.defaults.model.primary`（`provider/model`） |
| fast | `agents.defaults.utilityModel`（"short internal tasks"：会话标题等） |
| （视觉） | `agents.defaults.imageModel`——Manifest 无对应角色，不写 |
| （压缩） | `agents.defaults.compaction.model`——可选映射到 fast，默认不写 |
| fallbacks | `agents.defaults.model.fallbacks`——**不写**：failover 是 VMR 的职责，客户端再叠一层会让故障路径不可推理 |
| subagent / review / reasoning | 无全局槽位 → 告警 |

`agents.list[].model`（单个 agent 的覆盖）属于用户意图，ACM 不碰。

**密钥引用能力**：任意配置字符串支持 `${VAR}` 与 `${VAR:-default}`，`$${VAR}` 转义（官方 `config-secrets-env.md`）——**与 ACM 的引用语法完全一致**，可原样写入引用。

**坑**：
- JSON5 写入器：Python 生态的 JSON5 库普遍不保留注释，需要评估或自写"定位键 span 后原位替换"的最小写入器（这正是 Magpie 对 JSONC 的做法）。
- `$include`：受管键若位于被 include 的文件中，ACM 必须识别并置 ERROR，不能盲写主文件。
- 双重权威：OpenClaw 运行时自己会改写该文件（迁移、`openclaw config set`）。ACM 的漂移检测正好覆盖这种情况；但需要金样覆盖"OpenClaw 迁移重写后键序/格式变化不应被误判为漂移"（漂移比较的是值，不是字节）。
- OpenClaw 在 LAN/Tailscale 等私网地址上有请求防护（`request.allowPrivateNetwork` 等，见官方 vLLM 文档），团队 VMR 在内网时需要确认是否需额外设置。

**ACM 现状与差距**：无适配器，需新建；依赖 JSON5 写入器。

**临时启动（`acm run`）** [官方]：**仅支持一次性任务**：`openclaw agent exec "<任务>" --config-override '{"models":{"providers":{"vmr":{"baseUrl":"<VMR>/v1","apiKey":"${VMR_KEY}","api":"openai-completions","models":[...]}}},"agents":{"defaults":{"utilityModel":"vmr/<fast>"}}}' --model vmr/<default>`。交互式使用（经常驻 Gateway 与各渠道）无法临时注入——那需要改 Gateway 读取的配置，即 `acm use`。
- 依据：`openclaw agent exec` "runs one embedded agent turn without connecting to a Gateway. It is the recommended headless entry point for CI and coding automation"；"Config is layered entirely in memory … rather than writing a copy to disk"；`--config-override` "The resulting config is validated and never saved"；`--model` 选主模型（`docs/cli/agent.md`）。
- 待真机确认：`--config-override` 中的 `${VMR_KEY}` 是否做环境变量替换（文档写明 override 走"normal runtime normalization"，未明说替换）。若不替换，改为不在 override 中写 key、依赖进程环境中的 provider key 变量。
- 更正：上一版（临时启动设计文档 rev.1）判断 OpenClaw "不适用"，核查后修正为"一次性任务支持"。

**真机实测**：投影后 Gateway 热加载 → `openclaw agent exec "reply with OK"`（已核实的非交互入口）→ audit 命中 default 模型；一次会话标题生成命中 fast 模型。

### 4.6 Hermes Agent [官方]

**文件与格式**：`~/.hermes/config.yaml`（YAML；`$HERMES_HOME` 可改；Windows `%LOCALAPPDATA%\hermes`）；密钥常放 `~/.hermes/.env`；各 profile 在 `profiles/` 下有独立配置（Magpie 表）。Hermes 自己的 dashboard 也会写这个文件。

**连接字段**：

```yaml
providers:                      # 具名自定义 provider（官方示例中 api_key 使用 ${VAR}）
  team:
    base_url: https://vmr.team.lan/v1
    api_key: ${VMR_KEY}
model:
  provider: team                # 或 custom + base_url；具名 provider 能否直接被引用，实现时以源码确认
  default: coding               # "default" 与 "model" 两个键名都可
  api_mode: chat_completions    # chat_completions | codex_responses | anthropic_messages
  context_length: 200000        # 总窗口（输入+输出）
```

**角色槽位映射**：

| 角色 | 键 |
|---|---|
| default | `model.default`（+ `model.provider`） |
| fast | `auxiliary.<task>.{provider, model}`——共 11 个辅助任务（vision、compression、web_extract、title_generation、approval、curator 等）；默认 `provider: auto` 即跟随主模型。建议只为官方文档"Common override patterns"中推荐用快模型的任务写入（title_generation、compression、web_extract、approval），其余保持 `auto` |
| subagent | `delegation.{provider, model}`（官方注释："Override model for subagents (empty = inherit parent)"） |
| 窗口 | `model.context_length` |
| reasoning / review | 无 → 告警 |

**密钥引用能力**：`${VAR}` 引用（官方示例）或 `.env` 文件。

**加分项**：`session_affinity_header`——Hermes 可在每个请求上带一个会话 id 头，供"会话感知代理"使用。VMR 目前靠请求内容指纹做粘性，若将来支持读取显式会话头，Hermes 是现成的客户端。

**坑**：YAML 写入需 round-trip 保留注释（ruamel.yaml 已在依赖中，但 ACM 目前没有 YAML 写路径）；Hermes dashboard 与 ACM 同时写同一文件，依赖漂移检测。

**ACM 现状与差距**：无适配器，需新建；依赖 YAML 写入器。

**临时启动（`acm run`）** [官方]：`hermes chat --provider custom --base-url <VMR>/v1 -m <default>`，key 通过子进程环境变量 `OPENAI_API_KEY` 传入，不用 `--api-key`（会进命令行参数）。只走 OpenAI 兼容（Chat Completions）入口；辅助任务槽位与 `delegation` 无法单次注入，沿用 Hermes 自身配置（auto 即跟随主模型）。
- 依据 1：`--base-url <url>` / `--api-key <key>` "Explicit OpenAI-compatible endpoint and launch-only key for `--provider custom`. The key is … never written to disk"；`-m, --model` "Override the model for this run"（`reference/cli-commands.md`）。
- 依据 2：`OPENAI_API_KEY` 是 "the key for a custom OpenAI-compatible endpoint when `OPENAI_BASE_URL` is set; … sent only to that URL's exact origin"（`reference/environment-variables.md`）。
- 待真机确认：只给 `--base-url` 不给 `--api-key` 时是否读取 `OPENAI_API_KEY`；不行则改为同时设置 `OPENAI_BASE_URL` 与 `OPENAI_API_KEY` 两个环境变量。
- 更正：上一版判断 Hermes "没有 base_url 参数、只能有限支持"，核查后修正为"支持"。

**真机实测**：`hermes chat -q "reply with OK" --oneshot`（`-q` + `--oneshot`：回答后退出，已核实 `reference/cli-commands.md`）→ audit 命中；一次会话标题生成命中 fast 模型。

---

## 5. 第三梯队候选规格卡（精简）

> rev.2：本节原为"第二梯队规格卡"。这些 Agent 都需要独立代码路径，现归入 T3 候选；卡片保留，供将来按需晋升 T1 时作为起点。

卡片只记录实现时必需的事实与已知坑；细节在实现该适配器时再对照官方源补全。

| Agent | 文件 / 格式 | 端点 + 凭据 | 角色槽位 | 密钥引用 | 已知坑 | 来源 |
|---|---|---|---|---|---|---|
| **Gemini CLI** | `~/.gemini/settings.json`（JSON）+ `~/.gemini/.env` | `GOOGLE_GEMINI_BASE_URL`（写在 `.env`）+ key；`security.auth.selectedType` 选认证方式 | default → `model.name` | settings 支持 `$VAR`、`${VAR}`、`${VAR:-default}`（官方 configuration.md） | **只说 Gemini API**；`.env` 是 ACM 目前不支持的格式（需 env 写入器）；`~/.gemini` 下还有 Antigravity 的目录 | [官方] + [Magpie 源码] |
| **Qwen Code** | `~/.qwen/settings.json`（`$QWEN_HOME`） | `modelProviders.openai[]` 每项 `{id, name, baseUrl, envKey}`；`envKey` 指向 `env` 对象或 `~/.qwen/.env` 中的变量 | default → `settings.model {name, baseUrl}`；`security.auth.selectedType: "openai"` 免去启动认证提示；`imageModel` 用于生图 | 原生 `envKey`；settings 字符串支持 `$VAR`/`${VAR}`（官方） | 官方提示 `settings.model` 不宜手写，应配合 `modelProviders` 条目；同 id 多条目靠 `baseUrl` 区分 | [官方] + [Magpie 源码] |
| **Kimi Code** | `config.toml`：新版 Kimi Code（2.x）在 `~/.kimi-code`（`$KIMI_CODE_HOME`），旧 kimi-cli 在 `~/.kimi`（`$KIMI_SHARE_DIR`） | `[providers.<name>] {base_url, api_key}` + `[models."<key>"] {provider, model, max_context_size}` | default → `default_model`（必须是已定义的 models 键） | 官方示例为明文 `api_key`；引用支持未见说明 | Kimi 拒绝加载 `default_model` 或 provider 悬空的配置——写入顺序必须是 provider → models → default（删除反之）；**官方文档写 `~/.kimi/config.toml`，Magpie 注释称 kimi-cli 1.50 起交接给只读 `~/.kimi-code` 的新版**——实现前需在真机上确认 | [官方]（旧）+ [Magpie 源码]（新） |
| **Aider** | `~/.aider.conf.yml`（YAML）+ `.aider.model.metadata.json`（窗口等元数据） | `openai-api-base` + `openai-api-key`（或环境变量） | default → `model`；fast → `weak-model`；`editor-model`（architect 模式的编辑模型）可映射 default | 推荐用环境变量 `OPENAI_API_KEY` 而非写入文件 | 一个 YAML + 一个派生 JSON 元数据文件，跨文件一致性是 SPEC 中早已识别的"最难用例"；活跃度下降（最后推送 2026-05-22） | [官方] |
| **Crush** | 配置 `~/.config/crush/crush.json` + 数据文件 `~/.local/share/crush/crush.json` | `providers.<id> {type, base_url, api_key, models[]}` | `models.large`（default）、`models.small`（fast） | 支持 `$VAR` 与 `$(command)`（官方 README） | **Crush 自己的选择器把选择写进数据文件，并且数据文件优先于配置文件**——只写配置文件会被覆盖（Magpie 源码注释）；数据文件含 key，权限需 0600 | [官方] + [Magpie 源码] |
| **Goose** | `~/.config/goose/config.yaml` + `custom_providers/<id>.json` | 声明式 custom provider（JSON）：端点、模型列表、每模型 `context_limit`、`reasoning` | default → `GOOSE_PROVIDER` / `GOOSE_MODEL`（config.yaml 中） | **"Provider API keys do not go in config.yaml"**（官方），走系统钥匙串 / secrets | `dynamic_models: false` 才会用声明的列表；无 `context_limit` 时按名字猜或用 128K（Magpie 注释引用 goose 源码 `context_limit.rs`） | [官方] + [Magpie 源码] |
| **oh-my-pi** | `~/.omp/agent/config.yml` + `models.yml`（`PI_CONFIG_DIR`、`OMP_PROFILE` 等） | 同 Pi 的 provider/model 语义，YAML 形态 | default；其他角色与 fallback 链（`RenameRefs` 处理） | 同 Pi（未核实） | 与 Pi 共享 `PI_CODING_AGENT_DIR` 变量，可能指向 Pi 的目录——需防止误写 Pi 文件（Magpie 注释） | [Magpie 源码] |
| **Droid（Factory）** | `~/.factory/settings.json`（`$FACTORY_HOME_OVERRIDE`） | `customModels[] {model, displayName, baseUrl, apiKey, provider}`，provider ∈ `anthropic` / `openai`（Responses）/ `generic-chat-completion-api` | default → `sessionDefaultSettings.model`，值形如 `custom:<id>` | 官方 BYOK 文档描述了按环境解析的写法（实现时确认） | 自定义模型的选择 id 由 displayName 推导（空格变短横线并带序号）——必须显式写 `id` 字段避免漂移 | [官方] + [Magpie 源码] |
| **Cline CLI** | `~/.cline/data/settings/providers.json`（`$CLINE_DIR`）+ `models.json` | 只能用内建 `openai-compatible` provider（自定义 provider id 会在会话启动时被拒，cline/cline#14180） | default → `lastUsedProvider` + 该 provider 的 `model`；`reasoning {enabled, effort}` | 未核实 | VS Code 扩展优先读取 `globalState.json` 中自己的状态——ACM 只支持 CLI，扩展明确排除 | [Magpie 源码] |

---

## 6. 对 ACM 的工程影响

### 6.1 格式写入器是真正的关键路径

| 写入器 | 现状 | T1（及其 T2 成员）需要 | T3 候选需要 | 实现建议 |
|---|---|---|---|---|
| JSON（保序） | 已有 | Claude Code、Pi（含 OmO、Prime Agent） | Qwen、Droid、Crush、Cline、Gemini | — |
| TOML（tomlkit round-trip） | 已有 | Codex | Kimi | — |
| YAML（ruamel round-trip） | 依赖已有，写路径未实现 | **Hermes** | Aider、Goose、oh-my-pi | 按 SPEC 原计划启用 ruamel rt 模式；round-trip 测试先于适配器（PRINCIPLE §6.3） |
| **JSONC**（保留注释） | 无 | **OpenCode**（含 MiMo Code、DevEco Code） | — | 不做完整解析-重序列化；采用"解析定位键的字节范围 → 原位替换 → 整体重新解析校验"的最小写入器（Magpie `internal/edit` 的思路），与现有 AST 非破坏断言组合 |
| **JSON5** | 无 | **OpenClaw** | — | 同 JSONC 的原位替换策略；JSON5 额外语法（无引号键、单引号、尾逗号）需要专门的扫描器与 fixture |
| env 文件 | 无 | — | Gemini CLI | 简单，但涉及 key 明文，需要先确定是否只写引用 |

**结论**：T1 的六个 Agent 里有三个（OpenCode、OpenClaw、Hermes）依赖新写入器。写入器的 round-trip 测试必须先于适配器完成，这是 PRINCIPLE §6 的既有质量门禁。

### 6.2 协议与 Manifest 方案的联动修正

- **Codex 只说 Responses**：Manifest 方案 §5.5.3 中 Codex 的协议偏好序应定为 `[openai-responses]`，不再列 chat；方案 §8.1 的待核项 A3 由此关闭。VMR 侧要服务 Codex 用户，必须给 `default`（以及 `subagent`、`review`）角色模型提供 `openai-responses` 入口；`vmr check` 的 V3 告警应专门提示这一点。
- **ACM 现有 Codex 适配器的协议映射有缺陷**（`src/acm/adapters/codex.py:94-106`）：
  - `protocol: openai`（Chat Completions 端点）被映射为 `wire_api = "responses"`，且**不告警**——Codex 会对一个只懂 Chat Completions 的端点发 `/responses` 请求，运行时才失败。应改为：非 `openai-responses` 协议的 provider 投影到 Codex 时产生 ERROR（该 Agent 阻断，批处理中其他 Agent 照常）。
  - `protocol: anthropic` 被映射为 `wire_api = "chat"`——Codex 已不接受该值。
  - 相关金样 `tests/fixtures/codex/config.golden.toml` 中的 `wire_api = "openai"` 也是过时取值（fixture 本身作为"既有用户文件"样本无妨，但断言应覆盖新规则）。
- **Gemini 协议**：若 T2 的 Gemini CLI 落地，ACM 的 `protocol` 枚举需新增 `gemini`；VMR 不提供该入口，Manifest 对它不适用，只用于直连。

### 6.3 密钥落盘方式的统一策略

| Agent | 原生引用能力 | ACM 应写入 |
|---|---|---|
| Codex | `env_key` | 变量名（现状已如此） |
| Pi | `"$NAME"` / `"!command"` | `$NAME`（现状已如此） |
| OpenCode | `{env:VAR}` / `{file:path}` | `{env:VAR}` |
| OpenClaw | `${VAR}` / `${VAR:-default}` | 原样写 ACM 的引用 |
| Hermes | `${VAR}`、`.env` | `${VAR}` |
| Qwen Code | `envKey` + `$VAR` | `envKey` |
| Claude Code | `env` 为字面量（官方："Values here are plain text in the settings file"）；`apiKeyHelper` 命令 | **`apiKeyHelper`**——官方明确建议 "for API credentials, use apiKeyHelper"（settings-reference）；ACM 写入固定模板 `printenv <VAR>`，不写明文。待真机确认 helper 子进程继承调用方环境变量 |
| Goose | 系统钥匙串 | 不写 key，提示用户用 Goose 自己的方式配置 |

原则：**凡 Agent 原生支持引用的，一律写引用，绝不写明文**。按上表，T1 的 6 个 Agent 全部可以做到"配置文件中零明文"（Claude Code 经 `apiKeyHelper`）。

### 6.4 角色槽位矩阵（T1 完整版，取代 Manifest 方案 §5.5.4 的三列版）

| 角色 | Claude Code | Codex | OpenCode | Pi | OpenClaw | Hermes |
|---|---|---|---|---|---|---|
| default | `model` + SONNET 槽 | `model` | `model` | `defaultModel` | `agents.defaults.model.primary` | `model.default` |
| reasoning | OPUS + FABLE 槽 | 告警 | 告警 | 注册 | 告警 | 告警 |
| fast | HAIKU 槽 | 告警 | `small_model` | 注册 | `agents.defaults.utilityModel` | `auxiliary.{title_generation, compression, web_extract, approval}` |
| subagent | `CLAUDE_CODE_SUBAGENT_MODEL` | `agents.default_subagent_model` | 告警 | 告警 | 告警 | `delegation.model` |
| review | 告警 | `review_model` | 告警 | 告警 | 告警 | 告警 |
| 窗口 | `CLAUDE_CODE_MAX_CONTEXT_TOKENS` | catalog 条目 + `model_context_window` | `models.<id>.limit.context` | `contextWindow` | `models[].contextWindow` | `model.context_length` |

"告警"均为投影损失告警，按 Manifest 方案的槽位策略处理（未声明的非必需槽位不写；Claude Code 别名槽位缺失时回落 default）。

---

## 7. 临时启动配置（`acm run`）总表与事实核查

临时启动的命令设计、执行机制与原则约束见 `docs/ACM_Ephemeral_Run_Design_opus-5.5.md`；**各 Agent 的具体注入规则只在本文维护**（各规格卡的"临时启动"段落与本节）。

### 7.1 第一梯队

| Agent | 注入方式 | 密钥去向 | 进程模式 | 可注入的角色 | 核查结论 |
|---|---|---|---|---|---|
| Claude Code | `--settings '<内联 JSON>'` | `apiKeyHelper: printenv <VAR>`，JSON 中无密钥 | `exec`，零文件 | 全部（default、reasoning、fast、subagent、窗口） | 支持；1 项待真机确认（§4.1） |
| Codex | 多个 `-c key=value` | `env_key` | 有临时 catalog 时父进程，否则 `exec` | default、review、subagent、窗口（经 catalog） | 支持 |
| OpenCode | 环境变量 `OPENCODE_CONFIG_CONTENT` + 可选 `-m` | `{env:VAR}` | `exec`，零文件 | default、fast（`small_model`）、窗口 | 支持（源码确认变量替换） |
| Pi | `-e <随包固定扩展>` + `--model` | `$NAME` | `exec`，零文件 | default + 注册其余角色模型；有 fast / reasoning 时经虚拟模型 `acm/auto` 按思考档位路由 | 支持 |
| OpenClaw | `openclaw agent exec "<任务>" --config-override '<JSON>' --model ...` | `${VAR}`（替换与否待确认） | 由 OpenClaw 自身管理临时状态 | default、fast（`utilityModel`） | **仅一次性任务**；交互式不支持；1 项待确认 |
| Hermes | `--provider custom --base-url ... -m ...` | 子进程环境变量 `OPENAI_API_KEY` | `exec`，零文件 | 仅 default | 支持（仅 OpenAI 兼容入口）；1 项待确认 |

### 7.2 第二梯队（家族成员）

| 成员 | 预期 | 核查结论 |
|---|---|---|
| MiMo Code、DevEco Code | 继承 OpenCode 的内联配置机制 | **未核实**：未找到官方源码或文档；且 Magpie 源码显示这两个分叉已改名环境变量（`MIMOCODE_HOME`、`DEVECO_CONFIG_DIR`），`OPENCODE_CONFIG_CONTENT` 很可能也被改名。实现时真机确认实际变量名，作为成员参数声明 |
| OmO、Prime Agent | 继承 Pi 的 `-e` + `--model` | **未核实**：未找到官方源码或文档；目录变量已改名（`OMO_CODING_AGENT_DIR`、`PRIME_AGENT_CODING_AGENT_DIR`），命令行参数是否保留未知 |

T2 成员的 `acm run` 在真机确认前默认关闭，`acm run` 对其给出明确提示，不做猜测性注入。

### 7.3 第三梯队候选

未调研临时启动方式；晋升为 T1 时按本节格式补齐并核查。

### 7.4 事实核查记录（2026-10-19 至 10-20）

| # | 被核查的论断 | 出处 | 结论 |
|---|---|---|---|
| 1 | Claude Code 可用 `--settings` 做单会话覆盖，且接受内联 JSON | code.claude.com CLI reference | **确认** |
| 2 | 给 Claude Code 子进程设置 `ANTHROPIC_AUTH_TOKEN` 即可临时换 key | settings-reference：settings 的 `env` 值覆盖 shell 导出值 | **否定**：用户 settings.json 中的同名值会覆盖它；改为经 `--settings` 注入并置空 |
| 3 | Claude Code 凭据宜用 `apiKeyHelper` | settings-reference `apiKeyHelper` 与 `env` 条目 | **确认**（官方原文建议）；同时改变了持久投影的密钥策略（§6.3） |
| 4 | Codex `-c` 支持点分路径覆盖嵌套表 | `codex-rs/utils/cli/src/config_override.rs` | **确认** |
| 5 | OpenCode 内联配置优先级高于用户与项目配置 | config 文档 "Precedence order" | **确认**（仅低于管理员托管配置） |
| 6 | OpenCode 内联配置中 `{env:VAR}` 生效 | `packages/core/src/config.ts` | **确认** |
| 7 | Pi 扩展注册的 provider 可被同一命令的 `--model` 选中 | `docs/custom-provider.md` | **确认** |
| 8 | Hermes 没有临时指定 base_url 的参数，只能有限支持 | `reference/cli-commands.md` | **否定**：有 `--base-url` / `--api-key`（配合 `--provider custom`） |
| 9 | OpenClaw 不适用临时启动 | `docs/cli/agent.md` | **部分否定**：`agent exec` 支持一次性任务的内存叠加配置；交互式仍不适用 |
| 10 | CC Switch 的临时启动只支持 Claude Code，key 写入系统临时目录 | `cc-switch` 源码 `src/App.tsx:1254`、`src-tauri/src/commands/misc.rs` | **确认** |
| 11 | Magpie 无临时启动命令 | Magpie `internal/cli` 命令列表与 `docs/reference.md` 检索 | **确认**（未找到；结论为"未发现"而非"已证明不存在"） |
| 12 | T2 成员继承族长的注入方式 | 无官方来源；Magpie 源码显示变量已改名 | **未核实** |
| 13 | Pi、OpenClaw、Hermes 的非交互调用命令（原未验证项 U1） | Pi `docs/cli.md`；OpenClaw `docs/cli/agent.md`；Hermes `reference/cli-commands.md` | **确认**：`pi -p`、`openclaw agent exec`、`hermes chat -q ... --oneshot` |

---

## 8. 第一梯队真机实测规程

"实测有效"的定义（每个 T1 Agent、每次发版）：

1. **投影**：在干净的测试 HOME（含该 Agent 的真实既有配置样本，带 hooks / MCP / 注释等非受管内容）上执行 `acm use <profile>`。
2. **调用**：用该 Agent 的非交互模式发一次最小请求（Claude Code `claude -p`、Codex `codex exec`、OpenCode `opencode run`；Pi / OpenClaw / Hermes 的非交互命令在实现时按其官方 CLI 文档确认）。
3. **证据**：VMR audit 中出现该请求，`model` 字段等于角色解析结果；对有 fast 槽位的 Agent，再触发一次后台任务并确认命中 fast 模型。
4. **无损**：比对非受管内容与投影前语义一致（现有 AST 断言）。
5. **回滚**：`acm rollback <agent>` 后受管字段恢复、期间 Agent 写入的状态存活。
6. **记录**：Agent 版本号、ACM 版本、VMR 版本、结果，写入发版记录。Agent 版本升级导致失败时，按铁律置 ERROR，不盲写。

T2（家族成员）不执行第 2–3 步，只跑金样（1、4、5）；其代码路径的正确性由族长的真机实测覆盖。

---

## 9. 未验证项、风险与下一步

### 9.1 未验证项

| # | 项目 | 何时验证 |
|---|---|---|
| U1 | ~~Pi、OpenClaw、Hermes 的非交互调用命令~~ 已核实（§7.4 #13） | — |
| U2 | Hermes 的 `model.provider` 能否直接引用具名 `providers.<id>` | Hermes 适配器实现时，读 `hermes_cli` 源码 |
| U3 | Codex `model_catalog_json` 条目的精确结构 | Codex catalog 生成实现前，读 `codex-rs/protocol/src/openai_models.rs` |
| U4 | Claude Code `apiKeyHelper` 子进程是否继承调用方环境变量（决定 `printenv <VAR>` 模板是否可用） | P6.1 真机 |
| U5 | Kimi Code 新旧配置目录的实际行为 | Kimi 适配器实现时真机确认 |
| U6 | OpenClaw 私网请求防护是否影响团队内网 VMR | OpenClaw 真机实测时 |
| U7 | T3 全部条目仅来自 Magpie 表 | 不验证（无回报）；若某项被申请转入 T2 时再核 |

### 9.2 风险

1. **上游格式漂移速度**：Magpie 的 LESSONS.md 显示其维护者（主要是夜间运行的 AI 编码代理）几乎每天都在修 Agent 适配问题。T1 的 6 个 Agent 意味着持续的跟进成本——这是选择"T1 只放 6 个"的根本原因。
2. **新写入器的风险集中在 JSON5 / JSONC**：原位替换式写入器的正确性完全依赖扫描器；需要 fuzz 或大量真实样本 fixture。
3. **OpenClaw 的双重权威更强**：它不仅运行时写文件，还会做启动迁移与 `doctor --fix`。漂移检测会频繁触发时，用户体验会变差，需要真机观察后再调。
4. **Codex catalog 文件**是 ACM 第一个"完整生成并独占"的文件，需要在 PRINCIPLE 中补一条规则：ACM 新建且独占的文件（不与 Agent 共享）可整文件生成，但路径必须在白名单中、回滚即删除。

### 9.3 下一步

执行顺序与验收标准见 `docs/ACM_Rebuild_Action_Plan_opus-5.5.md`。本节旧版中"先修 Codex 协议映射缺陷"一项取消：ACM 将按 Action Plan 重建，旧适配器整体归档，该缺陷作为新 Codex 适配器的金样用例（`openai` 协议 provider 投影到 Codex 必须报错）保留其教训。

## 10. 实现回写（2026-10-20，ACM 0.4 实现后与上文的差异与新增事实）

> 本节由实现阶段回写。与上文冲突时，**以本节为准**；上文保留为设计与核查的原始记录。

### 10.1 待确认项的真机结论

| 项 | 结论 | 依据 |
|---|---|---|
| Claude Code：`env` 中置空串的 `ANTHROPIC_AUTH_TOKEN` / `ANTHROPIC_API_KEY` 是否视为未设置并回落 `apiKeyHelper`（§4.1） | **确认可用** | 真机测试（本地模拟网关，隔离 HOME）：`acm run claude` 用 `--settings` 内联 JSON 置空两者 + `apiKeyHelper: printenv VAR`，请求带期望的 key |
| `apiKeyHelper` 子进程是否继承调用方环境变量（U4） | **确认继承** | 同上；`printenv <VAR>` 模板可用 |
| OpenCode `small_model` 是否对应 `fast` 角色 | **确认被使用** | 真机：首个请求是标题生成，走 `small_model`；测试断言为模型集合 `{主模型, fast 模型}` |
| Codex 自定义 catalog 的严格性 | **确认被严格解析** | 真机：不合规 catalog 被拒；已用金样固定合规结构（含 `base_instructions`） |
| Pi 扩展 API 的每模型字段 | **新发现** | 真机：扩展注册模型时 `input / reasoning / contextWindow / maxTokens / cost` 必填；随包扩展 `acm_pi_provider.ts` 对未知值写保守默认 |
| OpenClaw `--config-override` 内 `${VAR}` 是否被替换（§7） | **仍未确认** | 本机无 OpenClaw 二进制；`acm run openclaw` 把 provider 的 `apiKey` 写为 `${VAR}`（凭据为明文时改为 `${ACM_RUN_KEY}` 并经环境变量传值），启动时输出"替换未经真机验证"的提示；仅支持一次性任务（`agent exec`） |
| Hermes `--base-url` 不带 `--api-key` 时的行为（§7） | **仍未确认** | 本机无 Hermes 二进制；金样覆盖 |

### 10.2 与上文设计的偏差

| 项 | 上文 | 实现 |
|---|---|---|
| Prime Agent `subagentDefaultModel` | 可映射 subagent 角色 | **不写**：语义未经核实，宁缺毋滥；仅 Pi 通用槽位 |
| OpenCode `limit` | 按模型卡片写 | schema 要求 `limit.context` 与 `limit.output` 成对出现；上下文已知而输出未知时写 `min(32000, context)` 并告警 |
| OpenCode 配置键 | `provider` | 沿用 `provider`（官方文档与已装 1.3.13 一致）；schema 标注其 deprecated（新键 `providers`），记为升级风险 |
| Hermes provider 命名 | `providers.<alias>` | 具名项统一前缀 `acm-`，`model.provider: custom:acm-<alias>`，避免与内建名冲突；`model` 为空串哨兵时整体替换为映射 |
| OpenClaw `$include` | 未规定 | 受管段使用 `$include` 时适配器报错（ERROR），不编辑 |
| 历史命令 | `history prune` | `acm prune --keep N`；`acm restore N` 的 N 为 **op 编号** |
| 临时启动 T2 | 默认拒绝 | 同；`acm run` 对 T2 成员报错退出 1 |
| 单端点 Agent 的跨 provider 角色（复审 B6） | 未规定 | Claude Code 只有一个 `ANTHROPIC_BASE_URL`，Codex 只有一个 `model_provider`：来自其他 provider 的角色 / 成员不写入槽位或 catalog，回落默认模型（Claude Code）或删除槽位（Codex `review_model` / `agents.default_subagent_model`）并告警。别名槽位映射本身不变 |
| `acm run` 的明文 key（复审 B1） | 统一 `ACM_RUN_KEY` | 每个 provider 一个变量：默认 provider 用 `ACM_RUN_KEY`，其他用 `ACM_RUN_KEY_<NAME>`（Pi、OpenCode、OpenClaw） |

### 10.2a 复审核实（2026-10-20，官方文档）

| 项 | 结论 | 来源 |
|---|---|---|
| Claude Code 别名槽位 | `ANTHROPIC_DEFAULT_{OPUS,SONNET,HAIKU,FABLE}_MODEL` 控制 `opus` / `sonnet` / `haiku` / `fable` 别名解析，现行映射正确 | code.claude.com/docs/en/model-config |
| `CLAUDE_CODE_MAX_CONTEXT_TOKENS` | 存在："Override the context window size Claude Code assumes for the active model"——属模型能力信息，不是用量预算 | code.claude.com/docs/en/env-vars |
| Claude Code 认证优先级 | `ANTHROPIC_AUTH_TOKEN` / `apiKeyHelper` 高于订阅 OAuth 登录；订阅登录存于钥匙串或 `~/.claude/.credentials.json`，与 `settings.json` 分离——移除 ACM 字段即回到订阅，无需重新登录（登录本身过期除外） | code.claude.com/docs/en/authentication |
| Codex / OpenCode / Pi 的登录存储 | `~/.codex/auth.json`、`~/.local/share/opencode/auth.json`、`~/.pi/agent/auth.json`；ACM 不管理（测试强制：任何适配器的受管文件都不是登录存储） | 基于经验判断，未真机核实 |

### 10.3 测试覆盖的真实程度

- T1 中 Claude Code / Codex / Pi / OpenCode 有真机二进制测试（`tests/real/`，二进制缺失时自动跳过）；Hermes / OpenClaw 仅金样。
- 格式层语料为按官方文档合成的"前 ACM 用户配置"样本（含 hooks / MCP / 注释），非真实机器拷贝（`tests/fixtures/README.md`）。
