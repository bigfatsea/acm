# Feedback v1

我把这份 `ACM_PROJECT_SPEC_FINAL_v1.0.md` 从头到尾重新看了一遍。我认为还有 **6 个值得补的关键点，其中 3 个属于比较重要的架构缺口，另外 3 个属于规格严谨性问题。**

我会按优先级说。

---

## 一、最高优先级：Rollback 的数据模型还没有完全闭环

这是我认为目前最值得修的地方。

现在文档同时定义了：

* `ChangeSet.FieldOp.old/new`
* `manifest.json` 记录“最后一次写入值”
* `journal.jsonl`
* snapshot
* `rollback --to <snapshot-id>`
* 默认字段级 rollback
* `--hard` 整文件 rollback

这些机制分别都合理，但**它们之间的关系还没有被严格定义清楚**。

尤其这里：

> `manifest.json` 记录 ACM 写过的每个 `(file, path)` 及最后一次写入值。

但是 `release` 又要求：

> 恢复 pre-ACM 旧值。

问题是：

```text
ACM 第一次写：
A → B

第二次写：
B → C

第三次写：
C → D
```

Manifest 最后只有：

```text
current = D
```

那么：

```bash
acm release
```

到底恢复到：

```text
A
```

还是：

```text
C
```

？

从产品语义上显然应该是 **A：ACM 接管之前的状态**。

但当前规格没有明确规定这个值究竟存在哪里。

Journal 可以做到，但目前只是说 Journal 记录操作，没有正式规定它承担 rollback history 的数据模型。

### 建议

把三个东西的职责明确成：

```text
Manifest
= 当前 ACM ownership / 当前 ACM 写入状态

Journal
= 每一次 ChangeSet transaction 的历史

Snapshot
= 完整文件级 disaster recovery
```

然后明确：

```text
rollback
→ 基于 Journal / transaction history 做字段级逆操作

release
→ 恢复“ACM 首次接管该字段之前”的值

--hard rollback
→ snapshot restore
```

这会让整个数据模型真正闭环。

---

# 二、最高优先级：`rollback --to snapshot-id` 和字段级 rollback 目前存在语义冲突

CLI 这里目前写的是：

> `acm rollback [<agent>] [--to <snapshot-id>] [--hard]`

同时又规定：

> 默认字段级回滚，`--hard` 才整文件 snapshot 还原。

这里实际上存在一个概念问题：

**snapshot 是 file-level artifact，而默认 rollback 是 field-level operation。**

例如：

```text
Snapshot S1
    file = config.toml
    entire file = A

之后：
T1 → ACM 修改 model
T2 → Agent 修改 MCP
T3 → ACM 修改 model
```

如果用户：

```bash
acm rollback --to S1
```

到底意味着：

### A

把 ACM-managed fields 恢复到 S1 对应的值？

还是：

### B

整个文件恢复 S1？

还是：

### C

恢复到某一个 transaction？

我建议不要让 `snapshot-id` 同时承担两种语义。

### 建议改成

概念上分成：

```text
acm rollback
acm rollback --to <transaction-id>
acm rollback --hard --to <snapshot-id>
```

也就是：

> **普通 rollback 回滚 transaction / managed fields；hard rollback 才引用 snapshot。**

这样用户模型非常清晰。

---

# 三、最高优先级：多文件“事务”目前实际上还不是 crash-safe transaction

文档现在的机制是：

```text
file A → os.replace
file B → os.replace

如果 B 失败：
→ 用原始 bytes 恢复 A
```



这可以解决：

> **正常运行过程中的异常。**

但解决不了：

> **ACM 自己在 A replace 完成、B replace 尚未完成时突然 crash / kill / power loss。**

例如：

```text
A = 新
B = 旧
```

ACM 此时死亡。

下次启动怎么办？

当前规格没有定义 recovery protocol。

这对于一个把：

> “安全写配置”

作为核心卖点的工具来说，值得补上。

### 建议

不需要设计复杂数据库事务，只需要增加一个非常轻量的：

```text
transaction journal

PREPARED
  ↓
COMMITTING
  ↓
COMMITTED
```

启动时：

```text
发现 PREPARED / COMMITTING transaction
→ doctor / init 自动检测
→ 根据 journal + temp files 恢复
```

也就是说：

> **Safety Engine 要具备 crash recovery，而不仅仅是 exception rollback。**

这个我认为应该加入 v1.0。

---

# 四、一个非常值得补的安全机制：Commit 前最终一致性检查

现在流程是：

```text
读取文件
→ 计算 old
→ 生成 ChangeSet
→ 修改内存
→ 写入
```

但存在一个 race：

```text
T0 ACM read config
T1 Agent/user 修改 config
T2 ACM 写入
```

