# // Ver 2026-08-26 15:35, by claude-sonnet-5
# VMR 新 Status 输出对 ACM 的影响分析与适配 Action Plan（v1）

> **分析日期**：2026-08-26
> **分析对象**：VMR 实机实例 `http://192.168.0.22:8800`（版本 `949be5a`，2026-08-26）；vmr 源码 `/Users/stanford/code/vmr`（同 commit）
> **ACM 基线**：当前工作区（`src/acm/vmr.py` Ver 2026-08-24），`uv run pytest` 150 passed
> **方法声明**：本文所有结论均基于①vmr 服务端源码逐行阅读（`internal/server/server.go`、`admin.go`、`internal/core/core.go`、CHANGELOG）、②对实机三个端点的 curl 实测、③ACM 源码逐行核对。**不依赖任何文档的转述性 claim**；文档仅在"ACM 自己声称了什么"这一层被引用。

---

## TL;DR（一页结论）

1. **新 `/status` 输出本身对 ACM 的核心链路零破坏**：ACM 的主数据源是 `GET /v1/models`，实测其响应形状（`data[].id` + `vmr_protocol`）与 ACM 解析器完全兼容，一个字节都没变。
2. **但同一轮 VMR 演进中，有两样 ACM 依赖的东西真的死了**：
   - `GET /healthz` 已从路由表移除（现为 `/health`），实测返回 **404**——ACM 探测链第 2 步成为死代码；
   - `~/.vmr/config.toml` 兜底检查的对象在新一代 VMR 中不存在（`~/.vmr/` 只有 `logs/`、`image_cache/`，配置是项目目录下的 `config.yaml`）——第 3 步同样死亡。
   - 探测链实际退化成了**单点**：只剩 `/v1/models`。
3. **最严重的潜在影响不是 404，而是鉴权**：新版 VMR 把 `/v1/models` 和 `/status` 纳入了 `api_keys` 鉴权面。一旦用户按 VMR 自己的告警建议配置了 `api_keys`（当前实机正因未配置而报 "open proxy" 警告），ACM 的探测会收到 401，而现有代码把 HTTPError 静默吞掉 → 返回 None → `acm init` **无任何提示地**退化为直连模板。这违反公理 3 的"显式暴露，绝不静默"，是本次必须修的头号问题。
4. CoreConfig schema、全部 adapters、Safety Engine、writers、drift 检测**均不受影响**（论证见 §3.3）——它们从不读取 VMR 的任何端点。
5. 新 `/status` 提供了真正有价值的新信息（模型能力集、context window、端点健康、实例版本、配置 staleness），其中一部分值得**有边界地**吸收为探测富化；quota/traffic 等运行时遥测则明确拒绝纳入（scope test 论证见 §3.5）。
6. Action Plan 共 7 步（Step 0–6）：fixtures 先行 → vmr.py 重写 → CLI 显式暴露 → 死代码清理 → 文档双语联动 → 全量门禁 → 真机验收。预计改动集中在 `src/acm/vmr.py`、`src/acm/cli.py`、`tests/conftest.py`、`tests/unit/test_vmr.py`、USER_GUIDE 双语 §8.2、SPEC §9，**不触碰 schema 与 adapters**。

---

## 1. 事实基础

### 1.1 新 VMR 的 HTTP 路由表与鉴权模型

来源：`vmr/internal/server/server.go` `Handler()`（逐行核对）：

| 路由 | 方法 | 鉴权 | 说明 |
|---|---|---|---|
| `/v1/chat/completions` | POST | 走 chat 鉴权 | OpenAI 方言入口 |
| `/v1/messages` | POST | 同上 | Anthropic 方言入口 |
| `/v1/responses` | POST | 同上 | OpenAI-Responses 方言入口 |
| `/v1/models` | GET | **`s.auth(...)` 门禁** | 模型列表（ACM 主数据源） |
| `/health` | GET | **无鉴权** | 纯 liveness（原 `/healthz` 的替代者） |
| `/status` | GET | **`s.auth(...)` 门禁** | 管理面全量状态 |
| `/status.html`、`/log`、`/log.html` | GET | 部分 | 仪表盘与日志流 |

文件头注释原文："**Anything else is 404.**"

鉴权语义（`server.go authenticate()`，逐行核对）：

- 鉴权面只有顶层 `api_keys:` 列表（单数 `api_key` catch-all 已删除）；
- **`api_keys` 为空时大门完全敞开**（当前实机即此状态，因此 `/status` 才发出 "not loopback-only and no api_keys are configured — open proxy" 警告）；
- 配置了 `api_keys` 后，凭据通过 `Authorization: Bearer <key>` 或 `x-api-key: <key>` 提供，否则 **401**（`server_test.go` 多处用例钉死该行为）；
- `/health` 被**刻意**排除在鉴权外（注释明说：liveness 无凭据可用）。

### 1.2 实机验证记录（2026-08-26，http://192.168.0.22:8800）

| 端点 | 实测结果 |
|---|---|
| `GET /v1/models` | **200**，`{"object":"list","has_more":false,"data":[{"id":"agent","object":"model","type":"model","owned_by":"vmr","vmr_protocol":"openai"},{"id":"cheap",...},{"id":"coding",...}]}` |
| `GET /healthz` | **404 page not found**（路由已不存在） |
| `GET /health` | **200**，`{"status":"ok","time":"...","uptime_seconds":362}` |
| `GET /status` | 200（因未配 api_keys 而免鉴权），载荷见 §1.3 |
| `GET /v1/models` + 错误 Bearer | 仍 200（api_keys 为空 = 鉴权关闭）；`server_test.go` 钉死：配置后错误 key → 401 |

**关键判定**：`/v1/models` 的响应形状与 ACM `probe_vmr()` 的解析逻辑（读 `data[].id`、可选 `vmr_protocol`，白名单校验协议值）**完全兼容，零变更**。

### 1.3 `/status` 新载荷结构解剖

实测顶层键：`audit / current_time / image_cache / instance / models / quota / system / traffic`。

对 ACM 有潜在意义的字段（其余为运维遥测）：

```
instance:
  version: "949be5a"            # VCS short hash，进程级恒定
  base_urls:                     # 按 ingress 协议回显客户端可达 URL
    {anthropic|openai|openai-responses}: "http://192.168.0.22:8800/v1/"
  config:
    path: "/Users/stanford/code/vmr/config.yaml"
    mtime / stale: false         # 配置文件是否比进程加载时更新
    issues: [ {field, message, severity} ]   # vmr 自身 config.Check() 结果
  models: 3                      # 计数
models[]:                        # 每个 (虚拟模型 × 协议) 一条 —— 不去重！
  - id: "agent"
    protocol: "openai"
    capabilities: [audio,image,text,thinking,tools,video]   # 各 endpoint 并集
    max_context_tokens: 512000                              # 各 endpoint 最大值
    endpoints[]:
      - endpoint: "openai/bai/deepseek-v4-flash"  # 仅展示名：<adapterType>/<provider>/<model>
        protocol / priority / consecutive_failures / available / serving
        capabilities / max_context_tokens          # endpoint 级覆盖值
quota[]:                          # 配额桶/闸门仪表（pct/headroom/period/model_multipliers）
```

