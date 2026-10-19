// Ver 2026-10-07 02:30, by vmr/agent
// ACM (Agent Config Management) 完整架构设计方案 v1.0
// 遵循 VMR 设计哲学：单一职责、关注点严格隔离、无痕恢复与原子快照

# ACM (Agent Config Management) 系统架构与设计方案 (v1.0)

> **项目代号**：`acm` (Agent Config Management)  
> **核心定位**：本地优先、轻量级、面向全生态 AI Coding Agent 的模型配置管家与无痕版本快照引擎。  
> **设计基准**：继承 VMR 极简与确定性哲学（严格分离 L0 本地配置平面与 L1/L2 网络路由平面），彻底解决 Magpie / CC Switch 破坏性覆写、配置污染及无法无痕回滚的致命缺陷。

---

## 一、 为什么立项 ACM？它与 VMR 的关系是什么？

### 1.1 核心痛点与定位分水岭

在当前 Coding Agent 实践中，开发者面临两大互补但完全正交的痛点：
1. **网络层痛点（由 VMR 解决）**：出网流量的高可用容灾、Prompt Cache 亲和保护、协议字节保真透传、任务法医审计与凭据安全过滤（L1/L2 运行时）；
2. **本地文件系统痛点（由 ACM 解决）**：各个 Coding Agent（Claude Code, Cursor, OpenClaw, Codex, Pi, Cline 等）的本地配置文件格式各异、路径分散，模型切换门槛高，且市面工具（如 Magpie、CC Switch）存在**粗暴覆写原文件、破坏原有注释与结构、无法确定性无痕恢复**的问题（L0 本地持久化）。

```
┌────────────────────────────────────────────────────────────────────────────────────────┐
│                        ACM 与 VMR 的双子星分层协作架构                                 │
└────────────────────────────────────────────────────────────────────────────────────────┘

  [ L0 客户端配置管理面 ] ──▶ 【 ACM (Agent Config Management) 】
    - 职责：管理本地 ~/.claude/settings.json, ~/.codex/config.toml 等本地文件
    - 特性：GUI 菜单栏 + CLI、原子版本快照 (Generation Tree)、无痕逆向补丁恢复 (Pristine Rollback)
    - 边界：只管模型连接（Base URL, Model Name, Context, Thinking），绝对不碰 MCP / Prompts
         │
         │ (一键注入：将各 Agent 的 Base URL 指向 127.0.0.1:8800)
         ▼
  [ L1/L2 本地网络代理面 ] ──▶ 【 VMR (Virtual Model Router) 】
    - 职责：单静态二进制守护进程，拦截出网 HTTP/SSE 流量
    - 特性：三协议独立物理通道、Byte-Faithful 零翻译透传、被动 Failover、Prompt Cache 亲和、Agent Guard
    - 边界：坚决不碰客户端本地配置文件，只专注网络报文生命周期与飞行记录仪 (audit.jsonl)
```

**立项铁律**：ACM 必须作为独立开源项目独立演进。它可以独立对接任何第三方模型平台（OpenRouter、DeepSeek、SiliconFlow 等）；当检测到本地有 VMR 运行时，提供 `acm link vmr` 的丝滑极简联动，成为 VMR 的最强前置引流入口。

---

## 二、 GUI 技术选型深度评估与推荐

ACM 作为面向终端开发者的日常效率工具，**拥有直观的桌面 UI（托盘/菜单栏常驻 + 快速下拉切换）是抢占心智的关键**。我们对主流轻量级 GUI 技术栈进行了系统性横向对比：

