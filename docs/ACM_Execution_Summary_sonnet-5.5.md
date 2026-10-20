<!-- // Ver 2026-10-20 12:10, by Opus 5.5 -->

# ACM 0.4 重建：执行总结

> **意图复述**：按已确认的 Action Plan（R1–R8）、历史与写入安全设计（H1–H7）和临时启动设计，把 ACM 从 0.3 的残缺实现整体重建为 0.4，并在 VMR 侧补上 Manifest 发布端；全程自行决策、不中断提问，难以抉择的项记入遗留。本文记录落地结果、过程中出现的新问题与处理、以及遗留事项。
>
> **范围**：In —— ACM 仓库（`main` 上的本地提交）、VMR 的 `feat/manifest` 分支（独立 worktree）。Out —— 推送、打 `v*` 标签、发布 PyPI、合并 VMR 分支（均未执行，见 §6）。

## 1. 结论

| 项 | 结果 |
|---|---|
| ACM 0.4（版本 `0.4.0.dev0`） | 完成：配置 schema v4、格式层、引擎（历史/恢复/漂移/锁/故障注入）、目录与 Manifest 客户端、10 个适配器、9 个命令、`acm run` |
| 测试 | 418 个用例：417 通过、1 跳过（纯 JSON 样本无注释，属预期）；`ruff check`、`mypy src`（strict，51 个源文件）全绿 |
| 真机验证 | Claude Code、Codex、Pi、OpenCode 的真实二进制对本地模拟网关通过（13 个 `real` 测试）；**Hermes、OpenClaw 本机未安装，仅金样** |
| 打包 | `uv build` 成功；在隔离环境安装 wheel 后确认 `adapters/data/*`（Codex 基础指令、Pi 扩展、NOTICE）随包可读 |
| VMR 侧 | `feat/manifest` 分支一次本地提交（`6cef295e`）：`GET /manifest`、`models.<name>.meta`、`public_base_url`、`vmr check` 角色校验、`/v1/models` 增字段；`go test ./...`、`go vet`、`gofmt` 全部通过 |
| 对外动作 | **均未执行**：无 push、无标签、无 PyPI、VMR 分支未合并 |

规模（粗略）：`src/` 6265 行，`tests/` 4564 行；测试分布 unit 248 / golden 114 / fault 12 / e2e 31 / real 13。

## 2. 执行过程

```mermaid
flowchart LR
    P0["P0 归档基线"] --> P1["P1 规格"]
    P1 --> P2["P2 骨架"]
    P2 --> P3["P3 格式层"]
    P3 --> P4["P4 引擎"]
    P4 --> P5["P5 目录与解析"]
    P5 --> P6["P6 适配器与 CLI"]
    P6 --> P6b["P6b acm run"]
    P6b --> P7["P7 VMR Manifest"]
    P7 --> P8["P8 文档与打包"]
    P8 --> P9["P9 总结"]
```

| 阶段 | 内容 | 提交 |
|---|---|---|
| P0 | 旧版打标签 `legacy-v0.3.0`、分支 `legacy/v0.3`；`main` 删旧代码；旧文档入 `docs/archive/`；旧版 183 测试先验证通过 | `5d437dd` `896e013` |
| P1 | `ACM_PRINCIPLE_v3.md`、`ACM_SPEC_v3.md`，重写 `CLAUDE.md` | `4f2aec0` |
| P2 | `core`、config v4、引用语法、CLI 骨架、测试基础设施 | `d965f25` |
| P3 | 自研 JSON/JSONC/JSON5 原位编辑器；TOML（tomlkit）、YAML（ruamel）；6 个 T1 语料 + hypothesis 属性测试（另用 10 倍强度复验） | `e55183d` |
| P4 | 内容寻址版本库 + 追加式历史；evaluate/commit/apply；restore（字段/整文件/op/baseline/rollback）；status；prune；故障注入 | `c92c1ca` |
| P5 | ModelCard、Manifest 客户端（ETag、缓存、失败矩阵、不跟随重定向）、角色 × 协议解析、探测与提案生成 | `e7a886d` |
| P6 | 适配器：Claude Code、Codex、Pi 族（Pi/OmO/Prime Agent）、OpenCode 族（OpenCode/MiMo Code/DevEco Code）、Hermes、OpenClaw；命令接线 | `c3a9a74` … `a375f21` |
| P6b | `acm run` 运行器、各适配器 `plan_launch`、`acm <agent>` 简写、子进程端到端测试 | `a375f21` |
| P7 | VMR Manifest（独立 worktree，不碰 VMR 主工作区的未提交改动） | VMR `6cef295e` |
| P8 | README（中英）、USER_GUIDE（中英）、SPEC 与支持矩阵回写、wheel 数据文件核对、最终门禁 | `93aa1ab` |
| P9 | 本文 | — |

