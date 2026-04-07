"""Jinja2 source strings for Ryven `nodes.py` and `gui.py` generation.

This variant intentionally does *not* auto-inject `in0/in1/... = self.get_input_val(...)`
bindings into `core_logic`. Instead, `core_logic` must explicitly call
`self.get_input_val(index)` so the AI can choose meaningful variable names.
"""

# --- multi-node nodes.py ---
NODES_TEMPLATE = '''from ryven.node_env import *
from . import nodes

class NodeBase(Node):
    def __init__(self, params):
        Node.__init__(self, params)

    def get_input_val(self, index):
        val = self.input(index)
        return val.payload if val and hasattr(val, 'payload') else val

{% for node in configs %}
class {{ node.class_name }}(NodeBase):
    """ {{ node.description }} """
    title = '{{ node.title }}' # Node Title
    init_inputs = [ # Node Inputs
        {% for inp in node.inputs %}NodeInputType(label='{{ inp.label }}', type_='{{ inp.type }}'),
        {% endfor %}]
    init_outputs = [ # Node Outputs
        {% for outp in node.outputs %}NodeOutputType(label='{{ outp.label }}', type_='{{ outp.type }}'),
        {% endfor %}]

    def update_event(self, inp=-1):
        {% for inp in node.inputs %}{% if inp.type == 'exec' %}
        if inp == -1 {% for sub_inp in node.inputs %}{% if sub_inp.type == 'data' %} or inp == {{loop.index0}}{% endif %}{% endfor %}:
            return
        {% endif %}{% endfor %}
        try:
            # Core Logic ======================
            {{ node.core_logic | indent(12) }}

            {% for outp in node.outputs %}
            {% if outp.type == 'exec' %}self.exec_output({{ loop.index0 }}) {% endif %}
            {% endfor %}
        except Exception as e:
            print("[{{ node.title }}] Error:", e)

{% endfor %}
export_nodes([
    {% for node in configs %}{{ node.class_name }},
    {% endfor %}
])

@on_gui_load
def load_gui():
    from . import gui
'''

# --- multi-node gui.py ---
GUI_TEMPLATE = '''from ryven.gui_env import *
from . import nodes
from .widget_template import *

{% for node in configs %}
{% if node.has_main_widget and node.main_widget_template == "custom" %}
from qtpy.QtWidgets import QWidget
class {{ node.class_name }}_MainWidget(NodeMainWidget, QWidget):
    def __init__(self, params):
        NodeMainWidget.__init__(self, params)
        QWidget.__init__(self)
        self.setFixedSize(220, 120)
{{ node.main_widget_code | default('# Your custom initialization code here') | indent(8, true) }}

{% endif %}
@node_gui(nodes.{{ node.class_name }})
class {{ node.class_name }}Gui(NodeGUI):
    color = '{{ node.color }}'
    input_widget_classes = {
        {% for inp in node.inputs %}{% if inp.widget and inp.widget.type != "None" %}
        {% if inp.widget.type == 'int_spinbox' %}'{{ inp.label }}_widget_{{ loop.index0 }}': inp_widgets.Builder.int_spinbox({{ inp.widget.args }}),
        {% elif inp.widget.type == 'float_spinbox' %}'{{ inp.label }}_widget_{{ loop.index0 }}': float_spinbox({{ inp.widget.args }}),
        {% elif inp.widget.type == 'line_edit' %}'{{ inp.label }}_widget_{{ loop.index0 }}': inp_widgets.Builder.evaled_line_edit({{ inp.widget.args }}),
        {% elif inp.widget.type == 'combo_box' %}'{{ inp.label }}_widget_{{ loop.index0 }}': combo_box({{ inp.widget.args }}),
        {% elif inp.widget.type == 'slider' %}'{{ inp.label }}_widget_{{ loop.index0 }}': slider({{ inp.widget.args }}),
        {% else %}'{{ inp.label }}_widget_{{ loop.index0 }}': {{ inp.widget.type }}({{ inp.widget.args }}),
        {% endif %}{% endif %}{% endfor %}
    }
    init_input_widgets = {
        {% for inp in node.inputs %}{% if inp.widget and inp.widget.type != "None" %}
        {{ loop.index0 }}: {'name': '{{ inp.label }}_widget_{{ loop.index0 }}', 'pos': '{{ inp.widget.pos or 'besides' }}'},
        {% endif %}{% endfor %}
    }
    {% if node.has_main_widget %}
    {% if node.main_widget_template == "button" %}
    main_widget_class = button_main_widget({{ node.main_widget_args or '' }})
    {% elif node.main_widget_template == "text_display" %}
    main_widget_class = text_display_main_widget({{ node.main_widget_args or '' }})
    {% elif node.main_widget_template == "image_display" %}
    main_widget_class = image_display_main_widget({{ node.main_widget_args or '' }})
    {% elif node.main_widget_template == "matrix_display" %}
    main_widget_class = matrix_display_main_widget({{ node.main_widget_args or '' }})
    {% elif node.main_widget_template == "custom" %}
    main_widget_class = {{ node.class_name }}_MainWidget
    {% endif %}
    main_widget_pos = '{{ node.main_widget_pos or "below ports" }}'
    {% endif %}

{% endfor %}
'''

