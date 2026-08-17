

# 基于GLM版的ACM方案完善建议 V1
以下建议严格以**GLM版为基底**，保留其「三公理体系、字段级回滚、Core纯逻辑分层」等核心优势，从另外两份文档中吸收高价值内容进行补全、优化，同时对GLM版中不合理的部分给出调整方案。

---

## 一、【新增补全】GLM版完全缺失、值得吸收的高价值点
### 1. 动态适配器热加载协议（来源：Gemini版）
- **具体建议**：约定用户自定义适配器目录 `~/.acm/adapters/`，ACM启动时通过 `importlib` 自动扫描加载目录下的 `.py` 文件；用户脚本只需继承适配器基类、实现核心方法，即可无缝参与 `use`/`diff`/`rollback` 全命令流程，无需修改源码、无需编译。
- **价值**：是「可编程、可扩展」定位的核心落地能力，大幅降低社区贡献长尾Agent适配的门槛，同时满足企业内部自定义Agent的扩展需求。

### 2. 全通道分发矩阵（来源：Gemini版）
- **具体建议**：在GLM版原有 `uv tool install` / `pipx` 基础上，补充三类分发渠道：
  - `uvx acm` 免安装瞬时执行（类似npx，最低试用门槛）
  - Homebrew Tap 隔离安装（适配macOS/Linux用户习惯）
  - pyapp 单二进制打包（覆盖Windows、离线生产环境）
- **价值**：覆盖不同用户场景的安装需求，把「上手摩擦」降到最低，是现代CLI工具的标配体验。

### 3. 受保护路径黑名单校验机制（来源：Sonnet版）
- **具体建议**：要求每个适配器必须声明 `protected_paths`（禁止修改的字段路径，如 `mcpServers`、`permissions`、`plugins`），核心安全引擎执行写入前自动校验，确保所有变更均不在黑名单范围内。
- **价值**：与GLM版原有的「管理字段白清单」形成**双重防护**：白名单保证“只改该改的”，黑名单保证“绝对不改不该碰的”，从正反两面彻底杜绝误写非管字段，强化「无损」核心承诺。

### 4. 快照生命周期管理策略（来源：Sonnet版）
- **具体建议**：为文件级兜底快照增加保留策略：每个Agent默认保留最近20个快照，按FIFO规则自动清理过期快照；支持用户通过配置自定义保留数量。
- **价值**：补齐工程细节，避免快照无限制占用磁盘空间，同时不牺牲灾难恢复能力。

### 5. 三阶段事务提交标准化流程（来源：Gemini版）
- **具体建议**：把GLM版零散的原子写、快照、校验机制，统一规范为标准三阶段事务流程：
  1. 准备阶段：读取原文件、计算哈希、生成快照、写入事务日志
  2. 内存变更阶段：生成ChangeSet、执行内存修改、语法校验、非管字段篡改断言
  3. 提交阶段：临时文件写入 + os.replace 原子替换 + 更新事务状态
  任一阶段失败均触发对应层级的回滚。
- **价值**：让安全机制从“零散功能”变成“标准化流程”，减少实现遗漏，不同适配器的安全一致性更有保障。

### 6. `acm doctor` 健康诊断命令（来源：Gemini版）
- **具体建议**：新增 `acm doctor` 命令，自动扫描诊断：配置文件语法正确性、文件读写权限、依赖环境变量缺失、配置与基线漂移、目标Agent进程冲突等常见问题，并给出修复建议。
- **价值**：CLI工具的标配实用功能，大幅降低用户排错成本，提升工具的可靠性感知。

### 7. 快照历史查询与指定版本回滚（来源：Gemini版 + Sonnet版）
- **具体建议**：
  - 新增 `acm history [agent]`：查看该Agent的配置变更时间线、对应快照哈希与来源Profile
  - 扩展 `acm rollback`：支持 `--to=<hash>` 回滚到指定历史快照；补充 `--hard` 参数显式触发整文件快照还原（默认仍为字段级回滚）
