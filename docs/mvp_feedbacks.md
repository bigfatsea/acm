### 问题 2：漂移阻断（与“仅观察、不阻断”的约定背道而驰）

- **Plan 中的做法**：§1.1 安全底线写“受管字段漂移检测 + **默认阻断**（退出码 2）+ `--force`”；§4.2 算法明确“写命令默认阻断”。
- **我们约定的简化**：漂移**只展示、不阻断**。`diff` 负责教育用户，写入负责收敛，不给用户添堵。理由是个人开发者本机场景下，阻断式体验极差，用户会无脑加 `--force`，使检测形同虚设。
- **后果**：KP（关键路径）上多了阻断判断、`--force` 状态传递、退出码 2 的精细控制，而实际用户价值为负（打扰用户）。

### 问题 3：把 `diff` 和 `apply` 踢出 MVP（最致命的缺失）

- **Plan 中的做法**：§1.1 明确“明确不在 MVP：`apply` / `diff` / ...”。只留下 `use`、`status`、`rollback`、`init`。
- **我们约定的简化**：`diff` 是“只观察”的核心载体；`apply` 是“只收敛不切换”的标准声明式操作。两者是 MVP 的骨架命令。
- **为什么这是致命的**：
  - 没有 `diff`，用户无法知道“为什么阻断”或“当前到底差在哪”，只能看模糊的 `status`。这是把用户蒙在鼓里。
  - 没有 `apply`，用户修改了 `config.toml`（SSOT 合法行为）后，**无法重新投影当前 Profile**，只能切到其他 Profile 再切回来（丑陋且易出错），或者依赖危险的 `init --force`。
- **Plan 的逻辑漏洞**：§4.2 批处理原则引用了 PRINCIPLE §4.3.6（`apply` 的批处理语义），但命令列表却没有 `apply`——这是自相矛盾。




**问题 2：init 命令中 VMR 探测的复杂度被低估**

Action Plan 将 `init`（含 VMR 探测与提案确认）放在 WP5（CLI 命令面）中实现。但 VMR 探测涉及：
- 多端点 HTTP 探测（§4.2 的 VMR 探测方案，含 4 步容错）
- 提案构建（providers.vmr + models.* + profiles.daily）
- 交互确认（rich 展示 → 用户确认）
- 配置生成（含 ENV 引用注释）

这实际上是一个**独立的功能模块**，而不仅仅是"CLI 命令面"的编排逻辑。WP5 的规模标注为 L，但包含 init（含 VMR）+ use + status + rollback + 全局旗标 + 退出码 + 输出掩码，实际工作量可能超过 L。

**建议**：将 VMR 探测与提案构建拆为独立任务包（如 WP5a），CLI 命令面（WP5b）只负责组装。这样 WP5b 的规模可降为 M，且 VMR 探测可独立测试。


### 问题 3：WP5 的 `use` 编排逻辑与 WP4 的依赖关系需要更明确

WP5 的 `use` 命令需要调用 WP4 的状态判定（漂移检测）和 WP3 的安全引擎（唯一写通道）。Action Plan 的依赖图标注了 WP5 依赖 WP1-WP4，但 WP5 的任务细项中没有明确描述 `use` 的完整编排流程（读 config → resolve → 读 active → 选 profile → plan → safety write → 写 active → 输出）。如果 WP5 和 WP4 并行开发，接口契约（ResolvedProfile 的字段、plan() 的返回值）需要在 WP4 交付前冻结。

**建议**：在 WP4 的验收标准中增加"导出稳定的公共接口（ResolvedProfile 数据结构 + plan() 签名）"，并在 WP5 的任务细项 1 中描述完整的 `use` 编排流程伪代码。

### 问题 4：`--dry-run` 的行为边界不够明确

Action Plan 在 §1.1 的命令表中列出了 `--dry-run` 全局旗标，但在各 WP 的任务细项中没有明确 `--dry-run` 的具体行为：
- 是否计算漂移检测？（如果算了，输出什么？）
- 是否写 active 文件？（自检记录提到"不写 active/快照/last_write"，但应更明确）
- 是否执行 VMR 探测？（init --dry-run 应该只输出提案不写盘）

**建议**：在 WP5 的任务细项中增加 `--dry-run` 的行为规范：只计算不写盘（不写 active/快照/last_write），init --dry-run 输出提案但不写 config.toml，status --dry-run 正常执行漂移检测并输出差异。




### P1. 范围：把 Slice 2 和「不可降级的漂移」写进诞生条件

这是总问题，后面好几条都从这里长出来。

漂移默认阻断是正确的**终局**行为，不是开箱行为。目标用户第一次 `acm use` 时，Agent 配置里往往已有手写的 `base_url`/`model`。按 Plan：无 `last_write` → `UNMANAGED`，第一次能写；之后手改才阻断。逻辑自洽，但代价是必须先做六态、`last_write` 存明文、`--force` 覆盖、exit 2、status 漂移摘要——WP4 整包 + WP5 很大一块。这些都不服务「≤3 条命令指向同一模型」。

Pi 同理：Codex 已经覆盖「TOML + 新建表」。Pi 的独特处是**全新建文件 + rollback=删文件**（A11），这是第三种形状，也是新的破坏模式。放进 MVP 完成线，等于发布前必须把最危险的回滚语义做对。

PyPI 是分发，不是定义。`acm` 包名极大概率冲突（A13 自己也写了），发布问题会卡住「MVP 完成」。

**建议**：完成线改回 M2。Pi、PyPI、漂移阻断从「不可降级」降为 M2 之后的触发项。若 v2.1 已经把漂移写进原则第⑤条，那是规格回潮，Plan 在忠实地执行一个我们建议过不要放进第一期的决定。

---

### P2. Rollback 语义自相矛盾，按字面实现会坏

三处规定对不上：

1. `rollback` = 恢复**最新**整文件快照  
2. A12：恢复**前**先把当前文件再快照一次  
3. `last_write.backup_id` 有记录，但 rollback 流程**没说用它**

按 1+2：先写入新快照 T_now，再恢复「最新」→ 最新就是刚写下的 T_now → **rollback 变成 no-op**。

即便实现成「快照后恢复上一份」，还有第二个洞：**rollback 之后 `last_write` 怎么更新，全文没写。** 若只拷文件、不改 `last_write`：

- 盘上已回到写前值  
- `last_write` 仍是投影后的值  
- `status` → `DRIFTED`  
- 下次 `use` 被阻断，必须 `--force`

用户按文档做了官方恢复，工具反而宣布被外部篡改。这是会直接打穿「可逆性」验收的设计漏洞。

**必须先拍板再写 WP5：**

- 恢复目标 = `last_write.backup_id` 指向的那份，不是字典序最大  
- 恢复前快照可以留（A12 合理），但不得成为恢复目标  
- 恢复成功后更新 `last_write`（字段值改为恢复后的值，或清成 UNMANAGED）。否则漂移机与 rollback 互斥

「最新快照」这种说法在 A12 之后已经不成立，应删掉。

---

### P3. `detect` 以配置文件存在为准，会打穿开箱路径

Claude / Codex：`settings.json` / `config.toml` 存在才算检测到。  
Pi：`models.json` **可以不存在，ACM 负责创建**。

成功标准是「装好 Agent 后 ≤3 条命令指向 VMR」。没跑过的 Claude 常常没有 `settings.json`。按当前 detect，该 Agent 被跳过，`use` 显示成功、少投了一家——验收第 1 条在真实全新机器上会失败。

Pi 能建文件、Claude 不能，标准不统一。

**建议**：detect 主判据改为「配置目录或可执行文件」；目标文件不存在则走「ACM 创建」（与 Pi 同一条路径）。这不是新功能，是 3 命令故事的前提。创建文件的 rollback=删除，和 A11 是同一套确认，应提前到 Claude/Codex，而不是只给 Pi。

---

### P4. 把 Writer 词法保真塞进写通道，诞生风险很高

两件事叠在一起：

1. WP2 验收：JSON「整值替换后**其余字节级不变**」  
2. WP3 写通道第③步：`tree_diff` 非管节点零差异，失败则 **exit 2、整次不写**

`json.dumps` 保键序、猜缩进、保留末尾换行，做得到；保「其余字节」做不到（冒号空格、不同层级缩进、空行、数字写法）。这条验收要么永远红，要么上线前被迫放水。

更严重的是 **runtime 用 tree_diff 挡写入**：Writer 稍有偏差（`1` vs `1.0`、空 `env` 对象被创建、tomlkit 改了表类型），ACM 会对合法文件拒绝投影。工具从「补丁器」变成「Writer 正确性的人质」。Plan 还写了 int/float **严格等价**，等于主动收紧误报。

**建议**：

- 写通道只保证：**未管键语义还在**（解析后结构/值）。这是原则要的  
- 词法（注释/键序/空白）只做测试夹具，失败不挡写入  
- JSON 明确不承诺字节级；TOML 注释能留最好，不当闸门  
- WP2 不再是适配器的硬前置，与 WP6 用同一份 Claude 夹具一起验收更快

指纹校验（写前 H0、提交前重读）便宜且对，可留。flock + 原子替换可留。SIGKILL / 双进程抢锁作为 **WP3 的诞生验收** 过重，放到 M2 之后的可靠性包。

---

### P5. Codex 双文件写 `auth.json`：范围和原则都有问题

原则：SSOT 只存 `${ENV}`，不做 secret storage。  
Plan：resolve 出明文 → 写入 Claude 的 `env.ANTHROPIC_*`，以及 Codex 的 **`auth.json` 实体 key**，再在 `config.toml` 里用 `env_key` 指过去。

Claude 写 `settings.json` 的 env 块是投影所必需（Agent 不读 `~/.acm/`）。Codex 的惯用做法是 `env_key = "FOO"`，由 **Codex 自己读环境变量**。若如此，`auth.json` 根本不必进 `config_paths`，双文件事务、提交顺序、中途失败、孤儿 key、WP7 故障注入整段都可以没有。

`auth.json` 里往往还有 OAuth token。把它列入受管文件，等于把「凭证文件的双重所有权」——规格里最难的那种——放进第一个 TOML 适配器。

**建议**：先用本机 Codex 实证一条路径：只改 `config.toml` 的 `model` / `model_providers.<id>`（`env_key` 指向已有环境变量）能否跑通。能，则 `auth.json` 移出 MVP。不能，再上双文件，并写明「这是密钥落盘，不是引用」。现在把双文件当既定架构，是在为未验证的映射付最大复杂度。

---

### P6. Core Config schema 比能投影的更肥

WP1 把 `capabilities.*`、`reasoning.budget_tokens`、`context_window`、`max_output_tokens`、`temperature` 都做成校验规则；WP6 又把其中大半标成投影损失告警。

结果：init 从 VMR 生成配置时要填一堆 **两个 P0 Agent 都写不进去的字段**，否则校验失败；`use` 再 stderr 警告「无法表达」。这是自扰。

**建议**：MVP schema 只强制投影真正会写的：`providers.{protocol,base_url,api_key}`、`models.{provider,id}`、`profiles.main`。其余可选，有则告警，无则沉默。VMR 提案才能是短文件，而不是一份小型模型目录。

---

## 3. 细小问题（一笔带过）