源码级事实补充（防误读，均已核对实现）：

1. **`models[].id` 就是虚拟模型名**，与 `/v1/models` 的 `data[].id` 是同一个东西（agent/cheap/coding）——两 surface 一致，可互为印证。
2. **`endpoints[].endpoint` 字符串是展示名，不是可寻址 id**。`core.Endpoint.Name()` 注释明说是给 `/status` 和日志看的人类可读标识；真正的上游寻址在 vmr 内部完成。**任何想把 `"openai/bai/deepseek-v4-flash"` 当作模型 id 写进 ACM config 的做法都是错的**。
3. **同名多协议不去重**：一个虚拟模型若同时注册 openai + anthropic 两组端点，`/status.models` 会出两条（`modelStatus` 注释明说）；而 `/v1/models` 会按协议排序去重只出一条（首个协议胜出）。消费方必须自行处理这个差异。
4. **`base_urls` 是请求回显**：由 caller 的 Host 头 + 是否 TLS 推导（`instanceBaseURLs()`），带尾部斜杠 `/v1/`，注释明说 "**Display only; never consulted for auth or routing**"。它反映"你怎么进来的"，不是配置真值。
5. `has_more` 字段存在但目前恒为 `false`（分页留位，观察项）。

### 1.4 变更时间线（vmr CHANGELOG + git log 核实）

- **Breaking**: `/admin/status` → `/status`；loopback-only 限制移除；鉴权统一收口到 `api_keys`；
- **Breaking**: `/status` 载荷重构为 `instance/system/traffic` 三块；
- `/status.models` 从"按显示串 `"name [protocol]"` 键控的 map"改为结构化数组（2026-08-26 commit `4b1c79b`，同时加入 `base_urls`）;
- 新增 `GET /health`（无鉴权 liveness）、`/log`、`/status.html`；
- 整个 vmr 仓库 grep `healthz` **零命中**——`/healthz` 在当前代际从未存在过或早已移除。

值得记录的一个历史事实：ACM 的 MVP Action Plan（2026-08-24/25 定稿）就已实测到 "`/healthz` 404 而 `/v1/models` 200"（A2 决策条目），但仍按"快速通道保留容错"处理——当时的判断是"多端点容错总没错"。今天的事实表明 healthz 不是暂时 404，而是**永久消失**（路由表钉死 Anything else is 404），死代码应当清理而非继续容忍。

---

## 2. ACM 现状：谁在消费 VMR 面

### 2.1 `probe_vmr()` 三步链逐条对照新现实

`src/acm/vmr.py`（Ver 2026-08-24）：

| 步骤 | 代码行为 | 新现实下的实测/推演 | 判定 |
|---|---|---|---|
| ① `GET {host}/v1/models` | 解析 `data[]` → `VmrModelInfo(id, vmr_protocol)`；协议白名单校验；`base_url = f"{host}/v1"` | 实机 200，形状兼容 | ✅ 存活，主契约不变 |
| ② `GET {host}/healthz` | 200 即视为存活（models 为空） | **404**；HTTPError ⊂ URLError（已验证 `issubclass=True`），异常被静默吞掉后落到步骤③ | ❌ **死代码** |
| ③ `~/.vmr/config.toml` 存在性 | 存在即视为"装了但没跑" | 本机 `~/.vmr/` 只有 `image_cache/ logs/`；新 VMR 配置是项目目录 `config.yaml`，且仓库内 grep `.vmr` 只命中 logs/image_cache 默认目录 | ❌ **死代码**（针对本代 VMR 恒假） |

**净效果**：容错链退化为单点。只要 `/v1/models` 可达一切照旧；一旦它不可达（含下述鉴权场景），整个探测无声失败。

### 2.2 消费面矩阵（grep 全量核对）

| ACM 组件 | 是否触碰 VMR 面 | 证据 |
|---|---|---|
| `vmr.py probe_vmr/generate_vmr_proposal/generate_template_config` | ✅ 唯一直接消费者 | 本文件 |
| `cli.py init` | ✅ 调 probe，输出 detected/base_url/模型数 | L78–L83 |
| `config.py` schema | ❌ 无 vmr 专属字段 | providers/models/profiles 全部通用 |
| `resolve.py` | ❌ 只认 `${VAR}` 引用语法（`${VMR_KEY}` 只是普通引用） | 测试佐证 |
| adapters（claude_code/codex/pi） | ❌ 纯函数，输入是 ResolvedProfile | plan() 源码 |
| safety/writers/state/status/lock/masking | ❌ 零耦合 | grep 零命中 |
| 测试基建 | ✅ `MockVmrHandler` 同时 mock 了 `/v1/models` 和 `/healthz`（conftest.py + test_vmr.py 两处重复定义） | 源码 |
| 文档 | ✅ USER_GUIDE 双语 §8.2、SPEC §9 明文写着 healthz/config.toml 探测序列 | L830–860 等 |

另核对一处关联逻辑：init 生成的提案写 `api_key: "${VMR_KEY:-}"`。Pi 投影时若 `VMR_KEY` 未导出且解析值为空，`_resolve_pi_api_key` 会显式降级为 `"dummy"` 并发 ProjectionWarning——这条路径本身健康，但它反衬出一个不对称：**投影侧会用凭据，探测侧却从不带凭据**。

### 2.3 D7 现状确认

`grep -rn pool src/acm/{vmr,cli}.py` 零命中，`generate_vmr_proposal()` 无池生成逻辑——`init` 自动生成带 pool 提案确实未实施，与 `ACM_PROJECT_SPEC_v2.1.md` §7.3.3、CLAUDE.md "Implementation Status" 段落"`acm init` 不生成 pool 提案（未实现）"的现行表述一致。（历史脚注：这条订正最初见于已 retire 的 `DESIGN_MODEL_POOL_v1.md` §13.4；该文件已于 2026-08-26 commit `9035bde` 并入 SPEC §7.3.3，本文档起改为直接引用现行 SPEC。）本报告不推翻"本轮不做该能力"的既有裁剪，但在 §10 附录给出"如果做，新格式让它变得更好做"的路线评估。

---

## 3. 影响判定

### 3.1 总判定

**有影响，但影响面精确且可控**：

- 对"ACM 配置格式（CoreConfig schema）"：**零影响**；
- 对"ACM 已实现的命令行为"：`init` 的探测链受实质影响（两个死分支 + 一个静默降级风险），`use/status/rollback` **零影响**；
- 对"测试与文档"：mock server、golden fixtures、USER_GUIDE/SPEC 的探测序列描述需要同步更新，否则文档在教用户调用一个已经 404 的端点。

### 3.2 影响明细

#### I1【高 · 行为风险】鉴权后的静默降级

场景推演（每步均有代码依据）：