即使进程守护在 T0 检查时没有发现 Agent 正在运行，也不能保证 T1 不发生。

所以仅仅：

> Process Guard + Drift Detection

还不够。

### 建议加入：

**Pre-commit fingerprint check**

即：

```text
Prepare:
    read original bytes
    hash = H0

Plan / mutate

Commit 前:
    reread original file
    hash == H0 ?
        yes → commit
        no  → abort + drift
```

这几乎没有多少实现成本，却会显著增强 Safety Engine。

尤其符合你现在的设计哲学：

> 不靠更多 edge-case logic，而是用一个更好的 abstraction 消灭 race。

---

# 五、`非破坏性保证`这一节还需要稍微降一下措辞

现在写：

> YAML 注释、缩进、空行、键序 100% 保留。

> TOML 注释、缩进、键序、表序 100% 保留。

从工程规格角度，我建议不要使用 **100%**。

不是因为 ruamel/tomlkit 不够好，而是因为：

> 你无法保证所有输入文件、所有 parser corner case、所有 formatter 行为都满足这个承诺。

而且“未管理节点结构级不变”和“文本完全不变”是两个不同层次。

建议改成类似：

```text
YAML/TOML:
- 未管理语义节点不发生变化
- 已知格式元素尽可能 round-trip 保留
- Golden fixtures 对注释、键序、空白等行为进行约束
```

然后把真正可以保证的东西写成：

> **对于 ACM 官方支持并覆盖的 fixture 集合，测试必须达到定义的 preservation guarantee。**

这比“100%”更加专业，也更容易长期维护。

---

# 六、JSONC 是目前 Format Helper 里面最值得再明确一下的一个点

你已经正确否定了：

> RFC 6902 = 无损。

这一点很好。

但目前又写：

> JSONC 用注释保留解析器。

这个规格还不够具体。

因为真正困难的是：

```text
parse
→ modify
→ serialize
```

如何保证：

```text
// comment A
{
  "foo": "bar", // comment B
}
```

这些 lexical information 被保留。

所以这里不用现在就指定具体 library，但建议在规格层定义一个接口：

```text
Format Writer 必须声明：
- semantic preservation
- lexical preservation
- comment preservation
- ordering preservation
```

然后每一种格式明确 capability。

这样以后换 JSONC 实现，也不会破坏架构。

---

# 七、Core Config 的 Credential Model 还可以再收紧一点

目前：

```toml
api_key = "${VMR_KEY}"
```

以及：

```text
明文 opt-in
```

这个方向是对的。

但我建议再明确一个原则：

> **Core Config 不应该承担 secret storage。**

也就是说：

```text
Core Config
→ credential reference

Credential Store
→ actual secret
```

例如：

```toml
api_key = "${VMR_KEY}"
```

或者未来：

```toml
credential = "anthropic-default"
```

然后由：

```text
env
keychain
```

提供真正 secret。

这样 ACM 本身就不会逐渐演变成：

> “另一个 API key manager”。

这和你的 Scope 哲学也更一致。

不过这不需要 MVP 就实现 keychain；**只需要现在把 abstraction 定义清楚。**

---

# 八、`acm init` 自动 import VMR，我建议稍微谨慎

目前：

```text
acm init
→ 探测 VMR
→ 如果运行则自动 import
```



从“3 条命令以内”的产品目标看非常漂亮。

但从 ACM 的另一个原则：

> Core Config 是用户的 SSOT

来看，这实际上意味着：

```bash
acm init
```

可能会**自动修改用户的核心配置**。

我更倾向：

```text
acm init
→ detect
→ generate proposal
→ confirm
→ import
```

或者提供：

```bash
acm init --yes
```

这样默认安全、自动化场景又不受影响。

这是一个小问题，但值得修。

---

# 九、CLI 里 `use` / `apply` / `init` 的语义已经不错，但建议明确一个核心概念：Desired State

现在系统实际上已经隐含存在：

```text
Core Config + Active Profile
        ↓
Desired State
        ↓
Current State
        ↓
ChangeSet
```

但是文档没有把 **Desired State** 作为正式概念提出来。

我认为这是值得增加的一个抽象。

因为一旦有了它：

```text
status
= current vs desired

diff
= current vs desired

apply
= current → desired

drift
= current != last ACM state

use
= change desired state
```

整个 CLI 语义会非常干净。

甚至：

```text
Core Config
   ↓
Active Profile
   ↓
Desired State
   ↓
Adapter
   ↓
ChangeSet
   ↓
Current State
```

这可能比继续增加 CLI 命令更有价值。

---

# 十、`status` 的状态模型建议正式定义

现在 `status` 会展示：

> 当前 profile / 漂移 / 上次操作时间。

