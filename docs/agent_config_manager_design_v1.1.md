<!-- // Ver 2026-10-08 00:48, by coding | v1.1 rev.2: 市场格局/事故实证/受管面纪律/存在理由/语言栈 -->

# ACM (Agent Config Management) 系统架构与设计方案 (v1.1 rev.2)

> **项目代号**：`acm`（PyPI 包名 `agent-config-manager`）
> **核心定位**：本地优先、零守护进程、面向全生态 AI Coding Agent 的**模型配置 SSOT 与字段级投影引擎**。
> **文档性质**：本文件是 v1.0 设计方案的修订版（产品愿景层）。**治理规格以 `docs/ACM_PROJECT_PRINCIPLE_v2.2.md` 为准**——两者冲突时，v2.2 原则无条件胜出。本文的职责是把 v1.0 时代的原始愿景与当前已落地的架构（v0.3.x MVP + schema v3）重新对齐，并吸收 2026 年竞品（magpie）的实况经验。
>
> **rev.2（2026-10-08）**：基于同日完成的市场扫描、竞品事故实证、字段级 80/20 分析与存在性讨论，增补：§2.4 市场格局、§2.5 事故实证与两种写入架构、§3.6 受管面纪律、§4.2 存在理由与死亡条件、§5.1 语言栈评估；并相应修订 §5/§6/§7。核心结论变化：**ACM 的存在理由收敛为「VMR 的配置面 + 零守护进程极简工具」，不再是通用配置切换器**（见 §4.2）。

---

## 一、v1.1 修订总纲：这次修订改了什么，为什么

v1.0 成文于项目立项之前，是一份"从痛点出发"的愿景文档。此后项目经历了原则重铸（v2.2 治理规格）与 MVP 交付（Python CLI，Claude Code / Codex / Pi 三适配器上跑通 Safety Engine），v1.0 中的若干核心机制判断已被推翻或降级。v1.1 不做"措辞修补"，而是逐项裁定：**保留、修正、废止**。

| # | v1.0 主张 | 裁定 | v1.1 立场 |
|---|---|---|---|
| 1 | L0 本地配置面 / L1-L2 网络面双子星分层，ACM 与 VMR 正交互补 | **保留** | 仍是立项根基。联动方式修正：不再新增 `acm link vmr` 命令，VMR 探测并入 `acm init`（已交付），增量合并走触发式的 `acm import vmr` |
| 2 | 只管模型连接核心要素，绝不碰 MCP / Prompts / hooks / plugins | **保留并强化** | 已固化为 v2.2 §2.1 判定原则："换了 Provider/模型之后理应保持不变的东西，ACM 一律不碰"，并加设范围测试一票否决 |
| 3 | RFC 6902 JSON Patch + CST 整文件补丁 + 世代快照树（gen-001/002/003） | **废止，改为字段所有权模型** | 整文件版本控制陷入"双重权威死锁"（详见 §3.1）：Agent 运行时持续向同一文件写 OAuth token、会话状态、插件记录，整文件世代回滚必然打丢窗口期写入。改为 Kubernetes SSA 式的字段所有权：受管字段确定性写入 + 字段级回滚，未管内容 AST 级零破坏，整文件快照仅作只读灾难恢复兜底 |
| 4 | "Byte-Identical Pristine State" 物理字节完全一致恢复 | **废止，改为两级诚实声明** | 字节级完全一致在 Agent 运行时并发写同一文件的前提下不可承诺。v1.1 承诺：未管理节点**语义级不变**（硬承诺）；注释/键序/排版保留按金样 fixture 界定，不夸大 |
| 5 | `~/.acm/history/<agent>/gen-*.patch` + `active_state.json` | **废止，改为 v2.2 §3.3 数据模型** | `~/.acm/config.yaml`（SSOT）+ `~/.acm/state/<agent>/`（journal.jsonl 事务日志 / last_write.json / snapshots/<txid>/）；配置与状态严格分离，状态永不写回 config.yaml |
| 6 | Go + Wails v3 菜单栏 GUI 为 Milestone 2 主交付 | **废止，降级为触发式（P3）** | v2.2 明文将"变成 GUI 全家桶"列为反面界定，且实际技术栈已定为 Python 3.12 + PyPI/uvx 分发。GUI/TUI 的真实价值保留（见 §5），但只在核心 CLI 语义稳定、出现真实需求后，以"CLI 之上的薄投影层"形态触发（`--json` 先行） |
| 7 | 命令面 `list / use / rollback / diff`，Milestone 1 交付 | **修正** | MVP 已交付 `init / status / use / rollback`；`diff / doctor / history / release / import vmr` 均为触发式升级，按 v2.2 §7 触发表启动，不预防性实现 |
| 8 | 首批 6 款 Agent（含 Cursor、OpenClaw、Cline） | **修正** | "适配器数量"不是 KPI。P0 = Claude Code / Codex / Pi（格式与投影形态上足以验证架构充分性，均已交付）；Aider 为 P1 首位（YAML + 角色模型压力测试） |
| 9 | 原则 4：落盘前沙箱语法校验 + 端点连通性干跑 | **保留并细化** | 已兑现为：`${ENV}` 解析失败 = 硬错误、任何写盘前整体中止；`--dry-run`；写管道内语法自检 + AST 非破坏断言 + SHA-256 指纹复核 + 原子替换。端点连通性干跑保留为 opt-in 触发项（涉及网络与凭据外发，不可默认开启） |
| 10 | 对 Magpie / CC Switch "粗暴覆写、无法无痕回滚"的批判 | **修正（事实已变）** | 2026 年的 magpie 已实现"只改那一个键、注释顺序格式原样保留、原子重写"（见 §2）。差异化必须升级：ACM 的护城河不再是"不破坏文件"，而是**漂移显式阻断、字段级精确回滚、SSOT-as-code、零守护进程**（见 §4） |