- `ruamel.yaml` 为尚不存在的 Aider 锁进运行时依赖：典型预付款，应移出。  
- 错误文案提 `acm doctor`，命令却不在 MVP，用户会去敲。  
- `--verbose` 在 A4 待拍板，WP5 命令表已经写进去。  
- `rollback --force` 与 `use --force` 同旗标不同义（删文件 vs 覆盖漂移）。  
- 验收第 2 条「10 次循环后注释不变」对 JSON 无意义，对 TOML 也不该是硬性 e2e。  
- `${VMR_KEY:-}` 空默认是否过正则，实现时要放进 WP1 边界用例。  
- Windows `msvcrt` 分支「保编译不验收」：要么声明不支持 Win，要么不要假装有分支。  
- 公开函数强制 docstring + mypy strict：过程税，不挡事，但不要变成 WP0 的阻塞。  
- A 项默认「未拍板按建议执行」合理；**P2/P3/P5 不在 A 表里**，却比 A1 pydantic 更该先拍。


--------


#### 1. 双文件写入与指纹校验的死锁/竞态漏洞（WP3 / WP7）

* **现状**：Codex 涉及双文件（`auth.json` + `config.toml`）。WP3 的五步流水线中，指纹校验（Step ④）是“重读磁盘字节校验 H0，通过后执行原子替换（Step ⑤）”。


* **问题**：如果流水线是针对每个文件独立顺序执行“①~⑤”，当第一个文件（`auth.json`）替换成功后，如果在写第二个文件（`config.toml`）前发生异常中断或指纹失败，系统将处于**非原子中间状态**（尽管文档在 §4.2 和 §7.5.6 承认了此窗口靠漂移阻断兜底）。


* **修正建议**：在 WP3 设计中，必须明确：
1. **快照与指纹检查必须在任何写盘发生前对双文件一次性全部完成**（Batch Fingerprint Check）；
2. 提交时按 `auth.json -> config.toml` 顺序原子 replace；


3. 若第二个文件 replace 抛出 OS 级不可恢复异常，立即记录特定的 recovery flag，防止 `last_write` 处于部分失效的未定义状态。



#### 2. `rollback` 恢复“ACM 全新建文件”与非破坏性公理的冲突（A11 / WP8）

* **现状**：Pi 适配器会全新建 `models.json`（原本不存在）。A11 提出：rollback 恢复到写前状态意味着**直接删除该文件**（加 `--force`）。


* **问题**：这**违反了公理 2（非破坏性：未管字段必须无损保留）**。用户可能在 `use` 之后，让 Pi 运行并向 `models.json` 写入了自定义模型或配置。如果整文件物理删除，将造成用户不可逆的数据丢失。


* **修正建议**：
* **禁止直接 rm 物理文件**：当检测到目标文件写前为 `NOT_EXIST` 时，rollback 的安全行为应该是**将其重命名为 `models.json.acm_orphaned.<ts>` 归档**，而不是直接 unlink 删除。


* 终端明确打印：`"File was originally created by ACM; archived to models.json.acm_orphaned.<ts> instead of hard deletion."`



---

#### 1. 退出码与 typer usage-error 的冲突处理（A5）

* **分析**：Plan 中敏锐发现了 typer 默认 usage error 为 exit 2，与安全阻断 exit 2 冲突。


* **裁决**：**完全赞同 A5 建议**。必须在 typer entrypoint 顶层重写 click 的 `UsageError.exit_code = 1`，将所有参数解析/命令错误归入 exit 1，**把 exit 2 绝对纯净地留给 Safety Engine 的安全阻断（漂移/写锁/白名单越界）**。



#### 2. 状态判定中 active 缺失的歧义（A10 / WP4）

* **分析**：Plan 明确了 `init` 不写 active，首次 `use` 才写。


* **张力**：如果用户先跑 `init`，然后直接跑 `status`，此时 `active` 为 `None`，六态机算出来的每个 Agent 状态是什么？
* **裁决**：需在 WP4 中明确补充一条规则：当 `active` 为 `None` 时，所有已检测到的 Agent 统一展示为 `UNMANAGED`（或在 profile 列标注 `(none)`，状态不计算 OUT_OF_SYNC，只按 last_write 判定是否有漂移）。



#### 3. pydantic 依赖的取舍（A1）

* **裁决**：**保留 pydantic**。MVP 核心是对 TOML 三层结构、枚举、ENV 引用、URI 形状做强校验，手写 ~300 行 dataclass 校验容易隐藏 edge case 且测试维护成本高。既然锁已就绪，保留它符合 Pragmatism。



---

### 三、 细小问题速览（一笔带过）

* **A2（VMR 探测端点）**：实测 `/v1/models` 返回 200 且含 `vmr_protocol`，改为主探测端点完全正确，回写 Spec。


* **A4（`--verbose`）**：纳入。排障和 CI 必须输出 DEBUG 日志。


* **A6（`rollback` 旗标）**：仅暴露 `rollback [<agent>] [--force]`，不注册 `--hard/--to-tx`，符合极简原则。


* **A12（`rollback` 前快照）**：赞同。写操作前一律 append 快照，保证误 rollback 仍可自愈。


* **A13（PyPI 命名）**：提前准备 `acm-cli` 作为 fallback。
---

# Review of Feedbacks（综合评审意见）

> **评审时间**：2026-08-24 | **方法**：第一性原理 + PRINCIPLE v2.1 治理规格 + 本机实证
> **原则**：所有反馈均为建议，非指令；逐条独立判断，不服膺强硬措辞；与 PRINCIPLE 冲突时以 PRINCIPLE 为准。

## 0. 评审总则

1. **治理规格优先**：PRINCIPLE v2.1 是最高权威（核心原则、边界、数据模型、命令语义）。任何与 PRINCIPLE 冲突的反馈，除非用户明确决定走治理修订流程，否则不予采纳。
2. **第一性原理**：每一反馈从"字段所有权、非破坏性、显式暴露、可逆性"四条公理出发判断。
3. **本机实证**：涉及 Codex auth.json / detect 行为等可验证主张，以本机 2026-08-24 实测为准。
4. **"我们约定的简化"核查**：Agent 1 声称存在"漂移只展示不阻断/diff+apply 进 MVP"的事先约定——经 grep 全文（SPEC/PRINCIPLE/附录 D/Plan），**项目文档中无此约定**，且与 PRINCIPLE §4.3.1 + §7 明确冲突。若用户确在其他对话中达成过此约定，需走 PRINCIPLE 治理修订流程。

## 1. 合并主题索引

| 评审主题 | 对应原始条目 | 裁决 | 影响 Action Plan 修改点数 |
|---|---|---|---|
| T1 漂移阻断 | Agent 1 问题2 + Agent 3 P1 尾部 | ❌ 拒绝 | 0（保持 + 强化教育说明） |
| T2 diff/apply 进 MVP | Agent 1 问题3 | ❌ 拒绝 | 0 |
| T3 MVP 完成线后置 | Agent 3 P1 | ❌ 拒绝（采纳缓解措施） | 0（缓解方案由 T5 覆盖） |
| T4 rollback 语义（核心漏洞） | Agent 3 P2 | ✅ 全盘接受 | 6 处修改 |
| T5 rollback 归档而非删除 | Agent 4 问题2 | ✅ 全盘接受 | 4 处修改 |
| T6 detect 主判据 | Agent 3 P3 | 🔶 部分接受 | 3 处修改 + 待拍板 |
| T7 Writer 词法/语义分界 | Agent 3 P4 | 🔶 部分接受 | 4 处修改 |
| T8 Codex auth.json | Agent 3 P5 | 🔶 部分接受（结论采纳，论证修正） | 4 处修改 + 待实证 |
| T9 批处理指纹校验 | Agent 4 问题1 | 🔶 部分接受 | 1 处修改 |
| T10 init/VMR 拆包 | Agent 2 问题2 | ✅ 接受 | 3 处修改 |
| T11 use 编排与接口冻结 | Agent 2 问题3 | 🔶 部分接受 | 2 处修改 |
| T12 --dry-run 行为边界 | Agent 2 问题4 | ✅ 接受 | 1 处修改 |
| T13 active=None 状态展示 | Agent 5 问题2 | 🔶 部分接受 | 1 处修改 |
| T14 Core Config schema 必填/可选 | Agent 3 P6 | ✅ 接受 | 1 处修改 |
| T15 A 组待拍板项赞同 | Agent 5 全项 | ✅ 全部接受 | 0（维持原建议） |
| T16 细小问题 15 项 | 散布各 Agent | 逐条裁决见 §2.16 | 若干 |

---

## 2. 逐主题详细评审

---

### T1. 漂移"只展示不阻断"（Agent 1 问题2 + Agent 3 P1 尾部）

**原文摘要**：漂移应只展示、不阻断。阻断式体验差，用户会无脑 --force 使检测形同虚设。声称"这是我们约定的简化"。

**评审分析**：
- PRINCIPLE §4.3.1 语义不变量第 1 条明确定义："漂移没有自动修复路径：任何写入命令遇外部漂移默认阻断，`--force` 或先 `diff` 确认，不存在静默收敛。"
- PRINCIPLE §7 里程碑分级兑现原则将"显式暴露（漂移阻断、投影损失告警）"列为**公理级语义**——"在任何里程碑都必须成立，只允许兑现粒度分级，不允许语义降级"。
- 项目文档中**不存在**"漂移只展示不阻断"的约定（grep 实证：SPEC/PRINCIPLE/附录 D/Plan 均无）。
- 从第一性原理："显式暴露"公理要求 ACM 对"自己不知道的事"（外部修改）不能静默处理。阻断 + `--force` 是"用户知情确认"的最小实现；"用户会无脑 --force"是用户行为，不构成设计缺陷。

**裁决**：❌ **拒绝**。如需改变漂移语义，须走 PRINCIPLE 治理修订流程。

**合理内核**：阻断必须配套教育手段（阻断消息有 expected/found 具体值 + 建议 `use --dry-run`；status 展示漂移摘要）——Plan 已全部覆盖。

**对 Action Plan 的影响**：0（保持现状，添加教育手段说明注记）。

---

### T2. diff/apply 进 MVP（Agent 1 问题3）

**原文摘要**：diff/apply 是 MVP 骨架命令，踢出去是致命缺失。没有 diff 用户不知道为什么阻断；没有 apply 手改 config.toml 后无法重新投影。Plan §4.2 引用 PRINCIPLE §4.3.6 但无 apply，自相矛盾。

**评审分析**：
- **diff**：PRINCIPLE §7 触发式升级表明确 diff 触发条件为"--dry-run 与漂移阻断消息不足以支撑'先看再写/排查漂移'工作流"。MVP 的阻断消息（expected/found 具体值）+ `use --dry-run` + status 漂移摘要已构成"教育"基础。规格已裁决。
- **apply**：Agent 1 说"手改 config.toml 后无法重新投影，只能切到其他 Profile 再切回来"。**此论据不成立**：`use` 是"设为激活并立即收敛"，重复 `use <同一profile>` 是幂等的——如果 Desired State 因手改 config.toml 而变化，`use` 会重新投影并收敛。apply 的"只收敛不切换"语义正是 `use` 的子集。当 profile 不变时，`use` 等价于 `apply`。
- **"自相矛盾"**：PRINCIPLE §4.3.6 是"跨 Agent 批处理原则"——适用于所有批量投影命令（use/rollback/release 均批量操作），**不是 apply 专属**。引用正确，无矛盾。

