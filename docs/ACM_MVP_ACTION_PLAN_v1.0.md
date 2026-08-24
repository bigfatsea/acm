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
5. [任务包分解 WP0–WP9](#5-任务包分解)
6. [测试与质量策略](#6-测试与质量策略)
7. [端到端验收（MVP 硬性验收 8 条）](#7-端到端验收)
8. [风险与对策（MVP 特定）](#8-风险与对策)
9. [其他重要问题与待拍板决策](#9-其他重要问题与待拍板决策)
10. [本次规划自检记录](#10-本次规划自检记录)
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

**明确不在 MVP（触发式后置，不实现、不占位）**：`apply` / `diff` / `doctor` / `history` / `release` / 独立 `import vmr` / `bind` / Journal 与字段级回滚 / `rollback --to-tx` / `--snapshot` 参数 / 显式 protected_paths 黑名单 / 正式 Adapter Protocol 类层级 / YAML、JSONC Writer / `--json` 输出。

> 注：`rollback` 在 MVP 中**只交付整文件恢复**（等价于终局的 `--hard` 最新快照语义）。

### 1.2 任务包总览

| 包 | 名称 | 一句话目标 | 规模 | 前置依赖 | 核心验收要点 |
|---|---|---|---|---|---|
| **WP0** | 工程脚手架 | 包骨架、依赖基线、工具链、测试基建 | S | — | `uv run acm --version` 可跑；ruff/mypy/pytest 全绿；lock 无漂移 |
| **WP1** | Core Config 模型与解析 | config.toml 三层 schema、校验、ENV 引用、ResolvedProfile | M | WP0 | 正反例单测全绿；注释 round-trip 保留 |
| **WP2** | Format Writers | JSON 保序 + TOML round-trip + 解析树 diff 断言 | M | WP0 | round-trip 金样全绿（先于适配器交付） |
| **WP3** | Safety Engine 唯一写通道 | 五步流水线、快照、指纹、原子替换、写锁、last_write | L | WP1, WP2 | 故障注入全套负面测试全绿 |
| **WP4** | 状态判定与漂移 | 六态机、漂移检测、幂等、Desired State 计算骨架 | M | WP1, WP3 | 六态矩阵单测全绿 |
| **WP5** | CLI 命令面 | init/use/status/rollback + 全局旗标 + 退出码 + 输出掩码 | L | WP1–WP4 | CliRunner 集成测试全绿；退出码规范测试全绿 |
| **WP6** | Claude Code 适配器 | 映射表 + env 块注入 + 金样 a/b/c | M | WP2–WP5 | 金样三步断言全绿 + CLI 集成测试 |
| **WP7** | Codex 适配器 | 双文件事务（config.toml + auth.json）+ 注释密集夹具 | M | WP2–WP5 | 金样三步断言全绿 + 双文件中途失败注入 |
| **WP8** | Pi 适配器（Slice 2） | 注册式投影 + 全新建 models.json 场景 | M | WP2–WP5 | 金样三步断言全绿（含"文件不存在→创建"） |
| **WP9** | 端到端验收与发布 | Slice 1 内部跑通 → PyPI 发布 → 硬性验收 8/8 | M | WP0–WP8 | 8 条硬性验收全过；uvx/tool/pipx 安装验证 |

### 1.3 依赖图与推荐执行顺序

```
WP0 ──┬── WP1 ──┬── WP4 ──┬── WP5 ──┬── WP6 ──┬── WP7 ──┬── WP8 ──┐
      └── WP2 ──┴── WP3 ──┘         └─────────┴─────────┴─────────┴── WP9
```

推荐顺序：**WP0 → WP1 → WP2 → WP3 → WP4 → WP5 → WP6 → WP7 → WP8 → WP9**。
（WP5 的 `use` 编排逻辑先以 stub 适配器验收；`use` 的 CLI 集成测试随 WP6/7/8 逐适配器落地。WP5↔WP6 可并行或交错。）

**里程碑**：
- **M1（内核就绪）**：WP0–WP4 完成 → Safety Engine + Writers + Core Config 全部有单测背书。
- **M2（Slice 1 完成）**：WP5–WP7 完成 → 本机 `init → use daily` 让 Claude Code + Codex 指向同一套模型（≤3 条命令），内部 uvx/pip -e 跑通。
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
| Codex 配置 | `~/.codex/config.toml` 存在 | 双文件事务 + 注释密集 MCP 表夹具来源（脱敏） |
| Pi 配置 | `~/.pi/agent/settings.json`（153B）存在；`models-store.json`（365KB，内部注册表**绝不碰**）存在；**`models.json` 不存在** | Pi 全新建文件场景 = 真实场景（非假设） |
| VMR | `127.0.0.1:8800` 存活；`/healthz` **404**；`/v1/models` **200** 返回 `[{id:agent},{id:cheap},{id:coding}]` 且含 `vmr_protocol` 字段；`~/.vmr/` 仅有 image_cache/logs（无配置文件） | **Spec §9 探测顺序需调整**（见待拍板 A2）；探测实现必须多端点容错 |
| 项目 git | main 分支，working tree clean | 产出文档不 commit，留在工作区 |

### 2.2 依赖引入决策（对齐 SPEC D2 依赖预算）

**运行时依赖（锁定在 uv.lock，CI 检查漂移）**：

| 依赖 | 用途 | 预算归属 |
|---|---|---|
| `typer` + `rich` | CLI 框架 + 终端渲染 | 计 1 组 |
| `tomlkit` | Core Config 与 Codex config.toml 的 round-trip 编辑 | 硬依赖（Codex P0 零新增） |
| `ruamel.yaml` | MVP 阶段**不写** YAML；保留依赖以锁定 P1 Aider 前置能力（SPEC D6 要求 Helper 级金样单测前置锁定）——MVP 仅保留锁，不实现 YAML Writer | 预算内 |
| `pydantic` | 见**待拍板 A1**（现 pyproject 已硬依赖；Spec 定义为可选） | 待定 |

- **stdlib 承担，不引入新依赖**：JSON 保序编辑（json + object_pairs_hook）、文件锁（`fcntl`/`msvcrt`）、VMR 探测 HTTP（`urllib.request` + 超时）、指纹（`hashlib.sha256`）、原子写（`tempfile` + `os.replace`）。
- 明确**不引入**：requests、click（typer 自带）、commentjson/jstyleson（Spec 附录 B 已实证否决）、watchdog、psutil。
- 开发依赖（现有）：`pytest` + `pytest-cov`、`ruff`、`mypy`（strict）。CI 另加 `uv lock --check` 步骤。

### 2.3 pyproject.toml 基线调整清单（WP0 执行）

1. 依赖清单按 A1 拍板结果落定（含 pydantic 去留）。
2. 版本单一来源：`__version__ = "0.1.0"` 定义于 `acm/__init__.py`；pyproject 若支持 dynamic version 则读取之，否则保留 pyproject 静态版本、`__init__.py` 经 `importlib.metadata` 读取保持一致（实现时取最小改动，CLI `--version` 与包版本恒一致）。
3. 保留现有 ruff（line-length=100）/mypy（strict）/pytest（testpaths=tests）配置；补充 pytest 的 fixture 目录说明。
4. 入口 `acm = "acm:main"` 保持不变（main 由 WP5 实现）。
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
│   ├── main.py                   # main()：组装 typer 应用并执行（WP5）
│   ├── cli.py                    # typer 命令定义：init/use/status/rollback + 全局旗标（WP5）
│   ├── errors.py                 # 异常层级与退出码映射（1/2/3/4/130）（WP5）
│   ├── config.py                 # Core Config：加载/结构校验/schema 版本/TOML round-trip（WP1）
│   ├── resolve.py                # ENV 引用语法校验与实时求值、ResolvedProfile（WP1）
│   ├── state.py                  # state 目录管理：active 读写、last_write 读写、目录权限、启动清理（WP3/WP4）
│   ├── lock.py                   # 非阻塞全局写锁（fcntl/msvcrt 双实现）（WP3）
│   ├── safety.py                 # ★唯一写通道：五步流水线、快照留存、指纹、原子替换（WP3）
│   ├── status.py                 # 六态判定、漂移检测、幂等判断（WP4）
│   ├── projection.py             # Desired State 计算骨架（profile → per-agent 期望字段）（WP4）
│   ├── vmr.py                    # VMR 探测（多端点容错）与提案构建（WP5）
│   ├── output.py                 # rich 渲染、--no-color/NO_COLOR、stderr/stdout 流约定（WP5）
│   ├── masking.py                # 敏感字段掩码（首尾 3 位）、--show-secrets（WP5）
│   ├── util.py                   # 路径 Helper（env 覆盖→XDG→平台默认→探测）；测试 HOME 注入（WP1/WP3）
│   ├── writers/
│   │   ├── __init__.py           # Writer 能力声明契约（语义/注释/键序/空白四级保证）与注册（WP2）
│   │   ├── json_editor.py        # 保序 JSON 编辑（键序/缩进/末尾换行/非 ASCII 行为保持）（WP2）
│   │   ├── toml_editor.py        # tomlkit round-trip 编辑 + 点路径读写 + 新建表（WP2）
│   │   └── tree_diff.py          # 解析树 diff 断言（非管节点零篡改）（WP2）
│   └── adapters/
│       ├── __init__.py           # 注册表（确定性顺序 [claude_code, codex, pi]）、类型别名（FieldOp/Warning）（WP5/WP6）
│       ├── claude_code.py        # 映射表 + detect/config_paths/plan（WP6）
│       ├── codex.py              # 双文件事务 + model_providers 表（WP7）
│       └── pi.py                 # 注册式投影 + 全新建文件（WP8）
└── tests/
    ├── conftest.py               # 隔离 HOME fixture、金样配置工厂、路径注入（WP0）
    ├── fixtures/
    │   ├── configs/              # Core Config 金样（含非法样本）
    │   ├── claude_code/          # settings.json 金样（脱敏）
    │   ├── codex/                # config.toml + auth.json 金样（脱敏，注释密集）
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
   → adapter.plan()（纯函数：映射表 + 少量转换，产出 ops + warnings；不碰文件）
   → Safety Engine 唯一写通道：
       ① 白名单校验（file ∈ config_paths；path ∈ 命名空间）失败 → exit 2
       ② 写前整文件快照 → state/<agent>/snapshots/<ts>/（Append-only）
       ③ 内存修改 + 非管节点断言（Writer round-trip → 语法自检 → 解析树 diff 零篡改）
       ④ pre-commit 指纹校验（重读字节 sha256 == H0；不等 → 中止 exit 2，绝不覆盖）
       ⑤ os.replace 原子替换（跨文件按序提交；异常回退清理 temp）
       ⑥ 覆写 last_write.json（profile/时间/backup_id/受管字段值）
   → 输出：投影告警聚合（stderr）+ rich 汇总（stdout）
```

---

## 4. 核心设计要点

### 4.1 MVP 简化契约（对齐 SPEC §12 Slice 1"不做正式 Protocol 类层级"）

- **适配器模块接口**（模块级约定，非 Protocol 类）：每个适配器模块导出以下实体：
  - 常量：`AGENT_ID`（如 `"claude_code"`）、`DISPLAY_NAME`。
  - `detect(env) -> bool`：配置目录/文件存在为主判据（Agent 首次运行必建配置），可执行文件存在为辅。失败 → 该 Agent 跳过并汇总告警，不影响其他 Agent。
  - `config_paths(env) -> list[Path]`：声明本适配器管理的全部文件路径（= Safety Engine 快照/加锁/白名单的边界）；必须经 `util.py` 路径 Helper，禁止硬编码绝对路径。
  - `plan(profile, env) -> tuple[list[FieldOp], list[ProjectionWarning]]`：纯函数编译，产出数据 ops 与未映射告警。**无磁盘 I/O**。
- **最小数据结构**（放 `adapters/__init__.py`，MVP 不设独立 ChangeSet 子系统）：
  - `FieldOp(file, path, old, new, created)`：`path` 为点路径（如 `"env.ANTHROPIC_BASE_URL"`、`"model"`、`"model_providers.coding.base_url"`）；`old` 含"不存在"哨兵。
  - `ProjectionWarning(field, agent_id, reason)`：Desired State 中无法表达/需降级表达的字段，进入告警。
- **白名单**：`op.path` 必须命中该适配器映射表声明的命名空间前缀集合；`op.file` 必须在 `config_paths()` 返回集合内。MVP 不做显式黑名单（`protected_paths` 触发式后置）；"绝不碰 `~/.claude.json`/`models-store.json`"由白名单封闭性天然保证（这些文件根本不在 config_paths/命名空间内）。

### 4.2 关键算法与方案要点（编码蓝本，非源码）

| 主题 | 方案要点 |
|---|---|
| **JSON 保序 Writer** | 用 `json.loads(..., object_pairs_hook=OrderedDict)` 保序解析；缩进宽度从源文本嵌套行前导空白探测；末尾换行存在性探测；非 ASCII 行为探测（源含原样非 ASCII → dump 时 `ensure_ascii=False`）；写入 = 目标路径赋值后整体序列化，键序天然保持。词法保证按 SPEC §7.5.4 JSON 行（语义保证、键序保证、缩进/末尾换行保留） |
| **TOML round-trip** | tomlkit parse 为 Document；点路径 get/set；新建表用 tomlkit table API（Codex `model_providers.<id>`）；注释/键序免费保留。词法保证按 fixture 界定 |
| **解析树 diff（非管节点断言）** | 修改前后各解析一次，递归比较解析树，排除受管点路径对应节点；其余结构/值 100% 相同才通过。Safety 阶段 ③ 与金样断言共用此工具 |
| **指纹与快照** | 写前读原始字节，`sha256` 记 H0（文件不存在 → 哨兵 `NOT_EXIST`）；快照 = 原始字节原样拷贝至 `state/<agent>/snapshots/<ts>/`（文件名保持，避免路径碰撞时加序号）；`<ts>` = UTC epoch 纳秒固定宽度零填充（字典序 = 时间序，保证"最新快照"确定性）。Append-only，不做 FIFO 清理 |
| **原子写** | 同目录 temp 文件（后缀 `.acm_tmp`）→ `os.replace` 原子替换；启动时清理残留 `.acm_tmp`（静默内务）。多文件按声明顺序提交（见 Codex 双文件顺序） |
| **写锁** | `state/.lock` 上 `fcntl.flock(LOCK_EX|LOCK_NB)`（Windows 用 msvcrt 对应实现）；占用 → 立即报错 `⚠️ Another acm process is holding the write lock.`，exit 2，不排队 |
| **漂移检测** | 对每个受管字段：当前磁盘值（经 Writer 读取）vs `last_write.json` 存值（**存值非哈希**，PRINCIPLE §3.3）；不等 → DRIFTED → 写命令默认阻断，报 expected/found（展示走掩码），exit 2；`--force` 显式覆盖。**无自动修复路径** |
| **六态判定** | `NOT_DETECTED`（未安装）/ `UNMANAGED`（已安装未接管）/ `SYNCED`（Current==Desired 无漂移）/ `OUT_OF_SYNC`（Current==last_write≠Desired）/ `DRIFTED`（Current≠last_write）/ `ERROR`（不可读/语法损坏/权限异常）。优先级 `ERROR > DRIFTED > OUT_OF_SYNC > SYNCED`；`NOT_DETECTED`/`UNMANAGED` 由安装与接管状态先行判定。MVP 全量实现六态（SPEC §7.6） |
| **幂等** | Desired == Current 且无漂移 → ops 为空 → no-op，exit 0，**不产生新快照**（SPEC §7.5.8） |
| **ENV 引用** | 语法仅 `${VAR}` 与 `${VAR:-default}`，整字段替换（正则白名单校验，拒绝子串/嵌套/命令替换）；**投影时实时求值**；缺失且无默认 → 硬错误列表，任何写入发生前整体中止，exit 1 |
| **掩码** | 路径 token 命中敏感规则（api_key/token/auth/secret/key 类）→ 值只显示首尾各 3 位；`--show-secrets` 明文 opt-in。作用于 diff/status/init 提案/last_write 展示 |
| **双文件提交顺序（Codex）** | 先写 `auth.json`（key），后写 `config.toml`（引用 key 的 `env_key`）。失败影响最小化：先失败 → 仅多一个孤儿 key（无害）；后失败 → 文件已更新但 last_write 未记 → 下次被漂移检测阻断，`rollback --hard` 兜底（SPEC §7.5.6 已认可该窗口） |
| **VMR 探测** | 顺序容错：`GET /healthz`（快速通道）→ `GET /v1/models`（**主证据**，实测 200 且即数据源）→ 读取 `~/.vmr/` 已知配置（如存在）→ 全失败则未探测到。超时 ≤1s。命中 → 从模型列表（id + `vmr_protocol`）构建提案（providers.vmr + models.* + 默认 profile daily）。（Spec §9 表述差异见待拍板 A2） |
| **init 提案** | 扫描 Agent（detect）→ 探测 VMR → 构建提案：VMR 命中 → providers.vmr（base_url=`http://127.0.0.1:8800/v1`、protocol 取 vmr_protocol、api_key=`${VMR_KEY:-}`（生成时附注释：本地代理无鉴权可留空，需鉴权则设 VMR_KEY））+ 各虚拟模型 + `profiles.daily{main="coding"}`（或首个模型）；VMR 未命中 → 生成含注释示例的模板 config.toml（用户手编 SSOT 属合法路径，成功标准只约束"零手改 **Agent 配置文件**"）。rich 展示提案 → 交互确认 → 写入 config.toml + 创建 state 目录（0700）+ 生成 `~/.acm/.gitignore`。config 已存在 → 提示 覆盖/取消（默认取消，绝不静默破坏）；`--force` 跳过提示（增量合并范围见待拍板 A3） |
| **批处理原则** | `use`/`status` 遍历注册表固定顺序，按 Agent 独立运算收敛；单 Agent 阻断/失败不中断其余；stderr 明确指出失败 Agent；最终退出码 = 全部 Agent 的最高严重度（PRINCIPLE §4.3.6） |
| **崩溃安全** | 写前快照 + 原子替换消除中间损坏态；无重量级 WAL 状态机（SPEC §7.5.6）；提交间隙 SIGKILL 的最坏后果 = 部分文件已更新/未记 last_write → 漂移阻断 → `rollback --hard` 复原 |
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

**范围与边界**：只读解析 + 校验 + 求值；**不写盘**（写盘仅 init，见 WP5）。不支持迁移命令（`version` 未知即明确报错）。

**前置**：WP0。

**交付物**：`config.py`、`resolve.py`、`util.py`（路径 Helper 部分）。

**任务细项（关键函数与算法）**：
1. `load_config(path) -> CoreConfig`：tomlkit 解析 → 结构校验 → `version == 1` 校验（未知版本 → 明确报错 exit 1，文案含"由 acm doctor / 手改 version 处理"指引——doctor 本身后置，仅给指引文案）。
2. 结构校验规则（校验失败 → exit 1，错误信息尽量定位到表/键）：
   - `providers.*`：`protocol ∈ {openai, anthropic, openai-responses}` 必填；`base_url` 必填（URI 形状校验）；`api_key` 必填（允许 `${VAR}` 引用或明文；明文合法但 doctor 后置期仅在 use 输出提示一次——MVP 简化为 init 生成时提示一次）；`headers`/`proxy` 可选（字典/URI）。
   - `models.*`：`provider` 必须引用存在的 provider；`id` 非空；`context_window`/`max_output_tokens` 正整数；`temperature` 数值；`capabilities` 枚举校验（`vision: bool`、`tools ∈ {native,xml,markdown}`、`json_mode: bool`）；`reasoning.effort ∈ {low,medium,high}`、`reasoning.budget_tokens` 正整数（可选）。
   - `profiles.*`：`main` 必填且引用存在的 model；其余角色槽位（`cheap` 等）可选且须引用存在 model；Profile 至少一个。
3. ENV 引用语法校验（`resolve.py`）：整字段匹配 `${VAR}` / `${VAR:-default}` 白名单正则；拒绝子串插值/嵌套/命令替换 → schema 错误。
4. `resolve(profile, env) -> ResolvedProfile`：投影时实时求值（不在加载时固化）；收集全部未解析引用（缺失且无默认）→ 返回硬错误列表（调用方在**任何写入前**中止，exit 1）。
5. round-trip 保留：`config.toml` 的读取/回写（MVP 中仅 init 覆盖生成与未来 import 用）必须保留用户注释与键序（tomlkit）。
6. 路径 Helper：`resolve_agent_path(agent_id, rel, env)` 解析顺序 = env 覆盖变量 → XDG → 平台默认 → 探测；测试经 HOME/XDG 注入隔离。

**测试计划**（`tests/unit/test_config.py`、`test_resolve.py`）：
- 正例：三层完整配置解析正确；注释/键序 round-trip 保留断言。
- 反例矩阵：缺 protocol、protocol 非法、base_url 缺失、model 引用不存在的 provider、profile 引用不存在的 model、capabilities 枚举非法、reasoning.effort 非法、version 非 1。
- ENV 语法边界：`${VAR}`、`${VAR:-default}`、子串插值拒绝、嵌套拒绝、`${}` 空变量名拒绝、明文+引用并存拒绝。
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
4. `tree_diff(parsed_before, parsed_after, managed_paths) -> list[str]`：递归比较解析树，排除受管路径节点，返回非管差异清单；Safety 阶段③ 与金样断言共用。要点：对"值等价但类型不同"（int vs float）做容差策略——MVP 采取严格等价（配置语义精确性优先），记录于注释。

**测试计划**（`tests/unit/test_writers_json.py`、`test_writers_toml.py`、`test_writers_diff.py`；`tests/fixtures/writers/`）：
- JSON：键序保持（逆序输入 → 逆序输出）、缩进探测（2/4/制表符样本）、末尾换行有无两态、非 ASCII 两态（原样/转义）、整值替换后其余字节级不变（逐字节 diff 定位仅目标路径）。
- TOML：注释保留（行注释/表头注释/值后注释）、键序保留、空行保留、新建表后原有内容不变、解析-序列化-再解析字节级稳定。
- tree_diff：修改受管路径 → 无差异；修改非管节点 → 精确列出差异；空改 → 空清单。

**验收标准**：
- [ ] round-trip 金样全绿（SPEC §11"Writer round-trip 单测先于适配器交付"硬性前置）。
- [ ] 两种 Writer 的能力声明与测试断言一致（能力表可查询、可审计）。
- [ ] tree_diff 在受管修改场景零误报、非管修改场景零漏报（单测覆盖）。
- [ ] 本包不产生磁盘写入（内存操作，单测断言无副作用）。

---

### WP3 Safety Engine 唯一写通道（规模 L）

**目标**：实现唯一磁盘写通道的五步流水线 + 快照留存 + 指纹校验 + 原子替换 + 全局写锁 + last_write 落盘 + 崩溃清理。**本包是整个 MVP 安全的脊梁**。

**范围与边界**：只提供"写通道"能力（输入 ops → 完成写盘），不感知 CLI/适配器语义；不做漂移检测（属 WP4，但提供漂移所需数据源 last_write 的写）；不做六态判定。黑名单机制 MVP 不实现（白名单封闭）。

**前置**：WP1（路径/状态目录约定）、WP2（Writer）。

**交付物**：`safety.py`、`lock.py`、`state.py`（state 目录与 last_write 部分；state.py 分阶段填充：本包建目录/权限/锁/last_write 写，WP4 补 active 与 last_write 读）。

**任务细项（关键函数与算法）**：
1. `acquire_write_lock()` / `release_write_lock()`：`fcntl.flock` 非阻塞；占用 → `SafetyBlockedError`（exit 2）+ 标准文案；Windows 分支 msvcrt（MVP 以 macOS/Linux 为验证矩阵，Win 分支仅保编译通过）。
2. `write_changeset(agent_id, profile_name, ops, env) -> WriteResult`：串起五步流水线：
   - ① 白名单校验：`op.file ∈ config_paths()` 且 `op.path` 命中命名空间前缀；违反 → `SafetyBlockedError`（exit 2），**任何文件零变更**。
   - ② 写前快照：逐文件读原始字节记 H0（含 `NOT_EXIST` 哨兵）；快照目录 `state/<agent>/snapshots/<ts>/` 原样落盘（文件不存在 → 以哨兵标记记录"写前不存在"，供 rollback 判定删除语义）；目录 0700。
   - ③ 内存修改 + 非管节点断言：Writer 加载 → 应用 ops → 语法自检（可再解析）→ tree_diff 非管节点零差异；失败 → 中止（exit 2），文件零变更。
   - ④ pre-commit 指纹校验：重读磁盘字节，sha256 与 H0 逐文件比对；不等 → 外部并发修改 → 整体中止（exit 2）+ drift 报告，绝不覆盖。
   - ⑤ 原子替换：逐文件同目录 temp（`.acm_tmp`）→ `os.replace`；按 ops 声明顺序提交（双文件顺序由适配器保证，见 WP7）；任一异常回退 → 清理 temp，已替换文件保持新值（符合 SPEC §7.5.6 语义，靠后续漂移阻断 + rollback --hard 兜底）。
   - ⑥ 覆写 `last_write.json`：`{profile, timestamp, backup_id=<ts>, fields: {path: value}}`；文件 0600。
   - 空 ops（幂等）→ 直接返回 no-op，**不建快照、不写 last_write**。
3. `cleanup_stale_tmp(state_dir)`：启动时扫描并静默清理残留 `.acm_tmp`（内务，无用户感知）。
4. `ensure_state_permissions()`：state/logs 目录 0700、文件 0600 创建即设置。
5. 快照命名与检索：`<ts>` = UTC epoch 纳秒固定宽度；`latest_snapshot(agent)` 字典序取最大（确定性）。

**测试计划**（`tests/fault/test_fault_injection.py`、`test_lock_contention.py`、`test_sigkill.py`；配合 conftest 隔离 HOME）：
- 白名单外路径（file 或 path 任一越界）→ exit 2 + 文件字节级零变更。
- 多文件事务中途失败注入（测试钩子在步骤⑤第 N 文件前抛错）→ 未替换文件零变更、temp 无残留。
- 提交间隙 SIGKILL：子进程写通道运行中 `kill -9` → 磁盘无"写一半"文件（每文件要么旧字节要么新字节）；残留 `.acm_tmp` 下次启动被清理；last_write 缺失/过期 → 触发漂移阻断路径（由 WP4 单测配合验证）。
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

**范围与边界**：只做"判定/计算"，不触发任何写入；`status` 命令的展示在 WP5。Desired State 的适配器侧编译依赖 WP6+（本包以注册表接口 + 空实现/桩验收）。

**前置**：WP1、WP3。

**交付物**：`status.py`、`projection.py`、`state.py`（active 读写部分；承接 WP3 的 state.py，本包补 active 与 last_write 读）。

**任务细项**：
1. `read_active(env) -> str | None` / `write_active(profile, env)`：active 文件（仅存 profile 名）；写仅由 `use` 调用（WP5 强制）；不存在 = 尚未激活（首次 use 创建，非错误）。
2. `read_last_write(agent, env) -> LastWrite | None`：读取上次投影记录（profile/时间/backup_id/字段值）。
3. `compute_state(agent, env) -> AgentState`：六态判定实现——
   - detect 失败 → `NOT_DETECTED`；detected 且无 last_write → `UNMANAGED`；
   - 读取当前配置失败/语法损坏/权限异常 → `ERROR`；
   - 逐受管字段比较 current vs last_write → 任一不等 → `DRIFTED`；
   - 否则比较 current vs desired（期望字段经适配器 plan 编译）→ 不等 → `OUT_OF_SYNC`；相等 → `SYNCED`。
   - 优先级 `ERROR > DRIFTED > OUT_OF_SYNC > SYNCED`；文件被删（曾创建）→ 视为 DRIFTED（期望存在值 vs found 不存在）。
4. `detect_drift(agent, env) -> list[DriftEntry]`：逐字段 expected/found（展示走掩码）。
5. `is_noop(agent, ops, env) -> bool`：幂等判断（desired==current 且无漂移）。
6. `compute_desired(profile, env) -> dict[agent_id, list[FieldOp]]`：遍历注册表，调各适配器 `plan()` 编译；MVP 阶段注册表为空/桩时返回空（WP6+ 填充）。
7. 未初始化判定：config.toml 缺失 → 六态计算给出"未初始化"信号（CLI 层映射为"请先 `acm init`" + exit 1，见 A10）；active 缺失 = 正常初始态（首次 use 创建），不视为错误。

**测试计划**（`tests/unit/test_status.py`、`test_projection.py`）：
- 六态矩阵：构造 NOT_DETECTED / UNMANAGED / SYNCED / OUT_OF_SYNC / DRIFTED / ERROR 各输入组合断言。
- 优先级：DRIFTED+OUT_OF_SYNC 并存 → DRIFTED；ERROR+DRIFTED → ERROR。
- 漂移 expected/found 精确值与掩码展示。
- 幂等：desired==current 无漂移 → no-op；有漂移 → 非 no-op。
- 文件删除场景（曾创建后删除 → DRIFTED）。
- active 读写、last_write 读写 round-trip。

**验收标准**：
- [ ] 六态矩阵单测全绿（与 SPEC §7.6 枚举完全一致，无枚举缩减）。
- [ ] 漂移判定输出 expected/found 具体值（掩码后）。
- [ ] 本包零写入（除 active/last_write 显式读写函数，单测断言无其他副作用）。
- [ ] 与 WP3 联测：last_write 缺失 → 漂移阻断路径成立（配合故障注入）。

---

### WP5 CLI 命令面（规模 L）

**目标**：`init / use / status / rollback` 四条命令 + 全局旗标 + 退出码规范 + 输出/掩码/日志；`use` 的编排逻辑（resolve → per-agent plan → Safety 写通道 → last_write → 告警聚合）。

**范围与边界**：MVP 命令面完整实现；`--to-tx`/`--snapshot` 等后置参数**不注册**（typer 未知选项即拒绝，报错清晰）；`--verbose` 纳入与否见待拍板 A4。`use` 对具体适配器的集成验证在 WP6+ 落地（本包以 stub 适配器验收）。

**前置**：WP1–WP4。

**交付物**：`cli.py`、`main.py`、`errors.py`、`output.py`、`masking.py`、`vmr.py`。

**任务细项**：
1. typer 应用与命令注册：`init [--dry-run] [--force]`、`use <profile> [--dry-run] [--force]`、`status [--verbose]`、`rollback [<agent>] [--force]`；全局旗标 `--dry-run` `--force` `--no-color` `--show-secrets`。
2. 退出码规范（SPEC §10.2 / PRINCIPLE §4.3.3）：0 成功/no-op；1 配置错误（语法/schema/ENV 未解析、config 未初始化）；2 安全阻断（漂移/写锁/白名单）；3 I/O 与权限；4 未找到（Agent/profile/snapshot）；130 SIGINT（typer 捕获 + 统一处理）。流约定：正常结果 stdout，错误/警告/日志 stderr。**usage-error 退出码冲突见待拍板 A5**。
3. `init`：
   - Agent 扫描（遍历注册表 detect，失败跳过并汇总）；
   - VMR 探测（§4.2 容错顺序，超时 1s）；
   - 提案构建（VMR 命中 → 完整生成；未命中 → 注释示例模板）；
   - rich 展示提案（含将写入的 providers/models/profile；api_key 显示 `${VAR}` 引用本身，无明文）；
   - 交互确认（typer confirm；`--force` 跳过；config 已存在 → 覆盖/取消，默认取消；增量合并见 A3）；
   - 写入：config.toml（tomlkit 生成，含清晰注释）+ `state/` 目录（0700）+ `~/.acm/.gitignore`（排除 state/ logs/ .lock）；
   - `--dry-run`：只展示提案零写盘。
4. `use <profile>`：
   - config.toml 缺失 → "未初始化：请先 `acm init`" → exit 1（A10）；校验 profile 存在（否则 exit 4）；
   - resolve（ENV 缺失 → 硬失败 exit 1，零写盘）；
   - **写 active**（激活态仅 use 可写；active 由首次 use 创建而非 init；**active 更新独立于投影 ops**——换 profile 后即使模型相同、投影为 no-op，active 也照常更新）；
   - 遍历已检测 Agent：
     - 每 Agent：compute_state → 漂移 → 默认阻断 exit 2（标准文案 §10.3）+ 建议 `--force`；`--force` 显式覆盖；
     - plan 编译 → ops 空（幂等）→ no-op 跳过 → Safety 写通道 → 收集投影告警；
     - 批处理独立收敛：单 Agent 失败不中断其余，stderr 指名失败 Agent，最终退出码 = 最高严重度；
   - 投影告警聚合展示（stderr 单行 + status 汇总源）。
   - `--dry-run`：计算 + 展示（含预期变更与告警），**不写 active/快照/last_write**，零写盘。
5. `status [--verbose]`：表格展示各 Agent 六态 + 当前 profile + 漂移摘要 + 投影告警汇总；`--verbose` 扩展（受管字段明细，掩码）。
6. `rollback [<agent>] [--force]`：MVP 语义 = 恢复最新整文件快照（等价终局 `--hard`）；缺省恢复全部有状态的 Agent；无快照 → exit 4；涉及删除"ACM 全新创建文件"（恢复到"不存在"）时要求 `--force` 显式确认（见待拍板 A11 的安全提示）；恢复前同样获取写锁并做快照留档（恢复动作本身也是写，保留可回溯性——设计决策见 A12）。
7. `masking.py`：敏感路径 token 规则（api_key/token/auth/secret/key）；掩码 = 首尾各 3 位；`--show-secrets` 全局 opt-in。
8. `output.py`：rich 渲染；`--no-color` 与 `NO_COLOR` 环境变量；日志（stdlib logging → `~/.acm/logs/acm.log`，目录 0700；默认 INFO 摘要，`--verbose` DEBUG；错误/警告走 stderr）。
9. `errors.py`：异常层级（ConfigError→1、SafetyBlockedError→2、IOFailure→3、NotFoundError→4、UserAbort→130）与 typer 退出码映射。
10. `vmr.py`：探测 + `/v1/models` 解析（id、vmr_protocol）→ 提案数据结构。

**测试计划**（`tests/integration/test_cli_init.py`、`test_cli_use.py`、`test_cli_status.py`、`test_cli_rollback.py`；typer CliRunner + 隔离 HOME）：
- init：全新 HOME → 提案展示（VMR 命中/未命中两分支，用 fake VMR HTTP 或探测注入）→ 确认 → config.toml/.gitignore/state 生成正确（0700 断言）；已存在 config → 默认取消（文件零变更）；`--force` 覆盖；`--dry-run` 零写盘；VMR 未命中 → 模板 config 生成。
- use：stub 适配器全链路（幂等 no-op exit 0 无快照 / 正常投影 / 漂移阻断 exit 2 + expected/found + `--force` 收敛 / ENV 缺失 exit 1 零写盘 / 未知 profile exit 4 / 未 init exit 4）；批处理：一 Agent 阻断另一 Agent 成功 → 成功者生效 + 退出码非零 + stderr 指名。
- status：六态各场景展示（与 WP4 单测同构的 CLI 面）。
- rollback：有快照恢复字节一致（写前后 sha256）；无快照 exit 4；`--force` 删除场景。
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

**前置**：WP2–WP5。

**交付物**：`adapters/claude_code.py`；金样 `tests/fixtures/claude_code/`；金样测试 `tests/golden/test_adapters_claude.py`；CLI 集成测试 `tests/integration/test_cli_claude.py`。

**任务细项（映射表与转换）**：
1. `detect`：`~/.claude/settings.json` 存在（主判据）+ `claude` 可执行（辅）。
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

**目标**：TOML round-trip + **双文件事务**（`config.toml` + `auth.json`）+ "新建 TOML `model_providers` 表"形状（SPEC Slice 1 第二种形状）。

**范围与边界**：只写 `~/.codex/config.toml` 与 `~/.codex/auth.json`；`mcp_servers`（本机实证注释密集）等非管内容零破坏。

**前置**：WP2–WP5。

**交付物**：`adapters/codex.py`；金样 `tests/fixtures/codex/`（config.toml 注释密集 MCP 表 + auth.json，脱敏）；`tests/golden/test_adapters_codex.py`；`tests/integration/test_cli_codex.py`。

**任务细项**：
1. `detect`：`~/.codex/config.toml` 存在（主判据）+ `codex` 可执行（辅）。
2. `config_paths`：config.toml + auth.json（顺序 = 提交顺序：auth.json 在前、config.toml 在后，理由见 §4.2）。
3. 映射表：
   - `profile.main.model_id` → 顶层 `model`；
   - `reasoning.effort` → 顶层 `model_reasoning_effort`（SPEC 适配矩阵 ✔，具体取值映射金样校准）；
   - provider → `model_providers.<id>` 表：`base_url`、`wire_api`（protocol 方言映射）、`env_key`（指向 auth.json 中的 key 名）；
   - `api_key` 解析值 → auth.json 对应 key（key 名 = 上述 env_key，金样校准命名规则）。
4. 双文件一致性：两文件的 op 在同一批次（同一 FieldOp 列表）内提交；提交顺序保证最坏失败可自愈（§4.2）。
5. 投影损失：无法表达的字段 → 告警。
6. 白名单命名空间：`model`、`model_reasoning_effort`、`model_providers.*`；auth.json 的 key 路径。

**测试计划（金样 a/b/c + 双文件故障）**：
- fixture：真实 config.toml 脱敏（保留 `mcp_servers` 大量带注释条目、`features`/`sandbox` 等非管表）+ auth.json 脱敏。
- a. Apply：顶层 model / model_reasoning_effort / model_providers.<id> 表（base_url/wire_api/env_key）与 auth.json key 均正确；auth.json 其余键（如 OAuth 相关，若有）不变。
- b. Non-destructive：mcp_servers 全部注释与条目逐字节保留（tree_diff + 词法断言）。
- c. Rollback：双文件均恢复写前字节。
- 负面：中途失败注入（auth.json 已替换、config.toml 前失败）→ 未替换文件零变更、temp 无残留；`rollback --hard` 可恢复。
- 幂等：重复 use → no-op 无新快照。
- CLI 集成：use daily → status SYNCED；外部改 `model` → DRIFTED → 阻断 → `--force`。

**验收标准**：
- [ ] 金样 a/b/c 全绿（含双文件）；mcp_servers 注释保留断言全绿。
- [ ] 双文件中途失败注入 → 自愈路径（漂移阻断 + rollback --hard）验证通过。
- [ ] 本机真实 config.toml（先备份）use 一次成功，注释与非管表不变（人工确认）。

---

### WP8 Pi 适配器（Slice 2，规模 M）

**目标**：注册式投影形态 + **全新建文件场景**（本机实证 `models.json` 不存在），补齐 P0 三件套。

**范围与边界**：只写 `~/.pi/agent/models.json`（不存在则创建）与 `~/.pi/agent/settings.json`；**绝不碰 `models-store.json`**（白名单封闭）；`trust.json`/`auth.json`/extensions/skills 零触碰。

**前置**：WP2–WP5。

**交付物**：`adapters/pi.py`；金样 `tests/fixtures/pi/`；`tests/golden/test_adapters_pi.py`；`tests/integration/test_cli_pi.py`。

**任务细项（映射表与转换）**：
1. `detect`：`~/.pi/agent/` 目录存在。
2. `config_paths`：models.json + settings.json；models.json 不存在 → 标记"ACM 将创建"（`created` 语义）。
3. 映射表（注册式：消费完整 models 定义）：
   - provider → `providers.<name>`：`baseUrl`、api 方言（`openai-completions` / `anthropic-messages`，由 protocol 映射）、`apiKey`（解析明文）、`models[]` 数组项：`id`、`contextWindow`、`maxTokens`、`compat`、`thinkingLevelMap`（能力位/推理等级映射，金样校准）；
   - settings.json：`defaultProvider`、`defaultModel`、`defaultThinkingLevel`；
   - 推理：`reasoning.effort` → `thinkingLevelMap` 与 `defaultThinkingLevel` 的换算（Spec 适配矩阵 ✔ 同构度最高）。
4. 全新建文件流程：models.json 由 ACM 首次创建（`created_by_acm` 语义）→ last_write 记录创建事实 → rollback 恢复 = 删除该文件（要求 `--force`，A11）。
5. 投影损失：无法表达字段 → 告警。

**测试计划（金样 a/b/c + 新建场景）**：
- fixture：settings.json 真实脱敏（153B 样本）；models.json 用"预置样例"与"不存在"两种输入态。
- a. Apply：不存在 → 创建且结构正确；存在 → 精确更新；settings.json 三默认字段正确；其余键（如自定义键）不变。
- b. Non-destructive：settings.json 非管字段零破坏；models-store.json 从未被读写（单测断言路径不在 config_paths）。
- c. Rollback：创建场景 → 文件删除（`--force`）；更新场景 → 字节恢复。
- 负面：op 指向 models-store.json → 拦截 exit 2 文件零变更。
- CLI 集成：use daily → status SYNCED；外部删 models.json → DRIFTED → 阻断。

**验收标准**：
- [ ] 金样 a/b/c 全绿（含全新建文件与删除回滚）。
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
2. 打包验证：`uv build`；隔离环境 `uvx acm --version`、`uv tool install acm`、`pipx install`（如本机可用）逐一验证。
3. 硬性验收 8 条脚本化（对应 §7 逐条），在隔离 HOME 全量执行。
4. 发布：查名（PyPI 索引）确认可用 → `uv build` → `uv publish`（或等效流程）；发布后 `uvx acm` 从公网拉取冒烟。
5. 发布前对照"非成功样貌"自检（SPEC §14）：无 GUI/MCP/网关/私有 DB/数量 KPI/状态入库。

**测试计划**：`test_e2e_acceptance.py` = §7 的 8 条验收映射为可执行脚本（隔离 HOME + fake VMR 或真实 VMR）。

**验收标准**：
- [ ] 硬性验收 8/8 全绿（§7 表格逐条）。
- [ ] `uvx acm` / `uv tool install acm` / `pipx` 三通道安装冒烟通过。
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

- mypy strict 全绿（`warn_return_any` 已开，禁止 Any 泄漏）；公开函数必须有 docstring。
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
| 2 | 非破坏性：10 次 use/rollback 循环后未管键与注释不变 | 循环脚本 + tree_diff/词法断言 | 10/10 循环后非管内容与初始一致 |
| 3 | 可逆性：任意写入后 rollback 回到写前字节 | 写后 sha256 vs 恢复后 sha256 | 逐文件字节相等 |
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
| Codex 双文件事务中途失败 | 低 | 中 | 提交顺序（auth.json 先）+ 漂移阻断 + `rollback --hard` 兜底（§4.2） |
| VMR 端点漂移（本机 healthz 404 实证） | 高 | 中 | 多端点容错探测顺序；`/v1/models` 为主证据（A2 待拍板是否回写 Spec） |
| 上游 Agent schema 漂移 | 高频 | 小 | 金样哨兵 + ERROR 态安全阻断 + AI 辅助改适配器 |
| 快照明文密钥泄露 | 低 | 中 | state 0700/0600 + 展示掩码 + README 卸载建议删除 `~/.acm/` |
| PyPI 包名冲突 | 中 | 中 | WP9 发布前先查名；必要时 `acm-cli` 备用名（A13） |
| 单人维护漂移 | 中 | 高 | 治理规格分层 + 本 Action Plan 任务包验收即质量门 + scope 严格控制 |
| Pi 全新建文件被误删（rollback） | 低 | 中 | 恢复"删除文件"要求 `--force` 显式确认（A11） |

---

## 9. 其他重要问题与待拍板决策

> 本节收录规划过程中发现的新问题、Spec 需调整点、需要你拍板的 Option。**建议（Recommendation）为默认执行路径，未拍板前按建议执行；你的裁决后可回写本表。**

### A1. pydantic 依赖去留（依赖预算 vs 现状）
- **发现**：现有 pyproject.toml 已将 `pydantic>=2.0.0` 列为**硬依赖**；SPEC D2 定义其"可选"，引入标准为"Core Config 校验超 ~200 行或规则组合"。uv.lock 已锁定 pydantic 2.13.4。
- **影响**：运行时依赖组数（typer+rich、ruamel、tomlkit、pydantic）与 SPEC"≤4 个"表述的符合度。
- **建议**：**保留 pydantic 并正式计入预算**——理由：Core Config 三层嵌套 + capabilities/reasoning 子表 + credential 语法校验的校验规则预计超 200 行且开始组合；已在 lock 中零增量成本；SPEC D2 允许"引入即计入预算"。以"5 个运行时依赖"口径在 README 说明（或按"4 组"口径）。若你倾向严格 ≤4，则降级为 dataclass + 显式校验（WP1 工作量 +0.5 天）。
- **需拍板**：保留（默认）/ 剔除。

### A2. VMR 探测端点与 Spec §9 表述差异（需回写 Spec）
- **发现**：本机实证 `127.0.0.1:8800/healthz` 返回 404，而 `/v1/models` 返回 200 且包含模型列表（含 `vmr_protocol`）；`~/.vmr/` 无配置文件（仅 image_cache/logs）。SPEC §9 描述探测为"healthz，fallback 读取 ~/.vmr/ 配置"——与实测不符。
- **影响**：若照 Spec 字面实现，本机将探测失败，init 生成模板而非完整 VMR 提案，直接击穿成功标准 1。
- **建议**：探测顺序改为 `healthz`（快速通道）→ `/v1/models`（主证据 + 数据源）→ `~/.vmr/` 已知配置 → 未命中；并将该顺序**回写 Spec §9**。
- **需拍板**：认可建议（默认）并确认回写 Spec。

### A3. init 重复执行的"增量合并"选项范围
- **发现**：SPEC §10 命令表写"提示 覆盖/增量合并/取消"；§9 又说 MVP 阶段增量合并靠手编 TOML 或 `init --force` 重生成解决（import vmr 后置）。两处张力。
- **建议**：MVP 的 init 重复执行仅提供 **覆盖 / 取消**（默认取消）；"增量合并"随独立 `import vmr` 触发引入，避免 MVP 偷偷实现半个 import 语义。
- **需拍板**：认可（默认）/ 坚持 MVP 即支持增量合并。

### A4. `--verbose` 是否纳入 MVP
- **发现**：SPEC §12 Slice 1 旗标清单只含 `--dry-run/--force/--no-color/--show-secrets`；§10.1 又定义了 `--verbose`（DEBUG 日志）。日志目录 `logs/` 在 MVP 目录布局中。
- **建议**：**低成本纳入 `--verbose`**（日志基建反正要建；排障必需），在 §12 清单补记为范围微扩。
- **需拍板**：纳入（默认）/ 严格排除。

### A5. usage-error 退出码与"2=安全阻断"冲突
- **发现**：typer/click 对未知命令/参数默认退出码为 2，与 SPEC 定义的"2=安全阻断"语义冲突，脚本化时无法区分。
- **建议**：统一拦截 usage 错误 → 输出用法说明到 stderr → 退出码 **1**（归入"配置/用法错误"档），保留 2 专用于安全阻断；在 SPEC §10.2（或 PRINCIPLE §4.3.3）补一句注明。
- **需拍板**：认可（默认）/ 保持 typer 默认 2 并在文档声明重载。

### A6. rollback 的旗标面（MVP）
- **发现**：终局 `--to-tx/--hard/--snapshot` 多态旗标 MVP 不实现；直接不注册会报"unknown option"。
- **建议**：MVP 只注册 `rollback [<agent>] [--force]`；`--hard` 不注册（行为本身即 hard 语义，README 说明"MVP rollback = 整文件恢复最新快照"）；`--to-tx/--snapshot` 不注册（typer 自动拒绝，错误信息清晰）。避免"注册但报未实现"的伪接口。
- **需拍板**：认可（默认）/ 要求注册并显式拒绝。

### A7. 掩码规则覆盖范围
- **发现**：last_write 存明文值（漂移比对需要），展示需掩码；init 提案无明文（只显 `${VAR}`）。
- **建议**：统一敏感 token 规则（api_key/token/auth/secret/key），作用于 status 明细 / dry-run 展示 / 错误消息中的 expected/found（`--json` 属 Phase 2，引入时复用同一规则）；快照与 last_write 静态文件靠 0700 保护，不额外加密（MVP 边界）。
- **需拍板**：认可（默认）/ 需 keychain 级保护（明确不属 MVP）。

### A8. README 失效文档链接
- **发现**：README 引用的 `ACM_PROJECT_SPEC_v2.0.md`、`ACM_PROJECT_SPEC_FINAL_v1.1.md`、`ACM_SPEC_CONSISTENCY_REVIEW.md` 已不存在于 docs/（仅存 v2.1 两份 + 深度研报等）。
- **建议**：WP0 修正链接指向 v2.1 两份，或标注"已归档"。
- **需拍板**：修正（默认）/ 保留历史引用。

### A9. CI 是否启用（GitHub Actions）
- **发现**：SPEC §11.3 有 CI 策略；本机为单人内部开发。
- **建议**：先在本地脚本（`make check` 或 pre-commit）承载质量门，CI 工作流**随代码入库一并启用**（低成本、锁漂移检查有价值）；若暂无远端仓库需求可延后。
- **需拍板**：本地脚本（默认）/ 立即上 CI。

### A10. 未 init 即 use/status 的行为与 active 文件的创建时机
- **发现**：config.toml 缺失时 use/status 的行为在 Spec 未明示；且 **init 不创建 `state/active`**（Spec：激活态"只能通过 acm use 改变"），active 在首次 use 前本就不存在——不能以 active 缺失作为"未初始化"判据。
- **影响**：守卫条件选错会导致首次 use 被误拦或永不拦截。
- **建议**：① config.toml 缺失 → "未初始化：请先 `acm init`" → exit 1（use/status 一致）；② active 由首次 use 创建（正常流程，非错误）；③ active 更新独立于投影幂等（use 换 profile 即使模型相同也更新 active）。
- **需拍板**：认可（默认）/ 其他处理。

### A11. rollback 恢复"ACM 全新创建文件"的安全性
- **发现**：Pi models.json 由 ACM 创建；恢复"写前状态"= 删除文件。若 Pi 运行期间已向其中写入用户内容，整文件恢复会连内容一起删除（MVP 无字段级回滚，SPEC 已认可 MVP 整文件语义，但删除比覆盖更敏感）。
- **建议**：涉及"删除文件"的 rollback 必须 `--force` 显式确认（输出将删路径清单）；README 提示"此操作属灾难恢复，可能丢失 Agent 期间新增内容"。
- **需拍板**：认可（默认）/ 更保守（MVP 禁止删除，仅提示）。

### A12. rollback 动作本身是否留档
- **发现**：rollback 恢复前是否再快照一次，Spec 未明示。
- **建议**：**恢复前先留一份当前快照**（恢复动作视为一次写），保证"恢复错了还能再恢复"，成本极低且符合 Append-only 哲学。
- **需拍板**：留档（默认）/ 不留。

### A13. PyPI 包名可用性
- **发现**：包名 `acm` 极可能已被占用（通用缩写）。
- **建议**：WP9 发布前查名（PyPI 索引，如 `pip index versions acm` 或 PyPI JSON API）；若冲突使用备用名（如 `acm-cli`）并同步改 pyproject/入口（入口 `acm` 命令名不受影响）。
- **需拍板**：备用名预案认可（默认）/ 其他命名。

### A14. 测试中 VMR 的注入方式
- **发现**：e2e 需 VMR 场景，但不能依赖本机 8800 常驻（且 healthz 404）。
- **建议**：conftest 提供 fake VMR HTTP server（或探测目标 env 注入），e2e 默认走 fake；本机真实 VMR 作为人工验证补充。
- **需拍板**：fake server 方案（默认）/ 只验证真实 VMR。

### A15. Windows 支持范围
- **发现**：Spec 提及 POSIX/Win 原子操作与 msvcrt 锁；本机为 macOS，MVP 验证矩阵无 Windows。
- **建议**：代码层 `fcntl`/`msvcrt` 双实现保编译与基础可用，但 Windows 不在 MVP 验收矩阵（文档注明"macOS/Linux 优先"）。
- **需拍板**：认可（默认）/ 明确 MVP 仅 macOS/Linux（去掉 Win 分支）。

---

## 10. 本次规划自检记录

> 规划完成后通读全文的自检修正记录（评审输出，供追溯）：

| 检项 | 发现 | 修正 |
|---|---|---|
| 范围 | 初稿误将 `--json`、`doctor` 文案、`protected_paths` 黑名单列入 MVP | 按 SPEC §12/触发式升级表剔除并显式声明"不在 MVP" |
| 一致性 | `rollback` 旗标面初稿含 `--hard`；与 SPEC"MVP 仅整文件恢复"语义重复 | 收敛为 `rollback [<agent>] [--force]`，语义在 §4.2/A6 说明 |
| 一致性 | VMR 探测初稿照抄 Spec"healthz 优先" | 按本机实证（healthz 404、/v1/models 200）改为多端点容错并列入 A2 回写 |
| 疏漏 | 初稿未覆盖"ACM 全新创建文件"的 rollback 删除安全 | 新增 A11 + WP8 任务细项 4 + 风险表条目 |
| 疏漏 | 初稿未定义快照 `<ts>` 命名确定性（"最新快照"歧义） | §4.2 明确 UTC 纳秒固定宽度、字典序=时间序 |
| 疏漏 | 初稿未处理"未 init 即 use" | 新增 A10 与 WP5 任务细项 4 |
| 一致性 | use 的 CLI 集成测试归属（WP5 vs WP6+） | 明确 WP5 以 stub 验收编排逻辑，适配器集成测试随 WP6/7/8 落地（§5 依赖图注） |
| 错误 | 初稿将 ENV 校验放 config 加载时 | 修正为"投影时实时求值"（SPEC §7.3.1-3），加载只做语法校验 |
| 边界 | 初稿把"非 VMR 用户手编 config.toml"误判为违背零编辑原则 | 明确成功标准仅约束"零手改 **Agent 配置文件**"，SSOT 手编合法（§4.2 init 提案） |
| 疏漏 | 未提测试卫生（真实配置保护） | 新增 §4.3 铁律 + 风险表首条 |
| 一致性 | use 流程中"读 active（仅此处可写）"表述错误；active 由首次 use 创建而非 init | 重写 WP5 task 4 与 WP4 task 7：guard 改为 config.toml 缺失（exit 1）；active 更新独立于投影幂等 |
| 引用 | "SPEC §4.3.6 / SPEC §3.3 / SPEC §4.3.3" 引用错位（分属 PRINCIPLE 与 SPEC §10.2） | 修正为 PRINCIPLE §4.3.6 / §3.3；退出码引用改 SPEC §10.2 / PRINCIPLE §4.3.3 |
| 疏漏 | `--dry-run` 是否写 active 未明确 | WP5 明确不写 active/快照/last_write |
| 疏漏 | WP4 前置依赖表缺 WP3（last_write 读依赖其写入） | 修正为 WP1, WP3 |
| 事实 | "uv publish --dry-run 查名"不成立 | A13/WP9 改为 PyPI 索引查名 |
| 范围 | A7 提及 JSON 输出掩码（--json 不在 MVP） | 移除并注明 --json 引入时复用规则 |
| 边界 | 快照"文件不存在"的记录方式未定义（rollback 删除语义依据） | WP3 明确哨兵标记记录 |
| 一致性 | §6.4 CI 常规 job 会连带执行 e2e 验收 | 明确 e2e 标记默认排除、单独 job |
| 边界 | WP0 CI 交付物与 A9 默认（本地优先）张力 | WP0 改为"质量门脚本 + CI 骨架（可选）" |

---

## 附录 A：金样 fixture 规范

1. **来源与脱敏**：取自本机真实文件（settings.json / config.toml / auth.json / settings.json@pi），将全部密钥/令牌替换为确定性占位（如 `sk-xxxxxxxxxxxxxxxx`、`"PLACEHOLDER_TOKEN"`），**保留**：结构、注释、键序、空行、缩进风格、格式怪癖（如 Codex 注释密集的 `mcp_servers` 表）。
2. **目录与命名**：`tests/fixtures/<agent>/`（每适配器独立，漂移不跨 Agent 传染）；文件命名如 `settings.golden.json`、`config.golden.toml`、`auth.golden.json`、`models.golden.json`；writers 词法金样放 `tests/fixtures/writers/`。
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
| ChangeSet（MVP 简化） | 适配器产出的 `FieldOp` 列表 + `ProjectionWarning` 列表（无独立子系统命名） |
| last_write | `state/<agent>/last_write.json`：最近一次投影记录（profile/时间/backup_id/受管字段值），MVP 漂移检测数据源 |
| Snapshot | 写前原样字节备份，`snapshots/<ts>/`，Append-only，灾难恢复与审计 |
| Drift | Current ≠ ACM 最后写入值（外部修改）→ 默认阻断 |
| Projection Loss | Desired 中目标 Agent 无法表达的字段 → 显式告警 |
| 六态 | NOT_DETECTED / UNMANAGED / SYNCED / OUT_OF_SYNC / DRIFTED / ERROR |
| 唯一写通道 | safety.py 的五步流水线：白名单 → 快照 → 内存修改+非管断言 → 指纹 → 原子替换 → last_write |
