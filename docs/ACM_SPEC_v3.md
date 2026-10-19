<!-- // Ver 2026-10-20 02:40, by Claude Sonnet 5.5 -->

# ACM 实现规格 v3

> **文档性质**：实现参考。原则、边界、命令语义以 `docs/ACM_PRINCIPLE_v3.md` 为准，冲突时改本文。各 Agent 的配置位置、键值规则、临时启动注入规则、事实核查记录**只**在 `docs/ACM_Agent_Support_Matrix_opus-5.5.md` 维护，本文只定义契约与机制。
>
> **取代**：`docs/archive/ACM_PROJECT_SPEC_v2.2.md`。适用版本：0.4.0，config schema v4。

---

## 1. 技术栈与布局

- Python ≥ 3.12，macOS / Linux（全局锁用 `fcntl`）。依赖：pydantic v2、typer、rich、tomlkit、ruamel.yaml；JSON / JSONC / JSON5 编辑器为自研（无第三方依赖）。开发：pytest、hypothesis、ruff（行宽 100）、mypy strict。
- 分发：PyPI 包 `agent-config-manager`，导入名与命令名 `acm`，`uvx` 为主路径。

```
src/acm/
├── core/       errors.py（异常与退出码）paths.py lock.py masking.py
├── config/     schema.py（pydantic v4）load.py refs.py
├── catalog/    model.py（ModelCard）static.py manifest.py（客户端）resolve.py（角色 × 协议）
├── formats/    base.py（Document 接口）jsonc.py（JSON / JSONC / JSON5）toml.py yaml.py
├── adapters/   base.py registry.py claude_code.py codex.py pi.py opencode.py openclaw.py hermes.py
├── engine/     plan.py（Plan / Op）history.py（版本库 + 历史）write.py restore.py status.py
├── run/        runner.py（临时启动）
└── cli/        main.py（入口与 `acm <agent>` 简写）commands.py output.py
```

## 2. 术语

| 术语 | 含义 |
|---|---|
| 协议 `Protocol` | `openai-completions` / `anthropic-messages` / `openai-responses`（与 Pi 的 `api` 取值一致） |
| 角色 `Role` | `default` / `reasoning` / `fast` / `subagent` / `review`（封闭词表） |
| 目录 | 一个 provider 提供的模型卡片集合（静态声明或来自 Manifest） |
| ModelCard | 模型卡片：id、协议集合、角色提示、上下文、输出上限、输入模态、工具调用、推理 |
| ResolvedTarget | 针对某个 Agent，已解析好的端点、凭据引用、各角色的具体模型与协议 |
| Plan | 适配器的输出：字段级 ops、拥有的辅助文件、投影告警、错误 |
| 受管路径 | Plan 中 ops 所指的键路径；写入时记入历史，是漂移检测的依据 |
| 键路径 `KeyPath` | `tuple[str \| int, ...]`，不以 `.` 切分（模型 id 本身可含点） |

## 3. 配置 schema v4（`~/.acm/config.yaml`）

```yaml
version: 4                      # 必填；非 4 一律拒绝（不兼容读取 v3，用 `acm init --force` 重新生成）

providers:                      # ≥ 1
  <name>:                       # 名称：[A-Za-z0-9_-]+，不得含 . 或 @
    # —— 静态 provider ——
    protocol: openai-completions      # | anthropic-messages | openai-responses
    base_url: https://api.deepseek.com/v1   # http(s)；openai-* 含 /v1，anthropic-messages 不含 /v1
    api_key: "${DEEPSEEK_API_KEY}"    # 整字段引用；也允许明文（输出掩码）
    headers: {}                       # 可选；值同样可为 ${VAR}
    models:                           # ≥ 1
      deepseek-v4-pro:
        context_window: 1000000       # 以下均可选
        max_output_tokens: 65536
        input: [text, image]          # 缺省 [text]
        tool_call: true
        reasoning: true
        effort: high                  # low | medium | high
        roles: [fast]                 # 角色提示，使 <name>@fast 可解析

  <name2>:
    # —— Manifest 型 provider（与 protocol / base_url / models 互斥）——
    manifest: "https://vmr.team.lan/manifest"   # url | 文件路径 | file:// | "${VAR}"
    api_key: "${VMR_KEY}"
    headers: {}

profiles:                       # ≥ 1
  <name>:
    default: team@default       # 引用（模型或角色）；roles 与 default 同在时才有意义
    roles:                      # 可选；键 ∈ {reasoning, fast, subagent, review}
      reasoning: team@reasoning
      fast: team@fast
    models:                     # 可选：成员注册（label → 引用），供有模型注册表的 Agent（Pi 族等）使用
      deep: team.agent
```