1. 用户采纳 VMR 的 open-proxy 告警，配置顶层 `api_keys: [sk-...]`；
2. `acm init` → `probe_vmr()` → `urlopen(/v1/models)` 抛 `HTTPError 401`；
3. `except (urllib.error.URLError, TimeoutError, OSError, json.JSONDecodeError): pass` 吞掉（HTTPError ⊂ URLError，已验证）；
4. 步骤② healthz 404 → 同样吞掉；步骤③ config.toml 不存在 → 返回 `None`；
5. `cli.init` 打印 *"VMR not running. Generating standard multi-provider template."* ——**这句话在事实上是错的**（VMR 正在运行，只是不认得我们），并生成一份与用户真实环境完全脱节的直连模板。

违反铁律"显式暴露，绝不静默处理"。这是唯一一个会造成**用户可见的错误产物**的影响，定为 P0。

#### I2【低 · 僵尸代码】healthz 分支

永久 404（路由表白名单钉死）。当前无害（吞异常继续），但它让"多端点容错"变成纸面能力，且 mock server 还在给它返回 200——**测试在为一个不存在的世界作证**。P1 清理。

#### I3【低 · 僵尸代码】`~/.vmr/config.toml` 分支

对本代 VMR 恒假。`vmr.py` 里那段 NOTE 注释（"never migrate or clean it up when touching ACM config formats"）所防御的场景在本代 VMR 中不存在。P1 清理，同时 USER_GUIDE §8.2 第 3 条同步删除。

#### I4【信息 · 无需行动】base_url 硬编码拼接

`probe.base_url = f"{host}/v1"` 与实机 `instance.base_urls.*`（`http://<host>/v1/`）语义一致（仅差尾部斜杠）。由于 `base_urls` 只是请求回显，ACM 用自己探测用的 host 拼接得到的结果与之等价。**不需要改**；若未来做 /status 富化可顺带校验一致性（§10 O2）。

### 3.3 明确不受影响的部分及论证

- **CoreConfig schema**：providers/models/profiles 三层没有任何 vmr 专属概念；`protocol ∈ {openai, anthropic, openai-responses}` 与 vmr 三 ingress 协议天然对齐（`/v1/chat/completions` ↔ openai、`/v1/messages` ↔ anthropic、`/v1/responses` ↔ openai-responses）。
- **adapters / Safety Engine / writers / state / drift**：纯投影层，输入是 ResolvedProfile，从不发起网络请求。VMR 面 whatever 形状都影响不到它们。
- **use/status/rollback**：状态机的比较对象是 last_write.json vs 磁盘 vs config.yaml，三者都在 ACM 自有域内。
- **`/v1/models` 主契约**：响应形状未变（§1.2 实测）。vmr CHANGELOG 中历次 breaking 都发生在 `/status`/auth/ingress 层，`/v1/models` 作为 OpenAI 兼容契约保持了稳定——这也印证了 SPEC §9 "VMR 侧零改动：只需暴露标准的模型列表查询端点" 这条设计输入依然成立。

### 3.4 机会项（新格式带来的正向价值，详见 §10）

| # | 机会 | 价值 | 建议 |
|---|---|---|---|
| O1 | `/health` 作为新的 liveness 快速通道 | 恢复双端点容错；无鉴权永远可达，还能区分"没跑"vs"跑了但不认我"（401 场景的关键判据） | **P0 采纳**（随 I1 一起修） |
| O2 | `/status` 富化：version、config.stale/issues、capabilities、max_context_tokens | 版本哨兵（schema 漂移检测）、vmr 侧问题显式曝光、L2 context_window 预填 | P1/P2 有边界采纳 |
| O3 | D7（init 池提案）若启动，/status 提供了比 /v1/models 好得多的数据源（label+能力+上下文窗口一次拿全） | 降低实施成本 | 附录评估，不在本轮 |
| O4 | quota/traffic 遥测 | — | **拒绝**，见 §3.5 |

### 3.5 明确拒绝的方向（第一性原理 + scope test）

1. **quota/headroom 驱动 profile 选择或投影决策**：scope test 问"换 provider/model 时这个功能变不变？"——quota 是 VMR 的运行时计量状态，与 agent 配置投影无关。ACM 的职责是把声明的配置忠实投影，不是替用户选路。纳入只会制造第二个真相源，违反 SSOT。拒绝。
2. **把 `/status` 升级为主数据源**：它是 vmr 私有管理面，近两周内刚经历两次 breaking 重构（map→数组、块重构），而 `/v1/models` 是对外契约、始终稳定。把易变私有面当主依赖等于自愿绑上对方的发布节奏。拒绝；只做"尽力而为、解析失败即忽略"的可选富化。
3. **为探测引入配置文件字段**（如在 config.yaml 里存 vmr 地址/key）：探测是 init 时刻的一次性行为，此时 config.yaml 可能还不存在（先有鸡还是先有蛋）。环境变量（已有 `ACM_VMR_PROBE_URL` 先例）是正确层级。

---

## 4. 适配方案设计

### 4.1 探测链重设计（I1/I2/I3 + O1 一揽子）

新顺序与判定语义：

```
① GET {host}/v1/models            （携带凭据，若有）
     200      → OK, models=N              （主证据+数据源，不变）
     401/403  → AUTH_REQUIRED              ← 新增终态，独立判定，绝不静默，
                                             不依赖②的结果（HTTP 401/403 本身
                                             已是"服务端在线且要求鉴权"的
                                             充分证据，不需要 /health 佐证）
     其他异常（连接被拒/超时等）→ 转②，用 /health 区分"没跑"vs"跑了但
                                  /v1/models 单独有问题"
② GET {host}/health               （无鉴权，替代 healthz；仅在①非 401/403
                                     地失败时才会走到这一步）
     200 → DEGRADED, models=[]    （VMR 存活但 /v1/models 不可用/超时；
                                     保持原"降级提案"语义）
     异常 → 转③
③ （原 ~/.vmr/config.toml 分支）→ 删除
④ 全部失败 → None（未检出，走模板，现状不变）
```

设计要点：

- **凭据来源**：`ACM_VMR_PROBE_KEY`（专用，优先）→ 回落 `VMR_KEY`（复用提案里已有的引用变量，语义自洽："agents 用什么 key 连 vmr，探测就用什么 key 问 vmr"）。以 `Authorization: Bearer` 发送。
- **新增终态而非抛异常**：扩展 `VmrProbeResult`（见 §4.4），保持 `probe_vmr()` 永不 raise 的既有契约，把决策留给 CLI 层。
- **超时维持 1s × 2 次请求**，最坏 ~2s，可接受。
- **`rstrip("/")` 已有**，无需动。

### 4.2 显式暴露策略（CLI 层）

`cli.init` 收到 `outcome == "auth_required"` 时：

- stderr 输出黄色警告：说明 VMR 在 `{host}` 存活但要求鉴权、`/v1/models` 不可枚举、提示 `export ACM_VMR_PROBE_KEY=...`（或 `VMR_KEY`）后重跑；
- **仍然生成模板并继续交互流程，exit code 保持 0**。理由：init 是交互命令，用户可能有意识地选择"先要个模板"；硬阻断（exit 1/2）超出必要强度。但警告必须在 stderr 且措辞不得再说 "VMR not running"——改为如实的 "requires authentication"。
- 掩码纪律：凭据只进请求头，任何输出路径（stdout/stderr/日志）不得出现 key 值；现有 masking 模块管的是 `${VAR}` 字面量，此处靠"不打印"保证，并在测试中断言。