**裁决**：❌ **拒绝**。

**对 Action Plan 的影响**：0（保持）。

---

### T3. MVP 完成线后置——Pi/PyPI/漂移阻断降为 M2 后触发项（Agent 3 P1）

**原文摘要**：完成线改回 M2；Pi、PyPI、漂移阻断从不可降级降为触发项。Pi 全新建文件+rollback=删文件是最危险回滚语义；PyPI 包名冲突会卡住；漂移阻断是终局行为。

**评审分析**：
- **Pi**：SPEC 附录 D 已对"砍 Pi 的提议"做出裁决："拒绝砍 Pi 的提议（真实在用 + 注册式投影形态 + 全新建文件场景），改为 Slice 2 交付。"
- **PyPI**：SPEC D5 定义"MVP 只做一个主路径——发布到 PyPI"；包名冲突风险有预案（A13），不构成必然卡住。
- **漂移阻断**：公理级语义（T1），不可降级。
- **合理担忧**：Pi 的全新建文件+rollback 删除确实是"最危险回滚语义"——但**解决方案是加固 rollback 语义（T5 归档方案），而非把 Pi 移出 MVP**。

**裁决**：❌ **拒绝**。采纳缓解措施（T5 归档方案替代硬删除）。

**对 Action Plan 的影响**：0（保持 MVP 完成线定义；T5 的修改已覆盖缓解）。

---

### T4. rollback 语义自相矛盾——**本评审中最高价值的发现**（Agent 3 P2）

**原文摘要**：三处规定对不上——① rollback = 恢复最新整文件快照；② A12 恢复前再快照一次；③ last_write.backup_id 有记录但 rollback 流程没说用它。按 ①+② → 最新快照就是刚写下的 → no-op。恢复后 last_write 不更新 → DRIFTED → 下次 use 被阻断。

**评审分析**：
- **完全成立**。这是自检时遗漏的真漏洞。
- 核心矛盾：Snapshot 的 `<ts>` 命名是 UTC 纳秒（字典序最大 = 最新），A12 恢复前写新快照 → 字典序最大变成刚写的那份 → 恢复"最新" = 恢复刚写的那份 → 无效果。
- 第二漏洞：恢复后 `last_write` 不更新 → 盘上值回到写前，但 last_write 仍存投影后值 → 下次 use 被 DRIFTED 阻断。

**裁决**：✅ **全盘接受**。采纳三项修正：

1. **恢复目标 = `last_write.backup_id` 指向的快照**（非字典序最大）。恢复前快照（A12）保留但**明确排除在恢复目标之外**（标记为"恢复前置快照"）。
2. **恢复成功后更新 `last_write`**：字段值 = 恢复后的值（写前值），`profile` 保留原投影 profile 名（或标记为 `restored`），`backup_id` 更新为新写入的恢复前快照 ID。
3. **删除"最新快照"表述**，改为"目标快照 = `last_write.backup_id` 记录的那份"（若 `backup_id` 缺失则 fallback 字典序最大，但常理不应发生）。

**补充设计**：恢复后若 Agent 在窗口期写入过新值，整文件恢复会覆盖——这是 MVP 整文件恢复的固有语义（SPEC 已认可），阻断消息与 `--force` 显式化。

**对 Action Plan 的影响**：6 处修改——§4.2 指纹与快照行/原子写行、WP3 快照检索函数、WP5 rollback 任务项、A12 措辞、验收 3 措辞、§4.2 幂等行。

---

### T5. rollback 恢复"ACM 全新建文件"——归档而非删除（Agent 4 问题2）

**原文摘要**：A11 的 rollback 整文件删除违反公理 2（未管字段不可逆丢失）。建议 rename 归档为 `<file>.acm_orphaned.<ts>`，显式打印文案。

**评审分析**：
- 成立。直接 unlink 意味着用户或 Agent 在写入后新增的内容（如 Pi 向 models.json 写入自定义模型）被不可逆删除。
- rename 归档是原子操作，成本趋近于零，且与 Append-only 快照哲学一致（保留历史）。
- 与 T4 联动：归档动作记录在 rollback 结果中。
- 验收 3"rollback 回到写前字节"对"创建文件"场景应改为"文件被归档（不再在位）+ 归档文件字节 == 写前（即空/原内容）"；归档文件路径明文输出。

**裁决**：✅ **全盘接受**。

**对 Action Plan 的影响**：4 处修改——A11 全文重写（归档+删除）、WP8 新建文件回滚语义、WP3 流水线中 NOT_EXIST 哨兵的恢复动作定义、WP5 rollback 任务项（恢复时判断 created 文件→归档+文案）。

---

### T6. detect 主判据（Agent 3 P3）

**原文摘要**：detect 以配置文件存在为准，没跑过的 Agent 被跳过 → 验收 1 在全新机器失败。建议：detect 主判据改为配置目录或可执行文件；目标文件不存在则走 ACM 创建（与 Pi 同路径）。

**评审分析**：
- 成立：SPEC §7.4 的 detect 定义写"配置目录/文件存在 = 已安装（主判据）"，但"装好 Agent 从未运行"的场景确实存在。
- 从第一性原理：ACM 的"接管"是针对配置文件投影；如果 Agent 从未运行过、没有配置文件，ACM 能否创建？——已在 Pi 上实现（全新建文件），机制相同。
- 风险：detect 以可执行文件为准可能误报（安装但不想管的 Agent）。但 ACM 是非破坏性、幂等的，不 `use` 它即可。
- 建议调整为：**detect 主判据 = "可执行文件或配置目录存在"**；配置文件存在时优先（快路径）；配置文件不存在且可执行存在 → 标记为"可接管（将创建）"，`use` 时创建文件（与 Pi 同机制）。统一了 Pi 与 Claude/Codex 的创建路径。
- 需回写 SPEC §7.4 与适配矩阵 detect 列。

**裁决**：🔶 **部分接受**。接受 detect 主判据调整，但保留"配置文件存在"作为优先级信号；创建文件场景统一走 T5 归档机制。

**需用户确认**：detect 放宽范围是否可接受（误报风险 vs 开箱增益）。

**对 Action Plan 的影响**：3 处修改——§4.1 detect 定义、WP6/7/8 detect 任务项、SPEC §7.4 回写。

---

### T7. Writer 词法保真进写通道——运行时语义/词法分界（Agent 3 P4）

**原文摘要**：① JSON"其余字节级不变"做不到（冒号空格/缩进/空行/数字写法）；② runtime tree_diff 挡写入 → 工具变"Writer 正确性的人质"；③ int/float 严格等价主动收紧误报。建议：写通道只保证未管键语义；词法只做测试夹具不挡写入；JSON 不承诺字节级；WP2 硬前置可取消；SIGKILL/双进程后置。

**评审分析**：
- **① 成立**：SPEC §7.5.4 明确"不使用'100% 保留'这类无法对所有输入负责的绝对承诺"，JSON 词法保证是"缩进风格自动探测匹配；末尾换行保留"——**不是字节级**。Plan 写"整值替换后其余字节级不变"过强。修正为"对金样 fixture 子集断言词法（fixture 界定承诺）"，通用表述改为"语义保证 + 键序保证 + 缩进风格匹配 + 末尾换行保留"。
- **② 成立但需精确**：PRINCIPLE §3.4 不变量 4 明确"未管理节点**语义级不变**（硬承诺）"。所以 runtime 只应断言语义级（结构 + 值），**词法级差异不计入 runtime 阻断**。Plan 的 tree_diff 在 Safety 阶段③ 应改为语义级 tree_diff（数值等价容差）。
- **③ 成立**：int/float 严格等价在语义级是误报（`1` vs `1.0` 值相同）。改为数值等价容差。
- **拒绝 WP2 后置**：SPEC §11.3 明确"Format Writer round-trip 单测先于任何适配器交付"——保留前置，但范围缩小为**语义 round-trip + 能力声明**。
- **拒绝 SIGKILL/双进程后置**：SPEC §11 MVP 期测试集 + §12 验收 4 明确要求这两项。各一例本就最低限。

**裁决**：🔶 **部分接受**。

**对 Action Plan 的影响**：4 处修改——WP2 验收措辞、WP3 ③ tree_diff 改为语义级、§4.2 解析树 diff 行 int/float 容差、§4.2 非管节点断言行补充"语义级"。

---

### T8. Codex auth.json——env_key 单文件方案优先（Agent 3 P5）

**原文摘要**：Codex 惯用 `env_key` 指向环境变量，auth.json 不必进 `config_paths`。双文件事务/中途失败/孤儿 key 整段可省。auth.json 含 OAuth token（双重所有权）。建议：先本机实证 env_key 单文件可跑通，能则 auth.json 移出 MVP。

**评审分析**：
- **本机实证**（2026-08-24 12:00）：
  - `~/.codex/auth.json` 结构：`auth_mode` (str)、`OPENAI_API_KEY` (**null**)、`tokens.id_token/access_token/refresh_token/account_id`、`last_refresh`。**这是 Codex 运行态 OAuth 文件**，由 Agent 运行时持续写入（公理 2 的双重所有权典型场景）。
  - `~/.codex/config.toml` 现**无** `model_providers` 表。
  - Codex 的 `model_providers.<id>.env_key` 语义：Codex 运行时读取该环境变量值作为 API key（已知产品行为）。
- **结论采纳**：MVP 优先采用 **env_key 单文件方案**——ACM 只写 config.toml（`model_providers.<id>.env_key = "VMR_KEY"`），Codex 运行时自读环境变量。这消除了：明文落盘、凭证文件双重所有权、双文件事务复杂度。
- **论证修正**：P5 说"违反原则（SSOT 只存 `${ENV}`）"——**不成立**。PRINCIPLE §3.2 约束对象是 Core Config 与 ACM 自身存储，**不是限制 Agent 配置的投影格式**。Claude settings.json env 块写明文也是投影必要输出，同构且不违反原则。但 env_key 方案确实**更贴合** credential 引用哲学（引用贯穿到 Agent 侧），所以采纳结论、修正论据。
- **实施要求**：WP7 先本机实证 env_key 单文件可跑通（VMR 无鉴权 / 有鉴权两态）；可行则 auth.json 后置（触发条件：用户需 ACM 托管 key 且 env_key 不可行）。
- **双文件机制保留**：WP3 多文件 + 批处理指纹（T9）保留为 Safety Engine 通用能力（Pi 的 settings.json + models.json、未来 Aider 仍需要多文件）。

**裁决**：🔶 **部分接受**（结论采纳，论证修正）。

**需用户确认**：env_key 实证结果（需本机实际操作验证）；若 env_key 不可行，回退方案。

**对 Action Plan 的影响**：4 处修改——WP7 任务项重写为"实证 env_key 单文件方案 → 可行则 auth.json 后置；不可行再双文件（标注凭证落盘）"；§4.2 双文件提交顺序行改为"备选方案"；SPEC §8 适配矩阵 Codex 行 auth.json 降级为"备选"；WP3 流水线注释更新。

