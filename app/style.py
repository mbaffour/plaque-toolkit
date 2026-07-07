"""Centralised visual theme for the Plaque Toolkit desktop app.

A single accent colour, consistent spacing, rounded controls, hover/pressed states,
styled tabs / group boxes / tables. ``get_stylesheet()`` is applied once in launch().
A professional light theme is the default; a dark variant is available as a bonus.
"""
import re

# --------------------------------------------------------------------------- #
#  Palettes — one accent colour per theme, everything derives from these.
# --------------------------------------------------------------------------- #
LIGHT = {
    "accent":        "#2563eb",   # primary action / selection (indigo-blue)
    "accent_hover":  "#1d4ed8",
    "accent_press":  "#1e40af",
    "accent_soft":   "#dbeafe",   # tinted backgrounds (selected rows, soft fills)
    "bg":            "#f4f6fb",   # window background
    "surface":       "#ffffff",   # cards / panels / inputs
    "surface_alt":   "#eef1f7",   # alternating rows, subtle fills
    "border":        "#d6dbe5",
    "border_strong": "#c2c9d6",
    "text":          "#1f2733",
    "text_muted":    "#6b7484",
    "text_inverse":  "#ffffff",
    "ok":            "#16a34a",
    "warn":          "#d97706",
    "danger":        "#dc2626",
    "shadow":        "#00000018",
}

DARK = {
    "accent":        "#3b82f6",
    "accent_hover":  "#60a5fa",
    "accent_press":  "#2563eb",
    "accent_soft":   "#1e293b",
    "bg":            "#0f141c",
    "surface":       "#1a212d",
    "surface_alt":   "#222b39",
    "border":        "#2c3644",
    "border_strong": "#3a4658",
    "text":          "#e6eaf2",
    "text_muted":    "#9aa6b8",
    "text_inverse":  "#ffffff",
    "ok":            "#22c55e",
    "warn":          "#f59e0b",
    "danger":        "#ef4444",
    "shadow":        "#00000040",
}

# Font stack kept platform-friendly; Segoe UI on Windows reads cleanly at these sizes.
_FONT = '"Segoe UI", "Inter", "Helvetica Neue", Arial, sans-serif'


def palette(theme="light"):
    return DARK if theme == "dark" else LIGHT


def _scale_fonts(css, scale):
    """Multiply every ``font-size: Npx`` in a stylesheet by ``scale`` (>=1.0), so a single
    "Larger text" setting enlarges the whole UI consistently. Clamped to a sane range."""
    if not scale or abs(scale - 1.0) < 1e-3:
        return css
    scale = max(1.0, min(2.0, float(scale)))
    return re.sub(r"font-size:\s*(\d+)px",
                  lambda m: f"font-size: {max(9, int(round(int(m.group(1)) * scale)))}px",
                  css)


