# Ryven Node Generator — 拓展与优化分析

## 一、用户体验与界面

### 1.1 校验与反馈
- **当前**：核心逻辑、端口 Args、类名等无格式校验，错误只在生成/导入 Ryven 后才暴露。
- **建议**：
  - 类名实时校验：仅允许合法 Python 标识符（字母/数字/下划线），禁止与 Python 关键字冲突。
  - 端口 label 唯一性提示（同节点内重名时警告）。
  - 生成前做一次「预生成」检查：调用 `generate_code_from_data` 并捕获 Jinja2/语法错误，在弹窗或状态栏展示具体错误行/字段。
- **可选**：Core Logic 区域集成简单语法高亮（如 QSyntaxHighlighter）或至少关键字高亮，减少笔误。

### 1.2 节点列表与导航
- **当前**：节点列表只有标题，多节点时难以区分；删除后 `current_idx` 置 -1，需手动再选节点。
- **建议**：
  - 列表项显示「类名 · 标题」或子标题（如端口数、是否有 main widget），便于识别。
  - 删除当前节点后自动选中前一节点或第一个节点，并刷新预览与表单。
  - 支持拖拽调整节点顺序（对应 `nodes_data` 顺序），方便整理导出/生成顺序。

### 1.3 配置与持久化
- **当前**：无「最近项目」「默认保存路径」等。
- **建议**：
  - 使用 QSettings 保存：窗口尺寸/位置、上次导出目录、最近打开的 JSON 路径（可选）。
  - 未保存修改时，关闭前提示「是否保存当前配置」。

---

## 二、代码质量与健壮性

### 2.1 异常处理
- **当前**：`update_live_preview()` 中 `try/except: pass` 会吞掉所有异常；`import_config` 未校验 JSON 结构。
- **建议**：
  - 预览失败时在状态栏或预览区边缘显示简短错误信息（如 "Preview error: ..."），避免静默失败。
  - 导入 JSON 时校验必选字段（如 `class_name`, `title`, `inputs`, `outputs`, `core_logic`），缺少时提示并拒绝或只合并可识别部分。

### 2.2 数据层与默认值
- **当前**：节点/端口数据多处用 `.get()`，若旧版 JSON 缺少新字段可能表现不一致。
- **建议**：
  - 定义「节点/端口/Widget」的规范数据结构（如 dataclass 或 TypedDict），在 `load_node_to_ui` 和导入时用统一 `normalize_node(data)` 补全默认值并校验类型，再写回 `nodes_data`。

### 2.3 生成逻辑
- **当前**：`generator.generate_code_from_data` 会原地修改 `nodes_data`（如 `main_widget_template` 转小写），若调用方未预期可能产生副作用。
- **建议**：
  - 生成前对传入的 `nodes_data` 做深拷贝再 `setdefault`/规范化，避免修改原始配置；或明确在文档/注释中说明「会原地修改」。

---

## 三、功能拓展

### 3.1 端口与类型
- **当前**：端口仅 `data` / `exec` 两种类型。
- **建议**：
  - 若 Ryven 支持更多类型（如自定义 type token），可在 ComboBox 中增加选项，并在模板中输出对应 `NodeInputType`/`NodeOutputType` 参数。
  - 端口增加「可选」勾选（对应 Ryven 的 optional 输入），在模板中生成相应 API。

### 3.2 节点模板与片段
- **当前**：每次从零配置新节点。
- **建议**：
  - 「从模板创建」：内置若干模板（如「单输入单输出 data」「带 exec 的触发器」「带 main widget 的显示节点」），一键生成对应端口与默认 core_logic。
  - 支持「复制节点」：复制当前节点为新节点（class_name 自动加后缀），再微调。

### 3.3 批量与工程
- **当前**：只支持单次导出到一个目录，且固定生成 `nodes.py` + `gui.py` + `widget_template.py`。
- **建议**：
  - 导出时可选「覆盖/备份」：若目标目录已有同名文件，可选择备份为 `nodes.py.bak` 再写入。
  - 可选「仅更新部分文件」：例如只重新生成 `nodes.py` 或只生成 `gui.py`，便于与已有项目融合。
  - （远期）简单「工程」概念：一个工程 = 多组节点配置 + 导出路径，便于管理多套节点集。

### 3.4 输入控件
- **当前**：Input 仅支持 None / int_spinbox / float_spinbox / line_edit / combo_box / slider。
- **建议**：
  - 与 `widget_template.py` 对齐：若模板中已有 checkbox、color_picker 等，在 UI 的 Widget 下拉中增加对应项，并在 `generator.py` 的 GUI 模板中增加分支，生成对应工厂调用。
  - Args 输入可考虑「表单化」：根据当前 Widget 类型动态生成若干输入框（如 init、range_min、range_max），减少手写参数字符串出错。