---

### T9. 双文件指纹批处理（Agent 4 问题1）

**原文摘要**：逐文件独立走 ①~⑤ 存在非原子中间状态。建议：快照与指纹对双文件一次性全部完成（Batch Fingerprint Check），提交按 auth.json → config.toml 顺序原子 replace；第二个文件 replace 失败时记录 recovery flag。

**评审分析**：
- 成立：逐文件独立走 ①~⑤ 有跨文件窗口。SPEC §7.5.1 三阶段设计的精神是"阶段 1 全部文件快照/H0 → 阶段 3 全部文件 pre-commit 校验通过后再逐个替换"——但 Plan 的流水线描述未明确"批处理"语义。
- 采纳：WP3 明确"快照（阶段 1）、内存修改+断言（阶段 3.1）、pre-commit 指纹校验（阶段 3.2）对全部文件一次性完成，全部通过后才开始按序替换（阶段 3.3）"。
- **拒绝** recovery flag：SPEC §7.5.6 明确"无 Journal 时期无重量级 WAL 状态机"；MVP 崩溃模型 = 漂移阻断 + rollback --hard 兜底；增加持久化 flag 与简化哲学冲突。

**裁决**：🔶 **部分接受**（接受批处理指纹，拒绝 recovery flag）。

**对 Action Plan 的影响**：1 处修改——WP3 流水线 ④ 措辞明确"批处理指纹：全部文件的 pre-commit 校验一次性完成，全部通过后才进入替换"。

---

### T10. init/VMR 探测拆包（Agent 2 问题2）

**原文摘要**：VMR 探测（多端点 HTTP + 提案构建 + 交互确认 + 配置生成）是独立功能模块，WP5 规模超 L。建议拆 WP5a（VMR 探测与提案构建）+ WP5b（CLI 命令面）。

**评审分析**：成立。WP5 当前包含：init（含 VMR 探测 + 提案 + 交互 + 生成）+ use + status + rollback + 全局旗标 + 退出码 + 掩码 + 日志。确实过载。拆包后：WP5a（vmr.py 探测+提案构建，独立可测）+ WP5b（CLI 命令面组装，依赖 WP5a + WP1-WP4）。规模：WP5a=S/M，WP5b=M。

**裁决**：✅ **接受**。

**对 Action Plan 的影响**：3 处修改——§1.2 任务包表新增 WP5a 行、§1.3 依赖图更新、原 WP5 章节拆两节。

---

### T11. use 编排与接口冻结（Agent 2 问题3）

**原文摘要**：WP5 的 use 完整编排流程未成文；WP4 与 WP5 并行开发时接口需冻结（ResolvedProfile 结构 + plan() 签名）。

**评审分析**：
- 成立：编排流程需成文，接口需冻结。
- **修正**：Agent 2 描述的流程"读 active → 选 profile"不准确——`use` 的 profile 来自**命令行参数**，`active` 是 `use` 的**输出**（写入）而非输入。已在自检中修正（最终版约定了正确流程：config 缺失 guard → 校验 profile → resolve → 写 active → per-agent plan → 漂移闸 → 写通道 → 告警聚合）。
- 采纳：WP4 验收加"导出稳定公共接口（ResolvedProfile 结构 + plan() 签名 + FieldOp 类型）"。

**裁决**：🔶 **部分接受**（采纳接口冻结建议，编排流程已于自检修正）。

**对 Action Plan 的影响**：2 处修改——WP4 验收加接口冻结条款；WP5 任务项 1 加完整编排注释（确认已正确）。

---

### T12. `--dry-run` 行为边界（Agent 2 问题4）

**原文摘要**：各 WP 未明确 --dry-run 具体行为（是否计算漂移、是否写 active、是否执行 VMR 探测）。建议 init --dry-run 只出提案不写盘，status --dry-run 正常输出差异，use --dry-run 计算不写。

**评审分析**：
- 已自检修正部分（不写 active/快照/last_write），但需正式成文。
- 补充：**status 天然只读，不接受 `--dry-run`**（或接受但忽略）；rollback 支持 `--dry-run`（展示将恢复的快照、归档动作、影响文件）。

**裁决**：✅ **接受**。

**对 Action Plan 的影响**：1 处修改——WP5 任务项加 `--dry-run` 行为规范表（init/use/rollback/status 各列清晰）。

---

### T13. active=None 时 status 展示（Agent 5 问题2）

**原文摘要**：init 后直接 status，active=None 时各 Agent 状态是什么？建议统一 UNMANAGED 或 profile 列标 (none)，不计算 OUT_OF_SYNC，只按 last_write 判定漂移。

**评审分析**：
- 成立：此场景必须定义。
- 采纳：active=None 时，profile 列显示 `(none)`；已检测 Agent 无 last_write → UNMANAGED；有 last_write → 按漂移判定展示（DRIFTED 或与 last_write 一致则显示 last-write 状态，避免用 SYNCED 污染语义——SYNCED 严格定义需要 desired）；不计算 OUT_OF_SYNC（无 desired 可比）。
- 细化：SYNCED 枚举不与 active=None 场景混用。

**裁决**：🔶 **部分接受**（核心规则采纳，细化避免状态语义污染）。

**对 Action Plan 的影响**：1 处修改——WP4 六态任务项加 active=None 时的展示规则。

---

### T14. Core Config schema 必填/可选（Agent 3 P6）

**原文摘要**：MVP schema 强制校验 capabilities/reasoning/context_window 等，但大半投影不进去，init 生成配置时填一堆无用字段，use 再告警"无法表达"。建议 MVP schema 只强制 providers.{protocol,base_url,api_key}、models.{provider,id}、profiles.main。

**评审分析**：
- 成立。MVP 只有 2-3 个适配器，投影能力有限。强制校验投影不进去的字段 = 自扰。
- 采纳：MVP 必填 = `providers.{protocol,base_url,api_key}`、`models.{provider,id}`、`profiles.main`（至少一个 profile）；其余字段（context_window / max_output_tokens / temperature / reasoning / capabilities / 角色槽位）**全部可选**——写了则校验+尽力映射+不能映射告警（投影损失机制），不写则沉默。
- 与投影损失告警机制天然一致。VMR 提案生成短文件（仅必填字段）。

**裁决**：✅ **接受**。

**对 Action Plan 的影响**：1 处修改——WP1 结构校验规则表改为"必填/可选"两档。

---

### T15. A 组待拍板项的赞同（Agent 5 全项）

**原文摘要**：A1 pydantic 保留（理由：手写 300 行校验易藏 edge case）、A2 VMR 探测端点回写 Spec、A4 --verbose 纳入、A6 rollback 旗标仅 `[<agent>] [--force]`、A12 恢复前快照赞同、A13 acm-cli fallback。

**评审分析**：全部与 Plan 建议一致。A12 需与 T4 联动修正"不得成为恢复目标"。

**裁决**：✅ **全部接受**。

**对 Action Plan 的影响**：0（维持原建议；A12 已在 T4 修改中覆盖）。

---

### T16. 细小问题逐条裁决

| # | 来源 | 问题 | 裁决 | 决定 | 修改点 |
|---|---|---|---|---|---|
| C1 | Agent 3 | ruamel.yaml 为 Aider 锁进运行时依赖，预付款 | ⚠️ 待拍板 | 默认按 SPEC D2 预算保留（D6 要求 MVP 前置锁定 ruamel 能力）；若用户坚持最小化则可移除（P1 前重引） | §2.2 |
| C2 | Agent 3 | 错误文案提 `acm doctor` 但命令不在 MVP | ✅ 接受 | 改：MVP 文案不提 doctor（"升级 acm 或手改 version"） | WP1 task 1 |
| C3 | Agent 3 | `--verbose` 在 A4 待拍板但 WP5 命令表已写 | ✅ 接受 | 直接定为纳入（A4 默认纳入，消除不一致） | A4/WP5 |
| C4 | Agent 3 | `rollback --force` 与 `use --force` 同旗标不同义 | ✅ 接受 | 保持 `--force`，文档化 per-command 语义表 | WP5 旗标表 |
| C5 | Agent 3 | 验收 2"10 次循环后注释不变"对 JSON 无意义 | ✅ 接受 | 改为"未管键（JSON）/ 未管键+注释（TOML）" | §7 验收 2 |
| C6 | Agent 3 | `${VMR_KEY:-}` 空默认是否过正则 | ✅ 接受 | WP1 边界用例补 `${VAR:-}`（空默认值） | WP1 测试计划 |
| C7 | Agent 3 | Windows msvcrt"保编译不验收" | ✅ 接受 | MVP 明确仅 macOS/Linux，代码不含 Win 分支 | A15/WP3 |
| C8 | Agent 3 | docstring + mypy strict 过程税 | 🔶 部分接受 | 不阻塞 WP0 验收；docstring 仅要求公开 API | WP0 验收标准 |
| C9 | Agent 3 | P2/P3/P5 应优先拍板（比 A1 pydantic 更该先拍） | ✅ 接受 | 并入待拍板清单（本 review 已给出默认裁决） | 新增 C 组待拍板 |
| C10 | Agent 5 | A5 usage-error 退出码赞同 | ✅ 接受 | 维持 Plan 建议（拦截 usage 错误→exit 1） | — |

---

## 3. 汇总表

| 主题 | 裁决 | 合理内核 | 修改点数量 | 优先级 |
|---|---|---|---|---|
| T1 漂移阻断 | ❌ 拒绝 | 教育手段说明 | 0 | — |
| T2 diff/apply 进 MVP | ❌ 拒绝 | 阻断消息+--dry-run 已覆盖 | 0 | — |
| T3 MVP 完成线后置 | ❌ 拒绝 | T5 归档缓解 | 0 | — |
| T4 rollback 语义漏洞 | ✅ 全盘接受 | — | 6 | **P0** |
| T5 归档而非删除 | ✅ 全盘接受 | — | 4 | **P0** |
| T6 detect 主判据 | 🔶 部分接受 | 需用户确认 | 3 | **P0（待拍板）** |
| T7 Writer 语义/词法分界 | 🔶 部分接受 | — | 4 | P1 |
| T8 Codex auth.json | 🔶 部分接受 | 需实证 | 4 | **P0（待实证）** |
| T9 批处理指纹 | 🔶 部分接受 | — | 1 | P1 |
| T10 init/VMR 拆包 | ✅ 接受 | — | 3 | P1 |
| T11 use 编排与接口冻结 | 🔶 部分接受 | — | 2 | P1 |
| T12 --dry-run 行为边界 | ✅ 接受 | — | 1 | P1 |
| T13 active=None 状态展示 | 🔶 部分接受 | — | 1 | P1 |
| T14 Core Config schema | ✅ 接受 | — | 1 | P1 |
| T15 A 组待拍板赞同 | ✅ 全部接受 | — | 0 | — |
| T16 细小问题 | 15 项逐条裁决 | — | 若干 | P2 |

**裁决分布**：✅ 全盘接受 5 项 / 🔶 部分接受 7 项 / ❌ 拒绝 3 项 / ⚠️ 待拍板 1 项（C1 ruamel）

---

## 4. 结论与待用户确认/拍板清单