- **价值**：把回滚能力从“只能退一步”升级为完整的版本管理体系，同时保持GLM版字段级回滚的核心优势。

### 8. 金样回归测试体系（来源：Gemini版）
- **具体建议**：建立Golden File测试套件，每个适配器配套「带手写注释、带MCP配置、带私有字段」的真实配置样本，执行三步断言闭环：
  1. Apply后目标字段精确修改
  2. 非管字段与注释字节级完全保留
  3. 回滚后文件SHA256与原文件完全一致
- **价值**：从工程层面刚性保障「无损」承诺，防止迭代中引入回归bug，是项目长期可维护性的核心基石。

### 9. 进程守护完整交互设计（来源：Gemini版 + Sonnet版）
- **具体建议**：完善GLM版仅提及的进程检测逻辑：写入前自动检测目标Agent的活跃进程，检测到则默认阻断操作并给出明确警告，提供 `--force` 参数允许用户强制写入。
- **价值**：避免Agent运行时覆盖磁盘配置、导致ACM变更丢失的问题，细节上强化安全感知。

### 10. 适配优先级矩阵与量化验收标准（来源：Sonnet版）
- **具体建议**：将所有Agent按P0/P1/P2分级，每个阶段明确交付物与可量化验收标准（例如MVP要求3个Agent回滚后文件哈希与初始样本完全一致）。
- **价值**：GLM版路线图偏粗粒度，补充后项目里程碑更清晰，验收可量化、可对齐。

---

## 二、【优化增强】GLM版已有、可进一步完善的点
### 1. Core Config Schema 表达能力升级（吸收Sonnet版细节）
- **原有基础**：GLM版已有 providers / models / profiles 三层结构。
- **优化建议**：
  - 补充 `protocol` 枚举值（增加 `openai-responses` 等方言）、自定义headers、代理设置、组织ID等连接层参数
  - 完善模型层字段：补充 `capabilities`（vision、tool_call方言、json mode）、`reasoning` 完整参数（effort + budget_tokens）
  - 环境变量引用支持默认值语法：`${ENV_VAR:-default_value}`
- **价值**：让核心配置的表达能力更完整，覆盖更多供应商与Agent的差异化需求，减少适配器的特殊处理逻辑。

### 2. 适配器契约接口标准化（吸收Sonnet版接口设计）
- **原有基础**：GLM版定义了 detect / plan / verify 协议。
- **优化建议**：
  - 统一强制属性：`agent_id`、`display_name`
  - 新增 `config_paths()` 方法：由适配器声明所有受管文件路径，核心引擎统一处理快照，避免每个适配器重复实现快照逻辑
  - 标准化 `diff()` 方法输出格式，由核心层统一渲染
- **价值**：减少适配器重复代码，接口规范度更高，新增Agent适配的心智负担更低。

### 3. VMR协同体验升级（吸收Gemini版 + Sonnet版）
- **原有基础**：GLM版有 `acm import vmr` 命令。
- **优化建议**：
  - 新增 `acm use-vmr <virtual_model>` 快捷命令：一键将所有已探测Agent切换到VMR指定虚拟模型
  - 新增 `acm vmr status`：查看本地VMR运行状态、暴露的虚拟模型列表
  - 优化探测逻辑：优先探测 `http://127.0.0.1:8800/healthz`，再 fallback 读取 `~/.vmr/config.yaml`
- **价值**：强化VMR场景「最后一公里」的体验优势，符合项目初始动因，操作更极简。

### 4. 多文件事务原子性增强（吸收Gemini版事务思想）
- **原有基础**：GLM版有单文件原子写能力。
- **优化建议**：针对Aider这类多文件配置的Agent，实现跨文件事务：任一文件写入失败，自动回滚所有已提交的文件变更，确保配置整体一致性。
- **价值**：避免“部分文件改成功、部分失败”的中间状态，提升复杂场景下的可靠性。

