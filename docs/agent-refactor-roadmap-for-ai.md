# Ryven 节点生成器 Agent 分阶段重构规格（供分次交给 AI 执行）

> **文档用途**：按阶段将对应章节交给 AI 实现；每阶段满足 **验收标准** 后再进入下一阶段。  
> **硬性约束**：**保留以 JSON 为核心的 `AssistantTurn` 契约**（及流式协议中的 `<<<JSON>>>`），**UI 依赖该结构化结果**。重构的是 **如何产生该 JSON**（ReAct 循环、工具），而非替换 JSON 形状。  
> **宗旨**：**借鉴仓库内 `claude_code/` 源码** 实现工具模型、上下文注入、权限与消息闭环——详见 **`docs/agent-react-and-claude-code-reference.md`**（含 **Claude Code 文件级实现分析**）。

---

## 0. 全局不变量（任何阶段都不得破坏）

### 0.1 结构化输出模型：`AssistantTurn`

来源：`ryven_node_generator/ai_assistant/schemas.py`

| 字段 | 含义 | UI / 下游依赖 |
|------|------|----------------|
| `message` | 对用户可见的短说明 | 聊天历史、流式正文 |
| `core_logic` | 节点 `try` 内 Python 主体 | 生成 `nodes.py`、校验 |
| `config_patch` | **部分**节点配置 | `merge.apply_config_patch` |
| `self_test_cases` | 可选桩测用例 | 可内嵌在 `submit` 或仅工具侧使用 |

`config_patch` 允许键：`class_name`, `title`, `description`, `color`, `inputs`, `outputs`, `core_logic`, `has_main_widget`, `main_widget_template`, `main_widget_args`, `main_widget_pos`, `main_widget_code`。

### 0.2 解析与归一化

- `finalize_parsed_turn`（`core/finalize_turn.py`）产出 **dict** 供 `main_window` 使用。  
- 流式：`JSON_SEP = "<<<JSON>>>"` 前为对用户可见文本，后为 **单个 JSON 对象**（若仍采用该协议；**ReAct 模式下也可仅在最终 `submit` 轮输出该格式**，见阶段 B）。

### 0.3 主线策略：ReAct + 工具；旧 self repair 降级

- **主线**：**「修改 + 测试」均为工具**（如 `apply_node_patch`、`run_stub_test`），由 **ReAct 循环**（多步 `tool_calls` → 执行 → 再采样）直到 **`submit_node_turn`** 产出 `AssistantTurn` 或达到停止条件。  
- **旧 `run_turn_with_self_repair` 的 for 循环**：在 ReAct 全量启用后 **不再作为默认路径**；桩测实现 **迁移为 `run_stub_test` 内部复用**（与 `docs/agent-react-and-claude-code-reference.md` 一致）。  
- **可选兜底**：保留环境变量 **`AI_LEGACY_SELF_REPAIR_LOOP=true`**（名称可调整）仅在 **关闭工具 Agent** 时走旧路径，便于回归对比。

### 0.4 「一轮」对 UI 的含义

一次用户发送后，对外仍交付 **一个** `finalize` 后的 **dict**（可含 `_streamed_reply_plain`、`repair_trace` 等）；**内部**可有任意多步工具调用。

---

## 1. 术语

- **最终产物（Final Turn Payload）**：与 `finalize_parsed_turn` 输出语义一致的 `dict`。  
- **工具（Tool）**：中间步骤能力；结果进入对话，**最终以 `submit_node_turn` 收敛为 `AssistantTurn`**。  
- **编排器**：维护消息历史、步数、`should_stop`；**对标 Claude Code 主查询循环**（见参考文档 §2）。

---

## 阶段 A（基线，已完成或可对照）

| 内容 | 说明 |
|------|------|
| 契约测试 | `tests/test_ai_assistant_contract.py` |
| `contracts/`、`orchestration/run_agent_session` | 当前 `run_agent_session` → `run_turn_with_self_repair` |
| 延迟 import | `ai_assistant/__init__.py` 等，减轻无 LangChain 时的导入成本 |