### 4.1 本次评审最重要的发现

Agent 3 的 **P2（rollback 语义漏洞）** 发现了自检中遗漏的循环死锁——恢复"最新快照" + A12 恢复前再快照 → no-op；恢复后 last_write 不更新 → DRIFTED 死循环。**最高质量反馈，无保留采纳**。

### 4.2 需用户拍板/确认的清单

| 编号 | 主题 | 默认裁决 | 您的决定（2026-08-24 已回执） |
|---|---|---|---|
| **D1** | T6 detect 主判据放宽为"可执行文件或配置目录存在"（误报风险 vs 开箱增益） | 采纳 | ✅ **已确认：按建议方案处理** |
| **D2** | T8 Codex env_key 实证结果：若本机验证 env_key 单文件可跑通，auth.json 移出 MVP 受管范围 | 采纳（待实证后确认） | ⏳ **保留事项：待核实确认**（文档按 env_key 默认方案写入，auth.json 列为 D2 备选，标注实证门） |
| **D3** | C1 ruamel.yaml 预付款（MVP 移除/保留） | 默认按 SPEC 保留 | ✅ **已确认：MVP 阶段移除 Aider 支持**（ruamel 移出 MVP 依赖，SPEC D2/D6 回写） |
| **D4** | C7 Windows 支持（MVP 明确仅 macOS/Linux/不含 Win 分支） | 收紧 | ✅ **已确认：MVP 仅 macOS/Linux，删 Win 分支** |
| **D5** | 漂移阻断"教育手段"是否需额外增强（如 MVP 内加 `acm diff --summary` 子命令？） | 保持现状（阻断消息+--dry-run+status） | ✅ **已确认：按建议方案处理（保持现状）** |
| **D6** | Agent 1 声称的"约定"是否存在（用户是否在其他对话中与 Agent 达成过） | 项目文档中无此约定 | ✅ **已确认：无此约定**（PRINCIPLE 未提及即不存在；Agent 1 的"我们约定的简化"主张无依据，不予采信） |

> **决策回执（2026-08-24）**：以上 D1–D6 用户已逐项裁决，本评审对应的修改已按裁决落地执行（见 §5 修改大纲与 Action Plan/SPEC 工作区改动）。

### 4.3 确认后即可执行的修改

以下修改不依赖拍板（T4/T5/T7/T9/T10/T11/T12/T13/T14 已明确裁决），待您确认本评审后即可按修改大纲执行。

> **执行状态（2026-08-24）**：用户已确认本评审，修改大纲已全部落地执行（Action Plan AP-01~31、SPEC SP-01~04），改动留在工作区未 commit。

---

## 5. Action Plan 修改大纲（待确认后执行，暂不改文档）

### 5.1 修改点清单

| 编号 | 涉及主题 | 修改位置 | 修改内容摘要 | 优先级 |
|---|---|---|---|---|
| AP-01 | T4 | §4.2 指纹与快照行 / 原子写行 | 恢复目标=`last_write.backup_id` 指向的快照；删"最新快照"；非管节点断言行补充"语义级" | P0 |
| AP-02 | T4 | WP3 快照检索函数 | `latest_snapshot_for_rollback(agent, backup_id)`：按 backup_id 定位 | P0 |
| AP-03 | T4 | WP5 rollback 任务项 | 恢复前快照标记为"恢复前置快照"排除在目标外；恢复后更新 last_write | P0 |
| AP-04 | T4 | A12 措辞 | 补充"恢复前快照排除在恢复目标外" | P0 |
| AP-05 | T4 | 验收 3 措辞 | 删除"最新"定语；添加"恢复目标由 backup_id 确定" | P0 |
| AP-06 | T5 | A11 全文重写 | 删除→归档 rename + 文案；涉及 WP8 回滚语义 | P0 |
| AP-07 | T5 | WP3 流水线 ② | NOT_EXIST 哨兵 → 恢复时 rename 归档（非 unlink） | P0 |
| AP-08 | T5 | WP5 rollback 任务项 | 归档动作判断（created 文件→归档+文案） | P0 |
| AP-09 | T5 | §7 验收 3 | 创建文件场景：归档文件字节 == 写前 | P0 |
| AP-10 | T6 | §4.1 detect 定义 | 主判据改为"可执行文件或配置目录存在"；配置文件缺失→创建 | P0（待拍板 D1） |
| AP-11 | T6 | WP6/WP7/WP8 detect 任务项 | 同步调整 detect 逻辑 | P0 |
| AP-12 | T7 | WP2 验收措辞 | 去"字节级不变"→"fixture 界定词法承诺"；通用表述改"语义+键序+缩进风格+末尾换行" | P1 |
| AP-13 | T7 | WP3 ③ tree_diff 断言 | 改为语义级（数值等价容差）；词法差异不计入 runtime 阻断 | P1 |
| AP-14 | T7 | §4.2 解析树 diff 行 | 补充 int/float 容差说明；标注"语义级，非词法" | P1 |
| AP-15 | T8 | WP7 任务项重写 | 先实证 env_key 单文件（可行则 auth.json 后置）；不可行再双文件 | P0（待拍板 D2） |
| AP-16 | T8 | §4.2 双文件提交顺序行 | 改为"备选方案，仅 auth.json 需要时启用" | P0 |
| AP-17 | T8 | §1.2 WP7 表 | 目标改"config.toml（env_key 单文件）" | P0 |
| AP-18 | T9 | WP3 流水线 ④ 措辞 | 明确"批处理指纹：全部文件 pre-commit 校验一次性完成，通过后才替换" | P1 |
| AP-19 | T10 | §1.2 表 + §1.3 图 + WP5 章节 | 拆 WP5a（VMR 探测+提案）+ WP5b（CLI 组装） | P1 |
| AP-20 | T11 | WP4 验收加接口冻结条款 | "导出稳定公共接口（ResolvedProfile/FieldOp/plan 签名）" | P1 |
| AP-21 | T12 | WP5 任务项加 --dry-run 规范表 | init/use/rollback/status 各列 | P1 |
| AP-22 | T13 | WP4 六态任务项 | active=None 展示规则（(none)+UNMANAGED/漂移状态） | P1 |
| AP-23 | T14 | WP1 校验规则表 | 必填/可选两档；MVP 必填缩小 | P1 |
| AP-24 | C2 | WP1 task 1 文案 | 去 doctor 提法 | P2 |
| AP-25 | C3 | 确认 A4 纳入 / WP5 命令表 | --verbose 定案 | P2 |
| AP-26 | C4 | WP5 旗标表 + 命令帮助 | --force per-command 语义表 | P2 |
| AP-27 | C5 | §7 验收 2 措辞 | JSON/TOML 区分 | P2 |
| AP-28 | C6 | WP1 测试计划 | 补 `${VAR:-}` 空默认边界用例 | P2 |
| AP-29 | C7 | A15 / WP3 lock.py | 删除 Win 分支，明确仅 macOS/Linux | P2 |
| AP-30 | C8 | WP0 验收标准 | docstring 不阻塞（仅公开 API） | P2 |
| AP-31 | C1 | §2.2 依赖表 | ruamel 待拍板后落定 | P2（待拍板 D3） |

### 5.2 SPEC 回写点（走 SPEC 治理流程）

| 编号 | 位置 | 回写内容 |
|---|---|---|
| SP-01 | SPEC §7.4 detect 定义 | 主判据调整为"可执行文件或配置目录存在"（T6） |
| SP-02 | SPEC §8 适配矩阵 Codex 行 | auth.json 从"目标文件"降为"备选"（T8），标注实证日期 2026-08-24 |
| SP-03 | SPEC §9 VMR 探测顺序 | 已由 A2 覆盖（healthz→/v1/models→fallback） |

### 5.3 不改动项

- **PRINCIPLE**：无修改。漂移阻断等公理级保持。如用户想改漂移语义，需走 PRINCIPLE 治理修订流程。
- **T1/T2/T3** 拒绝项：保持现状。
- **T15** 已有建议项：维持原建议。

---

*评审结束。以上所有修改在您确认后执行。*---

# Round 2 Review（第二轮综合评审意见）

> **评审时间**：2026-08-24 | **方法**：逐项核对当前 Action Plan **实际文本**（非反馈转述）+ 第一性原理 + PRINCIPLE v2.1 + 用户核心哲学（MVP 聚焦、尽量简单、不强行加依赖、不扩范围）
> **结论形态**：✅ 全盘接受 / 🔶 部分接受（注明取舍）/ ❌ 拒绝（含理由）/ ⏳ 已知问题（记录、MVP 不解决）
> **重要声明**：部分反馈对文档现状的转述已过时或不准，本评审一律以文档实际文本核实后判断。

## 0. 核实方法说明

- 本轮反馈来源分为「二（重大 3 项）」「三（次要 6 项）」「R1–R6」「细小残留」四块，合并去重后共 **20 个评审主题（E1–E20）**。
- 每个主题：**核实**（问题在当前文档是否真实存在）→ **分析**（第一性原理 + PRINCIPLE）→ **裁决** → **修改建议**（仅建议，不执行）。

## 1. 合并主题索引

| 主题 | 来源 | 核实 | 裁决 |
|---|---|---|---|
| E1 FieldOp.old 职责错位 | 二.1 + R5.2 | ✅ 属实 | ✅ 接受（与 R5.2 合并解决） |
| E2 崩溃一致性窗口未告知 | 二.2 | ✅ 属实 | ✅ 接受（纯文档告知） |
| E3 幂等边界：漂移到期望值 | 二.3 | ✅ 属实 | ✅ 接受（精化判定顺序） |
| E4 rollback 后 last_write"或"歧义 | R3 | ✅ 属实 | ✅ 接受（定唯一算法） |
| E5 last_write 缺失 ≠ 漂移阻断 | R4 | ✅ 属实 | ✅ 接受 |
| E6 --dry-run Desired 来源 + created 归属 | R5 | ✅ 属实 | ✅ 接受 |
| E7 active=None 六态无合法值 | R6 | ✅ 属实 | 🔶 部分接受（精化） |
| E8 tree_diff 两套规则（严格等价残留） | R1 | ✅ 属实 | ✅ 接受 |
| E9 命令/退出码不一致（--hard / exit4 / 删除回滚） | R2 | ✅ 属实 | ✅ 接受 |
| E10 双文件事务残留文案 | 细小残留 | ✅ 属实 | ✅ 接受 |
| E11 WP5→WP5b 旧引用 | 细小残留 | ✅ 属实 | ✅ 接受 |
| E12 §9.1 缺 detect 决策行 | 细小残留 | ✅ 属实 | ✅ 接受 |
| E13 流水线步数表述 | 三.1 | ✅ 属实 | ✅ 接受（措辞统一） |
| E14 恢复前置快照标记方式 | 三.2 | ❌ 不必要 | ❌ 拒绝（被 E4 机制取代，无需标记） |
| E15 归档文件留存规则 | 三.3 | ✅ 属实 | ✅ 接受（一句澄清） |
| E16 实证门标准/工作量 | 三.4 | 🔶 部分属实 | 🔶 部分接受（加实证标准；拒工作量数字） |
| E17 active 写入时机 | 三.5 | ⚠️ 其"后写 active"建议错误 | 🔶 部分接受（拒其改法，接受"文档说明"） |
| E18 术语表未同步 | 三.6 | ✅ 属实 | ✅ 接受 |
| E19 Pi apiKey 明文注 | 细小残留 | ⚠️ 可选 | 🔶 部分接受（加一句注） |
| E20 ruamel 移除一致性 | 细小残留 | ✅ 一致 | ✅ 无动作 |