校验规则（加载期，离线、确定性）：`extra=forbid`；profile 至少声明 `default` 或 `models` 之一；声明 `roles` 必须同时声明 `default`；静态 provider 与 Manifest 型字段互斥；`base_url` 须 http(s)；provider 名称合法；同一 profile 内不允许两个 label 解析到同一 `(provider, 模型 id)`。引用的存在性：静态引用在加载期校验；Manifest 型引用在解析期（需要目录）校验。

### 3.1 引用语法

| 形式 | 例 | 规则 |
|---|---|---|
| 凭据 | `${VAR}`、`${VAR:-default}` | 整字段；`VAR` ∈ `[A-Za-z_][A-Za-z0-9_]*`；不支持插值、嵌套；未设置且无默认 = 硬错误，任何写盘之前中止 |
| 限定模型 | `provider.id` | 按**第一个点**切分，左侧必须是已声明的 provider 名，故 id 可含点 |
| 裸模型 | `id` | 在**静态** provider 中全局唯一时有效；Manifest 型 provider 不支持裸 id |
| 角色 | `provider@role` | `role` ∈ 角色词表；在该 provider 目录中按目标 Agent 的协议偏好序解析 |

模型引用的解析顺序：先尝试限定（第一个点之左是已声明 provider 且其目录中有该 id），否则按裸 id 在静态 provider 中查找。

## 4. 目录与 Manifest

### 4.1 ModelCard

```python
@dataclass(frozen=True)
class ModelCard:
    provider: str
    id: str
    protocols: tuple[Protocol, ...]        # 非空
    display_name: str | None
    description: str | None
    roles: tuple[Role, ...]
    context: int | None                    # 最大可路由上下文
    context_floor: int | None              # 所有候选的最小上下文（Manifest 型才有）
    output: int | None
    input: tuple[str, ...]                 # 恒含 "text"
    tool_call: bool | None
    reasoning: bool | None
    effort: str | None                     # 仅静态
```

静态 provider 的模型卡片由 `models` 直接生成（`protocols = (provider.protocol,)`）。未知即缺省：不知道的值为 `None`，绝不当作 `0` / `False`。

### 4.2 Manifest v1

由网关发布的 JSON 文档（服务端实现见 VMR；设计依据 `docs/ACM_VMR_Manifest_Analysis_and_Design_opus-5.5.md` §5.3）：

```json
{ "manifest_version": 1,
  "gateway": {"kind": "vmr", "version": "0.7.3", "name": "team-vmr"},
  "endpoints": {"openai-completions": "https://h/v1", "anthropic-messages": "https://h", "openai-responses": "https://h/v1"},
  "auth": {"required": true},
  "models": [{"id": "coding", "display_name": "...", "description": "...",
              "protocols": ["openai-completions"], "roles": ["default", "subagent"],
              "limit": {"context": 1000000, "context_floor": 200000, "output": 32000},
              "modalities": {"input": ["text", "image"]}, "tool_call": true, "reasoning": true,
              "guarantee": {"input": ["text"], "tool_call": true, "reasoning": false}}] }
```

客户端规则：未知字段忽略；未知角色忽略；`manifest_version` ≠ 1 → 该来源无效（错误，不降级）；`models[].protocols` 必须 ⊆ `endpoints` 的键；同一 (协议, 角色) 上出现多个模型 → Manifest 非法。`guarantee` 本版本仅用于展示。