建议正式定义至少：

```text
NOT_DETECTED
UNMANAGED
SYNCED
DRIFTED
CONFLICT
ERROR
```

这样未来 CLI、`--json`、CI、脚本调用都可以共用同一套状态枚举。

这属于很小的设计成本，但会显著提高 API 稳定性。

---

# 十一、我建议把“Adapter Capability”再提升一级

现在 Matrix 已经很好了：

> 哪些字段可以表达、哪些需要转换。

但未来 Adapter 实际上有两种能力：

```text
Semantic Capability
    vision
    reasoning
    tools
    context_window
    multi-model
```

以及：

```text
Projection Capability
    can_write_model
    can_write_provider
    can_write_reasoning
    can_register_model
    can_set_default
```

两者不要混为一谈。

例如：

```text
Core Model:
vision = true
```

但某个 Agent：

```text
can express vision capability = false
```

那么应该产生：

```text
WARNING:
profile partially expressible
```

而不是悄悄丢掉。

这个是未来 ACM 真正有价值的“semantic compiler”能力。

---

# 十二、还有一个值得补的东西：Projection Loss / Warning

这是上面 Capability Matrix 的自然延伸。

假设 Core Config：

```text
reasoning:
  effort = high
  budget_tokens = 16000
```

目标 Agent 只能表达：

```text
reasoning = high
```

那么 ACM 应该明确告诉用户：

```text
⚠ 1 field cannot be represented by Claude Code:
  models.coding.reasoning.budget_tokens

  Projection will omit this field.
```

否则：

```text
Core SSOT
→ Agent
```

过程中发生 silent loss。

这实际上和你现在强调的：

> “不静默覆盖”

是同一个哲学。

建议把它正式加入：

```text
ChangeSet / Report
```

模型。

---

# 十三、MVP 的命令数量稍微有点偏多，但我认为不需要砍

现在 Phase 1 一口气有：

```text
init
use
apply
status
diff
history
rollback
release
doctor
import vmr
```



从“1–2 周 MVP”看，这是偏多的。

但考虑到：

* 很多只是 Core operation 的 CLI wrapper；
* 没有 GUI；
* Safety 是产品本身；

我不会要求删掉。

我只建议在 implementation priority 上明确：

```text
Core:
init
use
status
diff
apply

Safety:
rollback
release
doctor

Audit:
history

Integration:
import vmr
```

这样实际开发时不会把十个 command 当十个独立 feature。

---

# 十四、风险表还漏掉一个很现实的风险：Adapter 维护成本

目前风险表已经考虑 schema drift，但没有把：

> **“支持 Agent 数量增长导致 Adapter 维护成本线性增长”**

单独列出来。

这个风险对于 ACM 是核心风险之一。

建议增加：

```text
风险：
Adapter maintenance burden

对策：
- 每 Agent 独立模块
- Golden fixture
- Capability Matrix
- community adapter
- P2 后才开放动态 Adapter
- 严格控制官方 Adapter 数量
```

更重要的是明确：

> **ACM 的长期成本主要不是 Core，而是 Adapter maintenance。**

这会影响以后所有产品决策。

---

# 十五、最后一个我认为值得补的：版本兼容 / Migration

Core Config 已经有：

```toml
version = 1
```



那么就应该顺手定义：

```text
version = 1
```

意味着：

> schema version，而不是 ACM 软件版本。

以及未来：

```text
version 1 → version 2
```

由：

```text
acm doctor
```

检测并：

```text
acm migrate
```

或者自动 migration。

不需要现在实现，但应该在架构层留下这个位置。

否则一旦 Core Config schema 真正发生变化，旧用户配置怎么处理会变成临时设计。

---

# 我对最终版的最终评价

如果之前 GLM 版我给 9/10，那么现在这份最终版我会给：

**9.3/10。**

而且这个分数不是因为“功能更多”，恰恰相反，是因为你们已经把很多东西**删掉了**。

目前最大的优点是：

> **Scope 已经非常干净，而且 Safety Engine 已经从“文件备份工具”升级成了真正的 Ownership / ChangeSet / Transaction 系统。**

尤其这条：

```text
Core Config
→ Profile
→ Adapter
→ ChangeSet
→ Ownership
→ Writer
→ Atomic Write
→ Journal/Snapshot
```

已经可以作为整个项目的架构脊柱。

我现在不会建议继续增加什么“大功能”。

真正值得做的是把下面 **6 个点补严谨**：

