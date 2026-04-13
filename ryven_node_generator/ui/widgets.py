"""Reusable Qt widgets for the node editor (ports, AI worker)."""

import copy
import threading
from PySide6.QtWidgets import (
    QComboBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)
from PySide6.QtCore import QThread, Signal

from .constants import EDITOR_ROW_H, INPUT_WIDGET_EXAMPLES


class ShellApprovalController:
    """Cross-thread controller for manual shell approval.

    The ReAct worker thread calls `begin()` + `wait_approved()` and blocks.
    The UI thread receives `react_shell_request` and calls `decide()` to unblock it.
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._event = threading.Event()
        self._request_id: str | None = None
        self._approved: bool = False

    def begin(self, request_id: str) -> None:
        with self._lock:
            self._request_id = request_id
            self._approved = False
            self._event.clear()

    def decide(self, request_id: str, approved: bool) -> None:
        with self._lock:
            if self._request_id != request_id:
                return
            self._approved = bool(approved)
            self._event.set()

    def cancel_pending(self) -> None:
        """Unblock any pending wait (treated as not approved)."""
        with self._lock:
            self._approved = False
            self._event.set()

    def wait_approved(self, request_id: str, *, should_stop=None) -> bool:
        """Block until UI decides (or should_stop becomes true)."""
        while True:
            if should_stop is not None and should_stop():
                return False
            if self._event.wait(timeout=0.25):
                with self._lock:
                    return bool(self._request_id == request_id and self._approved)


class NoWheelComboBox(QComboBox):
    """Block wheel events so scrolling the panel does not change the selection."""

    def wheelEvent(self, event):
        event.ignore()


class _AITurnWorker(QThread):
    stream_delta = Signal(str)
    progress_event = Signal(dict)
    finished_ok = Signal(dict)
    failed = Signal(str)
    stopped = Signal()

    def __init__(
        self,
        user_text,
        history,
        current_node,
        class_names,
        project_root=None,
        parent=None,
        shell_approval_controller: ShellApprovalController | None = None,
    ):
        super().__init__(parent)
        self._user_text = user_text
        self._history = list(history)
        self._current_node = copy.deepcopy(current_node)
        self._class_names = list(class_names)
        self._project_root = project_root
        self._stop_requested = False
        self._shell_approval_controller = shell_approval_controller

    def stop(self):
        self._stop_requested = True
        if self._shell_approval_controller is not None:
            # Unblock if we are waiting for user shell approval.
            self._shell_approval_controller.cancel_pending()

    def run(self):
        try:
            # Defer import so `pip install .` (without [ai]) still launches the UI;
            # LangChain / dotenv are only required when the user runs an assistant turn.
            from ryven_node_generator.ai_assistant.orchestration import run_agent_session

            r = run_agent_session(
                user_text=self._user_text,
                current_node=self._current_node,
                existing_class_names=self._class_names,
                history=self._history,
                project_root=self._project_root,
                on_progress=self.progress_event.emit,
                on_reply_delta=self.stream_delta.emit,
                should_stop=lambda: self._stop_requested,
                shell_approval_controller=self._shell_approval_controller,
            )
            if self._stop_requested:
                self.stopped.emit()
                return
            self.finished_ok.emit(r)
        except Exception as e:
            if self._stop_requested:
                self.stopped.emit()
                return
            self.failed.emit(str(e))


class PortCard(QFrame):
    changed = Signal()
    move_requested = Signal(int)
    remove_requested = Signal()

    def __init__(self, is_input=True, data=None):
        super().__init__()
        self.is_input = is_input
        self.setObjectName("PortCard")

        root = QVBoxLayout(self)
        root.setContentsMargins(8, 8, 8, 8)
        root.setSpacing(6)

        row1 = QHBoxLayout()
        row1.setContentsMargins(0, 0, 0, 0)
        row1.setSpacing(6)

        default_label = "input" if is_input else "output"
        self.label_edit = QLineEdit(data.get("label", default_label) if data else default_label)
        self.type_combo = NoWheelComboBox()
        self.type_combo.addItems(["data", "exec"])
        if data:
            self.type_combo.setCurrentText(data.get("type", "data"))

        self.idx_badge = QLabel("0/0")
        self.idx_badge.setObjectName("IndexBadge")

        self.up_btn = QPushButton("↑")
        self.up_btn.setObjectName("MoveBtn")
        self.up_btn.setFixedSize(26, EDITOR_ROW_H)
        self.up_btn.setToolTip("Move up")

        self.down_btn = QPushButton("↓")
        self.down_btn.setObjectName("MoveBtn")
        self.down_btn.setFixedSize(26, EDITOR_ROW_H)
        self.down_btn.setToolTip("Move down")

        self.del_btn = QPushButton("Delete")
        self.del_btn.setObjectName("DeleteBtn")
        self.del_btn.setFixedHeight(EDITOR_ROW_H)

        label_lbl = QLabel("Label")
        label_lbl.setFixedWidth(36)
        type_lbl = QLabel("Type")
        type_lbl.setFixedWidth(32)

        self.label_edit.setMinimumWidth(72)
        self.label_edit.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.label_edit.setFixedHeight(EDITOR_ROW_H)
        self.type_combo.setFixedWidth(72)
        self.type_combo.setFixedHeight(EDITOR_ROW_H)

        row1.addWidget(self.idx_badge)
        row1.addWidget(label_lbl)
        row1.addWidget(self.label_edit, 1)
        row1.addWidget(type_lbl)
        row1.addWidget(self.type_combo)
        row1.addWidget(self.up_btn)
        row1.addWidget(self.down_btn)
        row1.addWidget(self.del_btn)
        root.addLayout(row1)

        if is_input:
            self.w_panel = QWidget()
            self.w_panel.setObjectName("PortWidgetPanel")
            wlay = QVBoxLayout(self.w_panel)
            wlay.setContentsMargins(0, 0, 0, 0)
            wlay.setSpacing(6)

            row2 = QHBoxLayout()
            row2.setContentsMargins(0, 0, 0, 0)
            row2.setSpacing(6)
            w_lbl = QLabel("Widget")
            w_lbl.setFixedWidth(42)
            p_lbl = QLabel("Position")
            p_lbl.setFixedWidth(44)
            self.w_type = NoWheelComboBox()
            self.w_type.addItems(list(INPUT_WIDGET_EXAMPLES.keys()))
            self.w_pos = NoWheelComboBox()
            self.w_pos.addItems(["besides", "below"])
            self.w_type.setMinimumWidth(88)
            self.w_type.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
            self.w_type.setFixedHeight(EDITOR_ROW_H)
            self.w_pos.setFixedWidth(72)
            self.w_pos.setFixedHeight(EDITOR_ROW_H)
            row2.addWidget(w_lbl)
            row2.addWidget(self.w_type, 1)
            row2.addWidget(p_lbl)
            row2.addWidget(self.w_pos)
            wlay.addLayout(row2)

            row3 = QHBoxLayout()
            row3.setContentsMargins(0, 0, 0, 0)
            row3.setSpacing(6)
            a_lbl = QLabel("Args")
            a_lbl.setFixedWidth(40)
            self.w_args = QLineEdit()
            self.w_args.setPlaceholderText("init=1, range=(0, 100)")
            self.w_args.setClearButtonEnabled(True)
            self.w_args.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
            self.w_args.setFixedHeight(EDITOR_ROW_H)
            row3.addWidget(a_lbl)
            row3.addWidget(self.w_args, 1)
            wlay.addLayout(row3)

            root.addWidget(self.w_panel)

            self.w_type.currentTextChanged.connect(lambda t: self.w_args.setText(INPUT_WIDGET_EXAMPLES.get(t, "")))
            self.w_type.currentTextChanged.connect(self._on_widget_type_changed)

            widget_data = (data or {}).get("widget")
            if isinstance(widget_data, dict):
                self.w_type.setCurrentText(widget_data.get("type", "None"))
                self.w_pos.setCurrentText(widget_data.get("pos", "besides"))
                self.w_args.setText(widget_data.get("args", ""))

            self.type_combo.currentTextChanged.connect(self._on_type_changed)
            self._on_type_changed(self.type_combo.currentText())
            self.w_type.currentTextChanged.connect(lambda: self.changed.emit())
            self.w_pos.currentTextChanged.connect(lambda: self.changed.emit())
            self.w_args.editingFinished.connect(lambda: self.changed.emit())
            self._on_widget_type_changed(self.w_type.currentText())

        self.label_edit.editingFinished.connect(lambda: self.changed.emit())
        self.type_combo.currentTextChanged.connect(lambda: self.changed.emit())
        self.up_btn.clicked.connect(lambda: self.move_requested.emit(-1))
        self.down_btn.clicked.connect(lambda: self.move_requested.emit(1))
        self.del_btn.clicked.connect(self.remove_requested.emit)

    def _on_type_changed(self, t):
        if self.is_input:
            self.w_panel.setVisible(t == "data")
            if t == "exec":
                self.w_type.setCurrentText("None")
                self.w_args.clear()

    def _on_widget_type_changed(self, widget_type):
        if not self.is_input:
            return
        is_none = widget_type == "None"
        if is_none:
            self.w_args.clear()
        self.w_args.setEnabled(not is_none)
        self.w_pos.setEnabled(not is_none)

    def set_order_state(self, index, total):
        self.idx_badge.setText(f"{index + 1}/{total}" if total > 0 else "0/0")
        self.idx_badge.setToolTip(f"Index: {index}, position {index + 1}/{total}")
        self.up_btn.setEnabled(index > 0)
        self.down_btn.setEnabled(index < total - 1)

    def get_data(self):
        d = {"label": self.label_edit.text(), "type": self.type_combo.currentText()}
        if self.is_input and d["type"] == "data" and self.w_type.currentText() != "None":
            d["widget"] = {
                "type": self.w_type.currentText(),
                "args": self.w_args.text(),
                "pos": self.w_pos.currentText(),
            }
        return d

