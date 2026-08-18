# ACM 规格说明书（v2.0 vs v1.1）一致性、Gap 与错误分析报告

> **分析对象**：
> - 治理性规格：`docs/ACM_PROJECT_SPEC_v2.0.md`（以下简称 **v2.0**）
> - 实现参考：`docs/ACM_PROJECT_SPEC_FINAL_v1.1.md`（以下简称 **v1.1**）
>
> **基本定位**：v2.0 为**治理规格**（原则、边界、核心数据模型、命令语义），v1.1 为**实现参考**（事务细节、数据结构、适配矩阵、文案与历史裁决）。原则上发生冲突时以 v2.0 为准。

---

## 目录

1. [核心发现概览](#1-核心发现概览)
2. [矛盾与不一致项分析及裁决建议](#2-矛盾与不一致项分析及裁决建议)
   - [2.1 `acm use` 命令签名与单 Agent 语义冲突](#21-acm-use-命令签名与单-agent-语义冲突)
   - [2.2 `acm diff` 参数规范与比对维度不一致](#22-acm-diff-参数规范与比对维度不一致)
   - [2.3 分层配置（Base SSOT + Overlay）的范围界定与路线图脱节](#23-分层配置base-ssot--overlay的范围界定与路线图脱节)
   - [2.4 跨 Agent 批量操作时的错误聚合与退出策略](#24-跨-agent-批量操作时的错误聚合与退出策略)
   - [2.5 事务时序极端崩溃窗口与 `apply` 幂等自愈的逻辑矛盾](#25-事务时序极端崩溃窗口与-apply-幂等自愈的逻辑矛盾)
   - [2.6 Phase 2 辅助命令在 v2.0 中的遗漏](#26-phase-2-辅助命令在-v20-中的遗漏)
   - [2.7 `release` 局部清理 vs 全局清理的边界界定](#27-release-局部清理-vs-全局清理的边界界定)
3. [已达成高度一致的关键维度](#3-已达成高度一致的关键维度)
4. [修改与行动建议汇总清单](#4-修改与行动建议汇总清单)

---

## 1. 核心发现概览

经逐行比对，两份文档在核心架构、公理原则、安全哲学（字段所有权、非破坏性、Append-only 快照、内存派生 Manifest、内置适配器 Protocol）以及状态机枚举和退出码上高度一致。

但两份文档在**命令参数语法、分层配置定义、极端崩溃时序自愈逻辑、批处理流程细节**等处存在 7 处不一致、Gap 或潜在逻辑瑕疵。

---

## 2. 矛盾与不一致项分析及裁决建议

### 2.1 `acm use` 命令签名与单 Agent 语义冲突

#### 问题现象
- **v1.1（§10.1 & §12）**：定义签名 `acm use <profile> [<agent>] [--dry-run] [--force]`，并在 Phase 2 说明中称 `acm use <profile> <agent>` 为“一次性投影”。
- **v2.0（§4.2 & §4.3）**：定义签名 `acm use <profile>`（无 `<agent>` 参数），并在 §4.3.2 强调“`use` 改变 Desired State 并收敛；`apply` 只收敛不改变”。

#### 深度分析
1. 若 `use` 允许跟 `<agent>`，存在两种可能的语义解构，均会打破概念正交性：
   - **解构 A**：全局 Active Profile 变更为 `<profile>`，但仅收敛写入该 `<agent>`。这会导致其他已检测 Agent 瞬间进入 `OUT_OF_SYNC` 状态，违背用户直觉。
   - **解构 B**：不改动全局 Active Profile，仅将 `<profile>` 单次覆盖投影到该 Agent。这直接破坏了“`use` 必然改变 Desired State”的核心语义，且与 Phase 2 的 `acm bind <profile> <agent>`（持久绑定）产生混淆。
2. 投影到特定 Agent 的收敛职责应由 `acm apply [<agent>]` 承担；持久指定特定 Agent 的模型应由 `acm bind <profile> <agent>` 承担。

#### 裁决与建议
- **以 v2.0 为准**。
- **建议**：
  1. `use` 命令移除 `[<agent>]` 位置参数，统一为 `acm use <profile>`（全局切换 Desired State 并收敛到全部检测到的 Agent）。
  2. 若用户只需收敛单个 Agent，使用 `acm apply <agent>`。
  3. 修改 v1.1 §10.1 与 §12 中有关 `acm use <profile> <agent>` 的描述，消除多态歧义。

---

### 2.2 `acm diff` 参数规范与比对维度不一致

#### 问题现象
- **v1.1（§10.1）**：采用枚举选项 `acm diff [<agent>] [--against desired|last-write|snapshot]`（默认 `desired`）。
- **v2.0（§4.2）**：采用布尔开关 `acm diff [<agent>]`（说明中提及 `--against-snapshot`）。

#### 深度分析
1. 在 ACM 字段生命周期中，存在三个关键比对基准：
   - `desired`：当前磁盘落盘值 vs 激活 Profile 编译后的目标期望值（回答“如果 apply 会改什么”）；
   - `last-write`：当前磁盘落盘值 vs ACM 上次写入值（回答“外部或 Agent 自身在未托管期间改了什么”，是诊断 `DRIFTED` 的唯一精准依据）；
   - `snapshot`：当前磁盘落盘值 vs 物理快照原样字节（用于 `--hard` 救砖前的全量差异取证）。
2. v2.0 的 `--against-snapshot` 布尔开关丢弃了 `--against last-write` 维度，使得用户在遭遇 `DRIFTED` 阻断时无法直接 diff 外部漂移内容。

#### 裁决与建议
- **以 v1.1 的枚举设计为准**（v1.1 的设计在功能完备性上更优，且符合 CLI 最佳实践）。
- **建议**：
  1. 将 v2.0 §4.2 中的 `--against-snapshot` 修正为 `--against desired|last-write|snapshot`（默认 `desired`）。

---

### 2.3 分层配置（Base SSOT + Overlay）的范围界定与路线图脱节

#### 问题现象
- **v2.0（§2.2）**：在 In-Scope 中写入“支持向后兼容的分层配置演进（团队 Base SSOT + 本地个人 Overlay 覆盖，纯环境变量引用，零密钥入库）”。
- **v1.1（§5.2 & §12）**：仅在 §5.2 提及“项目级 Profile（repo 内 `.acm/`）明确不进 MVP，作为 P3 开放问题评估”，未在配置模型（§7.3）和实施路线图（§12）中对 Base + Overlay 进行任何设计与排期。

#### 深度分析
1. 团队 Base SSOT + 本地个人 Overlay（类似 `config.toml` + `config.local.toml` 或仓库级 `.acm/`）是高级企业/团队协作诉求。
2. MVP 阶段必须保持单一事实源 `~/.acm/config.toml`，避免过早引入配置层叠与继承算法复杂度。
3. v2.0 在治理规格中提出此概念，但未标明阶段，容易导致实现期误将其当作 Phase 1/Phase 2 范围。

#### 裁决与建议
- **两者互补，但需明确阶段定位**。
- **建议**：
  1. 在 v2.0 §2.2 与 §7 路线图中明确标注：分层配置（Base + Overlay / 项目级 `.acm/`）属于 **Phase 3（开放问题评估）**，MVP 与 Phase 2 严格维持单机单一 `~/.acm/config.toml`。
  2. v1.1 附录中补充 Base + Overlay 的架构演进备忘，避免概念断层。

---

### 2.4 跨 Agent 批量操作时的错误聚合与退出策略

#### 问题现象
- **v2.0（§4.3.6）**：明确定义“跨 Agent 批处理原则：批量投影按 Agent 独立执行，任一 Agent 发生错误或阻断时，在 stderr 明确指出失败 Agent，命令最终返回对应非零退出码，已成功的 Agent 保持生效。”
- **v1.1（§7.5.1 / §10.2）**：在描述事务提交与退出码时，均使用单 Agent 视角（“任一违反即中止，退出码 2”），未在流水线流程（§7.1）与提交算法（§7.5.1）中描述多 Agent 循环迭代时的错误聚合机制。

#### 深度分析
1. 当执行 `acm use` 或 `acm apply` 且未指定 `<agent>` 时，ACM 会遍历本机所有已检测的 Agent。
2. 若 Agent A 成功，Agent B 遭遇外部漂移阻断（Drift Block）：
   - 策略 1（Fail-fast）：遇到 Agent B 立即中断，Agent C 不被处理。
   - 策略 2（Continue-and-Aggregate）：Agent A 成功生效，Agent B 阻断报错于 stderr，继续处理 Agent C；全部结束后返回退出码 2。
3. v2.0 明确采纳策略 2（更适合 CLI 批量运维）。v1.1 缺少该循环控制层的伪代码/流程说明。

#### 裁决与建议
- **以 v2.0 为准**。
- **建议**：
  1. 在 v1.1 §7.1 流水线与 §7.5.1 事务提交流程外层增加“跨 Agent 批处理迭代与错误聚合”说明：单 Agent 失败不中断其他 Agent，汇总所有 Warning/Error 到 stderr，退出码取最高严重级别。

---

### 2.5 事务时序极端崩溃窗口与 `apply` 幂等自愈的逻辑矛盾

#### 问题现象
- **v1.1（§7.5.1 & §7.5.6）**：
  - §7.5.1 提交顺序：先执行 `os.replace` 替换目标配置，再追加写入 `journal.jsonl`。
  - §7.5.6 崩溃恢复断言：“最坏后果是部分文件已更新、部分未更新...随后任意一次 `acm apply` 即幂等收敛至一致状态”。
- **v2.0（§3.4 & §4.3.1）**：
  - §4.3.1 铁律：“漂移没有自动修复路径：任何写入命令遇外部漂移默认阻断，`--force` 或先 `diff` 确认”。

#### 深度分析（逻辑漏洞 / Gap）
1. 设想极端崩溃场景：进程在目标文件 `os.replace` 成功后、`journal.jsonl` 追加前被 `SIGKILL` 终止。
2. 此时：
   - 磁盘文件已是新值（New Value）；
   - 但 `journal.jsonl` 中并无该事务记录（Manifest 派生出的 `FieldOwnership.current` 仍为 Old Value）；
3. 用户随后执行 `acm apply`：
   - Safety Engine 检查磁盘，发现 `Current (New) != ACM 最后写入值 (Old)`；
   - 判定为 **外部篡改（DRIFTED）**；
   - 根据 v2.0 §4.3.1 铁律，`apply` 遇到 Drift 会**默认阻断（退出码 2）**，绝不会“自动收敛自愈”！
4. 此时必须依赖用户传入 `--force`，或者通过 `acm rollback --hard` 恢复快照。

#### 裁决与建议
- **修正 v1.1 §7.5.6 中的自愈描述**。
- **建议**：
  1. 修改 v1.1 §7.5.6 文案，诚实声明：若崩溃发生在 `os.replace` 之后但 `journal` 写入之前，ACM 下次启动会将磁盘变更识别为外部漂移（`DRIFTED`）而安全阻断；用户可通过 `acm apply --force` 确认收敛，或通过 `acm rollback --hard` 回滚快照。消除“无需任何干预直接 `apply` 自动收敛”的不严谨断言。

---

### 2.6 Phase 2 辅助命令在 v2.0 中的遗漏

#### 问题现象
- **v1.1（§10.1 & §12）**：明确定义了 Phase 2 的一组实用命令：
  - `acm profile list | show <name> | create <name>`
  - `acm use-vmr [<model>]`（薄糖层）
  - `acm vmr status`
  - `acm config migrate`
- **v2.0（§4.2 & §7）**：仅在路线图中提及 `acm bind` 与 `--json`，未列入上述命令。

#### 深度分析
1. v2.0 作为治理规格，刻意保持了最小命令集（只列出了核心命令）。
2. 但 `acm profile list/show` 是 CLI 基础易用性命令，`acm config migrate` 是 schema 演进的必要机制。完全不提及会导致治理视角出现命令全貌 Gap。

#### 裁决与建议
- **裁决结论**：**暂不展开，维持现状**。
  - v2.0 聚焦 Phase 1（MVP）核心治理原则，避免过早引入下一阶段辅助命令细节；
  - v1.1 作为实现参考仅供后续开发参考，不作为当前阶段约束。

---

### 2.7 `release` 局部清理 vs 全局清理的边界界定

#### 问题现象
- **v1.1（§7.5.2 & §10.1）与 v2.0（§4.2）**：均定义了 `acm release [<agent>] [--force]`。
- 但对“指定单个 `<agent>`”与“未指定 `<agent>`（释放全部）”在清理文件系统时的差异描述不够清晰。

#### 深度分析
1. 当执行 `acm release codex`（局部释放）：
   - 仅恢复 Codex 的受管字段至接管前状态，删除 `~/.acm/state/codex/`；
   - 全局配置 `~/.acm/config.toml` 与当前激活状态 `~/.acm/state/active` **必须保留**（其他 Agent 仍在受管）。
2. 当执行 `acm release`（全量释放）：
   - 恢复所有已检测 Agent 的配置；
   - 清空 `~/.acm/state/` 下所有 Agent 目录及 active 记录；
   - 但 `~/.acm/config.toml` 是用户的声明式配置（SSOT 资产），**不应被 `release` 自动物理删除**（文档提示若要彻底抹除，由用户手动 `rm -rf ~/.acm`）。

#### 裁决与建议
- **两文档原则一致，需在实现细节中补充精确边界**。
- **建议**：
  1. 在 v1.1 §7.5.2 中补充细化局部 release 与全量 release 的具体文件清理列表，明确 `config.toml` 不在任何 `release` 命令的主动删除范围内。

---

## 3. 已达成高度一致的关键维度

经严格比对，以下核心架构与设计决策在两份文档中已实现完全对齐与自洽：

| 维度 | v2.0 治理规格 | v1.1 实现参考 | 一致性评估 |
|---|---|---|:---:|
| **三大公理与字段所有权** | §1（SSOT、非破坏性、可逆性） | §1、§2.2 | ✅ 完全一致 |
| **适配器架构模型** | §5（内置 Python 模块，拒绝动态反射加载） | §6 D7、§7.4 | ✅ 完全一致 |
| **Adapter Protocol 职责** | §5（detect, config_paths, plan 3纯函数） | §7.4 | ✅ 完全一致 |
| **快照保留策略** | §1.3（Append-only 单纯追加，无静默 FIFO） | §6 D4、§7.5.3 | ✅ 完全一致 |
| **Manifest 所有权模型** | §3.3（内存派生视图，消除磁盘双写） | §6 D4、§7.5.2 | ✅ 完全一致 |
| **Agent 状态机枚举** | §4.1（6 种互斥主状态，优先级明确） | §7.6 | ✅ 完全一致 |
| **CLI 退出码体系** | §4.3.3（0, 1, 2, 3, 4, 130 语义） | §10.2 | ✅ 完全一致 |
| **P0 适配目标与优先级** | Claude Code, Codex, Pi | Claude Code, Codex, Pi | ✅ 完全一致 |
| **Credential 引用语法** | `${VAR}`, `${VAR:-default}` 整字段替换 | §7.3.1 整字段替换 | ✅ 完全一致 |
| **非破坏性保证分级** | 语义级硬保证 + 词法级 Fixture 界定 | §7.5.4 | ✅ 完全一致 |

---

## 4. 修改与行动建议汇总清单

为使两份文档达到 100% 严丝合缝的工程就绪状态，建议按以下清单执行文档微调：

### A. 对 `docs/ACM_PROJECT_SPEC_v2.0.md` 的修订（已执行）
1. **§4.2 命令总表**：
   - 将 `acm diff [<agent>]` 说明中的 `--against-snapshot` 修正为 `--against desired|last-write|snapshot`。
2. **§2.2 In-Scope**：
   - 将分层配置（Base SSOT + Overlay）明确标注为 Phase 3 规划。

### B. 对 `docs/ACM_PROJECT_SPEC_FINAL_v1.1.md` 的修订（已执行）
1. **§10.1 命令总表 & §12 路线图**：
   - 移除 `acm use` 的 `[<agent>]` 参数，统一为 `acm use <profile>`，单 Agent 收敛统一由 `acm apply <agent>` 承载。
2. **§7.1 流水线**：
   - 补充多 Agent 批处理循环与错误聚合逻辑（按 Agent 独立执行，stderr 聚合报错，退出码返回最高级别）。
3. **§7.5.6 崩溃恢复章节 & §11/§12 验收断言**：
   - 修正“写入间隙崩溃后直接 `apply` 自动收敛”的不严谨文案，明确指出因漂移检测机制的存在，此边界场景需配合 `--force` 或 `--hard` 恢复。
4. **§7.5.2 & §10.1 Release 章节**：
   - 细化单 Agent Release 与全量 Release 的目录/状态文件清理清单，明确 `~/.acm/config.toml` 永不被自动删除。
