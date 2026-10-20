<!-- // Ver 2026-10-20 16:10, by Opus 5.5 -->

# ACM → VMR 交接：Manifest 发布端

> **意图复述**：ACM 0.4 需要 VMR 发布 `GET /manifest`（模型目录）。本文把 VMR 侧需要做、已做、建议做的事交给 VMR 的维护者（或其 Agent）自行实施。**ACM 侧不再修改 VMR 仓库**——VMR 可能有并行进行的工作，合并、改写、取舍都由 VMR 侧决定。
>
> **范围**：In —— ACM 消费的契约、参考实现的位置与状态、联调结果、建议的后续改动。Out —— 对 VMR 仓库的任何直接操作。

## 1. ACM 消费的契约（Manifest v1）

权威定义：ACM 仓库 `docs/ACM_SPEC_v3.md` §4.2–§4.4；设计依据 `docs/ACM_VMR_Manifest_Analysis_and_Design_opus-5.5.md` §5.3。要点：

| 项 | 要求 |
|---|---|
| 路径与认证 | `GET /manifest`；配置了 `api_keys` 时需要 `Authorization: Bearer <key>`。401 / 403 → ACM 视为配置错误（退出 1）。**不要重定向**：ACM 不跟随重定向（避免凭据被带到别的主机），30x 等同不可达 |
| 缓存 | 返回 `ETag`；`If-None-Match` 命中返回 304。ACM 只缓存通过校验的文档 |
| 版本 | `manifest_version: 1`；其他值 → ACM 拒绝该来源 |
| `endpoints` | 键为协议名 `openai-completions` / `anthropic-messages` / `openai-responses`；值为客户端应直连的 base URL（openai-* 含 `/v1`，anthropic-messages 不含） |
| `models[]` | `id`、`protocols`（⊆ `endpoints` 的键）、可选 `display_name` / `description` / `roles` / `limit.{context, context_floor, output}` / `modalities.input` / `tool_call` / `reasoning` / `guarantee` |
| 角色唯一性 | 同一（协议, 角色）只能有一个模型，否则 ACM 判整份 Manifest 非法 |
| 未知即缺省 | 不知道的字段省略，不写 0 / false。ACM 忽略未知字段与未知角色 |
| 语义 | `limit.*` 是模型的**能力上限**（超过即不提供服务）；Agent 每次请求实际用多少由 Agent 自己决定。ACM 只把上限写进 Agent 描述模型的字段（如 OpenCode `limit.context`、Claude Code `CLAUDE_CODE_MAX_CONTEXT_TOKENS`），从不写 Agent 的用量预算 |

## 2. 参考实现（已复核，已 fast-forward 进 VMR `main`）

| 项 | 值 |
|---|---|
| worktree | `/Volumes/SSD2T/code/vmr-manifest` |
| 分支 / 提交 | `feat/manifest` @ `c1b31619`（单个提交，未推送；由 VMR 侧 Agent 在第二轮任务中 rebase 并重做，回报见 `/Users/stanford/code/vmr/docs/ACM_VMR_Task_Report_sonnet-5.5.md`） |
| 基点 | VMR `main` @ `3c6bb177`，是 `main` 的直接后继，可 `git merge --ff-only feat/manifest` |
| 改动 | `internal/server/manifest.go`（新增）、`internal/server/{manifest_test.go,server.go}`、`internal/config/{config.go,config_validate.go,check.go,manifest_meta_test.go}`、`CHANGELOG.md`、`config.example{,.zh}.yaml`、`docs/{KNOWN_ISSUES.md,UserGuide.md,UserGuide.zh.md}` |
| ACM 侧复核的门禁（只读运行） | `gofmt -l .` 无输出；`go vet ./...` 无输出；`go test -race ./...` exit 0（43 个包 ok） |
| 设计取舍 | 清单每次由路由快照现算（无第二份真相）；`meta` 只描述、永不影响路由；直连名 `provider:model` 不列入；ETag = 文档内容哈希；角色冲突是**加载期错误**（启动拒绝、热重载保留旧配置）；不信任 `X-Forwarded-*`，代理后必须设 `public_base_url`（未设而见到转发头时 WARN 一次） |