### 4.3 获取与缓存

- 来源：`https://…` 条件请求（`If-None-Match`，携带 `Authorization: Bearer <api_key>` 与 provider 的 `headers`）；本地文件 / `file://` 直接读取（无 ETag，无缓存）。
- 缓存：`~/.acm/state/manifests/<provider>.json`（0600）：`{url, etag, fetched_at, body}`。超时 2 秒（`ACM_MANIFEST_TIMEOUT` 可调）。

| 情形 | `use` / `apply` / `run` | `status` |
|---|---|---|
| 200 | 校验、写缓存、使用 | 同左 |
| 304 | 使用缓存 | 同左 |
| 网络失败 + 有缓存 | 使用缓存，stderr 告警（含缓存时间） | 同左，标注"目录新鲜度未知" |
| 网络失败 + 无缓存 | 退出 3，零写盘 | 依赖它的 Agent 置 ERROR |
| 401 / 403 | 退出 1，提示检查凭据，零写盘 | 依赖它的 Agent 置 ERROR |
| 结构非法 / 未知主版本 | 退出 1，零写盘 | 依赖它的 Agent 置 ERROR |

### 4.4 角色 × 协议解析

输入：provider 目录、引用、目标 Agent 的**协议偏好序**（适配器声明）。

1. `P.<id>`：取卡片；按偏好序取第一个 `p ∈ card.protocols`；无交集 → 若是 default 则该 Agent 置 ERROR，否则投影损失告警。
2. `P@r`：按偏好序遍历 `p`，取满足 `r ∈ roles ∧ p ∈ protocols` 的卡片（唯一性已在 §4.2 保证；静态 provider 以 `roles` 提示构造同样的集合）。
3. 找不到：`default` → ERROR；其他角色由适配器的**槽位策略**决定（回落到 default 并告警，或不写）。

输出 `ResolvedTarget`：`provider`、`endpoints`（按协议）、`credential`（引用 + 解析值句柄）、`default: ResolvedModel`、`roles: {Role: ResolvedModel | None}`、`members: {label: ResolvedModel}`、`warnings`。`ResolvedModel = (card, protocol, base_url)`。

## 5. 格式层

### 5.1 `Document` 接口

```python
class Document(Protocol):
    format: str                              # "json" | "jsonc" | "json5" | "toml" | "yaml"
    def get(self, path: KeyPath) -> Any      # 缺失返回 MISSING 哨兵
    def set(self, path: KeyPath, value: Any) -> None   # 沿途缺失的对象自动创建
    def delete(self, path: KeyPath) -> None            # 不存在则无操作
    def render(self) -> bytes                # 未修改部分尽可能逐字节不变
    def tree(self) -> Any                    # 语义树（dict / list / 标量），用于非破坏断言
def parse(fmt: str, data: bytes) -> Document      # 失败抛 FormatError
def empty(fmt: str) -> Document                   # 文件不存在时使用
```

### 5.2 各格式保证

| 格式 | 实现 | 保证 |
|---|---|---|
| JSON / JSONC / JSON5 | 自研"定位字节范围 → 原位替换"编辑器，统一接受 JSON5 超集（注释、尾逗号、无引号键、单引号、十六进制、`+`/`-`、`Infinity`/`NaN`） | 修改某个值只替换该值的字节；插入 / 删除成员保持缩进、换行风格（LF / CRLF）、尾逗号风格；BOM 保留；其余字节不变 |
| TOML | tomlkit round-trip | 注释与表顺序保留 |
| YAML | ruamel.yaml round-trip（保留引号、不折行） | 注释与键序保留 |

所有实现须通过同一套通用测试：未修改 → `render()` 与输入逐字节相同；改一个键 → 语义树只在该路径不同；含点的键可正确定位；真实语料 + 属性测试（hypothesis）。

### 5.3 非破坏断言