def get_stylesheet(theme="light", scale=1.0):
    """Return a complete Qt stylesheet string for the chosen theme.

    ``scale`` > 1.0 enlarges every font-size in the sheet — the accessibility
    "Larger text" setting in the View menu."""
    c = palette(theme)
    css = f"""
* {{
    font-family: {_FONT};
    font-size: 13px;
    color: {c['text']};
}}

QMainWindow, QDialog {{
    background: {c['bg']};
}}

/* Pop-up menus (Export ▾ dropdown, Help menu, context menus). Explicitly themed so the
   popup never falls back to the OS dark-mode background (which left dark text unreadable
   on a dark menu). */
QMenu {{
    background: {c['surface']};
    color: {c['text']};
    border: 1px solid {c['border_strong']};
    border-radius: 8px;
    padding: 4px;
}}
QMenu::item {{
    background: transparent;
    color: {c['text']};
    padding: 6px 22px 6px 16px;
    border-radius: 5px;
}}
QMenu::item:selected {{
    background: {c['accent']};
    color: {c['text_inverse']};
}}
QMenu::item:disabled {{
    color: {c['text_muted']};
}}
QMenu::separator {{
    height: 1px;
    background: {c['border']};
    margin: 4px 8px;
}}
QMenuBar {{
    background: {c['surface']};
    color: {c['text']};
}}
QMenuBar::item {{
    background: transparent;
    padding: 4px 10px;
}}
QMenuBar::item:selected {{
    background: {c['accent_soft']};
    color: {c['text']};
}}

QWidget#AppRoot {{
    background: {c['bg']};
}}

/* ---- Header / toolbar band ------------------------------------------- */
QFrame#HeaderBar {{
    background: {c['surface']};
    border: none;
    border-bottom: 1px solid {c['border']};
}}
QLabel#HeaderTitle {{
    font-size: 18px;
    font-weight: 700;
    color: {c['text']};
}}
QLabel#HeaderSubtitle {{
    font-size: 12px;
    color: {c['text_muted']};
}}

/* ---- Tabs ------------------------------------------------------------ */
QTabWidget::pane {{
    border: none;
    background: {c['bg']};
    top: -1px;
}}
QTabBar {{
    background: transparent;
}}
QTabBar::tab {{
    background: transparent;
    color: {c['text_muted']};
    padding: 9px 20px;
    margin-right: 2px;
    border: none;
    border-bottom: 2px solid transparent;
    font-weight: 600;
}}
QTabBar::tab:hover {{
    color: {c['text']};
}}
QTabBar::tab:selected {{
    color: {c['accent']};
    border-bottom: 2px solid {c['accent']};
}}

/* ---- Group boxes (cards) -------------------------------------------- */
QGroupBox {{
    background: {c['surface']};
    border: 1px solid {c['border']};
    border-radius: 10px;
    margin-top: 14px;
    padding: 12px 14px 14px 14px;
    font-weight: 600;
}}
QGroupBox::title {{
    subcontrol-origin: margin;
    subcontrol-position: top left;
    left: 12px;
    top: 2px;
    padding: 0 4px;
    color: {c['text_muted']};
    font-size: 12px;
}}

/* generic surface card */
QFrame#Card {{
    background: {c['surface']};
    border: 1px solid {c['border']};
    border-radius: 10px;
}}

/* ---- Buttons -------------------------------------------------------- */
QPushButton {{
    background: {c['surface']};
    color: {c['text']};
    border: 1px solid {c['border_strong']};
    border-radius: 8px;
    padding: 7px 16px;
    font-weight: 600;
}}
QPushButton:hover {{
    border-color: {c['accent']};
    color: {c['accent']};
}}
QPushButton:pressed {{
    background: {c['surface_alt']};
}}
QPushButton:disabled {{
    color: {c['text_muted']};
    border-color: {c['border']};
    background: {c['surface']};
}}

/* primary / accent buttons */
QPushButton#Primary {{
    background: {c['accent']};
    color: {c['text_inverse']};
    border: 1px solid {c['accent']};
}}
QPushButton#Primary:hover {{
    background: {c['accent_hover']};
    border-color: {c['accent_hover']};
    color: {c['text_inverse']};
}}
QPushButton#Primary:pressed {{
    background: {c['accent_press']};
    border-color: {c['accent_press']};
}}
QPushButton#Primary:disabled {{
    background: {c['border_strong']};
    border-color: {c['border_strong']};
    color: {c['surface']};
}}

/* ---- Inputs --------------------------------------------------------- */
QLineEdit, QDoubleSpinBox, QSpinBox, QComboBox {{
    background: {c['surface']};
    border: 1px solid {c['border_strong']};
    border-radius: 8px;
    padding: 6px 10px;
    selection-background-color: {c['accent']};
    selection-color: {c['text_inverse']};
}}
QLineEdit:focus, QDoubleSpinBox:focus, QSpinBox:focus, QComboBox:focus {{
    border: 1px solid {c['accent']};
}}
QLineEdit:hover, QDoubleSpinBox:hover, QSpinBox:hover, QComboBox:hover {{
    border-color: {c['accent']};
}}
QComboBox::drop-down {{
    border: none;
    width: 22px;
}}
QComboBox::down-arrow {{
    image: none;
    border-left: 4px solid transparent;
    border-right: 4px solid transparent;
    border-top: 5px solid {c['text_muted']};
    margin-right: 8px;
}}
QComboBox QAbstractItemView {{
    background: {c['surface']};
    border: 1px solid {c['border_strong']};
    border-radius: 8px;
    selection-background-color: {c['accent_soft']};
    selection-color: {c['text']};
    padding: 4px;
    outline: none;
}}
QDoubleSpinBox::up-button, QSpinBox::up-button,
QDoubleSpinBox::down-button, QSpinBox::down-button {{
    width: 16px;
    border: none;
    background: transparent;
}}

/* ---- Check boxes ---------------------------------------------------- */
QCheckBox {{
    spacing: 8px;
    padding: 2px 0;
}}
QCheckBox::indicator {{
    width: 16px;
    height: 16px;
    border-radius: 4px;
    border: 1px solid {c['border_strong']};
    background: {c['surface']};
}}
QCheckBox::indicator:hover {{
    border-color: {c['accent']};
}}
QCheckBox::indicator:checked {{
    background: {c['accent']};
    border-color: {c['accent']};
    image: none;
}}

/* ---- Tables --------------------------------------------------------- */
QTableView {{
    background: {c['surface']};
    alternate-background-color: {c['surface_alt']};
    border: 1px solid {c['border']};
    border-radius: 10px;
    gridline-color: {c['border']};
    selection-background-color: {c['accent_soft']};
    selection-color: {c['text']};
    outline: none;
}}
QTableView::item {{
    padding: 4px 6px;
    border: none;
}}
QHeaderView::section {{
    background: {c['surface_alt']};
    color: {c['text_muted']};
    padding: 7px 8px;
    border: none;
    border-right: 1px solid {c['border']};
    border-bottom: 1px solid {c['border']};
    font-weight: 600;
}}
QHeaderView::section:first {{
    border-top-left-radius: 10px;
}}
QHeaderView::section:last {{
    border-top-right-radius: 10px;
    border-right: none;
}}
QTableCornerButton::section {{
    background: {c['surface_alt']};
    border: none;
    border-bottom: 1px solid {c['border']};
}}

/* ---- Summary card --------------------------------------------------- */
QFrame#SummaryCard {{
    background: {c['surface']};
    border: 1px solid {c['border']};
    border-radius: 10px;
}}
QLabel#SummaryHeading {{
    color: {c['text_muted']};
    font-size: 11px;
    font-weight: 700;
}}

/* ---- Status pill / mode helper text --------------------------------- */
QLabel#ModeHelp {{
    color: {c['text_muted']};
    font-size: 12px;
}}
QLabel#Placeholder {{
    color: {c['text_muted']};
    font-size: 14px;
}}

/* ---- Splitter ------------------------------------------------------- */
QSplitter::handle {{
    background: transparent;
}}
QSplitter::handle:horizontal {{
    width: 10px;
}}
QSplitter::handle:vertical {{
    height: 10px;
}}

/* ---- Progress bar --------------------------------------------------- */
QProgressBar {{
    background: {c['surface_alt']};
    border: none;
    border-radius: 6px;
    height: 6px;
    text-align: center;
    color: transparent;
}}
QProgressBar::chunk {{
    background: {c['accent']};
    border-radius: 6px;
}}

/* ---- Status bar ----------------------------------------------------- */
QStatusBar {{
    background: {c['surface']};
    border-top: 1px solid {c['border']};
    color: {c['text_muted']};
}}
QStatusBar::item {{
    border: none;
}}

/* ---- Scrollbars ----------------------------------------------------- */
QScrollBar:vertical {{
    background: transparent;
    width: 12px;
    margin: 2px;
}}
QScrollBar::handle:vertical {{
    background: {c['border_strong']};
    border-radius: 5px;
    min-height: 30px;
}}
QScrollBar::handle:vertical:hover {{
    background: {c['text_muted']};
}}
QScrollBar:horizontal {{
    background: transparent;
    height: 12px;
    margin: 2px;
}}
QScrollBar::handle:horizontal {{
    background: {c['border_strong']};
    border-radius: 5px;
    min-width: 30px;
}}
QScrollBar::handle:horizontal:hover {{
    background: {c['text_muted']};
}}
QScrollBar::add-line, QScrollBar::sub-line {{
    width: 0; height: 0;
}}
QScrollBar::add-page, QScrollBar::sub-page {{
    background: transparent;
}}

/* ---- Tooltips ------------------------------------------------------- */
QToolTip {{
    background: {c['text']};
    color: {c['surface']};
    border: none;
    border-radius: 6px;
    padding: 6px 9px;
    font-size: 12px;
}}

/* ---- About tab body ------------------------------------------------- */
QLabel#AboutBody {{
    font-size: 13px;
    line-height: 150%;
}}
"""
    return _scale_fonts(css, scale)


# Colours the matplotlib canvas / figures should match the Qt theme with.
def figure_colors(theme="light"):
    c = palette(theme)
    return {
        "face": c["surface"],
        "text": c["text"],
        "accent": c["accent"],
        "muted": c["text_muted"],
    }
