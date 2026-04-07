# Agent 架构：借鉴 Claude Code 源码与 ReAct 方向

## 宗旨（必须贯彻）

**本项目的 Agent 演进以仓库内 `claude_code/`（Claude Code 客户端源码）为首要参考实现**：在抽象（工具模型、上下文、权限、消息形态）与工程细节（结果截断、流式健壮性）上 **主动对照源码**，避免仅凭概念文档「空想架构」。  
Ryven 领域不同（节点 JSON 而非任意仓库改码），但 **「模型 ↔ 工具 ↔ 结果回填 ↔ 再采样」** 的闭环与 Claude Code **同源**。

---

## 1. 当前生成器 Agent 的形态（基线）

| 维度 | 现状（`ryven_node_generator/ai_assistant/`） |
|------|---------------------------------------------|
| 模型接入 | `ChatOpenAI`（LangChain），兼容 OpenAI 形态 API |
| 单轮产出 | 流式自然语言 + `<<<JSON>>>`，或函数调用，解析为 `AssistantTurn` |
| 历史「多轮」 | `self_repair.py`：**for 循环**内反复 **整段重生成** + 桩测，失败信息 **拼进下一轮 user 文本**；**不是** tool_result 驱动的 ReAct |
| 目标形态 | **ReAct 主循环**：思考 → **工具「改节点」** → **工具「测」** → 再思考，直到 `submit` 或停止条件；**「修改 + 测试」一律走工具**，由模型决定何时测、测什么 |

**结论**：旧 self repair 的价值在于 **桩测执行器可复用**；其 **外层 for 循环** 在坚定采用 ReAct 后应 **降级为可选兜底或移除**，避免 **双循环**（外层 for + 内层 ReAct）难以调试。

---

## 2. Claude Code 源码如何实现「Agent + 工具」（可对照文件）

以下路径均相对于仓库内 `claude_code/src/`。

### 2.1 工具不是裸函数，而是带生命周期与元数据的 `Tool`

**文件**：`Tool.ts`（核心类型）、`tools.ts`（注册表）

- **`Tool` 类型**（节选语义）：`name`、`inputSchema`（Zod/JSON Schema）、异步 **`call(args, context, canUseTool, parentMessage, onProgress)`** → `Promise<ToolResult>`；另有 `isReadOnly`、`isDestructive`、`maxResultSizeChars`、`validateInput`、`checkPermissions`、`prompt()` 等。  
- **注册**：`getAllBaseTools()` 返回 **当前环境可用的全部工具实例数组**（`tools.ts` 中按 feature flag、环境变量拼装 Bash、Read、Edit、MCP 等）。  
- **按上下文裁剪**：`getTools(toolPermissionContext)`（同文件）在权限上下文中 **过滤** 可用工具，避免一次性塞满无效工具。

**借鉴到 Ryven**：Python 侧实现 **`ToolSpec` / `RyvenTool`**：统一 `name`、`description`、`parameters`（JSON Schema）、**`execute(ctx, args) -> str`**，以及 **`readonly` / `max_output_chars`**；**「改节点」「跑桩测」各为一个工具**，由注册表挂进 ReAct 循环。

### 2.2 共享上下文 `ToolUseContext`

**文件**：`Tool.ts` 中 `ToolUseContext`

- 一次「查询」内共享：**`abortController`**、`readFileState`、`getAppState`/`setAppState`、**`options.tools`**（当前工具列表）、**`mainLoopModel`**、MCP 客户端、**`messages`** 等。  
- 工具通过 **同一 context** 访问会话状态、发通知、更新进行中 tool id 等。

**借鉴到 Ryven**：实现 **`AgentContext`**（或沿用 orchestration 层已有思路）：**项目根**、**当前节点快照**、`should_stop`、**只读/可写根路径**、可选 **`on_progress`**，**每个工具只接收 context + 参数**，避免全局单例。

### 2.3 消息层：用「是否含 `tool_use`」判断工具轮，而非盲信 `stop_reason`

**文件**：`utils/messages.ts`

- **`isToolUseRequestMessage`**：助手消息且 `content` 中 **存在 `type === 'tool_use'`** 即视为工具请求；注释明确 **`stop_reason === 'tool_use'` 不可靠**。  
- 用户侧 **`tool_result`** 与 `tool_use_id` 配对；另有 **reorderMessagesInUI** 等，保证 UI 与 API 边界一致。

**借鉴到 Ryven**：OpenAI 兼容接口下用 **`tool_calls` 非空** 作为「需要执行工具」的判据；结果以 **role=tool**（或厂商要求格式）写回，再 **追加一轮 assistant**。

### 2.4 权限：`canUseTool` 与 `permissions.ts`

**文件**：`utils/permissions/permissions.ts`（如 `hasPermissionsToUseTool`）

- 工具执行前走 **规则 + hook**（含无 UI 的 headless 场景）；**允许/拒绝/询问** 可改变 `updatedInput`。  
- Bash 等还与 **命令分类、只读模式** 联动。

**借鉴到 Ryven**：**`apply_node_patch`** 可默认允许或需确认；**`run_shell`** 必须走 **白名单/超时/权限**（与 Claude Code 的 Bash 策略同旨）。

### 2.5 Bash：`BashTool.tsx` + `bashSecurity.ts`

**文件**：`tools/BashTool/BashTool.tsx`、`tools/BashTool/bashSecurity.ts`

