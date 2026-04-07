"""Main application window: node list, editor, code/JSON preview, AI assistant."""

from __future__ import annotations

import copy
import html
import json
import sys
import uuid
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
from PySide6.QtGui import QFont, QTextCharFormat, QTextCursor

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
from .widgets import NoWheelComboBox, PortCard, _AITurnWorker, ShellApprovalController
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
        self._ai_shell_approval_controller: ShellApprovalController | None = None
        self._ai_tab_widget = None
        self._ai_streaming_this_turn = False
        self._ai_turn_in_progress = False
        self._ai_pin_chat_to_bottom = True
        self._ai_preview_active = False
        self._ai_pending_snapshot_nodes: list | None = None
        self._ai_pending_proposed_nodes: list | None = None
        self._ai_pending_changed_keys: set[str] = set()
        self._ai_highlighted_widgets: set = set()
        self._ai_style_backup: dict[int, str] = {}
        self._ai_system_block_collapsed: dict[str, bool] = {}

        # When AI diff preview is enabled, store scroll anchors per tab.
        self._code_diff_anchors: dict[str, str] = {}

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
        self._ensure_node_uids(self.nodes_data)
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

    def _ensure_node_uids(self, nodes: list[dict]) -> bool:
        """Ensure every node has a stable, unique ID."""
        changed = False
        seen: set[str] = set()
        for node in nodes:
            uid = str(node.get("node_uid", "")).strip()
            if not uid or uid in seen:
                node["node_uid"] = uuid.uuid4().hex
                uid = node["node_uid"]
                changed = True
            seen.add(uid)
        return changed

    def _ai_chat_interaction_locked(self) -> bool:
        if getattr(self, "_ai_turn_in_progress", False):
            return True
        return self._ai_worker is not None and self._ai_worker.isRunning()

    def _ai_scroll_chat_to_bottom(self):
        if not getattr(self, "ai_chat_scroll", None):
            return
        sb = self.ai_chat_scroll.verticalScrollBar()
        sb.setValue(sb.maximum())

    def _ai_force_chat_to_bottom(self):
        """Keep chat pinned to bottom across layout reflow."""
        self._ai_scroll_chat_to_bottom()
        QTimer.singleShot(0, self._ai_scroll_chat_to_bottom)
        QTimer.singleShot(30, self._ai_scroll_chat_to_bottom)

    def _ai_on_chat_range_changed(self, _min: int, _max: int):
        """When chat content grows/reflows, keep viewport at bottom."""
        if self._ai_pin_chat_to_bottom:
            self._ai_scroll_chat_to_bottom()

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
            role, text, meta = project_ws.normalize_ai_turn(h[i])
            if role == "user":
                lay.addWidget(self._ai_make_user_message_row(text, i, meta))
                i += 1
                # One user turn may include multiple system progress lines and an assistant reply.
                system_lines: list[str] = []
                system_start = i
                while i < n:
                    r2, t2, _m = project_ws.normalize_ai_turn(h[i])
                    if r2 == "user":
                        break
                    if r2 == "system":
                        system_lines.append(t2)
                    elif r2 == "assistant":
                        if system_lines:
                            lay.addWidget(
                                self._ai_make_system_block_bubble(
                                    system_lines,
                                    block_key=f"{system_start}:{i}",
                                )
                            )
                            system_lines = []
                        lay.addWidget(self._ai_make_assistant_bubble(t2))
                    i += 1
                if system_lines:
                    lay.addWidget(
                        self._ai_make_system_block_bubble(
                            system_lines,
                            block_key=f"{system_start}:{i}",
                        )
                    )
            elif role == "assistant":
                lay.addWidget(self._ai_make_assistant_bubble(text))
                i += 1
            elif role == "system":
                start = i
                lines = [text]
                i += 1
                while i < n:
                    r2, t2, _m = project_ws.normalize_ai_turn(h[i])
                    if r2 != "system":
                        break
                    lines.append(t2)
                    i += 1
                lay.addWidget(self._ai_make_system_block_bubble(lines, block_key=f"{start}:{i}"))
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
        self._ai_force_chat_to_bottom()

    def _ai_make_user_message_row(self, text: str, user_index: int, ctx: dict | None = None) -> QWidget:
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
        # Always clickable; handler shows a message if AI is still running (avoids stuck-disabled after thread teardown races).
        btn.setEnabled(True)
        # QToolButton.clicked emits (bool); do not use partial(..., idx) or the bool becomes user_index.
        btn.clicked.connect(lambda _checked=False, idx=user_index: self._ai_withdraw_turn(idx))

        bubble = QFrame()
        bubble.setObjectName("AiUserBubble")
        blay = QVBoxLayout(bubble)
        blay.setContentsMargins(12, 10, 12, 10)
        blay.setSpacing(4)
        ctx = ctx or {}
        title = (ctx.get("context_title") or "").strip()
        cname = (ctx.get("context_class_name") or "").strip()
        cuid = str(ctx.get("context_node_uid", "")).strip()
        if title or cname:
            display = html.escape(title or cname)
            sub_raw = cname if title and cname and title != cname else ""
            sub = html.escape(sub_raw) if sub_raw else ""
            ctx_lbl = QLabel()
            ctx_lbl.setObjectName("AiUserContextLine")
            if sub:
                ctx_lbl.setText(
                    f'Context node: <a href="#">{display}</a> <span style="color:#7d8c9c;">({sub})</span>'
                )
            else:
                ctx_lbl.setText(f'Context node: <a href="#">{display}</a>')
            ctx_lbl.setTextFormat(Qt.RichText)
            ctx_lbl.setTextInteractionFlags(Qt.TextBrowserInteraction)
            ctx_lbl.setOpenExternalLinks(False)
            nidx = int(ctx.get("context_node_idx", -1))
            cname_f = cname or None
            uid_f = cuid or None
            ctx_lbl.linkActivated.connect(
                lambda _u, i=nidx, cn=cname_f, uid=uid_f: self._ai_goto_history_context_node(i, cn, uid)
            )
            blay.addWidget(ctx_lbl)
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

    def _ai_goto_history_context_node(self, node_idx: int, class_name: str | None, node_uid: str | None):
        """Switch node list / editor to the node referenced by a stored chat context."""
        target = -1
        if node_uid:
            for i, node in enumerate(self.nodes_data):
                if str(node.get("node_uid", "")).strip() == node_uid:
                    target = i
                    break
        if target < 0 and class_name:
            for i, node in enumerate(self.nodes_data):
                if str(node.get("class_name", "")) == class_name:
                    target = i
                    break
        if target < 0 and 0 <= node_idx < len(self.nodes_data):
            target = node_idx
        if target < 0:
            QMessageBox.information(
                self,
                "Node not found",
                "That context node is no longer in this project (renamed or deleted).",
            )
            return
        self.node_list_ui.setCurrentRow(target)

    def _restore_nodes_from_history_snapshot(self, snapshot_nodes: list, preferred_idx: int = -1) -> bool:
        """Restore full node list from a user-turn snapshot."""
        if not isinstance(snapshot_nodes, list):
            return False
        self._ai_reset_preview_state()
        self.nodes_data = copy.deepcopy(snapshot_nodes)
        self._ensure_node_uids(self.nodes_data)

        self.node_list_ui.blockSignals(True)
        self.node_list_ui.clear()
        for node in self.nodes_data:
            self.node_list_ui.addItem(self._node_list_text(node))
        self.node_list_ui.blockSignals(False)

        if self.nodes_data:
            if not (0 <= preferred_idx < len(self.nodes_data)):
                preferred_idx = self.current_idx if 0 <= self.current_idx < len(self.nodes_data) else 0
            self.current_idx = -1
            self.node_list_ui.setCurrentRow(preferred_idx)
        else:
            self.current_idx = -1
            self._clear_editor()

        self._refresh_counts()
        self.update_live_preview()
        return True

    def _restore_node_from_history_snapshot(
        self,
        snapshot_node: dict,
        context_node_uid: str | None,
        preferred_idx: int = -1,
    ) -> tuple[bool, int]:
        """Restore only ONE node from a user-turn snapshot.

        This must not rebuild node list order; it only replaces the target node dict
        in `self.nodes_data`, updates the node list text for that index, and reloads
        the editor/code previews if the restored node is currently selected.
        """
        if not isinstance(snapshot_node, dict):
            return False, -1

        # Ensure the snapshot node has a uid to match current nodes robustly.
        snap_uid = str(snapshot_node.get("node_uid", "")).strip()
        if context_node_uid and not snap_uid:
            snapshot_node = copy.deepcopy(snapshot_node)
            snapshot_node["node_uid"] = context_node_uid
            snap_uid = context_node_uid

        target_idx = -1
        if snap_uid:
            for i, node in enumerate(self.nodes_data):
                if str(node.get("node_uid", "")).strip() == snap_uid:
                    target_idx = i
                    break
        if target_idx < 0 and 0 <= preferred_idx < len(self.nodes_data):
            target_idx = preferred_idx

        if target_idx < 0 or target_idx >= len(self.nodes_data):
            return False, -1

        # Replace the node dict in-place; do not touch list order.
        self.nodes_data[target_idx] = copy.deepcopy(snapshot_node)
        self._ensure_node_uids(self.nodes_data)

        # Update the list item display text for this index (keeps order).
        try:
            item = self.node_list_ui.item(target_idx)
            if item:
                item.setText(self._node_list_text(self.nodes_data[target_idx]))
        except Exception:
            pass

        restored_current = target_idx == self.current_idx
        if restored_current:
            self.load_node_to_ui(self.nodes_data[target_idx])
        else:
            # Code previews depend on whole project; refresh them.
            self.update_live_preview()

        # Withdraw is an undo-like operation; clear stale AI diff so previews remain consistent.
        if self._ai_preview_active:
            self._ai_reset_preview_state()

        return True, target_idx

    def _ai_make_assistant_bubble(self, text: str) -> QWidget:
        wrap = QFrame()
        wrap.setObjectName("AiAssistantBubble")
        blay = QVBoxLayout(wrap)
        blay.setContentsMargins(12, 10, 12, 10)
        blay.setSpacing(4)
        meta = QLabel("Assistant")
        meta.setObjectName("AiChatMeta")
        body = QTextEdit()
        body.setReadOnly(True)
        body.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        body.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        body.setFixedHeight(78)
        body.setObjectName("AiBubbleBody")
        body.setText(text or "")
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
        body = QTextEdit()
        body.setReadOnly(True)
        body.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        body.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        body.setFixedHeight(78)
        body.setObjectName("AiBubbleBody")
        body.setStyleSheet("color: #c4a9a4;")
        body.setText(text or "")
        blay.addWidget(meta)
        blay.addWidget(body)
        return wrap

    def _ai_make_system_item_editor(
        self, text: str, max_visible_lines: int = 5, parent: QWidget | None = None
    ) -> QTextEdit:
        body = QTextEdit(parent)
        body.setReadOnly(True)
        body.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        body.setObjectName("AiBubbleBody")
        body.setStyleSheet(
            "color: #c4a9a4; background: transparent; border: 1px solid #5a4e50; border-radius: 6px;"
        )
        body.viewport().setAutoFillBackground(False)
        body.setText(text or "")
        fm = body.fontMetrics()
        line_height = max(1, fm.lineSpacing())
        line_count = max(1, len((text or "").splitlines()))
        visible_lines = min(max_visible_lines, line_count)
        height = int(visible_lines * line_height + 30)
        body.setFixedHeight(height)
        if line_count > max_visible_lines:
            body.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        else:
            body.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        return body

    def _ai_toggle_system_block(self, block_key: str, content: QWidget, btn: QToolButton):
        collapsed = bool(self._ai_system_block_collapsed.get(block_key, False))
        collapsed = not collapsed
        self._ai_system_block_collapsed[block_key] = collapsed
        content.setVisible(not collapsed)
        btn.setText("▸" if collapsed else "▾")
        btn.setToolTip("Expand system details" if collapsed else "Collapse system details")
        self._ai_force_chat_to_bottom()

    def _ai_make_system_block_bubble(self, lines: list[str], block_key: str) -> QWidget:
        wrap = QFrame()
        wrap.setObjectName("AiSystemBubble")
        blay = QVBoxLayout(wrap)
        blay.setContentsMargins(12, 10, 12, 10)
        blay.setSpacing(6)

        header = QWidget(wrap)
        header.setStyleSheet("background: transparent;")
        hlay = QHBoxLayout(header)
        hlay.setContentsMargins(0, 0, 0, 0)
        hlay.setSpacing(8)
        toggle = QToolButton(header)
        toggle.setAutoRaise(True)
        toggle.setStyleSheet("background: transparent; color: #c4a9a4; border: none;")
        meta = QLabel(f"System ({len(lines)} step{'s' if len(lines) != 1 else ''})")
        meta.setObjectName("AiChatMeta")
        meta.setStyleSheet("background: transparent;")
        hlay.addWidget(toggle, 0, Qt.AlignTop)
        hlay.addWidget(meta, 1, Qt.AlignVCenter)

        content = QWidget(wrap)
        content.setStyleSheet("background: transparent;")
        cl = QVBoxLayout(content)
        cl.setContentsMargins(0, 0, 0, 0)
        cl.setSpacing(6)
        for t in lines:
            cl.addWidget(self._ai_make_system_item_editor(t, parent=content))

        collapsed = bool(self._ai_system_block_collapsed.get(block_key, False))
        content.setVisible(not collapsed)
        toggle.setText("▸" if collapsed else "▾")
        toggle.setToolTip("Expand system details" if collapsed else "Collapse system details")
        toggle.clicked.connect(
            lambda _checked=False, k=block_key, c=content, b=toggle: self._ai_toggle_system_block(k, c, b)
        )

        blay.addWidget(header)
        blay.addWidget(content)
        return wrap

    def _ai_withdraw_turn(self, user_idx: int):
        if self._ai_chat_interaction_locked():
            QMessageBox.information(
                self,
                "Withdraw",
                "Wait until the current AI run finishes, then you can withdraw a turn.",
            )
            return
        h = self._ai_history
        if user_idx < 0 or user_idx >= len(h):
            return
        role, _text, _meta = project_ws.normalize_ai_turn(h[user_idx])
        if role != "user":
            return
        _yes = QMessageBox.StandardButton.Yes
        _no = QMessageBox.StandardButton.No
        if (
            QMessageBox.question(
                self,
                "Withdraw message",
                "Remove this question and the entire AI reply for this turn?",
                _yes | _no,
                _no,
            )
            != _yes
        ):
            return
        n = len(h)
        last_u = None
        for j in range(n - 1, -1, -1):
            if project_ws.normalize_ai_turn(h[j])[0] == "user":
                last_u = j
                break
        is_latest = last_u is not None and user_idx == last_u
        restored_from_snapshot = False
        restored_idx = -1
        _, _, meta = project_ws.normalize_ai_turn(h[user_idx])
        context_uid = str(meta.get("context_node_uid", "")).strip() or None
        snapshot_node = meta.get("snapshot_node")
        snapshot_nodes = meta.get("snapshot_nodes")  # backward compatibility
        preferred_idx = -1
        try:
            preferred_idx = int(meta.get("context_node_idx", -1))
        except Exception:
            preferred_idx = -1

        if isinstance(snapshot_node, dict):
            restored_from_snapshot, restored_idx = self._restore_node_from_history_snapshot(
                snapshot_node, context_uid, preferred_idx
            )
        elif isinstance(snapshot_nodes, list):
            # Try to locate the same node by uid first.
            if context_uid:
                candidate = None
                for nd in snapshot_nodes:
                    if str((nd or {}).get("node_uid", "")).strip() == context_uid:
                        candidate = nd
                        break
                if isinstance(candidate, dict):
                    restored_from_snapshot, restored_idx = self._restore_node_from_history_snapshot(
                        candidate, context_uid, preferred_idx
                    )
            # Fallback to index from the saved meta.
            if not restored_from_snapshot and 0 <= preferred_idx < len(snapshot_nodes):
                candidate = snapshot_nodes[preferred_idx]
                if isinstance(candidate, dict):
                    restored_from_snapshot, restored_idx = self._restore_node_from_history_snapshot(
                        candidate, context_uid, preferred_idx
                    )
        # Remove this user message and every following assistant/system message until the next user (full turn).
        rm_end = user_idx + 1
        while rm_end < n and project_ws.normalize_ai_turn(h[rm_end])[0] != "user":
            rm_end += 1
        if is_latest:
            if restored_from_snapshot:
                # Clear AI preview only if it was for the same currently selected node.
                if self._ai_preview_active and restored_idx == self.current_idx:
                    self._ai_reset_preview_state()
                self._ai_last_result = None
            else:
                # If we couldn't restore from snapshot, fallback to legacy undo.
                if self._ai_preview_active:
                    self._ai_undo_proposal()
                else:
                    self._ai_last_result = None
        self._ai_history[:] = h[:user_idx] + h[rm_end:]
        self._rebuild_ai_chat_ui()
        self._schedule_autosave()
        if restored_from_snapshot:
            self.statusBar().showMessage(
                "Conversation turn withdrawn and context node restored from snapshot.", 3000
            )
        else:
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

        # Keep code preview tabs pinned to the earliest change when AI diff is rendered.
        self.preview_tabs.currentChanged.connect(self._on_preview_tab_changed)

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
        self.ai_chat_scroll.verticalScrollBar().rangeChanged.connect(self._ai_on_chat_range_changed)

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

    def _on_preview_tab_changed(self, _index: int):
        w = self.preview_tabs.currentWidget()
        if w is self.nodes_preview:
            anchor = self._code_diff_anchors.get("nodes", "")
            self._scroll_preview_textedit_to_anchor(self.nodes_preview, anchor)
        elif w is self.gui_preview:
            anchor = self._code_diff_anchors.get("gui", "")
            self._scroll_preview_textedit_to_anchor(self.gui_preview, anchor)
        elif w is self.json_preview:
            anchor = self._code_diff_anchors.get("json", "")
            self._scroll_preview_textedit_to_anchor(self.json_preview, anchor)

    def _scroll_preview_textedit_to_anchor(self, te: QTextEdit, anchor: str):
        """Scroll QTextEdit so the first-change anchor is near the top (best-effort).

        If the document is shorter than the viewport, the scroll range may be 0 and this becomes a no-op.
        """
        if not anchor:
            return
        try:
            if not te.find(anchor):
                return

            cursor = te.textCursor()
            rect = te.cursorRect(cursor)
            sb = te.verticalScrollBar()
            if sb.maximum() <= 0:
                return

            # rect.top() is in viewport coordinates: shift scrollbar so the cursor is near the top.
            top_padding = 6
            target = sb.value() + rect.top() - top_padding
            if target < sb.minimum():
                target = sb.minimum()
            if target > sb.maximum():
                target = sb.maximum()
            sb.setValue(int(target))
        except Exception:
            # Fallback: do nothing (avoid breaking preview).
            return

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
            "node_uid": str(node.get("node_uid", "")).strip() or uuid.uuid4().hex,
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
            if not str(self.nodes_data[row].get("node_uid", "")).strip():
                self.nodes_data[row]["node_uid"] = uuid.uuid4().hex
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
            "node_uid": uuid.uuid4().hex,
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
            from ryven_node_generator.ai_assistant.preview_diff import json_list_diff_html_and_first_change

            try:
                html_doc, first = json_list_diff_html_and_first_change(
                    self._ai_pending_snapshot_nodes,
                    self._ai_pending_proposed_nodes,
                )
                self.json_preview.setHtml(html_doc)
                self._code_diff_anchors["json"] = first
            except Exception as e:
                self._set_preview_plain_text(self.json_preview, f"(JSON diff error: {e})")
            return
        if not self.nodes_data:
            self.json_preview.clear()
            return
        try:
            self._set_preview_plain_text(
                self.json_preview,
                json.dumps(self.nodes_data, indent=4, ensure_ascii=False),
            )
            self._code_diff_anchors.pop("json", None)
        except Exception as e:
            self._set_preview_plain_text(self.json_preview, f"(JSON preview error: {e})")

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

            if (
                self._ai_preview_active
                and self._ai_pending_snapshot_nodes is not None
                and self._ai_pending_proposed_nodes is not None
            ):
                from ryven_node_generator.ai_assistant.preview_diff import (
                    text_diff_html_and_first_change,
                )

                snap_n, snap_g = generator.generate_code_from_data(self._ai_pending_snapshot_nodes)
                prop_n, prop_g = generator.generate_code_from_data(self._ai_pending_proposed_nodes)

                nodes_html, nodes_first = text_diff_html_and_first_change(snap_n, prop_n)
                gui_html, gui_first = text_diff_html_and_first_change(snap_g, prop_g)

                self.nodes_preview.setHtml(nodes_html)
                self.gui_preview.setHtml(gui_html)
                self._code_diff_anchors["nodes"] = nodes_first
                self._code_diff_anchors["gui"] = gui_first
            else:
                self._set_preview_plain_text(self.nodes_preview, n_code)
                self._set_preview_plain_text(self.gui_preview, g_code)
                self._code_diff_anchors.pop("nodes", None)
                self._code_diff_anchors.pop("gui", None)
        except Exception as e:
            self.statusBar().showMessage(f"Code preview error: {e}", 4000)
            return

        if 0 <= self.current_idx < len(self.nodes_data):
            self.node_preview.update_preview(self.nodes_data[self.current_idx])

    def _force_plain_previews(self):
        """Force-reset all code/json preview QTextEdits to plain text.

        This prevents any leftover diff HTML spans from persisting after Keep/Undo.
        """
        # Clear anchors and render plain text regardless of current diff flags.
        self._code_diff_anchors.pop("nodes", None)
        self._code_diff_anchors.pop("gui", None)
        self._code_diff_anchors.pop("json", None)

        self._update_ai_context_label()

        if not self.nodes_data:
            self.nodes_preview.clear()
            self.gui_preview.clear()
            self.json_preview.clear()
            return

        try:
            # JSON plain
            self._set_preview_plain_text(
                self.json_preview,
                json.dumps(self.nodes_data, indent=4, ensure_ascii=False),
            )
            # Code plain
            n_code, g_code = generator.generate_code_from_data(self.nodes_data)
            self._set_preview_plain_text(self.nodes_preview, n_code)
            self._set_preview_plain_text(self.gui_preview, g_code)
        except Exception as e:
            self.statusBar().showMessage(f"Preview render error: {e}", 4000)
            return

        if 0 <= self.current_idx < len(self.nodes_data):
            self.node_preview.update_preview(self.nodes_data[self.current_idx])

    def _set_preview_plain_text(self, te: QTextEdit, text: str):
        """Reset text format state before writing plain preview content.

        QTextEdit may keep cursor char format from previous HTML spans (diff colors).
        If we directly call setPlainText after setHtml, the whole document can inherit
        stale foreground color (e.g. all red/green). This hard-resets the format first.
        """
        te.clear()
        te.setCurrentCharFormat(QTextCharFormat())
        te.setPlainText(text)
        c = te.textCursor()
        c.movePosition(QTextCursor.Start)
        te.setTextCursor(c)

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
        ctx = {
            "context_node_idx": self.current_idx,
            "context_node_uid": str(self.nodes_data[self.current_idx].get("node_uid", "")),
            "context_class_name": str(self.nodes_data[self.current_idx].get("class_name", "")),
            "context_title": str(self.nodes_data[self.current_idx].get("title", "")),
            # Store only the current node snapshot (do NOT snapshot the whole project),
            # so withdrawing this turn affects only that context node's JSON.
            "snapshot_node": copy.deepcopy(self.nodes_data[self.current_idx]),
            "snapshot_node_uid": str(self.nodes_data[self.current_idx].get("node_uid", "")),
        }
        self._ai_history.append(("user", text, ctx))
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
        hist_for_api = project_ws.ai_history_for_llm(list(self._ai_history[:-1]))
        self._ai_shell_approval_controller = ShellApprovalController()
        self._ai_worker = _AITurnWorker(
            text,
            hist_for_api,
            node,
            names,
            self._project_root,
            self,
            shell_approval_controller=self._ai_shell_approval_controller,
        )
        self._ai_worker.stream_delta.connect(self._ai_on_stream_delta)
        self._ai_worker.progress_event.connect(self._ai_on_worker_progress)
        self._ai_worker.finished_ok.connect(self._ai_on_worker_ok)
        self._ai_worker.stopped.connect(self._ai_on_worker_stopped)
        self._ai_worker.failed.connect(self._ai_on_worker_failed)
        self._ai_worker.finished.connect(self._ai_worker_cleanup)
        self._ai_worker.start()

    def _ai_worker_cleanup(self):
        self._ai_worker = None
        # Rebuild so withdraw buttons match post-thread state (avoids disabled buttons if rebuild ran mid-teardown).
        self._rebuild_ai_chat_ui()
        self._ai_refresh_commit_buttons()

    def _ai_on_worker_progress(self, event: dict):
        et = str((event or {}).get("type", ""))
        if et == "round_start":
            rnd = int(event.get("round", 1))
            mx = int(event.get("max_rounds", rnd))
            self._ai_history.append(("system", f"Round {rnd}/{mx}: generating and validating core_logic", {}))
        elif et == "round_result":
            rnd = int(event.get("round", 1))
            status = str(event.get("status", "failed"))
            reason = str(event.get("reason", "")).strip()
            icon = "✅" if status == "passed" else "❌"
            msg = f"Round {rnd} {icon} {status}"
            if reason:
                msg += f"\n- {reason}"
            self._ai_history.append(("system", msg, {}))
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
            self._ai_history.append(("system", msg, {}))
        elif et == "test_cases":
            rnd = int(event.get("round", 1))
            summary = [str(x) for x in (event.get("summary") or []) if str(x).strip()]
            msg = f"Round {rnd} cases: {', '.join(summary[:3])}" if summary else f"Round {rnd} cases: default smoke"
            self._ai_history.append(("system", msg, {}))
        elif et == "react_step":
            step = int(event.get("step", 0))
            tools = [str(x) for x in (event.get("tools") or []) if str(x).strip()]
            msg = f"ReAct step {step}: " + (", ".join(tools) if tools else "(no tools)")
            assistant_text = str(event.get("assistant_text") or "").strip()
            if assistant_text:
                # Keep it short: 2~3 lines max in chat bubble.
                lines = [l.strip() for l in assistant_text.splitlines() if l.strip()]
                if lines:
                    msg += "\n- AI:\n  " + "\n  ".join(lines[:3])
                else:
                    msg += "\n- AI: " + assistant_text
            self._ai_history.append(("system", msg, {}))
        elif et == "react_tool_call":
            step = int(event.get("step", 0))
            tool = str(event.get("tool") or "")
            args_preview = str(event.get("args_preview") or "").strip()
            msg = f"ReAct tool call @ {step}: {tool}"
            if args_preview:
                msg += "\n- args: " + args_preview
            self._ai_history.append(("system", msg, {}))
        elif et == "react_shell_request":
            step = int(event.get("step", 0))
            request_id = str(event.get("request_id") or "")
            cmd = str(event.get("command") or "").strip()
            msg = f"ReAct shell request @ {step}\n- cmd: {cmd}"
            self._ai_history.append(("system", msg, {}))

            approved = False
            if self._ai_shell_approval_controller is not None and request_id:
                mb = QMessageBox(self)
                mb.setWindowTitle("AI Shell Approval")
                mb.setIcon(QMessageBox.Question)
                mb.setText("AI requests to run a shell command.\n\n" + cmd + "\n\nRun it?")
                mb.setStandardButtons(QMessageBox.Yes | QMessageBox.No)
                mb.setButtonText(QMessageBox.Yes, "Run")
                mb.setButtonText(QMessageBox.No, "Cancel")
                r = mb.exec()
                approved = r == QMessageBox.Yes

            if self._ai_shell_approval_controller is not None and request_id:
                self._ai_shell_approval_controller.decide(request_id, approved)
        elif et == "react_tool_result":
            step = int(event.get("step", 0))
            tool = str(event.get("tool") or "")
            result_preview = str(event.get("result_preview") or "").strip()
            msg = f"ReAct tool result @ {step}: {tool}"
            if result_preview:
                lines = [l.strip() for l in result_preview.splitlines() if l.strip()]
                if lines:
                    msg += "\n- " + "\n  ".join(lines[:3])
                else:
                    msg += "\n- " + result_preview
            self._ai_history.append(("system", msg, {}))
        elif et == "react_submit_rejected":
            step = int(event.get("step", 0))
            err = str(event.get("error") or "").strip()
            args_preview = str(event.get("args_preview") or "").strip()
            msg = f"submit_node_turn rejected @ {step}"
            if err:
                msg += "\n- error: " + err
            if args_preview:
                msg += "\n- args: " + args_preview
            self._ai_history.append(("system", msg, {}))
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
        self._ai_history.append(("assistant", msg, {}))
        react_trace = result.get("react_trace") or []
        trace = result.get("repair_trace") or []
        if react_trace:
            self._ai_history.append(
                (
                    "system",
                    f"ReAct finished: {len(react_trace)} model step(s); last step index {int(result.get('repair_round', 0))}.",
                    {},
                )
            )
        elif trace:
            final_round = int(result.get("repair_round", len(trace)))
            passed_rounds = sum(1 for t in trace if str(t.get("status")) == "passed")
            self._ai_history.append(
                (
                    "system",
                    f"Self-repair finished: {len(trace)} rounds, using round {final_round}; passed rounds {passed_rounds}/{len(trace)}.",
                    {},
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
        self._ai_history.append(("system", f"Request failed: {err}", {}))
        self._ai_set_busy(False)
        self._rebuild_ai_chat_ui()
        self._schedule_autosave()
        QMessageBox.warning(self, "AI error", err)

    def _ai_on_worker_stopped(self):
        self._ai_turn_in_progress = False
        self._ai_history.append(("system", "Generation stopped by user.", {}))
        self._ai_set_busy(False)
        self._rebuild_ai_chat_ui()
        self._schedule_autosave()

    def _ai_build_patch_from_result(self, result: dict) -> dict:
        # Keys read from finalize_parsed_turn / ReAct output (see docs/agent-refactor-roadmap-for-ai.md §0):
        # core_logic, config_patch, message, validation_error, self_test_cases,
        # repair_trace, repair_round, _streamed_reply_plain, _stream_had_visible_reply, self_test_summary.
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
        # Force plain previews after Keep so diff HTML spans cannot linger.
        self._force_plain_previews()
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
        # Force plain previews after Undo so diff HTML spans cannot linger.
        self._force_plain_previews()
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