---

## 2. 逐项详细评审

---

### E1. `FieldOp.old` 职责错位（二.1 + R5.2）

**核实**：属实。§4.1 定义 `FieldOp(file, path, old, new, created)` 为 `plan()` 输出，同时 `plan()` 被强制"运行时零 I/O、纯函数"。适配器不读盘就无法获知 `old`；同理 `created`（依赖文件是否存在）也无法由纯函数判定。文档未说明 `old/created` 由谁填充。

**分析**：`old` 与 `created` 本质上是"磁盘当前事实"，属于 Safety/状态层的读取职责；`plan()` 只负责"期望值映射"（`file/path/new`）。把磁盘事实放进 plan 输出 = 接口设计缺陷，且与"适配器只编译不写盘"的治理约束（PRINCIPLE §3.4 不变量 2）冲突。

**裁决**：✅ **接受**。拆分为两层契约：
- `plan()` 输出 `PlannedOp(file, path, new)`（纯期望值，无磁盘事实）；
- Safety 依据磁盘读取（H0 == NOT_EXIST 判定 `created`；当前值读取判定 `old`）扩展为完整 `FieldOp(file, path, old, new, created)` 供 Writer/幂等/漂移使用。
- R5.2 的"created 由 Safety 打标"与之一致，一并解决；无需引入 `exists: bool` 传参。

**修改建议**：M-01（§4.1 FieldOp 契约拆分 + §4.1/§3.3 补充 created 归属说明）。

---

### E2. 配置与 last_write 崩溃一致性窗口未告知（二.2）

**核实**：属实。⑤ 原子替换 → ⑥ 覆写 last_write 之间的 SIGKILL 窗口在文档中仅"崩溃安全"笼统提及，未作为已知正常行为告知用户。

**分析**：MVP 不引入 WAL 状态机是正确取舍（SPEC §7.5.6 明确）；但该窗口确属"设计如此"，用户遇到会误判为 bug。告知成本为零（文档 + 帮助文案）。

**裁决**：✅ **接受**（纯文档补充，不改实现）。在风险与对策 + `use`/`rollback` 帮助文案注明："极端崩溃可能配置已更新但状态未记录，属保护机制正常表现，`acm use <profile> --force` 可重新对齐"。

**修改建议**：M-20。

---

### E3. 幂等边界：漂移到期望值（二.3）

**核实**：属实。§4.2 幂等规则"Desired == Current 且无漂移 → no-op"未覆盖"Current == Desired 但 Current ≠ last_write（外部修改恰好改成了目标值）"。

**分析**：从第一性原理——"漂移阻断"的目的是**防止 ACM 静默覆盖外部修改**。当 Current == Desired 时，没有写入动作、没有覆盖风险，阻断纯属摩擦。而"显式暴露"公理要求外部修改不被静默处理——用 status/阻断消息中的提示即可满足（无写盘、无静默覆盖）。因此正确判定顺序是：
1. 若所有受管字段 **Current == Desired** → no-op（exit 0），即使存在漂移也仅提示不阻断；
2. 仅当存在 **Current != Desired** 的字段、且其中含漂移字段 → 阻断（exit 2）。
这不违反 PRINCIPLE §4.3.1（阻断针对"要发生的写入"；无写入则无阻断必要），且消除无意义 `--force`。

**裁决**：✅ **接受**（精化幂等/漂移判定顺序）。注意这不是新增分支，而是把"漂移阻断"定位为"写入前的覆盖保护"这一更自然规则。

**修改建议**：M-02（§4.2 幂等行 + 漂移检测行 + WP4 幂等判定）。

---

### E4. rollback 后 last_write"或"歧义（R3）——**本轮最高价值的发现**

**核实**：属实。WP5b 任务 6 写"profile **保留原值或标记 restored**"——"或"导致不可实现的歧义；且归档场景的 fields 记录方式、恢复前置快照的排除范围均未定。

**分析**：逐点定唯一算法——
1. **profile 保持原名**，禁止 `restored` 哨兵：否则 `compute_desired("restored")` 会因 profile 不存在而 exit 4，status 也会脏。恢复后若盘上值 ≠ 当前激活 Desired，状态为 `OUT_OF_SYNC`（提示再 `use`），这是正确语义。
2. **归档场景（写前 NOT_EXIST）**：`last_write.fields` 必须记 **NOT_EXIST 哨兵**（非归档文件内容），否则 live 路径已不在而 last_write 仍有值 → 立刻 DRIFTED，T4 要防的死循环换个形态回来。
3. **"排除恢复前置快照"仅对当次恢复有效**：恢复前快照写入新 `backup_id` 后，就是下一次 rollback 的目标（undo-undo）。若做成持久排除标记，第二次 rollback 找不到目标或变 no-op，T4 的洞以另一种形式回归。因此**不引入持久标记**（此点与三.2 冲突，三.2 被拒，见 E14）。

**裁决**：✅ **接受**。WP5b 任务 6 收成一段确定性算法 + WP3 检索函数只服务该算法；删除散落的"最新/排除/restored"表述。

**修改建议**：M-06（WP5b 任务 6 唯一算法）+ M-04 相关（§4.2 指纹与快照行、WP3 检索函数措辞）。

---

### E5. last_write 缺失 ≠ 漂移阻断（R4）

**核实**：属实。WP3 故障注入（"last_write 缺失/过期 → 触发漂移阻断路径"）与 WP4 验收（"last_write 缺失 → 漂移阻断路径成立"）与六态语义（无 last_write → UNMANAGED，允许写入）矛盾——照验收实现，每个 Agent 的第一次 `use` 都会 exit 2。

**分析**：崩溃场景已被"last_write 存在但过期（字段不一致）→ DRIFTED"覆盖；"缺失"对应首次接管（UNMANAGED），应允许重投。阻断当且仅当 **last_write 存在且字段不一致**。

**裁决**：✅ **接受**。WP3 故障注入与 WP4 验收改为该命题，并补"首次 use 中途崩溃 → 重投即可"用例。

**修改建议**：M-07。

---

### E6. 两处接线未写：--dry-run Desired 来源 + created 归属（R5）

**核实**：属实。① `use --dry-run <profile>` 不写 active，若 `compute_state` 读 active，dry-run 算的是旧 profile 的期望值，展示错误；② `created` 归属未定义（已并入 E1）。

**分析**：明确两条契约：Desired 一律来自**命令行 profile 参数**（use 含 dry-run）；active 仅在**非 dry-run 且成功路径**上更新。`created` 由 Safety 依 H0=NOT_EXIST 计算（见 E1）。

**裁决**：✅ **接受**。

**修改建议**：M-08（WP5b use 流程 + WP4 compute_state 契约）。

---

### E7. active=None 时六态无合法值（R6）

**核实**：属实。WP4 的展示规则写"与 last_write 一致则显示 last-write 状态"——这不是六态枚举之一，CLI 会各写各的。T13 又禁止此处用 SYNCED。

**分析**：active=None 且已接管（有 last_write）是"配置事实存在、但无激活 Desired"的**异常边缘态**（正常路径下 active 由首次 use 创建且先于投影写入，此态仅出现在 active 被手动删除等非正常情况）。最简且不新增状态的方案：
- **DRIFTED 优先**（漂移是配置事实，与 active 无关，符合现有优先级）；
- 无漂移 → 显示 **UNMANAGED**（语义上"当前未被 ACM 激活管理"），`--verbose` 附 last profile / 时间。
这不需要第七态，也不误用 SYNCED，与"UNMANAGED = 未处于激活投影之下"一致。

**裁决**：🔶 **部分接受**（采纳"UNMANAGED + verbose"结论；修正为 DRIFTED 优先于 UNMANAGED，与现有优先级一致）。

**修改建议**：M-09（WP4 六态展示规则定案）。

---

### E8. tree_diff 两套规则：严格等价残留（R1）

**核实**：属实。WP2 任务细项 4 仍写"MVP 采取**严格等价**（配置语义精确性优先）"，与 §4.2/WP3③ 的"语义级 + 数值等价容差（`1` 与 `1.0` 等价）"矛盾——实现 WP2 会写死严格比较，WP3 调用同一函数导致误报。

**分析**：这是 T7 改了一半的遗漏（我上轮清理时只改了 §4.2/WP3，漏了 WP2 任务细项 4）。应统一为"语义级比较 + int/float 数值等价容差；词法只在测试计划（fixture 界定）"。

**裁决**：✅ **接受**。

**修改建议**：M-10（WP2 任务细项 4 删"严格等价"）。

---

### E9. 命令/退出码与正文不一致（R2）——**三处教错人**

**核实**：属实。
1. §4.2 双文件备选 / 崩溃安全 / WP3⑤ / 风险表仍写 `rollback --hard`（A6 已定 MVP 不注册 `--hard`，用户照敲即 unknown option）；
2. WP5b 测试计划"未 init exit 4"与 A10/任务 4"config 缺失 → exit 1"矛盾；
3. WP8 验收"含全新建文件与**删除回滚**"应为"归档回滚"。

**分析**：均为实现前必须消除的硬性不一致（命令面、退出码矩阵、验收断言）。另：§4.2/§1.1 中"等价于终局 `--hard` 语义"是语义引用而非命令建议，可保留但建议措辞改为"等价于终局的整文件恢复语义"以彻底避免误敲。

**裁决**：✅ **接受**。

**修改建议**：M-03（`rollback --hard` → `rollback`，共 4 处 + 语义措辞）/ M-04（exit 4 → exit 1）/ M-05（删除回滚 → 归档回滚）。

---

### E10. 双文件事务残留文案（细小残留 1）

**核实**：属实。§2.1 Codex 行（"双文件事务 + 注释密集 MCP 表夹具来源"）、§3.1 codex.py 注释（"双文件事务 + model_providers 表"）、风险表（"Codex 双文件事务中途失败"）仍以双文件为默认表述；夹具目录也列 auth.json。默认路径已是单文件（env_key），这些会把 WP7 带偏。

**分析**：双文件已降为备选（仅 env_key 不可行时启用），默认相关文案必须与之一致。

**裁决**：✅ **接受**。

**修改建议**：M-11（§2.1 Codex 行 / §3.1 codex.py 注释 / 风险表 → "env_key 单文件默认，双文件备选"；夹具目录去 auth.json 或标注备选）。

---

### E11. WP5→WP5b 旧引用（细小残留 2）

**核实**：属实。§2.3 入口（"main 由 WP5 实现"）、§3.1 多个模块注释（main/cli/errors/vmr/output/masking 均标 WP5）、WP1 范围（"写盘仅 init，见 WP5"）、§3.1 adapters/__init__（"WP5/WP6"）仍引用旧 WP5。

**分析**：WP5 已拆 WP5a/WP5b，全部引用应指向 WP5b（或 WP5a 视上下文）。

