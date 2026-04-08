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

## 3. 实验设计：六种工作流（authoring surface × LLM 深度）

在原先“LLM 深度”的基础上，增加 **是否使用 Ryven Node Generator（模板落盘）** 这一维，更贴近真实用法，也便于单独论证 **Generator 的便捷性**。

建议固定为 **6 个互斥条件**，CSV 中用 `workflow` 键（与脚本一致），并增加派生列 **`uses_generator`**（0/1）供分层统计或因子分析：

| 键 | `uses_generator` | 协议摘要 |
|----|------------------|----------|
| `W1_hand_only` | 0 | **直接编辑** `nodes.py` / `gui.py`；禁止任何 LLM。 |
| `W2_hand_chat` | 0 | 直接编辑源文件 + **普通 LLM 对话**（仅复制粘贴；无工具环、无自动写盘）。 |
| `W3_gen_chat` | 1 | 先用 **Generator** 生成/调整端口与样板并保存包，再用 **普通 LLM 对话**补 `core_logic`（同上，无 Agent 工具环）。 |
| `W4_gen_single` | 1 | Generator + **单轮 Agent**（一次 `submit_node_turn` 或 `max_steps=1`；允许各一次校验与 stub，**不允许**自修复循环）。 |
| `W5_gen_3stage` | 1 | Generator + **三阶段管线**（Plan → Implement → Verify；Verify 失败可回到 Implement，**总轮次有上限**）。 |
| `W6_gen_react` | 1 | Generator + **ReAct 工具循环**（`run_react_session`：validate/stub/apply_patch 等直至成功或 `max_steps`）。 |

**因子视角（写论文时可一句话点明）**：

- **因子 A**：`uses_generator ∈ {0,1}` — 对比 W1↔W3、W2↔W3 可量化“同样用聊天补逻辑时，先生成器打底”的时间与错误率差异。  
- **因子 B**：在 `uses_generator=1` 的子集中，对比 W3→W6 可得 **结构化 Agent / ReAct** 相对 **纯聊天** 的收益。

**协议要点（防混淆）**：

- W1/W2 的“产物路径”必须与 W3–W6 **语义等价**（同一任务同一验收），仅允许编辑方式不同。  
- W3–W6 的 Generator 部分应包含 **保存 `nodes.py`/`gui.py`**（或等价 workspace 导出），不能只停留在 UI 预览。  
- W6 的日志与 `react_trace` 作为诊断指标（D1–D2）的主要来源。

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

> 备注：若 W1/W2/W3 在协议中未接入生成器侧 stub 工具，仍应对所有条件使用**同一套**离线 stub runner 判定 A2/A3，保证口径一致。

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
- `workflow`：`W1_hand_only` … `W6_gen_react`（见 §3）
- `uses_generator`：0/1（与 §3 表一致；可由 `workflow` 派生）
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
  - `react_session.jsonl`（若 W6）
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

1. **箱线+散点**：六工作流的 `time_to_demo` 分布（对应 M1）。
2. **成功率条形图**：六工作流的 `instant_demo_ok`（对应 M2）。
3. **time_to_robust 分布**：六工作流的最终时间（对应 M3）。
4. **ReAct 诊断图**（只对 W6）：`llm_rounds × time_to_demo` 气泡大小=tool_calls（解释代价与稳定性）。
5. **（可选）Generator 因子图**：按 `uses_generator` 聚合或分面，突出 W2 vs W3、W1 vs 带生成器条件。

可选增强：

- **热力图**：`validation_on × loop_mode` 的 median time（展示“校验/循环”因子作用）。
- **失败原因堆叠条**：syntax/validation/stub mismatch/import error 比例。

---

## 8. 公平性与威胁（Threats to Validity）——写进论文会更“像研究”

### 8.1 学习效应与顺序效应

- 同一操作者做 6 个工作流会越来越熟：建议用**拉丁方**随机化顺序，或不同工作流分配不同操作者（至少 2 人）。

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

- 只评 **W1_hand_only vs W3_gen_chat vs W6_gen_react** 三组（覆盖：无工具 / 生成器+聊 / 生成器+闭环）。
- 指标只做 M1 + M2（time_to_demo + instant_demo_ok）。
- N=20，重复 K=1（先跑通流程），再把关键任务做 K=3 增强稳定性。

### 9.2 完整版（六工作流 + 三主指标）

- 六组都做：W1_hand_only–W6_gen_react
- 每个 task 至少 K=2（AI 条件建议 K=3）
- 三主指标 M1/M2/M3 都算
- W6 额外产出 D1–D4 诊断图

