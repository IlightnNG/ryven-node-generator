"""Main application window: node list, editor, code/JSON preview, AI assistant."""

from __future__ import annotations

import copy
import json
import sys
from functools import partial
from pathlib import Path

from PySide6.QtWidgets import (
    QApplication,
    QColorDialog,
    QComboBox,
    QFileDialog,
    QFrame,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QSplitter,
    QTabWidget,
    QTextEdit,
    QToolButton,
    QVBoxLayout,
    QWidget,
)
from PySide6.QtCore import Qt, QSettings, QTimer
from PySide6.QtGui import QFont, QTextCursor

from ryven_node_generator.codegen import generator
from ryven_node_generator.preview.node_preview import NodePreviewWidget
from ryven_node_generator.project import workspace as project_ws

from .constants import (
    EDITOR_LABEL_W,
    EDITOR_ROW_H,
    MAIN_WIDGET_EXAMPLES,
    STYLE,
    _AI_MODIFIED_TEXT_GREEN,
)
from .widgets import NoWheelComboBox, PortCard, _AITurnWorker
class GeneratorDesignerUI(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Ryven Node Generator - Studio")
        self.resize(1500, 920)
        self.setStyleSheet(STYLE)

        self.nodes_data = []
        self.current_idx = -1
        self._is_loading_node = False
        self.in_cards = []
        self.out_cards = []

        self._ai_history = []
        self._ai_last_result = None
        self._ai_worker = None
        self._ai_tab_widget = None
        self._ai_streaming_this_turn = False
        self._ai_turn_in_progress = False
        self._ai_preview_active = False
        self._ai_pending_snapshot_nodes: list | None = None
        self._ai_pending_proposed_nodes: list | None = None
        self._ai_pending_changed_keys: set[str] = set()
        self._ai_highlighted_widgets: set = set()
        self._ai_style_backup: dict[int, str] = {}

        self._project_root: str | None = None
        self._dirty = False
        self._project_init_scheduled = False
        self._save_timer = QTimer(self)
        self._save_timer.setSingleShot(True)
        self._save_timer.timeout.connect(self._flush_project_save)

        self._build_ui()
        self._rebuild_ai_chat_ui()
        self._update_project_bar()
        self.statusBar().showMessage("Starting… select or reopen a project folder.")

    def _build_ui(self):
        container = QWidget()
        root = QVBoxLayout(container)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        top_bar = self._build_top_bar()
        root.addWidget(top_bar)

        splitter = QSplitter(Qt.Horizontal)
        self._panel_left = self._build_left_panel()
        self._panel_editor = self._build_editor_panel()
        self._panel_preview = self._build_preview_panel()
        self._panel_left.setMinimumWidth(160)
        self._panel_editor.setMinimumWidth(220)
        self._panel_preview.setMinimumWidth(220)
        splitter.addWidget(self._panel_left)
        splitter.addWidget(self._panel_editor)
        splitter.addWidget(self._panel_preview)
        splitter.setStretchFactor(0, 1)
        splitter.setStretchFactor(1, 2)
        splitter.setStretchFactor(2, 2)
        splitter.setSizes([300, 600, 600])
        root.addWidget(splitter, 1)

        self.setCentralWidget(container)

    def showEvent(self, event):
        super().showEvent(event)
        if self._project_init_scheduled:
            return
        self._project_init_scheduled = True
        QTimer.singleShot(0, self._bootstrap_project)

    def closeEvent(self, event):
        if self._project_root:
            if self._dirty:
                r = QMessageBox.question(
                    self,
                    "Save project?",
                    "Save changes before closing?",
                    QMessageBox.Save | QMessageBox.Discard | QMessageBox.Cancel,
                    QMessageBox.Save,
                )
                if r == QMessageBox.Cancel:
                    event.ignore()
                    return
                if r == QMessageBox.Save:
                    self._flush_project_save()
            else:
                self._flush_project_save()
        event.accept()

    def _bootstrap_project(self):
        settings = QSettings()
        last = settings.value("last_project_path") or ""
        last = str(last).strip()
        if last and Path(last).is_dir():
            self._load_project_path(last, remember=True)
            return
        if last:
            QMessageBox.warning(
                self,
                "Last project missing",
                f"The saved project folder no longer exists:\n{last}\n\nSelect a new folder.",
            )
        else:
            QMessageBox.information(
                self,
                "Project folder",
                "Choose a folder for this project.\n\n"
                f"Files created: {project_ws.NODES_CONFIG_NAME}, {project_ws.AI_CHAT_NAME}\n"
                "The last folder is reopened automatically on the next launch.",
            )
        start = str(Path.home())
        path = QFileDialog.getExistingDirectory(self, "Select project folder", start)
        if path:
            self._load_project_path(path, remember=True)
        else:
            self._clear_project_session()

    def _clear_project_session(self):
        self._ai_reset_preview_state()
        self._project_root = None
        self._dirty = False
        self.nodes_data = []
        self._ai_history.clear()
        self._ai_last_result = None
        self._ai_turn_in_progress = False
        self._rebuild_ai_chat_ui()
        self.node_list_ui.clear()
        self.current_idx = -1
        self._clear_editor()
        self.update_live_preview()
        self._refresh_counts()
        self._update_project_bar()
        self.setWindowTitle("Ryven Node Generator - Studio")
        self.statusBar().showMessage("No project open — use Open Project…")

    def _update_project_bar(self):
        if self._project_root:
            short = str(Path(self._project_root).name)
            self.project_path_label.setText(f"Project: {short}")
            self.project_path_label.setToolTip(self._project_root)
            self.save_project_btn.setEnabled(True)
        else:
            self.project_path_label.setText("Project: —")
            self.project_path_label.setToolTip("")
            self.save_project_btn.setEnabled(False)

    def _maybe_prompt_save_before_leave(self) -> bool:
        """Return True if caller may proceed (switched project or cancelled)."""
        if not self._dirty or not self._project_root:
            return True
        r = QMessageBox.question(
            self,
            "Save project?",
            "Save changes to the current project before continuing?",
            QMessageBox.Save | QMessageBox.Discard | QMessageBox.Cancel,
            QMessageBox.Save,
        )
        if r == QMessageBox.Cancel:
            return False
        if r == QMessageBox.Save:
            self._flush_project_save()
        else:
            self._dirty = False
        return True

    def open_project_dialog(self):
        if not self._maybe_prompt_save_before_leave():
            return
        start = self._project_root or str(Path.home())
        path = QFileDialog.getExistingDirectory(self, "Open project folder", start)
        if path:
            self._load_project_path(path, remember=True)

    def save_project_manual(self):
        if not self._project_root:
            QMessageBox.information(self, "Save Project", "No project folder open. Use Open Project… first.")
            return
        self._flush_project_save()
        self.statusBar().showMessage("Project saved", 2000)

    def _load_project_path(self, path: str, *, remember: bool):
        root = str(Path(path).resolve())
        try:
            nodes = project_ws.load_nodes_list(root)
        except Exception as e:
            QMessageBox.warning(self, "Project load failed", str(e))
            nodes = []
        try:
            hist = project_ws.load_ai_history(root)
        except Exception:
            hist = []
        self._ai_reset_preview_state()
        self._project_root = root
        self._dirty = False
        self.nodes_data = nodes
        self._ai_history = hist
        self._ai_last_result = None
        if remember:
            settings = QSettings()
            settings.setValue("last_project_path", root)
        self._restore_nodes_ui_from_data()
        self._restore_ai_transcript_ui()
        self._update_project_bar()
        self.setWindowTitle(f"Ryven Node Generator - Studio — {Path(root).name}")
        self.statusBar().showMessage(f"Opened project: {root}", 3000)
        if not nodes:
            self.statusBar().showMessage("Empty project — add a node or import JSON.", 4000)

    def _restore_nodes_ui_from_data(self):
        self.node_list_ui.clear()
        for node in self.nodes_data:
            self.node_list_ui.addItem(self._node_list_text(node))
        if self.nodes_data:
            self.current_idx = -1
            self.node_list_ui.setCurrentRow(0)
        else:
            self.current_idx = -1
            self._clear_editor()
        self._refresh_counts()
        self.update_live_preview()

    def _restore_ai_transcript_ui(self):
        self._rebuild_ai_chat_ui()

    def _ai_chat_interaction_locked(self) -> bool:
        if getattr(self, "_ai_turn_in_progress", False):
            return True
        return self._ai_worker is not None and self._ai_worker.isRunning()

    def _ai_scroll_chat_to_bottom(self):
        if not getattr(self, "ai_chat_scroll", None):
            return
        sb = self.ai_chat_scroll.verticalScrollBar()
        sb.setValue(sb.maximum())

    def _rebuild_ai_chat_ui(self):
        if not getattr(self, "ai_chat_messages_layout", None):
            return
        lay = self.ai_chat_messages_layout
        while lay.count():
            item = lay.takeAt(0)
            w = item.widget()
            if w is None:
                continue
            if w is getattr(self, "_ai_streaming_block", None):
                w.setParent(None)
                continue
            w.deleteLater()

        h = self._ai_history
        i = 0
        n = len(h)
        while i < n:
            role, text = h[i]
            if role == "user":
                lay.addWidget(self._ai_make_user_message_row(text, i))
                i += 1
                if i < n and h[i][0] == "assistant":
                    lay.addWidget(self._ai_make_assistant_bubble(h[i][1]))
                    i += 1
                elif i < n and h[i][0] == "system":
                    lay.addWidget(self._ai_make_system_bubble(h[i][1]))
                    i += 1
            elif role == "assistant":
                lay.addWidget(self._ai_make_assistant_bubble(text))
                i += 1
            elif role == "system":
                lay.addWidget(self._ai_make_system_bubble(text))
                i += 1
            else:
                i += 1

        if self._ai_turn_in_progress:
            self._ai_streaming_editor.clear()
            self._ai_streaming_editor.setPlaceholderText(
                ""
                if getattr(self, "_ai_streaming_this_turn", False)
                else "Waiting for response…"
            )
            self._ai_streaming_block.setVisible(True)
            lay.addWidget(self._ai_streaming_block)
        else:
            self._ai_streaming_block.setVisible(False)
            self._ai_streaming_block.setParent(None)

        lay.addStretch(1)
        QTimer.singleShot(0, self._ai_scroll_chat_to_bottom)

    def _ai_make_user_message_row(self, text: str, user_index: int) -> QWidget:
        row = QWidget()
        rlay = QHBoxLayout(row)
        rlay.setContentsMargins(0, 0, 0, 0)
        rlay.setSpacing(8)
        rlay.setAlignment(Qt.AlignTop)

        btn = QToolButton()
        btn.setObjectName("AiWithdrawBtn")
        btn.setText("\u21a9")
        btn.setToolTip(
            "Withdraw this question and the following reply. "
            "If it was the latest turn, also drops a pending AI preview (same as Undo)."
        )
        btn.setEnabled(not self._ai_chat_interaction_locked())
        btn.clicked.connect(partial(self._ai_withdraw_turn, user_index))

        bubble = QFrame()
        bubble.setObjectName("AiUserBubble")
        blay = QVBoxLayout(bubble)
        blay.setContentsMargins(12, 10, 12, 10)
        blay.setSpacing(4)
        meta = QLabel("You")
        meta.setObjectName("AiChatMeta")
        body = QLabel(text)
        body.setObjectName("AiBubbleBody")
        body.setWordWrap(True)
        body.setTextInteractionFlags(Qt.TextSelectableByMouse)
        blay.addWidget(meta)
        blay.addWidget(body)

        rlay.addWidget(bubble, 1)
        rlay.addWidget(btn, 0, Qt.AlignTop)
        return row

    def _ai_make_assistant_bubble(self, text: str) -> QWidget:
        wrap = QFrame()
        wrap.setObjectName("AiAssistantBubble")
        blay = QVBoxLayout(wrap)
        blay.setContentsMargins(12, 10, 12, 10)
        blay.setSpacing(4)
        meta = QLabel("Assistant")
        meta.setObjectName("AiChatMeta")
        body = QLabel(text)
        body.setObjectName("AiBubbleBody")
        body.setWordWrap(True)
        body.setTextInteractionFlags(Qt.TextSelectableByMouse)
        blay.addWidget(meta)
        blay.addWidget(body)
        return wrap

    def _ai_make_system_bubble(self, text: str) -> QWidget:
        wrap = QFrame()
        wrap.setObjectName("AiSystemBubble")
        blay = QVBoxLayout(wrap)
        blay.setContentsMargins(12, 10, 12, 10)
        blay.setSpacing(4)
        meta = QLabel("System")
        meta.setObjectName("AiChatMeta")
        body = QLabel(text)
        body.setObjectName("AiBubbleBody")
        body.setStyleSheet("color: #c4a9a4;")
        body.setWordWrap(True)
        body.setTextInteractionFlags(Qt.TextSelectableByMouse)
        blay.addWidget(meta)
        blay.addWidget(body)
        return wrap

    def _ai_withdraw_turn(self, user_idx: int):
        if self._ai_chat_interaction_locked():
            return
        h = self._ai_history
        if user_idx < 0 or user_idx >= len(h) or h[user_idx][0] != "user":
            return
        n = len(h)
        last_u = None
        for j in range(n - 1, -1, -1):
            if h[j][0] == "user":
                last_u = j
                break
        is_latest = last_u is not None and user_idx == last_u
        rm_end = user_idx + 1
        if rm_end < n and h[rm_end][0] in ("assistant", "system"):
            rm_end += 1
        if is_latest and self._ai_preview_active:
            self._ai_undo_proposal()
        elif is_latest:
            self._ai_last_result = None
        self._ai_history[:] = h[:user_idx] + h[rm_end:]
        self._rebuild_ai_chat_ui()
        self._schedule_autosave()
        self.statusBar().showMessage("Conversation turn withdrawn.", 2500)

    def _schedule_autosave(self):
        if not self._project_root:
            return
        self._dirty = True
        self._save_timer.stop()
        self._save_timer.start(900)

    def _flush_project_save(self):
        if not self._project_root:
            return
        self._save_timer.stop()
        self.save_current_state(schedule_autosave=False)
        try:
            project_ws.save_nodes_list(self._project_root, self.nodes_data)
            project_ws.save_ai_history(self._project_root, self._ai_history)
            self._dirty = False
        except Exception as e:
            self.statusBar().showMessage(f"Save failed: {e}", 5000)
            QMessageBox.warning(self, "Save failed", str(e))

    def _build_top_bar(self):
        bar = QFrame()
        bar.setObjectName("TopBar")
        bar.setFixedHeight(58)
        lay = QHBoxLayout(bar)
        lay.setContentsMargins(12, 8, 12, 8)
        lay.setSpacing(8)

        self.open_project_btn = QPushButton("Open Project…")
        self.save_project_btn = QPushButton("Save Project")
        self.import_btn = QPushButton("Import JSON")
        self.export_btn = QPushButton("Export JSON")
        self.generate_btn = QPushButton("Generate Code")
        self.generate_btn.setObjectName("PrimaryBtn")
        for btn in (
            self.open_project_btn,
            self.save_project_btn,
            self.import_btn,
            self.export_btn,
            self.generate_btn,
        ):
            btn.setFixedHeight(34)

        self.open_project_btn.clicked.connect(self.open_project_dialog)
        self.save_project_btn.clicked.connect(self.save_project_manual)
        self.import_btn.clicked.connect(self.import_config)
        self.export_btn.clicked.connect(self.export_config)
        self.generate_btn.clicked.connect(self.final_generate)

        self.project_path_label = QLabel("Project: —")
        self.project_path_label.setStyleSheet("color: #7d8c9c;")
        self.project_path_label.setMinimumWidth(72)
        self.node_count_label = QLabel("Nodes: 0")
        self.node_count_label.setStyleSheet("color: #8b9aaa;")

        lay.addWidget(self.open_project_btn)
        lay.addWidget(self.save_project_btn)
        lay.addSpacing(8)
        lay.addWidget(self.import_btn)
        lay.addWidget(self.export_btn)
        lay.addStretch()
        lay.addWidget(self.project_path_label)
        lay.addWidget(self.node_count_label)
        lay.addSpacing(12)
        lay.addWidget(self.generate_btn)
        return bar

    def _build_left_panel(self):
        panel = QWidget()
        panel.setObjectName("LeftPanel")
        lay = QVBoxLayout(panel)
        lay.setContentsMargins(10, 10, 10, 10)
        lay.setSpacing(8)

        self.search_edit = QLineEdit()
        self.search_edit.setPlaceholderText("Search node title...")
        self.search_edit.setFixedHeight(EDITOR_ROW_H)
        self.search_edit.textChanged.connect(self._filter_nodes)
        lay.addWidget(self.search_edit)

        node_btns = QHBoxLayout()
        node_btns.setSpacing(8)
        self.add_node_btn = QPushButton("+ Add Node")
        self.del_node_btn = QPushButton("- Delete Node")
        self.del_node_btn.setObjectName("DangerBtn")
        for b in (self.add_node_btn, self.del_node_btn):
            b.setFixedHeight(EDITOR_ROW_H)
        self.add_node_btn.clicked.connect(self.add_node_action)
        self.del_node_btn.clicked.connect(self.del_node_action)
        node_btns.addWidget(self.add_node_btn, 1)
        node_btns.addWidget(self.del_node_btn, 1)
        lay.addLayout(node_btns)

        self.node_list_ui = QListWidget()
        self.node_list_ui.currentRowChanged.connect(self.handle_node_switch)
        lay.addWidget(self.node_list_ui, 1)
        return panel

    def _build_editor_panel(self):
        panel = QWidget()
        panel.setObjectName("EditorPanel")
        lay = QVBoxLayout(panel)
        lay.setContentsMargins(10, 10, 10, 10)

        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        content = QWidget()
        content.setObjectName("EditorContent")
        self.sl = QVBoxLayout(content)
        self.sl.setContentsMargins(6, 2, 6, 6)
        self.sl.setSpacing(8)

        self._build_core_group()
        self._build_ports_groups()
        self._build_logic_group()
        self._build_main_widget_group()

        self.sl.addStretch()
        self.scroll.setWidget(content)
        lay.addWidget(self.scroll)
        return panel

    def _build_preview_panel(self):
        panel = QWidget()
        panel.setObjectName("PreviewPanel")
        lay = QVBoxLayout(panel)
        lay.setContentsMargins(10, 10, 10, 10)
        self.preview_tabs = QTabWidget()
        self.nodes_preview = QTextEdit()
        self.nodes_preview.setReadOnly(True)
        self.gui_preview = QTextEdit()
        self.gui_preview.setReadOnly(True)
        self.json_preview = QTextEdit()
        self.json_preview.setReadOnly(True)
        self.json_preview.setPlaceholderText("Full project node list as JSON (same as nodes_config.json)…")
        jf = QFont()
        jf.setFamilies(["Consolas", "Courier New", "monospace"])
        jf.setPointSize(10)
        jf.setStyleHint(QFont.StyleHint.Monospace)
        self.json_preview.setFont(jf)
        self.node_preview = NodePreviewWidget()
        self.preview_tabs.addTab(self.nodes_preview, "nodes.py")
        self.preview_tabs.addTab(self.gui_preview, "gui.py")
        self.preview_tabs.addTab(self.json_preview, "nodes_config.json")
        self.preview_tabs.addTab(self.node_preview, "Preview")

        ai_tab = QWidget()
        self._ai_tab_widget = ai_tab
        ai_lay = QVBoxLayout(ai_tab)
        ai_lay.setContentsMargins(10, 10, 10, 10)
        ai_lay.setSpacing(10)

        ai_header = QLabel(
            "Assistant · API keys in <code>.env</code> at the repository root "
            "(<code>OPENAI_API_KEY</code> or <code>DASHSCOPE_API_KEY</code>; optional "
            "<code>LLM_PROVIDER</code> / <code>OPENAI_BASE_URL</code> for Bailian)."
        )
        ai_header.setWordWrap(True)
        ai_header.setTextFormat(Qt.RichText)
        ai_header.setObjectName("AiHeaderHint")
        ai_header.setStyleSheet("color: #8b98a8; font-size: 11px; background: transparent;")

        self.ai_chat_scroll = QScrollArea()
        self.ai_chat_scroll.setObjectName("AiChatScroll")
        self.ai_chat_scroll.setWidgetResizable(True)
        self.ai_chat_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.ai_chat_inner = QWidget()
        self.ai_chat_messages_layout = QVBoxLayout(self.ai_chat_inner)
        self.ai_chat_messages_layout.setContentsMargins(8, 8, 8, 8)
        self.ai_chat_messages_layout.setSpacing(10)
        self.ai_chat_scroll.setWidget(self.ai_chat_inner)

        self._ai_streaming_block = QWidget()
        _sbl = QVBoxLayout(self._ai_streaming_block)
        _sbl.setContentsMargins(0, 0, 0, 0)
        _sbl.setSpacing(4)
        _stream_meta = QLabel("Assistant")
        _stream_meta.setObjectName("AiChatMeta")
        self._ai_streaming_editor = QTextEdit()
        self._ai_streaming_editor.setObjectName("AiStreamEditor")
        self._ai_streaming_editor.setReadOnly(True)
        self._ai_streaming_editor.setMinimumHeight(88)
        self._ai_streaming_editor.setPlaceholderText("…")
        _sbl.addWidget(_stream_meta)
        _sbl.addWidget(self._ai_streaming_editor)
        self._ai_streaming_block.setVisible(False)

        self.ai_context_label = QLabel("AI context node: —")
        self.ai_context_label.setWordWrap(True)
        self.ai_context_label.setStyleSheet("color: #9aacbc; font-weight: 600; padding: 2px 0;")

        input_card = QWidget()
        input_card.setObjectName("AiInputCard")
        input_outer = QVBoxLayout(input_card)
        input_outer.setContentsMargins(10, 10, 10, 10)
        input_outer.setSpacing(8)
        self.ai_input = QTextEdit()
        self.ai_input.setObjectName("AiChatComposer")
        self.ai_input.setFixedHeight(76)
        self.ai_input.setPlaceholderText("Ask for changes to the selected node…")
        ai_row = QHBoxLayout()
        ai_row.setSpacing(10)
        ai_row.addStretch(1)
        self.ai_send_btn = QPushButton("Send")
        self.ai_send_btn.setMinimumWidth(88)
        self.ai_send_btn.setDefault(True)
        self.ai_send_btn.setAutoDefault(True)
        self.ai_keep_btn = QPushButton("Keep")
        self.ai_undo_btn = QPushButton("Undo")
        self.ai_keep_btn.setToolTip("Accept the pending AI change (writes to nodes_config).")
        self.ai_undo_btn.setToolTip("Discard the pending AI change and restore the previous config.")
        self.ai_keep_btn.setEnabled(False)
        self.ai_undo_btn.setEnabled(False)
        self.ai_send_btn.clicked.connect(self._ai_on_send)
        self.ai_keep_btn.clicked.connect(self._ai_keep_proposal)
        self.ai_undo_btn.clicked.connect(self._ai_undo_proposal)
        input_outer.addWidget(self.ai_input)
        ai_row.addWidget(self.ai_send_btn)
        input_outer.addLayout(ai_row)

        ai_lay.addWidget(ai_header)
        ai_lay.addWidget(self.ai_chat_scroll, 1)
        ai_lay.addWidget(self.ai_context_label)
        ai_lay.addWidget(input_card)
        self.preview_tabs.addTab(ai_tab, "AI")

        lay.addWidget(self.preview_tabs, 1)
        commit_row = QHBoxLayout()
        commit_row.setContentsMargins(0, 8, 0, 0)
        commit_row.setSpacing(10)
        commit_row.addWidget(self.ai_keep_btn)
        commit_row.addWidget(self.ai_undo_btn)
        commit_row.addStretch()
        self._ai_commit_hint = QLabel(
            "When the AI proposes config changes, review the JSON tab, then Keep or Undo here."
        )
        self._ai_commit_hint.setStyleSheet("color: #8b98a8; font-size: 11px;")
        self._ai_commit_hint.setWordWrap(True)
        commit_row.addWidget(self._ai_commit_hint, 1)
        lay.addLayout(commit_row)
        return panel

    def _build_core_group(self):
        g = QGroupBox("Core Properties")
        l = QVBoxLayout(g)
        l.setSpacing(6)
        self.name_edit = QLineEdit()
        self.title_edit = QLineEdit()
        self.desc_edit = QLineEdit()
        self.desc_edit.setPlaceholderText("Brief description of this node")
        self.color_btn = QPushButton("Color…")
        self.color_btn.clicked.connect(self.pick_color)
        self.color_btn.setFixedWidth(96)
        self.name_edit.setFixedHeight(EDITOR_ROW_H)
        self.title_edit.setFixedHeight(EDITOR_ROW_H)
        self.desc_edit.setFixedHeight(EDITOR_ROW_H)
        self.color_btn.setFixedHeight(EDITOR_ROW_H)

        row_name = QHBoxLayout()
        row_name.setContentsMargins(0, 0, 0, 0)
        row_name.setSpacing(8)
        lbl_name = QLabel("Class Name")
        lbl_name.setFixedWidth(EDITOR_LABEL_W)
        row_name.addWidget(lbl_name)
        row_name.addWidget(self.name_edit, 1, Qt.AlignVCenter)
        row_name.addWidget(self.color_btn, 0, Qt.AlignRight | Qt.AlignVCenter)
        l.addLayout(row_name)

        row_title = QHBoxLayout()
        row_title.setContentsMargins(0, 0, 0, 0)
        row_title.setSpacing(8)
        lbl_title = QLabel("Node Title")
        lbl_title.setFixedWidth(EDITOR_LABEL_W)
        row_title.addWidget(lbl_title)
        row_title.addWidget(self.title_edit, 1)
        l.addLayout(row_title)

        row_desc = QHBoxLayout()
        row_desc.setContentsMargins(0, 0, 0, 0)
        row_desc.setSpacing(8)
        lbl_desc = QLabel("Description")
        lbl_desc.setFixedWidth(EDITOR_LABEL_W)
        row_desc.addWidget(lbl_desc)
        row_desc.addWidget(self.desc_edit, 1)
        l.addLayout(row_desc)
        self.sl.addWidget(g)

        self.name_edit.editingFinished.connect(self.save_current_state)
        self.title_edit.editingFinished.connect(self.save_current_state)
        self.desc_edit.editingFinished.connect(self.save_current_state)

    def _build_ports_groups(self):
        self.in_group = QGroupBox("Input Ports")
        self.in_layout = QVBoxLayout(self.in_group)
        self.in_layout.setSpacing(6)
        in_header = QHBoxLayout()
        in_header.addStretch()
        self.btn_in = QPushButton("+ Add Input")
        self.btn_in.setFixedHeight(EDITOR_ROW_H)
        self.btn_in.clicked.connect(lambda: self.add_port_ui(True))
        in_header.addWidget(self.btn_in)
        self.in_layout.addLayout(in_header)
        self.sl.addWidget(self.in_group)

        self.out_group = QGroupBox("Output Ports")
        self.out_layout = QVBoxLayout(self.out_group)
        self.out_layout.setSpacing(6)
        out_header = QHBoxLayout()
        out_header.addStretch()
        self.btn_out = QPushButton("+ Add Output")
        self.btn_out.setFixedHeight(EDITOR_ROW_H)
        self.btn_out.clicked.connect(lambda: self.add_port_ui(False))
        out_header.addWidget(self.btn_out)
        self.out_layout.addLayout(out_header)
        self.sl.addWidget(self.out_group)

    def _build_logic_group(self):
        g = QGroupBox("Node Core Logic")
        l = QVBoxLayout(g)
        self.logic_edit = QTextEdit()
        self.logic_edit.setObjectName("NodeLogicEdit")
        self.logic_edit.setFixedHeight(120)
        l.addWidget(self.logic_edit)
        self.logic_edit.textChanged.connect(self.save_current_state)
        self.sl.addWidget(g)

    def _build_main_widget_group(self):
        g = QGroupBox("Main Widget")
        l = QVBoxLayout(g)
        self.mw_type = NoWheelComboBox()
        self.mw_type.addItems(["None", "button", "text_display", "image_display", "matrix_display", "custom"])
        self.mw_pos = NoWheelComboBox()
        self.mw_pos.addItems(["below ports", "between ports"])
        self.mw_args = QLineEdit()
        self.mw_args.setFixedHeight(EDITOR_ROW_H)
        self.mw_type.setFixedHeight(EDITOR_ROW_H)
        self.mw_pos.setFixedHeight(EDITOR_ROW_H)
        self.mw_text = QTextEdit()
        self.mw_text.setObjectName("MwCodeEdit")
        self.mw_text.setFixedHeight(96)
        self.mw_text.setPlaceholderText("# Custom widget code here")

        self.mw_pos_label = QLabel("Main Widget Position")
        self.mw_args_label = QLabel("Main Widget Args")

        l.addWidget(QLabel("Main Widget Template"))
        l.addWidget(self.mw_type)
        l.addWidget(self.mw_pos_label)
        l.addWidget(self.mw_pos)
        l.addWidget(self.mw_args_label)
        l.addWidget(self.mw_args)
        l.addWidget(self.mw_text)
        self.sl.addWidget(g)

        self.mw_type.currentTextChanged.connect(self._on_main_widget_type_changed)
        self.mw_type.currentTextChanged.connect(self.save_current_state)
        self.mw_pos.currentTextChanged.connect(self.save_current_state)
        self.mw_args.editingFinished.connect(self.save_current_state)
        self.mw_text.textChanged.connect(self.save_current_state)
        self._on_main_widget_type_changed(self.mw_type.currentText())

    def _node_list_text(self, node):
        return f"{node.get('title', 'Node')}  ({node.get('class_name', '-')})"

    def _next_node_name(self):
        base = "NewNode"
        existing = {n["class_name"] for n in self.nodes_data}
        if base not in existing:
            return base
        idx = 2
        while f"{base}{idx}" in existing:
            idx += 1
        return f"{base}{idx}"

    def _filter_nodes(self, keyword):
        keyword = keyword.strip().lower()
        for i in range(self.node_list_ui.count()):
            item = self.node_list_ui.item(i)
            item.setHidden(keyword not in item.text().lower())

    def _refresh_counts(self):
        self.node_count_label.setText(f"Nodes: {len(self.nodes_data)}")
        self.in_group.setTitle(f"Input Ports ({len(self.in_cards)})")
        self.out_group.setTitle(f"Output Ports ({len(self.out_cards)})")

    def save_current_state(self, schedule_autosave: bool = True):
        if self._is_loading_node:
            return
        if self._ai_preview_active:
            return
        if self.current_idx < 0 or self.current_idx >= len(self.nodes_data):
            return

        node = self.nodes_data[self.current_idx]
        node.update({
            "class_name": self.name_edit.text(),
            "title": self.title_edit.text(),
            "description": self.desc_edit.text(),
            "color": node.get("color", "#ffffff"),
            "inputs": [p.get_data() for p in self.in_cards],
            "outputs": [p.get_data() for p in self.out_cards],
            "core_logic": self.logic_edit.toPlainText(),
            "has_main_widget": self.mw_type.currentText() != "None",
            "main_widget_template": self.mw_type.currentText(),
            "main_widget_args": self.mw_args.text(),
            "main_widget_pos": self.mw_pos.currentText(),
            "main_widget_code": self.mw_text.toPlainText(),
        })

        item = self.node_list_ui.item(self.current_idx)
        if item:
            item.setText(self._node_list_text(node))
        self.update_live_preview()
        self.statusBar().showMessage("Node updated", 1500)
        if schedule_autosave:
            self._schedule_autosave()

    def handle_node_switch(self, row):
        if row == self.current_idx or row == -1:
            return
        if self._ai_preview_active:
            r = QMessageBox.question(
                self,
                "AI preview",
                "Discard the pending AI change and switch to another node?",
                QMessageBox.Yes | QMessageBox.No,
                QMessageBox.No,
            )
            if r != QMessageBox.Yes:
                self.node_list_ui.blockSignals(True)
                self.node_list_ui.setCurrentRow(self.current_idx)
                self.node_list_ui.blockSignals(False)
                return
            self._ai_undo_proposal()
        self.save_current_state()
        self.current_idx = row
        if 0 <= row < len(self.nodes_data):
            self.load_node_to_ui(self.nodes_data[row])

    def load_node_to_ui(self, node):
        self._is_loading_node = True
        try:
            for w in self.in_cards + self.out_cards:
                w.deleteLater()
            self.in_cards.clear()
            self.out_cards.clear()

            self.name_edit.setText(node.get("class_name", ""))
            self.title_edit.setText(node.get("title", ""))
            self.desc_edit.setText(node.get("description", ""))
            color = node.get("color", "#ffffff")
            self.color_btn.setText(color)
            self.color_btn.setToolTip(f"Node color {color}")
            self.color_btn.setStyleSheet(f"color: {color};")
            self.logic_edit.setPlainText(node.get("core_logic", "pass"))

            for p in node.get("inputs", []):
                self.add_port_ui(True, p, save_state=False)
            for p in node.get("outputs", []):
                self.add_port_ui(False, p, save_state=False)

            if node.get("has_main_widget", False):
                self.mw_type.setCurrentText(node.get("main_widget_template", "button"))
            else:
                self.mw_type.setCurrentText("None")
            self.mw_pos.setCurrentText(node.get("main_widget_pos", "below ports"))
            self.mw_args.setText(node.get("main_widget_args", MAIN_WIDGET_EXAMPLES.get(self.mw_type.currentText(), "")))
            self.mw_text.setPlainText(node.get("main_widget_code", "# Your custom initialization code here"))
            self._on_main_widget_type_changed(self.mw_type.currentText())
            self._refresh_port_order_ui()
        finally:
            self._is_loading_node = False
        self.update_live_preview()

    def add_node_action(self):
        if self._ai_preview_active:
            self._ai_undo_proposal()
        self.save_current_state()
        name = self._next_node_name()
        new_node = {
            "class_name": name,
            "title": name,
            "color": "#ffffff",
            "inputs": [],
            "outputs": [],
            "core_logic": "pass",
            "description": "Auto generated",
            "has_main_widget": False,
            "main_widget_template": "None",
            "main_widget_args": "",
            "main_widget_pos": "below ports",
            "main_widget_code": "# Your custom initialization code here",
        }
        self.nodes_data.append(new_node)
        self.node_list_ui.addItem(self._node_list_text(new_node))
        self.node_list_ui.setCurrentRow(len(self.nodes_data) - 1)
        self._refresh_counts()
        self.statusBar().showMessage("New node added", 1500)
        self._schedule_autosave()

    def del_node_action(self):
        if self.current_idx == -1:
            return
        if self._ai_preview_active:
            self._ai_undo_proposal()
        self.nodes_data.pop(self.current_idx)
        self.node_list_ui.takeItem(self.current_idx)
        if self.nodes_data:
            next_row = min(self.current_idx, len(self.nodes_data) - 1)
            self.current_idx = -1
            self.node_list_ui.setCurrentRow(next_row)
        else:
            self.current_idx = -1
            self._clear_editor()
            self.nodes_preview.clear()
            self.gui_preview.clear()
        self._refresh_counts()
        self.statusBar().showMessage("Node deleted", 1500)
        self._schedule_autosave()
        self.update_live_preview()

    def _clear_editor(self):
        self.name_edit.clear()
        self.title_edit.clear()
        self.desc_edit.clear()
        self.logic_edit.clear()
        self.mw_type.setCurrentText("None")
        self.mw_args.clear()
        self.mw_text.clear()
        for w in self.in_cards + self.out_cards:
            w.deleteLater()
        self.in_cards.clear()
        self.out_cards.clear()
        self._refresh_port_order_ui()

    def add_port_ui(self, is_input, data=None, save_state=True):
        if data is None:
            idx = len(self.in_cards) if is_input else len(self.out_cards)
            prefix = "input" if is_input else "output"
            data = {"label": f"{prefix}{idx}", "type": "data"}

        card = PortCard(is_input=is_input, data=data)
        card.changed.connect(self.save_current_state)
        card.move_requested.connect(lambda delta: self.move_port(card, is_input, delta))
        card.remove_requested.connect(lambda: self.remove_port(card, is_input))

        target_layout = self.in_layout if is_input else self.out_layout
        target_layout.addWidget(card)
        (self.in_cards if is_input else self.out_cards).append(card)

        self._refresh_port_order_ui()
        if save_state:
            self.save_current_state()

    def remove_port(self, card, is_input):
        cards = self.in_cards if is_input else self.out_cards
        if card not in cards:
            return
        cards.remove(card)
        card.deleteLater()
        self._refresh_port_order_ui()
        self.save_current_state()

    def move_port(self, card, is_input, delta):
        cards = self.in_cards if is_input else self.out_cards
        if card not in cards:
            return
        idx = cards.index(card)
        new_idx = idx + delta
        if new_idx < 0 or new_idx >= len(cards):
            return
        cards[idx], cards[new_idx] = cards[new_idx], cards[idx]

        layout = self.in_layout if is_input else self.out_layout
        for w in cards:
            layout.removeWidget(w)
        for w in cards:
            layout.addWidget(w)

        self._refresh_port_order_ui()
        self.save_current_state()

    def _refresh_port_order_ui(self):
        for cards in (self.in_cards, self.out_cards):
            total = len(cards)
            for idx, card in enumerate(cards):
                card.set_order_state(idx, total)
        self._refresh_counts()

    def _on_main_widget_type_changed(self, widget_type):
        has_widget = widget_type != "None"
        self.mw_pos_label.setVisible(has_widget)
        self.mw_pos.setVisible(has_widget)
        self.mw_args_label.setVisible(has_widget)
        self.mw_args.setVisible(has_widget)
        self.mw_text.setVisible(widget_type == "custom")

        example = MAIN_WIDGET_EXAMPLES.get(widget_type, "")
        self.mw_args.setPlaceholderText(example if example else "key='value'")
        if self._is_loading_node:
            return

        if self.current_idx < 0 or self.current_idx >= len(self.nodes_data):
            if not self.mw_args.text():
                self.mw_args.setText(example)
            return

        node = self.nodes_data[self.current_idx]
        previous_type = node.get("main_widget_template", "None")
        previous_example = MAIN_WIDGET_EXAMPLES.get(previous_type, "")
        current_args = self.mw_args.text().strip()
        if current_args == "" or current_args == previous_example:
            self.mw_args.setText(example)

    def _update_json_preview(self):
        if (
            self._ai_preview_active
            and self._ai_pending_snapshot_nodes is not None
            and self._ai_pending_proposed_nodes is not None
        ):
            from ryven_node_generator.ai_assistant.preview_diff import json_list_diff_html

            try:
                html_doc = json_list_diff_html(
                    self._ai_pending_snapshot_nodes,
                    self._ai_pending_proposed_nodes,
                )
                self.json_preview.setHtml(html_doc)
            except Exception as e:
                self.json_preview.setPlainText(f"(JSON diff error: {e})")
            return
        if not self.nodes_data:
            self.json_preview.clear()
            return
        try:
            self.json_preview.setPlainText(
                json.dumps(self.nodes_data, indent=4, ensure_ascii=False)
            )
        except Exception as e:
            self.json_preview.setPlainText(f"(JSON preview error: {e})")

    def _update_ai_context_label(self):
        if self.current_idx < 0 or self.current_idx >= len(self.nodes_data):
            self.ai_context_label.setText(
                "AI context node: (none selected — choose a node in the list to send its config)"
            )
            self.ai_context_label.setStyleSheet("color: #8b98a8; font-weight: 600; padding: 4px 0;")
            return
        if self._ai_preview_active and self._ai_pending_proposed_nodes is not None:
            n = self._ai_pending_proposed_nodes[self.current_idx]
        else:
            n = self.nodes_data[self.current_idx]
        cn = n.get("class_name", "?")
        tl = n.get("title", "?")
        self.ai_context_label.setText(
            f"AI context node: {cn}  —  «{tl}»  (index {self.current_idx} in nodes_config.json)"
        )
        self.ai_context_label.setStyleSheet("color: #9aacbc; font-weight: 600; padding: 4px 0;")

    def update_live_preview(self):
        self._update_json_preview()
        self._update_ai_context_label()
        if not self.nodes_data:
            self.nodes_preview.clear()
            self.gui_preview.clear()
            return
        try:
            n_code, g_code = generator.generate_code_from_data(self.nodes_data)
            self.nodes_preview.setPlainText(n_code)
            self.gui_preview.setPlainText(g_code)
        except Exception as e:
            self.statusBar().showMessage(f"Code preview error: {e}", 4000)
            return

        if 0 <= self.current_idx < len(self.nodes_data):
            self.node_preview.update_preview(self.nodes_data[self.current_idx])

    def pick_color(self):
        if self.current_idx < 0 or self.current_idx >= len(self.nodes_data):
            return
        if self._ai_preview_active:
            QMessageBox.information(
                self,
                "AI preview",
                "Keep or Undo the AI suggestion before changing node color.",
            )
            return
        c = QColorDialog.getColor()
        if c.isValid():
            self.nodes_data[self.current_idx]["color"] = c.name()
            self.color_btn.setText(c.name())
            self.color_btn.setToolTip(f"Node color {c.name()}")
            self.color_btn.setStyleSheet(f"color: {c.name()};")
            self.save_current_state()

    def import_config(self):
        fname, _ = QFileDialog.getOpenFileName(self, "Import Node Config", "", "JSON Files (*.json)")
        if not fname:
            return
        self._ai_reset_preview_state()
        try:
            with open(fname, "r", encoding="utf-8") as f:
                data = json.load(f)
            if not isinstance(data, list):
                raise ValueError("JSON root must be a list.")
            self.nodes_data = data
        except Exception as e:
            QMessageBox.warning(self, "Import Failed", f"Cannot import config:\n{e}")
            return

        self.node_list_ui.clear()
        for node in self.nodes_data:
            self.node_list_ui.addItem(self._node_list_text(node))

        if self.nodes_data:
            self.node_list_ui.setCurrentRow(0)
        else:
            self.current_idx = -1
            self._clear_editor()
        self._refresh_counts()
        self.update_live_preview()
        self.statusBar().showMessage("Config imported", 2000)
        self._schedule_autosave()

    def export_config(self):
        if self._ai_preview_active:
            QMessageBox.information(
                self,
                "Export",
                "Keep or Undo the AI suggestion first. Export uses the last committed node list.",
            )
            return
        self.save_current_state()
        fname, _ = QFileDialog.getSaveFileName(self, "Export Node Config", "nodes_config.json", "JSON Files (*.json)")
        if not fname:
            return
        try:
            with open(fname, "w", encoding="utf-8") as f:
                json.dump(self.nodes_data, f, indent=4, ensure_ascii=False)
            self.statusBar().showMessage("Config exported", 2000)
        except Exception as e:
            QMessageBox.warning(self, "Export Failed", f"Cannot export config:\n{e}")

    def _ai_set_busy(self, busy: bool):
        self.ai_send_btn.setEnabled(True)
        self.ai_send_btn.setText("Stop" if busy else "Send")
        self.ai_input.setEnabled(not busy)
        if busy:
            self.ai_keep_btn.setEnabled(False)
            self.ai_undo_btn.setEnabled(False)
            self._rebuild_ai_chat_ui()
        else:
            self._ai_refresh_commit_buttons()

    def _ai_begin_assistant_stream(self):
        self._ai_streaming_editor.clear()
        self._ai_streaming_editor.setPlaceholderText("AI is thinking and generating…")

    def _ai_on_stream_delta(self, s: str):
        if not s:
            return
        self._ai_streaming_editor.moveCursor(QTextCursor.End)
        self._ai_streaming_editor.insertPlainText(s)
        self._ai_streaming_editor.ensureCursorVisible()

    def _ai_on_send(self):
        if self._ai_worker is not None and self._ai_worker.isRunning():
            self._ai_worker.stop()
            self.statusBar().showMessage("Stopping AI generation…", 2000)
            return
        if self._ai_preview_active:
            QMessageBox.information(
                self,
                "AI",
                "Keep or Undo the current AI suggestion before sending another message.",
            )
            return
        self.save_current_state()
        if self.current_idx < 0 or not self.nodes_data:
            QMessageBox.warning(self, "AI", "Select a node first.")
            return
        text = self.ai_input.toPlainText().strip()
        if not text:
            return
        self.ai_input.clear()
        self._ai_history.append(("user", text))
        self._ai_turn_in_progress = True
        if self._ai_tab_widget is not None:
            self.preview_tabs.setCurrentWidget(self._ai_tab_widget)

        from ryven_node_generator.ai_assistant.config import ai_stream_enabled

        self._ai_streaming_this_turn = ai_stream_enabled()
        if self._ai_streaming_this_turn:
            self._ai_begin_assistant_stream()

        node = copy.deepcopy(self.nodes_data[self.current_idx])
        names = [n.get("class_name", "") for n in self.nodes_data]
        self._ai_set_busy(True)
        hist_for_api = list(self._ai_history[:-1])
        self._ai_worker = _AITurnWorker(text, hist_for_api, node, names, self)
        self._ai_worker.stream_delta.connect(self._ai_on_stream_delta)
        self._ai_worker.progress_event.connect(self._ai_on_worker_progress)
        self._ai_worker.finished_ok.connect(self._ai_on_worker_ok)
        self._ai_worker.stopped.connect(self._ai_on_worker_stopped)
        self._ai_worker.failed.connect(self._ai_on_worker_failed)
        self._ai_worker.finished.connect(self._ai_worker_cleanup)
        self._ai_worker.start()

    def _ai_worker_cleanup(self):
        self._ai_worker = None

    def _ai_on_worker_progress(self, event: dict):
        et = str((event or {}).get("type", ""))
        if et == "round_start":
            rnd = int(event.get("round", 1))
            mx = int(event.get("max_rounds", rnd))
            self._ai_history.append(("system", f"Round {rnd}/{mx}: generating and validating core_logic"))
        elif et == "round_result":
            rnd = int(event.get("round", 1))
            status = str(event.get("status", "failed"))
            reason = str(event.get("reason", "")).strip()
            icon = "✅" if status == "passed" else "❌"
            msg = f"Round {rnd} {icon} {status}"
            if reason:
                msg += f"\n- {reason}"
            self._ai_history.append(("system", msg))
        elif et == "test_result":
            rnd = int(event.get("round", 1))
            passed = int(event.get("passed", 0))
            total = int(event.get("total", 0))
            all_passed = bool(event.get("all_passed", False))
            icon = "✅" if all_passed else "❌"
            details = [str(x) for x in (event.get("details") or []) if str(x).strip()]
            msg = f"Round {rnd} tests {icon} {passed}/{total} passed"
            if details:
                msg += "\n- " + "\n- ".join(details[:2])
            self._ai_history.append(("system", msg))
        elif et == "test_cases":
            rnd = int(event.get("round", 1))
            summary = [str(x) for x in (event.get("summary") or []) if str(x).strip()]
            msg = f"Round {rnd} cases: {', '.join(summary[:3])}" if summary else f"Round {rnd} cases: default smoke"
            self._ai_history.append(("system", msg))
        else:
            return
        self._rebuild_ai_chat_ui()
        self._schedule_autosave()

    def _ai_on_worker_ok(self, result: dict):
        self._ai_turn_in_progress = False
        msg = result.get("message", "")
        if getattr(self, "_ai_streaming_this_turn", False):
            sr = result.get("_streamed_reply_plain") or ""
            if len(sr) > 0 and msg.startswith(sr):
                tail = msg[len(sr) :].lstrip("\n\r")
                if tail.strip():
                    self._ai_on_stream_delta("\n" + tail + "\n")
            elif not result.get("_stream_had_visible_reply") and msg.strip():
                self._ai_on_stream_delta(msg + "\n")
            self._ai_on_stream_delta("\n")
        self._ai_history.append(("assistant", msg))
        trace = result.get("repair_trace") or []
        if trace:
            final_round = int(result.get("repair_round", len(trace)))
            passed_rounds = sum(1 for t in trace if str(t.get("status")) == "passed")
            self._ai_history.append(
                (
                    "system",
                    f"Self-repair finished: {len(trace)} rounds, using round {final_round}; passed rounds {passed_rounds}/{len(trace)}.",
                )
            )
        self._ai_last_result = result
        self._ai_set_busy(False)
        self._ai_try_present_preview(result)
        self._rebuild_ai_chat_ui()
        self.statusBar().showMessage("AI reply received", 2000)
        self._schedule_autosave()

    def _ai_on_worker_failed(self, err: str):
        self._ai_turn_in_progress = False
        self._ai_history.append(("system", f"Request failed: {err}"))
        self._ai_set_busy(False)
        self._rebuild_ai_chat_ui()
        self._schedule_autosave()
        QMessageBox.warning(self, "AI error", err)

    def _ai_on_worker_stopped(self):
        self._ai_turn_in_progress = False
        self._ai_history.append(("system", "Generation stopped by user."))
        self._ai_set_busy(False)
        self._rebuild_ai_chat_ui()
        self._schedule_autosave()

    def _ai_build_patch_from_result(self, result: dict) -> dict:
        logic = result.get("core_logic")
        patch = dict(result.get("config_patch") or {})
        if logic:
            patch["core_logic"] = logic
        return patch

    def _ai_reset_preview_state(self):
        self._clear_ai_field_highlights()
        self._ai_preview_active = False
        self._ai_pending_snapshot_nodes = None
        self._ai_pending_proposed_nodes = None
        self._ai_pending_changed_keys = set()
        self._ai_refresh_commit_buttons()

    def _clear_ai_field_highlights(self):
        for w in list(self._ai_highlighted_widgets):
            wid = id(w)
            if wid in self._ai_style_backup:
                w.setStyleSheet(self._ai_style_backup[wid])
        self._ai_highlighted_widgets.clear()
        self._ai_style_backup.clear()

    def _ai_tint_widget_text(self, w: QWidget):
        """Mark a control as AI-modified: muted green text (no border)."""
        if w is None:
            return
        self._ai_highlighted_widgets.add(w)
        wid = id(w)
        if wid not in self._ai_style_backup:
            self._ai_style_backup[wid] = w.styleSheet() or ""
        orig = self._ai_style_backup[wid]
        c = _AI_MODIFIED_TEXT_GREEN
        if isinstance(w, QLineEdit):
            w.setStyleSheet(orig + f"\nQLineEdit {{ color: {c}; }}")
        elif isinstance(w, QTextEdit):
            w.setStyleSheet(orig + f"\nQTextEdit {{ color: {c}; }}")
        elif isinstance(w, QComboBox):
            w.setStyleSheet(
                orig
                + f"\nQComboBox {{ color: {c}; }}"
                + f"\nQComboBox QAbstractItemView {{ color: {c}; }}"
            )
        elif isinstance(w, QPushButton):
            w.setStyleSheet(orig + f"\nQPushButton {{ color: {c}; }}")
        else:
            w.setStyleSheet(orig + f"\ncolor: {c};")

    def _apply_ai_field_highlights(self, keys: set[str]):
        self._clear_ai_field_highlights()
        if not keys:
            return
        mw_keys = {
            "has_main_widget",
            "main_widget_template",
            "main_widget_args",
            "main_widget_pos",
            "main_widget_code",
        }
        if "class_name" in keys:
            self._ai_tint_widget_text(self.name_edit)
        if "title" in keys:
            self._ai_tint_widget_text(self.title_edit)
        if "description" in keys:
            self._ai_tint_widget_text(self.desc_edit)
        if "color" in keys:
            self._ai_tint_widget_text(self.color_btn)
        if "core_logic" in keys:
            self._ai_tint_widget_text(self.logic_edit)
        if "inputs" in keys:
            for card in self.in_cards:
                self._ai_tint_widget_text(card.label_edit)
                self._ai_tint_widget_text(card.type_combo)
                if hasattr(card, "w_type"):
                    self._ai_tint_widget_text(card.w_type)
                    self._ai_tint_widget_text(card.w_pos)
                    self._ai_tint_widget_text(card.w_args)
        if "outputs" in keys:
            for card in self.out_cards:
                self._ai_tint_widget_text(card.label_edit)
                self._ai_tint_widget_text(card.type_combo)
        if keys & mw_keys:
            self._ai_tint_widget_text(self.mw_type)
            self._ai_tint_widget_text(self.mw_pos)
            self._ai_tint_widget_text(self.mw_args)
            self._ai_tint_widget_text(self.mw_text)

    def _ai_refresh_commit_buttons(self):
        worker_busy = self._ai_worker is not None and self._ai_worker.isRunning()
        on = self._ai_preview_active and not worker_busy
        self.ai_keep_btn.setEnabled(on)
        self.ai_undo_btn.setEnabled(on)

    def _ai_try_present_preview(self, result: dict):
        from ryven_node_generator.ai_assistant.merge import apply_config_patch
        from ryven_node_generator.ai_assistant.preview_diff import node_changed_keys

        patch = self._ai_build_patch_from_result(result)
        if not patch:
            self._ai_refresh_commit_buttons()
            return
        idx = self.current_idx
        if idx < 0 or idx >= len(self.nodes_data):
            self._ai_refresh_commit_buttons()
            return

        snap = copy.deepcopy(self.nodes_data)
        prop = copy.deepcopy(self.nodes_data)
        skipped = apply_config_patch(prop[idx], patch)
        ch = node_changed_keys(snap[idx], prop[idx])
        if skipped:
            short = "; ".join(skipped[:4])
            if len(skipped) > 4:
                short += "…"
            self.statusBar().showMessage(short, 6000)
        if not ch:
            self._ai_refresh_commit_buttons()
            if patch:
                self.statusBar().showMessage(
                    "AI reply has no effective config change on this node.", 3500
                )
            return

        self._ai_pending_snapshot_nodes = snap
        self._ai_pending_proposed_nodes = prop
        self._ai_pending_changed_keys = ch
        self._ai_preview_active = True
        self.load_node_to_ui(prop[idx])
        self._apply_ai_field_highlights(ch)
        self.preview_tabs.setCurrentWidget(self.json_preview)
        self._ai_refresh_commit_buttons()
        QTimer.singleShot(0, self._ai_refresh_commit_buttons)
        self.statusBar().showMessage(
            "Review JSON diff (red/green); changed fields use muted green text — Keep or Undo below.", 5000
        )

    def _ai_keep_proposal(self):
        if not self._ai_preview_active or self._ai_pending_proposed_nodes is None:
            QMessageBox.information(self, "AI", "No pending AI change to keep.")
            return
        idx = self.current_idx
        if idx < 0 or idx >= len(self._ai_pending_proposed_nodes):
            return
        self._clear_ai_field_highlights()
        self._ai_preview_active = False
        self.nodes_data = copy.deepcopy(self._ai_pending_proposed_nodes)
        self._ai_pending_snapshot_nodes = None
        self._ai_pending_proposed_nodes = None
        self._ai_pending_changed_keys = set()
        self._ai_last_result = None
        self.save_current_state()
        self._ai_refresh_commit_buttons()
        self.statusBar().showMessage("AI change kept.", 2500)
        self._schedule_autosave()

    def _ai_undo_proposal(self):
        if not self._ai_preview_active:
            return
        if self._ai_pending_snapshot_nodes is None:
            self._ai_reset_preview_state()
            self._ai_last_result = None
            self._ai_refresh_commit_buttons()
            self.update_live_preview()
            return
        idx = self.current_idx
        self._clear_ai_field_highlights()
        self._ai_preview_active = False
        self.nodes_data = copy.deepcopy(self._ai_pending_snapshot_nodes)
        self._ai_pending_snapshot_nodes = None
        self._ai_pending_proposed_nodes = None
        self._ai_pending_changed_keys = set()
        self._ai_last_result = None
        if 0 <= idx < len(self.nodes_data):
            self.load_node_to_ui(self.nodes_data[idx])
        else:
            self.current_idx = -1
            self._clear_editor()
        self._ai_refresh_commit_buttons()
        self.update_live_preview()
        self.statusBar().showMessage("AI suggestion discarded.", 2000)

    def final_generate(self):
        if self._ai_preview_active:
            QMessageBox.information(
                self,
                "Generate",
                "Keep or Undo the AI suggestion before generating code.",
            )
            return
        self.save_current_state()
        path = QFileDialog.getExistingDirectory(
            self,
            "Choose Save Path",
            "",
            QFileDialog.ShowDirsOnly | QFileDialog.DontResolveSymlinks,
        )
        if not path:
            return
        try:
            generator.save_files(self.nodes_data, path)
            QMessageBox.information(self, "Generation Complete", f"Node code saved to:\n{path}")
            self.statusBar().showMessage("Code generated", 3000)
        except Exception as e:
            QMessageBox.warning(self, "Generation Failed", f"Cannot generate code:\n{e}")


def run_app() -> None:
    app = QApplication(sys.argv)
    app.setOrganizationName('RyvenGenerator')
    app.setApplicationName('NodeStudio')
    window = GeneratorDesignerUI()
    window.show()
    sys.exit(app.exec())
