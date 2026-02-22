"""
Design System for OCR Tool - Based on Pencil Design File
Nature-inspired green theme with warm neutral backgrounds
"""
from PySide6.QtWidgets import QGraphicsDropShadowEffect
from PySide6.QtGui import QColor

# =============================================================================
# COLOR PALETTE - From Pencil Design File
# =============================================================================

COLORS = {
    # Primary Accent (Nature Green)
    'accent_primary': '#3D8A5A',
    'accent_hover': '#2D6A44',
    'accent_light': '#C8F0D8',
    'accent_warm': '#D89575',
    
    # Background Colors (Warm Neutrals)
    'bg_primary': '#F5F4F1',      # Main window background
    'bg_surface': '#FFFFFF',       # Card surfaces
    'bg_muted': '#EDECEA',         # Subtle backgrounds
    'bg_elevated': '#FAFAF8',      # Elevated elements
    
    # Text Colors
    'text_primary': '#1A1918',     # Main text
    'text_secondary': '#6D6C6A',   # Secondary text
    'text_tertiary': '#9C9B99',    # Muted text
    
    # Border Colors
    'border_subtle': '#E5E4E1',
    'border_strong': '#D1D0CD',
    
    # Status Colors
    'status_positive': '#4D9B6A',  # Completed/Success
    'status_processing': '#4A90D9', # Processing
    'status_pending': '#9C9B99',   # Pending
    'status_warning': '#D4A64A',   # Warning
    'status_negative': '#D08068',  # Error
    
    # Legacy mappings for compatibility
    'accent': '#3D8A5A',
    'success': '#4D9B6A',
    'error': '#D08068',
    'border': '#E5E4E1',
}

# =============================================================================
# RADIUS TOKENS
# =============================================================================

RADIUS = {
    'sm': 8,
    'md': 12,
    'lg': 16,
}

# =============================================================================
# SPACING SYSTEM (4px base grid)
# =============================================================================

SPACING = {
    'xs': 4,
    'sm': 8,
    'md': 12,
    'lg': 16,
    'xl': 24,
    'xxl': 32,
}

# =============================================================================
# TYPOGRAPHY SYSTEM
# =============================================================================

TYPOGRAPHY = {
    'family': "'SF Pro Text', 'Helvetica Neue', 'PingFang SC', system-ui",
    'family_mono': "'SF Mono', 'Menlo', monospace",
    'size_xs': 10,
    'size_sm': 12,
    'size_md': 13,
    'size_lg': 14,
    'size_xl': 16,
}

# =============================================================================
# ANIMATION DURATIONS (ms)
# =============================================================================

ANIMATION = {
    'fast': 150,
    'normal': 250,
    'slow': 400,
}

# =============================================================================
# GLOBAL STYLESHEET
# =============================================================================