| 优先级    | 建议                                                                    |
| ------ | --------------------------------------------------------------------- |
| **P0** | 明确 Manifest / Journal / Snapshot 三者的数据职责和 rollback 数据模型               |
| **P0** | 解决 `rollback --to snapshot` 与字段级 rollback 的语义冲突                       |
| **P0** | 增加跨文件事务的 crash recovery / startup recovery                            |
| **P0** | Commit 前重新 hash 文件，解决 TOCTOU / 外部修改 race                              |
| **P1** | 正式定义 Desired State + Agent Status State Machine                       |
| **P1** | 增加 Projection Loss / Capability Warning，防止 Core → Agent 的 silent loss |

然后是一些次级完善：

```text
Credential reference abstraction
JSONC preservation contract
Schema migration
Adapter maintenance risk
init 的自动 import 确认语义
```

除此之外，我反而建议**停止继续设计**，直接进入实现。

因为现在再继续增加架构功能，很容易开始出现“为了让规格看起来更完整而增加复杂度”的反效果。当前版本已经跨过了从“方案设计”进入“工程验证”的临界点；下一步最有价值的信息不是继续讨论架构，而是用 **Claude Code + Codex + Pi 三个真实 Adapter 把 Safety Engine 跑起来**，看上述 Ownership / ChangeSet / Transaction 模型在真实配置文件上是否成立。当前规格本身也已经把这三个作为 P0，并用 Golden Test 和量化验收约束了 MVP。 

---------

# Feedback v2

以下从**高优先级（建议MVP阶段就明确/补充）**、**中优先级（P1-P2阶段完善）**、**低优先级（长期优化）**三个层级，给出进一步优化与补全建议。

---

## 一、高优先级：架构语义与核心安全的补全（建议MVP阶段明确）
这部分属于核心逻辑的边界模糊点，实现时一定会遇到，越早明确越减少返工。

### 1. 漂移检测与CLI命令的语义一致性需要明确
当前文档存在一处语义冲突：
- §7.5.2 提到：检测到漂移时**绝不静默覆盖**，要求 `--force`
- §10 又定义：`acm apply` 的作用是「重新对齐、修复漂移」

**问题**：`acm apply` 默认遇到漂移时，是直接强制覆盖（修复漂移），还是同样阻断并要求 `--force`？`acm use` 切换Profile时，遇到漂移又是什么行为？

**优化建议**：
- 明确统一规则：**所有写入类命令（use/apply/rollback/release）默认均触发漂移阻断**，检测到外部修改过管理字段时，先报错提示，必须加 `--force` 才会执行覆盖。
- 补充 `acm diff` 的漂移专项输出：清晰标注哪些字段发生了外部漂移、期望值与实际值。
- 可增加一个 `acm resolve` 轻量命令（或选项），提供两个选项：「以Profile为准覆盖磁盘」「以磁盘为准更新本地Profile」，替代粗暴的 `--force`。

### 2. Agent级Profile绑定的语义需要澄清
当前设计是**全局单一激活Profile**，`acm use <profile> --agent <id>` 更像「单次临时应用」。但真实高频场景是：用户希望 Claude Code 永远用官方直连Profile，Aider 永远用 DeepSeek 低成本Profile，不同Agent持久化绑定不同配置。

**优化建议**：
- 明确两种模式的定位：
  - **全局模式**（默认）：一个 active profile 投影到所有Agent，适合统一切VMR/统一切直连的场景。
  - **Agent级绑定**（P1补充）：支持 `acm bind <profile> --agent <id>`，为单个Agent持久化绑定专属Profile；`acm status` 中清晰展示每个Agent当前绑定的Profile。
- MVP阶段可以先不实现，但要在Scope中明确：当前仅支持全局Profile，Agent级绑定是后续规划，避免用户预期偏差。

### 3. 环境变量引用的完整规则缺失
仅提到 `${VAR}` 与 `${VAR:-default}` 语法，缺少关键边界定义：
- 解析时机：加载 `config.toml` 时解析，还是 apply 到Agent时实时解析？（建议实时解析，避免环境变量变更后需手动刷新）
- 优先级：同字段同时存在明文 `api_key` 和 env 引用时，谁优先？（建议env引用优先，明文作为兜底）
- 失败处理：环境变量不存在且无默认值时，是报错阻断，还是留空写入？（建议报错并提示，避免无效配置写入Agent）
- 安全边界：明确**不支持嵌套引用、不支持命令替换**，从规则上杜绝注入风险。

### 4. 并发写入安全与文件锁机制缺失
只考虑了「Agent进程正在运行」的冲突，没考虑「多个ACM进程同时执行写入」的场景（比如脚本并行调用、用户手滑开两个终端同时操作），可能引发竞态条件导致配置文件损坏。

**优化建议**：
- 引入全局文件锁（基于 `~/.acm/state/.lock` 的 flock 机制），同一时间只允许一个写入类命令执行。
- 锁等待超时策略：默认直接报错提示「另一个ACM进程正在运行」，避免长时间阻塞。
- 该机制实现成本极低，但能覆盖极端场景下的文件完整性，建议MVP阶段就做。