引擎对每个写入的文件断言：重新解析 `render()` 的结果成功；语义树相对写前仅在 ops 路径的前缀下有差异（`changed_paths(before, after)` 中每一项都必须以某个 op 路径为前缀）。

## 6. 适配器

### 6.1 契约

```python
class Adapter(Protocol):
    id: str; name: str; tier: Literal["T1", "T2"]; bins: tuple[str, ...]
    protocols: tuple[Protocol, ...]                      # 协议偏好序
    def detect(self, env) -> bool
    def files(self, env) -> list[FileSpec]               # (logical, path, format, owned: bool)
    def is_managed(self, logical: str, path: KeyPath) -> bool   # 白名单
    def plan_files(self, target: ResolvedTarget, view: DocView) -> Plan   # 纯函数；view 为只读视图
    def plan_launch(self, target: ResolvedTarget, ctx: LaunchContext) -> LaunchSpec
```

- `Plan = {ops: list[Set | Delete | OwnedFile], warnings: list[Warning], error: str | None}`。`Set(logical, path, value)`、`Delete(logical, path)`、`OwnedFile(logical, content: bytes)`。
- **槽位纪律**：适配器对其所有受管槽位**总是**产出 `Set` 或 `Delete`（不适用时 Delete），使"受管路径集合"稳定；引擎另外把上一次记录中存在、这次 Plan 不再包含的路径作为"退役路径"追加 `Delete`。
- **家族**：族长模块持有映射逻辑，成员是参数表（二进制名、目录、目录覆盖环境变量、文件名、额外槽位）；T2 成员只增加参数表条目与金样。
- 凭据写法：Agent 原生支持引用的一律写引用（见支持矩阵 §6.3）；仅当 Agent 不支持引用且 config 中为明文时才写明文，并告警。

### 6.2 注册

`registry.py` 中显式列出所有适配器（无反射、无动态加载）。CLI 的 Agent 名接受 `id`、别名（`claude`→`claude_code`）与连字符写法。

## 7. 引擎

### 7.1 状态目录 `~/.acm/state/`（0700）

```
.lock                      全局非阻塞 flock
active                     当前激活 profile 名
unmanaged.json             用户选择"不再管理"的 Agent 列表
objects/<ab>/<sha256>      版本库（0600），保存文件某版本的原始字节
history.jsonl              历史记录（只追加）
manifests/<provider>.json  Manifest 缓存
run/<pid>/                 临时启动的临时文件（用后即删，残留于下次运行时清理）
```

### 7.2 历史记录

每个被写入的文件一行 JSON：

```json
{"v":1,"seq":41,"time":"2026-10-20T10:03:12+08:00","op":17,"agent":"claude_code",
 "file":"/Users/u/.claude/settings.json","kind":"write","cmd":"acm use team",
 "before":"<sha256>","after":"<sha256>","paths":[["model"],["env","ANTHROPIC_BASE_URL"]],
 "owned":false,"external_before":false}
```

- `kind`：`baseline`（该文件第一次被 ACM 写入之前；`before == after`）、`write`、`restore`、`auto_revert`。
- `before` / `after`：版本哈希；文件不存在用 `"-"`。`paths`：该次 Plan 的全部受管路径（含退役路径）。`external_before`：写前内容是否不同于上一条记录的 `after`。
- `op`：同一次命令的所有记录共享。`seq`：全局递增。
- 一致性顺序：先写对象（幂等）→ 再写文件 → 再追加记录（单行 + `fsync`）。`baseline` 记录在该文件第一次写入**之前**追加，因此崩溃不会丢失"原始版本"；"写入后、记录前"崩溃只丢一条 `write`，下次运行表现为一次外部改动。
- 读取容错：末行截断 → 忽略并告警；记录引用的对象缺失或哈希不符 → 对应恢复被拒绝并说明。

### 7.3 写入流程（每个 Agent 为一个单元）