后续阶段以 **替换 `run_agent_session` 内部实现** 为 ReAct 为目标，**保持 Worker 入口仍调用 `run_agent_session`**。

---

## 阶段 B：ReAct 主循环 + `submit_node_turn` 唯一出口

**目标**：实现 **模型 ↔ 工具 ↔ 再模型** 闭环（OpenAI 兼容 **tools / tool_calls** 或等价 API）；**唯一正常结束** 为调用 **`submit_node_turn`** 且 JSON 通过 `AssistantTurn` 校验与 `finalize_parsed_turn`。

### 设计要点（对齐 Claude Code 抽象）

1. **工具注册表**：名称、`description`、`parameters`（JSON Schema），执行函数接收 **`AgentContext`**（项目根、当前节点、`should_stop`、进度回调）。参考 **`claude_code/src/tools.ts` + `Tool.ts`**。  
2. **判据**：以 **`tool_calls` 非空** 作为需要执行工具的一轮（对标 **`messages.ts`** 用 `tool_use` 块判断，而非盲信 `stop_reason`）。  
3. **步数与预算**：`AI_AGENT_MAX_STEPS`（必填上限）、`should_stop` 与 **abort** 对齐 **`ToolUseContext.abortController`** 思想。  
4. **流式**：可选仅对 **最后一轮** 或 **assistant 文本** 向 UI 推流；中间步走 `on_progress`（`phase: tool_start` / `tool_done`）。

### 任务

1. 在 `orchestration/` 新增 **`run_react_session`**（或扩展 `run_agent_session`，由 **`AI_AGENT_MODE=react|legacy`** 切换）。  
2. 实现 **`submit_node_turn`** 工具（或 function），参数与 **`AssistantTurn`** 字段一致。  
3. `run_agent_session`：**默认指向 ReAct**；`legacy` 时仍调用现有 `run_turn_with_self_repair`。

### 验收标准

- [ ] `AI_AGENT_MODE=legacy` 与当前行为一致（回归）。  
- [ ] `react` 模式下无 `submit` 时返回明确失败 dict，不崩溃。  
- [ ] `finalize_parsed_turn` 仍为唯一归一化出口。

### 交给 AI 的提示语模板

```
实现 docs/agent-refactor-roadmap-for-ai.md 阶段 B。参考 docs/agent-react-and-claude-code-reference.md §2。
禁止改变 AssistantTurn。submit 后经 finalize_parsed_turn。
```

---

## 阶段 C：「修改 + 测试」工具（核心）

**目标**：将 **改节点草稿** 与 **跑桩测** 从 prompt 与 self-repair 循环中 **抽成工具**，贯彻 **思考—修改—测试—再思考**。

### 建议工具

| 工具 | 职责 | 参考 CC |
|------|------|---------|
| `get_node_snapshot` | 返回当前节点 JSON | 类似只读 Read |
| `apply_node_patch` | 白名单字段合并到 **会话内草稿节点** | 类似 Edit，但作用域为节点 dict |
| `run_stub_test` | 对给定 `core_logic` + 用例跑桩测，返回摘要 | 复用 `self_repair` 内执行逻辑，**非**再套一层 for 循环 |
| `validate_core_logic` | 仅静态 AST/禁词（可选） | 轻量只读 |

### 任务

1. 草稿节点存在 **Context** 中，**`submit`** 时才转为最终 `AssistantTurn`（或与 `submit` 参数合并）。  
2. **`run_stub_test` 输出截断**（对标 **`toolResultStorage` / `maxResultSizeChars`**）。  
3. 单元测试：工具与 **旧桩测** 同输入同结论。

### 验收标准

- [ ] 不调用 LLM 也可单测工具。  
- [ ] 与阶段 B 的 ReAct 循环集成。

---

## 阶段 D：下线默认 self-repair for 循环，保留兼容开关

**目标**：**默认** `run_agent_session` **不再**调用 `run_turn_with_self_repair` 的 **多轮 for**；若用户显式 `AI_LEGACY_SELF_REPAIR_LOOP=true` 且 `AI_AGENT_MODE=legacy`，仍可走旧路径。