### 5. 敏感信息的全链路防护不足
仅提到「明文密钥需opt-in、doctor告警」，缺少全链路泄露防护：
- **快照与日志**：快照文件、journal日志中会包含原始配置（含明文密钥），需强制文件权限为 `0600`，仅所有者可读。
- **Diff输出**：`acm diff` 打印差异时，对 `api_key`、`token` 等敏感字段自动掩码（只显示首尾3位），避免终端录屏、日志泄露。
- **JSON输出**：`--json` 机器可读模式同样默认掩码，需显式加 `--show-secrets` 才输出明文。

---

## 二、中优先级：工程落地与体验完善（P1-P2阶段补充）
这部分不影响核心架构，但会显著提升工具的可靠性与易用性。

### 1. 补充 `acm init` 的幂等性与重复执行规则
用户重复执行 `acm init` 是非常常见的操作，当前只定义了全新机器的流程，未定义已有配置时的行为。

**优化建议**：
- 检测到 `~/.acm/config.toml` 已存在时，默认提示：「检测到已有配置，是否覆盖 / 合并更新 / 取消」，默认不破坏现有配置。
- 增加 `acm init --force` 强制重新生成，`acm init --import-vmr` 仅执行VMR探测与增量合并。

### 2. Agent自动探测规则需要明确化
`--agent all` 依赖自动探测，但探测逻辑未定义：
- 判定标准：是检查可执行文件在 `$PATH` 中，还是检查配置目录存在，还是两者都满足？
- 优先级与顺序：多个Agent同时检测到时，应用顺序是什么？
- 失败处理：某个Agent探测失败、或配置文件权限不足时，是整体中止还是跳过并告警？

**建议**：统一为「配置目录存在即视为已安装」，因为很多Agent可能安装了但未加入PATH，但配置目录一定存在；探测失败的Agent默认跳过并在结果中汇总告警，不影响其他Agent执行。

### 3. `acm release` 的边界语义需要细化
「恢复pre-ACM状态」的定义在边缘场景下不清晰：
- 如果某个配置文件**完全由ACM创建**（比如Pi的 `models.json` 用户原本没有），release 时是删除整个文件，还是只删除ACM写入的字段？
- 如果文件中既有ACM写入的字段，也有用户后续手动添加的其他字段，release 时只删除ACM管理的字段，保留用户内容。

**建议**：明确规则——
- 仅当整个文件的所有字段均为ACM管理、且原快照为空时，才删除文件；
- 其余情况只还原/移除ACM管理的字段，保留所有非管字段与注释。

### 4. 配置版本升级与迁移策略缺失
当前 `config.toml` 有 `version = 1`，但未定义版本升级机制。未来Schema变更时，旧版本配置如何处理是长期维护的关键问题。

**优化建议**：
- 明确版本号规则（语义化版本），ACM启动时校验配置版本；
- 低版本配置默认自动向前兼容，不兼容版本提供 `acm config migrate` 命令自动迁移；
- 快照、manifest 格式同样带版本号，确保跨版本回滚的兼容性。

### 5. CLI退出码规范缺失
脚本化、自动化是ACM的核心定位之一，但全文未定义退出码。不同错误场景返回统一的非0，调用方无法区分错误类型。

**建议补充标准退出码约定**：
| 场景 | 退出码 |
|---|---|
| 成功执行（含no-op幂等） | 0 |
| 配置语法错误 / Schema校验失败 | 1 |
| 漂移检测阻断 / 进程冲突阻断 | 2 |
| 文件权限不足 / 写入失败 | 3 |
| Agent未找到 / Profile不存在 | 4 |
| 用户取消 / 交互终止 | 130 |

同时约定：正常输出走 stdout，错误、警告、日志走 stderr，方便管道脚本过滤。

### 6. 金样测试的负面用例补充
当前三步断言主要覆盖正向流程，建议补充核心负面用例：
- 故意写入受保护路径，断言引擎拦截且文件无任何变更；
- 模拟多文件事务中途失败，断言已提交文件自动回滚、无残留；
- 模拟进程被强制终止（SIGKILL），断言无损坏的半写文件、临时文件被清理；
- 模拟磁盘空间不足，断言原子写入失败且原文件完好。

---

## 三、低优先级：长期生态与文档优化
### 1. 术语表前置，降低新贡献者门槛
全文大量使用 Field Ownership、ChangeSet、Managed Manifest、Round-trip、Drift、Projection 等专有概念，建议在文档开头（或附录）增加一个**核心术语表**，一句话解释每个术语的定义，方便社区贡献者快速理解设计哲学。