1. 读取该 Agent 的全部受管文件（字节 + 哈希；不存在记为 `"-"`）；解析失败 → Agent 置 ERROR，中止。
2. **漂移检查**：取每个文件最近一条 `write` / `restore` / `auto_revert` 记录；对其 `paths`，比较"该记录 `after` 版本中的值"与"当前文件中的值"。不一致 = 漂移。无记录 = 首次接管，无漂移基准。
   - 有漂移：非交互 → 退出 2，列出 `路径：ACM 写的值 → 现在的值`，除非 `--force`；交互 → 展示差异后三选一（覆盖 / 不再管理此 Agent / 放弃）。
3. 计算 Plan（含退役路径）；Plan 报错 → Agent 置 ERROR，中止。
4. 与当前值比较：全部相同 → no-op。
5. **首次接管或出现新受管路径**：展示变更清单并确认（`--yes` 跳过；非交互无 `--yes` → 退出 2）。`--dry-run` 到此为止并输出清单。
6. 内存中应用 ops → `render()` → 重新解析 + 非破坏断言（§5.3）；任一失败 → 中止，零写盘。
7. 复核各文件内容哈希与步骤 1 一致（防读写间隙被改）；不一致 → 中止，提示重试。
8. 首次写入某文件：先存 `before` 对象并追加 `baseline` 记录。
9. 存 `before` / `after` 对象；写临时文件（同目录）→ `fsync` → 保留权限与属组 → `os.replace`；符号链接写到链接目标并保留链接；多个硬链接时原位写。ACM 独占文件（`OwnedFile`）同样走此流程；其写前内容为 `"-"` 时，恢复 = 删除。
10. 追加历史记录。多文件中途失败 → 按已写文件逆序恢复其 `before` 版本，追加 `auto_revert` 记录，Agent 报错。

### 7.4 状态判定

`NOT_DETECTED`（未安装）→ `UNMANAGED`（无任何记录，或在 `unmanaged.json` 中，或无激活 profile）→ 否则：Plan 报错或文件无法解析或受管路径结构不匹配 = `ERROR`；有漂移 = `DRIFTED`；期望值 ≠ 当前值（含目录变化）= `OUT_OF_SYNC`；否则 `SYNCED`。`status` 输出漂移与差异明细、投影损失摘要、目录新鲜度。

### 7.5 恢复

| 命令 | 目标版本 | 默认模式 |
|---|---|---|
| `restore N` | 第 N 条记录的 `after` | 字段恢复 |
| `restore --baseline` | 该文件 `baseline` 记录的 `before` | 字段恢复 |
| `rollback` | 最近一次操作（`op`）中各文件的 `before` | 字段恢复 |

- **字段恢复**：令 `P` = 该文件历史中所有记录的 `paths` 的并集；对每个 `p ∈ P`，把当前文件中的值设为目标版本中的值（目标中缺失则删除）。当前文件的其他一切保持不变。适配器的 `is_managed` 对 `p` 不再成立 → 跳过并告警。
- **整文件恢复**（`--file`）：用目标版本的字节替换整个文件（目标为 `"-"` 则删除）；先展示"恢复后会丢失哪些非受管变化"并确认。
- 字段恢复到 baseline 且 baseline 为 `"-"`（ACM 新建的文件）：删除受管路径后若文件语义上为空对象则删除文件。
- 恢复本身走 §7.3 的写入流程（kind = `restore`），因此可被再次恢复。恢复可能与当前漂移无关，不做漂移阻断，但仍做非破坏断言与哈希复核。

### 7.6 `prune`

`acm prune --keep N`：每个文件保留最近 N 条记录及其引用的对象，加上所有 `baseline`；其余记录与不再被引用的对象删除。仅显式执行。

## 8. 命令