**裁决**：✅ **接受**。

**修改建议**：M-12。

---

### E12. §9.1 缺 detect 决策行（细小残留 3）

**核实**：属实。detect 主判据决策已写进 §4.1/WP6-8 正文，但 §9.1"已定设计决策"表没有对应行——与"该决策已定"的事实不一致。

**分析**：detect 放宽（可执行文件或配置目录存在）是用户已确认的决策，应在决策表补一行（标识沿用 D1 或另编号均可）。

**裁决**：✅ **接受**。

**修改建议**：M-13（§9.1 补 detect 行）。

---

### E13. 流水线步数表述不一致（三.1）

**核实**：属实。§3.3 数据流/WP3 目标/§1.2/附录 B 多处写"五步流水线"，但流程实体为 ①~⑥ 六步（含 last_write 收尾）。

**分析**：措辞歧义，统一即可（"核心五步 + 状态收尾一步（共 6 步）"或直接"六步流水线"）。低价值但修了避免实现时数错步数。

**裁决**：✅ **接受**（措辞统一）。

**修改建议**：M-14。

---

### E14. 恢复前置快照标记方式（三.2）

**核实**：不必要。三.2 建议"在 last_write 加 `is_restore_snapshot: true` 标记，恢复目标检索自动跳过"。

**分析**：与 **R3（E4）冲突且被其取代**。E4 已定：恢复前置快照写入新 `backup_id` 后即成为下一次 rollback 的目标（undo-undo）；"排除"只发生在当次恢复的操作内（目标 = 旧的 backup_id，非"最新"），无需持久标记。引入 `is_restore_snapshot` 反而会破坏第二次 rollback 的正确性。

**裁决**：❌ **拒绝**（引入不必要复杂度；采纳 E4 的 backup_id 机制即可）。文档只需把"排除恢复前置快照"表述为"恢复目标 = 更新前 last_write.backup_id（而非最新）"。

**修改建议**：无（并入 M-06）。

---

### E15. 归档文件留存规则（三.3）

**核实**：属实。只定义了归档行为，未说明留存策略。

**分析**：与快照一致采用 Append-only 哲学最简：**永久留存，用户按需手动清理**（Phase 2+ 可选 clean 命令，不在 MVP 写路径）。

**裁决**：✅ **接受**（一句澄清）。

**修改建议**：M-15（WP3 归档语义 / A11 补一句留存规则）。

---

### E16. WP7 实证门失败回退（三.4）

**核实**：部分属实。实证门已定义（本机验证 env_key 单文件可跑通 → 定案；不可行 → 双文件备选），但"实证标准"未写清；"工作量 +20%"属调度噪音。

**分析**：补一句**实证标准**有价值（如"Codex 能以该 provider 成功发起一次请求 / 配置被 Codex 正常识别"）；工作量百分比对设计文档无意义、且属于未知因素（不可行时也可能切换思路），拒绝纳入。

**裁决**：🔶 **部分接受**（加实证标准一句；拒工作量数字）。

**修改建议**：M-16。

---

### E17. active 写入时机（三.5）

**核实**：建议错误。三.5 主张"active 写入放在所有投影操作完成后执行"。

**分析**：**当前"先写 active 再投影"的语义是正确的**。若改为"后写 active"，部分投影失败时（A 成功 B 被阻断）会出现：active 仍是旧 profile，而 A 的配置已是新值 → A 被判定 **DRIFTED**（ACM 自己刚写的东西被判为外部篡改），status 撒谎。而当前顺序下部分失败 → active=新、A=SYNCED、B=OUT_OF_SYNC（current==last_write≠desired），完全正确，重跑 `use` 收敛即可。三.5 自己的备选方案（"文档说明属正常现象，status 显示 OUT_OF_SYNC，重跑 use 对齐"）才是对的。

**裁决**：🔶 **部分接受**——拒绝其"后写 active"改法；接受其"文档说明 OUT_OF_SYNC 正常、重跑 use 收敛"的部分。

**修改建议**：M-17（不改实现，仅补一句说明）。

---

### E18. 术语表未同步（三.6）

**核实**：属实。附录 B 缺"归档 / 恢复前置快照 / env_key 投影"等本轮新增概念。

**分析**：新人阅读成本，补词条即可。

**裁决**：✅ **接受**。

**修改建议**：M-18（附录 B 补 3 词条）。

---

### E19. Pi apiKey 明文落盘注（细小残留 6）

**核实**：属实但非问题。WP8 映射表写 `apiKey`（解析明文）——这是 Agent 侧投影输出，与 Claude env 块明文同构，不违反 PRINCIPLE §3.2（约束对象是 ACM 自身存储）。Pi 无 env_key 等价物（models.json 的 apiKey 是字面量）。

**分析**：加一句映射表注即可消歧义（"Pi 无 env_key 等价物，apiKey 为 Agent 侧投影明文"）。

**裁决**：🔶 **部分接受**（可选加注，低价值不阻塞）。

**修改建议**：M-19。

---

### E20. ruamel 移除一致性（细小残留 5）

**核实**：一致。ruamel 已从依赖表移除，与"Aider 不在 MVP"一致。

**分析**：无动作。保持不引（比 C1 的"默认保留"更优，符合最小依赖）。

**裁决**：✅ **接受现状**（无动作）。

---

## 3. 汇总

| 裁决 | 主题 | 说明 |
|---|---|---|
| ✅ 全盘接受 | E1, E2, E3, E4, E5, E6, E8, E9, E10, E11, E12, E13, E15, E18, E20 | 15 项（E20 为无动作确认） |
| 🔶 部分接受 | E7, E16, E17, E19 | 4 项（均取其有效内核、拒其瑕疵建议） |
| ❌ 拒绝 | E14 | 1 项（标记冗余，被 E4 取代） |
| ⏳ 已知问题（记录、MVP 不解决） | — | 0 项（本轮无新增 WAL/状态机类需求；E2 的窗口以文档告知解决） |

**关键原则核验**：本轮全部接受项均为**缺陷修正、契约澄清、文案统一、文档告知**——零新增依赖、零范围扩张、零复杂度上升，符合"MVP 聚焦核心、尽量简单"。

---

## 4. 结论：本轮最有价值的发现

1. **E1（FieldOp.old/created 职责错位）**：真实接口设计缺陷——把"磁盘当前事实"（old/created）放进了纯函数 plan() 的输出。解法：plan 只出 `(file,path,new)`，Safety 依据磁盘（H0=NOT_EXIST）计算 old/created。这与"适配器只编译不写盘"的治理约束（PRINCIPLE §3.4）一致。
2. **E4（rollback 后 last_write 唯一算法）**：把 WP5b 任务 6 的"或"收成确定性算法（profile 保持原名 / 归档场景记 NOT_EXIST 哨兵 / backup_id 自然支持 undo-undo / 不引入持久排除标记），并否决了三.2 的标记方案（E14）。
3. **E3（幂等边界精化）**：把"漂移阻断"正确定位为"写入前的覆盖保护"——Current==Desired 时无写入则无阻断，仅提示；不违反显式暴露公理，消除无意义 --force。
4. **E5（首次 use 与漂移阻断互斥）**：纠正 WP3/WP4 验收中"last_write 缺失 → 阻断"的错误（缺失=UNMANAGED 应允许写入），避免每个 Agent 第一次 use 都 exit 2。

**被拒项说明**：E14（标记冗余，被 E4 取代）、E17（后写 active 语义更差，当前先写 active 正确）。两者均因"存在更优解"或"建议反而不对"而拒，非敷衍。

---

## 5. 建议修改方案（待确认后执行，本轮不改文档）

> 与上一轮"修改大纲"合并后，本轮新增修改点如下（编号续 M-01…）。均已定位到 Action Plan 具体位置。

| 编号 | 涉及 | 位置 | 修改内容 |
|---|---|---|---|
| M-01 | E1 | §4.1 / §3.3 / WP4 | FieldOp 契约拆分：plan 输出 `(file,path,new)`；Safety 依 H0=NOT_EXIST 计算 `old/created`；补 created 归属说明 |
| M-02 | E3 | §4.2 幂等行 / 漂移行 / WP4 幂等判定 | 精化判定顺序：Current==Desired → no-op（漂移仅提示）；有写入需求时含漂移字段 → 阻断 |
| M-03 | E9 | §4.2 双文件备选 / 崩溃安全 / WP3⑤ / 风险表 | `rollback --hard` → `rollback`（整文件恢复）；语义引用措辞去 `--hard` 字样 |
| M-04 | E9 | WP5b 测试计划 | "未 init exit 4" → "未 init exit 1" |
| M-05 | E9 | WP8 验收 | "删除回滚" → "归档回滚" |
| M-06 | E4 | WP5b 任务 6 / §4.2 指纹与快照 / WP3 检索函数 | last_write 恢复更新定唯一算法（profile 原名 / 归档记 NOT_EXIST / backup_id=恢复前置快照 / 目标=更新前 backup_id）；删"或/最新/排除"表述 |
| M-07 | E5 | WP3 故障注入 / WP4 验收 | "last_write 缺失→阻断" → "阻断当且仅当 last_write 存在且字段不一致"；补首次 use 崩溃重投用例 |
| M-08 | E6 | WP5b use / WP4 | 明确 Desired 一律来自命令行 profile 参数；active 仅在非 dry-run 成功路径更新 |
| M-09 | E7 | WP4 六态展示规则 | active=None 定案：DRIFTED 优先；无漂移 → UNMANAGED（verbose 附 last profile/time）；不新增状态、不用 SYNCED |
| M-10 | E8 | WP2 任务细项 4 | 删"严格等价"，统一"语义级 + 数值等价容差" |
| M-11 | E10 | §2.1 Codex 行 / §3.1 codex.py / 风险表 / 夹具目录 | "双文件默认" → "env_key 单文件默认，双文件备选" |
| M-12 | E11 | §2.3 / §3.1 各注释 / WP1 范围 | WP5 旧引用 → WP5a/WP5b |
| M-13 | E12 | §9.1 | 补 detect 主判据决策行 |
| M-14 | E13 | §3.3 / WP3 目标 / §1.2 / 附录 B | 步数表述统一为"核心五步 + 状态收尾（共 6 步）" |
| M-15 | E15 | WP3 归档语义 / A11 | 补一句：归档文件永久留存、用户按需手动清理（与快照一致） |
| M-16 | E16 | WP7 实证门 | 补实证标准一句（Codex 以该 provider 成功发起一次请求）；不写入工作量数字 |
| M-17 | E17 | WP5b use / §8 风险表 | 不改实现；补一句：部分投影失败属正常，status 显示 OUT_OF_SYNC，重跑 `use` 收敛 |
| M-18 | E18 | 附录 B | 补术语：归档 / 恢复前置快照 / env_key 投影 |
| M-19 | E19 | WP8 映射表 | 补一句"Pi 无 env_key 等价物，apiKey 为 Agent 侧投影明文" |
| M-20 | E2 | §8 风险表 + use/rollback 帮助文案 | 补崩溃一致性窗口说明（配置已更新但状态未记录属正常保护，`use --force` 可对齐） |

**待用户确认项**：A3/A7/A8/A9（§9.2）仍开放，按默认建议执行即可、不阻塞实现（A8 已被 WP0 交付物默认覆盖）；如需可随时拍板。

