"""
Drop Zone Widget - Based on Pencil Design File
Modern upload area with icon circle and dual buttons
"""
from pathlib import Path
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QFileDialog
)
from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QDragEnterEvent, QDropEvent

from ..styles import COLORS, RADIUS


class DropZone(QWidget):
    """
    A drag-and-drop area for adding PDF files.
    Matches the design file with icon circle and dual buttons.
    """

    files_dropped = Signal(list)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAcceptDrops(True)
        self._is_hover = False
        self._setup_ui()

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 24, 24, 24)
        layout.setSpacing(12)

        # Spacer top
        layout.addStretch(1)

        # Icon circle - matching design file
        icon_container = QWidget()
        icon_container.setFixedSize(48, 48)
        icon_container.setStyleSheet(f"""
            background-color: {COLORS['bg_muted']};
            border-radius: 24px;
        """)
        
        icon_layout = QVBoxLayout(icon_container)
        icon_layout.setContentsMargins(0, 0, 0, 0)
        
        self.icon_label = QLabel("⇧")
        self.icon_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.icon_label.setStyleSheet(f"""
            font-size: 20px;
            font-weight: 600;
            color: {COLORS['accent_primary']};
            background: transparent;
        """)
        icon_layout.addWidget(self.icon_label)
        
        layout.addWidget(icon_container, 0, Qt.AlignmentFlag.AlignCenter)

        # Main text - minimal Apple style
        self.text_label = QLabel("拖入 PDF")
        self.text_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.text_label.setStyleSheet(f"""
            font-size: 14px;
            font-weight: 500;
            color: {COLORS['text_secondary']};
            font-family: 'Helvetica Neue', 'PingFang SC';
        """)
        layout.addWidget(self.text_label)

        # Spacing
        layout.addSpacing(12)

        # Button container - Primary + Secondary
        btn_layout = QHBoxLayout()
        btn_layout.setSpacing(10)
        btn_layout.addStretch()

        # Primary button - Select files
        self.browse_files_btn = QPushButton("选择文件")
        self.browse_files_btn.setFixedSize(90, 36)
        self.browse_files_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.browse_files_btn.clicked.connect(self._on_browse_files)
        self.browse_files_btn.setStyleSheet(f"""
            QPushButton {{
                background-color: {COLORS['accent_primary']};
                color: white;
                border: none;
                border-radius: {RADIUS['md']}px;
                font-size: 13px;
                font-weight: 600;
                font-family: 'Helvetica Neue', 'PingFang SC';
            }}
            QPushButton:hover {{ background-color: {COLORS['accent_hover']}; }}
        """)
        btn_layout.addWidget(self.browse_files_btn)

        # Secondary button - Select folder
        self.browse_folder_btn = QPushButton("选择文件夹")
        self.browse_folder_btn.setFixedSize(90, 36)
        self.browse_folder_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.browse_folder_btn.clicked.connect(self._on_browse_folder)
        self.browse_folder_btn.setStyleSheet(f"""
            QPushButton {{
                background-color: {COLORS['bg_surface']};
                color: {COLORS['text_secondary']};
                border: 1px solid {COLORS['border_subtle']};
                border-radius: {RADIUS['md']}px;
                font-size: 13px;
                font-weight: 500;
                font-family: 'Helvetica Neue', 'PingFang SC';
            }}
            QPushButton:hover {{ 
                background-color: {COLORS['bg_elevated']};
                border-color: {COLORS['border_strong']};
            }}
        """)
        btn_layout.addWidget(self.browse_folder_btn)
        btn_layout.addStretch()

        layout.addLayout(btn_layout)

        # Spacer bottom
        layout.addStretch(1)

        self._update_style()

    def _update_style(self):
        if self._is_hover:
            self.setStyleSheet(f"""
                DropZone {{
                    background-color: {COLORS['accent_light']}40;
                    border: 2px dashed {COLORS['accent_primary']};
                    border-radius: {RADIUS['lg']}px;
                }}
            """)
        else:
            self.setStyleSheet(f"""
                DropZone {{
                    background-color: {COLORS['bg_surface']};
                    border: 2px dashed {COLORS['border_subtle']};
                    border-radius: {RADIUS['lg']}px;
                }}
            """)

    def dragEnterEvent(self, event: QDragEnterEvent):
        if event.mimeData().hasUrls():
            for url in event.mimeData().urls():
                path = Path(url.toLocalFile())
                if path.suffix.lower() == '.pdf' or path.is_dir():
                    event.acceptProposedAction()
                    self._is_hover = True
                    self._update_style()
                    return
        event.ignore()

    def dragLeaveEvent(self, event):
        self._is_hover = False
        self._update_style()

    def dropEvent(self, event: QDropEvent):
        self._is_hover = False
        self._update_style()

        paths = []
        for url in event.mimeData().urls():
            path = Path(url.toLocalFile())
            if path.is_dir():
                paths.extend(str(p) for p in path.rglob("*.pdf"))
                paths.extend(str(p) for p in path.rglob("*.PDF"))
            elif path.suffix.lower() == '.pdf':
                paths.append(str(path))

        if paths:
            self.files_dropped.emit(paths)
            event.acceptProposedAction()
        else:
            event.ignore()

    def _on_browse_files(self):
        """Open file dialog to select PDF files"""
        files, _ = QFileDialog.getOpenFileNames(
            self, "选择 PDF 文件", "",
            "PDF 文件 (*.pdf);;所有文件 (*.*)"
        )
        if files:
            self.files_dropped.emit(files)

    def _on_browse_folder(self):
        """Open folder dialog to select a folder"""
        folder = QFileDialog.getExistingDirectory(self, "选择文件夹")
        if folder:
            folder_path = Path(folder)
            pdf_files = list(folder_path.rglob("*.pdf")) + list(folder_path.rglob("*.PDF"))
            if pdf_files:
                self.files_dropped.emit([str(f) for f in pdf_files])

    def mouseDoubleClickEvent(self, event):
        self._on_browse_files()