---

## 二、竞品实况：magpie（2026）给我们的三张清单

magpie 已从 v1.0 成文时的"破坏性覆写反面教材"演化为成熟的常驻型全家桶：菜单栏 / TUI / Web UI / CLI 四形态，35+ Agent，本地网关（127.0.0.1:3425，四协议互转）、路由组（smart/order/rotate/usage/pace 五种故障转移模式）、订阅共享（Claude/ChatGPT/Copilot/Gemini 登录态变 provider）、npm 插件与网关中间件、用量与成本追踪、Docker/WebDAV 同步。逐项过一遍 v2.2 §2.1 范围测试（"换了 Provider/模型之后理应保持不变吗？"），得出三张清单：

### 2.1 值得吸收的（进 v1.1 触发项，见 §6）

1. **模型目录外源化**：magpie 不内置任何模型清单，全部来自厂商 API 与 models.dev，"今天发布的模型下次刷新就有"。对 ACM 的启示：`import vmr` 拉取虚拟模型即天然外源；未来若做直连厂商 preset，同样只存端点与凭据引用，模型列表实时拉取，绝不在 config.yaml 里维护静态模型库。
2. **从既有工具导入**：magpie 支持 import CC Switch / Claude Code / Codex / Alma 的既有 provider。ACM 的对应物是触发项 `acm import agents`（从本机 Agent 现有配置反向生成 config.yaml 草案），受三条铁律约束：导入的明文密钥必须转 `${ENV}` 引用或显式 opt-in；导入只生成提案、确认后才落盘；产出的 config.yaml 属 L1 管理字段，天然满足范围测试。
3. **Profile 一键全局切换的 UX**：magpie 的 `save work && use work`（"Budget"、"Focus" 场景）验证了 Profile 语义的真实需求——这正是 ACM 的既有核心（`acm use <profile>`，全局默认 + 可指定单 Agent），无需新增能力，只需在 Phase 2 的 `acm bind`（Agent 级绑定）落地后补齐"部分 Agent 跟随全局、部分绑定独立 Profile"的混合场景。
4. **CLI 动词化直改**：`magpie claude deepseek/deepseek-v4-pro` 这种"单 Agent 单键直改"交互对一次性场景很顺手。ACM **不采纳为主接口**（它绕过了 SSOT 与 Profile 语义，容易退化成散点配置），等价能力已由 `acm use <profile> <agent>` 覆盖；若真实需求出现，可作触发项 `acm set <agent> <field>`，但必须先回答"这个字段落不入 config.yaml 的 SSOT"。
5. **TUI 优先于 GUI**：magpie 四形态中 `magpie tui` 证明了终端全功能界面足以承载复杂管理，且与 ACM 的 CLI 分发路径（PyPI/uvx）零额外依赖成本。若未来触发界面层，顺序定为 `--json` → TUI → 菜单栏 GUI。