| 选型方案 | 内存驻留 (RAM) | 二进制打包体积 | 跨平台支持 (macOS/Win/Linux) | 原生托盘/菜单栏能力 | 社区生态与维护心智 | 综合评分 |
|---|---|---|---|---|---|---|
| **方案 A：Go + Wails v3 (首选推荐 ⭐⭐⭐⭐⭐)** | **~15MB - 25MB** | **~12MB - 18MB** | 原生绑定系统 Webview2 / WebKit | 原生支持 Tray / Menubar / 浮窗无边框 | Go 语言单二进制交付，与 VMR 工具链代码资产高度复用 | **9.6 / 10** |
| **方案 B：Rust + Tauri v2 (强力竞品 ⭐⭐⭐⭐)** | ~25MB - 35MB | ~8MB - 15MB | 优秀（桌面+移动端） | 插件化支持 Tray 极佳 | Rust 内存极安全，但编译速度慢，Go 生态开发者上手门槛高 | **9.1 / 10** |
| **方案 C：Flutter Desktop (备选方案 ⭐⭐⭐)** | ~45MB - 60MB | ~25MB - 40MB | 优秀（自绘引擎） | 托盘与系统级深度集成需要多套第三方插件 | UI 渲染一致性极高，但 Dart 运行时偏重，不是系统工具首选 | **7.5 / 10** |
| **方案 D：Electron (淘汰方案 ❌)** | 120MB - 200MB+ | 80MB - 150MB+ | 优秀 | 成熟但笨重 | 违背 VMR 极简克制哲学，严重消耗系统内存（参考 CCR） | **4.0 / 10** |

### 选型推荐裁定：**方案 A (Go + Wails v3)**
- **推荐理由**：
  1. **与生态协同度最高**：ACM 核心文件解析、AST 补丁与版本哈希算法完全可以用纯 Go 实现（共享 VMR 的严格单元测试与代码习惯）；
  2. **轻巧且原生**：Wails v3 深度优化了菜单栏（MenuBar Panel）生命周期，点击托盘图标秒级呼出无边框面板，失焦自动收起，内存占用通常低于 20MB；
  3. **前端技术自由**：UI 界面采用纯原生 HTML/CSS/TypeScript（或轻量 Preact/Svelte），零打包体积包袱。

---

## 三、 ACM 核心架构与四大设计原则（对照 VMR 哲学）

### 原则 1：关注点严格隔离（Strict Model-Scope Isolation）
- **绝不范围蔓延**：吸取 CC Switch 把 MCP Server、Skills 插件、Prompt 模板搅合在一起导致用户配置文件被洗掉的惨痛教训。
- **ACM 仅治理模型连接的核心五要素**：
  1. `base_url` / `api_base`
  2. `model` / `model_name`
  3. `api_key` / 环境变量映射
  4. `context_window` / `max_tokens` (深度配置)
  5. `thinking_budget` / `reasoning_effort` (思考链预算)
- **绝对不触碰**：用户的 MCP Servers、自定义 Prompts、文件权限、插件开关（如 Claude Code 的 `enabledPlugins` 和 `hooks`）。

### 原则 2：无痕恢复与逆向补丁（Pristine Invertible Patching）
- 拒绝粗暴的全量覆写（Overwriting）。
- 采用 **RFC 6902 JSON Patch + AST-Preserving CST（保持所有注释、空行与缩进）**：
  - 接入新配置时，仅生成精确的增量补丁；
  - 退出或重置时，应用反向补丁（Inverse Patch），原文件恢复到**物理字节完全一致的初始状态（Byte-Identical Pristine State）**。

### 原则 3：Git-like 世代版本快照树（Generation Snapshot Engine）
- 每一次配置变更，自动在 `~/.acm/history/<agent>/` 下生成不可篡改的原子快照：
  - `gen-001 (Pristine 初始备份)`
  - `gen-002 (切至 DeepSeek 直连)`
  - `gen-003 (切至 VMR 本地路由)`
- 支持秒级查看版本差异（`acm diff`）与任意世代穿梭回滚（`acm rollback`）。

### 原则 4：配置热校验防手滑（Pre-Flight Dry Run Validation）
- 在任何配置落盘前，运行沙箱语法检验与端点连通性干跑（Dry Run），确保生成的配置绝不会导致 Agent 启动即崩溃。

---

## 四、 核心数据模型与状态机设计

### 4.1 目录组织结构 (`~/.acm/`)