### 4.3 `/status` 使用边界与陷阱清单（供 P1/P2 富化遵循）

若未来吸收 /status 数据，必须遵守：

1. 解析器 `extra="ignore"`、任何字段缺失/类型不符 → 整体放弃富化，退回纯 /v1/models 结果（富化永远是增益，永不能成为依赖）；
2. `endpoints[].endpoint` 字符串**禁止**当作可寻址模型 id 入 config（§1.3 陷阱 2）；
3. 多协议同名去重规则要与 `/v1/models` 的"协议排序首胜"对齐，避免两 surface 给出不同答案；
4. `base_urls` 尾部斜杠需 normalize（`rstrip("/")`）后再比对/采用；
5. `version` 只作展示与哨兵比对，不作行为分支依据（未知版本 → 警告，不是 ERROR——因为 /v1/models 主契约才是行为基础，它没坏就不 block）。

### 4.4 数据结构改动草案（`VmrProbeResult` 扩展）

```python
class VmrProbeOutcome(str, Enum):
    OK = "ok"                    # /v1/models 200，含模型清单
    AUTH_REQUIRED = "auth_required"   # /v1/models 401/403——独立判定，不依赖 /health
    DEGRADED = "degraded"        # /v1/models 非鉴权失败，但 /health 200 证实存活
    # not-running 仍以返回 None 表达，不改既有语义

class VmrProbeResult(BaseModel):
    model_config = ConfigDict(extra="forbid")
    detected: bool
    base_url: str
    models: list[VmrModelInfo] = Field(default_factory=list)
    outcome: VmrProbeOutcome = VmrProbeOutcome.OK
```

兼容性：现有调用点只读 `detected/base_url/models`，新增带默认值字段不破坏任何现有测试；`generate_vmr_proposal()` 签名不变。

---

## 5. Action Plan（分步执行）

> 原则：fixtures 先行（对应质量门禁"round-trip 测试先于 adapter 工作"的同构要求）；每步独立可验收；全程不碰 schema/adapters/safety。

| Step | 内容 | 主要文件 | 规模 |
|---|---|---|---|
| 0 | 基线固化 | — | S |
| 1 | 真实面 golden fixtures + mock 更新 | `tests/fixtures/`、`tests/conftest.py`、`tests/unit/test_vmr.py` | M |
| 2 | vmr.py 探测链重写 + 单测 | `src/acm/vmr.py`、`tests/unit/test_vmr.py` | M |
| 3 | CLI 显式暴露 | `src/acm/cli.py`、集成测试 | S |
| 4 | 死代码清理 | `src/acm/vmr.py`（③分支）、两处 MockVmrHandler 的 healthz 分支 | S |
| 5 | 文档双语联动 | USER_GUIDE.md/.zh §8.2、SPEC §9、CLAUDE.md（如有必要） | M |
| 6 | 全量门禁 + 真机验收 | — | S |

### Step 0 — 基线固化
- `uv run pytest && uv run ruff check . && uv run mypy src` 全绿（已预验：150 passed）。
- 产出：基线记录写入 PR 描述。

### Step 1 — fixtures 与 mock 先行（先立靶子再打）
1. **新增** `tests/fixtures/vmr_status_v2.json`：从实机抓取的 /status 载荷**脱敏快照**（去掉 quota 数值、路径中的用户名等；保留结构与键名）。作用：上游 schema 漂移哨兵——vmr 再改 /status 形状时此 fixture 的 diff 就是警报。
2. **新增** `tests/fixtures/vmr_models_response.json`：`/v1/models` 实测响应快照（含 `object/type/owned_by/vmr_protocol/has_more` 全字段），钉死主契约。
3. **改造** `MockVmrHandler`（conftest.py 与 test_vmr.py 两处，顺手合并为单一共享 handler）：
   - `/v1/models` 直接 serve fixture 文件；
   - `/healthz` 改为 **404**（钉死新现实——这正是 golden-fixture-as-drift-sentinel 的用法）；
   - 新增 `/health` 返回 `{"status":"ok","time":...,"uptime_seconds":N}`；
   - 新增可参数化的 `api_keys` 模式：配置后 `/v1/models` 无凭据返回 401、带正确 Bearer 返回 200。
4. **新增失败用例**（此刻应红）：`test_probe_auth_required_*`、`test_probe_health_fallback_*`。验收：新用例红、存量 150 个全绿。

### Step 2 — vmr.py 重写
按 §4.1/§4.4 实施：
- `VmrProbeOutcome` 枚举 + `VmrProbeResult.outcome` 字段（带默认值，向后兼容）；
- 凭据解析：`ACM_VMR_PROBE_KEY` → `VMR_KEY` → 无；
- 请求头：有 key 时加 `Authorization: Bearer`；
- 401/403 单独捕获（在 URLError 之前判 `isinstance(e, urllib.error.HTTPError) and code in (401,403)`）→ 直接返回 `AUTH_REQUIRED`，不进入步骤②；
- 步骤②改 `/health`，只在①以非 401/403 方式失败时才会执行；200 → `DEGRADED`；
- **删除步骤③**（`~/.vmr/config.toml` 分支及其 NOTE 注释一并移除）；
- docstring 同步新顺序与新终态。
- 单测补齐：四终态各至少 1 例；key 优先级 2 例；401+health-200 组合 1 例；断言请求头携带且不落日志。

### Step 3 — CLI 显式暴露
- `cli.init`：按 outcome 分支输出（§4.2 文案）；`OK/None` 路径输出保持逐字不变（避免扰动现有集成测试快照）。
- 集成测试（`tests/integration/test_cli_init.py` 补充）：auth_required 场景断言 stderr 含 "authentication"、stdout 走模板流程、exit 0、全文不含 key 明文。

### Step 4 — 死代码清理收尾
- 确认仓库内 `grep -rn "healthz\|config.toml" src/ tests/` 归零（docs 中的历史记录类文档除外，见 Step 5 第 3 条）；
- conftest/test_vmr 中合并后的 MockVmrHandler 删除旧分支。

### Step 5 — 文档联动
1. `USER_GUIDE.md` §8.2：探测序列改为 `/v1/models`（可携凭据）→ `/health`；新增"鉴权"小节（ACM_VMR_PROBE_KEY / VMR_KEY、401 行为、stderr 警告样式）；删除 config.toml 条目。§8.3 增补一句：提案 base_url 来自探测主机拼接，与 /status base_urls 回显语义一致。
2. `USER_GUIDE.zh.md` §8.2：同步翻译。
3. `ACM_PROJECT_SPEC_v2.1.md` §9（L705-722）：`acm init` 的 CLI 逐字转录注释（L710-712，"healthz 快速通道 → /v1/models → ~/.vmr/ 配置"）描述的是当前行为，不是历史记录——按新探测序列整段重写为"/v1/models（主证据+鉴权）→ /health（无鉴权 liveness）"，补一句鉴权后果（401 → auth_required 警告，模板降级，exit 0）。**不要与** Appendix「评估报告 Claim 核查表」L1054 的 healthz 条目混淆——那是对某份旧评估报告原始 claim 的核查记录，同 A2，历史快照，不改。
4. `docs/ACM_MVP_ACTION_PLAN_v1.0.md` 的 A2 条目：**不改写**（历史执行记录），仅在新分析文档（本文档）中交叉引用。
5. CLAUDE.md：Implementation Status 段落本身不涉及探测序列，但架构树注释（`vmr.py # VMR probe (/v1/models → /healthz → ~/.vmr) + proposal gen`）确实写了旧序列——**这是本文档最初核对遗漏的一处**，需同步改为 `/v1/models w/ optional bearer cred → /health`。

