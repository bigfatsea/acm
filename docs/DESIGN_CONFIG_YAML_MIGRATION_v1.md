# ACM 设计方案：Core Config 采用 YAML 格式（config.yaml）

<!-- 版本: v1.1 | 状态: 设计定稿，执行中 | 日期: 2026-08-26 -->
<!-- 关联文档: ACM_PROJECT_PRINCIPLE_v2.1.md（§1.3 技术栈基线）· ACM_PROJECT_SPEC_v2.1.md（§6 D3）·
     USER_GUIDE.md §5 · CLAUDE.md · DESIGN_MODEL_POOL_v1.md -->
<!-- 文档定位：本设计文档描述"ACM Core Config 使用 YAML"这一现状的设计依据与落地行动方案。
     全文按最终方案陈述，不保留被否决的备选路线叙述。
     文末附录 C 为本轮实施的执行记录与结果总结。 -->

---

## 目录

- [0. TL;DR](#0-tldr)
- [1. 背景与动机](#1-背景与动机)
- [2. 影响面全景分析](#2-影响面全景分析)
  - [2.1 范围澄清：只动 ACM 自己的 SSOT](#21-范围澄清只动-acm-自己的-ssot)
  - [2.2 源码影响面（逐文件）](#22-源码影响面逐文件)
  - [2.3 明确不受影响的组件及理由](#23-明确不受影响的组件及理由)
  - [2.4 测试影响面（逐文件）](#24-测试影响面逐文件)
  - [2.5 文档影响面（逐文件）](#25-文档影响面逐文件)
  - [2.6 构建/发布影响面](#26-构建发布影响面)
- [3. 方案设计与关键决策](#3-方案设计与关键决策)
  - [D1 迁移范围与投影纪律](#d1-迁移范围与投影纪律)
  - [D2 YAML 解析库选型：ruamel.yaml（safe 模式）](#d2-yaml-解析库选型ruamelyamlsafe-模式)
  - [D3 目标 YAML 格式规格](#d3-目标-yaml-格式规格)
  - [D4 schema version 保持 1 不变](#d4-schema-version-保持-1-不变)
  - [D5 直接切换：无存量迁移路径](#d5-直接切换无存量迁移路径)
  - [D6 附带小重构：配置路径集中化](#d6-附带小重构配置路径集中化)
  - [D7 版本号与发布策略](#d7-版本号与发布策略)
  - [D8 文档一致性原则：全量反映现状，拒绝补丁式批注](#d8-文档一致性原则全量反映现状拒绝补丁式批注)
- [4. Action Plan（任务分解）](#4-action-plan任务分解)
  - [Task 1 依赖与解析层改造](#task-1-依赖与解析层改造)
  - [Task 2 提案/模板生成器改造](#task-2-提案模板生成器改造)
  - [Task 3 CLI 改造](#task-3-cli-改造)
  - [Task 4 存量测试改造](#task-4-存量测试改造)
  - [Task 5 新增测试](#task-5-新增测试)
  - [Task 6 文档全量同步](#task-6-文档全量同步)
  - [Task 7 旧代码与遗留逻辑清理](#task-7-旧代码与遗留逻辑清理)
  - [Task 8 版本发布收尾](#task-8-版本发布收尾)
  - [Task 9 最终复核（收尾门禁）](#task-9-最终复核收尾门禁)
- [5. 风险登记表](#5-风险登记表)
- [6. 整体验收标准](#6-整体验收标准)
- [附录 A：解析层参考实现骨架](#附录-a解析层参考实现骨架)
- [附录 B：逐文件改动速查表](#附录-b逐文件改动速查表)
- [附录 C：执行记录与结果总结](#附录-c执行记录与结果总结)

---

## 0. TL;DR

**决策**：ACM 的单一事实源文件采用 YAML，路径为 `~/.acm/config.yaml`。YAML 的缩进层级对三层（providers → models → profiles）嵌套结构表达更清晰，是本项目的配置格式选择。

| 维度 | 决策 |
|---|---|
| 改动范围 | **仅 ACM 自有 SSOT 的格式与读写路径**。Codex 的目标文件 `~/.codex/config.toml`、VMR 探测回退的 `~/.vmr/config.toml` 均不动；`tomlkit` 作为 Codex 适配器的 round-trip 写入依赖**保留** |
| 投影纪律 | 本次为 ACM 内部迁移：**不触发任何 Agent 配置的自动重投影**。已投影的 Agent 文件保持最后一次投影状态，由用户在迁移完成后人工核查、分析、手动同步 |
| 解析库 | **`ruamel.yaml`（`typ="safe"` 纯数据加载）**。实验验证其天然规避 YAML 两大陷阱（YAML 1.2 语义无 yes/no 布尔歧义；重复键直接抛 `DuplicateKeyError`），并与 SPEC 既定的 P1 阶段 YAML 依赖预算合流为同一个包 |
| 数据模型 | **零变化**。providers/models/profiles 三层结构、全部字段名、校验规则、`${VAR}` 引用语法原样保留；`version = 1` 语义不变 |
| 存量兼容 | **不做存量迁移设计**。项目处于起步期，无存量用户负担：ACM 只读 `config.yaml`；文件缺失即标准的未初始化提示（`Run 'acm init' first`）；不存在任何迁移命令、检测逻辑或用户指引章节 |
| 文档方针 | 所有活文档（README / USER_GUIDE / CLAUDE.md / PRINCIPLE / SPEC / DESIGN_MODEL_POOL）**全量改写为 YAML 表述**，从头到尾只呈现当前实现，无变更注记、无补丁、无批注 |
| 改动规模 | 源码 3 个文件（`config.py` / `vmr.py` / `cli.py`）+ `util.py` 小增 + `pyproject.toml` 加一个依赖；测试 14 个文件内容转换 + 约 12 个新增用例；文档 9 个活文档全量同步 |
| 版本 | **0.2.0** |

---

## 1. 背景与动机

### 1.1 现状

ACM 的 SSOT 文件承载三层声明式配置（L1 providers / L2 models / L3 profiles），由 `acm init` 生成、用户手工维护、所有命令读取校验。实现要点：

- 解析入口：`src/acm/config.py::parse_config_toml()`，用 `tomlkit.parse` 后交给 pydantic `CoreConfig.model_validate`；
- 生成入口：`src/acm/vmr.py::generate_vmr_proposal()` / `generate_template_config()`，手拼文本；
- 文件路径：`cli.py` 三处内联 `acm_home / "config.toml"`。

### 1.2 为什么用 YAML

针对本文件的实际形态，YAML 的层级结构优势明确：

- models 下每项带可选子块（`reasoning` / `capabilities`），扁平表头写法需要 `[models.coding.reasoning]` 这类"跳表"，视觉上与同级模型条目割裂；YAML 的嵌套缩进把子属性自然归位到所属模型之下，三层结构一眼可读；
- pool-only profile 只需一个 `pool:` 子键即可表达，无需空表 + 子表两段式；
- 映射键允许包含 `.` `/` 等字符，VMR 探测到的上游模型 id 可直接作为别名键，无需净化改名；
- 列表与映射形态统一，未来引入数组型字段（如 headers 列表化）无需改变风格。

代价与缓解：新增一个 YAML 运行时依赖（选型见 D2，且 README 的 writers 描述本已宣传 ruamel.yaml）；YAML 的类型歧义风险由加载行为契约钉死（D2 表格）并有测试背书。ACM 对自身 SSOT 只有 `init` 整文件重生成一种写路径，不存在增量改写场景（`import vmr` 为触发式后置且未实现），因此格式选择只需优化"人读手写"体验——这正是 YAML 的强项。

### 1.3 目标（可验收）

1. 所有命令读写 `~/.acm/config.yaml`，行为与退出码语义完全不变；
2. 数据模型、校验规则、错误消息质量不降级；
3. YAML 特有的坑（布尔歧义、重复键、锚点引用、多文档）有明确的处理策略与测试背书;
4. 不存在任何存量迁移路径、迁移文档或自动重投影行为；
5. 全部质量门禁保持绿色（pytest / ruff / mypy strict）；
6. 全部活文档从头到尾只呈现 YAML 现实，无 TOML 残留（Agent 端文件的合法引用除外）。

---

## 2. 影响面全景分析

> 分析方法：对全仓库 `grep "config\.toml"`（源码/测试/文档分别统计），再逐一人工判定归属，并对照实际源码逐行核实。
> 统计基线：2026-08-26 工作区（v0.1.2）。

### 2.1 范围澄清：只动 ACM 自己的 SSOT

仓库里 "config.toml" 字样出现在三个**互不相干**的位置，动手前必须切开，否则会误伤：

| # | 文件 | 归属 | 处理 |
|---|---|---|---|
| ① | `~/.acm/config.yaml`（原 `config.toml`） | **ACM 自己的 SSOT**（本文档主角） | ✅ 本轮改为 YAML |
| ② | `~/.codex/config.toml` | **Codex CLI 的自有配置文件**，是投影目标（target），由 `adapters/codex.py` 管理、`writers/toml_editor.py` round-trip 写入 | ❌ 不动。这是上游 Agent 的既定格式，不由我们决定 |
| ③ | `~/.vmr/config.toml` | **VMR 的自有配置文件**，仅在 `probe_vmr()` 第三级回退中做存在性检查 | ❌ 不动。那是 VMR 项目的格式约定 |

推论：**`tomlkit` 依赖保留**（②的 round-trip 写入仍需要）；`safety.py` / `status.py` 中对 `.toml` 后缀的处理分支保留（服务的是②）。真正变化的只有①的读入路径与①的生成路径。

### 2.2 源码影响面（逐文件）

#### `src/acm/config.py` —— 核心改动点

| 位置 | 现状 | 动作 |
|---|---|---|
| L2 模块 docstring | `"""Core configuration data models and parser for ~/.acm/config.toml."""` | 改为 `config.yaml` |
| L7 | `import tomlkit` | 替换为 `from ruamel.yaml import YAML` 及 `from ruamel.yaml.error import YAMLError` |
| L82 `CoreConfig` docstring | "Top-level Core Config representation for ~/.acm/config.toml." | 改为 `config.yaml` |
| L96–99 `validate_version` 错误消息 | "...adjust version in ~/.acm/config.toml." | 改为 `config.yaml` |
| L176–186 `parse_config_toml(content)` | `dict(tomlkit.parse(content))` + 异常映射 `"Failed to parse TOML syntax"` | **整体替换**为 `parse_config_yaml(content)`：ruamel safe 加载 + 空/非映射根的友好报错 + `YAMLError`→`ConfigError("Failed to parse YAML syntax: ...")`。参考实现见附录 A |
| L189–199 `load_config(path)` | 读文件后调 `parse_config_toml` | 函数签名与逻辑不变；内部调用改名后的解析函数 |
| 其余全部模型类与校验器 | `ProviderConfig` / `ModelCapabilities` / `ModelReasoning` / `ModelConfig` / `ProfileConfig` / `CoreConfig` 及全部 cross-reference 校验 | **零改动**（数据模型与格式无关） |

#### `src/acm/vmr.py` —— 生成器改动点

| 位置 | 现状 | 动作 |
|---|---|---|
| L96 `probe_vmr` 第三级回退 | `(vmr_home / "config.toml").exists()` | **不改**（③，VMR 自有文件），并留注释防误清 |
| L104–148 `generate_vmr_proposal(probe)` | 手拼 TOML 行；模型键做了 TOML 特有的净化（`.`/`/` → `-` 以避免表嵌套），带引号包裹 | 重写为 YAML 行拼装：`version: 1` / `providers:` / `models:` / `profiles:` 结构；所有标量值经 `_q()` helper 双引号化（json.dumps 兼容转义）；**取消 TOML 式键名净化**——YAML 映射键允许包含 `.` 与 `/`（如 `gpt-4o`、`anthropic/claude-3.5` 直接作为键） |
| L150–175 `generate_template_config()` | 返回注释齐全的 TOML 模板字符串 | 重写为等价 YAML 模板（全文见 §3 D3），注释保留中文段落分隔符风格 |
| 两函数 docstring | "valid config.toml" / "commented template config.toml" | 改为 config.yaml 措辞 |

#### `src/acm/cli.py` —— 引用点改动（共 8 处命中）

| 位置 | 现状 | 动作 |
|---|---|---|
| L54 `init_cmd` docstring | "generate ~/.acm/config.toml" | 改措辞 |
| L57 | `config_file = acm_home / "config.toml"` | 改用 `util.get_config_path()`（D6）。文件缺失时维持既有 `"Run 'acm init' first"` 路径，无任何 legacy 分支（D5） |
| L90–92 提案校验 | 局部导入 `parse_config_toml` 校验提案 | 改调 `parse_config_yaml` |
| L99 提案展示横幅 | `"── Proposed ~/.acm/config.toml ──..."` | 改为 `config.yaml` |
| L125 临时文件名 | `f"config.toml.{os.getpid()}.acm_tmp"` | 改为 `f"config.yaml.{os.getpid()}.acm_tmp"`（0600 权限逻辑不变） |
| L165 `status_cmd` | `config_file = acm_home / "config.toml"` | 同 L57 |
| L229 `use_cmd` | 同上 | 同上 |

#### `src/acm/util.py` —— 小增量

| 位置 | 动作 |
|---|---|
| 模块级常量 | 新增 `CONFIG_FILENAME = "config.yaml"` |
| 新函数 | `get_config_path(env=None) -> Path`：`get_acm_home(env) / CONFIG_FILENAME`。消除 cli.py 三处内联文件名（单一事实源原则同样适用于我们自己的代码） |

### 2.3 明确不受影响的组件及理由

#### 明确不需要改的源码（防误伤清单）

| 文件 | 为什么不改 |
|---|---|
| `adapters/codex.py`（6 处 config.toml 命中） | 目标文件就是 `~/.codex/config.toml`（②），警告文案中的 "in config.toml" 指 Codex 文件 |
| `adapters/claude_code.py`、`adapters/pi.py` | 与 ACM 配置格式无关 |
| `adapters/__init__.py`、`projection.py`、`resolve.py` | 操作 `ResolvedProfile`，格式无关 |
| `safety.py` | `.toml` 分支服务于 Agent 端文件（②）；ACM SSOT 从不经 Safety Engine 写出（init 直写除外） |
| `status.py` | `.suffix == ".toml"` 语法检查同样是 Agent 端文件（②） |
| `writers/toml_editor.py`、`writers/json_editor.py`、`writers/tree_diff.py`、`writers/__init__.py` | 全部是 Agent 端写入器 |
| `state.py`、`lock.py`、`masking.py`、`errors.py`、`output.py`、`main.py` | 格式无关 |

### 2.4 测试影响面（逐文件）

> 判定规则：凡构造/断言 **① ACM SSOT 内容**的测试需要改造；凡涉及 **② Codex 文件**的引用保持不动。

**需要内容转换（→ YAML 字符串）：**

| 文件 | 引用数 | 说明 |
|---|---|---|
| `tests/conftest.py` | 4 | `make_config` fixture 改写 `config.yaml`；`sample_config_toml` fixture 更名为 `sample_config_yaml` 并转为 YAML 内容 |
| `tests/unit/test_config.py` | 26 | 全文件转换；导入改名 `parse_config_yaml`；`test_load_config_file_success` 的文件名改 `config.yaml` |
| `tests/unit/test_resolve.py` | 18 | 各用例内联配置转 YAML |
| `tests/unit/test_vmr.py` | 4 | `test_generate_vmr_proposal_is_valid_toml` / `test_generate_template_config_is_valid_toml` 更名为 `*_is_valid_yaml` 并经新解析器断言；dotted/命名空间模型 id 用例改按 YAML 键规则断言（键保留原名且加引号） |
| `tests/integration/test_cli_use.py` | 14 | `make_config(...)` 内容参数转 YAML |
| `tests/integration/test_cli_rollback.py` | 8 | 同上 |
| `tests/integration/test_exit_codes.py` | 6 | 同上 |
| `tests/integration/test_cli_codex.py` | 4 | 其中指向 `.acm` 配置的部分转换；`~/.codex/config.toml` 相关保持 |
| `tests/integration/test_cli_status.py` | 3 | 转换 |
| `tests/integration/test_cli_init.py` | 3 | 断言路径改 `config.yaml`；dry-run 断言 `not (.../config.yaml).exists()` |
| `tests/integration/test_cli_pi.py` | 2 | 转换 |
| `tests/integration/test_cli_claude.py` | 2 | 转换 |
| `tests/integration/test_e2e_acceptance.py` | 3 | 仅 L198 一处是 `.acm` SSOT（ENV 缺失验收用例），转 YAML；L46/L116 是 Codex 文件，不动 |
| `tests/unit/test_version.py` | — | `assert __version__ == "0.1.0"` → `"0.2.0"`（随 T8 版本对齐） |

**确认不需改动（引用均属②）：**

| 文件 | 说明 |
|---|---|
| `tests/golden/test_adapters_codex.py`（2 处） | `codex_dir / "config.toml"` 与快照内文件名——全是 Codex 侧 |
| `tests/fault/test_sigkill.py`（1 处） | 孤儿临时文件模拟的是 Codex 侧 `config.toml.8888.acm_tmp` |
| `tests/golden/test_adapters_pi.py`、`test_adapters_claude.py`、`test_adapters_pool_only.py` | 直接构造 `ResolvedProfile`，不经文本解析 |
| `tests/unit/test_writers_*`、`test_masking.py`、`test_projection.py`、`test_status.py`、`test_main.py` | 格式无关 |
| `tests/fixtures/codex/config.golden.toml` | **金样夹具，属②，一字不动**（它同时是上游 schema 漂移哨兵） |

### 2.5 文档影响面（逐文件）

> 方针见 D8：活文档全量改写为 YAML 表述，不留变更注记。

| 文件 | 命中情况 | 处理 |
|---|---|---|
| `CLAUDE.md` | SSOT 公理（L15）、数据流（L38）、状态分离铁律（L59）、Schema Essentials（`[profiles.*]` 记法）、目录树 writers 注释（保留） | 全面更新为 YAML 表述 |
| `README.md` / `README.zh.md` | SSOT 特性行、核心配置示例节（各 1 个 ```toml 块）、文档表中 Codex 路径（保留） | 示例块与措辞全面转 YAML |
| `docs/USER_GUIDE.md` / `USER_GUIDE.zh.md` | 各 34 处、各 9 个 ```toml 块（§5 整章为配置参考，另有 §3/§4/§6/§8/§10–§12/附录散布） | 整篇全量改写：所有示例、错误消息对照、布局树、recipes、FAQ 均呈 YAML 现实 |
| `docs/ACM_PROJECT_PRINCIPLE_v2.1.md` | L82 技术栈基线、L122 数据流图、L160 状态分离、L188/L202 命令语义、L246/L251 触发表（L70/L236 等 industry/Codex 语境保留） | 相关行全量改为 YAML 表述 |
| `docs/ACM_PROJECT_SPEC_v2.1.md` | §6 D3 整节、§6 竞品对照表 L914、采纳表 L974、§7.3 整节、§10 release 语义 L538、§10.7 布局树 L613/L626、触发式升级 L677/L688、init 流程注释（Codex 侧 L180/L259/L561/L639 保留） | 相关节全量改为 YAML 表述，D3 直接以 YAML 决策陈述 |
| `docs/DESIGN_MODEL_POOL_v1.md` | 约 10 处正文提及 + 3 个 ```toml 示例块（L104–106 为 Codex 侧，保留） | 正文与示例全量转为 YAML 表述 |
| `docs/ACM_MVP_ACTION_PLAN_v1.0.md`、`docs/ACM_CONFIG_MANAGEMENT_DEEP_DIVE_AND_BEST_PRACTICES.md`、`docs/agent_config_manager_deep_analysis.md`、`docs/agent_config_manager_evaluation_v1.0_custom-2-agent.md` | 合计约 63 处 | **冻结不改**。四份均为标注日期的前期研报/过程稿，内容大量引用上游 Agent 真实文件格式与行业案例，不属于描述当前系统的活文档；README 文档表中的链接以"历史研报/MVP 执行方案"身份保留 |

### 2.6 构建/发布影响面

| 项 | 动作 |
|---|---|
| `pyproject.toml` | `dependencies` 增加 `ruamel.yaml>=0.18`；`version` 升 `0.2.0` |
| `uv.lock` | `uv sync` 后随动（CI 有 lock 漂移检查） |
| `src/acm/__init__.py` | `__version__` 升 `0.2.0`（顺带修复与 pyproject 0.1.2 的既有不一致） |
| GitHub Actions（release.yml） | 无需改动（Trusted Publishing 流程与格式无关） |

---

## 3. 方案设计与关键决策

### D1 迁移范围与投影纪律

范围（§2.1 三分法）：仅 `~/.acm/config.yaml`（原 `config.toml`）的格式与读写路径；三条边界：

1. 不碰任何 Agent 端文件格式与其处理代码；
2. 不碰 `~/.vmr/config.toml` 探测回退；
3. `tomlkit` 不从依赖中移除（Codex 适配器硬依赖）。

**投影纪律**：本次是 ACM 内部实现迁移，不是一次配置变更。数据模型零变化意味着：对同一份语义内容，迁移前后推导出的期望投影完全一致，已投影的 Agent 文件与状态（last_write.json、snapshots）无需也不应被触碰。具体约束：

- 实施过程中**禁止**对本机真实环境执行 `acm use` / `acm apply` 类投影操作；
- 全部验证在 conftest 隔离的 fake HOME 中进行（既有机制保证）；
- 迁移合入后，用户（含开发者本人环境）如需让 Agent 跟进任何配置调整，走正常的人工 `status` 查看 → 分析 → 手动 `use` 流程，ACM 不提供也不会自动执行任何"迁移后批量重投影"。

### D2 YAML 解析库选型：ruamel.yaml（safe 模式）

**候选对比（含本机实测记录）：**

| 维度 | PyYAML（`safe_load`） | ruamel.yaml（`YAML(typ="safe")`） |
|---|---|---|
| YAML 规范代际 | 1.1：`yes/no/on/off` 隐式转布尔（"挪威问题"），键 `no:` 会变成 `{False: 'x'}`（实测复现） | **1.2**：`on`/`no` 保持字符串，仅 `true/false` 为布尔（实测复现）✅ |
| 重复键处理 | **静默后者覆盖前者**（实测复现，数据丢失风险） | **抛 `DuplicateKeyError`**（实测复现）✅ |
| 凭据引用解析 | `${VAR}` 可解析 | 同样可解析（实测复现） |
| 多文档拒绝 | ComposerError ✅ | ComposerError ✅ |
| 注释保留 round-trip（未来 import vmr 需要） | ❌ 无此能力 | ✅ `typ="rt"` 模式原生支持 |
| 类型标注/mypy strict | 一般 | 通过（`--strict` 实测通过；`load` 返回 Any，交 pydantic 收敛） |
| 生态熟悉度 | 最高 | 高（round-trip 事实标准；README 的 writers 描述已预告该依赖） |

**决策：采用 `ruamel.yaml>=0.18`，只用 `typ="safe"` 纯数据加载模式。**

理由链：

1. **两大陷阱免费消解**：若用 PyYAML，必须自写自定义 Loader（去布尔 resolver + 重复键检测约 30–40 行样板并配测试）；ruamel safe 模式开箱即是正确行为，符合"最小自研面"原则；
2. **依赖经济性**：SPEC D2 本就为 P1 阶段（Aider 等 YAML 目标 Agent）预算了 ruamel.yaml；现在引入即提前兑现该预算，避免先引 PyYAML 再叠 ruamel 造成双 YAML 库长期共存；
3. **为触发式升级铺路**：`import vmr`（增量合并、需保注释）一旦触发，同一依赖切到 `typ="rt"` 即可，无二次换库成本；
4. 代价（如实陈述）：比 PyYAML 略重的安装体积；API 略繁——但我们只用了 `YAML(typ="safe").load()` 一个入口，封装在单个函数内，复杂度不外泄。

**加载行为契约**（成为测试断言依据）：

| 输入 | 行为 |
|---|---|
| 合法映射文档 | 返回 `dict`，交 `CoreConfig.model_validate` |
| 空文件 / 仅注释 | `load` 返回 `None` → `ConfigError("Config file is empty or contains no YAML mapping.")` |
| 根为数组/标量 | 非 dict → `ConfigError`（明确指出根必须是 mapping） |
| 语法错误 | `YAMLError` 子类 → `ConfigError("Failed to parse YAML syntax: ...")`，exit 1 |
| 重复键 | `DuplicateKeyError` → 同上（fail-fast，杜绝静默丢字段） |
| 多文档（`---` 分隔） | ComposerError → 同上 |
| 锚点/别名/merge key（`<<`） | **允许**（ruamel 安全展开，实测复现），USER_GUIDE 标注"支持但不鼓励"，并有一个钉住行为的测试 |
| Tab 缩进 | ParserError → 正常报错路径 |
| `${VAR}` / `${VAR:-default}` | 原样字符串，后续走 `resolve.py` 既有逻辑（零改动） |

### D3 目标 YAML 格式规格

**格式总则**：

- 块风格（block style），2 空格缩进；顶层键序固定为 `version` → `providers` → `models` → `profiles`（生成器保证；手写顺序自由）；
- 所有凭据引用值**必须双引号包裹**（如 `api_key: "${ANTHROPIC_API_KEY}"`）——技术上 `${VAR}` 不加引号也能解析（`$` 非指示符字符，已实测），但强制引号消除一切边角疑虑并提升 grep 可见性；文档与生成器统一执行；
- 含 `": "` 序列、前导指示符字符（`` {[*&!|>'"%@` ``）、前后空白的标量一律加引号；生成器对所有标量统一 json.dumps 式双引号化，手写文档按需；
- 键名允许包含 `.` `/` `-`（YAML 映射键是普通字符串）——VMR 模型 id 不再需要净化改名。

**a) `acm init --force` 无 VMR 时生成的模板：**

```yaml
version: 1

# ── L1 供应商：端点与凭据引用 ──────────────────────────
providers:
  anthropic-direct:
    protocol: anthropic          # openai | anthropic | openai-responses
    base_url: https://api.anthropic.com
    api_key: "${ANTHROPIC_API_KEY}"   # 整字段引用环境变量，零密钥明文入库

  openai-direct:
    protocol: openai
    base_url: https://api.openai.com/v1
    api_key: "${OPENAI_API_KEY}"

# ── L2 模型：规格、行为与能力 ──────────────────────────
models:
  claude-sonnet:
    provider: anthropic-direct
    id: claude-3-7-sonnet-20250219
    context_window: 200000
    max_output_tokens: 8192
    temperature: 0.2             # 缺省 = 不写入，用 Agent 默认
    reasoning:
      effort: high               # low | medium | high

  gpt-4o:
    provider: openai-direct
    id: gpt-4o
    context_window: 128000
    max_output_tokens: 4096

# ── L3 Profile：命名的角色组合 ─────────────────────────
profiles:
  daily:
    main: claude-sonnet
    cheap: gpt-4o
```

**b) VMR 探测命中时的提案：**

```yaml
version: 1

# ── L1 供应商：端点与凭据引用 ──────────────────────────
providers:
  vmr:
    protocol: "openai"
    base_url: "http://127.0.0.1:8800/v1"
    api_key: "${VMR_KEY:-}"   # 本地 VMR 无鉴权可留空，如需鉴权可 export VMR_KEY

# ── L2 模型：规格、行为与能力 ──────────────────────────
models:
  "coding":
    provider: vmr
    id: "coding"

# ── L3 Profile：命名的角色组合 ─────────────────────────
profiles:
  daily:
    main: "coding"
```

（探测到的每个模型一个键；生成器对全部标量统一双引号化。）

**c) pool 写法示例：**

```yaml
profiles:
  reg:
    pool:
      fast: a
      coder: b
```

**d) 手写规范要点（写入 USER_GUIDE §5）**：布尔用 `true/false`（统一风格避免混淆）；数字不加引号；模型别名含特殊字符时可整体加引号；不支持在一个文件里写多个 `---` 文档。

### D4 schema version 保持 1 不变

`version` 字段语义是 **config schema（数据模型）版本**，本次只是序列化格式更换，数据模型零变化，故维持 `1`。文件扩展名本身已无歧义地标识了格式，不存在"同 version 两种格式无法区分解析器"的问题。`validate_version` 中错误消息里的文件路径字样同步更新。

### D5 直接切换：无存量迁移路径

项目处于起步期，不存在需要照拂的存量安装：**不提供迁移命令、不做旧格式检测、不写迁移指引**。行为定义简单完备：

- ACM 所有命令只读 `~/.acm/config.yaml`；
- 该文件缺失 = 未初始化，走既有的 `ConfigError("Config file not found at ... Run 'acm init' first.")`（exit 1）；
- 磁盘上若残留其他文件（包括旧名文件），ACM 不读取、不检测、不告警——它不是 ACM 的输入。

配套约束：

- `acm init` / `init --force` 是获得合法 `config.yaml` 的唯一入口（模板/提案见 D3）；
- 不因本次内部迁移触发任何 Agent 重投影（见 D1 投影纪律）；
- 测试体系不包含旧格式相关用例（不为其保留任何代码路径）。

### D6 附带小重构：配置路径集中化

现状 `cli.py` 三处内联 `acm_home / "config.toml"` 是文件名的散布。借迁移之机收敛：

- `util.py` 新增 `CONFIG_FILENAME` 常量与 `get_config_path(env)`；
- `cli.py` 三处改调 `get_config_path()`；
- 未来任何"路径再变更"（理论上不会有）只动一处。

此重构控制在 15 行以内，不引入抽象层。

### D7 版本号与发布策略

- 版本：`0.2.0`；
- `src/acm/__init__.py::__version__` 与 pyproject 对齐为 `0.2.0`（同时修复既有 0.1.0/0.1.2 不一致），`tests/unit/test_version.py` 断言同步更新；
- 发布渠道照旧：打 `v0.2.0` tag → GitHub Actions 构建 + PyPI Trusted Publishing；
- PyPI 项目描述随 README 更新自动携带新示例。

### D8 文档一致性原则：全量反映现状，拒绝补丁式批注

所有描述当前系统的活文档（README ×2、CLAUDE.md、USER_GUIDE ×2、PRINCIPLE、SPEC、DESIGN_MODEL_POOL）**全量改写**：每一处配置示例、路径引用、术语、错误消息对照都以 `config.yaml` / YAML 语法呈现，使读者在任何一页看到的都是"系统本来如此"。具体纪律：

1. **禁止变更注记**：不写"TOML→YAML""v2.2 变更""自 0.2.0 起"之类的过渡叙述、脚注、批注或新旧对照；
2. **禁止残迹**：活文档正文中不允许出现"ACM 自身配置曾用/可用 TOML"的表述；允许保留的 TOML 字样仅限三类语境——(a) Codex 自有文件 `~/.codex/config.toml` 及其 tomlkit 写入器描述；(b) `~/.vmr/config.toml`（VMR 项目自有文件）；(c) 泛指行业配置格式的技术论述（如语言/依赖选型对比）；
3. **历史档案不动**：四份前期研报/过程稿（§2.5 末行）保持原样——它们是带日期的史料而非现状描述，其中的上游 Agent 文件格式引用本身也是事实记录；
4. 治理文档（PRINCIPLE/SPEC）中被修订的小节（如 SPEC §6 D3）直接以最终决策内容呈现，原论证若仍有价值则以"选型理由"的形式融入新表述，而非"否决记录"的形式留存。

---

## 4. Action Plan（任务分解）

> 执行顺序即编号顺序；每个 Task 内部步骤即提交粒度建议。全程质量门禁：Task 4/5 结束、Task 6 结束、Task 8 结束各跑一轮全量 `uv run pytest` + `uv run ruff check .` + `uv run mypy src`。

### Task 1 依赖与解析层改造

**文件：`pyproject.toml`、`uv.lock`、`src/acm/util.py`、`src/acm/config.py`**

1. `pyproject.toml`：dependencies 增加 `"ruamel.yaml>=0.18"`；运行 `uv sync` 固定 lock。
2. `src/acm/util.py`：
   - 新增 `CONFIG_FILENAME = "config.yaml"`；
   - 新增 `get_config_path(env: Mapping[str, str] | None = None) -> Path`。
3. `src/acm/config.py`：
   - 移除 `import tomlkit`；新增 ruamel 导入；
   - `parse_config_toml` → `parse_config_yaml`（实现骨架见附录 A）：
     - 创建 `YAML(typ="safe")` 实例并 `load`；
     - `None` 结果 → `ConfigError("Config file is empty or contains no YAML mapping.")`；
     - 非 dict 根 → `ConfigError("Config root must be a mapping (key: value structure), got <type>.")`；
     - `YAMLError`（含 DuplicateKeyError/ParserError/ComposerError）→ `ConfigError(f"Failed to parse YAML syntax: {e}")`；
     - 成功 → `CoreConfig.model_validate(data)`，异常映射沿用 `"Invalid config structure: {e}"`；
   - 模块/docstring/版本错误消息中的路径字样更新为 `config.yaml`；
   - **不新增**任何旧格式检测函数（D5）。
4. 验收：与 Task 4 连续完成后 `uv run pytest tests/unit/test_config.py tests/unit/test_resolve.py` 绿。

> ⚠️ 执行提示：Task 1 改完解析层后，存量单测会大面积红——这是预期中间态。Task 1 与 Task 4 的 conftest 部分连续完成后再首次跑闸。

### Task 2 提案/模板生成器改造

**文件：`src/acm/vmr.py`**

1. 新增模块私有 `_q(value: Any) -> str` helper：`json.dumps(str(value))` 产出 YAML 安全的双引号标量（JSON 字符串转义是 YAML 双引号风格的合法子集）。
2. 重写 `generate_template_config() -> str`：返回 §3 D3-a 的 YAML 模板（保留中文分隔注释；缩进 2 空格）。
3. 重写 `generate_vmr_proposal(probe) -> str`：
   - 结构按 §3 D3-b；
   - **删除 TOML 式 `safe_name` 净化逻辑**（`.`、`/` 不再替换），键与标量统一 `_q()` 包裹；
   - 保留既有语义：`coding` 优先为主模型、`cheap` 存在时设为 cheap 角色、枚举失败时的占位模型与注释；
   - docstring 更新。
4. `probe_vmr` 的 `~/.vmr/config.toml` 回退分支：**明确不动**，并在代码旁留一行注释说明该文件属 VMR 项目格式，防止未来被误清理。
5. 验收：`tests/unit/test_vmr.py`（Task 4 转换后）全绿；生成的两份产物能通过 `parse_config_yaml` 往返校验（已有测试模式覆盖）。

### Task 3 CLI 改造

**文件：`src/acm/cli.py`**

1. `init_cmd`：
   - `config_file = get_config_path()`；
   - 提案校验改 `parse_config_yaml`；
   - 横幅文案、临时文件名（保持 0600 chmod 逻辑）、docstring 更新；
   - 缺失文件时的报错维持既有文案模式（路径来自变量，自然变为 config.yaml）。
2. `status_cmd` / `use_cmd`：同样替换路径获取方式；报错文案中的路径随之变化。
3. 确认 `rollback_cmd` 不读 ACM 配置（现状确实不读），无需改动。
4. 验收：`uv run pytest tests/integration/test_cli_init.py`（Task 4 后）全绿；隔离 HOME 下 `acm init --dry-run` 输出 YAML 提案。

### Task 4 存量测试改造

**文件：见 §2.4 表格**

1. `tests/conftest.py`：
   - `make_config` 写 `acm_dir / "config.yaml"`（docstring 同步）；
   - `sample_config_toml` → `sample_config_yaml`，内容按 D3 规范翻译（注意 `api_key: "${VMR_KEY:-sk-test-mock-key}"` 的引号）；
   - 全仓 `sample_config_toml` 引用点（多个集成测试的 fixture 参数名）同步改名。
2. 逐文件把内联配置字符串翻译为 YAML（机械翻译规则：`[a.b.c]` 表头 → 嵌套缩进；`key = "v"` → `key: v` 或引号形式；池子表 → `pool:` 子键）。
3. `tests/unit/test_config.py`：导入与调用改 `parse_config_yaml`；`test_load_config_file_success` 文件名改 `config.yaml`；`POOL_ONLY_TOML` 常量更名为 `POOL_ONLY_YAML`。
4. `tests/unit/test_vmr.py`：两个 `*_is_valid_toml` 用例更名 `*_is_valid_yaml`，断言经 `parse_config_yaml`；dotted-id 用例断言键保留原名（如 `anthropic/claude-3.5` 不被改名）且解析正确。
5. `tests/golden/*`、`tests/fault/*`：核对无 ①类引用后**不动**（golden codex 夹具是漂移哨兵，禁改）。
6. 验收：全量 `uv run pytest` 绿。

### Task 5 新增测试

**文件：新建 `tests/unit/test_yaml_loader.py`；`tests/integration/test_cli_init.py`（续）**

1. **YAML 加载行为契约组（全部为本机已实测行为的回归钉）**：
   - `test_duplicate_keys_rejected`：providers 下同名两键 → `ConfigError` 且消息含 "Failed to parse YAML"；
   - `test_on_off_yes_no_are_plain_strings`：`id: on`、键 `no:` 不发生布尔化（YAML 1.2 语义）；
   - `test_true_false_still_boolean`：`vision: true` → pydantic bool 正常；
   - `test_credential_ref_unquoted_parses` / `test_credential_ref_default_syntax`：`${VAR}`、`${VAR:-default}` 原样字符串；
   - `test_multi_document_rejected`：`---` 双文档 → ConfigError；
   - `test_empty_file_friendly_error` / `test_comment_only_file_friendly_error`；
   - `test_non_mapping_root_rejected`：根为数组 → ConfigError；
   - `test_tab_indentation_reports_syntax_error`；
   - `test_merge_keys_allowed_and_resolved`：锚点 + `<<` 展开（钉住"允许但文档标注不鼓励"的决策）；
   - `test_dotted_and_slashed_model_keys_preserved`：键 `gpt-4o.2`、`anthropic/claude-3.5` 原样保留。
2. **init 行为补强（并入 `test_cli_init.py`）**：
   - `test_init_writes_config_yaml_with_0600`：权限断言（沿用现有 chmod 逻辑，钉住新文件名）；
   - `test_init_proposal_banner_mentions_yaml`：横幅含 `config.yaml`。
3. **生成器补强**：
   - dotted/slash 模型 id 经提案往返后键名保真（扩展现有 validity 测试即可）。
4. 验收：新增用例全绿；`@pytest.mark.golden` / `fault` / `e2e` 标记分布不变。

### Task 6 文档全量同步

> 方针：D8。每个文档改完后自查：通读无过渡叙述、无新旧对照、示例可直接照抄运行。

1. `docs/ACM_PROJECT_PRINCIPLE_v2.1.md`：L82 技术栈基线句改为 "Core Config 用 YAML"；L122 数据流图路径 `~/.acm/config.yaml`；L160 状态分离铁律指向 `config.yaml`；L188 init 命令注释；L202 import vmr 合并目标；L246/L251 触发表措辞；头部 Date 刷新为 2026-08-26（不添加变更叙事）。保留：L70/L236 等行业语境与 Codex 写入器描述。
2. `docs/ACM_PROJECT_SPEC_v2.1.md`：§6 D3 整节改写为 "Core Config = ACM 自有的模型世界 SSOT，格式 YAML"（所有权声明保留；选型理由以正面论述呈现：层级清晰、键名字符宽裕、ruamel 1.2 语义安全、依赖与 P1 预算合流；"配置与状态的边界"段落路径字样更新）；§6 对照表 L914 行改为体现 YAML 结论；采纳表相应行核对；§7.3 整节示例与文字 YAML 化；L15/L538 release 语义路径字样；§10.7 布局树 L613 与 gitignore 段 L626；触发式升级 L677/L688 措辞；头部 Date 刷新。保留：Codex 侧 L180/L259/L561/L639、行业语境 L70/L192。
3. `docs/USER_GUIDE.md`：
   - §3.1/§3.6/§3.9 概念与示例；
   - **§5 整章**：标题路径、§5.1–§5.5 全部字段示例、§5.6 四个完整示例（a/b/c/d）、§5.7 错误消息对照表（更新为 YAML 专属错误行：duplicate key / empty file / multi-doc / tab indent）；
   - §4 Quick Start 产物示例；§6.1 init 流程文案（横幅、写入文件清单）、§6.5 exit code 表（区分 ACM 配置错误与 Agent 文件损坏语境的措辞核对）;
   - §8 提案示例与 "hand-edit" 措辞；§9.6/§10.1 布局树；§11 recipes；§12 FAQ（含凭据存放等）；Appendix A/B;
   - 通读确认无迁移类内容、无过渡叙述。
4. `docs/USER_GUIDE.zh.md`：与英文版逐节镜像同步。
5. `README.md` / `README.zh.md`：SSOT 特性行路径、核心配置示例块（```yaml）、相关措辞；保留 Codex 路径/writers 描述。
6. `CLAUDE.md`：SSOT 公理（L15）、数据流（L38）、状态分离铁律（L59）、Config Schema Essentials 记法（`version = 1`、`profiles.*` YAML 化）；目录树 writers 注释保留；Implementation Status 补一行 pool/init 相关现状核对（如有必要）。
7. `docs/DESIGN_MODEL_POOL_v1.md`：正文约 10 处提及与 3 个 ```toml 示例块全量 YAML 化（L104–106 Codex 侧保留）；语义内容一字不改，只换表述载体。
8. 四份历史档案：**不动**。
9. 验收：全仓 `grep -rn "config\.toml" --include="*.md"`（排除 docs/ 四档案）剩余命中逐条归类，必须全部属于 §2.5/D8 允许的三类语境；`grep -rn '```toml'` 在活文档中为 0。

### Task 7 旧代码与遗留逻辑清理

1. `src/acm/config.py`：确认 `tomlkit` 导入与 `parse_config_toml` 无残留（函数体已被替换，不留兼容 shim——直接切换，不做 deprecated 别名）。
2. `src/acm/cli.py`：确认无 `from acm.config import parse_config_toml` 残留。
3. 全仓源码 `grep -rn "parse_config_toml\|sample_config_toml\|POOL_ONLY_TOML" src/ tests/` 应为 0 命中。
4. `grep -n "config\.toml" src/acm/*.py` 剩余命中核对：仅 `adapters/codex.py`（②）、`vmr.py` 的 `~/.vmr/config.toml` 回退（③）及其防护注释。
5. `src/acm/writers/__init__.py`：`TOML_CAPABILITIES` **保留**（描述 Codex 写入器，语义未变）。
6. 确认无死代码产生：`get_config_path` 被 CLI 三处消费；无未被引用的新增符号。
7. 清理 `__pycache__` 陈旧字节码不影响正确性（pytest 自动重编译），无需手工干预。

### Task 8 版本发布收尾

1. `pyproject.toml` `version = "0.2.0"`；`src/acm/__init__.py` `__version__ = "0.2.0"`；`tests/unit/test_version.py` 断言更新为 `"0.2.0"`。
2. 全量门禁：`uv sync && uv run pytest && uv run ruff check . && uv run mypy src`。
3. 本机冒烟（严格使用一次性临时 HOME，不触碰真实环境）：
   - `HOME=$(mktemp -d) uv run acm init --dry-run`（观察 YAML 提案与横幅）;
   - 去 dry-run 完成 init → 检查生成的 `config.yaml` 内容与权限（600）→ `acm status` → `acm rollback`;
   - 确认全程无任何对真实 `~/.codex`、`~/.claude` 等目录的写入。
4. Git：功能分支单提交序列（建议按 Task 分 commit）；合并后打 `v0.2.0` tag 触发发布流水线。（是否立即发布 tag 由项目所有者决定，默认仅合并不打 tag。）

### Task 9 最终复核（收尾门禁）

> 以下 checklist 逐项打勾后方可关闭本次工作。复核时应假设"前面每一步都可能出错"，一切以实际代码与实际输出为准。

**A. 代码残留扫描**
- [ ] `grep -rn "parse_config_toml" src/ tests/` = 0 命中
- [ ] `grep -rn "config\.toml" src/acm/` 剩余命中逐条核对：仅允许 `adapters/codex.py`（②）、`vmr.py` 的 `~/.vmr/config.toml` 回退（③）及防护注释
- [ ] `pyproject.toml` 中 `tomlkit` 仍在 dependencies（不该被顺手删掉）
- [ ] `ruamel.yaml` 出现在 dependencies 且 `uv.lock` 同步（无 lock 漂移告警）

**B. 行为一致性抽查**
- [ ] 六状态机语义不变：任取一个 DRIFTED / ERROR / SYNCED 场景的手工复演
- [ ] 退出码矩阵回归：`test_exit_codes.py` 全绿且未弱化断言
- [ ] 幂等 no-op、漂移阻断 `--force`、白名单拦截、ENV 缺失零写盘四条安全底线用例全绿
- [ ] SIGKILL 故障注入与锁竞争用例全绿（证明 Safety Engine 未被波及）

**C. 新格式专项**
- [ ] 生成的模板与 VMR 提案均可被 `parse_config_yaml` 往返，且注释/键序符合 D3 总则
- [ ] D2 行为契约表逐行对应至少一个测试（Task 5 第 1 组）
- [ ] 手工验证一份"故意恶劣"的手写 YAML（tab、重复键、`on` 作值、多文档）的错误消息都可读、指错位置准确
- [ ] `acm status` 对"只有 config.yaml"的正常机器输出 NOT_DETECTED/提示 init，无任何 legacy 相关分支被触发

**D. 文档一致性**
- [ ] 活文档（README×2、CLAUDE.md、USER_GUIDE×2、PRINCIPLE、SPEC、DESIGN_MODEL_POOL）通读抽查 ≥10 处语境正确
- [ ] 活文档中 ```toml 代码块数量为 0
- [ ] 活文档 "config.toml/TOML" 剩余命中逐条归类：(a) Codex 文件 (b) VMR 文件 (c) 行业泛指——无第 (d) 类
- [ ] 四份历史档案 diff 为空

**E. 测试资产完整性**
- [ ] golden 夹具目录 diff 为空：`git diff --stat tests/fixtures/` 应无输出（Codex 金样哨兵未被误动）
- [ ] pytest markers 分布不变：golden/fault/e2e 计数与迁移前一致（新增用例不误挂标记）
- [ ] conftest 的隔离性未破坏：fake HOME / PATH 剥离 / VMR 死端口三项照旧

**F. 投影纪律与端到端演练（全部在隔离 HOME 中）**
- [ ] 实施期间无任何对真实 Agent 目录的写入（`git status` 干净 + 冒烟用临时 HOME 双重保证）
- [ ] 全新机器路径：init → use daily → status 全程 ≤ 3 条命令、零手工编辑（MVP 硬验收标准 #1 在新格式下复验）
- [ ] fake_vmr_server 场景：init 提案包含全部探测模型且键名保留原始 id 字符

复核结论记录于附录 C。

---

## 5. 风险登记表

| # | 风险 | 概率 | 影响 | 缓解措施 |
|---|---|---|---|---|
| R1 | 用户手写 YAML 时凭据引用忘加引号导致解析歧义 | 中 | 低 | `${VAR}` 起始值实测可安全解析；文档强制引号规范；生成器统一引号化示范 |
| R2 | ruamel.yaml 引入新的传递依赖或平台问题 | 低 | 低 | 纯 Python 包、零硬传递依赖；uv lock 锁定；macOS/Linux CI 实测 |
| R3 | 治理文档改写在去除旧表述时误伤规范性语义 | 中 | 高 | 改写仅限格式载体与路径字样，逐节 diff review；Task 9-D 通读门禁；原则类语句改动需逐字核对 |
| R4 | 测试翻译引入语义漂移（机械转换错漏） | 中 | 中 | 转换后逐用例比对断言目标不变；全量回归 + e2e 验收兜底；review 时重点看 fixture 内容而非测试逻辑 |
| R5 | YAML 生态习惯带来的新 Support 负担（锚点滥用、多文档等） | 低 | 低 | 行为契约已定义并有测试钉住；错误消息 fail-fast 且指位准确 |
| R6 | 活文档 TOML 清扫误伤 Codex/VMR 合法引用 | 低 | 中 | Task 9-D 三类语境白名单逐一归类核对，禁止一刀切替换 |
| R7 | 双 YAML 库诱惑（未来有人再引 PyYAML） | 低 | 低 | CLAUDE.md/依赖说明注明 "YAML 统一走 ruamel.yaml"；code review 把关 |
| R8 | init 生成的新格式在极端模型 id（空格、emoji 等）下键名异常 | 低 | 低 | `_q()` 对任意字符串做 JSON 兼容转义，覆盖全部 Unicode；dotted/slash 用例覆盖 |

---

## 6. 整体验收标准

1. **功能等价**：除配置文件名与语法外，所有命令的输入输出行为、退出码、告警文案语义与迁移前完全一致（漂移阻断/投影损失/掩码/幂等逐项复验）。
2. **门禁全绿**：`uv run pytest`（含 e2e/golden/fault）、`uv run ruff check .`、`uv run mypy src` 三闸通过。
3. **新格式健壮性**：Task 5 新增用例全绿，D2 行为契约表全覆盖。
4. **零越界**：Agent 端文件处理代码（adapters/writers/safety/status 的 .toml 分支）diff 为空；golden fixtures diff 为空；实施期间真实环境零写入。
5. **文档纯净**：活文档全量呈现 YAML 现实，无过渡叙述、无补丁批注；Task 9-D 白名单归类通过。
6. **无迁移残留**：源码与测试中不存在旧格式检测、转换工具或迁移用例。

---

## 附录 A：解析层参考实现骨架

> 供执行时直接取用；以实际编码时的 ruff/mypy 结果为准。行为契约见 §3 D2 表格。

```python
# src/acm/config.py （关键片段示意）
from ruamel.yaml import YAML
from ruamel.yaml.error import YAMLError


def parse_config_yaml(content: str) -> CoreConfig:
    """Parse and validate YAML string content into CoreConfig.

    Loader contract (see DESIGN_CONFIG_YAML_MIGRATION_v1.md §3 D2):
    - YAML 1.2 semantics via ruamel safe loader (no yes/no bool coercion)
    - duplicate keys are hard errors (fail-fast, never silently dropped)
    - anchors/merge keys are allowed and resolved
    - multi-document input is rejected
    """
    try:
        data = YAML(typ="safe").load(content)
    except YAMLError as e:
        raise ConfigError(f"Failed to parse YAML syntax: {e}") from e

    if data is None:
        raise ConfigError(
            "Config file is empty or contains no YAML mapping."
        )
    if not isinstance(data, dict):
        raise ConfigError(
            f"Config root must be a mapping (key: value structure), got {type(data).__name__}."
        )

    try:
        return CoreConfig.model_validate(data)
    except Exception as e:
        raise ConfigError(f"Invalid config structure: {e}") from e
```

```python
# src/acm/util.py （新增片段示意）
CONFIG_FILENAME = "config.yaml"


def get_config_path(env: Mapping[str, str] | None = None) -> Path:
    """Return the absolute path of ACM's Core Config file."""
    return get_acm_home(env) / CONFIG_FILENAME
```

```python
# src/acm/vmr.py （_q helper 示意）
import json

def _q(value: Any) -> str:
    """Render a scalar as a YAML-safe double-quoted string.

    JSON string escaping is a valid subset of YAML double-quoted style,
    so json.dumps covers all edge cases (leading indicators, ': ', unicode).
    """
    return json.dumps(str(value))
```

---

## 附录 B：逐文件改动速查表

| 文件 | 改动类型 | 要点 | 所属 Task |
|---|---|---|---|
| `pyproject.toml` | 修改 | +ruamel.yaml>=0.18；version→0.2.0 | T1 / T8 |
| `src/acm/util.py` | 修改 | +CONFIG_FILENAME / get_config_path() | T1 |
| `src/acm/config.py` | 修改 | parse_config_yaml 替换 parse_config_toml；tomlkit 导入移除；docstring/报错文案 | T1 |
| `src/acm/vmr.py` | 修改 | 两生成器重写为 YAML 输出；+_q()；删 TOML 键名净化；~/.vmr 回退不动 | T2 |
| `src/acm/cli.py` | 修改 | 三命令路径集中化 + 文案/临时文件名/横幅 | T3 |
| `src/acm/__init__.py` | 修改 | __version__ → 0.2.0（顺带修复既有不一致） | T8 |
| `src/acm/adapters/*`、`projection.py`、`resolve.py`、`safety.py`、`status.py`、`state.py`、`lock.py`、`masking.py`、`errors.py`、`output.py`、`main.py`、`writers/*` | **不动** | 见 §2.3 防误伤清单 | — |
| `tests/conftest.py` | 修改 | make_config→config.yaml；sample_config_yaml 重命名+翻译 | T4 |
| `tests/unit/test_config.py` | 修改+新增 | 全量翻译；导入改名；POOL_ONLY_YAML | T4 |
| `tests/unit/test_yaml_loader.py` | **新建** | D2 行为契约逐项钉死 | T5 |
| `tests/unit/test_resolve.py` | 修改 | 内联配置翻译 | T4 |
| `tests/unit/test_vmr.py` | 修改 | *_is_valid_yaml 更名断言；dotted-id 键名断言 | T4 |
| `tests/integration/test_cli_init.py` | 修改+新增 | 路径断言；+权限/横幅用例 | T4 / T5 |
| `tests/integration/test_cli_use.py` `test_cli_status.py` `test_cli_rollback.py` `test_exit_codes.py` `test_cli_codex.py` `test_cli_pi.py` `test_cli_claude.py` `test_e2e_acceptance.py` | 修改 | make_config 内容翻译；e2e 仅 L198 属①需改 | T4 |
| `tests/unit/test_version.py` | 修改 | 版本断言 → 0.2.0 | T8 |
| `tests/golden/*`、`tests/fault/test_sigkill.py`、`tests/fixtures/codex/config.golden.toml` | **不动** | 全部属②语境；金样哨兵禁改 | — |
| `docs/ACM_PROJECT_PRINCIPLE_v2.1.md` | 修改 | §1.3/数据流图/命令表等相关行 YAML 化 | T6 |
| `docs/ACM_PROJECT_SPEC_v2.1.md` | 修改 | D3 以 YAML 决策陈述；§7.3/布局树/release 语义等 YAML 化 | T6 |
| `docs/USER_GUIDE.md` / `.zh.md` | 修改 | 整篇 YAML 化（含 §5 整章与 §5.6/§5.7） | T6 |
| `README.md` / `README.zh.md` | 修改 | 示例块与 SSOT 措辞 | T6 |
| `CLAUDE.md` | 修改 | SSOT 公理、数据流、Schema Essentials 记法 | T6 |
| `docs/DESIGN_MODEL_POOL_v1.md` | 修改 | 正文与 3 个示例块 YAML 化（Codex 侧保留） | T6 |
| `docs/ACM_MVP_ACTION_PLAN_v1.0.md`、deep-dive/evaluation/deep-analysis 等历史档案 | **冻结不改** | 带日期的史料，非现状描述 | — |
| `docs/DESIGN_CONFIG_YAML_MIGRATION_v1.md`（本文档） | 修改 | 设计与行动计划；文末附执行记录 | — |
| `uv.lock` | 随动 | uv sync 生成 | T1 |

---

## 附录 C：执行记录与结果总结

> 执行轮：2026-08-26。按 §4 任务顺序全量执行完毕，三道质量门禁（`uv run pytest` / `uv run ruff check .` / `uv run mypy src`）终态全绿。

### C.1 逐任务执行结果

| Task | 结果 | 关键产出 |
|---|---|---|
| T1 依赖与解析层 | ✅ | `pyproject.toml` + `ruamel.yaml>=0.18`（实装 0.19.1）；`util.py` 新增 `CONFIG_FILENAME` / `get_config_path()`；`config.py` 移除 tomlkit、改 ruamel safe 加载，`parse_config_yaml()` 含空文件/非映射根/YAMLError 三类友好错误 |
| T2 生成器改造 | ✅ | `vmr.py` 新增 `_q()` 引用助手；模板与提案生成器输出 YAML，模型别名键原样保留（不再净化）；`~/.vmr/config.toml` 回退分支加保护注释 |
| T3 CLI 改造 | ✅ | `cli.py` 三处路径收敛至 `get_config_path()`；横幅/临时文件名/docstring 全部 YAML 化；校验走 `parse_config_yaml()` |
| T4 存量测试改造 | ✅ | conftest 夹具更名 `sample_config_yaml`；13 个测试文件完成 TOML→YAML 翻译（e2e 仅 L198 的①语境用例改动，Codex 侧 L46/L116 未动） |
| T5 新增测试 | ✅ | 新建 `tests/unit/test_yaml_loader.py`（12 例）：重复键硬错、YAML 1.2 无 yes/no 布尔化、`${VAR}`/`${VAR:-d}` 保真、多文档拒绝、空/注释文件友好错误、非映射根报类型名、tab 缩进语法错、锚点/merge key 安全展开、点斜线键保留。`test_cli_init.py` 增补 0600 权限断言与 init 横幅 YAML 文案断言 |
| T6 文档全量同步 | ✅ | PRINCIPLE（§1.3/数据流图/invariant/命令表）、SPEC（D3 以 YAML 决策陈述重写、§7.3 示例、A.1/A.2 裁决表改为"采纳"、依赖预算 D2 更新）、USER_GUIDE ×2 整篇（8 个 ACM 侧代码块全部转 YAML 且逐块验证可解析）、README ×2、CLAUDE.md、MODEL_POOL（正文 + 3 个示例块）。归档四份历史文档未动 |
| T7 清理核查 | ✅ | 全仓 grep：src/tests 零残留 `config_toml` 符号；活文档零 ```toml 块（仅 USER_GUIDE 各留 1 个 Codex 自身示例块）|
| T8 版本发布收尾 | ✅ | pyproject / `__init__.__version__` / `test_version.py` 三处统一 0.2.0（顺带修复既有 0.1.0 vs 0.1.2 不一致）；`uv sync` 后 lock 同步 |

### C.2 门禁与冒烟验证

- `uv run pytest`：**150 passed**（原 138 + 新增 12 loader 契约用例 −0 删减）
- `uv run ruff check .`：All checks passed
- `uv run mypy src`：Success, no issues found in 24 source files
- 隔离 HOME 冒烟：`acm init --force` 生成 `~/.acm/config.yaml` 权限 `0600`、内容为合法 YAML 模板（凭据引用双引号包裹）；`acm status` 正常出表；临时 HOME 用后即删，真实环境零接触
- 行为抽查符合 D5 直接切换语义：仅有旧名文件时报既有 "Run 'acm init' first"；新旧并存时只读 `config.yaml`

### C.3 执行偏差记录

1. **T5 merge-key 用例夹具修正**：初版夹具把锚点放在顶层 `defaults:` 键上，被 `CoreConfig(extra=forbid)` 拒绝——属测试夹具错误而非加载器缺陷；已将锚点移入 `providers:` 内部后通过。
2. **T6 中 lint 附带修复**：路径集中化后 `cli.py` 两处 `acm_home` 局部变量与 `config.py` 的 `Any` 导入成为死代码，ruff 报 F841/F401，随手清除。

### C.4 结论

设计文档 §0–§4 所述方案与最终实现一致，无未决事项。ACM Core Config 自 v0.2.0 起为 `~/.acm/config.yaml`；Codex 目标文件与 VMR 探测回退保持原有格式不动；投影纪律未被触碰（本轮未发生任何 Agent 配置写入路径的行为变更）。

> 注：本结论仅覆盖"YAML 格式改造"本身这个子集。工作区当前实际的整体 diff 还叠加了另一个独立功能（见附录 D.2 问题 1），该结论不应被读作"当前工作区全部未提交改动均出自本方案"。

---

## 附录 D：结合源码的二次复核（2026-08-26）

> 本附录由独立复核产生：逐文件核对本设计文档的论断与 `git diff` 实际内容、运行三道质量门禁、实测 D2 的 ruamel.yaml 行为契约。方法论：不采信文档自身的 claim，只采信源码/测试/命令输出。

### D.1 已直接修复的问题（根因清楚、方案无争议，已改并回归绿）

| # | 位置 | 问题 | 修复 |
|---|---|---|---|
| 1 | `src/acm/config.py` `validate_cross_references` | 校验错误消息仍残留 TOML 表头方括号记法（`under [models]`、`under [profiles]`，以及本轮 §18 新增校验里的 `'[profiles.<name>.pool]'`），与 `USER_GUIDE.md/.zh.md` §5.7 已经 YAML 化的错误消息对照表（写的是不带方括号的 `is not defined under models`）实际不符——即代码产出的文案与文档承诺的文案不一致 | 四处消息改为不带方括号的 `'models'` / `'profiles'` / `'pool'` 措辞；`tests/unit/test_config.py` 唯一相关的 `match` 断言不含方括号部分，改动后原样通过 |
| 2 | `CLAUDE.md`「Config Schema Essentials」 | 仍写 `version = 1`、`[profiles.*]`（TOML 记法），且称 `main` 为必填——与本轮之前已落地的 §18 registration-only 特性（`main` 可省略，只需 `pool` 非空）矛盾 | 改为 `version: 1` / `profiles:` 记法；`main` 必填性描述改为"除非声明非空 pool"；Implementation Status 里的 pool 说明一并补充 registration-only 行为 |
| 3 | `docs/USER_GUIDE.md` / `.zh.md` §3.1 三层示意图、§3.9 两处 pool 引用、§8.2/§8.3 VMR 探测小节 | 残留 `[providers]`/`[models]`/`[profiles]`/`[profiles.<name>.pool]`/`[models.*]` 等方括号记法；§8.3 更严重——仍描述"`[models.<safe-name>]`"，即**本轮迁移已在 D3 明确废除**的 VMR 模型 id 净化改名行为（生成器现在原样保留 `.`/`/`，不再改名） | 记法改为 `providers:`/`models:`/`profiles:`/`pool:`；§8.3 措辞改为如实描述"键名即模型自身 id，原样保留，不做净化改名" |
| 4 | `docs/USER_GUIDE.md` / `.zh.md` §5.4 字段表 | `main` 字段被标记为"✅ 必填"，与其正下方"pool 非空时 main 可省略"的规则文字自相矛盾（同一小节内的内部矛盾） | 改为"⚠️ 除非声明非空 `pool`，否则必填（见下文）" |

以上修复均已回归验证：`uv run pytest`（150 passed）、`uv run ruff check .`、`uv run mypy src` 三闸维持全绿；未改变任何测试断言的等价语义。D2 表格中的 ruamel.yaml 关键行为（重复键 → `DuplicateKeyError`）额外用一次性脚本实测复现，与文档论断一致。

### D.2 复核中发现、已由项目所有者拍板的问题

**问题 1（重要）：工作区未提交 diff 实际捆绑了两个互相独立、各自已完整实现的改动，而不只是 TOML→YAML 迁移。**

逐文件核对 `git diff` 发现，`src/acm/config.py`、`resolve.py`、`adapters/__init__.py`、`adapters/claude_code.py`、`adapters/codex.py`、`adapters/pi.py` 六个文件里，除本迁移涉及的格式相关改动外，还混有一个完全独立的功能改动：**"Pool-only Profile：registration-only 投影"**（`docs/DESIGN_MODEL_POOL_v1.md` §18，落款日期 2026-08-25——早于本迁移文档落款的 2026-08-26 一天）。核心变化是 `ProfileConfig.main` 从必填字符串改为 `str | None`、新增 schema 校验规则 R1（main 与 pool 至少一个非空）、以及三类 adapter 相应的 None 守卫与专属投影告警；未跟踪的新增金样测试文件 `tests/golden/test_adapters_pool_only.py` 也属于这个功能，与格式迁移无关。

**澄清时间线（避免与更早的 model pool 提交混淆）**：`git log` 显示上一个提交 `ff2008c feat: profile model pool ([profiles.*.pool]) with Pi multi-model projection` ——这是 model pool 功能的**基础版本**（§1–17：main 必填、pool 作为附加注册通道），确实已经提交。本附录讨论的是在那之后、于 2026-08-25 新增的**增量增强**——§18 registration-only（允许 pool 非空时省略 main），这部分连同本次 YAML 迁移一起，从未提交过，因此才会同时出现在当前工作区的未提交 diff 里。两者并非同一次提交的内容。

本设计文档 §2.2/§2.3/附录 B 对这几个文件的"改动点"描述与"防误伤清单"，只覆盖了 YAML 格式改造那部分——这在"仅论证本次迁移自身改动范围"的意义上没有错，但附录 C.4 原结论"设计文档 §0–§4 所述方案与最终实现一致，无未决事项"容易被误读为"工作区当前的全部未提交改动都出自本方案"，实际并非如此（已在 C.4 补一行澄清）。此外，本轮新增的 YAML loader 契约测试 `test_dotted_and_slashed_model_keys_preserved`（`tests/unit/test_yaml_loader.py`）本身写成了一个省略 `main`、仅有 `pool` 的 profile——即它能通过校验本身就依赖 §18 的 schema 变更，说明这两个改动在实现上是叠加关系（§18 在先，本迁移在其基础上继续开发），并非完全解耦。

**项目所有者裁定（2026-08-26）**：不拆分。§18 与本次 YAML 迁移合并为一个提交，一并 commit。理由：二者在实现上已叠加（拆分需要手工 `git add -p` 重构 diff，有操作风险且收益有限），且都已通过完整门禁验证。

**问题 2（次要，不阻塞 commit）：`docs/DESIGN_MODEL_POOL_v1.md` 内部仍有约 6 处 TOML 方括号记法未被 Task 6 转换**（如 §4.1"`[profiles.<name>.pool]` 子表"、§7.4 对照表"model pool（`[profiles.*.pool]`）"，以及 §13/§14 几处带日期的历史调查记录段落里的 `[models.a]`/`[models.cheap]` 等）。

根因：Task 9 收尾门禁的自查方法（`grep -rn "config\.toml"` + 统计 ` ```toml ` 代码块数）不会命中这类不含字面 "config.toml" 字符串的方括号路径记法——这是该验证方法本身的盲区。

**项目所有者裁定（2026-08-26）**：不修改。`docs/DESIGN_MODEL_POOL_v1.md` 整份文档计划在下一轮被删除，其关键设计信息届时会被提炼合并进核心设计文档；文档内残留的方括号记法与其他待办引用暂不处理。