### 2.2 明确拒绝的（范围测试不过，无论 magpie 做得多好）

- **本地网关 / 路由组 / 故障转移 / Intent routing**：这是 VMR 的领域（v2.2 §2.3 明文"本地代理/网关/请求改写"不管）。ACM 只负责把 Agent 指向网关端点，绝不内置第二个网关。
- **订阅共享 / OAuth 登录态池 / 账号轮转 / 额度监控**：v2.2 §2.3 明文不管；涉及凭据保管与账号生命周期，违反"不承担 secret storage"公理。
- **插件 / 网关中间件 / MCP-Skills-Instructions 库**：v2.2 铁律 1（绝不触碰 MCP、插件、Skills、提示词）；magpie 的 Library 模块即便宣称"只移除自己写的内容"，也在 ACM 的范围测试下出局。
- **用量与成本追踪 / OTLP 导出**：切换 Provider 后这些数据全部作废，范围测试直接不过。
- **常驻进程（守护进程 / 托盘常驻 / 自更新）**：见 §4.3，这是 ACM 的结构性差异点，不是能力短板。

### 2.3 竞争定位的诚实结论

magpie 是"重型常驻枢纽"路线：一个 resident 进程统管模型世界 + 网络面 + 生态插件，体验上限高，但用户让渡了大量本地控制权（常驻后台、下载 Bun 运行时跑插件、网关中介所有流量）。ACM 走"轻量确定性工具"路线：**按需运行、零守护进程、config.yaml 可 git 版本化、字段级精确回滚、一切异常显式暴露**。二者不是同一条赛道上的远近之争：

- 要"订阅共享 + 智能路由 + 全家桶 GUI"的用户 → magpie（或 ACM+VMR 组合中的 VMR 侧承担对位能力）；
- 要"配置文件绝对不被工具绑架、每次写入可审计可精确撤销"的用户 → ACM。
- ACM+VMR 组合对标 magpie 全家桶：VMR 承担 L1/L2 网络面对位能力（容灾、缓存亲和、协议透传、审计），ACM 承担 L0 配置面，且两半都坚持"非破坏 + 显式暴露"的哲学底线。

### 2.4 市场格局扫描（2026-10 实测）：语义空位确认，但 80% 战场已被占领

对"市面上是否有与 ACM 同定位的纯配置管理工具"做了实测扫描，结论：**纯粹做 Agent 配置管理（非网关、非全家桶）且带治理语义的工具没有找到，但「切换器」赛道已拥挤**：

| 工具 | 形态 | 定位 | 与 ACM 的关系 |
|---|---|---|---|
| **CC Switch**（farion1231，~89K stars） | Tauri 桌面 GUI + 托盘 | Claude Code/Codex/Gemini CLI/OpenCode/OpenClaw 供应商切换 + **MCP/Skills/Prompts/会话/用量/本地路由**，大而全 | 最近的邻居，哲学相反：范围无边界；已侵入本地路由（VMR 领域），印证 switcher 必然向网关蔓延 |
| **AI Switcher (aisw)**（burakdede） | CLI + Desktop alpha | 多**账号**命名 Profile 切换（Claude Code/Codex/Antigravity/Gemini） | 形态最像 ACM（CLI-first），但管账号轮换，无 SSOT/漂移/回滚语义 |
| **magpie**（yetone） | 常驻 app（菜单栏/TUI/Web/CLI） | 配置编辑只是其一大模块（35+ Agent），叠加网关/订阅/插件 | 见 §2.1-2.3 |

**语义空位确认**：字段级所有权、外部漂移检测+阻断、journal 字段级精确回滚、SSOT-as-code（可 git 的 YAML）——公开市场上**没有任何已落地工具在做**。「GitOps for AI Agents」目前只是博客话语（declarative config + PR review 的呼吁），无对应产品。诚实解读：差异化空位真实存在；但 CC Switch 89K stars 证明大众用脚投票选的是「GUI 全家桶」，治理语义属长尾但高信任价值的生态位——用户往往是**配置被工具搞坏过之后**才来找 ACM。

