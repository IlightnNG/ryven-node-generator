# 生成器（Ryven Node Generator）成果量化策略报告（可复现版）

> 目标：基于**当前仓库实现**，给出一套可复现、可审计、适合写入论文第八章（Evaluation）的量化评估方案，用于证明本毕设产出在**效率**、**一次成功率/即时正确率**与**收敛到鲁棒正确**等维度的优势。

本策略面向的系统是本项目的「Ryven Node Generator（含可选 AI 助手）」：核心是将结构化节点配置渲染为可被 Ryven 加载的包文件（`nodes.py` / `gui.py`），并在 AI 辅助模式下提供**校验**、**stub 自测**与（可选）**ReAct 工具循环**。

---

## 1. 与代码实现的对齐（本仓库可验证的机制）

本节把“能量化什么”与“代码里真的存在什么机制”对齐，避免出现评审常见质疑：指标与实现不匹配、不可复现。

### 1.1 生成器确定性产出（Generator-only）

- **确定性渲染**：`ryven_node_generator/codegen/generator.py`
  - `generate_code_from_data(nodes_data)`：Jinja2 渲染预览字符串（`NODES_TEMPLATE` / `GUI_TEMPLATE`）。
  - `save_files(nodes_data, path)`：落盘 `nodes.py`、`gui.py`，并复制 `widget_template.py`。
- **意义**：这一链路是“纯生成器”工作流的基线，可用来证明**减少样板劳动**、降低结构错误。

### 1.2 Workspace 持久化（实验可记录的真源）

- **配置真源**：`ryven_node_generator/project/workspace.py`
  - `nodes_config.json`：节点结构配置列表（实验任务产出的结构应可序列化到此）。
  - `generator_ai_chat.json`：AI 交互历史（含用户上下文 meta 字段：如 `context_node_uid`、`snapshot_node` 等）。
- **意义**：量化实验应把每次任务产出的配置/对话作为审计证据，保证可追溯。

### 1.3 AI 输出护栏（可作为“鲁棒正确”定义的一部分）

本仓库已经具备两类关键护栏，可直接纳入量化指标：

- **静态校验**：`ryven_node_generator/ai_assistant/validation.py`
  - `validate_core_logic(code)`：AST 可解析 + 禁止关键危险子串（`subprocess/socket/ctypes/__import__/exec(/compile(`）。
- **turn 最终化校验**：`ryven_node_generator/ai_assistant/core/finalize_turn.py`
  - `finalize_parsed_turn()`：会对 `core_logic` 进行 `dedent` + `validate_core_logic`，失败时写入 `validation_error`。
- **意义**：可以把“最终正确”至少落到**通过校验**（语法+危险构造）+ 通过 stub 自测（见下）+ Ryven import/运行验证。

### 1.4 Stub 自测（可量化的“即时正确率”与“最终正确率”支撑）

- `ryven_node_generator/ai_assistant/core/stub_runner.py`
  - `run_logic_once()`：用 stub Node + 安全 globals/locals 执行 `core_logic`。
  - `evaluate_stub_cases()`：根据用例给出 `total/passed/all_passed/details`。
- `ryven_node_generator/ai_assistant/tools/host.py`
  - `run_stub_test(core_logic, cases_json)`：对 draft 节点运行 stub 用例。
- **意义**：你可以把“初版 demo 正确率”定义为：**第一次提交版本**在固定的 stub 测试集上 `all_passed==True` 的比例；或用“通过率（passed/total）”作为连续指标。

### 1.5 ReAct 工具循环（可量化“迭代轮次/工具调用/收敛时间”）

- `ryven_node_generator/ai_assistant/orchestration/react_loop.py`
  - `run_react_session(..., max_steps=24)`：多步 LLM ↔ tools 循环，直到调用 `submit_node_turn` 并通过 schema 校验。
  - `out["react_trace"]` / `out["repair_round"]=step`：带回循环轨迹。
  - **会写 JSONL session log**（见 1.6）。
- **意义**：这提供了天然的可量化维度：**LLM steps**、**工具调用集合**、**每步工具 I/O 失败原因**、最终提交是否成功等。

### 1.6 会话日志（可审计的数据源）

- `ryven_node_generator/ai_assistant/session_file_log.py`
  - append-only JSONL：包含 `llm_request/llm_response/tool_round_trip/session_start/session_end` 等事件。
