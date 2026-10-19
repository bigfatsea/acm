# ACM MVP 实施 Action Plan v1.0

<!-- Version: 1.0.0 | Date: 2026-08-24 | Status: 待审阅（不 commit，留工作区） -->
<!-- 输入：docs/ACM_PROJECT_PRINCIPLE_v2.1.md（治理原则，全程遵守）
          docs/ACM_PROJECT_SPEC_v2.1.md（实现参考，MVP 范围定义见 §12 与附录 D） -->

> **本文档性质**：MVP 落地的**执行规划**（Action Plan），不是源码。
> 内容覆盖：工程基线、项目结构、依赖引入、模块构成、Function 职责与关键算法方案、任务包拆分、
> 每任务包的单元测试与验收标准、端到端硬性验收、风险对策，以及规划过程中发现的**待拍板问题**。
> 下一阶段编码时，以本文档为蓝本逐任务包生成实现代码。
>
> **遵守的治理底线（来自 PRINCIPLE v2.1，不可违背）**：
> ① 管理的是字段不是文件；② 未管字段语义级无损保留、显式暴露一切"ACM 不知道的事"；
> ③ 写前快照 + 原子替换 + 非阻塞排他锁；④ `${ENV}` 引用硬失败零写盘；
> ⑤ 漂移默认阻断 + `--force` 显式覆盖；⑥ 投影损失必须告警不静默丢弃；
> ⑦ 适配器只编译不写盘（一切磁盘写入走唯一通道）；⑧ 配置与状态分离（状态永不写回 config.toml）；
> ⑨ 铁律：绝不碰 MCP/插件/Skills/权限/hooks/私有 DB/`~/.claude.json`/`models-store.json`。

---

## 目录