### 5. Diff输出体验优化（吸收Gemini版 + Sonnet版）
- **原有基础**：GLM版有diff能力。
- **优化建议**：基于rich库实现高亮彩色统一diff（Unified Diff格式），支持按文件、按字段分级展示差异。
- **价值**：符合现代CLI工具的交互标准，用户可读性大幅提升。

---

## 三、【调整修正】GLM版不合理、建议调整或删除的点
### 1. 调整：MVP首批适配器选型
- **原有方案**：Claude Code + Codex + Pi
- **存在问题**：三个均为单文件、结构简单的配置场景，无法充分验证多文件联动、复杂参数映射、跨表修改等架构能力，MVP验证不充分，后续扩展仍可能暴露架构缺陷。
- **调整建议**：改为 **Claude Code + OpenClaw + Aider**（Sonnet版方案）
  - Aider覆盖YAML+JSON双文件、多角色模型、元数据同步等复杂场景，能充分验证ChangeSet、事务、无损补丁的架构通用性
  - Codex、Pi移入Phase 2，简单场景适配成本极低，不影响整体进度
- **理由**：MVP的核心目标是验证架构可行性，而非最快做完；复杂场景跑通后，简单Agent适配属于纯体力工作，风险极低。

### 2. 调整：Core Config 配置格式从 TOML 改为 YAML
- **原有方案**：采用单文件 `config.toml`
- **存在问题**：ACM配置存在多层嵌套（`providers`、`models.reasoning`、`profiles` 多角色模型），TOML深层嵌套可读性差、书写繁琐；且项目核心依赖 `ruamel.yaml` 处理Agent配置，核心配置改用YAML可减少技术栈心智负担，注释保留能力同样成熟。
- **调整建议**：切换为YAML格式，保留GLM版设计的 providers / models / profiles 三层逻辑结构不变。
- **理由**：YAML更适合深度嵌套的配置场景，与现有技术栈更匹配，可读性与可维护性更优。

### 3. 强化：Scope边界的刚性约束
- **原有现状**：有out of scope列表，但强调力度不足，未上升为项目铁律。
- **存在问题**：Scope膨胀是CC-Switch偏离初心的核心原因，仅靠功能列表不足以抵御后续的需求蔓延。
- **调整建议**：吸收Gemini版的「正交边界」原则，明确写入项目纲领：
  1. 绝不触碰MCP、插件、系统提示词、权限配置
  2. 绝不写入闭源IDE的私有数据库（如SQLite存储）
  3. 新增功能必须先判定是否属于「模型配置层」范畴，否则一律拒绝
- **理由**：从制度上防止项目跑偏，长期保持工具的极简、专注定位。

### 4. 调整：明确项目失败/降级退出条件
- **原有现状**：仅模糊提及「若失去理由1则重新评估」
- **存在问题**：表述模糊，缺乏可执行性，容易陷入无意义的维护投入。
- **调整建议**：补充明确的退出规则：
  - 若VMR项目终止，ACM立即降级为内部工具，停止新增功能，仅维护基础适配
  - 若连续6个月无社区反馈且内部使用频次极低，则归档项目
- **理由**：让项目存续决策有明确依据，符合GLM版务实、克制的整体风格。


------------

# 基于GLM版的ACM方案完善建议 V2
建议不要把三份方案“拼接”成一个更大的方案，而是以 GLM 版为骨架，做一次有选择的增强和删减。核心原则是：**强化 GLM 已经正确的架构判断，吸收 Gemini/Sonnet 的工程细节，但避免把 ACM 做成全功能配置平台。**

建议最终按下面这些方向调整。

### 一、GLM 基础架构：保留并进一步强化

1. **保留 GLM 的 Core Config / Provider → Model → Profile 三层模型。**

   * 这是最终版的核心数据模型。
   * 可以进一步明确三者职责边界，避免 Profile 再次膨胀成“大杂烩”。

2. **把“Managed Field / Ownership”提升为 ACM 的核心架构原则。**

   * 不只是实现一个 manifest。
   * 明确 ACM 管理的是“字段”，而不是“文件”。
   * 所有 patch、diff、rollback 都围绕这一原则设计。