GLOBAL_STYLE = """
QMainWindow {
    background-color: #F5F4F1;
}

QDialog {
    background-color: #FFFFFF;
    border-radius: 16px;
}

QStatusBar {
    background-color: #FFFFFF;
    border-top: 1px solid #E5E4E1;
    color: #6D6C6A;
    font-size: 12px;
    font-family: 'Helvetica Neue', 'PingFang SC';
}

QScrollBar:vertical {
    background-color: transparent;
    width: 8px;
}

QScrollBar::handle:vertical {
    background-color: #D1D0CD;
    border-radius: 4px;
    min-height: 30px;
}

QScrollBar::add-line:vertical,
QScrollBar::sub-line:vertical {
    height: 0;
}

QMessageBox {
    background-color: #FFFFFF;
}

QToolTip {
    background-color: #1A1918;
    color: #FFFFFF;
    border: none;
    border-radius: 8px;
    padding: 6px 10px;
    font-family: 'Helvetica Neue', 'PingFang SC';
}

QMenu {
    background-color: #FFFFFF;
    border: 1px solid #E5E4E1;
    border-radius: 12px;
    padding: 8px;
}

QMenu::item {
    padding: 8px 24px;
    border-radius: 8px;
    font-family: 'Helvetica Neue', 'PingFang SC';
}

QMenu::item:selected {
    background-color: #3D8A5A;
    color: white;
}

QMenu::separator {
    height: 1px;
    background-color: #E5E4E1;
    margin: 6px 12px;
}

QLineEdit {
    background: #F5F4F1;
    border: 1px solid #E5E4E1;
    border-radius: 8px;
    padding: 8px 12px;
    font-family: 'Helvetica Neue', 'PingFang SC';
    font-size: 13px;
}

QLineEdit:focus {
    border-color: #3D8A5A;
}

QComboBox {
    background: #F5F4F1;
    border: 1px solid #E5E4E1;
    border-radius: 8px;
    padding: 8px 12px;
    font-family: 'Helvetica Neue', 'PingFang SC';
    font-size: 13px;
}

QComboBox::drop-down { border: none; width: 24px; }
QComboBox::down-arrow {
    image: none;
    border-left: 5px solid transparent;
    border-right: 5px solid transparent;
    border-top: 6px solid #6D6C6A;
}

QCheckBox {
    font-family: 'Helvetica Neue', 'PingFang SC';
    font-size: 13px;
    color: #1A1918;
}

QCheckBox::indicator {
    width: 18px;
    height: 18px;
    border-radius: 4px;
    border: 2px solid #D1D0CD;
}

QCheckBox::indicator:checked {
    background-color: #3D8A5A;
    border-color: #3D8A5A;
}

QRadioButton {
    font-family: 'Helvetica Neue', 'PingFang SC';
    font-size: 13px;
    color: #1A1918;
}
"""

# =============================================================================
# BUTTON STYLES
# =============================================================================

def get_button_style(variant='primary'):
    """Get button style for specific variant"""
    if variant == 'primary':
        return """
            QPushButton {
                background-color: #3D8A5A;
                color: white;
                border: none;
                border-radius: 12px;
                padding: 10px 20px;
                font-size: 14px;
                font-weight: 600;
                font-family: 'Helvetica Neue', 'PingFang SC';
            }
            QPushButton:hover { background-color: #2D6A44; }
            QPushButton:pressed { background-color: #1D4A2E; }
            QPushButton:disabled { background-color: #EDECEA; color: #9C9B99; }
        """
    elif variant == 'secondary':
        return """
            QPushButton {
                background-color: #FFFFFF;
                color: #1A1918;
                border: 1px solid #E5E4E1;
                border-radius: 12px;
                padding: 10px 20px;
                font-size: 14px;
                font-weight: 500;
                font-family: 'Helvetica Neue', 'PingFang SC';
            }
            QPushButton:hover { background-color: #FAFAF8; border-color: #D1D0CD; }
            QPushButton:pressed { background-color: #F5F4F1; }
        """
    elif variant == 'danger':
        return """
            QPushButton {
                background-color: #D08068;
                color: white;
                border: none;
                border-radius: 12px;
                padding: 10px 20px;
                font-size: 14px;
                font-weight: 600;
                font-family: 'Helvetica Neue', 'PingFang SC';
            }
            QPushButton:hover { background-color: #B06048; }
            QPushButton:pressed { background-color: #904028; }
        """
    elif variant == 'ghost':
        return """
            QPushButton {
                background-color: transparent;
                color: #6D6C6A;
                border: none;
                border-radius: 8px;
                padding: 8px 16px;
                font-size: 14px;
                font-weight: 500;
                font-family: 'Helvetica Neue', 'PingFang SC';
            }
            QPushButton:hover { color: #D08068; background-color: #FAFAF8; }
        """
    return ""


def get_card_style():
    """Get card container style"""
    return """
        background-color: #FFFFFF;
        border-radius: 16px;
        border: 1px solid #E5E4E1;
    """


def apply_shadow(widget, radius=24, opacity=0.08, offset_y=4):
    """Apply shadow effect to widget (matches design file)"""
    shadow = QGraphicsDropShadowEffect()
    shadow.setBlurRadius(radius)
    shadow.setOffset(0, offset_y)
    shadow.setColor(QColor(26, 25, 24, int(255 * opacity)))
    widget.setGraphicsEffect(shadow)


def apply_card_shadow(widget):
    """Apply card shadow matching design file"""
    apply_shadow(widget, radius=24, opacity=0.08, offset_y=2)
