from qtpy.QtWidgets import (
    QLineEdit,
    QDoubleSpinBox,
    QComboBox,
    QSlider,
    QWidget,
    QHBoxLayout,
    QVBoxLayout,
    QLabel,
    QTextEdit,
)
from qtpy.QtCore import Qt, QTimer
from qtpy.QtGui import QFont, QImage, QPixmap
from ryven.gui_env import NodeInputWidget, NodeMainWidget, Data
import numpy as np
from typing import Tuple


def _extract_payload(value):
    return value.payload if hasattr(value, "payload") else value


def _read_port_payload(node, source: str = "input", port_index: int = 0):
    """Read payload from node input/output port in a tolerant way."""
    if node is None:
        return None

    source = str(source or "input").lower()
    idx = int(port_index)
    raw = None

    if source in ("input", "in"):
        if hasattr(node, "input"):
            try:
                raw = node.input(idx)
            except Exception:
                raw = None
        elif hasattr(node, "inputs") and 0 <= idx < len(node.inputs):
            raw = node.inputs[idx]
    elif source in ("output", "out"):
        if hasattr(node, "output"):
            try:
                raw = node.output(idx)
            except Exception:
                raw = None
        elif hasattr(node, "outputs") and 0 <= idx < len(node.outputs):
            out_obj = node.outputs[idx]
            # Try common output value field names.
            for attr in ("val", "value", "payload"):
                if hasattr(out_obj, attr):
                    raw = getattr(out_obj, attr)
                    break
            if raw is None:
                raw = out_obj

    return _extract_payload(raw)


def float_spinbox(
    init: float = 1.0,
    range: Tuple[float, float] = (0.0, 99.0),
    decimals: int = 2,
    step: float = 0.1,
    descr: str = "",
):
    """Creates a Float Spin Box input widget class."""

    class StdInpWidget_FloatSpinBox(NodeInputWidget, QDoubleSpinBox):
        def __init__(self, params):
            NodeInputWidget.__init__(self, params)
            QDoubleSpinBox.__init__(self)

            self._prevent_update = False
            self.setRange(*range)
            self.setDecimals(decimals)
            self.setSingleStep(step)
            self.setValue(init)
            self.setMinimumWidth(80)

            font = QFont()
            font.setFamily("Arial")
            font.setPointSize(8)
            self.setFont(font)

            if descr:
                self.setToolTip(descr)
            self.valueChanged.connect(self.value_changed)

        def value_changed(self, value):
            if not self._prevent_update:
                self.update_node_input(Data(value))

        @property
        def val(self):
            return Data(self.value())

        def get_state(self):
            return {"val": self.val}

        def set_state(self, data):
            if "val" in data:
                self._prevent_update = True
                self.setValue(data["val"].payload)
                self._prevent_update = False

        def val_update_event(self, val):
            if isinstance(val.payload, (int, float)):
                self._prevent_update = True
                self.setValue(float(val.payload))
                self._prevent_update = False

    StdInpWidget_FloatSpinBox.__doc__ = descr
    return StdInpWidget_FloatSpinBox


def combo_box(items: list = None, init_index: int = 0, descr: str = ""):
    """Creates a Combo Box input widget class."""
    if items is None:
        items = []

    class StdInpWidget_ComboBox(NodeInputWidget, QComboBox):
        def __init__(self, params):
            NodeInputWidget.__init__(self, params)
            QComboBox.__init__(self)
            self._prevent_update = False
            self.addItems(items)
            self.setCurrentIndex(init_index)
            self.setMinimumWidth(120)

            font = QFont()
            font.setFamily("Arial")
            font.setPointSize(8)
            self.setFont(font)

            if descr:
                self.setToolTip(descr)
            self.currentTextChanged.connect(self.selection_changed)

        def selection_changed(self, text):
            if not self._prevent_update:
                self.update_node_input(Data(text))

        @property
        def val(self):
            return Data(self.currentText())

        def get_state(self):
            return {"val": self.val}

        def set_state(self, data):
            if "val" in data:
                text = data["val"].payload
                index = self.findText(str(text))
                if index >= 0:
                    self._prevent_update = True
                    self.setCurrentIndex(index)
                    self._prevent_update = False

        def val_update_event(self, val):
            text = str(val.payload)
            index = self.findText(text)
            if index >= 0:
                self._prevent_update = True
                self.setCurrentIndex(index)
                self._prevent_update = False

    StdInpWidget_ComboBox.__doc__ = descr
    return StdInpWidget_ComboBox