## 3. 自行做出的决策

| 编号 | 决策 | 理由 |
|---|---|---|
| D1 | 提交直接落在 `main`，不推送 | R2 已批准在 `main` 删旧代码；对外动作留给用户 |
| D2 | 脚本用 `uv run --no-project python`；不在 shell 中定义 `python3` | 本机 `python3` 是别名，会触发项目构建，曾使多命令脚本中止两次 |
| D3 | 旧代码导出副本仅放 scratchpad 作移植参考，不入仓库 | 旧代码已有标签与分支留存 |
| D4 | 协议名统一为 `openai-completions` / `anthropic-messages` / `openai-responses`；去掉 `temperature`/`proxy`/`budget_tokens` 等只在 schema 里存在的字段；`acm prune` 取代 `history prune`；Manifest 非法或未知版本 → 退出 1 | 与 Pi 的 `api` 取值对齐；"改变模型就会变化"才属于范围 |
| D5 | 历史增加 `baseline` 记录（首次写入前先记）并记录每次的 `paths`；引擎对"上次记录有、本次计划没有"的路径追加 `Delete`（退役路径） | 使 baseline 恢复和换 profile 后的清理都有精确依据 |
| D6 | YAML：未修改时 `render()` 原字节返回；修改后按检测到的缩进重排，接受空白可能规整化 | ruamel 无法保证未改区域排版一致 |
| D7 | 格式层语料为按官方文档合成的"前 ACM 用户配置"样本，并在 README 声明 | 不拷贝用户真实配置 |
| D8 | Manifest 抓取不跟随重定向 | 避免凭据被带到其他主机 |
| D9 | CLI 命令接线放在适配器之后统一做 | 依赖适配器注册表 |
| D10 | OpenCode：`limit.context` 与 `limit.output` 必须成对，上下文已知而输出未知时写 `min(32000, context)` 并告警；沿用 `provider` 键（schema 标为 deprecated） | 与官方文档及已装 1.3.13 一致 |
| D11 | Hermes：具名 provider 前缀 `acm-`，`model.provider: custom:acm-<alias>`；`model` 为空串哨兵时整体替换为映射 | 避免与内建名冲突 |
| D12 | Prime Agent 的 `subagentDefaultModel` 不写 | 语义未核实，宁缺毋滥；支持矩阵 §10 已更正 |
| D13 | `meta`（VMR）永不影响路由；清单每次由路由快照现算；直连名不列入清单 | 网关只发布不决策；不另存第二份真相 |
| D14 | `restore --baseline` 成功后该 Agent 置为 `UNMANAGED`，直到下一次 `use`/`apply` | 否则 status 会把接管前的值当作漂移 |

## 4. 过程中遇到的新问题与处理

### 4.1 安全事件（需要用户知晓）

**测试输出泄露宿主机环境变量。** 测试夹具原先只清理部分环境变量；pytest 失败时打印了完整的 `Ctx`，其中含宿主机的真实环境变量，包括一个形似 `AI302_API_KEY` 的密钥，于是出现在本会话的终端输出里。
- 处理：夹具改为**白名单**环境（仅 `LANG`、`LC_ALL`、`TERM`、`TMPDIR`、`USER`、`LOGNAME` + 伪造的 `HOME`/`PATH`）；`Ctx.env` 字段 `repr=False`，不再进入任何 repr；真机测试只用本地模拟网关与伪造密钥。
- 残余：该密钥已出现在会话记录里。**建议按你的风险偏好决定是否轮换**（见 §5 L8）。
- 另：`~/code/vmr/docs/vmr-agent-dynamic-routing-protocol_agent.md` 中的一处明文 key 已换成 `sk-vmr-...`（按你的要求）。

