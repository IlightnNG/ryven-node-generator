"""Render Ryven `nodes.py` / `gui.py` and copy bundled `widget_template.py` into the output folder."""

from __future__ import annotations

import os
import shutil
from pathlib import Path

from jinja2 import Template

from .templates_v2 import GUI_TEMPLATE, NODES_TEMPLATE

WIDGET_TEMPLATE_FILENAME = "widget_template.py"
_PKG_ROOT = Path(__file__).resolve().parent.parent


def generate_code_from_data(nodes_data):
    """Render nodes.py and gui.py strings from in-memory node configs (preview)."""
    for node in nodes_data:
        node.setdefault("main_widget_template", "button")
        node.setdefault("main_widget_args", "")
        node.setdefault("main_widget_pos", "below ports")
        node.setdefault("main_widget_code", "# Your custom initialization code here")
        node["main_widget_template"] = str(node["main_widget_template"]).lower()

    n_code = Template(NODES_TEMPLATE).render(configs=nodes_data)
    g_code = Template(GUI_TEMPLATE).render(configs=nodes_data)
    return n_code, g_code


def save_files(nodes_data, path="NodeTest"):
    """Write nodes.py, gui.py, and widget_template.py to disk."""
    n_code, g_code = generate_code_from_data(nodes_data)
    os.makedirs(path, exist_ok=True)

    with open(f"{path}/nodes.py", "w", encoding="utf-8") as f:
        f.write(n_code)
    with open(f"{path}/gui.py", "w", encoding="utf-8") as f:
        f.write(g_code)

    src_template = _PKG_ROOT / "assets" / WIDGET_TEMPLATE_FILENAME
    dst_template = os.path.join(path, WIDGET_TEMPLATE_FILENAME)
    shutil.copyfile(src_template, dst_template)