```
~/.acm/
├── acm.yaml                  # ACM 全局配置与已注册 Profile 池
├── active_state.json         # 当前各 Agent 处于哪个 Generation 快照
└── history/                  # 各 Agent 的历史版本快照库
    ├── claude_code/
    │   ├── gen-000_pristine.jsonc  # 首次使用时捕获的绝对纯净备份
    │   ├── gen-001_deepseek.patch  # 世代 1 变更补丁
    │   ├── gen-002_vmr.patch       # 世代 2 变更补丁
    │   └── ledger.jsonl            # 变更日志与 SHA256 校验和
    ├── cursor/
    └── codex/
```

### 4.2 核心配置文件规格 (`acm.yaml`)

```yaml
version: "1.0"

# 通用 Model Profiles（一次定义，各 Agent 自动投影映射）
profiles:
  vmr-local:
    label: "VMR 本地高可用路由"
    base_url: "http://127.0.0.1:8800"
    model: "smart-coder"
    api_key: "sk-vmr-local-token"
    context_window: 128000
    thinking_budget: 4096

  deepseek-direct:
    label: "DeepSeek 官方直连"
    base_url: "https://api.deepseek.com/v1"
    model: "deepseek-chat"
    api_key: "${DEEPSEEK_API_KEY}"
    context_window: 64000

  claude-official:
    label: "Anthropic 官方 Pro"
    mode: "native"  # 声明走原生默认认证，即回滚到 Pristine 状态
```

---

## 五、 UI 交互与菜单栏体验规划（参考与超越 Magpie）

### 5.1 托盘下拉轻量控制台面板 (MenuBar Panel)

```
┌───────────────────────────────────────────────┐
│  ACM — Agent Config Management         [⚙️] [✕]│
├───────────────────────────────────────────────┤
│  ⚡ Active Profile: [ vmr-local          ▼ ]  │
├───────────────────────────────────────────────┤
│  Managed Agents               Current Target   │
│  ───────────────────────────────────────────  │
│  ● Claude Code               smart-coder @VMR │
│  ● Codex CLI                 smart-coder @VMR │
│  ● Cursor                    deepseek-chat    │
│  ● OpenClaw                  smart-coder @VMR │
│  ○ Pi Agent                  (Native Default) │
├───────────────────────────────────────────────┤
│  Snapshot History (Claude Code)               │
│  ┌──────────────────────────────────────────┐ │
│  │ [●] Gen-3 (Now): vmr-local (127.0.0.1)   │ │
│  │ [ ] Gen-2 (Yesterday): deepseek-direct   │ │
│  │ [ ] Gen-1 (Original): Pristine Native    │ │
│  └──────────────────────────────────────────┘ │
│  [ ↩️ 一键无痕恢复初始状态 ]    [ 🔍 查看 Diff ] │
└───────────────────────────────────────────────┘
```

1. **一键全局切换**：顶部下拉框直接将全部已激活 Agent 批量对齐到指定 Profile；
2. **单 Agent 差异化控制**：支持单选特定 Agent 独立切换；
3. **安全恢复显眼可见**：底部常驻 `一键无痕恢复初始状态` 按钮，给予用户绝对掌控感，彻底消除“被工具绑架改不回去”的心理负担。

---

## 六、 落地路线图与开发里程碑

- **Milestone 1 (L0 核心内核)**：
  - 实现纯 Go 的 CST JSONC / TOML 解析器与 RFC 6902 Patch 引擎；
  - 实现 `~/.acm/history/` 世代快照树与 `pristine` 无损回滚逻辑；
  - 交付基础 CLI：`acm list`, `acm use <profile>`, `acm rollback`, `acm diff`。
- **Milestone 2 (Wails v3 桌面端)**：
  - 接入 Wails v3 托盘与 Menubar 原生生命周期；
  - 实现极轻量 Webview 交互面板（暗黑系、无边框、失焦收起）；
  - 支持首批 6 款核心 Agent（Claude Code, Codex, Cursor, OpenClaw, Pi, Cline）。
- **Milestone 3 (VMR 深度握手)**：
  - 自动探测本地是否运行 VMR（探测 `127.0.0.1:8800/health`）；
  - 自动读取 VMR 的虚拟模型列表，并在 ACM 界面一键生成对应的 VMR Profiles。
EOF