| 命令 | 要点 |
|---|---|
| `init [--vmr URL] [--force] [--yes]` | 扫描 Agent；探测目录（`--vmr` 或 `VMR_URL` 或本机默认地址 `http://127.0.0.1:8800`）：先 `GET /manifest`，404 回落 `GET /v1/models` 生成静态提案；401 / 403 明确提示；展示提案并确认后写 `config.yaml`（0600）。已存在则拒绝，除非 `--force` |
| `status [AGENT]` | 见 §7.4；退出码取最高严重级（ERROR→2，DRIFTED→2，其余 0） |
| `use PROFILE [AGENT...]` | 写 `active`（投影成功后）；逐 Agent 执行 §7.3 |
| `apply [AGENT...]` | 同 `use`，不改 `active` |
| `history [AGENT] [--full] [--limit N]` | 按文件分组列出记录，标注字段变化（受管路径的值变化，已掩码）；`--full` 附整文件差异 |
| `restore REF [AGENT] [--baseline] [--file]` | 见 §7.5 |
| `rollback [AGENT]` | 见 §7.5 |
| `run AGENT [-m REF] [--profile P] [--manifest M] [-- ARGS]` | 见 §9 |
| `prune --keep N` | 见 §7.6 |

输出：默认掩码（键名含 `key` / `token` / `secret` / `authorization` 的值）；`--show-secrets` 显示。

## 9. 临时启动 `acm run`

1. **目标来源优先级**：命令行（`-m`、`--profile`、`--manifest`）> 环境变量（`ACM_MANIFEST`，或 `VMR_URL` + `VMR_KEY`，此时无需 `config.yaml`，provider 名取 `gateway.kind`）> `config.yaml` 的激活 profile。
2. `-m REF` 覆盖 default：接受限定模型与角色引用；零配置模式下 `-m` 可省略 provider 前缀（`-m coding` 等价于 `gateway.kind.coding`）。
3. 经与 `use` 相同的解析层得到 `ResolvedTarget`，调用适配器 `plan_launch` 得到 `LaunchSpec = {argv, env, tmp_files, mode: "exec" | "child", notes}`。
4. 密钥不进 argv。临时文件（如有）写入 `~/.acm/state/run/<pid>/`（0700 / 0600）。`exec` 模式直接替换进程；`child` 模式 ACM 等待、透传终端与信号与退出码，退出后删除临时文件。
5. 适配器对不支持的 Agent / 场景返回明确错误（退出 1），不做猜测性注入；T2 成员在真机确认前默认拒绝。
6. 不写任何 Agent 文件、`config.yaml`、历史记录。

## 10. 安全

- 凭据只以引用形式存储；`config.yaml`、state 目录、版本库、Manifest 缓存权限 0600 / 0700。
- 版本库保存 Agent 配置的完整内容，可能含明文 key；`history` / `diff` 输出掩码；文档明示。
- 白名单由适配器 `is_managed` 声明，引擎在 Plan 阶段与写入阶段两次校验；`OwnedFile` 路径须在 `~/.acm` 或该 Agent 的配置目录内。
- 适配器纯函数；无 `eval`、动态导入、远端代码。

## 11. 测试与验收

| 层 | 内容 |
|---|---|
| 格式层 | 通用 round-trip 套件 + 真实语料（6 个 T1 Agent 的脱敏样本）+ hypothesis 属性测试（随机文档 × 随机注释 / 排版 × 随机 set / delete） |
| 引擎 | 写入流程各步的负向用例；故障注入（`ACM_TEST_FAULT_*` 环境变量，仅测试使用）：白名单越界、多文件中途失败、提交间隙 SIGKILL、外部并发篡改、锁竞争、`${ENV}` 缺失、对象已写记录未追加、历史末行截断、对象缺失 / 损坏 |
| 目录 | Manifest 失败矩阵全分支；角色唯一性；离线回落 |
| 适配器 | 金样三步断言 + 投影损失告警 + 未知结构置 ERROR；`plan_launch` 金样 + "密钥不在 argv"断言 |
| 真机（T1） | 隔离 HOME + 本地模拟网关；用真实 Agent 二进制验证请求到达期望端点、带期望模型名；记录 Agent / ACM 版本与结果 |

测试基础设施：每个测试自动隔离（假 HOME、清理 PATH、Manifest / VMR 探测指向死端口）；提供 `fake_gateway` fixture（模拟 Manifest 与各协议入口并记录请求）。
