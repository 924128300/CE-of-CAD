"""画布配色与通用样式。"""
from __future__ import annotations

BG = "#0f1419"
PANEL_BG = "#151b22"
GRID = "#1b232c"
TEXT = "#d7dee8"
MUTED = "#8a97a6"
ACCENT = "#2f81f7"
SELECT = "#19e3ff"
REVERSE = "#ff6b9d"
HOVER = "#ffcc33"
DEFAULT_ENTITY = (210, 218, 228)

STYLE_SHEET = f"""
QMainWindow, QDialog {{
    background: {BG};
}}
QWidget {{
    color: {TEXT};
    font-family: "Microsoft YaHei UI", "Segoe UI", sans-serif;
    font-size: 12px;
}}
QToolBar {{
    background: {PANEL_BG};
    border: none;
    spacing: 6px;
    padding: 4px 8px;
}}
QToolButton {{
    background: transparent;
    border: 1px solid transparent;
    border-radius: 4px;
    padding: 5px 9px;
}}
QToolButton:hover {{
    background: #1f2a35;
    border-color: #2a3a49;
}}
QToolButton:checked {{
    background: #1d3a5c;
    border-color: {ACCENT};
}}
QToolButton:disabled {{
    color: #5a6673;
}}
QGroupBox {{
    border: 1px solid #24303c;
    border-radius: 5px;
    margin-top: 10px;
    padding-top: 8px;
}}
QGroupBox::title {{
    subcontrol-origin: margin;
    left: 8px;
    padding: 0 4px;
    color: {MUTED};
}}
QTreeWidget, QTableWidget, QTableView, QListWidget, QTextBrowser, QPlainTextEdit {{
    background: #121920;
    border: 1px solid #24303c;
    border-radius: 4px;
    alternate-background-color: #151d25;
    selection-background-color: #1d3a5c;
}}
QHeaderView::section {{
    background: #1a2430;
    color: {MUTED};
    border: none;
    border-right: 1px solid #24303c;
    padding: 4px 6px;
}}
QLineEdit, QComboBox, QDoubleSpinBox, QSpinBox {{
    background: #121920;
    border: 1px solid #2a3948;
    border-radius: 4px;
    padding: 4px 6px;
}}
QPushButton {{
    background: #1d2a36;
    border: 1px solid #2c3d4d;
    border-radius: 4px;
    padding: 5px 12px;
}}
QPushButton:hover {{
    background: #24384a;
}}
QPushButton:disabled {{
    color: #5a6673;
}}
QPushButton#primary {{
    background: {ACCENT};
    border-color: {ACCENT};
    color: #ffffff;
    font-weight: bold;
}}
QPushButton#primary:hover {{
    background: #4b95ff;
}}
QStatusBar {{
    background: {PANEL_BG};
    color: {MUTED};
}}
QSplitter::handle {{
    background: #1a222b;
    width: 1px;
}}
QScrollBar:vertical {{
    background: #121920;
    width: 10px;
}}
QScrollBar::handle:vertical {{
    background: #2a3948;
    border-radius: 5px;
    min-height: 24px;
}}
QScrollBar::add-line, QScrollBar::sub-line {{
    height: 0px;
}}
QCheckBox {{
    spacing: 6px;
}}
"""