### 2. 明确与第三方配置工具的共存规则
可以补充一句说明：**不保证与 cc-switch 等其他配置管理工具共存**，同时使用可能导致配置互相覆盖、快照失效；建议同一Agent只使用一种配置管理工具。
不要求做兼容检测，但至少给出明确的风险提示，避免用户踩坑。

### 3. 配置版本管理的最佳实践指引
可以在文档末尾加一小节「推荐用法」：
- 建议用户将 `~/.acm/config.toml` 纳入个人 dotfiles 仓库进行版本管理；
- `state/`、`logs/` 目录建议加入 gitignore（可提供标准 .gitignore 模板）；
- 不建议将快照、manifest 纳入版本控制。

### 4. 附录裁决记录可适度精简
附录A非常详尽地记录了逐项裁决，对回溯决策很有价值，但部分条目偏细碎，一定程度上稀释了主文档的可读性。可以考虑：
- 保留核心分歧（四大矛盾点）的完整裁决；
- 细碎的采纳/拒绝项简化为表格汇总，详细记录移入单独的决策日志文档，主文档只保留结论。

---

## 四、整体总结
这份最终版已经完成了90%以上的核心设计，上述建议更多是**补全边界、细化语义、加固安全**，没有颠覆性的问题。其中最值得优先处理的是：
1. 漂移检测与命令语义的统一
2. 敏感信息全链路掩码与权限控制
3. 并发写入的文件锁机制
4. 环境变量引用的规则定义

把这几点补全后，这份规格文档的严谨度与可落地性会再上一个台阶，完全可以作为开源项目的官方规格基线。



---------

# Feedback v3

以下仅列**仍有必要进一步完善的点**（按优先级），其余可保持现状。

### 高优先级（建议尽快补齐或明确）

1. **ChangeSet 数据结构显式定义**  
   全文大量引用 ChangeSet，但缺少正式 schema（文件路径、JSONPath/点路径、旧值、新值、protected 标记、来源 profile 等）。建议在 §7.4 给出完整 dataclass / TypedDict 示例，作为 Adapter 与 Safety Engine 的契约边界。这是实现与测试的关键接口。

2. **§7.5 安全引擎细节补全**  
   文档引用了三阶段提交、漂移检测、多文件回滚、非破坏性等级（§7.5.1–7.5.4），但正文中相关段落在提供的版本里被截断。需确保完整写出：
   - 阶段 1–3 的伪代码/步骤
   - 跨文件失败时的内存字节回滚策略
   - 漂移检测与 `--force` 的精确语义
   - 格式保证等级（字节级 / 结构级 / 语义级）的定义与断言方式

3. **跨平台路径解析约定**  
   提到 XDG/macOS/Win，但缺少统一规则。建议补充简短规范（优先环境变量 → XDG → 平台默认路径 → 探测），并在每个 Adapter 的 `config_paths()` 中强制使用该 Helper，避免硬编码。

4. **Core Config 与 state 的边界再明确一次**  
   `active_profile` 已正确放到 state，建议在 §7.3 明确：`config.toml` 只含用户可版本控制的声明式内容；运行时状态（active、manifest、snapshots、logs）全部进 `~/.acm/state/`。防止未来把状态写回 config。

### 中优先级（完善体验与可维护性）

5. **进程守护的分级策略**  
   已提到 Claude Code 因支持热切换而放宽。建议正式写成表格：哪些 Agent 默认阻断、哪些仅警告，依据是什么（官方文档/实测）。

6. **错误与失败模式清单**  
   补充常见失败场景的处理约定（目标文件不存在、权限不足、JSON/YAML 语法已坏、ENV 引用缺失、多文件部分成功）。`doctor` 与 CLI 输出应有统一的错误码/退出码约定，方便脚本使用。

7. **项目级 Profile 的开放问题**  
   之前文档留过“是否支持 `.acm/` 仓库级覆盖”。最终版未表态。建议在开放问题或 Scope 中明确：MVP 只做全局；项目级作为 P2/P3 评估项，或直接声明暂不支持，避免实现时摇摆。

8. **依赖与锁定策略**  
   已定 ≤4 个运行时依赖。建议补充：使用 uv 锁定、CI 检查依赖漂移、pydantic 是否引入的最终决定标准（或明确 fallback 到 dataclass）。

### 低优先级 / 可选增强

- 在成功标准后增加一句“非成功样貌”（例如：变成第二个 cc-switch、开始写 GUI/MCP、依赖私有 DB 等），强化铁律。
- `acm doctor` 的输出示例（帮助统一 UX）。
- 贡献流程一句话引用（铁律写入 CONTRIBUTING + PR 模板检查清单），与附录 A 呼应。
- 日志级别与 `--verbose` 的约定（当前较简略）。

