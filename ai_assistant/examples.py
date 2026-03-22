"""Example JSON strings embedded in prompts (English labels; Data-flow vs literal-input patterns)."""

from __future__ import annotations

import json

# Typical Ryven pattern: upstream node sends Data(ndarray or nested list). NodeBase.get_input_val
# already unwraps .payload, so inK is the raw value — no line_edit needed.
_NODE_DATA_FLOW = {
    "class_name": "ToMatrixNode",
    "title": "To matrix",
    "description": "Cast upstream Data (list or ndarray) to a numpy ndarray; output as Data",
    "color": "#4e79ad",
    "inputs": [{"label": "arr", "type": "data"}],
    "outputs": [{"label": "matrix", "type": "data"}],
    "core_logic": (
        "import numpy as np\n"
        "x = np.asarray(in0)\n"
        "self.set_output_val(0, Data(x))"
    ),
    "has_main_widget": False,
    "main_widget_template": "None",
    "main_widget_args": "",
    "main_widget_pos": "below ports",
    "main_widget_code": "# Only when main_widget_template is custom",
}

NODE_CONFIG_JSON_EXAMPLE = json.dumps(_NODE_DATA_FLOW, ensure_ascii=False, indent=2)

# When the user must type a literal on the node (no upstream array), use a widget on the data port.
_NODE_LITERAL_INPUT = {
    "class_name": "LiteralMatrixNode",
    "title": "Matrix from literal",
    "description": "Parse a typed Python literal from line_edit into ndarray",
    "color": "#5a8fc7",
    "inputs": [
        {
            "label": "txt",
            "type": "data",
            "widget": {
                "type": "line_edit",
                "args": "init='[[1,0],[0,1]]', descr='2D list literal'",
                "pos": "besides",
            },
        }
    ],
    "outputs": [{"label": "matrix", "type": "data"}],
    "core_logic": (
        "import ast\n"
        "import numpy as np\n"
        "x = np.asarray(ast.literal_eval(str(in0)))\n"
        "self.set_output_val(0, Data(x))"
    ),
    "has_main_widget": False,
    "main_widget_template": "None",
    "main_widget_args": "",
    "main_widget_pos": "below ports",
    "main_widget_code": "# Only when main_widget_template is custom",
}

NODE_CONFIG_LITERAL_EXAMPLE = json.dumps(_NODE_LITERAL_INPUT, ensure_ascii=False, indent=2)

_PATCH_MINI = {
    "class_name": "AddFloatsNode",
    "title": "Add floats",
    "inputs": [
        {
            "label": "x",
            "type": "data",
            "widget": {
                "type": "float_spinbox",
                "args": "init=0.5, range=(0.0, 1.0), step=0.1, descr='x'",
                "pos": "besides",
            },
        },
        {
            "label": "y",
            "type": "data",
            "widget": {
                "type": "int_spinbox",
                "args": "init=10, range=(0, 100), descr='y'",
                "pos": "besides",
            },
        },
    ],
    "outputs": [{"label": "sum", "type": "data"}],
    "core_logic": "self.set_output_val(0, Data(float(in0) + int(in1)))",
}

CONFIG_PATCH_MINI_EXAMPLE = json.dumps(_PATCH_MINI, ensure_ascii=False, indent=2)

INPUT_WIDGET_TYPES = (
    "Omit `widget` on a data port when the value comes from upstream nodes as Data (recommended for tensors/"
    "arrays). Use int_spinbox, float_spinbox, line_edit, combo_box, slider, or type None only when the node "
    "needs on-graph parameter editing. Exec ports never have widgets. "
    "The `args` string is passed into the widget factory (see Generator/widget_template.py and gui template); "
    "do not invent new `type` strings unless a matching factory exists in widget_template."
)