### Step 6 — 验收
见 §9。

**依赖关系**：Step 1 → 2 → 3 严格串行；4、5 可并行；6 最后。全程预估一个工作日内完成。

---

## 6. 测试计划汇总

| 类别 | 用例 | 断言要点 |
|---|---|---|
| unit | `test_probe_ok_with_fixture` | /v1/models 200 → OK，模型清单与 fixture 一致 |
| unit | `test_probe_auth_required_no_key` | api_keys 模式 + 无 key → outcome=AUTH_REQUIRED, detected=False 语义明确（建议 detected=False + outcome 区分，避免下游误生成 vmr 提案） |
| unit | `test_probe_auth_required_with_key_succeeds` | 带 ACM_VMR_PROBE_KEY → OK |
| unit | `test_probe_key_priority` | ACM_VMR_PROBE_KEY 优先于 VMR_KEY |
| unit | `test_probe_healthz_gone_health_alive` | /v1/models 非鉴权异常（连接被拒/超时）+ /health 200 → DEGRADED, models=[] |
| unit | `test_probe_all_dead_returns_none` | 死端口 → None（回归保护） |
| unit | `test_probe_never_leaks_key` | 捕获 urlopen 调用参数与结果对象字符串化输出，不含 key 值 |
| integration | `test_cli_init_auth_required_warns` | stderr 警告 + 模板流程 + exit 0 + 无 key 泄漏 |
| integration | `test_cli_init_ok_path_unchanged` | 存量 happy-path 输出逐字不变 |
| golden | fixture 快照比对 | vmr_status_v2.json / vmr_models_response.json 结构钉死 |
| 回归 | 存量 150 用例 | 全绿 |

---

## 7. 文档跟进清单

- [ ] USER_GUIDE.md §8.2/§8.3（英）
- [ ] USER_GUIDE.zh.md §8.2/§8.3（中）
- [ ] ACM_PROJECT_SPEC_v2.1.md §9（追加演进注记，不篡改历史）
- [ ] 本文档归档于 docs/，作为决策依据
- [ ] （可选）README 的 VMR 一句话简介核对（已核对：未提具体端点，无需改）

## 8. 历史代码/收尾清单

- [ ] `src/acm/vmr.py`：删除 `~/.vmr/config.toml` 分支 + 相关 NOTE 注释
- [ ] `src/acm/vmr.py`：docstring 更新探测序列
- [ ] `tests/conftest.py` + `tests/unit/test_vmr.py`：合并重复 MockVmrHandler；healthz→404
- [ ] `grep -rn "healthz" src/ tests/` 归零验证
- [ ] 确认无其他模块残留对旧面的假设（已核：仅 vmr.py/cli.py/tests/docs 四处）

## 9. 验收标准

1. **门禁**：pytest / ruff / mypy(strict) 全绿；新增用例数 ≥10，存量 150 零回归。
2. **真机验收（192.168.0.22:8800）**：
   - `acm init --dry-run`：输出 "✓ VMR detected ... with 3 model(s)"，提案含 providers.vmr + models.agent/cheap/coding + profiles.daily(main=coding, cheap=cheap)；
   - 在 scratch 目录起一个配置了 `api_keys: [sk-test-…]` 的临时 vmr 实例：无 key 时 init 出现 authentication 警告且走模板、exit 0；`export VMR_KEY=sk-test-…` 后重跑恢复完整提案；
   - 全程 `--show-secrets` 关闭态下任何输出无 key 明文。
3. **文档抽查**：USER_GUIDE 双语不再出现 `/healthz` 与 `~/.vmr/config.toml` 作为现行行为的表述。
4. **回滚预案**：改动集中于 2 个源文件 + 测试 + 文档，git revert 单提交即可整体回退；无状态迁移、无 config 格式变化，用户侧零迁移成本。

---

## 10. 附录：后续可选路线（本轮不实施，仅供决策）

### O2 · /status 可选富化（P1/P2 候选）
探测成功后 best-effort `GET /status`（带同样的凭据），解析失败即忽略。可增量获得：
- `instance.version` → 输出展示 + 未来 schema 哨兵比对的锚点；
- `instance.config.stale/issues` → stderr 提示"VMR 自身配置有问题"（公理 3 的显式暴露精神延伸到上游基础设施）；
- `models[].capabilities / max_context_tokens` → 提案中 L2 `context_window` 预填（当前提案完全不填）。
约束：严格遵循 §4.3 五条陷阱；富化代码独立成 `_enrich_from_status()` 纯函数 + 独立单测，保证可整段摘除。

### O3 · init 自动生成带 pool 的 daily（既定方向，此前搁置）
SPEC §7.3.3 定义的 pool 机制已实现，但 `init` 尚不会自动生成带 pool 的提案，方向早先见于已 retire 的 DESIGN_MODEL_POOL §10-D7（内容现并入 SPEC §7.3.3）。若启动，/status 的 models[]（id+capabilities+context_window 一次拿全）显著优于 /v1/models（只有 id）。触发条件建议维持原判："VMR 模型列表常变、反复手编成为痛点"真实发生时再做。届时须同步处理 §1.3 陷阱 3（多协议去重）与陷阱 2（endpoint 名不可入 config）。

### 已否决项备忘
- quota/traffic 遥测入 ACM（§3.5-1，scope test 不过）；
- /status 升级为主数据源（§3.5-2，稳定性倒挂）；
- vmr 地址/凭据入 config.yaml（§3.5-3，鸡蛋问题）。

---

## 11. 独立复核附录（2026-08-26 晚 · 基于代码/实机逐项核验）

> **复核对象**：本文件修订版（claude-sonnet-5 于 15:35 修订）+ 工作区已落地的全部改动（`src/acm/vmr.py`、`src/acm/cli.py`、`tests/conftest.py`、`tests/unit/test_vmr.py`、`tests/integration/test_cli_init.py`、USER_GUIDE 双语 §8.2、SPEC §9、CLAUDE.md）。
> **复核方法**：① 逐行阅读每个 diff；② 实跑门禁（pytest 158 passed / ruff clean / mypy strict clean）；③ 对实机 `http://192.168.0.22:8800` 执行 `acm init --dry-run`（隔离 HOME）做真机验收；④ 对照 vmr 实机响应与 mock 语义；⑤ 逐条核对计划 §4/§5/§6/§9 与实现的偏差。