2026-10-20 16:05 只读检查：VMR `main` 已指向 `c1b31619`，远端没有 `feat/manifest`。用户已同意合入，并要求清理 worktree 和分支。清理交给 VMR 侧 Agent 做，见第三轮任务书 `/Users/stanford/code/vmr/docs/ACM_VMR_Task_Prompt_Round3_opus-5.5.md` §2。**此后 ACM 侧联调只从 VMR `main` 构建。**

## 3. 联调结果（2026-10-20）

### 3.1 第一轮（`6cef295e`，存根 Agent）

用 `feat/manifest` 编译的二进制（临时端口 18899、`api_keys` 开启、假上游），ACM 在临时 HOME 中执行，Claude Code / Codex / Pi / OpenCode 为存根二进制：

| 步骤 | 结果 |
|---|---|
| `acm init --vmr http://127.0.0.1:18899` | 读到 Manifest，生成 `vmr@default` / `vmr@fast` 的 profile |
| `acm use daily --yes` | 四个 Agent 写入成功；`status` 全部 SYNCED |
| 再次 `acm apply` | 带 `If-None-Match`，304，全部 noop |
| 停掉 VMR 后 `status` / `apply` | 使用缓存并告警 "served from cache … unreachable" |
| 修改 `max_context_tokens` 后重启 | 四个 Agent 变为 OUT_OF_SYNC，差异为上下文窗口 |
| `acm restore --baseline --yes` | ACM 新建的文件全部删除，回到初始状态 |

联调用的配置要点：`model_defaults` 声明 `capabilities` 与 `max_context_tokens`；`models.coding.meta.roles: [default]`，`models.cheap.meta.roles: [fast]`；`coding` 挂三个协议，`cheap` 挂两个。未验证：经 VMR 到真实上游的请求链路（上游为死端口）。

### 3.2 第二轮联调（2026-10-20 15:00，`c1b31619`，真实 Agent）

ACM 侧独立复跑，不依赖 VMR 回报的结论。环境：VMR 构建到 ACM 的 scratchpad、监听 `127.0.0.1:18921`、`api_keys` 开启；上游为 ACM 的 `tests/fake_gateway.py`（三协议、流式）；ACM 0.4.0 与 Claude Code / Codex / OpenCode / Pi 的**真实二进制**在 `env -i` 白名单环境、临时 HOME 下运行。VMR 配置：`main`（default，三协议）、`quick`（fast，completions + messages）、`deep`（reasoning，messages + responses）。

| 步骤 | 结果 |
|---|---|
| `curl /manifest` 无 key / 有 key | 401 / 200 + ETag |
| `acm init --vmr … --yes` | 识别 4 个 Agent，生成 `vmr@default` + `roles.{reasoning,fast}` |
| `acm use daily --yes` | 四个 Agent 写入，`status` 全部 SYNCED；配置文件 0600，不含 key |
| 真实 `claude -p` / `codex exec` / `opencode run` / `pi -p` | 全部 exit 0 返回 `OK`；上游收到 `big-model`（四个）与 `small-model`（OpenCode 标题生成走 `small_model`） |
| `acm apply` | 304，全部 noop |
| 热重载改 `max_context_tokens` | 四个 Agent OUT_OF_SYNC → `apply` → SYNCED |
| 热重载成角色冲突 | VMR 日志 `rejected, keeping current config`，ETag 不变，`apply` noop；`vmr check` 对冲突配置 exit 1 |
| 协议缺 `default`（`main` 去掉 anthropic-messages） | Claude Code ERROR（`no model with role 'default' on anthropic-messages`），其余三个照常写入，exit 2；符合 SPEC §4.4 |
| `public_base_url` 指向另一个源 | 修复前：ACM 静默改写四个 Agent 的端点。修复后：`use`/`apply`/`status`/`run` 均告警（见 §4 V4） |
| `history` / `rollback` / `restore --baseline` | 正常；baseline 恢复后 Agent 退出托管集合（D1），`use` 需显式点名才重新托管 |
| `acm run claude/codex/opencode/pi`，`-m vmr@fast` | 全部返回 `OK`，`-m vmr@fast` 打到 `small-model`；Agent 配置文件未被改动（变化的只有 Agent 自己的 session / sqlite） |