---

## 10. 结论写法模板（给论文第八章直接复用）

你最终应能写出类似下面的结论段（示例结构，不填数字）：

- **效率**：与纯手写相比，生成器模板工作流将 `time_to_demo` 的中位数从 \(T_\text{manual}\) 降至 \(T_\text{gen}\)，相当于 **\(S\)× 加速**；ReAct 在平均时间上略高于单层，但显著提升成功率。
- **即时正确率**：在 20 个任务中，W6 的 `instant_demo_ok` 达到 \(p\%\)，高于 W3/W4/W5 等弱闭环条件；失败主要来自（列出 top2 原因：语法/输出不匹配/导入错误）。
- **最终鲁棒**：在 robust 用例集上，W6 的 `time_to_robust` 更稳定（IQR 更小），且日志显示其通过 `validate_core_logic_tool` 与 `run_stub_test` 的反馈循环减少了返工。
- **生成器便捷性**：对比 **W2_hand_chat vs W3_gen_chat**（同用纯聊、差在是否先用 Generator），报告 M1/M2 的相对提升。

---

## 11. 附：建议在论文中引用的实现点（文件清单）

- 确定性生成：`ryven_node_generator/codegen/generator.py`
- workspace 与审计：`ryven_node_generator/project/workspace.py`
- core_logic 校验：`ryven_node_generator/ai_assistant/validation.py`
- turn 最终化与错误汇报：`ryven_node_generator/ai_assistant/core/finalize_turn.py`
- stub 自测：`ryven_node_generator/ai_assistant/core/stub_runner.py`
- ReAct 循环：`ryven_node_generator/ai_assistant/orchestration/react_loop.py`
- JSONL 日志：`ryven_node_generator/ai_assistant/session_file_log.py`

---

## 12. 蒙特卡洛模拟数据（无实测时的论文占位）

当无法完成完整用户实验时，可用 **脚本生成的模拟 trial 表** 保持图表与叙事结构一致；**必须在论文中明确标注为 simulation**，并附上 `simulation_manifest.json` 中的参数版本。

- **生成**：`scripts/evaluation/generate_strategy_trials.py`  
  - 潜变量：每条 trial 的 `latent_hardness ~ Beta`、操作者微扰、可选环境噪声。  
  - 时间：**对数正态** wall-clock；ReAct 锚点按难度 L1/L2/L3 分别约 **1 / 2 / 3 分钟** 中位；手写 **L1 不低于约 10 分钟** 并随难度放大。  
  - 正确率：**logistic** 模型，`instant_demo_ok` 与 `final_robust_ok` 条件于难度与是否首过；**W6（Generator+ReAct）** 在 pass@1 与最终鲁棒上参数最强；**W3（Generator+聊）** 相对 **W2（手写+聊）** 体现样板节省时间。  
  - 输出：`data/strategy_trials_simulated.csv` + `data/simulation_manifest.json`（含 `schema_version: sim_v3` 与汇总统计）；CSV 含列 **`uses_generator`**。

- **出图**（与 CSV 解耦）：`scripts/evaluation/plot_strategy_results.py`  
  - 默认读取 `data/strategy_trials_simulated.csv`；`--html-only` 可跳过 Kaleido 静态导出。  

- **共享常量**：`scripts/evaluation/strategy_constants.py`（工作流顺序、配色、标签）。

---

## 13. 叙事要点：Generator 便捷性 + ReAct（W6）相对优势

在统一判定 **A1（校验）+ A2（demo stub）+ A3（robust stub）** 下，论文可强调：

1. **生成器便捷性（因子 A）**：在**同样使用纯 LLM 聊天**时，**W3_gen_chat** 相对 **W2_hand_chat** 的 **M1** 更短、**M2** 往往更高（样板与端口结构由模板保证，减少低级结构错误）。  
2. **效率（端到端）**：**W6** 相对 **W1_hand_only / W2**，**M1/M3 中位数**显著更低（模板 + 工具闭环减少样板与返工）。  
3. **即时正确率（M2）**：**W6** 的 **pass@1** 高于 **W3–W5**（工具反馈降低“一次提交即错”的概率）。  
4. **最终鲁棒**：**W6** 的 **final 成功率**与 **time_to_robust**（成功子集）优于弱闭环条件；诊断图用 **llm_rounds / tool_calls** 解释成本来源。

与 **W5_gen_3stage** 的对比建议写成：**W5 可能在部分任务上 demo 略快**（固定阶段、轮次少），但 **W6 在扩展用例与失败恢复上更稳**；**实测时**应以同一 `robust_cases` 验证。