1. [执行摘要：MVP 定义回顾与任务包总览](#1-执行摘要)
2. [环境与工程基线（已验证）](#2-环境与工程基线)
3. [目标项目结构](#3-目标项目结构)
4. [核心设计要点（MVP 简化契约与关键算法）](#4-核心设计要点)
5. [任务包分解 WP0–WP9（WP5 拆分为 WP5a/WP5b）](#5-任务包分解)
6. [测试与质量策略](#6-测试与质量策略)
7. [端到端验收（MVP 硬性验收 8 条）](#7-端到端验收)
8. [风险与对策（MVP 特定）](#8-风险与对策)
9. [重要设计决策与待拍板项](#9-重要设计决策与待拍板项)
- [附录 A：金样 fixture 规范](#附录-a金样-fixture-规范)
- [附录 B：MVP 相关术语速查](#附录-bmvp-相关术语速查)

---

## 1. 执行摘要

### 1.1 MVP 定义回顾（源自 SPEC v2.1 §12，权威范围）

**MVP = Phase 1 · Slice 1 + Slice 2。**

| 维度 | Slice 1 | Slice 2 |
|---|---|---|
| 命令 | `init`（含 VMR 探测与提案确认）/ `use <profile>` / `status` / `rollback`；全局旗标 `--dry-run` `--force` `--no-color` `--show-secrets` | —（沿用 Slice 1 命令面） |
| 适配器 | **Claude Code → Codex**（分片交付） | **Pi**（补齐 P0 三件套） |
| 数据 | `config.toml`（providers/models/profiles）+ `state/active` + `state/<agent>/last_write.json` + `state/<agent>/snapshots/<ts>/`（Append-only） | — |
| Writer | JSON = stdlib 保序；TOML = tomlkit round-trip | — |
| 安全底线（不可降级） | 白名单封闭写入；写前整文件快照；tempfile + `os.replace` + 非阻塞 flock；pre-commit 指纹校验；`${ENV}` 硬失败零写盘；**受管字段漂移检测 + 默认阻断（退出码 2）+ `--force`**；投影损失 stderr 告警并在 status 汇总；输出掩码；state 目录 0700 | — |
| 架构形态 | 适配器 = 数据驱动映射表 + 少量普通代码；**不做正式 Protocol 类层级、不设 ChangeSet 子系统命名**；写入走唯一通道函数（白名单校验 → 快照 → 内存修改与非管节点断言 → 指纹校验 → 原子替换 → 记 last_write） | — |
| 收尾 | 内部 pip -e/uvx 跑通 | **PyPI 发布**（uvx / uv tool install / pipx 可用） |

**明确不在 MVP（触发式后置，不实现、不占位）**：`apply` / `diff` / `doctor` / `history` / `release` / 独立 `import vmr` / `bind` / Journal 与字段级回滚 / `rollback --to-tx` / `--snapshot` 参数 / 显式 protected_paths 黑名单 / 正式 Adapter Protocol 类层级 / YAML、JSONC Writer / **Aider 适配器**（随 P1 引入）/ `--json` 输出。

> 注：`rollback` 在 MVP 中**只交付整文件恢复**（等价于终局的整文件恢复语义；MVP 恢复目标 = 更新前 `last_write.backup_id` 指向的快照）。

### 1.2 任务包总览

| 包 | 名称 | 一句话目标 | 规模 | 前置依赖 | 核心验收要点 |
|---|---|---|---|---|---|
| **WP0** | 工程脚手架 | 包骨架、依赖基线、工具链、测试基建 | S | — | `uv run acm --version` 可跑；ruff/mypy/pytest 全绿；lock 无漂移 |
| **WP1** | Core Config 模型与解析 | config.toml 三层 schema、校验、ENV 引用、ResolvedProfile | M | WP0 | 正反例单测全绿；注释 round-trip 保留 |
| **WP2** | Format Writers | JSON 保序 + TOML round-trip + 解析树 diff 断言 | M | WP0 | round-trip 金样全绿（先于适配器交付） |
| **WP3** | Safety Engine 唯一写通道 | 六步流水线、快照、指纹、原子替换、写锁、last_write | L | WP1, WP2 | 故障注入全套负面测试全绿 |
| **WP4** | 状态判定与漂移 | 六态机、漂移检测、幂等、Desired State 计算骨架 | M | WP1, WP3 | 六态矩阵单测全绿 |
| **WP5a** | VMR 探测与提案构建 | vmr.py：多端点容错探测 + `/v1/models` 解析 + 提案/模板构建（独立可测） | S/M | WP1 | 探测/提案单测全绿（fake VMR 注入） |
| **WP5b** | CLI 命令面 | init/use/status/rollback + 全局旗标 + 退出码 + 输出掩码/日志 | M | WP1–WP4, WP5a | CliRunner 集成测试全绿；退出码规范测试全绿 |
| **WP6** | Claude Code 适配器 | 映射表 + env 块注入 + 金样 a/b/c | M | WP2–WP5b | 金样三步断言全绿 + CLI 集成测试 |
| **WP7** | Codex 适配器 | env_key 单文件投影（config.toml；auth.json 备选）+ 注释密集夹具 | M | WP2–WP5b | 金样三步断言全绿 +（若启用双文件）中途失败注入 |
| **WP8** | Pi 适配器（Slice 2） | 注册式投影 + 全新建 models.json 场景 | M | WP2–WP5b | 金样三步断言全绿（含"文件不存在→创建"） |
| **WP9** | 端到端验收与发布 | Slice 1 内部跑通 → PyPI 发布 → 硬性验收 8/8 | M | WP0–WP8 | 8 条硬性验收全过；uvx/tool/pipx 安装验证 |

### 1.3 依赖图与推荐执行顺序

```
WP0 ──┬── WP1 ──┬── WP4 ──┬── WP5b ──┬── WP6 ──┬── WP7 ──┬── WP8 ──┐
      │         └── WP5a ─┘          └─────────┴─────────┴─────────┴── WP9
      └── WP2 ──┴── WP3 ──┘
```

推荐顺序：**WP0 → WP1 → WP2 → WP3 → WP4 → WP5a → WP5b → WP6 → WP7 → WP8 → WP9**（WP5a 可提前至 WP4 后并行，便于独立验收 VMR 探测）。
（WP5b 的 `use` 编排逻辑先以 stub 适配器验收；`use` 的 CLI 集成测试随 WP6/7/8 逐适配器落地。WP5b↔WP6 可并行或交错。）

**里程碑**：
- **M1（内核就绪）**：WP0–WP4 完成 → Safety Engine + Writers + Core Config 全部有单测背书。
- **M2（Slice 1 完成）**：WP5a/WP5b–WP7 完成 → 本机 `init → use daily` 让 Claude Code + Codex 指向同一套模型（≤3 条命令），内部 uvx/pip -e 跑通。
- **M3（MVP 完成）**：WP8–WP9 完成 → Pi 适配器齐 + PyPI 发布 + 硬性验收 8/8。

---

## 2. 环境与工程基线

### 2.1 本机环境验证结果（2026-08-24 实测）

| 项 | 实测结果 | 对规划的影响 |
|---|---|---|
| uv 版本 | 0.11.28 | 支持 uv sync/lock/run/uvx/tool，满足分发策略（SPEC D5） |
| 默认 Python | 3.12.13（uv 托管，`uv python list` 确认） | 与 SPEC D2 基线 3.12+ 一致；`.python-version` = 3.12 |
| 已有工程 | pyproject.toml + uv.lock 已存在；`src/acm/__init__.py` 为 stub（`Hello from acm!`）；无 tests/ | WP0 在既有骨架上改造，不新建仓库 |
| 已安装 Agent | claude（~/.local/bin）、codex、pi（pnpm）均存在 | P0 三适配器的真实环境验证目标 |
| Claude Code 配置 | `~/.claude/settings.json` 存在 | 金样夹具来源（脱敏） |
| Codex 配置 | `~/.codex/config.toml` 存在 | env_key 单文件投影 + 注释密集 MCP 表夹具来源（脱敏；auth.json 备选） |
| Pi 配置 | `~/.pi/agent/settings.json`（153B）存在；`models-store.json`（365KB，内部注册表**绝不碰**）存在；**`models.json` 不存在** | Pi 全新建文件场景 = 真实场景（非假设） |
| VMR | `127.0.0.1:8800` 存活；`/healthz` **404**；`/v1/models` **200** 返回 `[{id:agent},{id:cheap},{id:coding}]` 且含 `vmr_protocol` 字段；`~/.vmr/` 仅有 image_cache/logs（无配置文件） | **Spec §9 探测顺序已按多端点容错同步**（见 A2）；探测实现多端点容错 |
| 项目 git | main 分支，working tree clean | 产出文档不 commit，留在工作区 |

### 2.2 依赖引入决策（对齐 SPEC D2 依赖预算）

**运行时依赖（锁定在 uv.lock，CI 检查漂移）**：

| 依赖 | 用途 | 预算归属 |
|---|---|---|
| `typer` + `rich` | CLI 框架 + 终端渲染 | 计 1 组 |
| `tomlkit` | Core Config 与 Codex config.toml 的 round-trip 编辑 | 硬依赖（Codex P0 零新增） |
| `pydantic` | **保留**（Core Config 校验规则将超 200 行；uv.lock 已锁定，零增量成本） | 预算内 |

- **stdlib 承担，不引入新依赖**：JSON 保序编辑（json + object_pairs_hook）、文件锁（`fcntl`，仅 macOS/Linux）、VMR 探测 HTTP（`urllib.request` + 超时）、指纹（`hashlib.sha256`）、原子写（`tempfile` + `os.replace`）。
- 明确**不引入**：requests、click（typer 自带）、commentjson/jstyleson（Spec 附录 B 已实证否决）、watchdog、psutil。
- 开发依赖（现有）：`pytest` + `pytest-cov`、`ruff`、`mypy`（strict）。CI 另加 `uv lock --check` 步骤。

### 2.3 pyproject.toml 基线调整清单（WP0 执行）

1. 依赖清单按 A1 拍板结果落定（含 pydantic 去留）。
2. 版本单一来源：`__version__ = "0.1.0"` 定义于 `acm/__init__.py`；pyproject 若支持 dynamic version 则读取之，否则保留 pyproject 静态版本、`__init__.py` 经 `importlib.metadata` 读取保持一致（实现时取最小改动，CLI `--version` 与包版本恒一致）。
3. 保留现有 ruff（line-length=100）/mypy（strict）/pytest（testpaths=tests）配置；补充 pytest 的 fixture 目录说明。
4. 入口 `acm = "acm:main"` 保持不变（main 由 WP5b 实现）。
5. README 文档链接修复/标注（指向已删除文档的链接，见待拍板 A8）。

---

## 3. 目标项目结构

### 3.1 目录树（MVP 终态）

```
acm/                              # 仓库根（现有）
├── pyproject.toml / uv.lock / README.md / .python-version
├── docs/                         # 规格文档（现有，含本文档）
├── src/acm/
│   ├── __init__.py               # 版本常量、包元数据
│   ├── __main__.py               # python -m acm 入口（委托 main）
│   ├── main.py                   # main()：组装 typer 应用并执行（WP5b）
│   ├── cli.py                    # typer 命令定义：init/use/status/rollback + 全局旗标（WP5b）
│   ├── errors.py                 # 异常层级与退出码映射（1/2/3/4/130）（WP5b）
│   ├── config.py                 # Core Config：加载/结构校验/schema 版本/TOML round-trip（WP1）
│   ├── resolve.py                # ENV 引用语法校验与实时求值、ResolvedProfile（WP1）
│   ├── state.py                  # state 目录管理：active 读写、last_write 读写、目录权限、启动清理（WP3/WP4）
│   ├── lock.py                   # 非阻塞全局写锁（fcntl；仅 macOS/Linux，无 Win 分支）（WP3）
│   ├── safety.py                 # ★唯一写通道：六步流水线、快照留存、指纹、原子替换（WP3）
│   ├── status.py                 # 六态判定、漂移检测、幂等判断（WP4）
│   ├── projection.py             # Desired State 计算骨架（profile → per-agent 期望字段）（WP4）
│   ├── vmr.py                    # VMR 探测（多端点容错）与提案构建（WP5a）
│   ├── output.py                 # rich 渲染、--no-color/NO_COLOR、stderr/stdout 流约定（WP5b）
│   ├── masking.py                # 敏感字段掩码（首尾 3 位）、--show-secrets（WP5b）
│   ├── util.py                   # 路径 Helper（env 覆盖→XDG→平台默认→探测）；测试 HOME 注入（WP1/WP3）
│   ├── writers/
│   │   ├── __init__.py           # Writer 能力声明契约（语义/注释/键序/空白四级保证）与注册（WP2）
│   │   ├── json_editor.py        # 保序 JSON 编辑（键序/缩进/末尾换行/非 ASCII 行为保持）（WP2）
│   │   ├── toml_editor.py        # tomlkit round-trip 编辑 + 点路径读写 + 新建表（WP2）
│   │   └── tree_diff.py          # 解析树 diff 断言（非管节点零篡改）（WP2）
│   └── adapters/
│       ├── __init__.py           # 注册表（确定性顺序 [claude_code, codex, pi]）、类型别名（PlannedOp/FieldOp/Warning）（WP5b/WP6）
│       ├── claude_code.py        # 映射表 + detect/config_paths/plan（WP6）
│       ├── codex.py              # env_key 单文件投影 + model_providers 表（WP7；auth.json 备选）
│       └── pi.py                 # 注册式投影 + 全新建文件（WP8）
└── tests/
    ├── conftest.py               # 隔离 HOME fixture、金样配置工厂、路径注入（WP0）
    ├── fixtures/
    │   ├── configs/              # Core Config 金样（含非法样本）
    │   ├── claude_code/          # settings.json 金样（脱敏）
    │   ├── codex/                # config.toml 金样（脱敏，注释密集；auth.json 备选）
    │   ├── pi/                   # settings.json / models.json 金样（脱敏）
    │   └── writers/              # JSON/TOML round-trip 词法金样
    ├── unit/                     # 各模块单测（test_config/resolve/lock/status/masking/...）
    ├── golden/                   # 各适配器金样 a/b/c 断言（test_adapters_claude/codex/pi）
    ├── fault/                    # 故障注入（test_fault_injection / test_lock_contention / test_sigkill）
    └── integration/              # CLI 集成（test_cli_init/use/status/rollback）+ e2e_acceptance
```

### 3.2 模块职责边界（防越权铁律）

- **config.py / resolve.py**：只读解析与纯计算，不产生任何 I/O（除显式的 load/save 入口函数）。
- **adapters/*.py**：只编译（profile → ops + warnings），**运行时零物理 I/O**；对磁盘的所有访问仅通过 `config_paths()` 声明 + `plan()` 输出路径。契约等价于 PRINCIPLE §3.4，但 MVP **不引入 Protocol 类层级**（见 §4.1）。
- **safety.py**：唯一写通道。任何其他模块不得直接写 Agent 配置文件；通过 code review 与单测强制（金样断言"文件只经安全引擎变更"）。
- **state.py / lock.py**：只负责 `~/.acm/state/` 与 `~/.acm/logs/`；`config.toml` 的写仅允许 `init`（生成/覆盖）与用户手编（SSOT 归属用户）。

### 3.3 MVP 数据流（简化流水线）

```
config.toml（SSOT，用户可手编/init 生成）
   → resolve（ENV 实时求值；缺失 → 硬失败 exit 1，零写盘）
   → ResolvedProfile
   → adapter.plan()（纯函数：映射表 + 少量转换，产出 PlannedOp(期望值) + warnings；不碰文件、不读磁盘当前事实）
   → Safety Engine 唯一写通道（核心五步 + 状态收尾一步）：
       ① 白名单校验（file ∈ config_paths；path ∈ 命名空间）失败 → exit 2
       ② 写前整文件快照 + 读 H0（NOT_EXIST 咽兵）→ Safety 依 H0/当前值把 PlannedOp 补全为完整 FieldOp(file,path,old,new,created)（created=H0==NOT_EXIST；old=当前值）→ state/<agent>/snapshots/<ts>/（Append-only）
       ③ 内存修改 + 非管节点断言（Writer round-trip → 语法自检 → **语义级**解析树 diff 零篡改）
       ④ pre-commit 指纹校验（批处理：全部文件重读字节 sha256 == H0；任一不等 → 中止 exit 2，绝不覆盖）
       ⑤ os.replace 原子替换（跨文件按序提交；异常回退清理 temp）
       ⑥ 覆写 last_write.json（profile/时间/backup_id/受管字段值）
   → 输出：投影告警聚合（stderr）+ rich 汇总（stdout）
```

---

## 4. 核心设计要点

### 4.1 MVP 简化契约（对齐 SPEC §12 Slice 1"不做正式 Protocol 类层级"）

- **适配器模块接口**（模块级约定，非 Protocol 类）：每个适配器模块导出以下实体：
  - 常量：`AGENT_ID`（如 `"claude_code"`）、`DISPLAY_NAME`。
  - `detect(env) -> bool`：**主判据 = "可执行文件或配置目录存在"**（提升全新机器开箱路径：装好 Agent 未运行过也能被接管）；配置文件存在时优先（快路径 + 丰富接管信息）；配置文件不存在且可执行存在 → 标记"可接管（将创建）"，`use` 时创建（与 Pi 全新建文件同一机制）。失败 → 该 Agent 跳过并汇总告警，不影响其他 Agent。（与 SPEC §7.4 一致）
  - `config_paths(env) -> list[Path]`：声明本适配器管理的全部文件路径（= Safety Engine 快照/加锁/白名单的边界）；必须经 `util.py` 路径 Helper，禁止硬编码绝对路径。
  - `plan(profile, env) -> tuple[list[PlannedOp], list[ProjectionWarning]]`：纯函数编译，产出**期望值 ops**（`PlannedOp(file, path, new)`）与未映射告警。**无磁盘 I/O**（不读磁盘当前事实）。
- **最小数据结构**（放 `adapters/__init__.py`，MVP 不设独立 ChangeSet 子系统）：
  - `PlannedOp(file, path, new)`：Adapter 产出的**纯期望值**；`path` 为点路径（如 `"env.ANTHROPIC_BASE_URL"`、`"model"`、`"model_providers.coding.base_url"`）。**不含磁盘当前事实**（`old`/`created` 由 Safety 依磁盘判定，见下）。
  - `FieldOp(file, path, old, new, created)`：Safety 依磁盘事实把 `PlannedOp` 扩展为完整操作——`created` 由 `H0 == NOT_EXIST` 判定（文件原本不存在）；`old` 由当前磁盘值判定（含"不存在"哨兵）；供 Writer/幂等/漂移/回滚使用。
  - `ProjectionWarning(field, agent_id, reason)`：Desired State 中无法表达/需降级表达的字段，进入告警。
- **白名单**：`op.path` 必须命中该适配器映射表声明的命名空间前缀集合；`op.file` 必须在 `config_paths()` 返回集合内。MVP 不做显式黑名单（`protected_paths` 触发式后置）；"绝不碰 `~/.claude.json`/`models-store.json`"由白名单封闭性天然保证（这些文件根本不在 config_paths/命名空间内）。

### 4.2 关键算法与方案要点（编码蓝本，非源码）

| 主题 | 方案要点 |
|---|---|
| **JSON 保序 Writer** | 用 `json.loads(..., object_pairs_hook=OrderedDict)` 保序解析；缩进宽度从源文本嵌套行前导空白探测；末尾换行存在性探测；非 ASCII 行为探测（源含原样非 ASCII → dump 时 `ensure_ascii=False`）；写入 = 目标路径赋值后整体序列化，键序天然保持。词法保证按 SPEC §7.5.4 JSON 行（语义保证、键序保证、缩进/末尾换行保留） |
| **TOML round-trip** | tomlkit parse 为 Document；点路径 get/set；新建表用 tomlkit table API（Codex `model_providers.<id>`）；注释/键序免费保留。词法保证按 fixture 界定 |
| **解析树 diff（非管节点断言）** | 修改前后各解析一次，递归比较解析树，排除受管点路径对应节点；**语义级**比较（结构 + 值，int/float 数值等价容差：`1` 与 `1.0` 视为等价；词法差异不计入 runtime 阻断）；其余语义 100% 相同才通过。Safety 阶段 ③ 与金样断言共用此工具 |
| **指纹与快照** | 写前读原始字节，`sha256` 记 H0（文件不存在 → 哨兵 `NOT_EXIST`）；快照 = 原始字节原样拷贝至 `state/<agent>/snapshots/<ts>/`（文件名保持，避免路径碰撞时加序号）；`<ts>` = UTC epoch 纳秒固定宽度零填充（字典序 = 时间序，仅用于列出/审计）。**rollback 恢复目标 = 更新前 `last_write.backup_id` 指向的快照**（非"最新"/非字典序最大）；恢复前快照（A12）写入**新** `backup_id` 后即成为下一次 rollback 的目标（undo-undo），仅当次恢复排除，**不引入持久排除标记**。Append-only，不做 FIFO 清理 |
| **原子写** | 同目录 temp 文件（后缀 `.acm_tmp`）→ `os.replace` 原子替换；启动时清理残留 `.acm_tmp`（静默内务）。多文件按声明顺序提交（见 Codex 双文件顺序，仅备选启用时） |
| **写锁** | `state/.lock` 上 `fcntl.flock(LOCK_EX|LOCK_NB)`（MVP 仅 macOS/Linux，无 Win 分支）；占用 → 立即报错 `⚠️ Another acm process is holding the write lock.`，exit 2，不排队 |
| **漂移检测** | 对每个受管字段：当前磁盘值（经 Writer 读取）vs `last_write.json` 存值（**存值非哈希**，PRINCIPLE §3.3）；不等 → 判定为外部修改。**阻断定位为"写入前的覆盖保护"**：仅当存在 `Current != Desired` 且其中含漂移字段时写命令默认阻断（报 expected/found，展示走掩码，exit 2，`--force` 显式覆盖）；若所有受管字段 `Current == Desired`（无写入发生）则 no-op、仅 `status`/提示展示漂移，不阻断（见幂等行）。**无自动修复路径**。阻断消息含 expected/found + 建议 `use --dry-run` |
| **六态判定** | `NOT_DETECTED`（未安装）/ `UNMANAGED`（已安装未接管）/ `SYNCED`（Current==Desired 无漂移）/ `OUT_OF_SYNC`（Current==last_write≠Desired）/ `DRIFTED`（Current≠last_write）/ `ERROR`（不可读/语法损坏/权限异常）。优先级 `ERROR > DRIFTED > OUT_OF_SYNC > SYNCED`；`NOT_DETECTED`/`UNMANAGED` 由安装与接管状态先行判定。MVP 全量实现六态（SPEC §7.6） |
| **幂等** | 判定顺序：① 所有受管字段 `Current == Desired` → no-op（exit 0），**即使存在漂移也仅提示不阻断**（无写入则无覆盖风险，无需 `--force`）；② 存在 `Current != Desired` 且其中含漂移字段 → 阻断（exit 2）；③ 无漂移且 `Current != Desired` → 正常投影收敛。no-op 均**不产生新快照**（SPEC §7.5.8） |
| **ENV 引用** | 语法仅 `${VAR}` 与 `${VAR:-default}`，整字段替换（正则白名单校验，拒绝子串/嵌套/命令替换）；**投影时实时求值**；缺失且无默认 → 硬错误列表，任何写入发生前整体中止，exit 1 |
| **掩码** | 路径 token 命中敏感规则（api_key/token/auth/secret/key 类）→ 值只显示首尾各 3 位；`--show-secrets` 明文 opt-in。作用于 diff/status/init 提案/last_write 展示 |
| **双文件提交顺序（Codex，备选方案）** | **默认 env_key 单文件方案**（ACM 只写 config.toml，`model_providers.<id>.env_key` = 环境变量名，Codex 运行时自读，ACM 不落盘明文；本机实证 auth.json 为 Codex 运行态 OAuth 文件）；auth.json 双文件为**备选**（仅当 env_key 不可行时启用）。若启用：先写 `auth.json`（key），后写 `config.toml`（引用 key 的 `env_key`）；失败影响最小化：先失败 → 仅多一个孤儿 key（无害）；后失败 → 文件已更新但 last_write 未记 → 下次被漂移检测阻断，`rollback` 兜底（SPEC §7.5.6 已认可该窗口） |
| **VMR 探测** | 顺序容错：`GET /healthz`（快速通道）→ `GET /v1/models`（**主证据**，实测 200 且即数据源）→ 读取 `~/.vmr/` 已知配置（如存在）→ 全失败则未探测到。超时 ≤1s。命中 → 从模型列表（id + `vmr_protocol`）构建提案（providers.vmr + models.* + 默认 profile daily）。（Spec §9 已同步） |
| **init 提案** | 扫描 Agent（detect）→ 探测 VMR → 构建提案：VMR 命中 → providers.vmr（base_url=`http://127.0.0.1:8800/v1`、protocol 取 vmr_protocol、api_key=`${VMR_KEY:-}`（生成时附注释：本地代理无鉴权可留空，需鉴权则设 VMR_KEY））+ 各虚拟模型 + `profiles.daily{main="coding"}`（或首个模型）；VMR 未命中 → 生成含注释示例的模板 config.toml（用户手编 SSOT 属合法路径，成功标准只约束"零手改 **Agent 配置文件**"）。rich 展示提案 → 交互确认 → 写入 config.toml + 创建 state 目录（0700）+ 生成 `~/.acm/.gitignore`。config 已存在 → 提示 覆盖/取消（默认取消，绝不静默破坏）；`--force` 跳过提示（增量合并范围见待拍板 A3） |
| **批处理原则** | `use`/`status` 遍历注册表固定顺序，按 Agent 独立运算收敛；单 Agent 阻断/失败不中断其余；stderr 明确指出失败 Agent；最终退出码 = 全部 Agent 的最高严重度（PRINCIPLE §4.3.6） |
| **崩溃安全** | 写前快照 + 原子替换消除中间损坏态；无重量级 WAL 状态机（SPEC §7.5.6）；提交间隙 SIGKILL 的最坏后果 = 部分文件已更新/未记 last_write → 各文件自身完整，靠漂移阻断 + `rollback` 复原；属保护机制正常表现（文档告知：`use --force` 可重新对齐） |
| **文件权限** | `~/.acm/state/` 与 `logs/` 创建即 `0700`、内部文件 `0600`（含快照，因其可能含明文密钥） |

### 4.3 测试卫生（贯穿所有任务包）

- **一切测试使用隔离 HOME**：conftest 将 `HOME`/`XDG_CONFIG_HOME`（及 ACM 自定义覆盖变量）指向 `tmp_path`，真实用户配置**永不触碰**；金样来自真实文件脱敏。
- 真实环境验证（可选、谨慎）：先在隔离 HOME 跑通，再对真实配置**先备份后验证**（手动命令，不入测试）。
- 故障注入通过测试钩子环境变量（如 `ACM_TEST_FAULT_*`）驱动，生产路径零感知。

---

## 5. 任务包分解

> 每个 WP 均包含：目标 / 范围与边界 / 前置依赖 / 交付物 / 任务细项（含关键函数与算法要点）/ 测试计划 / 验收标准。

---

### WP0 工程脚手架（规模 S）

**目标**：把现有 stub 骨架升级为可开发、可测试、可锁定的工程基座。

**范围与边界**：只搭基座，不实现业务逻辑；不引入新运行时依赖的最终决策（由 A1 拍板）。

**前置**：无（本包即起点）。

**交付物**：
- `pyproject.toml` 调整（§2.3 清单）、`uv.lock` 同步
- `src/acm/__init__.py`（版本常量）、`src/acm/__main__.py`、`main.py` 占位（可 `--version`）
- `tests/conftest.py`（隔离 HOME fixture、金样工厂、路径注入）
- 质量门脚本（本地：`make check` = ruff + mypy + pytest + `uv lock --check`）+ CI 骨架（GitHub Actions，按 A9 拍板：默认本地优先，CI 随代码入库启用）
- README 文档链接修正/标注（A8）

**任务细项**：
1. 依赖清单落定（按 A1 拍板）；`uv lock` 重新生成；确认 `uv sync` 干净。
2. `__version__` 单一来源 + `--version` 出口打通。
3. conftest 提供：`tmp_home` fixture（隔离 HOME/XDG）、`make_config()`（按需生成三层 config.toml）、`install_fixture_agent()`（把金样文件铺入 tmp_home）、`env_override`（设置 VMR 探测目标/测试钩子）。
4. ruff/mypy/pytest 空跑通过（零测试也绿）；`uv lock --check` 纳入本地脚本。

**测试计划**：无业务单测；验收即测试（本包验收即质量门槛）。

**验收标准**：
- [ ] `uv sync` 成功且无警告；`uv lock --check` 通过。
- [ ] `uv run acm --version` 输出 `0.1.0`，exit 0。
- [ ] `uv run ruff check . && uv run ruff format --check .` 通过（空代码也过）。
- [ ] `uv run mypy src` 通过（strict 模式，空包即可过）。
- [ ] `uv run pytest` 通过（可零测试）。
- [ ] README 不再包含指向已删除文档的失效链接（或已加"归档"标注）。

---

### WP1 Core Config 模型与解析（规模 M）

**目标**：`~/.acm/config.toml`（providers/models/profiles 三层）的加载、结构校验、schema 版本检查、ENV 引用语法校验与实时求值、ResolvedProfile 计算。全部纯逻辑，可脱离磁盘单测。

**范围与边界**：只读解析 + 校验 + 求值；**不写盘**（写盘仅 init，见 WP5b）。不支持迁移命令（`version` 未知即明确报错）。

**前置**：WP0。

**交付物**：`config.py`、`resolve.py`、`util.py`（路径 Helper 部分）。

**任务细项（关键函数与算法）**：
1. `load_config(path) -> CoreConfig`：tomlkit 解析 → 结构校验 → `version == 1` 校验（未知版本 → 明确报错 exit 1，文案提示"升级 acm 或手改 version"——**不提 doctor**（命令不在 MVP））。
2. 结构校验规则（**必填/可选两档**；校验失败 → exit 1，错误信息尽量定位到表/键）：
   - **必填（MVP 最小集）**：
     - `providers.*`：`protocol ∈ {openai, anthropic, openai-responses}`、`base_url`（URI 形状校验）、`api_key`（允许 `${VAR}` 引用或明文；明文合法，init 生成时提示一次）；
     - `models.*`：`provider` 必须引用存在的 provider；`id` 非空；
     - `profiles.*`：`main` 必填且引用存在的 model；至少一个 profile。
   - **可选（写了则校验 + 尽力投影，不能映射 → 投影损失告警；不写则沉默）**：`context_window`/`max_output_tokens` 正整数；`temperature` 数值；`capabilities` 枚举校验（`vision: bool`、`tools ∈ {native,xml,markdown}`、`json_mode: bool`）；`reasoning.effort ∈ {low,medium,high}`、`reasoning.budget_tokens` 正整数；其余角色槽位（`cheap` 等）须引用存在的 model；`headers`/`proxy`（字典/URI）。
   - 注：必填集缩小后，VMR 提案生成短文件（仅必填字段），与投影损失告警机制天然一致。
3. ENV 引用语法校验（`resolve.py`）：整字段匹配 `${VAR}` / `${VAR:-default}` 白名单正则；拒绝子串插值/嵌套/命令替换 → schema 错误。
4. `resolve(profile, env) -> ResolvedProfile`：投影时实时求值（不在加载时固化）；收集全部未解析引用（缺失且无默认）→ 返回硬错误列表（调用方在**任何写入前**中止，exit 1）。
5. round-trip 保留：`config.toml` 的读取/回写（MVP 中仅 init 覆盖生成与未来 import 用）必须保留用户注释与键序（tomlkit）。
6. 路径 Helper：`resolve_agent_path(agent_id, rel, env)` 解析顺序 = env 覆盖变量 → XDG → 平台默认 → 探测；测试经 HOME/XDG 注入隔离。

**测试计划**（`tests/unit/test_config.py`、`test_resolve.py`）：
- 正例：三层完整配置解析正确；注释/键序 round-trip 保留断言。
- 反例矩阵：缺 protocol、protocol 非法、base_url 缺失、model 引用不存在的 provider、profile 引用不存在的 model、capabilities 枚举非法、reasoning.effort 非法、version 非 1。
- ENV 语法边界：`${VAR}`、`${VAR:-default}`、`${VAR:-}`（空默认值）、子串插值拒绝、嵌套拒绝、`${}` 空变量名拒绝、明文+引用并存拒绝。
- 求值：有默认值回退、无默认缺失 → 硬错误列表（多引用同时缺失全量列出）。
- 幂等：同一配置重复解析结果一致。

**验收标准**：
- [ ] 上述单测全绿（覆盖正反例 ≥ 30 例）。
- [ ] 所有校验错误信息可定位到具体表/键（含行号，tomlkit 提供）。
- [ ] 未解析引用在**零写盘**前提下以错误列表整体暴露（不逐条中断）。
- [ ] 本包不产生任何磁盘写入（可由单测断言：无 `~/.acm` 副作用）。

---

### WP2 Format Writers（规模 M）

**目标**：JSON 保序 + TOML round-trip 两个 Writer 及解析树 diff 断言工具；**先于任何适配器交付**（SPEC §11.3）。

**范围与边界**：只做内存读改写 + 序列化；不做文件 I/O 与安全语义（属 WP3）；不做 YAML/JSONC（MVP 外）。

**前置**：WP0。

**交付物**：`writers/__init__.py`（能力声明契约）、`writers/json_editor.py`、`writers/toml_editor.py`、`writers/tree_diff.py`。

**任务细项**：
1. 能力声明契约：每种 Writer 声明语义/注释/键序/空白四级保证（对齐 SPEC §7.5.4 表：JSON 语义=保证、注释=n/a、键序=保证、空白=缩进风格探测匹配+末尾换行保留；TOML 语义=保证、注释/键序/空白=fixture 界定）。契约对象暴露 `capabilities()` 供测试与文档断言。
2. JSON 保序编辑：保序解析（object_pairs_hook）；缩进探测（嵌套行前导空白统计取众数）；末尾换行探测；非 ASCII 行为探测；点路径 get/set（新建路径可创建）；整值替换不重排。
3. TOML round-trip：tomlkit Document 点路径 get/set；新建嵌套表（Codex `model_providers.<id>` 场景）；注释/键序保留断言。
4. `tree_diff(parsed_before, parsed_after, managed_paths) -> list[str]`：递归比较解析树，排除受管路径节点，返回非管差异清单；Safety 阶段③ 与金样断言共用。要点：统一为**语义级比较**（结构 + 值），int/float 数值等价容差（`1` 与 `1.0` 视为等价）；**词法差异不计入 runtime 断言**，仅测试层按 fixture 界定（与 §4.2/WP3③ 一致）。

**测试计划**（`tests/unit/test_writers_json.py`、`test_writers_toml.py`、`test_writers_diff.py`；`tests/fixtures/writers/`）：
- JSON：键序保持（逆序输入 → 逆序输出）、缩进探测（2/4/制表符样本）、末尾换行有无两态、非 ASCII 两态（原样/转义）、整值替换后其余内容**语义不变 + 词法按 fixture 界定**（对金样 fixture 子集断言词法保留；**通用承诺 = 语义保证 + 键序保证 + 缩进风格匹配 + 末尾换行保留，不承诺任意输入的字节级不变**）。
- TOML：注释保留（行注释/表头注释/值后注释）、键序保留、空行保留、新建表后原有内容不变、解析-序列化-再解析字节级稳定。
- tree_diff：修改受管路径 → 无差异；修改非管节点 → 精确列出差异；空改 → 空清单。

**验收标准**：
- [ ] round-trip 金样全绿（SPEC §11"Writer round-trip 单测先于适配器交付"硬性前置）。
- [ ] 两种 Writer 的能力声明与测试断言一致（能力表可查询、可审计）。
- [ ] tree_diff 在受管修改场景零误报、非管修改场景零漏报（单测覆盖）。
- [ ] 本包不产生磁盘写入（内存操作，单测断言无副作用）。

---

### WP3 Safety Engine 唯一写通道（规模 L）

**目标**：实现唯一磁盘写通道的六步流水线（核心五步 + last_write 状态收尾） + 快照留存 + 指纹校验 + 原子替换 + 全局写锁 + last_write 落盘 + 崩溃清理。**本包是整个 MVP 安全的脊梁**。

**范围与边界**：只提供"写通道"能力（输入 ops → 完成写盘），不感知 CLI/适配器语义；不做漂移检测（属 WP4，但提供漂移所需数据源 last_write 的写）；不做六态判定。黑名单机制 MVP 不实现（白名单封闭）。

**前置**：WP1（路径/状态目录约定）、WP2（Writer）。

**交付物**：`safety.py`、`lock.py`、`state.py`（state 目录与 last_write 部分；state.py 分阶段填充：本包建目录/权限/锁/last_write 写，WP4 补 active 与 last_write 读）。

**任务细项（关键函数与算法）**：
1. `acquire_write_lock()` / `release_write_lock()`：`fcntl.flock` 非阻塞；占用 → `SafetyBlockedError`（exit 2）+ 标准文案。**MVP 仅 macOS/Linux，无 Win 分支**。
2. `write_changeset(agent_id, profile_name, ops, env) -> WriteResult`：串起六步流水线（核心五步 + 状态收尾一步）：
   - ① 白名单校验：`op.file ∈ config_paths()` 且 `op.path` 命中命名空间前缀；违反 → `SafetyBlockedError`（exit 2），**任何文件零变更**。
   - ② 写前快照 + Safety 补全 FieldOp：逐文件读原始字节记 H0（含 `NOT_EXIST` 哨兵）；依 H0/当前值把 `PlannedOp` 扩展为 `FieldOp(file,path,old,new,created)`（`created`=H0==NOT_EXIST；`old`=当前磁盘值）；快照目录 `state/<agent>/snapshots/<ts>/` 原样落盘（文件不存在 → 以哨兵标记记录"写前不存在"，供 rollback 判定**归档语义**——ACM 创建的文件恢复时 rename 归档为 `<file>.acm_orphaned.<ts>`，绝不 unlink；**归档文件与快照一致永久留存、用户按需手动清理**，不在 MVP 写路径）；目录 0700。
   - ③ 内存修改 + 非管节点断言：Writer 加载 → 应用 ops → 语法自检（可再解析）→ **语义级** tree_diff 非管节点零差异（数值等价容差：`1` 与 `1.0` 视为等价；**词法差异不计入 runtime 阻断**——词法保真仅在测试层按 fixture 界定断言）；失败 → 中止（exit 2），文件零变更。
   - ④ pre-commit 指纹校验（**批处理**）：对**全部**目标文件一次性重读磁盘字节，sha256 与 H0 逐文件比对；任一不等 → 外部并发修改 → 整体中止（exit 2）+ drift 报告，绝不覆盖；**全部通过后才进入替换阶段**（消除跨文件窗口）。
   - ⑤ 原子替换：逐文件同目录 temp（`.acm_tmp`）→ `os.replace`；按 ops 声明顺序提交（多文件顺序由适配器保证，若启用备选双文件见 WP7）；任一异常回退 → 清理 temp，已替换文件保持新值（符合 SPEC §7.5.6 语义，靠后续漂移阻断 + `rollback` 兜底）。
   - ⑥ 覆写 `last_write.json`：`{profile, timestamp, backup_id=<ts>, fields: {path: value}}`；文件 0600。
   - 空 ops（幂等）→ 直接返回 no-op，**不建快照、不写 last_write**。
3. `cleanup_stale_tmp(state_dir)`：启动时扫描并静默清理残留 `.acm_tmp`（内务，无用户感知）。
4. `ensure_state_permissions()`：state/logs 目录 0700、文件 0600 创建即设置。
5. 快照命名与检索：`<ts>` = UTC epoch 纳秒固定宽度；**rollback 恢复目标定位函数 `latest_snapshot_for_rollback(agent, backup_id)` 只服务 rollback 的唯一恢复算法**（目标 = 更新前 `last_write.backup_id` 指向的快照；`backup_id` 缺失时 fallback 字典序最大并告警，正常不应发生）；`list_snapshots(agent)` 字典序列举（供审计与 `--dry-run` 展示）。

**测试计划**（`tests/fault/test_fault_injection.py`、`test_lock_contention.py`、`test_sigkill.py`；配合 conftest 隔离 HOME）：
- 白名单外路径（file 或 path 任一越界）→ exit 2 + 文件字节级零变更。
- 多文件事务中途失败注入（测试钩子在步骤⑤第 N 文件前抛错）→ 未替换文件零变更、temp 无残留。
- 提交间隙 SIGKILL：子进程写通道运行中 `kill -9` → 磁盘无"写一半"文件（每文件要么旧字节要么新字节）；残留 `.acm_tmp` 下次启动被清理；last_write **存在但字段不一致** → 触发漂移阻断路径（由 WP4 单测配合验证）；last_write **缺失**（首次接管/中途崩溃未记）→ **不阻断、允许重投**（UNMANAGED 语义），补"首次 use 中途崩溃 → 重投即可"用例。
- 指纹不匹配：快照后、提交前外部篡改（测试钩子）→ 整体中止 exit 2，无覆盖。
- 双进程抢锁：并发子进程写同一隔离 HOME → 一方 exit 2 与标准文案，最终文件完整合法（可解析）。
- 权限失败（可行时）：目标目录只读 → exit 3，原文件完好。
- 快照：写入后快照字节 == 写前字节；Append-only（两次写入 → 两个快照目录，无删除）。

**验收标准**：
- [ ] 上述负面用例全绿（SPEC §11 MVP 期最低限负面集：白名单拦截、SIGKILL、双进程锁、指纹不匹配、ENV 缺失[在 WP1 层验证]）。
- [ ] 写通道唯一性：除 safety.py 外无任何模块含"写 Agent 配置"逻辑（code review + 金样断言"文件变更仅经通道"）。
- [ ] 幂等 no-op 不产生快照（单测断言快照目录数不变）。
- [ ] 权限：state 目录 0700 / 文件 0600 断言。
- [ ] 崩溃清理：残留 temp 在下一次任意命令启动时被清除。

---

### WP4 状态判定与漂移（规模 M）

**目标**：六态机、漂移检测、幂等判断、Desired State 计算骨架（active 读写 + last_write 读取 + per-agent 期望字段编译接线）。

**范围与边界**：只做"判定/计算"，不触发任何写入；`status` 命令的展示在 WP5b。Desired State 的适配器侧编译依赖 WP6+（本包以注册表接口 + 空实现/桩验收）。

**前置**：WP1、WP3。

**交付物**：`status.py`、`projection.py`、`state.py`（active 读写部分；承接 WP3 的 state.py，本包补 active 与 last_write 读）。

**任务细项**：
1. `read_active(env) -> str | None` / `write_active(profile, env)`：active 文件（仅存 profile 名）；写仅由 `use` 调用（WP5b 强制）；不存在 = 尚未激活（首次 use 创建，非错误）。
2. `read_last_write(agent, env) -> LastWrite | None`：读取上次投影记录（profile/时间/backup_id/字段值）。
3. `compute_state(agent, desired_profile, env) -> AgentState`：六态判定实现——（`desired_profile` = Desired 来源：use 含 dry-run = 命令行 `<profile>` 参数；status = active）
   - detect 失败 → `NOT_DETECTED`；detected 且无 last_write → `UNMANAGED`；
   - 读取当前配置失败/语法损坏/权限异常 → `ERROR`；
   - 逐受管字段比较 current vs last_write → 任一不等 → `DRIFTED`；
   - 否则比较 current vs desired（期望字段经适配器 plan 编译）→ 不等 → `OUT_OF_SYNC`；相等 → `SYNCED`。
   - 优先级 `ERROR > DRIFTED > OUT_OF_SYNC > SYNCED`；文件被删（曾创建）→ 视为 DRIFTED（期望存在值 vs found 不存在）。
   - **active=None（未激活）展示规则**：profile 列显示 `(none)`；**DRIFTED 优先**（漂移是配置事实，与 active 无关，符合现有优先级）；无漂移 → **UNMANAGED**（语义：当前未被 ACM 激活管理），`--verbose` 附 last profile / 时间；**不计算 OUT_OF_SYNC**（无 Desired 可比）；不新增第七态、不使用 SYNCED（SYNCED 严格定义需 Desired）。
4. `detect_drift(agent, env) -> list[DriftEntry]`：逐字段 expected/found（展示走掩码）。
5. `is_noop(agent, desired_profile, env) -> bool`：幂等判断（经 `plan(desired_profile)` 求期望，逐字段 `current == desired` → no-op；无写入则即使有漂移也不阻断，仅 status/提示展示）。
6. `compute_desired(desired_profile, env) -> dict[agent_id, list[PlannedOp]]`：遍历注册表，调各适配器 `plan()` 编译（期望值）；`desired_profile` 来源同任务 3（use=命令行参数、status=active）；MVP 阶段注册表为空/桩时返回空（WP6+ 填充）。
7. 未初始化判定：config.toml 缺失 → 六态计算给出"未初始化"信号（CLI 层映射为"请先 `acm init`" + exit 1，见 A10）；active 缺失 = 正常初始态（首次 use 创建），不视为错误。

**测试计划**（`tests/unit/test_status.py`、`test_projection.py`）：
- 六态矩阵：构造 NOT_DETECTED / UNMANAGED / SYNCED / OUT_OF_SYNC / DRIFTED / ERROR 各输入组合断言。
- 优先级：DRIFTED+OUT_OF_SYNC 并存 → DRIFTED；ERROR+DRIFTED → ERROR。
- 漂移 expected/found 精确值与掩码展示。
- 幂等（判定顺序）：current==desired（即使存在漂移）→ no-op；存在 current!=desired 且含漂移 → 阻断（exit 2）。
- 文件删除场景（曾创建后删除 → DRIFTED）。
- active 读写、last_write 读写 round-trip。

**验收标准**：
- [ ] 六态矩阵单测全绿（与 SPEC §7.6 枚举完全一致，无枚举缩减）。
- [ ] 漂移判定输出 expected/found 具体值（掩码后）。
- [ ] 本包零写入（除 active/last_write 显式读写函数，单测断言无其他副作用）。
- [ ] 与 WP3 联测：last_write 存在但字段不一致 → 漂移阻断路径成立；last_write 缺失（首次接管）→ 允许写入重投（配合故障注入）。
- [ ] 导出稳定公共接口（`ResolvedProfile` 结构、`plan()` 签名、`PlannedOp` 类型）——供 WP5b/WP6+ 并行开发前冻结。

---

### WP5a VMR 探测与提案构建（规模 S/M）

**目标**：VMR 多端点容错探测 + `/v1/models` 解析 + 提案/模板构建（独立可测模块）。

**范围与边界**：纯探测/构建逻辑；不涉及交互确认与文件写入（属 WP5b init）。

**前置**：WP1（config 结构）。

**交付物**：`vmr.py`。

**任务细项**：
1. 多端点容错探测（§4.2 顺序：`GET /healthz` 快速通道 → `GET /v1/models` 主证据+数据源 → `~/.vmr/` 已知配置 → 未命中；超时 ≤1s）。
2. `/v1/models` 解析：`id`、`vmr_protocol` → 提案数据结构。
3. 提案构建：VMR 命中 → `providers.vmr`（base_url=`http://127.0.0.1:8800/v1`、protocol 取 vmr_protocol、api_key=`${VMR_KEY:-}`）+ 各虚拟模型 + `profiles.daily{main="coding"}`（或首个模型）；未命中 → 注释示例模板 config。
4. 探测目标可经环境变量注入（测试用 fake VMR server）。

**测试计划**（`tests/unit/test_vmr.py`）：探测顺序各分支、超时、`/v1/models` 解析、提案构建（命中/未命中）、注入 fake server 全链路。

**验收标准**：
- [ ] 探测/提案单测全绿（fake VMR 注入，不依赖本机 8800）。
- [ ] 探测失败不抛异常（返回未命中信号）。

---

### WP5b CLI 命令面（规模 M）

**目标**：`init / use / status / rollback` 四条命令 + 全局旗标 + 退出码规范 + 输出/掩码/日志；`use` 的编排逻辑（resolve → per-agent plan → Safety 写通道 → last_write → 告警聚合）。

**范围与边界**：MVP 命令面完整实现；`--to-tx`/`--snapshot` 等后置参数**不注册**（typer 未知选项即拒绝，报错清晰）；`--verbose` 纳入。`use` 对具体适配器的集成验证在 WP6+ 落地（本包以 stub 适配器验收）。

**前置**：WP1–WP4、WP5a。

**交付物**：`cli.py`、`main.py`、`errors.py`、`output.py`、`masking.py`。

**任务细项**：
1. typer 应用与命令注册：`init [--dry-run] [--force]`、`use <profile> [--dry-run] [--force]`、`status [--verbose]`、`rollback [<agent>] [--dry-run] [--force]`；全局旗标 `--dry-run` `--force` `--no-color` `--show-secrets`。`--force` 通用语义 = 跳过安全确认，per-command 含义文档化：`use --force` = 覆盖漂移阻断；`rollback --force` = 确认恢复动作（含归档）；`init --force` = 跳过提示重新生成。
2. 退出码规范（SPEC §10.2 / PRINCIPLE §4.3.3）：0 成功/no-op；1 配置错误（语法/schema/ENV 未解析、config 未初始化）；2 安全阻断（漂移/写锁/白名单）；3 I/O 与权限；4 未找到（Agent/profile/snapshot）；130 SIGINT（typer 捕获 + 统一处理）。流约定：正常结果 stdout，错误/警告/日志 stderr。**usage-error 拦截→exit 1（见 A5）**。
3. `init`：
   - Agent 扫描（遍历注册表 detect，失败跳过并汇总）；
   - 调 WP5a 获取探测结果与提案（VMR 命中 → 完整生成；未命中 → 注释示例模板）；
   - rich 展示提案（含将写入的 providers/models/profile；api_key 显示 `${VAR}` 引用本身，无明文）；
   - 交互确认（typer confirm；`--force` 跳过；config 已存在 → 覆盖/取消，默认取消；增量合并见 A3）；
   - 写入：config.toml（tomlkit 生成，含清晰注释）+ `state/` 目录（0700）+ `~/.acm/.gitignore`（排除 state/ logs/ .lock）；
   - `--dry-run`：只展示提案零写盘。
4. `use <profile>`：
   - config.toml 缺失 → "未初始化：请先 `acm init`" → exit 1（A10）；校验 profile 存在（否则 exit 4）；
   - **Desired State 一律来自命令行 `<profile>` 参数**（含 `--dry-run`）：`compute_state`/`plan` 均以命令行 profile 为期望源，不读 `active`；
   - resolve（ENV 缺失 → 硬失败 exit 1，零写盘）；
   - **写 active**（激活态仅 use 可写；active 由首次 use 创建而非 init；**active 更新独立于投影 ops**——换 profile 后即使模型相同、投影为 no-op，active 也照常更新；**仅非 dry-run 且成功路径写入**，dry-run 不写 active）；
   - 遍历已检测 Agent：
     - 每 Agent：compute_state → 漂移 → 默认阻断 exit 2（标准文案 §10.3）+ 建议 `--force`；`--force` 显式覆盖；
     - plan 编译 → ops 空（幂等）→ no-op 跳过 → Safety 写通道 → 收集投影告警；
     - 批处理独立收敛：单 Agent 失败不中断其余，stderr 指名失败 Agent，最终退出码 = 最高严重度；
   - **部分投影失败属正常**：active=新、成功 Agent=SYNCED、被阻断 Agent=OUT_OF_SYNC（current==last_write≠Desired），status 如实展示，重跑 `use` 收敛即可（不属异常）；
   - 投影告警聚合展示（stderr 单行 + status 汇总源）。
   - `--dry-run`：计算 + 展示（含预期变更与告警），**不写 active/快照/last_write**，零写盘。
5. `status [--verbose]`：表格展示各 Agent 六态 + 当前 profile + 漂移摘要 + 投影告警汇总；`--verbose` 扩展（受管字段明细，掩码）。
6. `rollback [<agent>] [--force]`：MVP 语义 = 整文件恢复（等价终局整文件恢复语义）；**恢复目标 = 更新前 `last_write.backup_id` 指向的快照**（非"最新"；恢复前快照（A12）写入新 backup_id 后即成为下次 rollback 目标，仅当次排除，不引入持久标记）；缺省恢复全部有状态的 Agent；无快照 → exit 4；涉及"ACM 全新建文件"（恢复 = **归档** rename 为 `<file>.acm_orphaned.<ts>` 而非删除，见 A11；归档文件永久留存、用户按需手动清理）时要求 `--force` 显式确认；**恢复成功后按唯一算法更新 last_write**：`profile` 保持原名（禁用 `restored` 哨兵——否则 `compute_desired("restored")` 会 exit 4 且 status 脏）；`fields` = 恢复后的值（写前 NOT_EXIST 归档场景 → 记 `NOT_EXIST` 哨兵，非归档文件内容）；`backup_id` = 更新为恢复前置快照 ID（该快照成为下一次 rollback 目标，undo-undo）——杜绝"恢复后立即 DRIFTED 死循环"；`--dry-run`：展示将恢复的快照、归档动作与影响文件，零写盘。
7. `masking.py`：敏感路径 token 规则（api_key/token/auth/secret/key）；掩码 = 首尾各 3 位；`--show-secrets` 全局 opt-in。
8. `output.py`：rich 渲染；`--no-color` 与 `NO_COLOR` 环境变量；日志（stdlib logging → `~/.acm/logs/acm.log`，目录 0700；默认 INFO 摘要，`--verbose` DEBUG；错误/警告走 stderr）。
9. `errors.py`：异常层级（ConfigError→1、SafetyBlockedError→2、IOFailure→3、NotFoundError→4、UserAbort→130）与 typer 退出码映射。
10. `--dry-run` 行为规范：`init --dry-run` = 只展示提案零写盘；`use --dry-run` = 计算 + 展示（含漂移判定与告警），**不写 active/快照/last_write**；`rollback --dry-run` = 展示将恢复的快照/归档动作/影响文件，零写盘；`status` 天然只读，**不接受 `--dry-run`**。
11. `use` / `rollback` 的 `--help` 文案注明崩溃一致性窗口："极端情况下（写入完成与状态记录之间崩溃）配置可能已更新但状态未记录，属保护机制正常表现，`acm use <profile> --force` 可重新对齐"（与 §8 风险表同步）。

**测试计划**（`tests/integration/test_cli_init.py`、`test_cli_use.py`、`test_cli_status.py`、`test_cli_rollback.py`；typer CliRunner + 隔离 HOME）：
- init：全新 HOME → 提案展示（VMR 命中/未命中两分支，用 fake VMR HTTP 或探测注入）→ 确认 → config.toml/.gitignore/state 生成正确（0700 断言）；已存在 config → 默认取消（文件零变更）；`--force` 覆盖；`--dry-run` 零写盘；VMR 未命中 → 模板 config 生成。
- use：stub 适配器全链路（幂等 no-op exit 0 无快照 / 正常投影 / 漂移阻断 exit 2 + expected/found + `--force` 收敛 / ENV 缺失 exit 1 零写盘 / 未知 profile exit 4 / 未 init exit 1）；批处理：一 Agent 阻断另一 Agent 成功 → 成功者生效 + 退出码非零 + stderr 指名 + status 对失败者显示 OUT_OF_SYNC。
- status：六态各场景展示（与 WP4 单测同构的 CLI 面）。
- rollback：有快照恢复字节一致（写前后 sha256，恢复目标 = backup_id 快照）；无快照 exit 4；`--force` 归档场景（创建文件 → 归档 + 文案）；恢复后 last_write 更新（status 不再 DRIFTED）。
- 退出码矩阵：全命令 × 各错误类别映射断言。
- 掩码：status/rollback/dry-run 输出含敏感字段 → 掩码断言；`--show-secrets` 明文断言。
- SIGINT：Ctrl-C 模拟 → exit 130。

**验收标准**：
- [ ] 四条命令 + 全局旗标行为符合 SPEC §10/§12（MVP 子集），退出码矩阵测试全绿。
- [ ] `--dry-run` 全路径零写盘（含不建快照、不写 last_write、不建 state 目录）。
- [ ] init 在隔离 HOME 端到端生成可用 config.toml；重复执行默认不破坏现有配置。
- [ ] use 编排逻辑以 stub 适配器全绿（幂等/漂移/批处理/告警聚合）。
- [ ] 文案与 SPEC §10.3 标准模板一致（漂移/锁/投影损失）。

---

### WP6 Claude Code 适配器（规模 M）

**目标**：首个真实适配器，验证"JSON + env 块注入 + 高密度非管字段保护"架构能力（SPEC D6）。

**范围与边界**：只写 `~/.claude/settings.json`；**绝不碰 `~/.claude.json`**（白名单封闭）。仅当前稳定版单一路线（SPEC 上游演进原则）。

**前置**：WP2–WP5b。

**交付物**：`adapters/claude_code.py`；金样 `tests/fixtures/claude_code/`；金样测试 `tests/golden/test_adapters_claude.py`；CLI 集成测试 `tests/integration/test_cli_claude.py`。

**任务细项（映射表与转换）**：
1. `detect`：`claude` 可执行或 `~/.claude/` 目录存在（**主判据**）；`settings.json` 存在时优先接管；不存在 → 标记"可接管（将创建）"，`use` 时创建（与 Pi 同一机制）。
2. `config_paths`：仅 settings.json（路径经 Helper）。
3. 映射表（命名空间：`model`、`env.*`、`reasoning` 相关键）：
   - `profile.main.model_id` → `model`；
   - provider `base_url` → `env.ANTHROPIC_BASE_URL`；
   - provider `api_key`（解析后明文值）→ `env.ANTHROPIC_AUTH_TOKEN`（或 `ANTHROPIC_API_KEY`，金样校准二选一并记录）；
   - `reasoning.effort` → 目标文件实际存在的 effort 表达键（本机实证存在 `effortLevel` 类键，具体键名与取值映射（low/medium/high → Claude 表达）实现时以金样校准，写死在映射表并留注释）。
4. 投影损失（`ProjectionWarning`）：`reasoning.budget_tokens`（无法表达）；`context_window`/`max_output_tokens`/`temperature`/`capabilities.*` 若无法映射 → 告警（校准后决定哪些可表达）。
5. env 块处理：`env` 对象整体由 ACM 拥有的键（`ANTHROPIC_BASE_URL`、`ANTHROPIC_AUTH_TOKEN` 等）可写；env 内其他键（用户自有）不得触碰；`env` 块不存在 → 创建。
6. 值转换要点：api_key 经 resolve 得明文后由 Safety 通道写入（落盘为明文，state 0700 兜底；展示掩码）。

**测试计划（金样 a/b/c，SPEC §11.1）**：
- fixture：真实 `~/.claude/settings.json` 脱敏样本（保留 permissions/hooks/enabledPlugins 等非管键与注释性结构）。
- a. Apply：受管字段精确等于 Desired（语义断言）。
- b. Non-destructive：未管键语义级不变（tree_diff 断言）+ 词法（键序/缩进/末尾换行）按 fixture 界定断言。
- c. Rollback：恢复写前整文件（字节级 sha256 相等）。
- 负面：op 触碰 `~/.claude.json` 或 env 外路径 → 拦截 exit 2 且文件零变更。
- 投影告警：budget_tokens 等 → 告警产生与文案断言。
- CLI 集成：use daily 对 fixture HOME 的 settings.json 投影 → status 显示 SYNCED → 外部篡改 model → status DRIFTED → use 阻断 → `--force` 收敛。

**验收标准**：
- [ ] 金样 a/b/c 全绿；负面拦截用例全绿。
- [ ] 本机真实 settings.json（先备份）use 一次成功，其余键与排版不变（人工确认步骤，不入测试）。
- [ ] 投影告警在 use/status 中正确聚合展示。

---

### WP7 Codex 适配器（规模 M）

**目标**：TOML round-trip + "新建 TOML `model_providers` 表"形状（SPEC Slice 1 第二种形状）；**默认 env_key 单文件方案**（本机实证 `~/.codex/auth.json` 为 Codex 运行态 OAuth 文件，含 tokens、`OPENAI_API_KEY` 为 null——不列入受管范围）。

**范围与边界**：默认只写 `~/.codex/config.toml`；`mcp_servers`（本机实证注释密集）等非管内容零破坏。auth.json 为**备选**（仅当本机实证 env_key 单文件不可行时启用，届时明确标注"凭证落盘"）。

**前置**：WP2–WP5b。

**交付物**：`adapters/codex.py`；金样 `tests/fixtures/codex/`（config.toml 注释密集 MCP 表，脱敏）；`tests/golden/test_adapters_codex.py`；`tests/integration/test_cli_codex.py`。

**任务细项**：
1. `detect`：`codex` 可执行或 `~/.codex/` 目录存在（**主判据**）；`config.toml` 存在时优先接管；不存在 → 标记"可接管（将创建）"。
2. `config_paths`：**默认仅 config.toml**（env_key 单文件）；auth.json 列为 D2 备选（仅启用时加入，提交顺序 auth.json 在前、config.toml 在后）。
3. 映射表：
   - `profile.main.model_id` → 顶层 `model`；
   - `reasoning.effort` → 顶层 `model_reasoning_effort`（SPEC 适配矩阵 ✔，具体取值映射金样校准）；
   - provider → `model_providers.<id>` 表：`base_url`、`wire_api`（protocol 方言映射）、**`env_key` = 环境变量名（如 `VMR_KEY`），Codex 运行时自读环境变量，ACM 不落盘明文 key**。
4. **实证门**：本机验证 env_key 单文件可跑通（VMR 无鉴权 / 有鉴权两态）→ 正式确定；不可行 → 启用 auth.json 双文件备选（标注凭证落盘）。**实证标准**：Codex 能以该 provider 成功发起一次请求 / 该 `model_providers.<id>` 配置被 Codex 正常识别（不报未知 schema）。
5. 投影损失：无法表达的字段 → 告警。
6. 白名单命名空间：`model`、`model_reasoning_effort`、`model_providers.*`。

**测试计划（金样 a/b/c；双文件故障测试仅当启用 auth.json 备选时纳入）**：
- fixture：真实 config.toml 脱敏（保留 `mcp_servers` 大量带注释条目、`features`/`sandbox` 等非管表）。
- a. Apply：顶层 model / model_reasoning_effort / model_providers.<id> 表（base_url/wire_api/env_key）正确。
- b. Non-destructive：mcp_servers 全部注释与条目语义保留（tree_diff）+ 词法按 fixture 界定断言。
- c. Rollback：恢复写前字节（目标 = backup_id 快照）。
- 负面：op 触碰 config.toml 外路径（如 auth.json 未启用时）→ 拦截 exit 2 文件零变更；中途失败注入 → 未替换文件零变更、temp 无残留、`rollback` 可恢复。
- 幂等：重复 use → no-op 无新快照。
- CLI 集成：use daily → status SYNCED；外部改 `model` → DRIFTED → 阻断 → `--force`。

**验收标准**：
- [ ] 金样 a/b/c 全绿；mcp_servers 注释保留断言全绿。
- [ ] 实证结果记录（env_key 单文件可跑通性）并同步 SPEC §8。
- [ ] 本机真实 config.toml（先备份）use 一次成功，注释与非管表不变（人工确认）。

---

### WP8 Pi 适配器（Slice 2，规模 M）

**目标**：注册式投影形态 + **全新建文件场景**（本机实证 `models.json` 不存在），补齐 P0 三件套。

**范围与边界**：只写 `~/.pi/agent/models.json`（不存在则创建）与 `~/.pi/agent/settings.json`；**绝不碰 `models-store.json`**（白名单封闭）；`trust.json`/`auth.json`/extensions/skills 零触碰。

**前置**：WP2–WP5b。

**交付物**：`adapters/pi.py`；金样 `tests/fixtures/pi/`；`tests/golden/test_adapters_pi.py`；`tests/integration/test_cli_pi.py`。

**任务细项（映射表与转换）**：
1. `detect`：`pi` 可执行或 `~/.pi/agent/` 目录存在（**主判据**）。
2. `config_paths`：models.json + settings.json；models.json 不存在 → 标记"ACM 将创建"（`created` 语义）。
3. 映射表（注册式：消费完整 models 定义）：
   - provider → `providers.<name>`：`baseUrl`、api 方言（`openai-completions` / `anthropic-messages`，由 protocol 映射）、`apiKey`（解析明文；Pi 无 env_key 等价物，apiKey 为 Agent 侧投影明文——与 Claude env 块同构、不违反 PRINCIPLE §3.2，state 0700 兜底、展示掩码）、`models[]` 数组项：`id`、`contextWindow`、`maxTokens`、`compat`、`thinkingLevelMap`（能力位/推理等级映射，金样校准）；
   - settings.json：`defaultProvider`、`defaultModel`、`defaultThinkingLevel`；
   - 推理：`reasoning.effort` → `thinkingLevelMap` 与 `defaultThinkingLevel` 的换算（Spec 适配矩阵 ✔ 同构度最高）。
4. 全新建文件流程：models.json 由 ACM 首次创建（`created_by_acm` 语义）→ last_write 记录创建事实 → rollback 恢复 = **归档**该文件（rename 为 `models.json.acm_orphaned.<ts>`，要求 `--force` 确认；见 A11：归档而非删除）。
5. 投影损失：无法表达字段 → 告警。

**测试计划（金样 a/b/c + 新建场景）**：
- fixture：settings.json 真实脱敏（153B 样本）；models.json 用"预置样例"与"不存在"两种输入态。
- a. Apply：不存在 → 创建且结构正确；存在 → 精确更新；settings.json 三默认字段正确；其余键（如自定义键）不变。
- b. Non-destructive：settings.json 非管字段零破坏；models-store.json 从未被读写（单测断言路径不在 config_paths）。
- c. Rollback：创建场景 → 文件**归档**（`.acm_orphaned.<ts>` 不再在位，`--force` 确认）；更新场景 → 字节恢复（目标 = backup_id 快照）。
- 负面：op 指向 models-store.json → 拦截 exit 2 文件零变更。
- CLI 集成：use daily → status SYNCED；外部删 models.json → DRIFTED → 阻断。

**验收标准**：
- [ ] 金样 a/b/c 全绿（含全新建文件与归档回滚）。
- [ ] `models-store.json` 不可达性由白名单封闭保证并有单测背书。
- [ ] 真实环境（先备份 settings.json；models.json 本就不存在）验证一次（人工确认）。

---

### WP9 端到端验收与发布（MVP 收尾，规模 M）

**目标**：Slice 1 内部 pip -e/uvx 跑通 → Pi 齐 → **PyPI 发布** → 硬性验收 8/8。

**范围与边界**：打包/发布/文档；不做 Phase 2 任何功能。PyPI 名称可用性若冲突（见风险 R9）需先决策。

**前置**：WP0–WP8。

**交付物**：README 全面更新（快速上手 ≤3 条命令、命令表、FAQ、风险提示"同一 Agent 只用一种配置管理工具"、文档链接修正）、`tests/integration/test_e2e_acceptance.py`（8 条硬性验收脚本化）、发布检查单。

**任务细项**：
1. README 重写/更新：安装（uvx/uv tool/pipx）、MVP 命令示例（init → use daily → status）、非破坏性承诺与免责、VMR 协同说明、退出路径说明（卸载即可，建议删除 `~/.acm/`）。
2. 打包验证：`uv build`；隔离环境 `uvx --from agent-config-manager acm --version`、`uv tool install agent-config-manager`、`pipx install agent-config-manager`（如本机可用）逐一验证。
3. 硬性验收 8 条脚本化（对应 §7 逐条），在隔离 HOME 全量执行。
4. 发布：查名（PyPI 索引）确认可用 → `uv build` → `uv publish`（或等效流程）；发布后 `uvx --from agent-config-manager acm` 从公网拉取冒烟。
5. 发布前对照"非成功样貌"自检（SPEC §14）：无 GUI/MCP/网关/私有 DB/数量 KPI/状态入库。

**测试计划**：`test_e2e_acceptance.py` = §7 的 8 条验收映射为可执行脚本（隔离 HOME + fake VMR 或真实 VMR）。

**验收标准**：
- [ ] 硬性验收 8/8 全绿（§7 表格逐条）。
- [ ] `uvx --from agent-config-manager acm` / `uv tool install agent-config-manager` / `pipx` 三通道安装冒烟通过。
- [ ] 全新隔离 HOME 复现"≤3 条命令、零手改 Agent 配置文件"成功路径（VMR 场景）。
- [ ] README 无失效链接、命令面与 MVP 一致。

---

## 6. 测试与质量策略

### 6.1 测试层级

| 层级 | 位置 | 覆盖 | 命令 |
|---|---|---|---|
| 单元测试 | `tests/unit/` | config/resolve/lock/status/masking/writers 等纯逻辑 | `uv run pytest tests/unit` |
| Writer round-trip 金样 | `tests/unit/` + `tests/fixtures/writers/` | JSON/TOML 词法保真（先于适配器交付） | 同上 |
| 适配器金样 a/b/c | `tests/golden/` | 每适配器 Apply/Non-destructive/Rollback 三步断言 | `uv run pytest tests/golden` |
| 故障注入 | `tests/fault/` | SIGKILL/锁竞争/指纹不匹配/白名单拦截/中途失败/权限 | `uv run pytest tests/fault` |
| CLI 集成 | `tests/integration/` | 命令面/退出码/掩码/批处理/文案 | `uv run pytest tests/integration` |
| 端到端验收 | `tests/integration/test_e2e_acceptance.py` | 硬性验收 8 条 | `uv run pytest -m e2e` |
| 静态/类型 | — | ruff / mypy strict | `uv run ruff check .` / `uv run mypy src` |
| 依赖锁定 | — | lock 漂移 | `uv lock --check` |

### 6.2 金样 fixture 规范（详见附录 A）

- 来源：本机真实文件**脱敏**（结构/注释/键序/排版怪癖保留，密钥替换为占位）。
- 命名与目录：`tests/fixtures/<agent>/`，每适配器独立目录（漂移不跨 Agent 传染）。
- 断言分三层：语义（tree_diff）/ 词法（fixture 界定）/ 字节（rollback 与快照）。
- 同时充当**上游 schema 漂移哨兵**：Agent 升级后 CI 全量回归即暴露布局变化。

### 6.3 编码规范（MVP 硬约束）

- mypy strict 全绿（`warn_return_any` 已开，禁止 Any 泄漏）；公开函数必须有 docstring（仅公开 API，内部函数可免；不构成 WP0 验收阻塞）。
- ruff line-length 100；禁止第三方依赖超出 §2.2 清单。
- 模块边界铁律：适配器无 I/O、写通道唯一、config 与状态分离——由单测 + review 双重强制。

### 6.4 CI（建议，可后置）

GitHub Actions：`uv setup` → `uv sync` → ruff → mypy → `pytest tests/unit tests/golden tests/fault tests/integration -m 'not e2e'`（e2e 标记默认排除，验收套件在单独 job 执行）→ `uv lock --check`。启用与否见待拍板 A9。

---

## 7. 端到端验收

> 映射 SPEC §12 硬性 MVP 验收 8 条 → 可执行验证方式。全部在**隔离 HOME** 执行（真实环境仅最后人工确认）。

| # | 硬性验收（SPEC） | 验证方式 | 通过判据 |
|---|---|---|---|
| 1 | 全新机器 VMR 场景 ≤3 条命令指向 3 个 P0 Agent | e2e 脚本：fake/真实 VMR → `init`（交互确认）→ `use daily` → `status` | 3 个 Agent 全部 `SYNCED`；全程命令数 ≤3、零手改 Agent 配置 |
| 2 | 非破坏性：10 次 use/rollback 循环后未管键（JSON）/ 未管键+注释（TOML）不变 | 循环脚本 + tree_diff（语义级）+ fixture 界定词法断言 | 10/10 循环后非管内容与初始一致（语义级硬承诺；词法按 fixture 界定） |
| 3 | 可逆性：任意写入后 rollback 回到写前字节（**恢复目标由 `last_write.backup_id` 确定**，非字典序最大） | 写后 sha256 vs 恢复后 sha256 | 逐文件字节相等；创建文件场景：文件被归档（不再在位），归档文件字节 == 写前 |
| 4 | 可靠性：SIGKILL 无写一半文件；双进程抢锁一方 exit 2 | 故障注入套件 | 无中间损坏态；残留 temp 清理；锁竞争方 exit 2 |
| 5 | 幂等：连续两次 use 第二次 no-op 且无新快照 | 快照目录计数 | 第二次 exit 0 且快照数不变 |
| 6 | 防护：白名单外路径拦截文件零变更；ENV 缺失零写盘 | 负面用例 | 均 exit 2/1 且字节零变更 |
| 7 | 漂移：外部修改受管字段 → 阻断给出 expected/found；`--force` 后才收敛 | 篡改脚本 | 阻断文案含具体值；force 后 SYNCED |
| 8 | 退出路径：卸载 ACM 并删除 `~/.acm/` 后配置保持可用 | 文档路径验证（人工 + 脚本检查文件在位） | 各 Agent 配置保持最后投影状态 |

---

## 8. 风险与对策（MVP 特定）

| 风险 | 概率 | 影响 | 对策 |
|---|---|---|---|
| 真实环境验证污染用户配置 | 高（若直接对真实文件测试） | 高 | 一律隔离 HOME；真实验证必须"先备份后执行"；测试卫生铁律（§4.3） |
| Codex 多文件事务（备选双文件）中途失败 | 低 | 中 | 若启用：提交顺序（auth.json 先）+ 漂移阻断 + `rollback` 兜底（§4.2） |
| 多 Agent 批量投影部分失败 | 低 | 低 | 属正常：active=新、成功者 SYNCED、被阻断者 OUT_OF_SYNC，重跑 `use` 收敛（文档告知，不属异常） |
| 提交间隙极端崩溃（os.replace 后、last_write 前 SIGKILL） | 低 | 低 | 属保护机制正常表现：配置可能已更新但状态未记录；`use <profile> --force` 重新对齐（文档告知，不需 WAL） |
| VMR 端点漂移（本机 healthz 404 实证） | 高 | 中 | 多端点容错探测顺序；`/v1/models` 为主证据（A2：Spec §9 已同步） |
| 上游 Agent schema 漂移 | 高频 | 小 | 金样哨兵 + ERROR 态安全阻断 + AI 辅助改适配器 |
| 快照明文密钥泄露 | 低 | 中 | state 0700/0600 + 展示掩码 + README 卸载建议删除 `~/.acm/` |
| PyPI 包名冲突 | 中 | 中 | WP9 发布前先查名；必要时 `acm-cli` 备用名（A13） |
| 单人维护漂移 | 中 | 高 | 治理规格分层 + 本 Action Plan 任务包验收即质量门 + scope 严格控制 |
| Pi 全新建文件被误删（rollback） | 低 | 中 | 恢复"ACM 全新建文件"改为**归档 rename**（`.acm_orphaned.<ts>`，非删除）+ `--force` 显式确认（A11：归档） |

---

## 9. 重要设计决策与待拍板项

> 本节给出 MVP 的关键设计决策（含决策逻辑）与少数仍待拍板的开放项。均为最终结论，不保留修订历史。

### 9.1 已定设计决策

| 编号 | 决策点 | 最终决策 | 决策逻辑 |
|---|---|---|---|
| A1 | pydantic 依赖 | **保留 pydantic**（计入依赖预算：typer+rich、tomlkit、pydantic） | Core Config 三层嵌套 + capabilities/reasoning 子表 + credential 语法校验的规则将超 200 行且开始组合；uv.lock 已锁定，零增量成本 |
| A2 | VMR 探测端点 | `healthz`（快速通道）→ `/v1/models`（主证据 + 数据源）→ `~/.vmr/` 已知配置 → 未命中；已同步 Spec §9 | 本机实测 healthz 404 而 /v1/models 200 |
| A4 | `--verbose` | 纳入 MVP | 日志基建反正要建；排障必需 |
| A5 | usage-error 退出码 | 拦截 → exit 1（保留 2 专用于安全阻断） | typer 默认 2 与"2=安全阻断"冲突，脚本化需区分 |
| A6 | rollback 旗标面 | 仅 `[<agent>] [--force]`；不注册 `--hard/--to-tx/--snapshot` | MVP 整文件恢复即 hard 语义；避免"注册但报未实现"的伪接口 |
| A10 | 未 init 即 use/status | config.toml 缺失 → "请先 `acm init`" → exit 1（use/status 一致）；active 由首次 use 创建 | init 不创建 active，active 在首次 use 前本就不存在，不能作守卫判据 |
| A11 | rollback 恢复"ACM 全新建文件" | **归档 rename**（`<file>.acm_orphaned.<ts>`）而非删除，`--force` 确认；归档文件永久留存、用户按需手动清理 | 避免不可逆丢失用户/Agent 新增内容（公理 2）；与快照 Append-only 哲学一致 |
| A12 | rollback 前快照 | 留档（写入新 backup_id 后成为下次 rollback 目标，undo-undo），仅当次恢复排除 | 保证误恢复可自愈；恢复目标 = 更新前 `last_write.backup_id`；不引入持久排除标记 |
| A13 | PyPI 包名 | 发布前查名；冲突用 `acm-cli` fallback | `acm` 为通用缩写，极可能被占用 |
| A14 | 测试 VMR 注入 | conftest 提供 fake VMR server（探测目标 env 注入） | e2e 不能依赖本机 8800 常驻 |
| A15 | Windows 支持 | **MVP 仅 macOS/Linux**，无 Win 分支 | 避免未验证代码；Win 属终局语义，MVP 不承担 |
| A16 | detect 主判据 | **"可执行文件或配置目录存在"**（配置存在时优先接管；缺失则标记"可接管（将创建）"，use 时创建） | 提升装好未运行过的全新机器开箱路径；与 Pi 全新建文件机制统一；与 SPEC §7.4 一致 |

### 9.2 仍待拍板项

| 编号 | 开放项 | 默认建议 | 待拍板 |
|---|---|---|---|
| A3 | init 重复执行的"增量合并"选项 | 仅 覆盖 / 取消（默认取消）；增量合并随 `import vmr` 触发引入 | □ 认可 □ MVP 即支持增量合并 |
| A7 | 掩码规则覆盖范围 | 统一敏感 token 规则（status 明细 / dry-run 展示 / expected-found）；静态文件靠 0700 | □ 认可 □ 需 keychain 级保护（不属 MVP） |
| A8 | README 失效文档链接 | WP0 修正指向 v2.1 两份，或标注"已归档" | □ 修正 □ 保留历史引用 |
| A9 | CI 启用时机 | 本地质量门脚本优先，CI 随代码入库启用 | □ 本地优先 □ 立即上 CI |

---

## 附录 A：金样 fixture 规范

1. **来源与脱敏**：取自本机真实文件（settings.json / config.toml / auth.json@codex（D2 备选，仅启用双文件时入库）/ settings.json@pi），将全部密钥/令牌替换为确定性占位（如 `sk-xxxxxxxxxxxxxxxx`、`"PLACEHOLDER_TOKEN"`），**保留**：结构、注释、键序、空行、缩进风格、格式怪癖（如 Codex 注释密集的 `mcp_servers` 表）。
2. **目录与命名**：`tests/fixtures/<agent>/`（每适配器独立，漂移不跨 Agent 传染）；文件命名如 `settings.golden.json`、`config.golden.toml`、`models.golden.json`（`auth.golden.json` 仅 D2 备选启用时纳入）；writers 词法金样放 `tests/fixtures/writers/`。
3. **断言分层**：
   - 语义：解析树 diff（tree_diff）断言未管节点结构与值不变（硬承诺）。
   - 词法：注释/键序/空白按格式能力表（JSON 键序+缩进+末尾换行；TOML 注释+键序+空行）断言（fixture 界定承诺）。
   - 字节：rollback 后与写前 sha256 一致；快照与写前字节一致。
4. **哨兵职责**：fixture 同时充当上游 schema 漂移检测哨兵——Agent 升级后 CI 全量回归即暴露布局变化。
5. **禁止**：任何真实密钥进入 fixture/测试产物；fixture 不得依赖本机真实 HOME。

## 附录 B：MVP 相关术语速查

| 术语 | 定义（MVP 语境） |
|---|---|
| Core Config | `~/.acm/config.toml`：providers/models/profiles 三层声明式 SSOT（仅声明内容，状态不入此文件） |
| ResolvedProfile | Profile 经 ENV 引用实时求值后的具体值集合 |
| Desired State | 激活 Profile 经适配器 plan 编译后的字段级期望状态 |
| Current State | Agent 配置中受管字段的实际落盘值 |
| ChangeSet（MVP 简化） | 适配器产出的 `PlannedOp` 列表 + `ProjectionWarning` 列表（无独立子系统命名）；Safety 依磁盘扩展为 `FieldOp` |
| last_write | `state/<agent>/last_write.json`：最近一次投影记录（profile/时间/backup_id/受管字段值），MVP 漂移检测数据源 |
| Snapshot | 写前原样字节备份，`snapshots/<ts>/`，Append-only，灾难恢复与审计 |
| 归档 | ACM 全新建的 Agent 文件在 rollback 时 rename 为 `<file>.acm_orphaned.<ts>`（而非删除），永久留存、按需手动清理 |
| 恢复前置快照 | rollback 前先快照一次，写入新 backup_id 后成为下一次 rollback 的目标（undo-undo），仅当次恢复被排除 |
| env_key 投影 | Codex `model_providers.<id>.env_key` 指向环境变量名，Codex 运行时自读环境变量，ACM 不落盘明文 key |
| Drift | Current ≠ ACM 最后写入值（外部修改）→ 默认阻断 |
| Projection Loss | Desired 中目标 Agent 无法表达的字段 → 显式告警 |
| 六态 | NOT_DETECTED / UNMANAGED / SYNCED / OUT_OF_SYNC / DRIFTED / ERROR |
| 唯一写通道 | safety.py 的六步流水线：白名单 → 快照(+补全 FieldOp) → 内存修改+非管断言 → 指纹 → 原子替换 → last_write |