仍未验证：真实上游（真实 key、工具调用往返、长上下文）、真实 Caddy TLS 链路。

## 4. 建议 VMR 侧后续处理（按优先级）

### V1 反向代理后的 scheme —— 已处理（`c1b31619`）

不信任转发头；代理后必须设 `public_base_url`，未设而请求带 `X-Forwarded-*` 时 WARN 一次。ACM 侧另加了跨源告警作为客户端兜底（V4）。

### V2 发布输出上限 —— VMR 决定不做

`model_defaults` 没有输出上限的数据源，已登记到 VMR `docs/KNOWN_ISSUES.md`。ACM 继续写 32000 并告警。

### V4 端点与 Manifest 不同源 —— ACM 侧已处理

采纳 VMR 回报对 T3 的回答（不同源存在合理场景，不能判错）。ACM 的做法比"首次确认并记住"更简单：每次告警、不阻断、不新增状态；有意分开时，把 `manifest` 指向与端点相同的地址即可消除告警。https 清单配 http 端点时额外指出明文风险。见 ACM SPEC §4.3。

### V5（低，可选）"无 default 角色"告警按配置算，而发布按快照算

（读代码得出，未运行复现。）`checkManifestRoles` 遍历 `cfg.Models[*].Endpoints`；`buildManifest` 会跳过所有 provider 都被禁用的协议。若 `main` 在某协议上的 provider 全部禁用、而该协议仍由别的模型提供，清单在该协议上实际没有 `default`，`vmr check` 却不告警。ACM 侧会把对应 Agent 置 ERROR 并说明原因，所以不会静默出错；VMR 若想在源头提示，可让该检查与 `buildManifest` 共用同一份"可路由协议"判断。

### V6（中，已交给 VMR 第三轮）模型定位的表达

用户的问题：模型名可以随意起，Manifest 怎么表达"快 / 主力 / 深度"这类档次？结论：

- 档次由 `meta.roles` 表达（`fast` / `default` / `reasoning`），已经可用。
- 按任务选模型在 Agent 内部完成：Agent 选槽位，ACM 按角色填槽位，VMR 路由模型名。
- 不加自由的场景标签，不加档位数字。

交给 VMR 的三项：

- B1：`description` 写法约定，只改文档。
- B2：可选字段 `cost`，每百万 token 的价格。OpenCode schema 和 Pi 的 `registerProvider` 都有对应字段；单位和多候选时的聚合规则由 VMR 决定。
- B3：可选的 Pi `registerVirtualModel` 示例扩展，按角色路由。

ACM 侧待办：VMR 定下 `cost` 的字段名和规则后，ACM 负责解析，投影到 OpenCode / Pi，在 SPEC §4.2 登记，并核实 Pi `models.json` 是否接受 `cost`。

### V3 保持的不变量（无需改动，供后续修改时对照）

- 同一（协议, 角色）唯一，`vmr check` 继续把冲突当错误。
- `/manifest` 与业务接口同一套认证；不返回重定向。
- 未知字段省略而非置零。
- `gateway.version` 在开发构建中为 `"unknown"`，仅用于展示，可忽略。

## 5. 未验证的假设、风险与下一步

- **未验证**：真实上游链路（真实 key、工具调用、长上下文）；真实 TLS 终止代理（Caddy）。
- **风险**：若 VMR 侧改动契约字段名或语义，需同步更新 ACM SPEC §4 与 ACM 的 Manifest 客户端；任何契约变更先在两边文档登记。
- **下一步**：等 VMR 第三轮回报（清理结果、B1–B3）；之后从 VMR `main` 构建，用真实 key 在临时 HOME 中跑一遍 `init → use → 真实 Agent 发起一次带工具调用的请求`。