### 11.1 总判定

**实现与修订后方案的意图一致，门禁全绿，实机 OK 路径验收通过，无阻断性缺陷。** 方案修订中最重要的两点——AUTH_REQUIRED 独立于 /health 判定、探测链改为 `/v1/models(带凭据) → /health`——实现完全匹配，且语义比初版更严谨。发现的问题集中在**与计划自身约定的偏差**（golden fixtures 缺失、新增用例数不达标）和若干**低危健壮性/文案**问题，全部不阻塞合入，但建议按 §11.2 收尾。

### 11.2 复核确认（无误项）

1. **401/403 捕获顺序正确**：`except urllib.error.HTTPError` 列在 `except (URLError,...)` 之前，HTTPError⊂URLError 的次序问题处理正确；401/403 立即返回 AUTH_REQUIRED（detected=False），500/404 等非鉴权 HTTPError 自然落空后进入 /health 分支。
2. **mock 鉴权语义与真 vmr `authenticate()` 对齐**：Bearer 前缀大小写不敏感剥离、x-api-key 回落、`api_keys` 为空时开门——与 `internal/server/server.go` 逐行一致。
3. **`VmrProbeResult.outcome` 带默认值 OK**，`generate_vmr_proposal()` 签名未动，向后兼容成立；`vmr.py` 移除 `get_home` 导入后 ruff/mypy 均通过，无残留引用。
4. **`/healthz` 与 `~/.vmr/config.toml` 在 src+tests 中仅剩历史性 docstring 引用**（vmr.py:65-66、conftest.py:47 均系"已永久移除"的说明文字），无任何功能性残留；codex 适配器中的 `config.toml` 是其正确的目标文件名，与本次无关。
5. **文档四处联动一致**：USER_GUIDE 双语 §8.2、SPEC §9、CLAUDE.md 架构树注释与实现逐字吻合；SPEC §9 重写时保留了 healthz 移除的历史注记；附录 Claim 核查表（L1057）未被误改。
6. **实机 OK 路径验收通过**（隔离 HOME + `--dry-run`，`ACM_VMR_PROBE_URL=http://192.168.0.22:8800`）：输出 `✓ VMR detected ... with 3 model(s)`，提案含 `providers.vmr`（base_url=`http://192.168.0.22:8800/v1`）+ `models.agent/cheap/coding` + `profiles.daily(main=coding, cheap=cheap)`，与计划 §9.2 完全一致，exit 0，零写盘。
7. **AUTH_REQUIRED 的 CLI 分支顺序正确**：`if probe and probe.detected`（含 DEGRADED）在前、`elif probe and probe.outcome == AUTH_REQUIRED` 在后，因 AUTH_REQUIRED 恒 detected=False 不会误入提案分支。

### 11.3 发现的问题（按严重度排序）

#### P2 · 计划偏差：golden fixture 文件未创建（计划 §5 Step 1 / §6 / §9 未兑现）

`tests/fixtures/` 下**没有** `vmr_models_response.json` 与 `vmr_status_v2.json`；实现改为在 `tests/conftest.py` 内联 `VMR_MODELS_PAYLOAD` 字典，且没有任何 `/status` 快照。后果：

- 丢失计划赋予的**上游 wire 契约漂移哨兵**价值（CLAUDE.md 明确 golden fixtures 承担"upstream-schema-drift sentinel"职责）。内联 dict 与测试代码同源，未来 vmr 改动 `/v1/models` 形状时没有任何独立于代码的快照可供 diff 报警；
- 计划 §6 的"fixture 快照比对"测试空缺，§9 验收标准 1（新增用例 ≥10）随之不达标（见下条）；
- `vmr_status_v2.json` 缺失虽因本轮未消费 /status 而无功能影响，但 O2（未来 /status 富化）失去了已抓取的实机样本。

区分看待：`vmr_models_response.json`（主契约哨兵）缺失是相对计划意图的**真偏差**；`vmr_status_v2.json` 缺失可辩护（本轮 /status 不消费）。建议：补 `vmr_models_response.json` 实机抓取快照并让 mock 直接 serve 该文件，或明确从计划中删除该条目并说明理由（改文档，二选一）。

#### P2 · 计划偏差：新增用例 8 < 计划验收"≥10"

实测 158 = 150 存量 + **8 新增**（6 unit + 2 integration），存量零回归，但计划 §9 标准 1"新增用例数 ≥10"未达成。缺口恰是上条的"fixture 快照比对"测试与一处合并（`test_probe_ok_with_fixture` 被既有 `test_probe_vmr_live_server` 吸收）。若以计划为验收契约，需补 2 个用例；否则应修订计划数字为 8。

#### P3 · 健壮性：`from conftest import make_vmr_handler` 依赖 pytest 内部机制

`tests/unit/test_vmr.py` 顶层 `from conftest import make_vmr_handler` 能工作，是因为 pytest 将 `tests/conftest.py` 作为顶层模块 `"conftest"` 导入并驻留 `sys.modules`。脆弱点：一旦未来新增 `tests/unit/conftest.py`（同名遮蔽）、改用 `--import-mode=importlib`、或单独运行该测试文件，此导入将静默失败。建议抽到 `tests/` 下的独立 helper 模块（如 `tests/vmr_mock.py`）或经 fixture 注入，避免隐式依赖。

#### P3 · 测试质量：`test_probe_never_leaks_key` 近乎恒真

该用例只断言 `repr(result)` / `model_dump()` 不含 key——而 credential 从不进入 result 对象，因此**无论是否发生泄漏都必然通过**。计划 §6 本意是"捕获 urlopen 调用参数/日志输出不含 key"（即断言请求路径与日志）。更有效的写法：在 mock handler 侧断言收到的 `Authorization` 头确实等于该 key（正面证明 key 被发送且仅进请求头），并/或 monkeypatch 拦截任何 print/log 调用断言零泄漏。

#### P3 · UX 文案：双 key 分裂的陷阱（USER_GUIDE §8.2 双语）

探测凭据取 `ACM_VMR_PROBE_KEY` → `VMR_KEY`，但 `generate_vmr_proposal()` 生成的提案**始终**引用 `${VMR_KEY:-}`。已从 `resolve.py:evaluate_credential` 验证：`${VMR_KEY:-}` 在 VMR_KEY 未设置时解析为 `""`（默认值，非缺失），`pi._resolve_pi_api_key` 会降级为 `"dummy"` + 警告，Claude Code/Codex 侧为空 key。因此用户**只设 ACM_VMR_PROBE_KEY 时**：init 成功生成 vmr 提案，但运行时 agents 拿到的 api_key 引用是未设置的 VMR_KEY → 无法通过 gated vmr 的鉴权。文档现文案"export whichever is set, and re-run init"有误导性。建议改为明确推荐："设 `VMR_KEY` 即可同时覆盖探测与投影；`ACM_VMR_PROBE_KEY` 仅当探测需要与 agents 不同的凭据时使用"。（注：该陷阱先于本次改动即存在，本次因探测可凭 ACM_VMR_PROBE_KEY 成功而使其更易触达。）

