"""Qt stylesheets and editor defaults for the studio UI."""

STYLE = """
/* Retro low-saturation theme: steel blue accent, dusty red danger, sage green hints */
QMainWindow { background-color: #0c0e11; color: #d3d8e0; }
QWidget { background-color: #0c0e11; color: #d3d8e0; font-family: 'Segoe UI', 'Consolas'; font-size: 12px; }
QLabel { background: transparent; color: #9aa4b0; }

QWidget#LeftPanel, QWidget#EditorPanel, QWidget#PreviewPanel {
    background-color: #111418;
}
QWidget#EditorContent {
    background-color: #111418;
}

QFrame#TopBar {
    background-color: #12161b;
    border-bottom: 1px solid #2c3138;
}

QPushButton {
    background-color: #23272e;
    color: #d3d8e0;
    border: 1px solid #3a424c;
    border-radius: 6px;
    padding: 5px 10px;
    min-height: 24px;
    font-weight: 600;
}
QPushButton:hover {
    background-color: #2b3038;
    border-color: #5f7d93;
}
QPushButton:pressed {
    background-color: #1e2228;
    border-color: #4d6578;
    padding-top: 6px;
    padding-left: 11px;
    padding-right: 9px;
    padding-bottom: 4px;
}
QPushButton:disabled {
    background-color: #1a1e24;
    border-color: #2d323a;
    color: #6d7580;
}

QFrame#TopBar QPushButton {
    min-width: 84px;
}
QFrame#TopBar QPushButton#PrimaryBtn {
    background-color: #3a4f62;
    border: 1px solid #5f7d93;
    color: #e8eef4;
    font-weight: bold;
}
QFrame#TopBar QPushButton#PrimaryBtn:hover { background-color: #435a6e; border-color: #6d8ca2; }
QFrame#TopBar QPushButton#PrimaryBtn:pressed { background-color: #334556; border-color: #547286; }
QFrame#TopBar QPushButton#DangerBtn {
    background-color: #3d2e30;
    border: 1px solid #6e585a;
    color: #d8c8ca;
}
QFrame#TopBar QPushButton#DangerBtn:hover {
    background-color: #4a383b;
    border-color: #7d6568;
}
QFrame#TopBar QPushButton#DangerBtn:pressed { background-color: #322628; }

QSplitter::handle { background-color: #262b33; width: 1px; }
QSplitter::handle:hover { background-color: #4a5f72; }

QGroupBox {
    border: 1px solid #323840;
    border-radius: 8px;
    margin-top: 10px;
    padding-top: 10px;
    background-color: #161a20;
    font-weight: bold;
    color: #8fa0b0;
}
QGroupBox::title {
    subcontrol-origin: margin;
    left: 10px;
    padding: 0 4px;
}

QLineEdit, QComboBox {
    background-color: #1a1f26;
    color: #d3d8e0;
    border: 1px solid #343b44;
    border-radius: 6px;
    padding: 4px 8px;
    min-height: 26px;
    max-height: 28px;
}
QTextEdit, QListWidget {
    background-color: #1a1f26;
    color: #d3d8e0;
    border: 1px solid #343b44;
    border-radius: 6px;
    padding: 6px 8px;
}
QLineEdit:focus, QTextEdit:focus, QComboBox:focus, QListWidget:focus {
    border: 1px solid #5f7d93;
}

QListWidget::item { padding: 5px; border-radius: 4px; }
QListWidget::item:selected { background-color: #2a3138; border-left: 2px solid #5f7d93; }

QTabWidget::pane { border: 1px solid #323840; background-color: #161a20; }
QTabBar::tab {
    background: #161a20;
    color: #8e96a0;
    padding: 7px 12px;
    border: none;
}
QTabBar::tab:selected {
    color: #c8d0d8;
    border-bottom: 2px solid #5f7d93;
    font-weight: bold;
}
QTabBar::tab:hover { color: #d0d6de; }

QFrame#PortCard {
    background-color: #1a1f26;
    border: 1px solid #323842;
    border-radius: 8px;
}
QFrame#PortCard QWidget#PortWidgetPanel {
    background-color: #1a1f26;
}
QFrame#PortCard QLabel {
    background: transparent;
    color: #9aa4b0;
}
QFrame#PortCard QLabel#IndexBadge {
    background-color: #252b33;
    color: #a8b0ba;
    border: 1px solid #3d444d;
    border-radius: 4px;
    padding: 2px 5px;
    font-weight: bold;
}
QFrame#PortCard QPushButton#MoveBtn {
    background-color: #242a32;
    color: #c5cad2;
    border: 1px solid #3b424d;
    border-radius: 4px;
    padding: 0;
    font-weight: bold;
}
QFrame#PortCard QPushButton#MoveBtn:hover { border-color: #5f7d93; background-color: #2d343d; color: #e8eaed; }
QFrame#PortCard QPushButton#MoveBtn:pressed { background-color: #21272e; }
QFrame#PortCard QPushButton#MoveBtn:disabled { color: #5c636d; background-color: #1b2026; border-color: #2f353e; }
QFrame#PortCard QPushButton#DeleteBtn {
    background-color: #3d2e30;
    color: #d8c8ca;
    border: 1px solid #6e585a;
    border-radius: 4px;
    padding: 0 6px;
    font-weight: bold;
}
QFrame#PortCard QPushButton#DeleteBtn:hover { background-color: #4a383b; border-color: #7d6568; }
QFrame#PortCard QPushButton#DeleteBtn:pressed { background-color: #322628; }

QScrollArea {
    background-color: #111418;
    border: 1px solid #323840;
    border-radius: 8px;
}
QScrollBar:vertical { background: #13171c; width: 10px; border: none; }
QScrollBar::handle:vertical { background: #3a414c; border-radius: 4px; min-height: 18px; }
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0; }

QScrollArea#AiChatScroll {
    border: 1px solid #323840;
    border-radius: 10px;
    background-color: #0e1014;
}
QFrame#AiUserBubble {
    background-color: #1a2630;
    border: 1px solid #3d5568;
    border-radius: 12px;
}
QFrame#AiAssistantBubble {
    background-color: #1c2128;
    border: 1px solid #343b46;
    border-radius: 12px;
}
QFrame#AiSystemBubble {
    background-color: #2a2526;
    border: 1px solid #5a4e50;
    border-radius: 10px;
}
QLabel#AiChatMeta {
    color: #7d8a96;
    font-size: 10px;
    font-weight: 600;
    letter-spacing: 0.4px;
    background: transparent;
}
QLabel#AiBubbleBody {
    color: #d3d8e0;
    font-size: 12px;
    background: transparent;
}
QTextEdit#AiStreamEditor {
    background-color: #161b22;
    color: #cfd4dc;
    border: 1px solid #323840;
    border-radius: 8px;
    padding: 8px;
}
QTextEdit#AiChatComposer {
    border: 1px solid #343b44;
    border-radius: 8px;
}
QToolButton#AiWithdrawBtn {
    background-color: #242a32;
    color: #9aa7b8;
    border: 1px solid #3b424d;
    border-radius: 6px;
    min-width: 30px;
    min-height: 30px;
    font-size: 15px;
}
QToolButton#AiWithdrawBtn:hover {
    background-color: #2d3540;
    color: #c5ced9;
    border-color: #5f7d93;
}
QToolButton#AiWithdrawBtn:disabled {
    color: #555c66;
    background-color: #1a1f26;
    border-color: #2a3038;
}
QWidget#AiInputCard {
    background-color: #151a21;
    border: 1px solid #323840;
    border-radius: 10px;
}
"""