### 2.5 事故实证与两种写入架构（对 §3.1/§4 的证据支撑）

**cc-switch 事故实证**：其仓库标题含「覆盖/丢失/overwrite」的 issue 多达 **177 个**，同一类 bug 从 2026-02 到 2026-09 反复出现、修复后回归、多个至今 open：#1198（启动即改写 settings.json，hooks/permissions 丢失）、#1570（切换时完全覆盖文件，个人配置清零）、#3631（全量重写致 enabledPlugins 清空，用户原话"cc-switch 不该管的字段被清空"）、#6875（覆盖 config.toml 与 auth.json，**用户明确抱怨"无物理文件备份"**）、#6141（`permissions.deny` 数组整体覆盖）、#6183/#4142/#6230/#7235（静默覆盖 `[windows]`/`[projects]` 段、开关路由致文件丢失、自定义 env 丢失）、#6630/#7042（oauth/登录态被覆盖）。每类事故都能 1:1 映射到 ACM 三公理。旁证：anthropics/claude-code#27941（`.claude.json` 在会话运行中静默回滚用户编辑）——**双重权威死锁连「用户 vs Agent 运行时」之间都真实存在**；以及用户被迫把全部自定义配置塞进切换器的供应商 JSON 以求写回时"顺带"保留——把全部字段所有权上交给工具，正是字段所有权模型的反面活教材。

事故的时间线含义（02 月修了 03 月再犯，06 月修了 08 月批量 open）：**整文件覆写不是实现 bug，是模板恢复式架构的必然属性**。两种写入架构对照：

| | 模板恢复式（cc-switch 问题路径） | 外科手术式（magpie） |
|---|---|---|
| 写入模型 | 每 provider 存整文件模板，切换 = 整体写回 | 解析 → 定位目标键 span → 原位替换 → 原子写盘 |
| 未管内容命运 | 活在工具的数据模型里，模板与活文件的任何偏差在每次写盘时变成数据丢失 | **文件从不重新生成**，物理上碰不到那些字节，安全是"免费"的 |
| 爆炸半径 | 大（它还管 MCP/Skills/Prompts） | 极小（每 Agent 只写 1-3 个键：model / effort / planner） |
| 代价/边界 | 177 个 issue，修复后回归 | Profiles = 整快照恢复（双重权威陷阱入口）；无漂移概念（拥有的键被外部改动即静默覆盖）；无字段级回滚/审计/SSOT |

值得注意：我们 v1.0 的「世代快照树」与 cc-switch 的失败路径同构，v2.2 的字段所有权正是对它的否定——生产环境已替我们完成了实证。同时 magpie 证明了一件倒逼自省的事：**若 ACM 每个 Agent 也只写一个键，v2.2 的 Safety Engine 就是过度设计**。机器的重量必须由受管面承诺供血，由此导出 §3.6 的受管面纪律与 §4.2 的存在理由。

---

## 三、修正后的核心架构（v1.1 定稿）

### 3.1 三公理与字段所有权（取代世代补丁模型）

一切设计的根基（承 v2.2 §1，原文为准）：

1. **SSOT**：模型世界的描述只有一份（`~/.acm/config.yaml`），Agent 只是投影目标。
2. **非破坏性**：ACM 只拥有它写入的字段，不拥有整个文件；未管理字段必须无损保留。
3. **精确可逆**：回滚粒度是"ACM 管理的字段的逆操作"，整文件快照仅是灾难恢复兜底。

```
【ACM 强力控制区：Managed Fields】          【宿主自治保护区：Unmanaged Fields】
 base_url / api_key(引用) / model /          permissions / hooks / plugins / mcpServers /
 protocol 方言 / context / reasoning         OAuth token / 会话状态 / 一切其他内容
 100% 确定性写入、幂等收敛、字段级回滚        AST 解析树级零破坏保留
 外部修改 = Drift → 显式阻断写入             允许 Agent 运行时自由并发修改
```

为什么 v1.0 的世代快照树必然失败：Agent 配置文件是**双重权威文件**——ACM 想让连接字段严格演进，Agent 运行时却在同一文件持续写入状态。整文件世代回滚会把窗口期内 Agent 刚写入的 OAuth 刷新、会话记录一并打丢；Agent 升级重构文件结构后，历史 patch 路径全部失效。字段所有权模型从根上消除这个冲突：**受管字段 100% 绝对可控，未受管内容 100% 零破坏**，两者不再争夺同一份文件的整体版本权。