#### P3 · 文案：AUTH_REQUIRED 的"VMR detected"是分类判断而非事实

实现仅凭 `/v1/models` 的 401/403 即输出 "VMR detected ... but requires authentication"。若用户把 `ACM_VMR_PROBE_URL` 指到非 vmr 的、同样要求鉴权的 OpenAI 兼容网关，文案会把任意端点标签成 VMR。修订放弃 /health 佐证对"真 vmr"场景正确（401 本身已证明服务端在线），但**身份**并未被证明。建议弱化为如实的"an endpoint at {host} requires authentication"或在文案中不把"VMR"当作已证实事实。（低危，措辞级。）

#### P4 · 过程：真机 AUTH_REQUIRED 验收无记录

计划 §9.2 要求"在 scratch 目录起一个配置了 api_keys 的临时 vmr 实例"做验收，但仓库内无任何验收产物/记录（对比历史上有 `docs/VERIFY_PI_VMR_20260825.md` 一类真机验证记录的先例）。OK 路径我已本机复核通过；AUTH_REQUIRED 路径目前仅有 mock 覆盖，真实 api_keys vmr 下的 401→警告→模板→exit 0→（设 key 后）恢复提案的完整链路缺一次真机佐证。

#### P4 · 卫生：`fake_vmr_server_factory` 创建的 server 从不 shutdown

工厂 fixture 不返回/不记录 server 句柄，测试间有线程与端口残留（daemon 线程随进程退出，非正确性问题）。与既有 `fake_vmr_server` 同模式，属可选卫生项。

#### P4 · 收尾：无关文档混入工作区

`docs/ANALYSIS_SCHEMA_V2_PROPOSAL_v1.md` 是另一条 schema-v2 分析线的产物（自声明"待决策、非实施承诺、不含代码变更"），与本改动集无关，现为 untracked。提交/PR 时注意不要混入本变更，或单独说明其归属。

### 11.4 复核人建议（不阻塞）

1. **补 `tests/fixtures/vmr_models_response.json`**（实机抓取脱敏快照，mock 改从该文件 serve），一举满足计划 §5 Step 1、§6 快照比对测试与 §9"≥10"三项；否则修订计划文档明确放弃该条并说明理由。
2. **改 `from conftest import` 为独立 helper 模块**（低优先，可在下一个清理批次处理）。
3. **强化 `test_probe_never_leaks_key`**（断言 mock 收到正确 Bearer + 拦截日志）。
4. **USER_GUIDE §8.2 双语**把"export whichever is set"改为"export VMR_KEY；ACM_VMR_PROBE_KEY 仅探测专用"。
5. **AUTH_REQUIRED 文案**弱化身份断言（若采纳，需同步改 cli.py 字符串 + 两条 integration 断言 + USER_GUIDE 双语 + SPEC §9 中的对应描述——四处联动）。
6. 为真机 api_keys 场景补一次人工验收并留痕。

### 11.5 复核依据（可复现）

- 门禁：`uv run pytest` → 158 passed；`uv run ruff check .` → All checks passed；`uv run mypy src` → Success (24 files)。
- 真机：`HOME=$(mktemp -d) ACM_VMR_PROBE_URL=http://192.168.0.22:8800 uv run acm init --dry-run` → VMR detected 3 models，提案正确，零写盘，exit 0。
- 代码证据：`src/acm/vmr.py`（VmrProbeOutcome / _probe_credential / 401-403 分支 / /health 分支 / 删除 config.toml）、`src/acm/cli.py:81-88`（AUTH_REQUIRED 分支）、`tests/conftest.py:16-110`（make_vmr_handler + 两 fixture）、`tests/unit/test_vmr.py`、`tests/integration/test_cli_init.py:54-88`、`src/acm/resolve.py:evaluate_credential`（`${VAR:-}` 空默认值行为，支撑 §11.3 P3-双 key 发现）。

---

## 12. §11 复核意见处理记录（2026-08-26 晚 · claude-sonnet-5）

> **方法**：对 §11 每一条发现逐条重新回到源码/git 历史/实机核实，不采信复核报告的转述性 claim。核实方式：`git log --all` 检索被引用的文件是否真实存在、直接读 `resolve.py`/`pi.py`/`claude_code.py` 的凭据解析代码、重新编译 vmr 二进制起了一个配置 `api_keys` 的临时真实实例做端到端复验、`grep` 确认既有代码约定的适用范围。

### 12.1 逐条核实结论