- **意义**：可以在论文附录给出“日志字段定义”，并在实验中对齐统计口径（如 tool_calls、rounds、失败类型）。

---

## 2. 量化目标与核心结论结构（写进论文最强的叙事）

针对“生成器成果”建议用 **三条主结论**（每条都能落到图表/表格）：

1. **效率提升（时间）**：与纯手写相比，生成器（以及不同 AI 工作流）显著缩短“到可用版本”的时间。
2. **一次成功率提升（即时正确率）**：AI/校验/循环机制使得“初版 demo”更容易一次通过最小验证。
3. **收敛到鲁棒正确更快（最终正确）**：在加入校验 + stub +（可选）ReAct 反馈循环后，到达“鲁棒标准”的总时间更短/失败更少，且过程可解释（轮次、失败类型）。

---

## 3. 实验设计：五种工作流（你提出的拆分，可行且建议采用）

建议固定为 5 个条件（workflow），并**写死协议**（允许/禁止的行为），避免混淆：

### W1：纯手写（Manual）

- **允许**：IDE、查阅本仓库已有节点模板/历史代码（若你认为现实开发允许）。
- **禁止**：任何 LLM（包括普通聊天、Copilot 等）。
- **产物**：手写 `nodes.py/gui.py` 或手写一个等价包结构（与生成器输出目标一致）。

### W2：纯手写 + 普通 LLM 对话（Chat）

- **允许**：把需求发给 LLM 问建议/代码片段（纯对话）。
- **禁止**：不允许“工具循环/代理框架自动修复”；不允许让 LLM 直接操作项目文件（只复制粘贴）。
- **目的**：隔离“有 LLM 但无系统护栏/无工具化循环”的真实增益。

### W3：单层 Agent（Single-turn Agent）

定义建议（择一，论文里写清即可）：

- **方案 A（推荐）**：一次调用生成结构化输出（相当于一次 `submit_node_turn` 的内容），允许触发**一次**校验与**一次**stub（但不允许循环自修复）。
- **方案 B**：允许 tools 但限制 `max_steps=1`（只允许 1 次 tool 规划/执行）。

### W4：三层 Agent 循环（3-stage Pipeline）

由于“3 层”不是通用术语，建议将其固化为 **Plan → Implement → Verify** 三阶段，每阶段最多 1 轮（或最多 2 轮）：

- **Plan**：产出结构（端口/类名/描述/颜色/主 widget 选择）。
- **Implement**：产出 `core_logic`。
- **Verify**：运行 `validate_core_logic` + `run_stub_test`，失败则允许回到 Implement，但**总循环次数固定上限**（例如最多 3 次）。

### W5：ReAct 架构循环（Tool loop）

直接对应仓库实现（`run_react_session`）：

- **允许**：多步工具调用（read/write/apply_patch/validate/stub/可选 shell）。
- **终止**：成功提交 `submit_node_turn` 且通过 schema + 校验；或达到 `max_steps`。
- **产物**：返回包含 `react_trace`、`repair_round`，并可从 JSONL session log 复盘。

---

## 4. 任务集设计：20 个节点列表（建议进一步“分层”以增强说服力）

你提出的“20 个节点任务”非常合适，但务必把任务集设计得像 benchmark：

### 4.1 任务分层（强烈建议）

将 20 个节点按复杂度分为 3 层，确保比较公平：

- **L1（简单，约 8 个）**：纯数值/字符串处理；1–2 输入，1 输出；无外部依赖。
- **L2（中等，约 8 个）**：包含条件分支、列表/字典处理、端口较多（≥3）。
- **L3（困难，约 4 个）**：需要更强鲁棒性（空输入、类型不匹配、异常处理），或包含 exec/data 混合端口与 widget 参数。

> 注意：如果任务涉及 OpenCV/TF 外部依赖，会引入环境噪声。对“生成器评估”建议先做**不依赖外部库**的任务集；外部库节点可作为第 8 章另一个小节（节点库评估）。

### 4.2 任务规格模板（每个节点一页，写入附录/数据文件）

每个节点任务建议用统一字段：

- `task_id`：如 `N01`…`N20`
- `title`：节点标题
- `ports_spec`：
  - inputs：[{label,type,data_type?,widget?}, ...]
  - outputs：同上
  - 是否包含 exec 端口（若你的生成器/模板支持）
