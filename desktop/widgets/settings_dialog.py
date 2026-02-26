"""
Settings Dialog - Based on Pencil Design File
Card-based layout with DPI selector and toggle switches
"""
import threading

from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel,
    QPushButton, QLineEdit, QFileDialog, QFrame,
    QWidget, QComboBox, QScrollArea, QApplication
)
from PySide6.QtCore import Qt, QSettings, Signal

from ..styles import COLORS, RADIUS, get_button_style


class ToggleSwitch(QWidget):
    """Custom toggle switch widget with animated knob"""

    def __init__(self, checked=True, parent=None):
        super().__init__(parent)
        self._checked = checked
        self.setFixedSize(44, 24)
        self.setCursor(Qt.CursorShape.PointingHandCursor)

    def paintEvent(self, event):
        from PySide6.QtGui import QPainter, QColor, QPen
        from PySide6.QtCore import QRectF

        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        # Track
        track_color = QColor(COLORS['accent_primary']) if self._checked else QColor(COLORS['bg_muted'])
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(track_color)
        painter.drawRoundedRect(QRectF(0, 0, 44, 24), 12, 12)

        # Knob (white circle)
        painter.setBrush(QColor("#FFFFFF"))
        knob_x = 22.0 if self._checked else 2.0
        painter.drawEllipse(QRectF(knob_x, 2, 20, 20))

        painter.end()

    def mousePressEvent(self, event):
        self._checked = not self._checked
        self.update()

    def isChecked(self):
        return self._checked

    def setChecked(self, checked):
        self._checked = checked
        self.update()