def slider(
    init: float = 0.5,
    range: Tuple[float, float] = (0.0, 1.0),
    decimals: int = 2,
    descr: str = "",
):
    """Creates a Slider input widget with an editable value box on the left."""
    _min, _max = range
    _steps = 10000

    class StdInpWidget_Slider(NodeInputWidget, QWidget):
        def __init__(self, params):
            NodeInputWidget.__init__(self, params)
            QWidget.__init__(self)

            self._prevent_update = False
            self._range = (_min, _max)
            self._decimals = decimals
            self._steps = _steps

            layout = QHBoxLayout(self)
            layout.setContentsMargins(0, 0, 0, 0)

            self.value_edit = QLineEdit()
            self.value_edit.setFixedWidth(60)
            self.value_edit.setAlignment(Qt.AlignCenter)

            font = QFont()
            font.setFamily("Arial")
            font.setPointSize(8)
            self.value_edit.setFont(font)

            self.slider = QSlider(Qt.Horizontal)
            self.slider.setRange(0, _steps)
            self.slider.setMinimumHeight(22)

            layout.addWidget(self.value_edit)
            layout.addWidget(self.slider, 1)

            if descr:
                self.setToolTip(descr)

            self._set_internal_value(init)
            self.value_edit.editingFinished.connect(self._on_edit_finished)
            self.value_edit.returnPressed.connect(self._on_edit_finished)
            self.slider.valueChanged.connect(self._on_slider_changed)

        def _to_slider_pos(self, val: float) -> int:
            r0, r1 = self._range
            if r1 <= r0:
                return 0
            p = (float(val) - r0) / (r1 - r0)
            return int(round(p * self._steps))

        def _from_slider_pos(self, pos: int) -> float:
            r0, r1 = self._range
            p = pos / self._steps
            return r0 + p * (r1 - r0)

        def _set_internal_value(self, val: float):
            r0, r1 = self._range
            val = max(r0, min(r1, float(val)))
            self._prevent_update = True
            self.value_edit.setText(f"{val:.{self._decimals}f}")
            self.slider.setValue(self._to_slider_pos(val))
            self._prevent_update = False

        def _on_edit_finished(self):
            if self._prevent_update:
                return
            try:
                val = float(self.value_edit.text().strip())
                self._set_internal_value(val)
                self.update_node_input(Data(val))
            except ValueError:
                pass

        def _on_slider_changed(self, pos: int):
            if self._prevent_update:
                return
            val = self._from_slider_pos(pos)
            self._prevent_update = True
            self.value_edit.setText(f"{val:.{self._decimals}f}")
            self._prevent_update = False
            self.update_node_input(Data(val))

        @property
        def val(self):
            try:
                return Data(float(self.value_edit.text()))
            except ValueError:
                return Data(self._range[0])

        def get_state(self):
            return {"val": self.val}

        def set_state(self, data):
            if "val" in data:
                v = data["val"]
                payload = v.payload if hasattr(v, "payload") else v
                if isinstance(payload, (int, float)):
                    self._set_internal_value(float(payload))

        def val_update_event(self, val):
            payload = val.payload if hasattr(val, "payload") else val
            if isinstance(payload, (int, float)):
                self._set_internal_value(float(payload))

    StdInpWidget_Slider.__doc__ = descr
    return StdInpWidget_Slider


def button_main_widget(button_text: str = "Apply"):
    class _ButtonMainWidget(NodeMainWidget, QWidget):
        def __init__(self, params):
            NodeMainWidget.__init__(self, params)
            QWidget.__init__(self)

            from qtpy.QtWidgets import QPushButton

            btn = QPushButton(button_text)
            btn.clicked.connect(self.update_node)
            layout = QVBoxLayout(self)
            layout.setContentsMargins(0, 0, 0, 0)
            layout.addWidget(btn)

    return _ButtonMainWidget


def text_display_main_widget(
    title: str = "Text",
    placeholder: str = "No Data",
    read_only: bool = True,
    max_height: int = 180,
    source: str = "input",
    port_index: int = 0,
    refresh_on_init: bool = True,
    refresh_ms: int = 0,
):
    class _TextDisplayWidget(NodeMainWidget, QWidget):
        def __init__(self, params):
            NodeMainWidget.__init__(self, params)
            QWidget.__init__(self)
            self.node = getattr(self, "node", None)
            self.source = source
            self.port_index = port_index

            layout = QVBoxLayout(self)
            layout.setContentsMargins(2, 2, 2, 2)

            self.title_label = QLabel(f"{title} ({self.source}:{self.port_index})")
            self.text_display = QTextEdit()
            self.text_display.setReadOnly(read_only)
            self.text_display.setPlaceholderText(placeholder)
            self.text_display.setMaximumHeight(max_height)
            self.text_display.setStyleSheet("font-family: Consolas, monospace;")
            layout.addWidget(self.title_label)
            layout.addWidget(self.text_display)

            if refresh_on_init:
                self.refresh_from_node()
            if isinstance(refresh_ms, int) and refresh_ms > 0:
                self._timer = QTimer(self)
                self._timer.timeout.connect(self.refresh_from_node)
                self._timer.start(refresh_ms)

        def display_text(self, text):
            self.text_display.setPlainText(str(text))

        def append_text(self, text):
            self.text_display.append(str(text))

        def display_payload(self, val):
            payload = _extract_payload(val)
            self.display_text(payload)

        def clear_display(self):
            self.text_display.clear()

        def refresh_from_node(self):
            payload = _read_port_payload(self.node, self.source, self.port_index)
            if payload is not None:
                self.display_text(payload)

    return _TextDisplayWidget


