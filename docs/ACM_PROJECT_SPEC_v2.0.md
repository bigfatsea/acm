# ACM（Agent Config Manager）项目规格 v2.0（原则版）

<!-- Version: 2.0.0 | Status: Governing Spec | Date: 2026-08-17 -->
<!-- 本文档是 ACM 项目的治理性规格（governing spec），只保留四样东西：
     核心原则、边界定义、核心数据模型、命令语义。
     实现层面的细节（事务提交步骤、数据结构字段、状态机优先级、交互文案、
     目录布局、适配矩阵明细、竞品核查、历史裁决）全部下沉至
     docs/ACM_PROJECT_SPEC_FINAL_v1.1.md（降级为实现参考，implementation reference）。
     两者冲突时，以本文档的原则为准；实现参考与原则冲突时，改实现参考。 -->

> **文档性质**：对齐认知、防止走偏。不是照着抄代码的手册。
> 编码阶段在本文原则框架内自由发挥；任何实现选择，只要不违反本文原则，均为合法。

---

## 1. 定位与核心原则

**ACM 是"模型配置"的单一事实源（SSOT）与投影引擎**：用户在 ACM 中维护一套与 Agent 无关的 Provider/模型配置，通过一条命令安全地投影到本机任意 Coding Agent 的配置文件中，并可精确、无损地回滚。

三条公理，一切设计的根基：

- **公理 1（SSOT）**：模型世界的描述只有一份，Agent 只是投影目标。
- **公理 2（非破坏性）**：工具只拥有它写入的字段，不拥有整个文件。未管理字段必须无损保留。
- **公理 3（可逆性）**：任何变更必须可精确撤销，回滚粒度是"ACM 管理的字段"而非整个文件。

贯穿性原则：**ACM 管理的是字段，不是文件**。一切"ACM 不知道的事"（外部修改、无法表达的字段、并发与崩溃）都必须**显式暴露，绝不静默处理**。

技术栈基线（决策依据见 v1.1 §6）：Python 3.12+，最小依赖；适配器 = 普通 Python 模块（不是 DSL）；Core Config 用 TOML；分发主路径 PyPI / uvx。

---

## 2. 边界定义

### 2.1 判定原则

> **凡是"换了 Provider/模型之后理应保持不变的东西"，ACM 一律不碰。**

### 2.2 管什么（In Scope）

- **L1 连接与凭据**：base_url、protocol 方言、api_key（仅存 credential **引用**，不存密钥）、org_id、headers、proxy。
- **L2 模型规格与行为**：模型选择（含角色模型）、context window、max output tokens、reasoning、temperature、能力位。
- **Profile 管理**：多 Profile、激活态、回滚、diff。MVP 仅全局单一激活 Profile；支持向后兼容的分层配置演进（团队 Base SSOT + 本地个人 Overlay 覆盖，纯环境变量引用，零密钥入库）。
- **VMR 集成**：第一方集成，非架构依赖（无 VMR 时一切功能照常）。

### 2.3 不管什么（Out of Scope）

- MCP servers、Tools、Skills、Prompts、权限许可、hooks、plugins——坚决不碰。
- 账号轮转 / OAuth token 池 / 额度监控。
- 本地代理 / 网关 / 请求改写（VMR 的领域）。
- Secret storage（只存 `${ENV}` 引用，不做密钥保管）。
- Agent 启动包装、GUI / TUI。

### 2.4 铁律（刚性约束）

1. 绝不触碰 MCP、插件、Skills、系统提示词、权限配置、Agent 运行时状态文件。
2. 绝不写入闭源 IDE 私有数据库；没有公开、稳定、可安全修改的配置接口，就不支持该 Agent。
3. 任何新功能先过 §2.1 判定，不过即拒，无论需求来自谁。
4. ACM 的写入只落在适配器声明的管理路径上，由安全引擎强制校验（白名单 + 黑名单）。
5. 反面界定（出现任一即已走偏）：变成 GUI 全家桶、写私有数据库、适配器数量成为 KPI、Core Config 堆积状态或密钥保管职责。

---

## 3. 核心数据模型

### 3.1 概念实体与关系

```
Core Config（~/.acm/config.toml，SSOT）
  providers ──> models ──> profiles        # 三层声明式配置，仅存可版本控制内容
       │
       ▼  解析（ENV 引用实时求值）
ResolvedProfile
       ▼  Adapter 编译（纯函数，不碰文件）
Desired State（字段级期望状态）
       ▼  Safety Engine 收敛写入
Current State（各 Agent 配置中管理字段的实际落盘值）
```

关键概念（完整术语表见 v1.1 附录 C）：