class SettingsDialog(QDialog):
    """Modal settings dialog matching the design file."""
    hardware_status_ready = Signal(str, str, str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("设置")
        self.setModal(True)
        self.setFixedWidth(460)
        self.hardware_status_ready.connect(self._apply_hardware_status)
        self._setup_ui()
        self._load_settings()
        self._adjust_height()

    def _create_card(self):
        """Create a card container"""
        card = QFrame()
        card.setStyleSheet(f"""
            QFrame {{
                background-color: {COLORS['bg_primary']};
                border-radius: {RADIUS['md']}px;
                border: none;
            }}
        """)
        return card

    def _create_row(self, label_text, widget):
        """Create a settings row with label and widget"""
        row = QHBoxLayout()
        row.setSpacing(12)
        row.setContentsMargins(12, 12, 12, 12)
        
        label = QLabel(label_text)
        label.setStyleSheet(f"""
            font-size: 13px;
            font-weight: 500;
            color: {COLORS['text_primary']};
            font-family: 'Helvetica Neue', 'PingFang SC';
        """)
        
        row.addWidget(label)
        row.addStretch()
        row.addWidget(widget)
        
        return row

    def _adjust_height(self):
        """Fit dialog height to screen, enabling scroll if content is taller."""
        screen = QApplication.primaryScreen()
        if screen:
            available = screen.availableGeometry()
            max_h = available.height() - 80  # leave some margin
        else:
            max_h = 700

        self.adjustSize()
        if self.height() > max_h:
            self.setFixedHeight(max_h)

    def _setup_ui(self):
        # Outer layout: header (fixed) + scroll area + buttons (fixed)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(24, 24, 24, 24)
        outer.setSpacing(0)

        # ── Header (always visible, not scrollable) ──────────────────────
        header = QHBoxLayout()
        header.setContentsMargins(0, 0, 0, 16)

        title = QLabel("设置")
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
        outer.addLayout(header)

        # ── Scroll area wrapping all settings sections ────────────────────
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.setStyleSheet("QScrollArea { border: none; background: transparent; }")

        scroll_content = QWidget()
        scroll_content.setStyleSheet("background: transparent;")
        layout = QVBoxLayout(scroll_content)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(20)

        scroll.setWidget(scroll_content)
        outer.addWidget(scroll, 1)  # stretch = 1 so it fills remaining space

        # ============ Output Section ============
        output_section = QVBoxLayout()
        output_section.setSpacing(12)

        section_title = QLabel("输出设置")
        section_title.setStyleSheet(f"""
            font-size: 14px;
            font-weight: 600;
            color: {COLORS['text_primary']};
            font-family: 'Helvetica Neue', 'PingFang SC';
        """)
        output_section.addWidget(section_title)

        # Output directory card
        output_card = self._create_card()
        output_layout = QVBoxLayout(output_card)
        output_layout.setSpacing(0)
        output_layout.setContentsMargins(0, 0, 0, 0)

        # Output dir row
        self.output_dir_value = QLabel("与源文件相同")
        self.output_dir_value.setStyleSheet(f"""
            font-size: 13px;
            color: {COLORS['text_tertiary']};
            font-family: 'Helvetica Neue', 'PingFang SC';
        """)
        
        output_dir_widget = QWidget()
        output_dir_layout = QHBoxLayout(output_dir_widget)
        output_dir_layout.setSpacing(4)
        output_dir_layout.setContentsMargins(0, 0, 0, 0)
        output_dir_layout.addWidget(self.output_dir_value)
        chevron = QLabel("›")
        chevron.setStyleSheet(f"color: {COLORS['text_tertiary']}; font-size: 14px;")
        output_dir_layout.addWidget(chevron)
        
        output_dir_widget.setCursor(Qt.CursorShape.PointingHandCursor)
        output_dir_widget.mousePressEvent = lambda e: self._browse_dir()

        output_dir_row = self._create_row("输出目录", output_dir_widget)
        output_layout.addLayout(output_dir_row)

        # Separator
        separator = QFrame()
        separator.setFixedHeight(1)
        separator.setStyleSheet(f"background-color: {COLORS['border_subtle']};")
        output_layout.addWidget(separator)

        # Suffix row
        self.suffix_edit = QLineEdit("_ocr")
        self.suffix_edit.setFixedWidth(80)
        self.suffix_edit.setStyleSheet(f"""
            QLineEdit {{
                background: {COLORS['bg_surface']};
                border: 1px solid {COLORS['border_subtle']};
                border-radius: 6px;
                padding: 4px 8px;
                font-size: 13px;
                color: {COLORS['text_primary']};
            }}
        """)
        
        suffix_row = self._create_row("文件后缀", self.suffix_edit)
        output_layout.addLayout(suffix_row)

        # Separator
        output_separator = QFrame()
        output_separator.setFixedHeight(1)
        output_separator.setStyleSheet(f"background-color: {COLORS['border_subtle']};")
        output_layout.addWidget(output_separator)

        self.image_mode_combo = QComboBox()
        self.image_mode_combo.addItem("标准压缩 (推荐，速度快，体积小)", "lossy_85")
        self.image_mode_combo.addItem("无损画质 (体积大，写入较慢)", "lossless")
        self.image_mode_combo.setFixedWidth(280)
        self.image_mode_combo.setStyleSheet(f"""
            QComboBox {{
                background: {COLORS['bg_surface']};
                border: 1px solid {COLORS['border_subtle']};
                border-radius: 6px;
                padding: 6px 10px;
                font-size: 13px;
                color: {COLORS['text_primary']};
                font-family: 'Helvetica Neue', 'PingFang SC';
            }}
            QComboBox:hover {{
                border-color: {COLORS['accent_primary']};
            }}
            QComboBox::drop-down {{
                border: none;
                width: 20px;
            }}
            QComboBox::down-arrow {{
                image: none;
                border-left: 4px solid transparent;
                border-right: 4px solid transparent;
                border-top: 5px solid {COLORS['text_tertiary']};
                margin-right: 8px;
            }}
            QComboBox QAbstractItemView {{
                background: {COLORS['bg_primary']};
                border: 1px solid {COLORS['border_subtle']};
                border-radius: 6px;
                selection-background-color: {COLORS['accent_primary']};
                selection-color: white;
                padding: 4px;
            }}
        """)

        image_mode_row = self._create_row("输出图像", self.image_mode_combo)
        output_layout.addLayout(image_mode_row)

        output_section.addWidget(output_card)
        layout.addLayout(output_section)

        # ============ Quality Section ============
        quality_section = QVBoxLayout()
        quality_section.setSpacing(12)

        quality_title = QLabel("识别质量")
        quality_title.setStyleSheet(f"""
            font-size: 14px;
            font-weight: 600;
            color: {COLORS['text_primary']};
            font-family: 'Helvetica Neue', 'PingFang SC';
        """)
        quality_section.addWidget(quality_title)

        # DPI selector card
        dpi_card = self._create_card()
        dpi_layout = QHBoxLayout(dpi_card)
        dpi_layout.setSpacing(4)
        dpi_layout.setContentsMargins(4, 4, 4, 4)

        self.dpi_buttons = {}
        dpi_values = ["150", "200", "300", "400"]
        
        for i, dpi in enumerate(dpi_values):
            btn = QPushButton(dpi)
            btn.setCheckable(True)
            btn.setFixedHeight(36)
            btn.setProperty("dpi", dpi)
            btn.clicked.connect(self._on_dpi_clicked)
            dpi_layout.addWidget(btn)
            self.dpi_buttons[dpi] = btn

        # Set default
        self.dpi_buttons["300"].setChecked(True)
        self._update_dpi_styles()

        quality_section.addWidget(dpi_card)
        layout.addLayout(quality_section)

        # Initialize toggles dict
        self.toggles = {}

        # ============ Export Formats Section ============
        export_section = QVBoxLayout()
        export_section.setSpacing(12)

        export_title = QLabel("额外输出格式")
        export_title.setStyleSheet(f"""
            font-size: 14px;
            font-weight: 600;
            color: {COLORS['text_primary']};
            font-family: 'Helvetica Neue', 'PingFang SC';
        """)
        export_section.addWidget(export_title)

        # Export formats card
        export_card = self._create_card()
        export_layout = QVBoxLayout(export_card)
        export_layout.setSpacing(0)
        export_layout.setContentsMargins(0, 0, 0, 0)

        # Export format toggles
        export_toggles = [
            ("export_txt_toggle", "纯文本 (.txt)", False),
            ("export_md_toggle", "Markdown (.md)", False),
            ("export_md_images_toggle", "Markdown + 图片 (.md)", False),
        ]

        for i, (name, label, default) in enumerate(export_toggles):
            if i > 0:
                sep = QFrame()
                sep.setFixedHeight(1)
                sep.setStyleSheet(f"background-color: {COLORS['border_subtle']};")
                export_layout.addWidget(sep)

            toggle_widget = QWidget()
            toggle_layout = QHBoxLayout(toggle_widget)
            toggle_layout.setSpacing(12)
            toggle_layout.setContentsMargins(12, 12, 12, 12)

            label_widget = QLabel(label)
            label_widget.setStyleSheet(f"""
                font-size: 13px;
                font-weight: 500;
                color: {COLORS['text_primary']};
                font-family: 'Helvetica Neue', 'PingFang SC';
            """)

            toggle = ToggleSwitch(checked=default)
            self.toggles[name] = toggle

            toggle_layout.addWidget(label_widget)
            toggle_layout.addStretch()
            toggle_layout.addWidget(toggle)

            export_layout.addWidget(toggle_widget)

        export_section.addWidget(export_card)
        layout.addLayout(export_section)

        # ============ Performance Settings Section ============
        perf_section = QVBoxLayout()
        perf_section.setSpacing(12)

        perf_title = QLabel("性能设置")
        perf_title.setStyleSheet(f"""
            font-size: 14px;
            font-weight: 600;
            color: {COLORS['text_primary']};
            font-family: 'Helvetica Neue', 'PingFang SC';
        """)
        perf_section.addWidget(perf_title)

        # Performance settings card
        perf_card = self._create_card()
        perf_layout = QVBoxLayout(perf_card)
        perf_layout.setSpacing(0)
        perf_layout.setContentsMargins(0, 0, 0, 0)

        # Quality mode combo box (only fast and balanced; high removed for stability)
        self.quality_combo = QComboBox()
        self.quality_combo.addItem("快速 (Fast) - 推荐，速度快，适合大批量", "fast")
        self.quality_combo.addItem("平衡 (Balanced) - 兼顾速度和准确率", "balanced")
        self.quality_combo.setCurrentIndex(0)  # Default: fast
        self.quality_combo.setFixedWidth(280)
        self.quality_combo.setStyleSheet(f"""
            QComboBox {{
                background: {COLORS['bg_surface']};
                border: 1px solid {COLORS['border_subtle']};
                border-radius: 6px;
                padding: 6px 10px;
                font-size: 13px;
                color: {COLORS['text_primary']};
                font-family: 'Helvetica Neue', 'PingFang SC';
            }}
            QComboBox:hover {{
                border-color: {COLORS['accent_primary']};
            }}
            QComboBox::drop-down {{
                border: none;
                width: 20px;
            }}
            QComboBox::down-arrow {{
                image: none;
                border-left: 4px solid transparent;
                border-right: 4px solid transparent;
                border-top: 5px solid {COLORS['text_tertiary']};
                margin-right: 8px;
            }}
            QComboBox QAbstractItemView {{
                background: {COLORS['bg_primary']};
                border: 1px solid {COLORS['border_subtle']};
                border-radius: 6px;
                selection-background-color: {COLORS['accent_primary']};
                selection-color: white;
                padding: 4px;
            }}
        """)

        quality_row = self._create_row("识别质量", self.quality_combo)
        perf_layout.addLayout(quality_row)

        # Separator
        sep_perf = QFrame()
        sep_perf.setFixedHeight(1)
        sep_perf.setStyleSheet(f"background-color: {COLORS['border_subtle']};")
        perf_layout.addWidget(sep_perf)

        # Variant character normalization toggle
        variants_widget = QWidget()
        variants_layout = QHBoxLayout(variants_widget)
        variants_layout.setSpacing(12)
        variants_layout.setContentsMargins(12, 12, 12, 12)

        variants_label = QLabel('异体字归并（搜\u201c藏\u201d也能找到\u201c蔵\u201d）')
        variants_label.setStyleSheet(f"""
            font-size: 13px;
            font-weight: 500;
            color: {COLORS['text_primary']};
            font-family: 'Helvetica Neue', 'PingFang SC';
        """)

        self.toggles["variants_toggle"] = ToggleSwitch(checked=True)

        variants_layout.addWidget(variants_label)
        variants_layout.addStretch()
        variants_layout.addWidget(self.toggles["variants_toggle"])

        perf_layout.addWidget(variants_widget)

        perf_section.addWidget(perf_card)
        layout.addLayout(perf_section)

        # ============ Hardware Acceleration Section ============
        hw_section = QVBoxLayout()
        hw_section.setSpacing(12)

        hw_title = QLabel("硬件加速")
        hw_title.setStyleSheet(f"""
            font-size: 14px;
            font-weight: 600;
            color: {COLORS['text_primary']};
            font-family: 'Helvetica Neue', 'PingFang SC';
        """)
        hw_section.addWidget(hw_title)

        hw_card = self._create_card()
        hw_layout = QVBoxLayout(hw_card)
        hw_layout.setSpacing(0)
        hw_layout.setContentsMargins(0, 0, 0, 0)

        # Hardware status label (populated at load time)
        self.hw_status_label = QLabel("检测中…")
        self.hw_status_label.setStyleSheet(f"""
            font-size: 13px;
            color: {COLORS['text_secondary']};
            font-family: 'Helvetica Neue', 'PingFang SC';
        """)
        hw_status_row = self._create_row("当前硬件", self.hw_status_label)
        hw_layout.addLayout(hw_status_row)

        # Separator
        sep_hw = QFrame()
        sep_hw.setFixedHeight(1)
        sep_hw.setStyleSheet(f"background-color: {COLORS['border_subtle']};")
        hw_layout.addWidget(sep_hw)

        # GPU override combo box
        self.gpu_combo = QComboBox()
        self.gpu_combo.addItem("自动检测 (推荐)", "auto")
        self.gpu_combo.addItem("强制 CPU", "cpu")
        self.gpu_combo.addItem("强制 GPU", "gpu")
        self.gpu_combo.setCurrentIndex(0)
        self.gpu_combo.setFixedWidth(200)
        self.gpu_combo.setStyleSheet(f"""
            QComboBox {{
                background: {COLORS['bg_surface']};
                border: 1px solid {COLORS['border_subtle']};
                border-radius: 6px;
                padding: 6px 10px;
                font-size: 13px;
                color: {COLORS['text_primary']};
                font-family: 'Helvetica Neue', 'PingFang SC';
            }}
            QComboBox:hover {{
                border-color: {COLORS['accent_primary']};
            }}
            QComboBox::drop-down {{
                border: none;
                width: 20px;
            }}
            QComboBox::down-arrow {{
                image: none;
                border-left: 4px solid transparent;
                border-right: 4px solid transparent;
                border-top: 5px solid {COLORS['text_tertiary']};
                margin-right: 8px;
            }}
            QComboBox QAbstractItemView {{
                background: {COLORS['bg_primary']};
                border: 1px solid {COLORS['border_subtle']};
                border-radius: 6px;
                selection-background-color: {COLORS['accent_primary']};
                selection-color: white;
                padding: 4px;
            }}
        """)
        gpu_row = self._create_row("计算设备", self.gpu_combo)
        hw_layout.addLayout(gpu_row)
        # Warning label (shown only when hardware has warnings)
        self.hw_warning_label = QLabel("")
        self.hw_warning_label.setWordWrap(True)
        self.hw_warning_label.setStyleSheet(f"""
            font-size: 12px;
            color: #B8860B;
            padding: 8px 12px;
            font-family: 'Helvetica Neue', 'PingFang SC';
        """)
        self.hw_warning_label.setVisible(False)
        hw_layout.addWidget(self.hw_warning_label)

        hw_section.addWidget(hw_card)
        layout.addLayout(hw_section)

        # ============ Options Section ============
        options_section = QVBoxLayout()
        options_section.setSpacing(12)

        options_title = QLabel("选项")
        options_title.setStyleSheet(f"""
            font-size: 14px;
            font-weight: 600;
            color: {COLORS['text_primary']};
            font-family: 'Helvetica Neue', 'PingFang SC';
        """)
        options_section.addWidget(options_title)

        # Options card
        options_card = self._create_card()
        options_layout = QVBoxLayout(options_card)
        options_layout.setSpacing(0)
        options_layout.setContentsMargins(0, 0, 0, 0)

        # Toggle rows
        toggles = [
            ("skip_text_toggle", "跳过已有文字的页面", True),
            ("auto_open_toggle", "完成后自动打开文件", False),
            ("sound_toggle", "完成后播放提示音", True),
        ]

        for i, (name, label, default) in enumerate(toggles):
            if i > 0:
                sep = QFrame()
                sep.setFixedHeight(1)
                sep.setStyleSheet(f"background-color: {COLORS['border_subtle']};")
                options_layout.addWidget(sep)
            
            toggle_widget = QWidget()
            toggle_layout = QHBoxLayout(toggle_widget)
            toggle_layout.setSpacing(12)
            toggle_layout.setContentsMargins(12, 12, 12, 12)
            
            label_widget = QLabel(label)
            label_widget.setStyleSheet(f"""
                font-size: 13px;
                font-weight: 500;
                color: {COLORS['text_primary']};
                font-family: 'Helvetica Neue', 'PingFang SC';
            """)
            
            toggle = ToggleSwitch(checked=default)
            self.toggles[name] = toggle
            
            toggle_layout.addWidget(label_widget)
            toggle_layout.addStretch()
            toggle_layout.addWidget(toggle)
            
            options_layout.addWidget(toggle_widget)

        options_section.addWidget(options_card)
        layout.addLayout(options_section)

        layout.addStretch()

        # ── Buttons (always visible at bottom, not scrollable) ────────────
        btn_separator = QFrame()
        btn_separator.setFixedHeight(1)
        btn_separator.setStyleSheet(f"background-color: {COLORS['border_subtle']};")
        outer.addWidget(btn_separator)

        btn_row = QHBoxLayout()
        btn_row.setSpacing(10)
        btn_row.setContentsMargins(0, 12, 0, 0)

        cancel_btn = QPushButton("取消")
        cancel_btn.setFixedSize(90, 40)
        cancel_btn.clicked.connect(self.reject)
        cancel_btn.setStyleSheet(get_button_style('secondary'))

        save_btn = QPushButton("保存")
        save_btn.setFixedSize(90, 40)
        save_btn.clicked.connect(self._save_and_close)
        save_btn.setStyleSheet(get_button_style('primary'))

        btn_row.addStretch()
        btn_row.addWidget(cancel_btn)
        btn_row.addWidget(save_btn)

        outer.addLayout(btn_row)

    def _apply_hardware_status(self, status: str, color: str, warning_text: str):
        """Apply hardware status from background detection."""
        self.hw_status_label.setText(status)
        self.hw_status_label.setStyleSheet(f"""
            font-size: 13px;
            color: {color};
            font-family: 'Helvetica Neue', 'PingFang SC';
        """)
        if warning_text:
            self.hw_warning_label.setText(warning_text)
            self.hw_warning_label.setVisible(True)
        else:
            self.hw_warning_label.setVisible(False)

    def _refresh_hardware_status(self):
        """Populate hardware status label from core.hardware in background."""
        self.hw_status_label.setText("检测中…")

        def _worker():
            status = "CPU 模式"
            color = COLORS['text_secondary']
            warning_text = ""
            try:
                import platform
                from core.hardware import detect_hardware
                info = detect_hardware()

                if info.recommended_backend == "cuda":
                    status = f"NVIDIA GPU (CUDA {info.cuda_version}, {info.cuda_gpu_count} 卡)"
                    color = "#2E7D32"
                elif info.recommended_backend == "rocm":
                    status = "AMD GPU (ROCm)"
                    color = "#2E7D32"
                elif platform.system() == "Darwin":
                    status = "Apple CPU (macOS 不支持 GPU 加速)"

                if info.warnings:
                    warning_text = "\n".join(info.warnings)
            except Exception as e:
                status = f"检测失败: {e}"
            self.hardware_status_ready.emit(status, color, warning_text)

        threading.Thread(target=_worker, daemon=True).start()


    def _on_dpi_clicked(self):
        """Handle DPI button click"""
        sender = self.sender()
        dpi = sender.property("dpi")
        
        # Uncheck all
        for btn in self.dpi_buttons.values():
            btn.setChecked(False)
        
        # Check selected
        self.dpi_buttons[dpi].setChecked(True)
        self._update_dpi_styles()

    def _update_dpi_styles(self):
        """Update DPI button styles based on selection"""
        for dpi, btn in self.dpi_buttons.items():
            if btn.isChecked():
                btn.setStyleSheet(f"""
                    QPushButton {{
                        background-color: {COLORS['bg_surface']};
                        color: {COLORS['text_primary']};
                        border: none;
                        border-radius: {RADIUS['sm']}px;
                        padding: 8px;
                        font-size: 13px;
                        font-weight: 600;
                        font-family: 'Helvetica Neue', 'PingFang SC';
                    }}
                """)
            else:
                btn.setStyleSheet(f"""
                    QPushButton {{
                        background-color: transparent;
                        color: {COLORS['text_tertiary']};
                        border: none;
                        border-radius: {RADIUS['sm']}px;
                        padding: 8px;
                        font-size: 13px;
                        font-weight: 500;
                        font-family: 'Helvetica Neue', 'PingFang SC';
                    }}
                    QPushButton:hover {{
                        background-color: {COLORS['bg_muted']};
                    }}
                """)

    def _browse_dir(self):
        folder = QFileDialog.getExistingDirectory(self, "选择输出目录")
        if folder:
            self.output_dir_value.setText(folder)
            self.output_dir_value.setStyleSheet(f"""
                font-size: 13px;
                color: {COLORS['text_primary']};
                font-family: 'Helvetica Neue', 'PingFang SC';
            """)

    def _save_and_close(self):
        self._save_settings()
        self.accept()

    def _save_settings(self):
        settings = QSettings("SmartOCR", "OCRTool")

        # Find selected DPI
        selected_dpi = "300"
        for dpi, btn in self.dpi_buttons.items():
            if btn.isChecked():
                selected_dpi = dpi
                break

        output_dir = self.output_dir_value.text()
        if output_dir and output_dir != "与源文件相同":
            settings.setValue("output/use_custom", True)
            settings.setValue("output/custom_path", output_dir)
        else:
            settings.setValue("output/use_custom", False)
            settings.setValue("output/custom_path", "")

        settings.setValue("output/suffix", self.suffix_edit.text())
        settings.setValue("quality/dpi", selected_dpi)
        settings.setValue("options/skip_existing_text", self.toggles["skip_text_toggle"].isChecked())
        settings.setValue("options/auto_open", self.toggles["auto_open_toggle"].isChecked())
        settings.setValue("options/play_sound", self.toggles["sound_toggle"].isChecked())

        # Export format settings
        settings.setValue("export/txt", self.toggles["export_txt_toggle"].isChecked())
        settings.setValue("export/md", self.toggles["export_md_toggle"].isChecked())
        settings.setValue("export/md_images", self.toggles["export_md_images_toggle"].isChecked())

        # Performance settings
        settings.setValue("performance/quality", self.quality_combo.currentData())
        settings.setValue("performance/num_workers", 1)  # Fixed single-process for stability
        settings.setValue("performance/gpu_override", self.gpu_combo.currentData())

        # Variant character normalization
        settings.setValue("ocr/enable_variants", self.toggles["variants_toggle"].isChecked())
        settings.setValue("output/image_mode", self.image_mode_combo.currentData())
        settings.setValue("performance/auto_retry_enabled", True)
        settings.setValue("performance/max_retries", 2)
        settings.setValue("batch/group_by_language", True)
        settings.setValue("reliability/page_retry_limit", 2)
        settings.setValue("reliability/allow_fallback_copy", True)
        settings.setValue("reliability/show_fallback_detail", True)

        # Clear hardware cache so next OCR run re-evaluates the device
        try:
            from core.hardware import clear_cache
            clear_cache()
        except Exception:
            pass

    def _load_settings(self):
        settings = QSettings("SmartOCR", "OCRTool")

        self.suffix_edit.setText(settings.value("output/suffix", "_ocr"))

        # Load output dir
        if settings.value("output/use_custom", False, type=bool):
            custom_path = settings.value("output/custom_path", "")
            if custom_path:
                self.output_dir_value.setText(custom_path)
                self.output_dir_value.setStyleSheet(f"""
                    font-size: 13px;
                    color: {COLORS['text_primary']};
                    font-family: 'Helvetica Neue', 'PingFang SC';
                """)
        image_mode = settings.value("output/image_mode", "lossy_85")
        for i in range(self.image_mode_combo.count()):
            if self.image_mode_combo.itemData(i) == image_mode:
                self.image_mode_combo.setCurrentIndex(i)
                break

        # Load DPI
        dpi = settings.value("quality/dpi", "300")
        if dpi in self.dpi_buttons:
            for btn in self.dpi_buttons.values():
                btn.setChecked(False)
            self.dpi_buttons[dpi].setChecked(True)
            self._update_dpi_styles()

        self.toggles["skip_text_toggle"].setChecked(
            settings.value("options/skip_existing_text", True, type=bool)
        )
        self.toggles["auto_open_toggle"].setChecked(
            settings.value("options/auto_open", False, type=bool)
        )
        self.toggles["sound_toggle"].setChecked(
            settings.value("options/play_sound", True, type=bool)
        )

        # Load export format settings
        self.toggles["export_txt_toggle"].setChecked(
            settings.value("export/txt", False, type=bool)
        )
        self.toggles["export_md_toggle"].setChecked(
            settings.value("export/md", False, type=bool)
        )
        self.toggles["export_md_images_toggle"].setChecked(
            settings.value("export/md_images", False, type=bool)
        )

        # Load performance settings (map removed "high" to "balanced")
        quality = settings.value("performance/quality", "fast")
        if quality == "high":
            quality = "balanced"
        for i in range(self.quality_combo.count()):
            if self.quality_combo.itemData(i) == quality:
                self.quality_combo.setCurrentIndex(i)
                break

        # Load variant character toggle
        self.toggles["variants_toggle"].setChecked(
            settings.value("ocr/enable_variants", True, type=bool)
        )

        # Load GPU override
        gpu_override = settings.value("performance/gpu_override", "auto")
        for i in range(self.gpu_combo.count()):
            if self.gpu_combo.itemData(i) == gpu_override:
                self.gpu_combo.setCurrentIndex(i)
                break

        # Populate hardware status (best-effort, don't block UI if paddle not installed)
        self._refresh_hardware_status()