def image_display_main_widget(
    width: int = 220,
    height: int = 160,
    placeholder: str = "No Image",
    keep_aspect: bool = True,
    source: str = "input",
    port_index: int = 0,
    color_order: str = "bgr",
    refresh_on_init: bool = True,
    refresh_ms: int = 0,
):
    class _ImageDisplayWidget(NodeMainWidget, QWidget):
        def __init__(self, params):
            NodeMainWidget.__init__(self, params)
            QWidget.__init__(self)
            self.node = getattr(self, "node", None)
            self.source = source
            self.port_index = port_index
            self.color_order = str(color_order).lower()

            layout = QVBoxLayout(self)
            layout.setContentsMargins(2, 2, 2, 2)

            self.image_label = QLabel(placeholder)
            self.image_label.setAlignment(Qt.AlignCenter)
            self.image_label.setMinimumSize(width, height)
            self.image_label.setMaximumSize(width, height)
            self.image_label.setStyleSheet(
                "QLabel { border: 1px solid #666666; background: #1f1f1f; color: #aaaaaa; }"
            )
            self.keep_aspect = keep_aspect
            self.placeholder = placeholder
            layout.addWidget(self.image_label)

            if refresh_on_init:
                self.refresh_from_node()
            if isinstance(refresh_ms, int) and refresh_ms > 0:
                self._timer = QTimer(self)
                self._timer.timeout.connect(self.refresh_from_node)
                self._timer.start(refresh_ms)

        def show_image(self, image):
            if image is None:
                self.image_label.clear()
                self.image_label.setText(self.placeholder)
                return
            try:
                arr = np.asarray(image)
                if arr.ndim == 2:
                    h, w = arr.shape
                    arr = np.ascontiguousarray(arr.astype(np.uint8))
                    q_img = QImage(arr.data, w, h, w, QImage.Format_Grayscale8)
                else:
                    if arr.shape[2] > 3:
                        arr = arr[:, :, :3]
                    if self.color_order == "bgr":
                        arr = arr[:, :, ::-1]
                    arr = np.ascontiguousarray(arr.astype(np.uint8))
                    h, w = arr.shape[:2]
                    q_img = QImage(arr.data, w, h, w * 3, QImage.Format_RGB888)
                pix = QPixmap.fromImage(q_img)
                mode = Qt.KeepAspectRatio if self.keep_aspect else Qt.IgnoreAspectRatio
                self.image_label.setPixmap(
                    pix.scaled(self.image_label.width(), self.image_label.height(), mode, Qt.SmoothTransformation)
                )
            except Exception as e:
                self.image_label.setText(f"Display Error: {e}")

        def display_payload(self, val):
            payload = _extract_payload(val)
            self.show_image(payload)

        def refresh_from_node(self):
            payload = _read_port_payload(self.node, self.source, self.port_index)
            self.show_image(payload)

    return _ImageDisplayWidget


def matrix_display_main_widget(
    title: str = "Matrix",
    precision: int = 4,
    max_height: int = 220,
    source: str = "input",
    port_index: int = 0,
    max_rows: int = 12,
    max_cols: int = 12,
    refresh_on_init: bool = True,
    refresh_ms: int = 0,
):
    class _MatrixDisplayWidget(NodeMainWidget, QWidget):
        def __init__(self, params):
            NodeMainWidget.__init__(self, params)
            QWidget.__init__(self)
            self.node = getattr(self, "node", None)
            self.source = source
            self.port_index = port_index

            layout = QVBoxLayout(self)
            layout.setContentsMargins(2, 2, 2, 2)
            self.title_label = QLabel(f"{title} ({self.source}:{self.port_index})")
            self.text_display = QTextEdit()
            self.text_display.setReadOnly(True)
            self.text_display.setMaximumHeight(max_height)
            self.text_display.setStyleSheet("font-family: Consolas, monospace;")
            self.precision = precision
            self.max_rows = max_rows
            self.max_cols = max_cols
            layout.addWidget(self.title_label)
            layout.addWidget(self.text_display)

            if refresh_on_init:
                self.refresh_from_node()
            if isinstance(refresh_ms, int) and refresh_ms > 0:
                self._timer = QTimer(self)
                self._timer.timeout.connect(self.refresh_from_node)
                self._timer.start(refresh_ms)

        def _format_matrix(self, data):
            try:
                arr = np.asarray(data)
                if arr.ndim >= 1:
                    if arr.ndim == 2:
                        arr = arr[: self.max_rows, : self.max_cols]
                    return np.array2string(arr, precision=self.precision, suppress_small=False)
            except Exception:
                pass
            return str(data)

        def display_matrix(self, data):
            self.text_display.setPlainText(self._format_matrix(data))

        def display_payload(self, val):
            payload = _extract_payload(val)
            self.display_matrix(payload)

        def refresh_from_node(self):
            payload = _read_port_payload(self.node, self.source, self.port_index)
            if payload is not None:
                self.display_matrix(payload)

    return _MatrixDisplayWidget