### 缺失但非关键的内容

无重大架构或原则性缺失。测试策略、验收标准、退出条件、VMR 松耦合、分发克制都已到位。主要是实现契约（ChangeSet、安全引擎细节、路径 Helper）需要从“引用”变成“可编码的规范”。

---

---

# 三轮 Feedback 逐项处理结果（v1.0 -> v1.1）

> 处理原则：问题成立与否独立核实（不轻信 feedback 的 claim）；问题成立时择最优方案（不必是 feedback 建议的原方案）。规格文件已升级为 `ACM_PROJECT_SPEC_FINAL_v1.1.md`。

## Feedback v1（15 项）

1. **回滚数据模型闭环（Manifest/Journal/Snapshot 职责 + release 恢复目标未定义）--吸收**。问题属实且是 v1.0 最大的真实缺口。已重构为三元分工（D4/§7.5.2）：Manifest 存 ownership 现状（含 `pre_acm` 接管前原始值，release 的明确恢复目标）+ Journal 存事务历史（字段级回滚数据源）+ Snapshot 仅灾难恢复。未照搬"靠 Journal 扫描恢复 pre-ACM"的建议，改为 manifest 直接存 `pre_acm`，更简单且读取无需重放历史。
2. **`rollback --to` 双语义冲突--吸收**。属实。已分离为 `--to <txid>`（字段级，逆序回滚事务）与 `--hard --to <snapshot-id>`（整文件还原），两套 id 不可混用（§10.1）。
3. **crash-safe 事务与启动恢复--吸收**。属实（v1.0 只覆盖运行期异常）。已增加事务状态机 PREPARED->COMMITTING->COMMITTED/ABORTED + 启动恢复协议（§7.5.7），COMMITTING 态用该事务快照整体还原，刻意不引入 WAL 级复杂度。
4. **pre-commit 指纹校验（TOCTOU）--吸收**。成立且成本极低。已加入阶段 3 提交前重读磁盘字节比对 H0，不等即整体中止并报 drift（§7.5.1）。
5. **"100% 保留"措辞降级--吸收**。同意：无法对所有输入负责的绝对承诺不专业。已改为"语义级硬承诺（解析树 diff，任意输入）+ 词法级 fixture 界定承诺"两层模型（§7.5.4）。
6. **JSONC 保真契约 / Format Writer 能力声明--吸收**。成立。已增加 Writer 能力声明表（语义/注释/键序/空白四维），JSONC 注释保留定为 OpenCode 适配器交付硬要求（§7.5.4）。
7. **Core Config 不承担 secret storage--吸收**。与 Scope 哲学一致。已成文为 credential 引用原则 + 预留 `credential = "name"` 字段，keychain 后置（§7.3.1）。
8. **init 自动 import 需确认--吸收**。属实（静默改用户 SSOT 违反自身原则）。改为 detect -> proposal -> confirm，`--yes` 供自动化（§9/§10.1）。
9. **Desired State 形式化--吸收**。高价值抽象。已进流水线与 CLI 语义（use=改 Desired 并收敛、apply=幂等收敛、status/diff=Current vs Desired、drift=Current vs 上次写入）（§7.1）。
10. **Agent 状态机枚举--吸收**。成本低、API 稳定性高。已定义六态（§7.6）。
11. **语义能力 vs 投影能力分离--吸收**。已进矩阵双维度与告警模型（§7.4.1/§8）。
12. **投影损失告警（防 silent loss）--吸收**。"不静默"哲学的自然延伸，已进 ChangeSet.warnings 与 CLI 输出（§7.4.1/§10.3）。
13. **命令分组实现优先级--吸收**。已按 Core/Safety/Audit/Integration 分组写入 Phase 1（§12）。
14. **Adapter 维护负担风险--吸收**。已入风险表并标注"ACM 长期成本主要是 Adapter 而非 Core"（§13）。
15. **Schema 版本与迁移--吸收**。已定义 version=schema 版本、doctor 检测、`acm config migrate` 后置 P2（§7.3.2）。
- 末尾"停止设计、进入实现"的建议--**采纳**：已在 §14 加入规格冻结声明。
- "9.3/10"评分--不处理（非技术内容）。

## Feedback v2（13 项）

