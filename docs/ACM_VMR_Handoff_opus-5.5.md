<!-- // Ver 2026-10-20 12:00, by Opus 5.5 -->

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

## 2. 参考实现（已存在，未合并）

上一轮 ACM 重建时在 VMR 仓库建过一个**独立 worktree**，未碰主工作区：

| 项 | 值 |
|---|---|
| worktree | `/Volumes/SSD2T/code/vmr-manifest` |
| 分支 / 提交 | `feat/manifest` @ `6cef295e`（单个提交，未推送） |
| 基点 | `d91f647c`（与 `~/code/vmr` 的 `main` HEAD 相同；但主工作区有约 54 个未提交文件，合并前需先处理它们） |
| 改动 | `internal/server/manifest.go`（新增，233 行）、`internal/server/manifest_test.go`、`internal/server/server.go`（路由 `GET /manifest`，经 `s.auth`）、`internal/config/{config.go,config_validate.go,check.go,manifest_meta_test.go}`（`models.<name>.meta`、`public_base_url`、`vmr check` 角色校验）、`CHANGELOG.md`、`config.example.yaml`、`docs/KNOWN_ISSUES.md`、`docs/UserGuide.md` |
| 当时的验证 | `go test ./...`、`go vet ./...`、`gofmt -l` 通过（据 ACM 执行总结；本次未重跑 VMR 测试） |
| 设计取舍 | 清单每次由路由快照现算（无第二份真相）；`meta` 只描述、永不影响路由；直连名 `provider:model` 不列入；ETag = 文档内容哈希 |

**由 VMR 侧决定**：直接采用该分支、rebase 后采用、或按契约重新实现。ACM 只依赖 §1 的契约，不依赖实现细节。处理完后该 worktree 可删除（`git worktree remove /Volumes/SSD2T/code/vmr-manifest`）。

## 3. 联调结果（2026-10-20）

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

## 4. 建议 VMR 侧后续处理（按优先级）

### V1 反向代理后的 scheme（建议修）

`buildManifest` 在未设置 `public_base_url` 时用 `requestScheme(r)` 推导地址，而 `requestScheme` 只看 `r.TLS`。部署在 TLS 终止的反向代理（如 Caddy）之后时，发布的端点会是 `http://<host>…`，Agent 会按 http 去连。可选做法：

- 信任来自已知代理的 `X-Forwarded-Proto`；或
- 在文档与 `vmr check` 中明确：经反向代理对外服务时必须设置 `public_base_url`（`vmr check` 可在 `listen` 为回环地址且未设 `public_base_url` 时给出提示）。

### V2 发布输出上限（可选）

清单目前只有 `limit.context` / `context_floor`，没有 `limit.output`。OpenCode 的 schema 要求 `limit.output` 与 `limit.context` 成对出现，ACM 在未知时写保守值 32000（与 OpenCode 自身默认上限一致）并告警。若 VMR 的 `model_defaults` 将来声明上游模型的**最大输出能力**，可按与 `max_context_tokens` 相同的聚合规则发布为 `limit.output`（语义是能力上限，不是 Agent 预算）。不做也不影响正确性。

### V3 保持的不变量（无需改动，供后续修改时对照）

- 同一（协议, 角色）唯一，`vmr check` 继续把冲突当错误。
- `/manifest` 与业务接口同一套认证；不返回重定向。
- 未知字段省略而非置零。
- `gateway.version` 在开发构建中为 `"unknown"`，仅用于展示，可忽略。

## 5. 未验证的假设、风险与下一步

- **未验证**：真实上游链路；VMR 主工作区未提交改动与该分支的冲突情况（ACM 侧未查看其内容）。
- **风险**：若 VMR 侧改动契约字段名或语义，需同步更新 ACM SPEC §4 与 ACM 的 Manifest 客户端；建议任何契约变更先在两边文档登记。
- **下一步**：VMR 侧决定 §2 的处理方式并实施 V1；之后用真实 VMR 与真实 key，在临时 HOME 中跑一遍 `init → use → 真实 Agent 发起一次请求`。