---

## 四、生成器与模板

### 4.1 模板可维护性
- **当前**：NODES_TEMPLATE / GUI_TEMPLATE 以长字符串写在 `generator.py` 中。
- **建议**：
  - 将模板拆到独立文件（如 `templates/nodes.j2`, `templates/gui.j2`），用 `PackageLoader` 或相对路径加载，便于版本对比与复用。

### 4.2 输出格式
- **当前**：`update_event` 中所有 data 输出先 `set_output_val(..., None)`，实际值依赖用户在 core_logic 里手写。
- **建议**：
  - 若 core_logic 中有可识别的模式（如 `self.set_output_val(0, xxx)`），可考虑在模板中生成占位注释或默认占位，减少漏写。
  - 模板中对 `node.core_logic` 使用 `indent` 时，若用户输入带 Tab/混合缩进，可先做一次「统一为 4 空格」的规范化，避免生成代码缩进混乱。

### 4.3 与 Ryven API 的兼容
- **当前**：GUI 模板里 `int_spinbox` 使用 `inp_widgets.Builder.int_spinbox(...)`，`line_edit` 使用 `evaled_line_edit`，需依赖 Ryven 内置 Builder。
- **建议**：
  - 在文档或 UI 中注明「所需 Ryven 版本」及「依赖的 Builder 接口」。
  - 若未来 Ryven 更改 API，可考虑在 generator 中做版本检测或提供「兼容模式」开关（例如改用 widget_template 中的自定义实现）。

---

## 五、预览模块（node_preview.py）

### 5.1 性能与刷新
- **当前**：每次 `update_preview` 都会重算布局并重绘。
- **建议**：
  - 若后续支持「多节点预览」，可对未变更的节点做缓存（如 boundingRect + 数据哈希），仅变更时重绘。
  - 大量编辑时（如连续输入）可做防抖：300–500ms 内的多次 `update_preview` 合并为一次刷新。

### 5.2 交互与可访问性
- **当前**：预览区仅支持拖拽画布，无缩放。
- **建议**：
  - 支持鼠标滚轮缩放（`QGraphicsView::wheelEvent` + `scale()`），便于大节点或小屏查看。
  - 可选「适应窗口」按钮：`fitInView(node_item, Qt.KeepAspectRatio)`，方便一屏内看到完整节点。

### 5.3 与 Ryven 的同步
- **当前**：预览样式与逻辑独立于 Ryven，Ryven 主题或 API 变更后可能不一致。
- **建议**：
  - 在 README 或注释中说明「预览仅为近似，以实际 Ryven 为准」。
  - 若未来有需要，可提供「从 Ryven 主题文件读取颜色」的脚本或配置，使预览颜色与某主题一致。

---

## 六、工程与协作

### 6.1 文档与示例
- **建议**：
  - 在仓库中提供 1～2 个完整示例 JSON（含多种端口类型、main widget、custom code），便于新用户导入学习。
  - 简短「从 Generator 到 Ryven」的流程说明：导出 → 放入 Ryven 工程 → 在界面中如何找到节点。

### 6.2 测试
- **当前**：无自动化测试。
- **建议**：
  - 对 `generator.generate_code_from_data` 做单元测试：固定 `nodes_data`，断言生成字符串包含关键片段（如类名、端口数、main_widget_class）、且无 Jinja2 异常。
  - 对 `node_preview`：传入若干典型 `node_data`，断言 `_NodeGfx._calc()` 后 `_rect` 尺寸合理、无异常。

### 6.3 依赖与打包
- **建议**：
  - 在项目根目录提供 `requirements.txt`（PySide6、Jinja2），便于复现环境。
  - 若有需要，可用 PyInstaller 等打成单 exe，方便非技术用户使用。

---

## 七、优先级建议（简要）

| 优先级 | 项目 | 说明 |
|--------|------|------|
| 高 | 生成前校验 + 错误提示 | 避免生成无效代码，提升可维护性 |
| 高 | 预览异常时可见错误信息 | 不再静默失败，便于排查 |
| 高 | 导入 JSON 结构校验与默认值 | 防止脏数据导致界面或生成异常 |
| 中 | 节点复制 / 模板创建 | 提高配置效率 |
| 中 | 预览区缩放 / 适应窗口 | 改善预览体验 |
| 中 | 模板拆分为独立 .j2 文件 | 便于维护与版本管理 |
| 低 | QSettings 持久化、最近文件 | 提升日常使用体验 |
| 低 | 单元测试 + 示例 JSON | 保证重构安全与上手成本 |

以上内容可按需裁剪实施，优先做「高」和部分「中」项即可明显提升可用性与可维护性。