### 3.2 数据流与安全写入管道

```
config.yaml (SSOT, schema v3)
  → load/validate (pydantic, extra=forbid)
  → resolve_profile()        # ${ENV} 实时解析；失败 = 硬错误，零写盘
  → adapter.plan()           # 纯函数：字段级期望值 + 投影损失告警；适配器永不碰磁盘
  → write_changeset()        # Safety Engine 六步管道（唯一写盘路径）
  → last_write.json / journal.jsonl
```

Safety Engine 六步：① 白名单路径/命名空间校验 → ② 写前整文件快照（append-only）+ op 展开 → ③ 内存中编辑 + 语法自检 + AST 非破坏断言 → ④ SHA-256 指纹复核（防 TOCTOU）→ ⑤ 原子 `os.replace` → ⑥ last_write 更新。全局非阻塞 flock 防并发。

### 3.3 目录结构（v1.1 定稿，取代 v1.0 的 history/gen 树）

```
~/.acm/
├── config.yaml                     # SSOT：providers(L1, 内嵌 models L2) → profiles(L3)
│                                   #   schema v3；profile 两正交轴：default(驱动默认模型) + models(成员注册)
└── state/                          # 运行时状态，永不写回 config.yaml（数据模型不变量 1）
    ├── .lock                       # 全局非阻塞排他写锁
    └── <agent>/
        ├── last_write.json         # 最近成功投影的 profile、受管字段落盘值（漂移检测数据源；journal 上线后废止）
        ├── journal.jsonl           # （触发式）事务日志：txid/timestamp/字段级变更，字段级回滚数据源
        └── snapshots/<txid>/       # 每次物理修改前的整文件原样备份，append-only，只读审计 + 灾难恢复
```

### 3.4 状态机与退出码（不变）

六状态：`SYNCED / OUT_OF_SYNC / DRIFTED / ERROR / UNMANAGED / NOT_DETECTED`（优先级 ERROR > DRIFTED > OUT_OF_SYNC > SYNCED）。退出码：`0` 成功/no-op · `1` 配置错误 · `2` 安全阻断（漂移/写锁/白名单）· `3` I/O 失败 · `4` 未找到 · `130` SIGINT。stdout 走正常输出，stderr 走错误告警。

### 3.5 三条语义铁律（承 v2.2 §4.3，v1.1 重申）

1. **漂移没有自动修复路径**：受管字段被外部改动 → 默认阻断一切写入，`--force` 或先 `diff` 确认，绝不静默收敛。
2. **投影损失显式告警**：Desired State 中目标 Agent 无法表达的字段（如 Pi 无 registry 通道时其他成员模型），必须 stderr 聚合告警，绝不静默丢弃。
3. **批处理独立性**：批量投影按 Agent 独立执行，单个 Agent 阻断不回滚其他 Agent 的成功，最终退出码取最高严重级。

### 3.6 受管面纪律：字段 80/20 裁定与机制预算（rev.2 新增）

80% 的诉求是"切换请求去向"。magpie 的 1 键切换面是**网关代偿的结果**——连接字段被常驻网关一次性冻结；ACM 直连模式下同一诉求 = **4~6 字段原子束**（`base_url + api_key + model + 协议方言/wire_api (+ effort)`，见三适配器 plan() 实际写入清单），少任何一个直连切换都不成立；VMR 模式下切换面同样自然收敛到 model 单键。据此逐字段裁定：

| 字段 | 裁定 | 理由 |
|---|---|---|
| `context_window` / `max_tokens` | 灰色，**schema-only** | 换模型档位时确实要跟着变（直连正确性的一部分），但无专属机制 |
| `reasoning.budget_tokens` | 缓刑，schema-only | 目前仅产出投影损失告警，无任何 agent 通道消费 |
| `temperature` | **最弱的一个**，schema-only | 范围测试勉强过；schema 载体成本 O(1)，砍掉收益也是 0 |
| `org_id` / `headers` / `proxy` | 保留，schema-only | 企业中转/内网代理的少数派真需求；无任何专属机制 |
| 能力位（vision/tools/json_mode/thinking） | **最像 20% 的候选** | 只有 Pi 注册通道消费且部分仅产出告警；本质是注册元数据而非切换变量 |
| 成员注册（profile `models:`） | 20%，但有存在理由 | 只为 Pi 的 `defaultProvider` 不悬空（投影完整性），非切换语义；对 Claude/Codex 仅以告警存在 |