3. **进一步完善 GLM 的字段级 Rollback。**

   * 保留 GLM 的字段级回滚。
   * 吸收 Gemini/Sonnet 的 Snapshot / Journal 思路，但把完整 Snapshot 定位为审计、灾难恢复和兜底，而不是正常 rollback 机制。
   * 增加基本的并发/冲突检测：如果 Agent 在 ACM 写入之后修改了 ACM-owned field，不应该静默覆盖。

4. **强化 Adapter 的 ChangeSet 抽象。**

   * 不让 Adapter 直接随意修改文件。
   * Adapter 应该负责“语义映射”，Core/Safety Layer 负责生成、验证和执行 ChangeSet。
   * 这样可以把 Adapter 与安全机制解耦。

5. **吸收 Gemini 的 Adapter Mapping Matrix。**

   * GLM 虽然有 Adapter 思路，但 Gemini 对每个 Agent 的字段映射、配置位置、特殊语义梳理得更系统。
   * 最终版应该把它作为正式的 Adapter 开发基准，而不是散落在代码里。

---

### 二、从 Gemini / Sonnet 吸收，但 GLM 目前不足的部分

6. **增加完整的 Agent Capability / Config Matrix。**
   不只是记录“这个 Agent 支持不支持”，还应明确：

   * 配置文件位置；
   * 配置格式；
   * 支持哪些模型字段；
   * 哪些字段无法表达；
   * 哪些字段需要转换；
   * 是否支持多模型/角色模型；
   * 是否存在多文件协同。

   这是未来 Adapter 质量的核心资产。

7. **建立 Golden Config / Golden Test 体系。**
   三份方案都有涉及，Gemini尤其强调。

   * 每个 Agent 准备标准输入/输出样例；
   * Adapter 修改后自动验证；
   * Agent 上游 schema 变化时能尽早发现。

   这应该成为 Adapter 开发的基础设施，而不是后期测试。

8. **加入 `doctor / check / diff / dry-run` 这一组安全型 CLI 能力。**
   GLM 已有部分相关思路，但建议把它们作为正式的一等公民：

   * `check`：检查配置状态；
   * `diff`：查看 ACM 将要修改什么；
   * `dry-run`：只计算 ChangeSet，不写文件；
   * `doctor`：发现 schema drift、配置异常、Adapter 不兼容等问题。

   这些功能的价值远高于 GUI。

9. **吸收 Gemini 的 VMR Discovery / Import 思路。**
   不要只支持手工创建 VMR Profile。

   * 可以发现本机已有 VMR 配置；
   * 导入为 ACM Provider/Profile；
   * 但 ACM 不反过来承担 VMR Gateway 的职责。

10. **明确“VMR 是第一方集成，而不是架构依赖”。**
    GLM 已经提出这一点，建议进一步固化：

    > ACM 可以因为 VMR 而诞生，但脱离 VMR 仍然是完整产品。

11. **增加 Dynamic Adapter / 用户自定义 Adapter 的扩展机制。**
    这是 Gemini 很有价值的一点。

    * 不需要 ACM 官方为每个 Agent 发版；
    * 用户可以增加自己的 Adapter。

    但建议放在 MVP 后，不要让它拖慢第一版。

12. **吸收 Sonnet 的明确 MVP / P0-P1-P2 分层。**
    GLM 的技术方案比较完整，但最终版需要更加克制。
    建议第一阶段只把少数高价值 Agent 做深，而不是追求覆盖数量。

---

### 三、GLM 中需要调整的部分

13. **调整“市场空白”的表述。**
    不要再使用“市场空白”作为核心立项依据。

    应改成：

    > 需求已经被 CC-Switch 等产品验证，但 CLI-first、programmable、non-destructive、model-centric 这个交集仍然存在产品空间。

