# ACM (Agent Config Manager)

[English](https://github.com/bigfatsea/acm/blob/main/README.md) | **中文文档**

> **The Unified, Non-Destructive Model Configuration & Projection Engine for AI Coding Agents.**  
> 专为 Coding Agent 生态设计的轻量、非破坏性、聚焦于模型层（Model/Provider）的统一配置单一事实源（SSOT）与投影/回滚 CLI 工具。

---

## 💡 核心设计理念 (Philosophy)

ACM 管理的是**字段**，不是文件；模型世界的描述只有一份，Agent 只是投影目标。

- **公理 1（SSOT）**：用户在 ACM 中维护一套与 Agent 无关的 Provider / 模型声明式配置（`~/.acm/config.yaml`），一键投影至本机所有 Coding Agent。
- **公理 2（非破坏性）**：ACM 只拥有它写入的受管字段，绝不拥有整个文件。未管理字段（MCP Servers、插件、Skills、Prompt 规则、会话状态等）保持**语义级 100% 零破坏**。
- **公理 3（精准可逆）**：默认回滚粒度是“ACM 管理的字段逆操作”，而非整文件粗暴替换——绝不误伤 Agent 在此期间写入的新状态；同时提供物理快照作为灾难恢复兜底。

---

## 🌟 核心特性 (Key Features)

- 🎯 **聚焦模型层（Strict Model Scope）**：严格管理 L1 连接（base_url、api_key 引用、方言、headers、proxy）与 L2 模型规格行为（model、context_window、max_tokens、reasoning effort/budget、temperature、能力位）。**坚决不触碰 MCP、插件、权限与系统提示词**。
- 🛡️ **字段所有权与 AST 保真（Field Ownership & Lossless Mutation）**：基于 `ruamel.yaml`、`tomlkit` 与保序 JSON/JSONC 编辑器在内存中完成 AST 外科手术，对受管字段 100% 确定性写入，对未受管内容 100% 零破坏保留。
- 🔒 **多重安全防线（Safety Engine）**：
  - **白名单 + 黑名单**双重拦截，物理禁止触碰敏感路径；
  - **外部漂移检测**：受管字段若被外部篡改，写入命令默认阻断，杜绝静默覆盖；
  - **写前快照 + 原子替换（`os.replace`）**：单文件永不出现“写一半”中间损坏态；
  - **全局非阻塞文件锁**（`fcntl`/`msvcrt`）：消除双终端并发竞态；
  - **Credential 安全引用**：仅存储 `${VAR}` 环境变量引用，输出默认敏感信息掩码。
- 🔄 **分层回滚体系（Layered Recovery）**：
  - 默认**字段级精准回滚**（基于 Journal 逆操作，Agent 期间写入的状态不受影响）；
  - `--hard` **物理快照还原**（灾难救砖兜底）。
- 🔌 **Adapter Protocol 纯函数契约**：每 Agent 一个独立模块，仅实现 `detect` / `config_paths` / `plan` 纯计算职责。所有适配器**源码内置 + 金样单测门禁**合并，拒绝动态代码反射执行的安全隐患。
- 🤝 **VMR 深度协同（VMR Co-op）**：一键探测本地 VMR（Virtual Model Router）并导入虚拟模型；无 VMR 时直连任何 OpenAI / Anthropic / 第三方端点同样是一等公民。
- 🚪 **随时可退、零侵入（Zero Lock-in）**：`acm release` 可一键恢复至接管前 pre-ACM 状态；若迁移至其他工具，直接卸载 ACM 即可，配置文件原地保持最后生效状态继续可用。

---

## 📖 官方文档与规格

| 文档 | 说明 |
|---|---|
| 🏛️ [**ACM 项目指导原则与核心规格 v2.2**](https://github.com/bigfatsea/acm/blob/main/docs/ACM_PROJECT_PRINCIPLE_v2.2.md) | **最高治理准则**：公理原则、非破坏性边界、六步安全写通道、适配器契约与设计哲学 |
| 📋 [**ACM MVP 实施方案与交付规格 v1.0**](https://github.com/bigfatsea/acm/blob/main/docs/ACM_MVP_ACTION_PLAN_v1.0.md) | **执行方案**：WP0–WP9 任务分解、8 大硬性验收标准、状态机定义、测试与验证规范 |
| 🔬 [**配置管理深度研报与最佳实践**](https://github.com/bigfatsea/acm/blob/main/docs/ACM_CONFIG_MANAGEMENT_DEEP_DIVE_AND_BEST_PRACTICES.md) | 40 年配置管理演进、双重所有权本质、字段所有权机制深度剖析 |

---

## 🚀 快速上手 (Quick Start)

### 1. 运行与安装

```bash
# 方式 A: 免安装直接运行 (推荐，基于 uvx，命令名仍为 acm)
uvx --from agent-config-manager acm status

# 方式 B: 全局安装到系统环境
uv tool install agent-config-manager
```

> 注：PyPI 分发名为 `agent-config-manager`（短名 `acm` 易与 ACM 学会等混淆且存在抢注风险），安装后的 CLI 命令名保持 `acm` 不变。

### 2. 核心工作流（≤ 3 条命令）

```bash
# 1. 初始化：扫描本机已装 Agent + 探测本地 VMR，交互确认后生成 SSOT 配置
acm init

# 2. 投影收敛：将激活 Profile 投影到本机所有已检测到的 Agent（或指定 Agent）
acm use daily
# 亦可单独投影指定 Agent: acm use daily claude_code

# 3. 查看状态：各 Agent 配置主状态机、外部漂移标注与投影损失告警
acm status

# 4. 差异比对：查看当前落盘配置 vs 期望状态（或 vs 快照）
acm diff claude_code

# 5. 精准回滚：字段级回滚上一次事务（不破坏 Agent 期间写入的权限与插件状态）
acm rollback claude_code

# 6. 退出托管：短期试用后完全恢复 pre-ACM 状态
acm release
```

> **关于迁出与卸载**：  
> ACM 遵循绝对的非侵入式哲学。如果您在长期使用后决定迁移到其他工具，**无需执行任何 release 命令**，直接卸载 ACM 并删除 `~/.acm/` 目录即可，所有 Agent 现有的配置文件将完整保留并继续正常工作。

---

## 🗺️ 架构总览 (Architecture Overview)

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                           acm CLI（typer + rich）                            │
│    init / status / doctor / use / apply / diff / history / rollback / release│
├─────────────────────────────────────────────────────────────────────────────┤
│                         Core Engine（纯逻辑，无 I/O）                         │
│  CoreConfig 加载校验 · Profile 解析 · Desired State 计算 · 幂等收敛 · ENV 引用解析   │
├──────────────────────────┬──────────────────────────────────────────────────┤
│      Safety Engine       │                  Adapter Layer                   │
│  原子写回 (os.replace)   │   Adapter Protocol (detect / config_paths / plan)│
│  内存所有权派生视图      ├──────────────────────────────────────────────────┤
│  白/黑名单 · 漂移检测    │   内置适配器（源码内置 + 金样门禁，拒绝动态反射加载）│
│  排他写锁 · 快照单纯追加 │   • Claude Code (JSON / env)   • Codex (TOML+JSON)   │
│  字段级回滚 · 密钥掩码   │   • Pi (JSON 注册式)           • Aider (YAML 角色)    │
├──────────────────────────┴──────────────────────────────────────────────────┤
│                     Format Writers（保真能力声明式写入器）                   │
│      JSON 保序编辑 · ruamel.yaml round-trip · tomlkit · JSONC · .env         │
└─────────────────────────────────────────────────────────────────────────────┘
```

---

## ⚙️ 核心配置示例 (`~/.acm/config.yaml`)

```yaml
version: 3

# ── L1 供应商：端点、凭据引用与内嵌 L2 模型 ──────────────
providers:
  vmr:
    protocol: openai
    base_url: http://127.0.0.1:8800/v1
    api_key: "${VMR_KEY}"           # 整字段引用环境变量，零密钥明文入库
    models:
      coding:
        context_window: 131072
        max_output_tokens: 16384
        temperature: 0.2
        capabilities: { vision: false, tools: native, json_mode: true }
        reasoning:
          effort: high               # 适配器自动转译为目标 Agent 专属字段
          budget_tokens: 16000       # 目标 Agent 无法表达时自动产生投影损失告警

  anthropic-official:
    protocol: anthropic
    base_url: https://api.anthropic.com
    api_key: "${ANTHROPIC_API_KEY}"

# ── L3 Profile：命名的成员集合 + opt-in 默认项 ────────────
profiles:
  daily:
    default: coding                  # 唯一驱动 Agent 默认模型字段的开关
    models:
      coding: vmr.coding              # label -> 模型引用；无论是否设置 default，
                                      # 都会注册进具备注册通道的每个 Agent
```

---

## 🎯 适配器覆盖规划 (Adapter Matrix)

- **P0 (Phase 1 / MVP)**：
  - **Claude Code**：`~/.claude/settings.json`（JSON + env 块注入 + 高密度非管字段保护，绝不触碰 `~/.claude.json` 运行时状态）
  - **Codex**：`~/.codex/config.toml` + `~/.codex/auth.json`（TOML + JSON 双文件原子事务，保真保留带注释的 `mcp_servers`）
  - **Pi**：`~/.pi/agent/models.json` + `settings.json`（注册式投影 + 方言/thinking level 映射，绝不触碰 `models-store.json`。*注：Pi 采用多 Provider 增量注册设计，切换 Profile 时在 `models.json` 中保留已有 provider 供历史会话复用，若需清理可直接删除未使用的条目或使用 `acm rollback`*）
- **P1 (Phase 2)**：
  - **Aider**：`~/.aider.conf.yml` + `~/.aider.model.metadata.json`（YAML round-trip + 角色模型 main/weak/editor）
  - **Gemini CLI**、**OpenCode**（JSONC 注释保留）
- **P2 (Phase 3 / 社区贡献)**：
  - OpenClaw、Hermes、Cursor/Cline（仅公开 settings 通道）

---

## 📄 开源协议 (License)

[Apache-2.0 License](https://github.com/bigfatsea/acm/blob/main/pyproject.toml)