---

*Round 2 评审结束。以上修改建议待用户确认后执行（本轮不改任何文档）。*---

# Round 3 Review：修改落地复核（第三轮——对工作区实际改动的验收评审）

> **评审时间**：2026-08-24 | **方法**：以 git diff（ACM_MVP_ACTION_PLAN_v1.0.md / ACM_PROJECT_SPEC_v2.1.md 工作区改动）逐项对照本反馈文档中 Round 1 修改大纲（AP-01~31、SP-01~03）与 Round 2 修改方案（M-01~M-20），并对两份文档全文做残留一致性扫描（关键词：--hard / 最新快照 / 字典序 / 五步六步 / ruamel / auth.json / doctor / exit 4 / WP5 旧引用 / restored / 严格等价 等）。
> **性质**：只读复核，不修改任何已有文档。

## 0. 总体结论

**两份文档的修改整体高质量，可以进入 commit 前的最后微修。** Round 1 的 31 项 Action Plan 修改点（AP-01~31）与 3 项 SPEC 回写点（SP-01~03）、Round 2 的 20 项修改点（M-01~M-20）在 **Action Plan 内全部正确落地**，且 Action Plan 内部一致性良好（未发现自相矛盾、未发现旧概念残留、退出码/命令面/归档语义/幂等判定顺序全文统一）。

**主要问题集中在 SPEC 侧回写不完整**：共发现 5 处 SPEC 残留（其中 1 处高危），均为 Round 1/Round 2 修改大纲未覆盖到的 SPEC 独立段落。另有个别边缘残留（P2 级）如下列。

## 1. 修改点落地核验（抽全量）

| 组 | 核验结果 |
|---|---|
| AP-01~09（T4/T5 rollback 语义 + 归档） | ✅ 全部落地：§4.2 指纹与快照行、WP3 检索函数 `latest_snapshot_for_rollback(agent, backup_id)`、WP5b 任务 6 唯一算法（profile 原名 / NOT_EXIST 哨兵 / backup_id=恢复前置快照 / undo-undo / 无持久标记）、A11/A12 重写、验收 3 措辞，均与裁决一致 |
| AP-10~11（T6 detect 主判据） | ✅ 落地（§4.1 + WP6/7/8 task 1 + A16 决策行） |
| AP-12~14（T7 语义/词法分界） | ✅ 落地（WP2 测试计划与任务 4、WP3③、§4.2 解析树 diff 行；全文已无"严格等价""字节级不变"承诺残留） |
| AP-15~18（T8 env_key + T9 批处理指纹） | ✅ 落地（WP7 重写含实证门与实证标准、§4.2 双文件降备选、§1.2 表、WP3④ 批处理） |
| AP-19~23（拆包/接口冻结/dry-run/active=None/schema 两档） | ✅ 落地（WP5a/WP5b 章节与依赖图、WP4 验收冻结 PlannedOp 接口、WP5b 任务 10 规范表、WP4 任务 3 展示规则、WP1 必填/可选两档） |
| AP-24~31（C 组细项） | ✅ 落地（doctor 不提、A4 定案纳入、--force per-command 语义表、验收 2 JSON/TOML 区分、`${VAR:-}` 用例、无 Win 分支、docstring 不阻塞、ruamel 移出 §2.2） |
| SP-01~03（SPEC 回写） | ✅ 三处均落地（detect 定义 / §8 Codex 行 / §9 VMR 探测顺序）；**但见下文 §2 的 SPEC 其他段落遗漏** |
| M-01~M-20（Round 2） | ✅ 20 项全部落地（FieldOp/PlannedOp 契约拆分、幂等判定顺序、rollback 唯一算法、last_write 缺失≠阻断、Desired 来源、active=None 定案、双文件残留清理、WP5b 引用更新、术语表 3 词条等）；仅 M-20 为部分落地（见 N-4） |

## 2. 发现的问题

### 高危（commit 前必须修）

**N-1. SPEC §10 rollback 命令注释仍写"最新快照"（L710-716）——T4 修复的唯一漏网之鱼**
- 原文：`acm rollback ...` 注释块「【MVP 仅交付整文件恢复：等价于 --hard **最新快照**…】」「--hard 灾难恢复：整文件快照还原（--snapshot <id> …缺省为**最新快照**）」。
- 问题："最新快照"正是 T4/E4 判定必须消灭的语义（恢复目标 = 更新前 `last_write.backup_id`，非字典序最大）。Action Plan 已全面修正，但 SPEC §10 这段显式标注 "MVP 仅交付…" 的文字若被实现者参照，会原样重新引入 T4 的 rollback no-op / DRIFTED 死循环漏洞。
- 建议：该 MVP 注释改为「MVP 仅交付整文件恢复；恢复目标 = 更新前 `last_write.backup_id` 指向的快照（非"最新"）」；终局 `--snapshot <id>` 缺省语义可保留"最新"（属 Journal 时代多态语义），但应与 MVP 注释明确区隔。

### 中危（建议一并修）

**N-2. SPEC D2 结论行仍列 ruamel.yaml（L187）——D3 裁决回写遗漏**
- 原文：「结论：纯 Python，最小依赖（typer+rich、**ruamel.yaml**、tomlkit；pydantic 可选…）」。
- 问题：与同节更新后的预算行（L203「≤ 3 个…ruamel.yaml 随 P1 Aider 引入」）直接矛盾。
- 建议：结论行改为「typer+rich、tomlkit；pydantic 可选；ruamel.yaml 随 P1 Aider 引入」。

**N-3. SPEC 架构验证矩阵 Codex 行仍是"双文件事务"默认表述（L259）**
- 原文：「TOML round-trip + **双文件事务**（config.toml + auth.json）｜Codex」。
- 问题：与 SP-02 已更新的 §8 行（auth.json 降备选、env_key 单文件默认）矛盾，属 E10 同类残留；读者会误以为双文件仍是 MVP 既定架构。
- 建议：改为「TOML round-trip + 新建表形状（env_key 单文件默认；双文件事务降为备选机制，Safety Engine 多文件能力保留）｜Codex」。

**N-4. M-20 部分落地：use/rollback 帮助文案落点缺失**
- 崩溃一致性窗口告知已进 §8 风险表与 §4.2 崩溃安全行，但 WP5b 任务细项没有对应的"帮助文案注明"交付项。
- 建议：在 WP5b 任务 4/6 或任务 10 补半句"use/rollback `--help` 附崩溃窗口说明（配置已更新但状态未记录属正常保护，`use <profile> --force` 可对齐）"。

### 低危（择机处理即可）

**N-5. SPEC MVP 语境的两处 `rollback --hard` 文案（L576、L790）**
- §7.5.6（L576）与 §11 验收负面用例（L790）均以 apply/diff "上线后"括注界定了 MVP 时间语境，却引用 `acm rollback --hard`——A6 已定 MVP 不注册 `--hard`，照敲即 unknown option。建议改为裸 `rollback`。
- 另外 L790 "未记入 last_write 的变更触发漂移安全阻断" 与 E5/M-07 的精化（last_write **缺失** → 不阻断、允许重投；**存在但字段不一致** 才阻断）需对齐措辞，避免与首次 use 崩溃场景矛盾。

**N-6. SPEC §12 Slice 1 安全底线行未反映 no-op 例外（L820）**
- 「受管字段漂移检测 + 默认阻断（退出码 2）+ --force 显式覆盖」为无条件表述；§7.5.2/§7.5.8 已补"Current==Desired 时 no-op 仅提示不阻断"，§12 该行未同步。建议补一句"（no-op 且 Current==Desired 时除外，见 §7.5.8）"。

**N-7. Action Plan 附录 A fixture 清单未标 auth.json 备选（L762-763）**
- 来源列表无条件含 auth.json、命名示例含 `auth.golden.json`，与 M-11"夹具目录去 auth.json 或标注备选"的精神不一致（§2.1/§3.1 均已标注，唯附录 A 漏标）。建议补"（D2 备选）"注记。

**N-8. 跨文档流水线步数措辞（低价值）**
- SPEC §7.5.1 MVP 变体写"五步……末步改覆写 last_write"且未提 Safety 补全 FieldOp 环节；Action Plan 统一为"六步流水线（核心五步 + 状态收尾一步）"。语义等价、不致错，但跨文档措辞可再对齐。

**N-9. 其他备忘（无需阻塞）**
- SPEC L205「文件锁用 fcntl/msvcrt」与 D4/A15"MVP 无 Win 分支"存在终局/MVP 口径张力，可在 SPEC 加注"MVP 仅 fcntl"。
- SPEC §12 验收 #2（L838）"未管键与注释保持不变"未按 C5 区分 JSON（无注释）/TOML；验收 #3 未提 backup_id 目标。Action Plan §7 已细化，SPEC 保持泛化可接受。
- Action Plan §2.1 表"working tree clean"已因本次改动过时（纯事实快照，无害）。
- Action Plan §4.2 六态行 UNMANAGED 定义（"已安装未接管")与 active=None 规则复用 UNMANAGED（含"已接管但未激活"边缘态）存在定义张力——此为 E7 明示接受的取舍，WP4 任务 3 已就地说明，无需改。

## 3. 结论

- **Action Plan（ACM_MVP_ACTION_PLAN_v1.0.md）**：✅ 通过复核。AP-01~31 与 M-01~M-20 全部正确落地，内部一致性良好，无新增问题引入。可直接进入 commit。
- **SPEC（ACM_PROJECT_SPEC_v2.1.md）**：🔶 有条件通过。SP-01~03 已落地，但存在 **N-1（高危，"最新快照"残留，会使 T4 修复失效）** 及 N-2/N-3（依赖与双文件表述前后矛盾）等待修项。建议完成 N-1~N-3（必要）与 N-4（低成本）后一并 commit；N-5~N-9 可随后续治理流程处理。
- 本轮复核未修改任何文档；以上问题清单供拍板后执行。

*Round 3 复核结束。*

> **执行状态（2026-08-24）**：N-1~N-9 已按建议全部落实——
> - N-1：SPEC §10 MVP 注释改为"恢复目标 = 更新前 `last_write.backup_id` 指向的快照（非\"最新\"）"，终局 `--snapshot` 缺省语义加注与 MVP 区隔；
> - N-2/N-3/N-5/N-6：D2 结论行去 ruamel、架构验证矩阵 Codex 行降备选、§7.5.6/§11.1/§11 负面用例去 `--hard` 化并按 E5 对齐 last_write 缺失措辞、§12 安全底线行补 no-op 例外；
> - N-4：Action Plan WP5b 补任务 11（use/rollback 帮助文案注明崩溃一致性窗口）；
> - N-7：附录 A fixture 来源与命名标注 auth.json 为 D2 备选；
> - N-8/N-9：SPEC §7.5.1 统一为六步流水线措辞并补 Safety 补全 FieldOp 环节；文件锁注记 "MVP 仅 fcntl、无 Win 分支"。
> - 按复核结论保持现状不改：SPEC §12 验收 #2/#3 泛化措辞、Action Plan §2.1 "working tree clean" 事实快照、UNMANAGED 定义张力（E7 明示接受）。