| 概念 | 定义 |
|---|---|
| **Desired State** | 激活 Profile 经 Adapter 编译后的字段级期望状态 |
| **Current State** | 管理字段在磁盘上的实际值 |
| **Drift（漂移）** | Current ≠ ACM 最后写入值（被外部修改） |
| **Projection Loss** | Desired State 中目标 Agent 无法表达的字段；必须显式告警，不得静默丢弃 |
| **ChangeSet** | Adapter 产出的字段级变更集，Safety Engine 的**唯一输入**；含投影告警与黑白名单声明 |

### 3.2 Credential 引用（Core Config 不承担 secret storage）

- 引用语法仅 `${VAR}` 与 `${VAR:-default}` 两种，整字段替换，不支持子串插值与嵌套。
- 投影时实时解析；引用无法解析 = **硬错误，任何文件写入发生之前整体中止**。
- 明文存储是单机合法选择（CLI 输出始终默认掩码，不持续骚扰告警；仅在团队共享配置或文件权限异常时提示）。

### 3.3 回滚与状态数据模型

- **Journal（事务日志，`~/.acm/state/<agent>/journal.jsonl`）**：状态区唯一的事务持久化 SSOT，记录每次 ChangeSet 事务历史（txid、timestamp、profile、ops 字段级变更），作为字段级精准回滚的数据来源。
- **Snapshot（安全快照，`~/.acm/state/<agent>/snapshots/<txid>/`）**：每次物理修改前对原文件的全量原样备份，单纯追加留存（Append-only，写路径零轮转计算复杂度），用于灾难恢复（`--hard`）与只读比对。
- **Manifest（所有权视图）**：作为内存派生视图（Derived View）存在，从当前配置与 Journal 动态推导，不单独在磁盘双写持久化文件。

回滚语义分层：**字段级回滚（默认，Journal 逆操作）→ 整文件快照恢复（--hard 灾难救砖）**。

### 3.4 数据模型不变量（实现的硬约束）

1. 配置与状态分离：一切运行时状态（active profile、journal、snapshots）只存在于 state 目录，**不得写回 config.toml**。
2. Adapter 只做编译（profile → ChangeSet），**一切磁盘写入由 Safety Engine 统一执行**。适配器在架构契约上不授予写盘权限，由单元测试与金样门禁强制约束。
3. 写入必须原子与防并发：全局排他写锁（file lock）+ 临时文件原子替换（`tempfile` + `os.replace`），写前单纯落盘 snapshot，无需引入沉重的 WAL/2PC 中间状态机；在写锁内基于 AST 直接修改受管字段（未管理字段语义级原样保留），消除 TOCTOU 与并发冲突。
4. 非破坏性保证分两级诚实声明：未管理节点**语义级不变**（硬承诺）；注释/键序/排版保留按金样 fixture 界定。不承诺"100% 保留"。
5. 敏感内容全链路防护：state 目录 0700，输出默认掩码，明文 opt-in。
6. 幂等：期望值 == 当前值且无漂移 → no-op，退出码 0。

---

## 4. 命令语义

### 4.1 状态语义

每个 Agent 的状态由**配置主状态**唯一表征（互斥枚举，反映落盘数据真实对齐情况）：
`[SYNCED | OUT_OF_SYNC | DRIFTED | ERROR | UNMANAGED | NOT_DETECTED]`

- `SYNCED`：目标配置与当前激活 Profile 完全一致且无漂移；
- `OUT_OF_SYNC`：ACM 中 Profile 已变更或尚未投影；
- `DRIFTED`：受管字段被外部（手动或 Agent 运行时）篡改；
- `ERROR`：目标配置文件语法损坏或权限异常；
- `UNMANAGED`：检测到 Agent 但 ACM 尚未管理其配置；
- `NOT_DETECTED`：本机未安装该 Agent。

不引入高误判、高平台兼容成本的外部进程扫描阻断机制；写操作通过排他写锁与原子替换自然保障并发安全。

### 4.2 命令总表（语义，非界面规格）

```bash
acm init                    # 扫描 Agent + 探测 VMR + 展示提案 + 确认后生成 config.toml；
                            #   交互式下绝不静默修改与破坏现有配置（--force 显式重新生成）
acm status                  # 各 Agent 状态 + 漂移 + 投影告警摘要
acm doctor                  # 诊断一切异常（配置语法、引用缺失、漂移、权限异常）
acm use <profile>           # 改变 Desired State（换激活 Profile）并立即投影；遇漂移默认阻断
acm apply [<agent>]         # Current -> Desired 的幂等收敛（缺省全部）；漂移同样默认阻断
acm diff [<agent>]          # Current vs Desired / vs 快照（--against-snapshot），漂移专项标注
acm history [<agent>]       # 最近事务日志查看
acm rollback [<agent>]      # 字段级回滚（默认上一次事务，--to-tx 指定）；
                            #   --hard [--snapshot <id>] = 整文件快照灾难恢复（参数显式分离，杜绝多态混淆）
acm release [<agent>]       # 解除 ACM 托管，清空状态记录；物理文件原地保留（若为 ACM 全新创建且无用户内容的文件则安全清理）
acm import vmr              # 拉取 VMR 虚拟模型，增量合并进 config.toml

# 全局：--dry-run / --force / --verbose / --no-color / --show-secrets（明文密钥 opt-in） 语义自明
```