INPUT_WIDGET_EXAMPLES = {
    "None": "",
    "int_spinbox": "init=1, range=(0, 100), descr='Input Desc'",
    "float_spinbox": "init=0.5, range=(0.0, 1.0), step=0.1, descr='Input Desc'",
    "line_edit": "init='default', descr='Input Desc'",
    "combo_box": "items=['A', 'B'], init_index=0, descr='Input Desc'",
    "slider": "init=0.5, range=(0.0, 1.0), decimals=2, descr='Input Desc'",
}

# Muted retro green for “AI modified field” text (matches theme greens).
_AI_MODIFIED_TEXT_GREEN = "#7a9180"

# Single-line editor controls: unified height (px).
EDITOR_ROW_H = 28

# Fixed width for editor field labels (Class Name, Node Title, …).
EDITOR_LABEL_W = 76

MAIN_WIDGET_EXAMPLES = {
    "button": "button_text='Apply'",
    "text_display": "title='Text', placeholder='No Data', read_only=True, max_height=180, source='input', port_index=0, refresh_on_init=True",
    "image_display": "width=220, height=160, placeholder='No Image', keep_aspect=True, source='input', port_index=0, color_order='bgr', refresh_on_init=True",
    "matrix_display": "title='Matrix', precision=4, max_height=220, source='output', port_index=0, max_rows=12, max_cols=12, refresh_on_init=True",
    "custom": "",
}