**纪律（约束后续一切演进）**：能力位、成员注册、temperature 三者**永不获得专属机制**——不进命令、不进状态文件、不进写路径，只在 schema 与告警中存活；任何人为它们加功能的提议，先过触发表并回答"80% 用户换 provider 时动它吗"。同时保持清醒：**schema 宽度的维护成本是 O(1)，机制的维护成本才是 O(n)**——检验对象永远是机器的重量，不是字段的数量。

---

## 四、差异化护城河（v1.1 的产品论点）

v1.0 的护城河是"不破坏你的文件"。2026 年这已是 magpie 的入场券（"changes only that one key, comments stay as they were"）。v1.1 的护城河升级为五点，每点都对应一个 magpie 结构性给不了或不愿给的保证：

### 4.1 护城河与机制对应

| 护城河 | 机制 | magpie 为什么不给 |
|---|---|---|
| **零守护进程** | 按需 CLI，跑完即退；无常驻内存、无自更新、无后台端口 | magpie 的价值锚在常驻网关，结构性不可能放弃 resident 进程 |
| **SSOT-as-code** | 一份 YAML，可 git 版本化、可 diff、可团队共享（Phase 3 overlay） | magpie 的配置在应用内部数据库/UI 状态里，不可 review |
| **漂移显式阻断** | 受管字段被外部改动即 DRIFTED + 阻断写入，永不静默覆盖 | 直改工具天然假设"我写的就是对"，无外部漂移概念 |
| **字段级精确回滚** | 回滚 = 管理字段的逆操作；Agent 窗口期写入的状态存活 | 整文件/整键快照恢复会连带打丢宿主后续写入 |
| **凭据零保管** | 只存 `${VAR}` 引用，输出默认掩码，明文 opt-in | 订阅共享路线必须托管登录态与 token 池 |

一句话定位：**ACM 是唯一把"模型配置"当作受版本控制的代码来治理的工具，而不是又一个改配置的 GUI。**

### 4.2 存在理由：ACM = VMR 的配置面（L0 front door），不是通用切换器（rev.2 新增）

**对 80% 的诉求（给各 Agent 换模型），magpie 已经解决得足够好、体验更好。若 ACM 的自我定位是"更好用的配置切换器"，应该立即停——那是 cc-switch 的谨慎版、magpie 的残血版，没有独立价值。** ACM 剩余的存在理由建立在一个结构性事实上：

**「magpie 里配一个指向 VMR 的 Provider」不是等价方案**。链路变成 `Agent → magpie 网关（协议翻译/请求改写/会话归属/路由决策） → VMR → 上游`，而 magpie 不是一段中立导线：① VMR 的 **Byte-Faithful 零翻译透传**对已被 magpie 加工的流量无意义；② 会话连续性被 magpie 的路由/failover 重组，**Prompt Cache 亲和策略互相打架**；③ VMR 的 audit.jsonl 记到的是 magpie 的代理流量而非真实客户端行为，**法医审计失真**；④ 双层 failover 冗余，故障路径不可推理。**在乎 VMR 存在意义（透传/亲和/审计）的用户，要把 N 个 Agent 指向 VMR 且不引入第二个常驻枢纽，唯一方式就是一个纯配置面工具——这正是 ACM。**

存在条件等式：**ACM 值不值得存在 ≡ VMR 值不值得存在。** 服务三个人群（规模均诚实标注）：VMR 用户（小而高粘，与 VMR 同频）；零常驻极简派（直连官方 API、不愿为切模型跑一个下载 Bun 带插件生态的常驻应用；真实存在，转化靠信任创伤而非功能）；团队/CI GitOps 场景（话语存在、产品空白、付费意愿完全未验证——Phase 3，不押注）。

