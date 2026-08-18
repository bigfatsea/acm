# ACM 规格文档一致性与 Gap 分析报告（v2.0 vs v1.1）

<!-- Date: 2026-08-18 | Target: ACM_PROJECT_SPEC_v2.0.md vs ACM_PROJECT_SPEC_FINAL_v1.1.md -->

> **文档性质**：对比审阅《ACM 项目规格 v2.0（原则版）》与《ACM 最终版项目规格说明书 v1.1（实现参考）》，梳理两者之间的矛盾冲突、未闭环的设计 Gap、潜在逻辑错误及实现隐患，并给出可落地的修订建议。

---

## 目录

1. [总体审阅结论](#1-总体审阅结论)
2. [矛盾与不一致点（Contradictions & Inconsistencies）](#2-矛盾与不一致点)
3. [关键设计 Gap 与未闭环之处（Missing Specifications）](#3-关键设计-gap-与未闭环之处)
4. [重大安全隐患、逻辑错误与边缘陷阱（Errors & Edge Cases）](#4-重大安全隐患逻辑错误与边缘陷阱)
5. [修订建议与修复清单（Actionable Checklist）](#5-修订建议与修复清单)

---

## 1. 总体审阅结论

* **架构核心高度自洽**：两份文档在三大公理（SSOT、非破坏性、字段级可逆性）、三层核心配置模型（Providers / Models / Profiles）、三元恢复体系（Manifest / Journal / Snapshot）以及安全引擎强制校验的设计哲学上完全统一。
* **分层定位清晰**：v2.0 成功提炼并冻结了治理原则与数据模型公理；v1.1 详细充实了实现层细节、历史沿革与事实核查。
* **存在的主要问题**：
  1. **参数语义冲突**：`use` / `apply` 的 `--agent` 选项在单激活 Profile 的 MVP 约束下存在语义矛盾。
  2. **多 Agent 事务边界未闭环**：多 Agent 批量投影与单 Agent 隔离存储之间的事务失败处理、回滚作用域未明确。
  3. **状态机模型瑕疵**：`CONFLICT` 态作为互斥主状态，会导致读操作（`status`）下掩盖实际的配置同步态。
  4. **重大数据安全隐患**：`release` 在删除“ACM 创建的文件”时，未检查用户后续手动追加的未管理字段，存在破坏性删除风险。

---

## 2. 矛盾与不一致点

### 2.1 `use` / `apply` 的 `--agent` 参数与 Desired State 语义冲突

* **v2.0 规格定义**：
  * §2.2：*“MVP 仅全局单一激活 Profile。”*
  * §4.2 命令总表：
    * `acm use <profile>`：改变 Desired State（换激活 Profile）并立即投影。
    * `acm apply`：Current -> Desired 的幂等收敛。
    * 两个命令在总表中均**未提供** `--agent` 参数。
  * §4.3(2)：*“`use` 与 `apply` 语义不混淆：use 改变 Desired State 并收敛；apply 只收敛不改变。”*
* **v1.1 参考定义**：
  * §10.1 CLI 规格：
    * `acm use <profile> [--agent <id|all>]`
    * `acm apply [--agent <id|all>]`
  * §12 Phase 2：*“`acm bind`：Agent 级持久绑定（全局激活 + 每 Agent 覆盖的二级 Desired State；`use --agent` 保持一次性投影语义，两者不混淆）”*。
* **冲突分析**：
  * 在 MVP 阶段，Desired State 是单一全局状态（`~/.acm/state/active`）。
  * 若执行 `acm use daily --agent codex`：
    * **假设 A（修改 active 为 daily）**：Codex 投影成功；但未指定的 Claude Code 和 Pi 的期望值被动变为 daily，其状态变为 `OUT_OF_SYNC`，下次执行全局 `acm apply` 会将它们一并修改。这与用户“只想修改 codex”的局部意图冲突。
    * **假设 B（不修改 active）**：仅将 `daily` 投影到 Codex。但这违反了 v2.0 的铁律——`use` 必须改变 Desired State。此时 Codex 处于无法被 Desired State 解释的游离状态，`apply` 与 `status` 的计算地基将发生动摇。
* **结论与裁决**：
  * 在 MVP 阶段，`acm use <profile>` 应**严格作为全局命令**（不带 `--agent`）；
  * `acm apply [--agent <id>]` 允许带 `--agent`，表示“仅将特定的 Agent 收敛至全局 Desired State”；
  * `acm bind <profile> --agent <id>` 与局部覆盖的二级 Desired State 统一留到 Phase 2。

---

### 2.2 全局标志（Global Flags）列举不一致

* **v2.0 §4.2**：`# 全局：--dry-run / --force / --verbose / --no-color 语义自明`（未列 `--show-secrets` 与 `--json`）。
* **v1.1 §10.1 & v2.0 §3.4(6)**：明确规定敏感内容默认掩码，`--show-secrets` 显式 opt-in 输出明文，`--json` 为 Phase 2 交付。
* **结论**：v2.0 §4.2 漏列了 `--show-secrets`。虽然属于原则版简写，但为避免实现遗漏，应在全局参数列表中统一体现。

---

### 2.3 `rollback` 参数与快照指定的表述差异

* **v2.0 §4.2**：`acm rollback [<agent>] # 字段级回滚（默认最后一个事务，--to-tx 指定）；--hard = 整文件快照灾难恢复`。
* **v1.1 §10.1**：`acm rollback [<agent>] [--to-tx <txid>] [--hard [--snapshot <id>]] [--force]`。
* **结论**：v1.1 明确了 `--hard` 模式下可通过 `--snapshot <id>` 指定恢复特定快照（缺省为最新快照），参数分离逻辑严密。v2.0 简表中未体现 `--snapshot` 参数名。

---

## 3. 关键设计 Gap 与未闭环之处

### 3.1 跨 Agent 事务边界与回滚作用域未定义

* **现状描述**：
  * 一条 `acm use daily` 或 `acm apply` 通常会同时操作多个 Agent（如 Claude Code, Codex, Pi）。
  * v1.1 §7.7 规定：每个 Agent 在 `~/.acm/state/<agent>/` 下拥有完全独立的 `manifest.json`、`journal.jsonl` 和 `snapshots/`。
  * v1.1 §7.4 规定：每个 `ChangeSet` 结构体只包含单一 `agent_id: str`。
* **未闭环问题**：
  1. **多 Agent 执行失败的原子性**：如果投影到 Claude Code 成功，但投影到 Codex 时触发指纹校验失败（TOCTOU 外部篡改）导致中止：
     * 是否需要回滚已经提交的 Claude Code？
     * 还是各 Agent 事务完全隔离，支持部分成功并输出告警？
     * *根据 CLI 体验与隔离原则，Agent 间应为独立事务，但文档未对“部分成功时的退出码与状态”做出明确规定。*
  2. **缺省 `acm rollback` 的回滚范围**：
     * 用户执行 `acm rollback`（未传 `<agent>` 参数）时，是回滚上一次全局批量操作所涉及的所有 Agent，还是强制要求必须显式指定 `<agent>`？
     * 若回滚所有 Agent，需要一个全局的 Operation/Batch ID 将各 Agent 的事务串联，当前 Journal 数据模型缺少该全局关联字段。

---

### 3.2 字段级逆操作（Inverse ChangeSet）算法与漂移冲突机制未细化

* **现状描述**：v1.1 §10.1 规定 `--to-tx <txid>` 为“逆序回滚至该事务之后的状态”。
* **未闭环问题**：
  1. **多事务回滚算法**：若事务链为 $Tx_1 \to Tx_2 \to Tx_3$，回滚到 $Tx_1$ 需要连续对 $Tx_3$ 和 $Tx_2$ 执行逆操作。
     * 若 $Tx_2$ 写入的字段 $K_2$ 在磁盘上已被外部修改（发生 Drift），而 $Tx_3$ 写入的字段 $K_3$ 未被修改，回滚是整体阻断还是跳过冲突字段？
  2. **逆操作（Inverse Op）的精确规则**：
     * 若 `FieldOp.created == True`（本次新建），逆操作应为**删除键**（`delete op.path`）；
     * 若 `FieldOp.created == False` 且 `FieldOp.old` 存在，逆操作应为**恢复旧值**（`set op.path = op.old`）；
     * 此逆操作生成规则未在 Core/Adapter 契约中形式化。

---

### 3.3 状态机中 `CONFLICT` 态破坏只读命令（`status`）语义

* **现状描述**：
  * v1.1 §7.6 状态机定义：`CONFLICT = 环境冲突当前生效（Agent 进程运行中 / 写入锁被占 / 上次操作被阻断待处理）`。
  * 状态优先级：`ERROR > CONFLICT > DRIFTED > OUT_OF_SYNC > SYNCED`。
* **逻辑缺陷**：
  1. 用户运行 `acm status` 是一个**只读查看配置同步状态**的操作。
  2. 如果用户终端正开着 Codex 进程（后台运行中），此时配置实际已经完全对齐（`SYNCED`），但由于 `CONFLICT > SYNCED`，`status` 会将 Codex 显示为 `CONFLICT`，导致用户无法获知真实的配置同步状态。
  3. 此外，Claude Code 被 §7.5.5 定级为 `WARN`（允许热加载，写入不阻断），若 Claude Code 正在运行，它是否应属于 `CONFLICT` 存在定义模糊。
* **改进方案**：
  * `CONFLICT` 不应作为顶层互斥的配置同步状态；
  * Agent 基础同步状态应保持为纯粹的配置维度：`[SYNCED | OUT_OF_SYNC | DRIFTED | ERROR | UNMANAGED]`；
  * “进程运行中 / 锁被占用”应作为**运行时修饰标记（Flags / Badges）**展示在 status 旁边（例如：`codex: SYNCED (⚠️ process running, PID 12345)`）。

---

### 3.4 Format Writer 中的 `.env` 属于未使用的冗余定义

* **现状描述**：v1.1 §7.5.4 Format Writer 能力声明表中列出了 `.env` 格式，并在 §11.3 CI 策略中要求 `.env` round-trip 单测先于适配器交付。
* **问题分析**：
  * 审阅 P0（Claude Code, Codex, Pi）与 P1（Aider, Gemini CLI, OpenCode）的所有目标配置文件：
    * **Claude Code**：`settings.json`（JSON，包含 `env` 对象，非 `.env` 文件）
    * **Codex**：`config.toml` (TOML) + `auth.json` (JSON)
    * **Pi**：`models.json` (JSON) + `settings.json` (JSON)
    * **Aider**：`.aider.conf.yml` (YAML) + `.metadata.json` (JSON)
    * **Gemini CLI**：`settings.json` (JSON)
    * **OpenCode**：`opencode.json` (JSONC)
  * **没有任何官方 Agent 将 shell `.env` 文件作为其模型配置文件**。
  * 将 `.env` 写入器列入 MVP 核心交付和单测门禁，增加了无意义的工程负担。

---

## 4. 重大安全隐患、逻辑错误与边缘陷阱

### 4.1 `acm release` 销毁 ACM 创建文件时的破坏性漏洞（Critical Safety Risk）

* **规格现状**：
  * v1.1 §7.5.2 规定：*“完全由 ACM 创建且接管前不存在的文件（如 Pi 的 models.json 用户原本没有）整文件删除；其余情况只动管理字段，用户内容与注释保留。”*
* **致命边界场景**：
  1. 用户初次使用 Pi，本机不存在 `~/.pi/agent/models.json`。
  2. ACM 执行接管，创建了 `models.json` 并写入了 `providers.vmr`。
  3. 随后，用户手动编辑该文件，追加了自己的本地模型配置 `providers.my_ollama = { ... }`。
  4. 某天用户执行 `acm release pi`。
  5. 按照当前规格的“整文件删除”逻辑，ACM 会执行 `os.remove("~/.pi/agent/models.json")`，**直接将用户手动追加的 `providers.my_ollama` 永久删除**！
* **违背原则**：直接违反**公理 2（非破坏性：未管理字段必须无损保留）**。
* **修正逻辑**：
  * `release` 在决定是否整文件删除前，必须进行**非管理字段扫描**：
    * 仅当文件中**只包含** ACM 管理的字段且无任何外部注入内容时，才允许整文件删除；
    * 若文件中存在任何非 ACM 管理的键值（如用户后来手写的 `my_ollama`），**绝对禁止整文件删除**，必须降级为字段级删除（从 JSON 中剔除 ACM 注入的 keys）。

---

### 4.2 三阶段提交在目标目录不存在时的文件系统异常

* **规格现状**：
  * v1.1 §7.5.1 阶段 3 步骤 2：*“预备写入：在各目标文件同目录下写入临时文件 `<target>.acm_tmp`”*。
* **潜在错误**：
  * 在全新的机器或从未运行过该 Agent 的环境下（例如尚未启动过 Pi，`~/.pi/agent/` 目录尚不存在），目标文件不存在（$H_0 = \text{NOT\_EXIST}$）。
  * 阶段 3 直接尝试向 `~/.pi/agent/models.json.acm_tmp` 写入文件，会直接触发 Python `FileNotFoundError` 异常导致提交崩溃。
* **修正逻辑**：
  * 在阶段 3 创建临时文件前，必须显式调用 `target.parent.mkdir(parents=True, exist_ok=True)`。

---

### 4.3 Credential 解析生命周期与落盘明文的认知偏差

* **规格现状**：
  * v2.0 §3.2 与 v1.1 §7.3.1 强调：*“Core Config 存的是 credential 引用，ACM 不承担 secret storage”*。
  * 解析时机为投影时实时求值：`Core Config (${VAR}) -> ResolvedProfile (解出明文) -> ChangeSet (明文) -> 写入目标 Agent 文件 (明文)`。
  * v1.1 §7.3.1 注释称：*“解析时机：投影时实时解析，不在 config 加载时固化——环境变量变更后无需刷新。”*
* **认知与实现风险**：
  * 这里的“无需刷新”容易引起误解：一旦写入了 Agent 目标文件（如 Codex 的 `auth.json` 或 Claude Code 的 `settings.json`），磁盘上**已经是明文密钥**。
  * 如果用户在 shell 里修改了 `export ANTHROPIC_API_KEY=new_key`，目标 Agent **不会自动感知**，必须显式执行一次 `acm apply` 重新投影落盘。
  * 应在文档中明确区分“Core Config 免刷新”与“Agent 磁盘文件需执行 `acm apply` 重新投影”。

---

### 4.4 Pi 适配器的持久化字段名校准

* **规格现状**：
  * v1.1 §8 Pi 适配矩阵写着：settings.json 写入 `defaultProvider`、`defaultModel`、`defaultThinkingLevel`。
* **代码实证校验**：
  * 查阅 Pi 官方核心源码（`settings-manager.ts` 与 `SettingsConfig` 接口）：
    * 思考深度在 `settings.json` 中落盘的实际字段名为 `thinkingLevel`，而非 `defaultThinkingLevel`；
    * 适配器开发时需严格以此为准，避免向 Pi 写入无效字段。

---

## 5. 修订建议与修复清单

为确保项目进入代码实现阶段时无歧义、无隐患，建议执行以下修订：

| 序号 | 类别 | 涉及文档与章节 | 具体修订动作 |
|---|---|---|---|
| **1** | **安全隐患** | v1.1 §7.5.2 (`release`) | **修复文件删除逻辑**：增加安全检查——由 ACM 创建的文件，若当前包含非 ACM 管理的键值，严禁整文件删除，降级为字段级移除。 |
| **2** | **参数一致性** | v1.1 §10.1, §12 / v2.0 §4.2 | **收紧 MVP 参数**：MVP 阶段 `use <profile>` 仅支持全局；`apply` 支持可选 `--agent <id>`；`use --agent` 延后至 Phase 2 与 `bind` 统一。 |
| **3** | **事务边界** | v1.1 §7.5.1, §7.7 | **明确多 Agent 事务语义**：定义全局投影为“Agent 级独立事务串行提交”，单 Agent 失败不回滚已成功的其他 Agent；明确缺省 `acm rollback` 在 MVP 阶段要求显式传入 `<agent>` 参数。 |
| **4** | **状态机优化** | v1.1 §7.6 (`status`) | **解耦 `CONFLICT` 态**：将 `CONFLICT` 从互斥主状态中移出，主状态专注配置对齐（SYNCED/OUT_OF_SYNC/DRIFTED/ERROR/UNMANAGED），进程/锁冲突作为附加 Flag 显示。 |
| **5** | **实现健壮性** | v1.1 §7.5.1 (阶段 3) | **补充目录创建步骤**：原子写前显式调用 `target.parent.mkdir(parents=True, exist_ok=True)`。 |
| **6** | **冗余清理** | v1.1 §7.5.4, §11.3 | **剔除 `.env` Writer**：从 Format Writer 核心表中移除 `.env`，集中精力保障 JSON / TOML / YAML (ruamel) 的 round-trip 保真度。 |
| **7** | **参数补齐** | v2.0 §4.2 | **补齐全局参数**：在 v2.0 全局选项中补充 `--show-secrets` 声明。 |
| **8** | **适配细节** | v1.1 §8 (Pi 矩阵) | **校准 Pi 字段名**：将 `settings.json` 中的 `defaultThinkingLevel` 修正为落盘字段 `thinkingLevel`。 |