- **执行**：`exec` / 任务输出 / 可选 **SandboxManager**。  
- **安全**：解析 shell、拦截危险模式（进程替换、部分 zsh 特性等）、**只读命令校验**、**超时**、输出 **截断**；大结果走 **`toolResultStorage.ts`**（会话目录落盘 + 预览）。  
- **UI**：`renderToolUseMessage`、进度、长命令后台化等。

**借鉴到 Ryven**：若提供 `run_shell`，**默认关闭**；开启时 **cwd 锁项目、超时、max bytes**，结果 **截断或落盘摘要**。

### 2.6 主 API 调用与流式：`services/api/claude.ts`

**文件**：`services/api/claude.ts`

- 使用 **`anthropic.beta.messages.create(..., { stream: true })`**；**流式空闲 watchdog**、**卡顿检测**；注释说明 **工具输入 JSON 由调用方自行累积**，避免 SDK 层重复解析开销。

**借鉴到 Ryven**：多步 ReAct 时 **每步请求可取消**、**单连接空闲超时**，避免挂死。

### 2.7 子 Agent 工具子集

**文件**：`constants/tools.ts`

- **`ALL_AGENT_DISALLOWED_TOOLS`**、**`ASYNC_AGENT_ALLOWED_TOOLS`** 等：嵌套 Agent **缩小工具面**，防递归与风险。

**借鉴到 Ryven**：若日后有子任务，对工具列表 **显式白名单**。

### 2.8 侧路请求：`utils/sideQuery.ts`

- 轻量 **`beta.messages.create`**，与主循环共享鉴权/归因，用于分类器、搜索等 **不污染主 transcript**。

**借鉴到 Ryven**：意图分类、摘要可用 **小模型侧路调用**，与主 ReAct 历史分离。

### 2.9 工具入参：严格 JSON Schema（避免 `submit` 校验死循环）

Claude Code 侧 Tool 通常带 **`inputSchema` / `validateInput`**：类型不对会在执行前失败，而不是让主循环带着坏参数反复重试。

**借鉴到 Ryven**：OpenAI/LangChain 绑定的 function/tool 参数同样按 **JSON Schema** 校验（本地再由 Pydantic 校验 `AssistantTurn`）。典型坑：模型用 **空字符串 `""`** 表示「无」，但字段声明为 **`object` / `array` / `null`** 时，**`""` 非法**，会导致 `submit_node_turn rejected` 并占满步数。

**规范**：可选字段「无值」应 **省略该键** 或传 JSON **`null`**；**禁止**用 `""` 代替 `null`（尤其是 `config_patch`、`self_test_cases`）。`core_logic` 无变更时同样用 **`null`/省略**，不要用 `""`。

---

## 3. 映射到 Ryven：工具分层（「修改 + 测试」工具化）

| 层级 | 建议工具 | 作用 |
|------|----------|------|
| **只读** | `read_project_file` / `get_node_snapshot` | 对齐模板与当前节点，减幻觉 |
| **修改** | `apply_node_patch`（或 `propose_core_logic` + merge） | **结构化**改当前节点草稿，等价「可观测的编辑」 |
| **测试** | `run_stub_test` | 调用 **与现桩测同一执行器**，返回 stdout/失败栈摘要 |
| **交付** | `submit_node_turn` | 参数为完整 **`AssistantTurn` JSON**，经 `finalize_parsed_turn` 后 **结束 ReAct**，供 UI 应用 |
| **可选** | `run_shell` | 强限制，默认关 |

**最终 UI 契约不变**：仍以 **`AssistantTurn`（及 `finalize_parsed_turn` 的 dict）** 为一次用户请求的 **唯一对外交付**；ReAct 是 **达成该 JSON 的过程**。

**上下文预算（实现侧）**：对每次 API 请求限制 **进入模型的 user/assistant 条数**（`AI_CONTEXT_MAX_MESSAGES`，0=不截断），并将 **当前节点 JSON** 以 **紧凑单行** 形式放入 system 消息（`AI_CONTEXT_COMPACT_JSON`），以降低 token 与 CC 式「全量 transcript 无限增长」问题对齐。

---

## 4. 架构示意（与 Claude Code 同构的抽象）

```
用户输入
   ▼
┌─────────────────────────────────────────┐
│ ReAct 循环（对标 CC 主采样循环）          │
│  messages += assistant(tool_calls?)      │
│  → 执行 tools（ToolUseContext 式 ctx）    │
│  → tool_result → 再采样直到 stop 或上限    │
└─────────────────────────────────────────┘
   │ 唯一出口：submit_node_turn → AssistantTurn
   ▼
finalize_parsed_turn → main_window 预览 / 应用
```

- **不再依赖** 独立的 **`run_turn_with_self_repair` for 循环** 作为主线；桩测逻辑 **仅被 `run_stub_test` 工具调用**（代码复用 `self_repair` 模块内函数即可）。

---

## 5. 与 `docs/ai-self-repair-optimization.md` 的关系

- 该文档描述 **历史上已落地的 self-repair 多轮重试**；在 **ReAct + 工具** 成为主线后，其 **循环策略** 被 **工具循环替代**，**桩测执行器** 仍保留在 **`run_stub_test` 工具** 内复用。

---

## 6. 小结

- **Claude Code 可学之处**：`Tool` 契约、`ToolUseContext`、**工具注册与权限**、**tool_use / tool_result 消息语义**、Bash 与 **结果落盘**、流式 **健壮性**。  
- **Ryven 策略**：**借鉴 Claude Code 源码为默认立场**；**修改与测试均为工具**；**坚定 ReAct**；**`AssistantTurn` JSON 仍为 UI 核心契约**。
