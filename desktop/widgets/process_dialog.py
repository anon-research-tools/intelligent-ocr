"""
Process Dialog - Based on Pencil Design File
Language selection grid with card-based layout
"""
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel,
    QPushButton, QFrame, QWidget
)
from PySide6.QtCore import Qt

from ..styles import COLORS, RADIUS, get_button_style


class LanguageCard(QFrame):
    """Language selection card"""
    
    def __init__(self, icon_text, label_text, lang_code, parent=None):
        super().__init__(parent)
        self.lang_code = lang_code
        self._selected = False
        self._setup_ui(icon_text, label_text)
        
    def _setup_ui(self, icon_text, label_text):
        self.setFixedHeight(80)
        self.setMinimumWidth(80)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        
        layout = QVBoxLayout(self)
        layout.setSpacing(4)
        layout.setContentsMargins(0, 14, 0, 14)
        layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
        
        self.icon_label = QLabel(icon_text)
        self.icon_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.icon_label.setStyleSheet(f"""
            font-size: 22px;
            font-weight: 700;
            font-family: 'Helvetica Neue', 'PingFang SC';
        """)
        
        self.text_label = QLabel(label_text)
        self.text_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.text_label.setStyleSheet(f"""
            font-size: 12px;
            font-weight: 500;
            font-family: 'Helvetica Neue', 'PingFang SC';
        """)
        
        layout.addWidget(self.icon_label)
        layout.addWidget(self.text_label)
        
        self.set_selected(False)
        
    def set_selected(self, selected):
        self._selected = selected
        if selected:
            self.setStyleSheet(f"""
                LanguageCard {{
                    background-color: {COLORS['accent_light']};
                    border: 2px solid {COLORS['accent_primary']};
                    border-radius: {RADIUS['md']}px;
                }}
                QLabel {{
                    border: none;
                    background: transparent;
                }}
            """)
            self.icon_label.setStyleSheet(f"""
                font-size: 22px;
                font-weight: 700;
                color: {COLORS['accent_primary']};
                font-family: 'Helvetica Neue', 'PingFang SC';
            """)
            self.text_label.setStyleSheet(f"""
                font-size: 12px;
                font-weight: 500;
                color: {COLORS['accent_primary']};
                font-family: 'Helvetica Neue', 'PingFang SC';
            """)
        else:
            self.setStyleSheet(f"""
                LanguageCard {{
                    background-color: {COLORS['bg_primary']};
                    border: 1px solid {COLORS['border_subtle']};
                    border-radius: {RADIUS['md']}px;
                }}
                QLabel {{
                    border: none;
                    background: transparent;
                }}
            """)
            self.icon_label.setStyleSheet(f"""
                font-size: 22px;
                font-weight: 700;
                color: {COLORS['text_secondary']};
                font-family: 'Helvetica Neue', 'PingFang SC';
            """)
            self.text_label.setStyleSheet(f"""
                font-size: 12px;
                font-weight: 500;
                color: {COLORS['text_secondary']};
                font-family: 'Helvetica Neue', 'PingFang SC';
            """)
    
    def is_selected(self):
        return self._selected
        
    def mousePressEvent(self, event):
        self.set_selected(not self._selected)


class ProcessDialog(QDialog):
    """Dialog to select language before starting OCR processing."""

    def __init__(self, file_count: int, parent=None):
        super().__init__(parent)
        self.setWindowTitle("开始处理")
        self.setModal(True)
        self.setFixedWidth(380)
        self._file_count = file_count
        self._setup_ui()
        self.adjustSize()

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 24, 24, 24)
        layout.setSpacing(20)

        # Header with title and close button
        header = QHBoxLayout()
        
        title = QLabel("开始处理")
        title.setStyleSheet(f"""
            font-size: 18px;
            font-weight: 600;
            color: {COLORS['text_primary']};
            font-family: 'Helvetica Neue', 'PingFang SC';
        """)
        
        close_btn = QPushButton("✕")
        close_btn.setFixedSize(28, 28)
        close_btn.setStyleSheet(f"""
            QPushButton {{
                background-color: {COLORS['bg_muted']};
                color: {COLORS['text_secondary']};
                border: none;
                border-radius: 14px;
                font-size: 12px;
                font-weight: 500;
            }}
            QPushButton:hover {{ background-color: {COLORS['border_subtle']}; }}
        """)
        close_btn.clicked.connect(self.reject)
        
        header.addWidget(title)
        header.addStretch()
        header.addWidget(close_btn)
        
        layout.addLayout(header)

        # File count info card
        info_card = QFrame()
        info_card.setStyleSheet(f"""
            QFrame {{
                background-color: {COLORS['accent_light']};
                border-radius: {RADIUS['md']}px;
                border: none;
            }}
        """)
        info_layout = QHBoxLayout(info_card)
        info_layout.setSpacing(8)
        info_layout.setContentsMargins(14, 10, 14, 10)
        
        file_icon = QLabel("📄")
        file_icon.setStyleSheet(f"font-size: 16px; color: {COLORS['accent_primary']};")
        
        file_text = QLabel(f"已选择 {self._file_count} 个文件待处理")
        file_text.setStyleSheet(f"""
            font-size: 13px;
            font-weight: 500;
            color: {COLORS['accent_primary']};
            font-family: 'Helvetica Neue', 'PingFang SC';
        """)
        
        info_layout.addWidget(file_icon)
        info_layout.addWidget(file_text)
        info_layout.addStretch()
        
        layout.addWidget(info_card)

        # Language section
        lang_section = QVBoxLayout()
        lang_section.setSpacing(12)

        lang_label = QLabel("识别语言")
        lang_label.setStyleSheet(f"""
            font-size: 14px;
            font-weight: 600;
            color: {COLORS['text_primary']};
            font-family: 'Helvetica Neue', 'PingFang SC';
        """)
        lang_section.addWidget(lang_label)

        # Language grid
        lang_grid = QHBoxLayout()
        lang_grid.setSpacing(10)
        
        self.lang_cards = {}
        
        # Chinese card (selected by default)
        cn_card = LanguageCard("中", "中文", "ch")
        cn_card.set_selected(True)
        lang_grid.addWidget(cn_card)
        self.lang_cards["ch"] = cn_card
        
        # English card
        en_card = LanguageCard("En", "英文", "en")
        lang_grid.addWidget(en_card)
        self.lang_cards["en"] = en_card
        
        # Japanese card
        jp_card = LanguageCard("日", "日文", "japan")
        lang_grid.addWidget(jp_card)
        self.lang_cards["japan"] = jp_card

        lang_section.addLayout(lang_grid)
        
        layout.addLayout(lang_section)
        
        layout.addStretch()

        # Buttons
        btn_row = QHBoxLayout()
        btn_row.setSpacing(10)

        cancel_btn = QPushButton("取消")
        cancel_btn.setFixedSize(90, 40)
        cancel_btn.clicked.connect(self.reject)
        cancel_btn.setStyleSheet(get_button_style('secondary'))

        start_btn = QPushButton("▶ 开始处理")
        start_btn.setFixedHeight(40)
        start_btn.setMinimumWidth(120)
        start_btn.clicked.connect(self.accept)
        start_btn.setStyleSheet(get_button_style('primary'))

        btn_row.addStretch()
        btn_row.addWidget(cancel_btn)
        btn_row.addWidget(start_btn)

        layout.addLayout(btn_row)

    def get_languages(self) -> list[str]:
        """Get selected languages."""
        languages = []
        for lang_code, card in self.lang_cards.items():
            if card.is_selected():
                languages.append(lang_code)
        return languages if languages else ['ch']