14. **降低“超越 CC-Switch”的隐含目标。**
    ACM 不应该以 Agent 数量、GUI、功能数量竞争。

    核心竞争维度应该保持：

    > 简单、可靠、可脚本化、非破坏性、模型配置 SSOT。

15. **对“非破坏性”做更严格定义。**
    不要笼统承诺“无损”。

    应区分：

    * 结构级无损；
    * 文本级无损；
    * Comment 保留；
    * Formatting 保留。

    不同配置格式分别定义保证等级。

16. **不要把 JSON Patch 等同于真正的文件无损修改。**
    Sonnet 的方案在这里可以作为参考，但不能直接照搬。

    最终应该以“ChangeSet + format-specific round-trip editor”为核心，而不是简单依赖 RFC 6902。

17. **重新审视 VSCode 系 Agent 的支持策略。**
    GLM 不支持 private `state.vscdb` 是正确方向，应继续坚持。

    建议明确：

    > 没有公开、稳定、可安全修改的配置接口，就不支持。

    不为了增加 Agent 数量而突破这一原则。

18. **把完整 Snapshot 从“核心回滚机制”降级为 Safety Net。**
    GLM 已经比另外两份合理，但最终版应该明确三层：

    `ChangeSet / Field Rollback → Journal → Full Snapshot`

    正常操作不应该依赖整文件恢复。

---

### 四、GLM 可以删除或进一步收缩的部分

19. **压缩过于完整的分发方案。**
    不要 MVP 同时解决：
    `uvx + uv tool + pip + pipx + Homebrew + standalone`。

    第一阶段只需要一个主路径，例如：
    `uv tool install acm`。

    其他分发渠道等真实用户出现后再加。

20. **不要过早实现 GUI / TUI。**
    保持 CLI-first。

    如果未来需要交互式选择器，可以是 CLI 的薄层，而不是独立产品方向。

21. **不要把 Dynamic Adapter 过早放进核心 MVP。**
    架构上预留即可，第一阶段先把官方 Adapter 做扎实。

22. **不要扩展 MCP / Skills / Prompt / Plugin 管理。**
    这点 GLM 本身已经非常正确，最终版应该继续强化，而不是吸收另外两份文档中可能导致 Scope 膨胀的部分。

23. **不要因为 Adapter 数量而过早设计复杂插件生态。**
    先解决：

    > “官方 Adapter 能不能稳定、安全地完成 Projection？”

    再解决：

    > “第三方能不能自己写 Adapter？”

---

### 五、最终版建议增加一个 GLM 原方案中没有充分明确的核心层次

我建议最终架构明确分成：

```text
Core Config / SSOT
        ↓
Profile Resolution
        ↓
Adapter
        ↓
ChangeSet
        ↓
Ownership / Conflict Check
        ↓
Format-specific Writer
        ↓
Atomic Write
        ↓
Journal / Snapshot
```

其中：

**Core Config** 解决“ACM 认为模型世界是什么”。

**Adapter** 解决“目标 Agent 怎么表达”。

**ChangeSet** 解决“具体要改什么”。

**Ownership** 解决“ACM 有没有资格改”。

**Writer** 解决“怎么安全地改”。

**Journal/Snapshot** 解决“怎么追踪和恢复”。

这个层次实际上可以把三份文档里比较分散的优秀设计统一起来，而且不会增加太多产品复杂度。

---

### 最终取舍，可以压缩成一句话

**GLM 负责“骨架”，Gemini 负责“Adapter 和工程细节”，Sonnet 负责“MVP 克制和测试方法”；同时删除三份方案中任何会让 ACM 向 CC-Switch 全家桶、Gateway、GUI 或复杂插件平台演化的东西。**

最终最值得新增/强化的其实只有六件事：

**① Field Ownership + Conflict Detection
② ChangeSet
③ Adapter Mapping Matrix
④ Golden Tests / Schema Drift Detection
⑤ VMR Discovery / Import
⑥ 安全型 CLI（diff / dry-run / doctor / check）**

而最应该坚持删除/压缩的则是：