**经营姿态：不投入，不杀死，重新定位。** MVP 已交付且触发表纪律意味着维护成本接近零，处于正确的 park 状态。**死亡条件（满足任一即归档，沉没成本≈0）**：① VMR 的透传/亲和差异化被上游厂商原生解决；② 自用停用 VMR；③ magpie 提供"对指定 provider 透明直通"模式。届时 ACM 连配件价值也不存在。同时把与 magpie 的关系（含双网关串联问题）诚实写入 README，帮 VMR 目标用户避开错误链路。

---

## 五、界面层与语言栈路线（rev.2 修订）

v1.0 用整章论证 Go + Wails v3 菜单栏面板，这在当时是对的直觉（UI 是抢占心智的关键），但顺序错了：**界面层的价值完全依附于核心语义的确定性**。在漂移阻断、字段回滚、投影告警这些语义稳定之前做 GUI，只会把破坏性写操作包上漂亮的皮。

**市场证据对 v1.1 原判断的修正**：CC Switch 靠 GUI+托盘拿到 89K stars；aisw 做完 CLI 立刻补 Desktop alpha——**交互入口本身是采用驱动因素，不是附属品**。但两点制衡：ACM 的核心语义与 GUI 存在张力（"漂移默认阻断"必须翻译成"阻断 → 展示 diff → 显式 force 确认"的交互流，与 switcher 用户要的"一键"冲突，这是产品层面的真实冲突）；且 ACM 的治理生态位（团队/CI/GitOps）本来就是 CLI-native 场景。据此：**`acm tui` 触发优先级上调**（§6）；GUI 维持触发式 + `--json` 薄投影层不变。

### 5.1 语言栈评估：Python 何时是障碍（2026-10 实测 + 评估）

| 维度 | 评估 | 裁定 |
|---|---|---|
| 运行环境 | `uvx` 可自举托管 Python（无 Python 环境自动下载），目标用户（已装 coding agent 的开发者）门槛≈0；摩擦仅限离线/受控环境与首启下载等待 | **不构成障碍** |
| 运行速度 | 实测 `acm --help` 全程 0.23s（typer/pydantic 导入 0.11s）；配置切换是低频操作；常驻内存劣势（~50-80MB vs Go ~15-30MB，经验值）仅在被"零守护进程"架构排除的 GUI 场景激活 | **不构成障碍** |
| UI 绑定 | **Python 真短板**：PySide6 重、PyInstaller 产物 30-80MB、macOS 公证繁琐；TUI 例外（Textual 一流）。缓解：界面层被定义为 `--json` 之上的薄投影层，**若 GUI 真触发，可为独立进程/独立语言（Go/Wails 或 Tauri），语言选择不传染核心** | TUI 零障碍；GUI 时换语言 |
| 分发 | 相对 Go 单二进制（10-20MB、交叉编译、签名公证、自更新）是明确劣势；PyPI/uvx 对目标人群命中率极高 | **劣势但有分级缓解**，且在触发表后面 |

**总裁定**：当前产品形态（CLI、零守护、触发式 TUI）下 Python 不是障碍。核心语义语言无关（纯函数 plan() + Safety Engine + 金样门禁），**预防性重写无证据支持（YAGNI）**；若未来分发摩擦被真实数据证实为采用瓶颈，Go/Rust 重写核心是可行的收尾动作——由需求侧证据触发，不由预测触发。

v1.1 的界面路线：

```
Phase 2  acm --json          # 机器可读输出：一切界面的前置条件（已列入 v2.2 Phase 2）
触发项 1  acm tui             # 终端全功能面板（参考 magpie tui 验证过的可行性）：
                             #   Agent 状态总览 + Profile 切换 + diff/rollback 入口；纯 Python（Textual 类），零原生依赖
触发项 2  菜单栏/托盘面板      # 仅当 TUI 验证了交互模型且出现真实常驻需求；
                             #   形态收敛为 v1.0 设想的"状态总览 + 下拉切换 + 一键回滚"三件事，
                             #   且只是 acm --json 之上的投影层，不内嵌任何业务逻辑
```

触发条件（并入 §6 触发表）：TUI 在"多 Agent 混合绑定 + 漂移排查"成为日常工作流之后；GUI 在 TUI 交互模型稳定且有用户明确要求常驻入口之后。v1.0 的 GUI 技术选型对比表（Wails/Tauri/Flutter/Electron）整体作废——届时若真做 GUI，技术栈在当期重新评估，此处不留过期结论。