### 任务

1. 文档与 `config.py` 说明 **默认策略**。  
2. 从 `orchestration` 中 **删除或隔离** 对 `run_turn_with_self_repair` 的默认依赖（完成阶段 B/C 后）。

### 验收标准

- [ ] 默认配置下仅 ReAct + 工具路径。  
- [ ] Legacy 开关可一键回归旧行为。

---

## 阶段 E：权限与受控 Shell（可选）

**目标**：对标 **`permissions.ts` + `BashTool` + `bashSecurity.ts`**。

### 任务

1. `run_shell`：`AI_AGENT_BASH` 默认 false；cwd、timeout、输出上限；**当 agent 调用 `run_shell` 时必须先请求用户确认（UI 显示命令 + Run/Cancel），由用户点击后才执行**。  
2. `apply_node_patch` / 危险操作：**规则或确认**（若产品有 UI）。

### 验收标准

- [ ] 默认无任意 shell。  
- [ ] 权限拒绝或用户取消时，**tool_result/tool message** 含可读错误/取消原因，模型可重试或改用其它工具。
- [ ] 用户批准后，`run_shell` 的输出作为 tool_result 进入下一轮模型推理。

---

## 阶段 F：可观测性与文档

### 任务

1. 集中配置：`AI_AGENT_MODE`、`AI_AGENT_MAX_STEPS`、`AI_LEGACY_SELF_REPAIR_LOOP`、`AI_AGENT_BASH`。  
2. **上下文预算**（已实现）：`AI_CONTEXT_MAX_MESSAGES`（默认仅保留最近若干条 user/assistant）、`AI_CONTEXT_COMPACT_JSON`（节点 JSON 单行压缩）。  
3. 可选会话日志（脱敏）。  
4. 保持 **`docs/agent-react-and-claude-code-reference.md`** 与本文 **阶段编号一致**。  
5. 记录生成器与提示词的“协议行为”：`core_logic` 不再由模板注入 `in0/in1/... = self.get_input_val(...)`，而要求 AI 在代码里显式使用 `self.get_input_val(K)` 获取数据输入，并用局部变量名完成后续计算。  
6. 记录端口 `widget` 的可扩展策略：当前输入端口 widget 类型受 `assets/widget_template.py` 与 UI 的可选项约束；如模型需要“非预置 widget”，应先扩展 widget 工厂并同步 UI 选择列表（之后 AI 才能稳定使用 `config_patch.inputs[].widget.type`）。如需临时 UI 承载也可考虑 `main_widget_template=custom` 走自定义主组件路径。

### 验收标准

- [ ] 文档可指导「如何关闭 ReAct、回退 legacy」。  

---

## 附录 A：交给 AI 的最小上下文包

1. 本文当前阶段 + **§0**。  
2. `docs/agent-react-and-claude-code-reference.md`（**宗旨 + §2 源码对照**）。  
3. `schemas.py`、`core/finalize_turn.py`。  
4. `orchestration/session.py`、`ui/widgets.py` 中 Worker。

---

## 附录 B：PR 自检清单

- [ ] `AssistantTurn` 四字段语义未变。  
- [ ] UI 仍消费 `finalize` 后的 dict。  
- [ ] ReAct 有 `max_steps` 与 `should_stop`。  
- [ ] 新行为默认 **不** 依赖旧 self-repair for 循环（除非 legacy）。

---

## 附录 C：文档关系

- **`agent-react-and-claude-code-reference.md`**：**借鉴 Claude Code 源码** + 设计映射（主参考）。  
- **`ai-self-repair-optimization.md`**：历史 self-repair 实现说明；**策略已被阶段 C/D 取代**，保留作迁移说明。

---

**版本**：2.0（**ReAct + 修改/测试工具** 为主线；**借鉴 Claude Code** 为宗旨）  
**维护**：大阶段完成后在对应章节备注合并日期 / PR。