**① 全文件 Rollback 作为默认机制
② Private DB 修改
③ 过多分发渠道
④ GUI / TUI
⑤ MCP / Skills / Plugin 等 Scope 膨胀
⑥ “市场空白”这种过度乐观的定位。**


------------

# 基于GLM版的ACM方案完善建议 V3

以下建议按「优先级从高到低 + 类型」组织，便于直接落地修改。所有建议均基于前一轮对比分析，只保留高价值、可操作的内容。

### 一、必须吸收 / 大幅强化的高价值点（GLM 缺失或明显薄弱）

1. **多通道分发矩阵与安装体验（来自 Doc1）**  
   GLM 只简单提到 uv/pipx，几乎没有展开。必须补上完整的现代化分发矩阵：  
   - 通道 1：`uvx acm`（零安装推荐）+ `uv tool install acm`  
   - 通道 2：Homebrew Tap（自动隔离 venv）  
   - 通道 3：基于 pyapp 的 Standalone 单二进制（Windows/Linux 离线）  
   - 通道 4：pipx / pip  
   同时明确「目标用户几乎必然有 Python + uv，单二进制是锦上添花而非刚需」。这是用户第一印象的关键。

2. **完整的 CLI 命令规格与交互示例（来自 Doc1 + Doc3）**  
   GLM 的命令列表偏简略。建议扩充为带完整示例的规格，至少覆盖：  
   - `acm init [--dry-run]`（含自动探测 VMR + 扫描已安装 Agent 的流程）  
   - `acm use <profile> [--agent <name|all>] [--dry-run]`  
   - `acm apply`（重新对齐当前 active）  
   - `acm use-vmr [virtual_model]` / `acm import vmr`  
   - `acm status` / `acm doctor`  
   - `acm diff` / `acm history` / `acm rollback [--to=<hash>] [--hard]`  
   - `acm release`（已有，保持）  
   - `acm profile list/show/create`  
   同时补充全局选项（`--force`、`--verbose`、`--dry-run`）和进程冲突时的标准警告文案。

3. **Agent 优先级矩阵 + 保护字段清单 + 深度参数映射表（来自 Doc3 为主，Doc1 补充）**  
   GLM 的「首批适配器」表格过于简略。必须升级为：  
   - 明确 P0（Phase 1 必须）：Claude Code、Codex、Pi（或 OpenClaw，按真实需求定）  
   - P1 / P2 划分  
   - 每个 Agent 的：配置路径、格式、关键写入字段、**明确的保护字段（禁止修改）**、深度参数（reasoning / context / vision）映射方案  
   特别强调 Claude Code **只动 `~/.claude/settings.json`，绝不碰 `~/.claude.json`（运行时状态）**。

4. **Phase 验收标准与金样测试策略细化（来自 Doc3）**  
   GLM 有路线图但验收标准偏虚。补充 Phase 1 的硬验收：  
   - `acm init` → `acm use` 后，P0 三个 Agent 全部正确指向目标 Profile/VMR  
   - `acm rollback` 后文件与修改前字节级一致（字段级软回滚默认）  
   - 不触碰任何 MCP / Skills / Hooks / permissions  
   - 每个 Adapter 必须有带真实注释、MCP、怪癖字段的 Golden Fixture，并做三步断言（Apply / Non-destructive / Rollback）

5. **系统架构图与组件职责图（来自 Doc1 + Doc3）**  
   GLM 有文字架构，但缺少清晰的分层图。建议补一张：  
   CLI → Core（纯逻辑，无 I/O）→ Safety Engine + Adapter Layer（plan only）→ Format Helpers  
   并明确「Adapter 只产出 ChangeSet，写入与安全由 Safety Engine 统一执行」的强制约束。

6. **`acm init` 自动化流程细节（来自 Doc3）**  
   扫描本机 Agent（which / 路径探测）、探测本地 VRM（healthz + 配置）、自动生成 Core Profile、无 VMR 时的 fallback（手动输入或预设 Provider）、`--dry-run` 预览。这些是降低首次使用摩擦的关键。