---

## 六、落地路线图（v1.1 定稿：触发式，不排期）

承 v2.2 §7：完整命令面是终局语义，交付按触发分片；公理级语义（非破坏、显式暴露、可逆）在任何分片都不可降级。

**已交付（MVP v0.3.x，schema v3）**：`init`（含 VMR 探测）/ `status` / `use` / `rollback`；全局 `--dry-run --force --verbose --show-secrets --no-color`；Safety Engine 六步管道；Claude Code / Codex / Pi 三适配器（含 Profile 成员注册 + opt-in 默认投影）；金样 + 故障注入门禁。

**Phase 2（原则已定，待启动）**：Aider / Gemini CLI / OpenCode 适配器；`acm bind`（Agent 级绑定）；`--json`。

**v1.1 新增触发项**（并入 v2.2 §7 触发表，按真实需求启动）：

| 能力 | 触发条件 | 来源 |
|---|---|---|
| `acm tui` | **优先级上调（rev.2）**：多 Agent 管理或漂移排查出现真实重复需求即可启动（市场证据：交互入口本身是采用驱动因素） | §5 / magpie tui / CC Switch 89K stars |
| 菜单栏/托盘面板 | TUI 交互模型稳定 + 常驻入口的真实诉求 | §5 / v1.0 原设想 |
| `acm import agents`（从本机 Agent 现有配置反向生成 config.yaml 草案） | 新用户从 CC Switch / magpie / 手工配置迁移的诉求真实出现；明文密钥必须转 `${ENV}` 引用或显式 opt-in，且仅生成提案确认后落盘 | §2.1 / magpie import |
| 模型目录外源化（实时拉取厂商/VMR 模型列表辅助补全） | `import vmr` 上线后手工维护模型清单成为痛点 | §2.1 / magpie models.dev |
| 端点连通性 opt-in 干跑（`acm doctor` 的一部分） | 真实"切完配置 Agent 起不来"故障出现，且 doctor 触发条件同时满足 | v1.0 原则 4 |
| `acm set <agent> <field>`（受 SSOT 约束的单字段直改） | 一次性改单字段的诉求重复出现，且先回答该字段是否应入 config.yaml | §2.1 / magpie 直改交互 |

**永久不做**（v1.1 重申，含 magpie 已证明商业可行的部分）：网关/路由/故障转移、订阅共享与账号池、用量成本追踪、MCP/Skills/Prompts/插件管理、动态加载的适配器 DSL、GUI 全家桶、闭源 IDE 私有数据库写入。

---

## 七、未验证假设与风险

1. **存在性风险（rev.2 重写）**：ACM 作为独立通用切换器无生存空间（magpie 已覆盖 80% 且体验更好，CC Switch 占据大众心智）；其存在理由收敛为 VMR 配置面（§4.2），**生死与 VMR 绑定**。死亡条件见 §4.2，满足任一即归档，不做沉没成本椌护。市场风险的对冲不再是"竞争"，而是"绑定 VMR 差异化 + 诚实定位"。
2. **上游 schema 漂移**：Agent 厂商无义务保持配置格式稳定；当前靠金样 fixtures 作哨兵 + ERROR 态阻断兜底，适配器数量增长后此维护成本线性上升，是 Phase 2 扩适配器前必须正视的约束。
3. **v2.2 触发表与本文新增触发项的合流**：§6 新增项需在下一次 v2.2 文档回写时并入其 §7 触发表，保持单一权威源；在那之前以本文为准。
4. **TUI/GUI 的范围测试**：界面层本身不违反范围测试（它不改变任何字段语义），但历史上所有"顺手加一个功能"的破坏都发生在界面层；触发时须在治理文档中明确"界面层只读投影 + 白名单动作入口"的约束。
5. **文档合流（rev.2 新增）**：本文 §2.4/§2.5/§3.6/§4.2/§5.1 及 §6 触发表修订，需在下一次 v2.2 文档回写时择要并入治理规格（尤其 §3.6 受管面纪律与 §4.2 存在条件），保持单一权威源；在那之前以本文为准。事故实证（cc-switch #1198/#3631/#6875 等）可在 README 中以克制措辞引用，作为存在必要性的手素材。