### 4.2 引擎与格式层缺陷（测试发现并修复）

| 编号 | 问题 | 修复 |
|---|---|---|
| N4 | retire 之后遗留空父对象（如 `env: {}`），baseline 恢复不清理 | 恢复时无论目标键是否存在，都清理"目标版本没有的空祖先" |
| — | TOML 恢复后多出一个尾部空行 | `TomlDocument` 在 dirty 时规整化尾部换行 |
| — | `main()` 忽略 click 返回的 `Exit` 码；阻断结果缺 `code=2`；`restore` 未知 op 返回 0 | `rv = app(args=..., standalone_mode=False); return rv if isinstance(rv, int) else 0`；阻断设 `code=2`；无结果时抛 `NotFoundError`；阻断原因输出到 stderr |
| — | 若干弱断言（`or True`、不当的 `if False else`） | 全部收紧为真实断言 |

### 4.3 真机发现（对设计的修正）

| 编号 | 发现 | 处理 |
|---|---|---|
| N5a | Claude Code：`env` 置空 + `apiKeyHelper` 可行，helper 子进程继承环境变量 | 支持矩阵"待确认"项关闭 2 项 |
| N5b | OpenCode：首个请求是 `small_model` 的标题生成 | 测试断言改为模型集合 `{coding, cheap}`，同时证实 `fast` 角色被使用 |
| N5c | Codex：自定义 catalog 被严格解析 | 金样固定合规结构（含 `base_instructions`） |
| N5d | Pi：扩展注册模型要求每模型 `input/reasoning/contextWindow/maxTokens/cost` 必填，否则崩溃（`reading 'includes'`） | 随包扩展 `acm_pi_provider.ts` 对未知值写保守默认 |
| — | Pi 真机测试曾把 Pi 自己的运行时文件也纳入比较 | 只比较 ACM 受管文件 |

### 4.4 工具链

| 编号 | 问题 | 处理 |
|---|---|---|
| N1 | `ruff format` 0.16 会重排 Markdown 里的代码块，意外改动 `docs/` | `git checkout -- docs` 还原；`pyproject` 里 `extend-exclude = ["docs","_tmp","tests/fixtures"]` |
| N2 | Typer 0.27 内置 click，无独立 `click` 包，无法用 Group 子类做 `acm <agent>` 简写 | 在 `main()` 里对 argv 预处理 |
| N6 | `ruff format` 改写测试后，按精确文本锚点的补丁脚本失配 | 之后一律按行号或函数定位修改 |
| — | 重复的 pytest basename（golden 与 real 同名）导致收集冲突 | 真机测试改名 `test_real_*.py` |
| — | BSD `sed -i` 语法与 GNU 不同，一次 P8 编辑失败 | 改用 Python 脚本编辑 |

### 4.5 VMR 侧

- 确认 VMR 主工作区有你的未提交改动（`cmd/vmr/*`、多份文档等），因此所有改动都在独立 worktree `/Volumes/SSD2T/code/vmr-manifest`（分支 `feat/manifest`）中完成，主工作区未动。
- `meta.roles` 为封闭词表；同一协议上两个模型争同一角色 = `vmr check` 错误；某协议已有模型却无 `default` 角色 = 警告。
- 文档：`CHANGELOG.md [Unreleased]`、`docs/KNOWN_ISSUES.md`（"`meta` 永不影响路由"）、`config.example.yaml`、`docs/UserGuide.md` 新增 "Model manifest" 一节。

## 5. 遗留问题