### 二、GLM 已有但可进一步完善的点

1. **安全引擎（字段级 managed manifest）**  
   这是 GLM 的核心优势，保持不变，但建议补充：  
   - 三阶段提交伪代码（Prepare & Snapshot → In-Memory Mutate & Verify → Atomic Commit）  
   - 多文件变更时的顺序提交 + 失败回滚已提交项的策略  
   - 快照保留策略（每个 Agent 最近 N 个，FIFO）  
   - `acm release` 的精确语义（按清单移除所有 ACM 注入，恢复 pre-ACM 状态）

2. **Core Config Schema**  
   保持 TOML 格式与「所有权声明」表述，但建议：  
   - 补充更完整的示例（参考 Doc1 的 reasoning.budget_tokens、capabilities、多角色模型）  
   - 明确 `${ENV_VAR}` 引用优先、明文存储需显式 opt-in 并警告  
   - 增加 `active_profile` 或等价机制

3. **VMR 协同**  
   保持松耦合，但建议吸收 Doc1 的「一键全量对齐」与 Doc3 的「Core Profile 锚定 VRM」表述，使 `acm use-vmr` / `acm import vmr` 成为最自然的默认路径。

4. **风险与成功标准**  
   GLM 已有较好基础，建议补充 Doc3 的风险概率/影响表，并保持「对内 ≤3 命令 / ≤1 分钟零手工；对外只做一件事且可脚本化」的成功标准。

### 三、GLM 中需要调整或删除的点

1. **市场判断与立项叙事**  
   保持 GLM 的诚实立场（不说“市场空白”，承认 cc-switch 成功，明确生态位差异化），但可吸收 Doc1/Doc3 对 CC-Switch「全量覆写是架构级缺陷、不太可能自我修正」的更强表述，增强差异化说服力。无需删除，只需微调措辞。

2. **语言版本与依赖**  
   统一为 Python 3.11+（或 3.10+），明确最小运行时依赖目标（≤4 个：typer/rich、pydantic、ruamel.yaml、tomlkit，psutil 可选），并锁定 uv。

3. **Claude Code 路径表述**  
   已较谨慎，进一步强化「绝不碰 `~/.claude.json`」，避免与 Doc1/Doc3 的模糊表述冲突。

4. **可能过度简略的部分**  
   - Adapter Protocol 可补充更完整的接口示例（含 ChangeSet 结构暗示）  
   - 目录布局可更详细（state/<agent>/manifest.json + snapshots/）  
   - 删除任何可能暗示「整文件回滚是默认行为」的残留表述，统一以字段级为主

5. **不需要吸收的低价值点**  
   - Doc1 对「市场绝对空白」的过度宣称（已证伪）  
   - 任何把 Scope 扩大到 MCP/Skills 的暗示（三份都已否决）  
   - 过细的实现伪代码（最终规格保持架构级即可）

### 四、最终文档结构建议（基于 GLM 骨架微调）

保持 GLM 原有章节顺序与「公理 → 决策 → 架构 → 路线图」的叙事节奏，仅做以下增强：

1. 在「技术选型」后增加「分发矩阵」独立小节  
2. 把「首批适配器」升级为带优先级与保护字段的完整矩阵  
3. 在「安全机制」中补充三阶段提交与多文件策略细节  
4. 在「路线图」中补充 Phase 1 硬验收标准与金样测试策略  
5. 增加「CLI 命令完整规格」独立小节（或大幅扩充现有部分）  
6. 补充架构分层图与 `acm init` 流程描述

按以上清单吸收后，最终版将同时具备：
- GLM 的诚实叙事、字段级安全引擎、职责分离、公理清晰度
- Doc1 的分发体验与 CLI 完整度
- Doc3 的优先级、验收标准与 init 流程细节

这样既保持 GLM 的哲学优势，又补齐了可落地的工程细节，形成真正可执行的单一权威规格。
