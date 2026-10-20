# ACM（Agent Config Manager）

[English](README.md) | **中文**

> 用一份声明式配置管理所有 AI 编程 Agent 的模型设置：按字段投影到本机每个 Agent，只改该改的，随时可恢复。

ACM 以 `~/.acm/config.yaml` 作为「用哪些 provider / 模型」的唯一事实来源（SSOT），只把这些字段写入 Claude Code、Codex CLI、Pi、OpenCode、Hermes Agent、OpenClaw 及其家族成员的配置文件。文件里的其余内容——MCP、插件、skills、hooks、权限、提示词、注释、键顺序——逐字节保持原样。

## 为什么用

- **换模型只改一处。** 切换 provider 或 profile 一次，所有已安装的 Agent 跟随。
- **非破坏。** ACM 只拥有「字段」，不拥有整个文件。每次写入前都会重新解析并断言：只要受管字段之外有任何变化，就不写盘。
- **每个状态都能恢复。** 每次写入都进入内容寻址的历史库；`acm restore` 可把受管字段恢复到任一历史版本（`--file` 恢复整文件），恢复本身也可撤销。
- **漂移显式暴露。** 受管字段被手工或 Agent 改过时，ACM 阻断并展示差异，绝不静默覆盖。
- **配置里没有密钥。** 只存 `${VAR}` 引用；输出默认掩码。
- **先试再定。** `acm run opencode` 一次性用配置好的模型启动 Agent，不写 Agent 的任何配置。

## 安装

```bash
uv tool install agent-config-manager     # 或：pipx install agent-config-manager
acm --version
```

需要 Python ≥ 3.12，macOS 或 Linux。

## 快速开始

```bash
export VMR_KEY=sk-...                      # 你的网关或 provider 所用的 key
acm init --vmr http://127.0.0.1:8800       # 探测 Agent 与网关，生成 ~/.acm/config.yaml 提案
acm use daily                              # 勾选要管理的 Agent，投影提案中的 profile「daily」（先确认）
acm status                                 # SYNCED / OUT_OF_SYNC / DRIFTED / ERROR / UNMANAGED
acm history                                # ACM 写过什么（新→旧）
acm restore --baseline                     # 回到 ACM 接管之前的样子
```

没有网关？手写配置即可（见 [使用指南](docs/USER_GUIDE.zh.md#配置)）——任何兼容 OpenAI / Anthropic / Responses 的端点都可以。

一次性启动，不写 Agent 文件：

```bash
acm run claude -m vmr@reasoning            # 按角色选模型（`vmr` 是 init 按网关命名的 provider）
acm run pi                                 # 有 fast/reasoning 角色时，Pi 使用 acm/auto，按思考档位 low/medium/high 选模型
VMR_URL=https://vmr.lan VMR_KEY=sk-... acm opencode   # 零配置；`acm <agent>` 是 `acm run` 的简写
```

## 支持的 Agent

| Agent | 层级 | `acm run` | 真机二进制验证 |
|---|---|---|---|
| Claude Code | T1 | 支持 | 已验证 |
| Codex CLI | T1 | 支持 | 已验证 |
| Pi | T1 | 支持 | 已验证 |
| OpenCode | T1 | 支持 | 已验证 |
| Hermes Agent | T1 | 支持 | 未验证（仅金样测试） |
| OpenClaw | T1 | 支持 | 未验证（仅金样测试） |
| OmO、Prime Agent（Pi 家族） | T2 | 暂不支持 | 否 |
| MiMo Code、DevEco Code（OpenCode 家族） | T2 | 暂不支持 | 否 |

T1 有独立代码路径；T2 是家族内仅参数不同的成员，在有人真机确认前标注为实验性。

## 网关 Manifest

网关可发布 `GET /manifest`（模型、协议、角色 `default / reasoning / fast / subagent / review`、上限与能力），ACM 直接读取目录，不必手工抄写。[VMR](https://github.com/bigfatsea/vmr) 已实现，任何网关都可实现。格式见 [SPEC §4](docs/ACM_SPEC_v3.md)。

## 文档

| 主题 | 文档 |
|---|---|
| 用法、配置参考、各 Agent 映射、排障 | [docs/USER_GUIDE.zh.md](docs/USER_GUIDE.zh.md)（[English](docs/USER_GUIDE.md)） |
| 原则与边界 | [docs/ACM_PRINCIPLE_v3.md](docs/ACM_PRINCIPLE_v3.md) |
| 实现规格 | [docs/ACM_SPEC_v3.md](docs/ACM_SPEC_v3.md) |
| 参与开发 | [CLAUDE.md](CLAUDE.md) |

## 开发

```bash
uv sync
uv run pytest                  # 单元 / 金样 / 故障注入 / 端到端；Agent 未安装时真机测试自动跳过
uv run ruff check . && uv run mypy src
```

## 许可证

Apache-2.0