| 编号 | 事项 | 影响 | 建议 |
|---|---|---|---|
| L1 | **CP1–CP4 评审未停下**：PRINCIPLE v3、SPEC v3、引擎、适配器按"尽量不中断"自行继续，尚未经你审阅 | 规格可能有未对齐的取舍（D4–D14 为主要自决点） | 先读 D 表与 SPEC §7、§9 |
| L2 | Hermes、OpenClaw 无真机测试（本机未安装），只有金样 | 上游格式或行为与文档不符时无法提前发现 | 安装后跑一遍并补 `tests/real/` |
| L3 | OpenClaw `--config-override` 内 `${VAR}` 是否被替换，Hermes `--base-url` 不带 `--api-key` 的行为，均未核实 | `acm run` 对这两者可能不可用 | 真机核实后更新支持矩阵 §10.1 |
| L4 | T2 成员（OmO、Prime Agent、MiMo Code、DevEco Code）的 `acm run` 默认关闭，持久投影仅金样 | 标注"实验性" | 有人真机确认后逐个放开 |
| L5 | **你的真实 `~/.acm/config.yaml` 是 v3 格式**，0.4 会报 `unsupported config version 3`（`providers.vmr.protocol` 也用了旧协议名、模型含 `capabilities`） | 升级后第一次运行即失败，需迁移 | 按 USER_GUIDE "从 0.3 升级" 操作；我没有改动你的任何真实文件 |
| L6 | VMR `feat/manifest` 未合并、未推送；ACM `main` 的 28 个本地提交（含更早的文档提交）未推送，无 `v0.4.0` 标签，未发布 PyPI | 对外尚不可见 | 审阅后自行决定；发布需另行指示 |
| L7 | 若干已知限制：OpenCode `provider` 键被 schema 标为 deprecated；JSON5 新插入的键带引号；YAML 修改后空白可能规整化；`auto_revert` 记录类型保留但"写后校验"未实现（中途写失败只回滚，不留记录） | 都是显式暴露的小风险 | 已写入 SPEC / 支持矩阵 §10 |
| L8 | §4.1 的密钥已出现在会话记录里 | 取决于该会话记录的保存方式 | 视情况轮换 |
| L9 | 语料是合成样本而非真实用户配置 | 格式层对"野生"配置的覆盖未经真实样本检验 | 欢迎脱敏样本加入 `tests/fixtures/` |

## 6. 未验证的假设、风险与下一步

**未验证的假设**
- 支持矩阵中引用官方文档的各项规则，在实现阶段只对 4 个 T1 Agent 做了真机复核；其余仍以文档为准。
- Manifest v1 的字段由 VMR 实现与 ACM 客户端两端各自按设计文档落地，二者之间只有 ACM 的模拟网关与 VMR 自己的测试，**没有跨项目联调**。

**风险**
- 上游 Agent 配置格式变动是持续成本（Magpie 维护记录显示近乎每天都有适配修复）。对策是金样兼作"上游漂移哨兵"、未知结构置 `ERROR` 阻断；但 Hermes/OpenClaw 没有真机哨兵。
- 版本库保存 Agent 配置的原样副本，可能含已存在的明文 key；目录权限 0700/0600，但需要用户知情（USER_GUIDE 已写明）。

**建议的下一步（按优先级）**
1. 审阅 L1（规格与自决点），有异议的项我来改。
2. 用 `acm init --force` 对一个**副本 HOME**（`ACM_HOME`/`HOME` 指向临时目录）对着真实 VMR 跑一遍，完成 ACM ↔ VMR 的首次联调（需先合并或运行 `feat/manifest` 分支）。
3. 安装 Hermes / OpenClaw，补真机测试并关闭 L3。
4. 通过后再决定：合并 VMR 分支、推送 ACM、打 `v0.4.0` 并发布 PyPI。

## 7. 验证记录

| 检查 | 命令 | 结果 |
|---|---|---|
| ACM 测试 | `uv run pytest -q` | 417 passed, 1 skipped（40 秒） |
| 风格 | `uv run ruff check .` | All checks passed |
| 类型 | `uv run mypy src` | Success: no issues found in 51 source files |
| 打包 | `uv build` + 隔离环境安装 wheel，读取 `acm.adapters/data` | 三个数据文件均在 |
| VMR | `go test ./...`、`go vet ./...`、`gofmt -l internal` | 全部通过、无输出 |