#### 一（高优先级）
1. **漂移语义统一（apply"修复漂移"与"绝不静默覆盖"矛盾）--吸收**。矛盾属实（v1.0 第 541 行 vs 429 行，已核实）。统一为：所有写入类命令默认阻断，`--force` 覆盖，`apply` 收敛也过闸门（§7.5.2）。其中"`acm resolve` 命令（以磁盘为准更新 Profile）"**不采纳**：磁盘->Core Config 是与投影相反方向的 capture 语义，塞进 resolve 会混淆数据流方向；且违反"命令做薄"原则，留作未来独立评估。
2. **Agent 级 Profile 绑定--吸收（P1 规划，MVP 不做）**。需求真实。已明确：MVP 仅全局激活 profile；`acm bind` 持久绑定进 P1，与 `use --agent`（一次性投影）语义分离（§5.2/§12）。
3. **ENV 引用完整规则--吸收（方案更优）**。已定义：仅 `${VAR}`/`${VAR:-default}` 两种语法、禁止嵌套/命令替换（设计边界而非待办）、投影时实时解析、缺失即写前硬中止；"env 优先、明文兜底"的优先级规则**不需要**--单字段单一来源，同时出现视为 schema 错误，从模型上消灭优先级问题（§7.3.1）。
4. **并发写入文件锁--吸收**。已加全局 flock 非阻塞锁（标准库实现），占用即报错不排队（§7.5.6）。
5. **敏感信息全链路防护--吸收**。已加 state 目录 0700/0600、diff/status/--json 默认掩码、`--show-secrets` opt-in（§7.5.8）。

#### 二（中优先级）
1. **init 幂等规则--吸收**。已有配置时提示覆盖/合并/取消（默认取消），`--force` 跳过（§10.1）。
2. **探测规则明确化--吸收**。主判据=配置目录存在（PATH 会漏装），失败跳过+汇总告警，顺序=注册表固定顺序（§7.4）。
3. **release 边界语义--吸收**。已细化：ACM 全新创建且接管前不存在的文件整删，其余只动管理字段（§7.5.2）。
4. **配置迁移--吸收**（与 v1-15 同点合并处理，§7.3.2）。
5. **退出码规范--吸收**。已采纳表（0/1/2/3/4/130）+ stdout/stderr 约定（§10.2）。
6. **负面测试用例--吸收**。已入 §11.1（保护路径拦截、事务中途失败、SIGKILL、指纹不匹配、ENV 缺失、双进程竞争、磁盘/权限故障；注明按环境可行性注入）。

#### 三（低优先级）
1. **术语表--吸收**。已加附录 C。
2. **与第三方工具共存说明--吸收**。已入风险表：不保证与 cc-switch 等共存，README 明确提示（§13）。
3. **dotfiles 最佳实践--吸收**。已入 §7.7（gitignore 片段建议）。
4. **精简附录 A / 移出决策日志--不采纳**。附录 A 是 v1.0 任务的显式交付物（逐项可回溯裁决），是防"未来悄悄改决策"的审计记录；可读性问题以目录结构解决，不删审计轨迹。

## Feedback v3（8 项 + 若干小项）

1. **ChangeSet 正式 schema--部分吸收**。v1.0 §7.4 已有 FieldOp/ChangeSet dataclass（此点部分失实）；v1.1 按建议补齐 txid 与 warnings 字段（§7.4）。
2. **"§7.5 正文被截断"--不采纳（claim 不实）**。经核对 v1.0 原文，7.5.1–7.5.6 完整存在，无截断。相关四项内容（三阶段步骤/跨文件回滚/漂移语义/保证等级）v1.0 均已定义，v1.1 又有增强。
3. **跨平台路径解析约定--吸收**。已定 Helper 优先级（env 覆盖->XDG->平台默认->探测），适配器禁硬编码（§7.4）。
4. **config 与 state 边界再明确--吸收**。已在 D3 成文"任何功能不得把状态写回 config.toml"（§6 D3）。
5. **进程守护分级表--吸收**。BLOCK/WARN 两级 + 定级依据（官方 FAQ 证实 Claude Code 热切换）（§7.5.5）。
6. **失败模式清单 + 退出码--吸收**（与 v2-二.5 合并，§10.2 + §11.1 负面用例）。
7. **项目级 Profile 表态--吸收**。已明确：MVP 不做、P3 开放问题评估（§5.2）。
8. **依赖锁定策略与 pydantic 决策标准--吸收**。uv lock + CI 漂移检查 + pydantic 引入判据（校验逻辑 >~200 行）（§6 D2）。

#### 低优先级小项
- **"非成功样貌"反界定--吸收**。已加 §14 末段（含规格冻结声明）。
- **doctor 输出示例--不采纳**。属实现期 UX 细节，规格层已有诊断项清单与文案规范，先例一开规格会持续膨胀。
- **贡献流程一句话引用--已覆盖**。v1.0 §5.4 已有（铁律写入 CONTRIBUTING/PR 模板），无需重复。
- **日志级别约定--吸收**。一句话入 §7.7（--verbose=DEBUG，默认 INFO 摘要，logs 目录）。