### 4.3 语义不变量

1. **漂移没有自动修复路径**：任何写入命令遇外部漂移默认阻断，`--force` 或先 `diff` 确认，不存在静默收敛。
2. **`use` 与 `apply` 语义不混淆**：use 改变 Desired State 并收敛；apply 只收敛不改变。
3. **退出码规范**：0 = 成功/幂等 no-op；1 = 错误（配置错误/语法损坏/I/O异常）；2 = 安全阻断（检测到漂移/写锁冲突）。正常结果走 stdout，错误警告走 stderr。
4. 投影损失必须在 use/apply/diff/status 输出中聚合展示。
5. 成功路径硬标准：VMR 用户从装好到本机 3+ Agent 全部指向虚拟模型，≤ 3 条命令、零手工编辑；`release` 后清爽解除托管。
6. **跨 Agent 批处理原则**：批量投影按 Agent 独立执行，任一 Agent 发生错误或阻断时，在 stderr 明确指出失败 Agent，命令最终返回对应非零退出码，已成功的 Agent 保持生效。

---

## 5. 适配器与 Agent 覆盖

- **Adapter 契约**：每 Agent 一个普通 Python 模块，实现 detect / config_paths / plan 三个职责（运行时彻底零 I/O，verify 职责下沉至金样单测门禁）；plan 为纯函数，产出 ChangeSet + 投影告警。所有官方与社区适配器统一作为代码内置（Built-in），拒绝动态代码反射执行的安全隐患。
- **P0 = Claude Code、Codex、Pi**（真实使用优先；三者在格式/文件数/投影形态上覆盖架构充分性）。Aider 为 P1 首位（YAML + 角色模型压力测试）。明细见 v1.1 §8 适配矩阵（活文档）。
- 新增适配器 = 源码内置模块 + 独立金样 fixtures 门禁合并；"支持更多 Agent"永远不是目标本身。
- **上游多版本演进原则（先从简，后扩展）**：MVP 适配器仅面向当前最新稳定版单一路线实现；遇未知/破坏性 Schema 变动置 `ERROR` 态安全阻断，绝不盲写破坏文件。未来出现广泛新老版本共存诉求时，仅在单个 Agent 模块内部引入基于 AST 结构特征的策略分发，核心引擎与 Protocol 契约零改动。

## 6. 质量原则（验收的精神，非用例清单）

1. **金样回归**：每适配器配真实感 fixtures；正向三步断言（Apply 正确 / 非管字段无损 / 回滚后 Agent 期间写入的状态存活）。
2. **故障注入**：黑名单触碰、多文件中途失败、提交间隙 SIGKILL、外部并发篡改、ENV 缺失、双进程锁竞争——安全机制必须有负面测试背书。
3. Format Writer 的 round-trip 保真能力单测先于任何适配器交付。
4. 金样 fixtures 同时充当上游 schema 漂移哨兵。

## 7. 路线图（粒度：里程碑，非任务分解）

- **Phase 1（MVP）**：Core / Safety Engine / Format Writers / Adapter Protocol 框架 + P0 三适配器 + 全命令 + PyPI 发布。
- **Phase 2**：Aider / Gemini CLI / OpenCode 适配器；`acm bind`（Agent 级绑定）；`--json`。
- **Phase 3（触发式）**：brew tap / pyapp / 社区适配器流程——仅出现真实需求时启动。

## 8. 文档关系

| 文档 | 角色 |
|---|---|
| **本文档（v2.0）** | 治理规格：原则、边界、数据模型、命令语义。变更需慎重，原则不随实现摇摆。 |
| v1.1（ACM_PROJECT_SPEC_FINAL_v1.1.md） | 实现参考：事务协议细节、数据结构、状态机、文案、矩阵、附录裁决与核查。实现可偏离其中细节，前提是不违反 v2.0 原则；偏离积累后回写更新。 |
| feedback-for-v1.0.md 等 | 历史过程文档，仅存档。 |

<!-- 规格冻结于原则层。下一步最有价值的信息来自把三个真实适配器在 Safety Engine 上跑起来。 -->