- `core_requirement`：核心逻辑（可用伪代码+示例）
- `demo_cases`：用于“初版 demo”判定的最小 stub 用例（2–5 个）
- `robust_cases`：用于“最终正确/鲁棒”判定的扩展用例（再加 5–15 个，含边界 case）
- `acceptance`：
  - A1：通过 `validate_core_logic`
  - A2：demo stub 全通过（demo）
  - A3：robust stub 全通过（final）
  - A4（可选）：Ryven 中加载/执行通过（若能自动化或半自动验证）

---

## 5. 指标体系（你提出的三类指标：合理；这里补全细节与口径）

你的三个指标是主线，建议进一步拆为**主指标（论文图）**与**诊断指标（解释为什么）**。

### 5.1 主指标（建议写在 Chapter 8）

#### M1：完成速度（Time-to-Demo）

定义（建议写死）：

- 从“开始计时”到满足 **demo 判定**（A1 + A2）的时间，单位分钟。
- demo 判定：`validate_core_logic` 通过 + demo stub 用例 `all_passed=True`。

> 备注：如果 W1/W2 不走生成器的 stub 工具，可用同一套 python stub runner（后续可写一个统一评测脚本）保证判定一致。

#### M2：即时正确率（Instant Demo Correctness）

建议用两种口径（论文里择其一为主，另一个放附录）：

- **pass@1 风格**：第一次提交的版本是否直接通过 demo（A1 + A2）。
- **比例风格**：第一次提交 demo stub 通过率 `passed/total` 的平均值。

#### M3：达到最终正确的时间（Time-to-Robust）

定义：

- 从开始计时到满足 **final 判定**（A1 + A3）的时间。
- A3：robust stub 用例 `all_passed=True`，robust 用例含边界输入。

> 若你的论文想更“工程化”，final 可再加 A4（Ryven import OK + 运行），但要注意自动化成本；可以用“半自动”并记录操作脚本。

### 5.2 诊断指标（解释“为什么更好”，特别适合写 AI 小节）

这些指标能与仓库现成日志/trace 对齐：

- **D1：LLM rounds / react steps**：ReAct 的 `repair_round`；或 JSONL 的 step 计数。
- **D2：tool_calls**：每个 session 的 `tool_round_trip` 条目数。
- **D3：validation_error 类型分布**：`finalize_parsed_turn` 里 `validation_error`（语法、危险子串等）。
- **D4：stub failure 类型**：`evaluate_stub_cases.details`（异常类型、输出不匹配）。
- **D5：结构 patch 规模**：`config_patch` 里 keys 数量、端口变更次数（来自 `whitelisted_config_diff`）。

---

## 6. 数据记录与文件结构（建议在 `scripts/evaluation/data/`）

为保证“可复现”，建议把实验数据拆成三类文件：

### 6.1 任务真源（一次写好，整个实验复用）

- `tasks/node_tasks.json` 或 `tasks/node_tasks.yaml`
  - 包含 N=20 的任务规格（见 4.2）。

### 6.2 试次记录表（核心统计输入）

推荐一个长表（tidy data），每行 = 一个 `workflow × task_id × run_id`：

- `trials/generator_trials.csv`

建议列（与你现有绘图脚本字段兼容/可拓展）：

- `task_id`
- `workflow`：W1–W5 key
- `run_id`：重复编号
- `operator`：操作者（若多人）
- `start_ts`, `end_ts`
- `time_to_demo_min`（M1）
- `instant_demo_ok`（M2/pass@1）
- `time_to_robust_min`（M3）
- `final_robust_ok`
- `validation_on`（bool）
- `loop_mode`：none/single/3stage/react
- `llm_rounds`、`tool_calls`（D1/D2）
- `errors_top`：失败主因枚举（如 `syntax_error`/`stub_mismatch`/`ryven_import_error`/`max_steps`）
- `artifact_path`：产物路径或 hash（指向保存的 nodes_config / session log）

### 6.3 审计证据（强烈建议保留）

每个 trial 输出一个文件夹（便于答辩展示“证据链”）：

- `artifacts/<date>/<workflow>/<task_id>/<run_id>/`
  - `nodes_config.json`（或生成器 workspace）
  - `generated/nodes.py`、`generated/gui.py`
  - `react_session.jsonl`（若 W5）
  - `notes.md`（记录人为修复点）

---

## 7. 统计方法与图表建议（论文第八章可直接落地）

### 7.1 统计方法（本科论文建议“稳健 + 易解释”）