P8 阶段对**用户真实文件的唯一接触**是 `acm status --all` 读取 `~/.acm/config.yaml`（只读，因版本不符而报错退出，未写入任何文件）。

## 8. 复审附录（2026-10-20，Opus 5.5）

复审方式：通读引擎、CLI、解析、Manifest 客户端与适配器；在临时 HOME 中逐条复现；首次 ACM ↔ VMR 联调（结果见 `docs/ACM_VMR_Handoff_opus-5.5.md` §3）。

### 8.1 已修复

| 编号 | 问题（复现结论） | 处理 |
|---|---|---|
| B1 | `acm run` 对多 provider profile：默认 provider 的明文 key 被套用到所有 provider，发往其他 provider 的端点 | 每个 provider 一个变量（`ACM_RUN_KEY` / `ACM_RUN_KEY_<NAME>`），Pi / OpenCode / OpenClaw |
| B2 | 漂移明细未掩码，`use` / `apply` 被阻断时把新旧 key 明文打到 stderr | `describe_drift` 统一掩码 |
| B3 / B4 | `restore --baseline` 后 `acm use` 不经确认重新接管；"不再管理"不生效（之后每次都因漂移退出 2） | 受管集合 `state/managed.json`（正向列表）+ `npx skills` 式勾选；不在集合中的 Agent 跳过；重新纳入按接管确认 |
| B5 | 所有 Agent 投影失败时仍切换 `active` | 至少一个 Agent written / noop 才写 `active` |
| B6 | 单端点 Agent（Claude Code、Codex）把其他 provider 的模型写进槽位，请求发往默认端点 | 跨 provider 角色回落默认模型 / 删除槽位并告警；别名映射机制不变 |
| B7 | `init --force` 的 `config.yaml.bak` 为 0644 | 0600 原子写 |
| — | 掩码误伤 `CLAUDE_CODE_MAX_CONTEXT_TOKENS` 等计数字段 | `*tokens` 计数字段不掩码 |
| — | `prune --keep 0` 使所有 Agent 变为 UNMANAGED、丢失漂移基准 | `--keep` 下限 1 |
| — | 非法 Manifest 先写缓存再校验 | 先校验后缓存 |
| — | SPEC 声称独占文件路径受引擎校验，实际未实现 | 引擎强制独占文件位于 `~/.acm/owned/` |
| — | no-op 时每次重复投影告警 | 只在写入 / 预览 / 失败时输出，`--verbose` 始终输出 |
| — | 发布前无测试门禁；版本仍为 `0.4.0.dev0` | 新增 `ci.yml`（ubuntu + macOS：ruff、mypy、pytest），`release.yml` 依赖它并校验标签与版本一致；版本 `0.4.0` |

### 8.2 用户拍板

| 编号 | 决定 |
|---|---|
| D1 | 受管 Agent 由用户勾选（参照 `npx skills`）：只列检测到的 Agent，受管默认勾选，未勾选跳过 |
| D2 | 接管时移除的 key 必须可恢复（已由历史保证并实测）；订阅 / OAuth 登录存储永不受管，切回订阅无需重新登录（USER_GUIDE「订阅登录」） |
| D3 | VMR 的 `limit.*` 是能力上限，Agent 的用量预算由 Agent 决定；ACM 只写能力字段（PRINCIPLE §2.2 L2） |
| D4 | 0.3 用户的基线为 0.3 时期的文件，文档写明 |
| D5 | ACM 不再修改 VMR 仓库，改为交接文档 `docs/ACM_VMR_Handoff_opus-5.5.md` |
| D6 | 先修复与 CI，版本 0.4.0；推送与打标签由用户执行 |

### 8.3 仍未完成

- Hermes、OpenClaw 真机测试（L2、L3）；T2 成员 `acm run`（L4）。
- 经真实 VMR 到真实上游的请求链路未验证。
- Codex / OpenCode / Pi 的登录存储位置为基于经验判断（Claude Code 已对照官方文档）。
- 交互式勾选只有单元测试与一次伪终端手测，无自动化端到端测试。