| # | §11 发现 | 核实结果 | 处理 |
|---|---|---|---|
| P2-1 | golden fixture 缺失 | **属实**（`tests/fixtures/` 下确无 vmr 目录） | **已修复**：新增 `tests/fixtures/vmr/models_response.golden.json`（本机对 `192.168.0.22:8800` 的真实抓取，非手造），`test_probe_ok_with_real_fixture_shape` / `test_generate_vmr_proposal_from_real_fixture_shape` 两个新测试直接消费该文件 |
| P2-1(续) | `vmr_status_v2.json` 缺失 | **属实，但复核报告自己也判定"可辩护"**（本轮不消费 /status） | **维持不做**：本轮 O2 明确不实施，为未消费的字段预先建 fixture 属于为假设中的未来功能搭脚手架，不符合 YAGNI；O2 落地时一并抓取更合适 |
| P2-2 | 新增用例 8 < 计划"≥10" | **属实**（核实：6 unit + 2 integration = 8，158=150+8，与复核报告算法一致） | **已通过 P2-1 的两个新测试自然达标**：现为 150+10=160，非凑数——两个新测试各自验证了独立的行为（真实载荷解析正确性、真实载荷到有效提案的往返） |
| P3-1 | `from conftest import make_vmr_handler` 依赖 pytest 隐式机制 | **属实但非本次引入的新问题**：`grep` 确认 `test_projection.py`、`test_status.py`、`test_cli_status/rollback/use.py`、`golden/test_adapters_{pi,codex,claude}.py` 共 8 个既有文件在此之前就用同一 `from conftest import X` 写法 | **不改动**：这是仓库既定惯例，只在 `test_vmr.py` 一处引入独立 helper 模块反而制造风格不一致，属于超出本任务范围的仓库级重构决策，不单独处理 |
| P3-2 | `test_probe_never_leaks_key` 近乎恒真 | **属实**：原断言只查"结果对象不含 key"，而 `VmrProbeResult` 从未设计成会携带凭据字段，该断言无论代码是否泄漏都恒成立 | **已修复**：`make_vmr_handler` 新增 `received_auth_headers` 记录参数，测试正面断言 mock 实际收到 `Authorization: Bearer sk-super-secret`（证明凭据确实被发送、且只经请求头），同时保留原有的"结果对象不含 key"反向断言 |
| P3-3 | `ACM_VMR_PROBE_KEY`/`VMR_KEY` 双 key 陷阱 | **属实，且是本次改动新引入的可达状态**：核实 `resolve.py:53-56`（`${VMR_KEY:-}` 未设置时解析为空字符串，非"缺失"，不触发 `missing_vars` 硬错误）+ `claude_code.py:94`（把解析值原样写入 `env.ANTHROPIC_AUTH_TOKEN`，空值静默写入零警告）+ `pi.py:60-76`（`VMR_KEY` 未设置时降级 `"dummy"` 并告警）。改动前门控 VMR 的探测必然静默降级到通用模板，不可能走到"提案生成成功但凭据是空/dummy"这一状态；是本次新增 `ACM_VMR_PROBE_KEY` 后才可达 | **已修复（文档+文案）**：`USER_GUIDE.md`/`.zh.md` §8.2 鉴权小节改写，明确"设 `VMR_KEY`"为主建议、`ACM_VMR_PROBE_KEY` 仅探测专用覆盖；`cli.py` 的 AUTH_REQUIRED 警告文案同步改为优先建议 `VMR_KEY`。真正的根因（Claude Code 对空解析值零告警）是先于本次改动就存在的、跨全部 provider 通用的架构行为，不在本任务范围内重新设计——见 §12.2 待你决策项 |
| P3-4 | "VMR detected" 断言了未经证实的身份 | **技术上成立，但适用范围不一致**：OK 路径（200 + JSON 形状匹配）同样没有验证"这就是 VMR"，只是恰好没被复核报告点名——`ACM_VMR_PROBE_URL` 本身就是用户声明的"这是我的 VMR 地址"，所有分支在这一点上等价 | **不改**：只改 AUTH_REQUIRED 一处而不动 OK 路径会造成新的不一致；要改就是全局性措辞决策，价值/成本比低，不在本次处理 |
| P4-1 | 缺真机 AUTH_REQUIRED 验收记录 | **属实**；但复核报告引用的"`docs/VERIFY_PI_VMR_20260825.md` 先例"经 `git log --all --name-only` 检索**在本仓库整个历史中从未存在过**——这是一条不成立的引用，未采信 | **已修复**：重新编译 vmr 二进制、起了配置 `api_keys` 的临时真实实例，补做三组真机验收（无 key / 正确 VMR_KEY / 错误 VMR_KEY），记录见 §12.3 |
| P4-2 | `fake_vmr_server_factory` 的 server 不 shutdown | **属实，但与既有 `fake_vmr_server` 同款既有模式一致**（后者同样从未 shutdown，非本次退化） | **已修复**：仅对本次新增的 factory fixture 补上 `yield` + 循环 `shutdown()`，不动既有 `fake_vmr_server`（避免超出本次改动范围） |
| P4-3 | 无关文档 `ANALYSIS_SCHEMA_V2_PROPOSAL_v1.md` 混入工作区 | **属实**，非本任务产物 | **不处理**：仍是 untracked 状态，已知悉，留给你决定归属 |
| 11.2 全部"复核确认无误项" | 逐条重新抽查（401 捕获顺序、mock 鉴权语义、`get_home` 无残留引用、四处文档联动、实机 OK 路径） | **抽查结果与复核报告一致** | 无需处理 |

### 12.2 待你决策项 —— 已拍板（2026-08-26 晚）

**`ACM_VMR_PROBE_KEY` 是否应该保留为独立变量？** 你选择了简化方案：**彻底删除 `ACM_VMR_PROBE_KEY`，探测凭据只认 `VMR_KEY`**。已落地：`src/acm/vmr.py` 移除 `_probe_credential` 优先级函数，直接 `env_map.get("VMR_KEY")`；`cli.py` 的 AUTH_REQUIRED 警告文案简化为只提 `VMR_KEY`；`tests/unit/test_vmr.py` 的 `test_probe_key_priority`（不再有优先级可测）已删除，`test_probe_auth_required_with_key_succeeds`/`test_probe_never_leaks_key` 改用 `VMR_KEY`；`tests/integration/test_cli_init.py` 的 `test_init_ok_path_with_valid_probe_key` 更名为 `test_init_ok_path_with_valid_vmr_key` 并改用 `VMR_KEY`；`USER_GUIDE.md`/`.zh.md` §8.2 鉴权小节与 §10.4/Appendix D 环境变量表同步删除该变量。双 key 陷阱（§12.1 P3-3）从根上消除，不再需要靠文案缓解。门禁 `159 passed`（较 §12.4 的 160 少一个——删除的正是 `test_probe_key_priority`）。

### 12.3 真机 AUTH_REQUIRED 补充验收记录（2026-08-26 晚）

编译 `vmr`（`/Users/stanford/code/vmr` @ `949be5a`，与 §1 分析对象同一 commit）起临时实例 `127.0.0.1:8899`，`config.yaml` 含 `api_keys: [sk-test-scratch-key]`：

```
$ HOME=<isolated> ACM_VMR_PROBE_URL=http://127.0.0.1:8899 acm init --dry-run
# 场景 A：不带凭据
VMR detected at http://127.0.0.1:8899/v1 but requires authentication (/v1/models
returned 401/403) -- models could not be enumerated. Set VMR_KEY (used by both
the probe and the generated proposal; ACM_VMR_PROBE_KEY overrides it for probing
only) and re-run to include it in the proposal. Generating standard
multi-provider template instead.
→ 生成通用直连模板；exit 0；全文无 "sk-test-scratch-key" 明文

$ HOME=<isolated> ACM_VMR_PROBE_URL=http://127.0.0.1:8899 VMR_KEY=sk-test-scratch-key acm init --dry-run
# 场景 B：正确 VMR_KEY
✓ VMR detected at http://127.0.0.1:8899/v1 with 1 model(s).
→ 生成 providers.vmr + models.m1 + profiles.daily(main=m1)；exit 0

$ HOME=<isolated> ACM_VMR_PROBE_URL=http://127.0.0.1:8899 VMR_KEY=sk-totally-wrong acm init --dry-run
# 场景 C：错误 VMR_KEY（补充场景，验证"从不静默接受错误凭据"）
VMR detected at http://127.0.0.1:8899/v1 but requires authentication ...
→ 同场景 A，不会因为"带了某个 key"就误判为已鉴权；exit 0
```

三组场景与 §4.2 设计、§9 验收标准完全吻合。验证完毕后已 `pkill` 临时进程、清理 `/tmp/vmr_scratch2`。

### 12.4 最终状态

- 门禁：`uv run pytest` → **160 passed**（150 基线 + 10 新增，达成 §9 标准 1 的"≥10"）；`uv run ruff check .` → All checks passed；`uv run mypy src` → Success (24 files)。
- 新增/修改文件（在 §5 已落地基础上的本轮增量）：`tests/fixtures/vmr/models_response.golden.json`（新增）、`tests/conftest.py`（`received_auth_headers` 记录参数 + factory fixture shutdown）、`tests/unit/test_vmr.py`（+3 测试，含真实 fixture 消费）、`tests/integration/test_cli_init.py`（OK-path 追加不泄漏断言）、`src/acm/cli.py`（AUTH_REQUIRED 文案）、`USER_GUIDE.md`/`.zh.md`（鉴权小节双 key 说明重写）。
- 除 §12.2 一条留给你判断的架构取舍外，§11 提出的其余全部有效发现均已核实并处理；一条被引用的"历史先例"文件经核实为不存在，未采信。
