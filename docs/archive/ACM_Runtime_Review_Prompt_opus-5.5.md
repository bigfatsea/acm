<!-- // Ver 2026-10-20 12:30, by Opus 5.5 -->

# 任务：ACM 0.4 实际运行情况全面复核

## 目标

对 ACM（Agent Config Manager）0.4 做一次独立的、以**实际运行**为中心的复核：代码是否正确、安全、与设计一致，以及把它真正跑起来后，终端输出、写入的 Agent 配置文件和 `~/.acm/state` 下的数据是否符合预期、对用户是否可理解。找出明显的问题与缺口，能确认的给出证据，需要拍板的单独列出。

用你自己的判断决定先看什么、怎么验证、哪些地方值得深挖。下面只给上下文、范围和少量必须遵守的底线。

## 项目上下文

- 仓库：`/Volumes/SSD2T/code/acm`（分支 `main`，全部为本地提交，未推送）。先读 `CLAUDE.md`。
- ACM 是 CLI，没有 Web 页面。"运行起来之后看到的东西"指：命令的 stdout / stderr、退出码、交互式提示与勾选列表、它写入的 Agent 配置文件（Claude Code、Codex、Pi、OpenCode、Hermes、OpenClaw 等）、`~/.acm/state/`（history、版本库 objects、managed.json、Manifest 缓存）、`acm run` 实际启动 Agent 时注入的参数与环境。
- 治理文档（冲突时以前者为准）：`docs/ACM_PRINCIPLE_v3.md` → `docs/ACM_SPEC_v3.md` → `docs/ACM_Agent_Support_Matrix_opus-5.5.md`。用户视角：`docs/USER_GUIDE.md` / `.zh.md`、`README.md`。
- 已有结论与遗留：`docs/ACM_Execution_Summary_sonnet-5.5.md`（§5 遗留，§8 上一轮复审的修复与用户决定 D1–D6）。不必重复上一轮已修复的问题，但可以验证修复是否真的成立。
- 网关侧：VMR 的 Manifest 契约与联调记录见 `docs/ACM_VMR_Handoff_opus-5.5.md`。可编译运行的参考实现在 `/Volumes/SSD2T/code/vmr-manifest`（分支 `feat/manifest`），可用于联调。
- 开发命令：`uv sync`、`uv run pytest`、`uv run ruff check .`、`uv run mypy src`；本机二进制在 `.venv/bin/acm`。ad-hoc Python 用 `uv run --no-project python`。
- 本机已安装 Claude Code、Codex、Pi、OpenCode 的真实二进制；Hermes、OpenClaw 未安装。

## 范围

**In**：源码（`src/acm/`）与测试（`tests/`）；在隔离环境中端到端运行各命令（`init` / `use` / `apply` / `status` / `history` / `restore` / `rollback` / `prune` / `run`）；与本地 VMR 联调；用真实 Agent 二进制验证投影后的配置能被 Agent 正确读取；文档与实际行为的一致性；安全性（密钥是否泄露到输出、argv、文件权限、日志）。

**Out**：推送、打 `v*` 标签、发布 PyPI；修改 VMR 仓库；修改用户真实的 Agent 配置或 `~/.acm`。

## 底线（仅此几条）

1. **隔离运行**：所有运行都在临时目录中进行——设置 `HOME`、`ACM_HOME`、`PATH` 指向临时位置（必要时用存根二进制），绝不读写真实的 `~/.claude`、`~/.codex`、`~/.acm` 等。真实二进制只在隔离 HOME 下运行。
2. **不泄露密钥**：不要打印宿主机环境变量（历史上发生过一次泄露）；测试用伪造 key。
3. **只读对待 VMR 仓库**：可以编译到临时目录并运行，不在其中创建或修改任何东西。
4. **默认只报告不修改**：发现问题先记录与复现；如果某个修复很小且明确，可以在本地提交，但需在报告中逐条列出。

## 交付物

在仓库中写一份报告 `docs/ACM_Runtime_Review_<你的模型名>.md`（首行版本头 `<!-- // Ver YYYY-MM-DD HH:MM, by <模型名> -->`，中文），结构自定，但应包含：

- 一句话结论与复核范围；实际运行了什么（环境、版本、命令）。
- 问题清单，按严重度排序；每条有复现步骤或证据（命令、输出片段、文件位置 `path:line`），并区分"已复现确认"与"推断 / 未验证"。
- 文档与行为不一致之处。
- 需要用户拍板的问题，每个给出选项与你的建议。
- 未验证的假设、风险与建议的下一步。

完成后在对话中简要汇报结论和报告路径。
