# Ryven Node Generator

A desktop tool for designing and generating **Ryven-compatible node packages**. You define nodes in a visual editor (ports, widgets, colors, and Python logic); the app emits the standard `nodes.py`, `gui.py`, and `widget_template.py` layout expected by Ryven so end users can load the folder as a node package.

## Features

- **Visual node studio** — PySide6 UI to edit node metadata: titles, descriptions, input/output ports (`exec` / `data`), optional input widgets, main widgets (button, displays, or custom), and node color.
- **Code generation** — Jinja2 templates in `generator.py` render Ryven-style `nodes.py` and `gui.py`; `widget_template.py` is copied into the output folder.
- **Flow-style preview** — `node_preview.py` draws a lightweight preview of the node (ports and widgets) before you export.
- **Project workspace** — Save/load a project directory with `nodes_config.json` (node definitions) and optional `generator_ai_chat.json` (AI chat history).
- **Optional AI assistant** — With API keys configured, LangChain + an OpenAI-compatible chat model can suggest `core_logic` and partial config updates from natural language (see `.env.example`).

## Requirements

- **Python 3.10+** (recommended)
- **Core UI & codegen:** `PySide6`, `Jinja2`
- **AI features (optional):** `pip install -r requirements-ai.txt` and a `.env` file (see below)
- **Running generated nodes inside Ryven:** the generated package uses `ryven`, `qtpy`, and `numpy` (typical Ryven node environment)

## Installation

```bash
cd Generator
python -m venv .venv
# Windows: .venv\Scripts\activate
# macOS/Linux: source .venv/bin/activate

pip install PySide6 Jinja2
pip install -r requirements-ai.txt   # optional, for AI assistant
```

Copy `.env.example` to `.env` and set your provider (e.g. OpenAI or DashScope-compatible endpoint). **Do not commit `.env`.**

## Usage

Start the application:

```bash
python ui.py
```

1. Design or import your nodes in the UI.
2. Choose an output folder and generate files (`nodes.py`, `gui.py`, `widget_template.py`).
3. Point **Ryven** at that folder as a node package so users can add your nodes to their flows.

## Project layout (this repository)

| Path | Role |
|------|------|
| `ui.py` | Main window (`NodeStudio`); entry point |
| `generator.py` | Templates and file generation |
| `node_preview.py` | On-canvas-style node preview |
| `project_workspace.py` | `nodes_config.json` / `generator_ai_chat.json` I/O |
| `widget_template.py` | Shared widget helpers copied into generated packages |
| `ai_assistant/` | Optional LLM integration (structured JSON turns) |

## License

Add a `LICENSE` file if you publish this project publicly.
