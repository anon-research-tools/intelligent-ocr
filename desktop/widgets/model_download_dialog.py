"""
Model Download Dialog - Shows progress while downloading missing OCR models.

Appears when the user selects a quality mode whose models are not yet cached.
Download is done in a background QThread; a threading.Event on the OCRWorker
is set when download completes so the worker can continue processing.
"""
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QProgressBar, QPushButton,
)
from PySide6.QtCore import Qt, Signal, QThread

from ..styles import COLORS, get_button_style


# ---------------------------------------------------------------------------
# Background download thread
# ---------------------------------------------------------------------------

class _DownloadThread(QThread):
    """Runs PaddleOCR init in a background thread to trigger model download."""

    finished = Signal()
    failed = Signal(str)

    def __init__(self, model_names: list, parent=None):
        super().__init__(parent)
        self.model_names = model_names

    def run(self):
        try:
            import os
            os.environ['PADDLE_PDX_DISABLE_MODEL_SOURCE_CHECK'] = '1'
            from paddleocr import PaddleOCR

            # Dynamically detect det/rec models by suffix (works with any PaddleOCR version)
            det = next((m for m in self.model_names if '_det' in m), None)
            rec = next((m for m in self.model_names if '_rec' in m), None)

            kwargs = {
                'lang': 'ch',
                'use_doc_orientation_classify': False,
                'use_doc_unwarping': False,
                'use_textline_orientation': False,
            }
            if det:
                kwargs['text_detection_model_name'] = det
            if rec:
                kwargs['text_recognition_model_name'] = rec

            PaddleOCR(**kwargs)
            self.finished.emit()
        except Exception as exc:
            self.failed.emit(str(exc))


# ---------------------------------------------------------------------------
# Dialog
# ---------------------------------------------------------------------------

class ModelDownloadDialog(QDialog):
    """
    Modal dialog shown when OCR models need to be downloaded before processing.

    Signals:
        download_complete: emitted when all models have been downloaded.
        download_failed(str): emitted when download fails or is cancelled.
    """

    download_complete = Signal()
    download_failed = Signal(str)

    def __init__(self, missing_models: list, parent=None):
        super().__init__(parent)
        self.missing_models = missing_models
        self._download_thread: _DownloadThread | None = None
        self._cancelled = False
        self._setup_ui()
        self._start_download()

    # ------------------------------------------------------------------
    # UI setup
    # ------------------------------------------------------------------

    def _setup_ui(self):
        self.setWindowTitle("下载模型")
        self.setFixedWidth(420)
        self.setWindowModality(Qt.WindowModality.ApplicationModal)
        # Disable the native close button while downloading
        self.setWindowFlag(Qt.WindowType.WindowCloseButtonHint, False)

        layout = QVBoxLayout(self)
        layout.setSpacing(14)
        layout.setContentsMargins(24, 24, 24, 20)

        title = QLabel("正在下载 OCR 模型")
        title.setStyleSheet(f"""
            font-size: 15px;
            font-weight: 700;
            color: {COLORS['text_primary']};
            font-family: 'Helvetica Neue', 'PingFang SC';
        """)

        desc = QLabel(
            "首次使用此模式需要下载模型文件。\n"
            "下载完成后，以后无需重新下载，可完全离线使用。"
        )
        desc.setWordWrap(True)
        desc.setStyleSheet(f"""
            font-size: 13px;
            color: {COLORS['text_secondary']};
            font-family: 'Helvetica Neue', 'PingFang SC';
            line-height: 1.5;
        """)

        models_label = QLabel("需要下载: " + "、".join(self.missing_models))
        models_label.setWordWrap(True)
        models_label.setStyleSheet(f"""
            font-size: 11px;
            color: {COLORS['text_tertiary']};
            font-family: 'Helvetica Neue', monospace;
        """)

        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 0)  # indeterminate
        self.progress_bar.setFixedHeight(6)
        self.progress_bar.setTextVisible(False)
        self.progress_bar.setStyleSheet(f"""
            QProgressBar {{
                border: none;
                border-radius: 3px;
                background-color: {COLORS['bg_muted']};
            }}
            QProgressBar::chunk {{
                background-color: {COLORS['accent_primary']};
                border-radius: 3px;
            }}
        """)

        self.status_label = QLabel("正在下载模型，请耐心等待...")
        self.status_label.setStyleSheet(f"""
            font-size: 12px;
            color: {COLORS['text_secondary']};
            font-family: 'Helvetica Neue', 'PingFang SC';
        """)

        btn_row = QHBoxLayout()
        btn_row.addStretch()
        self.cancel_btn = QPushButton("取消")
        self.cancel_btn.setFixedHeight(32)
        self.cancel_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.cancel_btn.setStyleSheet(f"""
            QPushButton {{
                border: 1px solid {COLORS['border_subtle']};
                border-radius: 6px;
                padding: 6px 16px;
                color: #ff3b30;
                font-size: 13px;
                font-family: 'Helvetica Neue', 'PingFang SC';
            }}
            QPushButton:hover {{ background-color: #fff0ef; }}
        """)
        self.cancel_btn.clicked.connect(self._on_cancel)
        btn_row.addWidget(self.cancel_btn)

        layout.addWidget(title)
        layout.addWidget(desc)
        layout.addWidget(models_label)
        layout.addSpacing(4)
        layout.addWidget(self.progress_bar)
        layout.addWidget(self.status_label)
        layout.addLayout(btn_row)

    # ------------------------------------------------------------------
    # Download logic
    # ------------------------------------------------------------------

    def _start_download(self):
        self._download_thread = _DownloadThread(self.missing_models, self)
        self._download_thread.finished.connect(self._on_download_finished)
        self._download_thread.failed.connect(self._on_download_failed)
        self._download_thread.start()

    def _on_download_finished(self):
        if self._cancelled:
            return
        self.progress_bar.setRange(0, 1)
        self.progress_bar.setValue(1)
        self.status_label.setText("下载完成！")
        self.download_complete.emit()
        self.accept()

    def _on_download_failed(self, error: str):
        if self._cancelled:
            return
        self.progress_bar.setRange(0, 1)
        self.progress_bar.setValue(0)
        self.status_label.setText(f"下载失败: {error}")
        # Switch cancel button to a neutral close button
        self.cancel_btn.setText("关闭")
        self.cancel_btn.setStyleSheet(f"""
            QPushButton {{
                border: 1px solid {COLORS['border_subtle']};
                border-radius: 6px;
                padding: 6px 16px;
                color: {COLORS['text_primary']};
                font-size: 13px;
                font-family: 'Helvetica Neue', 'PingFang SC';
            }}
            QPushButton:hover {{ background-color: {COLORS['bg_muted']}; }}
        """)
        self.cancel_btn.clicked.disconnect()
        self.cancel_btn.clicked.connect(self._on_error_close)
        self.download_failed.emit(error)

    def _on_cancel(self):
        self._cancelled = True
        if self._download_thread and self._download_thread.isRunning():
            self._download_thread.terminate()
            self._download_thread.wait(3000)
        self.download_failed.emit("用户取消下载")
        self.reject()

    def _on_error_close(self):
        self.reject()

    def closeEvent(self, event):
        # Prevent accidental closure via Alt+F4 / Cmd+W while downloading
        if self._download_thread and self._download_thread.isRunning() and not self._cancelled:
            event.ignore()
        else:
            event.accept()