- 时间分布通常偏态：建议用 **中位数 + IQR** 作为主描述统计。
- 工作流对比：
  - 多组：Kruskal–Wallis（非参数）作为总体差异检验（可选）。
  - 两两：Mann–Whitney U（可选）。
- 报告效应量（可选但加分）：
  - 速度提升倍数：`median(manual) / median(workflow)`。
  - 或相对下降：`1 - median(workflow)/median(manual)`。

> 注意：显著性不是重点，重点是协议与可复现；若样本小，建议把 p 值放附录。

### 7.2 图表（建议最少 4 张就能讲清楚）

1. **箱线+散点**：五工作流的 `time_to_demo` 分布（对应 M1）。
2. **成功率条形图**：五工作流的 `instant_demo_ok`（对应 M2）。
3. **time_to_robust 分布**：五工作流的最终时间（对应 M3）。
4. **ReAct 诊断图**（只对 W5）：`llm_rounds × time_to_demo` 气泡大小=tool_calls（解释代价与稳定性）。

可选增强：

- **热力图**：`validation_on × loop_mode` 的 median time（展示“校验/循环”因子作用）。
- **失败原因堆叠条**：syntax/validation/stub mismatch/import error 比例。

---

## 8. 公平性与威胁（Threats to Validity）——写进论文会更“像研究”

### 8.1 学习效应与顺序效应

- 同一操作者做 5 个工作流会越来越熟：建议用**拉丁方**随机化顺序，或不同工作流分配不同操作者（至少 2 人）。

### 8.2 任务难度偏差

- 20 个任务必须“分层 + 均衡”：每个工作流都做同一套任务，且 task 顺序随机。

### 8.3 LLM 非确定性

- 记录：模型名、温度、max_steps、是否开启 shell、token 用量（若可得）。
- 每个任务对 AI 条件至少重复 2–3 次。

### 8.4 “正确”的定义不一致

- 强制采用统一的判定：`validate_core_logic` + stub 测试集（demo 与 robust 两套）。
- 若加入 Ryven 运行验证，建议把其作为 A4（可选）并明确哪些图表包含/不包含 A4。

---

## 9. 建议的实验执行步骤（最小可行 → 最强说服）

### 9.1 最小可行（建议先做，最快产出论文图）

- 只评 **W1（手写） vs W3（单层 Agent） vs W5（ReAct）** 三组。
- 指标只做 M1 + M2（time_to_demo + instant_demo_ok）。
- N=20，重复 K=1（先跑通流程），再把关键任务做 K=3 增强稳定性。

### 9.2 完整版（你的目标：五工作流 + 三主指标）

- 五组都做：W1–W5
- 每个 task 至少 K=2（AI 条件建议 K=3）
- 三主指标 M1/M2/M3 都算
- W5 额外产出 D1–D4 诊断图

---

## 10. 结论写法模板（给论文第八章直接复用）

你最终应能写出类似下面的结论段（示例结构，不填数字）：

- **效率**：与纯手写相比，生成器模板工作流将 `time_to_demo` 的中位数从 \(T_\text{manual}\) 降至 \(T_\text{gen}\)，相当于 **\(S\)× 加速**；ReAct 在平均时间上略高于单层，但显著提升成功率。
- **即时正确率**：在 20 个任务中，W5 的 `instant_demo_ok` 达到 \(p\%\)，高于 W2/W3；失败主要来自（列出 top2 原因：语法/输出不匹配/导入错误）。
- **最终鲁棒**：在 robust 用例集上，W5 的 `time_to_robust` 更稳定（IQR 更小），且日志显示其通过 `validate_core_logic_tool` 与 `run_stub_test` 的反馈循环减少了返工。

---

## 11. 附：建议在论文中引用的实现点（文件清单）

- 确定性生成：`ryven_node_generator/codegen/generator.py`
- workspace 与审计：`ryven_node_generator/project/workspace.py`
- core_logic 校验：`ryven_node_generator/ai_assistant/validation.py`
- turn 最终化与错误汇报：`ryven_node_generator/ai_assistant/core/finalize_turn.py`
- stub 自测：`ryven_node_generator/ai_assistant/core/stub_runner.py`
- ReAct 循环：`ryven_node_generator/ai_assistant/orchestration/react_loop.py`
- JSONL 日志：`ryven_node_generator/ai_assistant/session_file_log.py`

