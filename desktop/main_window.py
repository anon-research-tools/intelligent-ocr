"""
Main Window - Based on Pencil Design File
Nature-inspired design with green accent color
"""
import os
import re
import subprocess
import sys
from pathlib import Path
from datetime import datetime

from PySide6.QtWidgets import (
    QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QPushButton, QLabel, QStatusBar, QMessageBox,
    QApplication, QProgressBar, QFileDialog,
    QFrame, QGraphicsDropShadowEffect, QProgressDialog
)
from PySide6.QtCore import Qt, Slot, QSettings
from PySide6.QtGui import QAction, QKeySequence, QColor

from .widgets import DropZone, FileQueueWidget, SettingsDialog, ProcessDialog, ModelDownloadDialog
from .workers import OCRWorker, get_performance_settings
from .styles import (
    GLOBAL_STYLE, get_button_style, apply_card_shadow,
    COLORS, RADIUS
)
from core.task_manager import Task, TaskStatus


class MainWindow(QMainWindow):
    """
    Main application window - Nature inspired design.
    Width: 520px (matching design file)
    """

    VERSION = "2.2.4"

    def __init__(self):
        super().__init__()
        self._tasks: dict[int, Task] = {}
        self._next_task_id = 1
        self._current_worker: OCRWorker | None = None
        self._processing_start_time: datetime | None = None
        self._settings_cache = {}
        self._user_cancelled = False  # Track if stop was user-initiated vs error

        self._load_settings_cache()
        self._setup_ui()
        self._setup_menu()
        self._connect_signals()
        self._apply_styles()

    def _load_settings_cache(self):
        """Load settings into cache"""
        settings = QSettings("SmartOCR", "OCRTool")
        self._settings_cache = {
            'output_dir': None,
            'suffix': settings.value("output/suffix", "_ocr"),
            'dpi': int(settings.value("quality/dpi", "300")),
            'skip_existing_text': settings.value("options/skip_existing_text", True, type=bool),
            'auto_open': settings.value("options/auto_open", False, type=bool),
            'play_sound': settings.value("options/play_sound", True, type=bool),
        }

        # Output dir
        if settings.value("output/use_custom", False, type=bool):
            path = settings.value("output/custom_path", "")
            if path:
                self._settings_cache['output_dir'] = path

    def _apply_styles(self):
        """Apply global stylesheet"""
        self.setStyleSheet(GLOBAL_STYLE)

    def _setup_ui(self):
        """Setup main window UI - Matching Pencil Design"""
        self.setWindowTitle("智能OCR - 数字文献学")
        self.setFixedWidth(520)
        self.setMinimumHeight(640)
        self.resize(520, 680)

        # Central widget
        central = QWidget()
        central.setStyleSheet(f"background-color: {COLORS['bg_primary']};")
        self.setCentralWidget(central)

        # Main layout
        main_layout = QVBoxLayout(central)
        main_layout.setContentsMargins(24, 20, 24, 20)
        main_layout.setSpacing(16)

        # =============================================
        # HEADER - Title with badge and settings
        # =============================================
        header = QHBoxLayout()
        header.setSpacing(10)

        # Title with brand badge
        title_container = QHBoxLayout()
        title_container.setSpacing(10)

        title_label = QLabel("智能 OCR")
        title_label.setStyleSheet(f"""
            font-size: 20px;
            font-weight: 700;
            color: {COLORS['text_primary']};
            font-family: 'Helvetica Neue', 'PingFang SC';
            letter-spacing: -0.3px;
        """)

        brand_label = QLabel("数字文献学")
        brand_label.setStyleSheet(f"""
            font-size: 10px;
            font-weight: 600;
            color: {COLORS['accent_primary']};
            background-color: {COLORS['accent_light']};
            border-radius: 100px;
            padding: 3px 8px;
            font-family: 'Helvetica Neue', 'PingFang SC';
        """)

        title_container.addWidget(title_label)
        title_container.addWidget(brand_label)
        title_container.addStretch()

        # Settings button
        self.settings_btn = QPushButton("⚙")
        self.settings_btn.setFixedSize(36, 36)
        self.settings_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.settings_btn.setStyleSheet(f"""
            QPushButton {{
                background-color: {COLORS['bg_elevated']};
                color: {COLORS['text_secondary']};
                border: none;
                border-radius: 18px;
                font-size: 16px;
            }}
            QPushButton:hover {{ background-color: {COLORS['bg_muted']}; }}
        """)

        self.log_btn = QPushButton("☰")
        self.log_btn.setFixedSize(36, 36)
        self.log_btn.setToolTip("查看日志文件夹")
        self.log_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.log_btn.setStyleSheet(f"""
            QPushButton {{
                background-color: {COLORS['bg_elevated']};
                color: {COLORS['text_secondary']};
                border: none;
                border-radius: 18px;
                font-size: 16px;
            }}
            QPushButton:hover {{ background-color: {COLORS['bg_muted']}; }}
        """)

        header.addLayout(title_container, 1)
        header.addWidget(self.log_btn)
        header.addWidget(self.settings_btn)

        main_layout.addLayout(header)

        # =============================================
        # DROP ZONE - Matching design file
        # =============================================
        self.drop_zone = DropZone()
        self.drop_zone.setMinimumHeight(180)
        self.drop_zone.setMaximumHeight(200)
        apply_card_shadow(self.drop_zone)

        main_layout.addWidget(self.drop_zone)

        # =============================================
        # FILE QUEUE SECTION - With header
        # =============================================
        queue_section = QVBoxLayout()
        queue_section.setSpacing(10)

        # Queue header
        queue_header = QHBoxLayout()
        
        queue_title = QLabel("文件队列")
        queue_title.setStyleSheet(f"""
            font-size: 14px;
            font-weight: 600;
            color: {COLORS['text_primary']};
            font-family: 'Helvetica Neue', 'PingFang SC';
        """)

        self.queue_count_label = QLabel("")
        self.queue_count_label.setStyleSheet(f"""
            font-size: 12px;
            font-weight: 500;
            color: {COLORS['text_tertiary']};
            font-family: 'Helvetica Neue', 'PingFang SC';
        """)

        queue_header.addWidget(queue_title)
        queue_header.addStretch()
        queue_header.addWidget(self.queue_count_label)

        queue_section.addLayout(queue_header)

        # Queue card
        queue_card = QFrame()
        queue_card.setObjectName("queueCard")
        queue_card.setStyleSheet(f"""
            QFrame#queueCard {{
                background-color: {COLORS['bg_surface']};
                border-radius: {RADIUS['lg']}px;
                border: 1px solid {COLORS['border_subtle']};
            }}
        """)
        apply_card_shadow(queue_card)

        queue_layout = QVBoxLayout(queue_card)
        queue_layout.setContentsMargins(0, 8, 0, 8)
        queue_layout.setSpacing(0)

        # File queue widget
        self.file_queue = FileQueueWidget()
        queue_layout.addWidget(self.file_queue)

        queue_card.setMinimumHeight(180)
        queue_section.addWidget(queue_card, 1)

        main_layout.addLayout(queue_section, 2)

        # =============================================
        # ACTION BAR - Primary and secondary buttons
        # =============================================
        action_bar = QHBoxLayout()
        action_bar.setSpacing(10)

        self.clear_btn = QPushButton("🗑 清除列表")
        self.clear_btn.setStyleSheet(get_button_style('ghost'))
        self.clear_btn.setCursor(Qt.CursorShape.PointingHandCursor)

        self.start_btn = QPushButton("▶ 开始处理")
        self.start_btn.setStyleSheet(get_button_style('primary'))
        self.start_btn.setFixedHeight(40)
        self.start_btn.setMinimumWidth(120)
        self.start_btn.setCursor(Qt.CursorShape.PointingHandCursor)

        action_bar.addWidget(self.clear_btn)
        action_bar.addStretch()
        action_bar.addWidget(self.start_btn)

        main_layout.addLayout(action_bar)

        # =============================================
        # STATUS BAR - With progress
        # =============================================
        self.status_bar = QStatusBar()
        self.setStatusBar(self.status_bar)

        status_container = QWidget()
        status_layout = QVBoxLayout(status_container)
        status_layout.setContentsMargins(12, 12, 12, 12)
        status_layout.setSpacing(8)

        # Status row with label and percentage
        status_row = QHBoxLayout()
        
        self.status_label = QLabel("就绪")
        self.status_label.setStyleSheet(f"""
            color: {COLORS['text_secondary']};
            font-size: 12px;
            font-weight: 500;
            font-family: 'Helvetica Neue', 'PingFang SC';
        """)

        self.status_percent = QLabel("")
        self.status_percent.setStyleSheet(f"""
            color: {COLORS['accent_primary']};
            font-size: 12px;
            font-weight: 600;
            font-family: 'Helvetica Neue', 'PingFang SC';
        """)

        status_row.addWidget(self.status_label)
        status_row.addStretch()
        status_row.addWidget(self.status_percent)

        # Progress bar
        self.status_progress = QProgressBar()
        self.status_progress.setFixedHeight(4)
        self.status_progress.setTextVisible(False)
        self.status_progress.setVisible(False)
        self.status_progress.setStyleSheet(f"""
            QProgressBar {{
                border: none;
                border-radius: 2px;
                background-color: {COLORS['bg_muted']};
            }}
            QProgressBar::chunk {{
                background-color: {COLORS['accent_primary']};
                border-radius: 2px;
            }}
        """)

        status_layout.addLayout(status_row)
        status_layout.addWidget(self.status_progress)

        self.status_bar.addWidget(status_container, 1)

        # Powered by attribution
        powered_label = QLabel("Powered by PaddleOCR 3.0")
        powered_label.setStyleSheet(f"""
            color: {COLORS['text_tertiary']};
            font-size: 10px;
            font-family: 'Helvetica Neue', 'PingFang SC';
        """)
        self.status_bar.addPermanentWidget(powered_label)

        self._update_ui_state()

    def _setup_menu(self):
        """Setup menu bar"""
        menubar = self.menuBar()
        menubar.setStyleSheet(f"""
            QMenuBar {{
                background-color: {COLORS['bg_primary']};
                border: none;
            }}
            QMenuBar::item {{
                padding: 6px 12px;
                background: transparent;
            }}
            QMenuBar::item:selected {{
                background-color: {COLORS['bg_muted']};
                border-radius: 6px;
            }}
        """)

        # File menu
        file_menu = menubar.addMenu("文件")

        add_files_action = QAction("添加文件...", self)
        add_files_action.setShortcut(QKeySequence("Ctrl+O"))
        add_files_action.triggered.connect(self._on_add_files)
        file_menu.addAction(add_files_action)

        add_folder_action = QAction("添加文件夹...", self)
        add_folder_action.setShortcut(QKeySequence("Ctrl+Shift+O"))
        add_folder_action.triggered.connect(self._on_add_folder)
        file_menu.addAction(add_folder_action)

        file_menu.addSeparator()

        settings_action = QAction("设置...", self)
        settings_action.setShortcut(QKeySequence("Ctrl+,"))
        settings_action.triggered.connect(self._show_settings)
        file_menu.addAction(settings_action)

        file_menu.addSeparator()

        exit_action = QAction("退出", self)
        exit_action.setShortcut(QKeySequence("Ctrl+Q"))
        exit_action.triggered.connect(self.close)
        file_menu.addAction(exit_action)

        # Help menu
        help_menu = menubar.addMenu("帮助")

        about_action = QAction("关于", self)
        about_action.triggered.connect(self._show_about)
        help_menu.addAction(about_action)

    def _connect_signals(self):
        """Connect widget signals"""
        self.drop_zone.files_dropped.connect(self._on_files_dropped)
        self.clear_btn.clicked.connect(self._on_clear_queue)
        self.start_btn.clicked.connect(self._on_start_processing)
        self.settings_btn.clicked.connect(self._show_settings)
        self.log_btn.clicked.connect(self._open_log_folder)

        self.file_queue.remove_requested.connect(self._on_remove_task)
        self.file_queue.reprocess_requested.connect(self._on_reprocess_task)
        self.file_queue.open_folder_requested.connect(self._open_folder)
        self.file_queue.language_changed.connect(self._on_task_language_changed)

    def _show_settings(self):
        """Show settings dialog"""
        dialog = SettingsDialog(self)
        if dialog.exec():
            # Reload settings cache
            self._load_settings_cache()

    def _on_files_dropped(self, paths: list[str]):
        self._add_files(paths)

    def _on_add_files(self):
        files, _ = QFileDialog.getOpenFileNames(
            self,
            "选择 PDF 文件",
            "",
            "PDF 文件 (*.pdf);;所有文件 (*.*)"
        )
        if files:
            self._add_files(files)

    def _on_add_folder(self):
        folder = QFileDialog.getExistingDirectory(self, "选择文件夹")
        if folder:
            folder_path = Path(folder)
            pdf_files = list(folder_path.rglob("*.pdf")) + list(folder_path.rglob("*.PDF"))
            self._add_files([str(f) for f in pdf_files])

    def _add_files(self, paths: list[str]):
        added = 0
        for path in paths:
            path = Path(path)
            if path.suffix.lower() != '.pdf':
                continue
            lowered = path.name.lower()
            if lowered.startswith('.') or lowered.startswith('._') or lowered.endswith('_temp.pdf') or '_ocr_temp' in lowered:
                self.status_label.setText(f"跳过临时文件: {path.name}")
                continue

            # Validate PDF before adding to queue
            from core.pdf_processor import validate_pdf
            is_valid, error_msg = validate_pdf(str(path))
            if not is_valid:
                # Show brief warning in status bar rather than a blocking dialog
                self.status_label.setText(f"跳过无效文件: {path.name} ({error_msg})")
                continue

            # Determine output path
            output_dir = self._settings_cache.get('output_dir')
            suffix = self._settings_cache.get('suffix', '_ocr')

            # Sanitize filename for cross-platform compatibility
            safe_stem = re.sub(r'[\\/:*?"<>|]', '_', path.stem)

            if output_dir:
                output_path = Path(output_dir) / (safe_stem + suffix + ".pdf")
            else:
                output_path = path.parent / (safe_stem + suffix + ".pdf")

            task = Task(
                id=self._next_task_id,
                input_path=str(path),
                output_path=str(output_path),
                languages=['ch', 'en'],
            )
            self._next_task_id += 1
            self._tasks[task.id] = task

            self.file_queue.add_task(task)
            added += 1

        if added > 0:
            self.status_label.setText(f"已添加 {added} 个文件")
            self._update_ui_state()

    def _on_clear_queue(self):
        if self._current_worker and self._current_worker.isRunning():
            QMessageBox.warning(self, "提示", "正在处理中，无法清空队列")
            return

        self._tasks.clear()
        self.file_queue.clear_all()
        self.status_label.setText("队列已清空")
        self._update_ui_state()

    def _on_remove_task(self, task_id: int):
        task = self._tasks.get(task_id)
        if task and task.status == TaskStatus.PROCESSING:
            return

        if task_id in self._tasks:
            del self._tasks[task_id]
        self.file_queue.remove_task(task_id)
        self._update_ui_state()

    def _on_reprocess_task(self, task_id: int):
        task = self._tasks.get(task_id)
        if task:
            task.status = TaskStatus.PENDING
            task.progress = 0
            task.error_message = ""
            self.file_queue.update_task(task)

    def _on_task_language_changed(self, task_id: int, languages: list):
        task = self._tasks.get(task_id)
        if task:
            task.languages = languages

    def _on_start_processing(self):
        if self._current_worker and self._current_worker.isRunning():
            self._user_cancelled = True
            self._current_worker.request_stop()
            self.start_btn.setText("停止中...")
            self.start_btn.setEnabled(False)
            # Tell user why UI is momentarily unresponsive:
            # OCR inference on the current page cannot be interrupted mid-run.
            self.status_label.setText("正在取消，等待当前页面 OCR 完成后停止（约 10~20 秒）...")
            return

        pending_tasks = [t for t in self._tasks.values() if t.status == TaskStatus.PENDING]
        if not pending_tasks:
            QMessageBox.information(self, "提示", "没有待处理的文件")
            return
        settings = QSettings("SmartOCR", "OCRTool")
        if settings.value("batch/group_by_language", True, type=bool):
            pending_tasks.sort(key=lambda task: tuple(task.languages or ['ch', 'en']))

        self._processing_start_time = datetime.now()

        # Get performance settings
        perf_settings = get_performance_settings()

        # Use each task's individual language setting (set in queue or auto-detected)
        # Pass the first task's languages as default fallback for the worker
        default_langs = pending_tasks[0].languages if pending_tasks else ['ch', 'en']

        self._current_worker = OCRWorker(
            tasks=pending_tasks,
            languages=default_langs,
            dpi=self._settings_cache.get('dpi', 300),
            skip_existing_text=self._settings_cache.get('skip_existing_text', True),
            quality=perf_settings['quality'],
            num_workers=perf_settings['num_workers'],
            use_gpu=perf_settings.get('use_gpu'),
            auto_retry_enabled=perf_settings.get('auto_retry_enabled', True),
            max_retries=perf_settings.get('max_retries', 2),
            image_mode=perf_settings.get('image_mode', 'lossy_85'),
            page_retry_limit=perf_settings.get('page_retry_limit', 2),
            allow_fallback_copy=perf_settings.get('allow_fallback_copy', True),
        )

        self._current_worker.progress.connect(self._on_progress)
        self._current_worker.task_complete.connect(self._on_task_complete)
        self._current_worker.task_status.connect(self._on_task_status)
        self._current_worker.all_complete.connect(self._on_all_complete)
        self._current_worker.model_download_needed.connect(self._on_model_download_needed)
        self._current_worker.start()

        self.start_btn.setText("⏹ 停止")
        self.start_btn.setStyleSheet(get_button_style('danger'))
        self.status_progress.setVisible(True)
        self._update_ui_state()

    @Slot(list)
    def _on_model_download_needed(self, missing_models: list):
        """Show download dialog when a quality mode's models are not yet cached."""
        dlg = ModelDownloadDialog(missing_models, parent=self)
        # Use DirectConnection so notify_models_ready() is called immediately from
        # whatever thread emits download_complete.  This avoids a queued-connection
        # deadlock: OCRWorker's thread has no Qt event loop, so a queued signal
        # to it would never be delivered while it is blocked on threading.Event.wait().
        dlg.download_complete.connect(
            self._current_worker.notify_models_ready,
            Qt.ConnectionType.DirectConnection,
        )
        dlg.download_failed.connect(self._abort_worker)
        dlg.exec()

    def _abort_worker(self, error: str = ""):
        """Stop the current worker after a model download failure or cancellation."""
        # Treat this the same as a user-initiated cancel so _on_all_complete
        # shows "已取消" and suppresses the "完成: 0/0 成功" popup.
        self._user_cancelled = True
        if self._current_worker:
            self._current_worker.request_stop()
            # Unblock the threading.Event in run() so the worker thread can exit
            self._current_worker.notify_models_ready()

    @Slot(int, int, int)
    def _on_progress(self, task_id: int, current_page: int, total_pages: int):
        task = self._tasks.get(task_id)
        if task:
            task.status = TaskStatus.PROCESSING
            task.current_page = current_page
            task.total_pages = total_pages
            task.progress = int((current_page / total_pages) * 100) if total_pages > 0 else 0
            self.file_queue.update_task(task)

            self.status_progress.setMaximum(total_pages)
            self.status_progress.setValue(current_page)
            
            total_tasks = len([t for t in self._tasks.values() if t.status == TaskStatus.PROCESSING])
            total_pending = len([t for t in self._tasks.values() if t.status == TaskStatus.PENDING])
            total_all = total_tasks + total_pending
            
            if total_all > 0:
                percent = int((current_page / total_pages) * 100) if total_pages > 0 else 0
                self.status_label.setText(f"正在处理... {task.filename}")
                self.status_percent.setText(f"{percent}%")
            else:
                self.status_label.setText(f"处理中: {task.filename}")

    @Slot(int, bool, str)
    def _on_task_complete(self, task_id: int, success: bool, error_message: str):
        task = self._tasks.get(task_id)
        if task:
            if success:
                task.status = TaskStatus.COMPLETED
                task.progress = 100
                # Show non-fatal warning (e.g., recovered missing pages) in the task
                if error_message:
                    task.error_message = error_message
            elif self._user_cancelled:
                # User explicitly stopped — mark as cancelled, not failed
                task.status = TaskStatus.CANCELLED
                task.error_message = ""
            else:
                task.status = TaskStatus.FAILED
                task.error_message = error_message

            self.file_queue.update_task(task)

    @Slot(int, str)
    def _on_task_status(self, task_id: int, message: str):
        task = self._tasks.get(task_id)
        if task and message:
            self.status_label.setText(f"{task.filename} · {message}")

    @Slot()
    def _on_all_complete(self):
        if self._current_worker:
            try:
                self._current_worker.progress.disconnect()
                self._current_worker.task_complete.disconnect()
                self._current_worker.task_status.disconnect()
                self._current_worker.all_complete.disconnect()
                self._current_worker.model_download_needed.disconnect()
            except RuntimeError:
                pass  # Already disconnected
        self._current_worker = None
        self.status_progress.setVisible(False)
        self.status_percent.setText("")

        was_cancelled = self._user_cancelled
        self._user_cancelled = False  # Reset for next run

        completed = sum(1 for t in self._tasks.values() if t.status == TaskStatus.COMPLETED)
        failed = sum(1 for t in self._tasks.values() if t.status == TaskStatus.FAILED)
        total = completed + failed

        elapsed = ""
        if self._processing_start_time:
            delta = datetime.now() - self._processing_start_time
            minutes = int(delta.total_seconds() // 60)
            seconds = int(delta.total_seconds() % 60)
            if minutes > 0:
                elapsed = f" · 用时 {minutes}分{seconds}秒"
            else:
                elapsed = f" · 用时 {seconds}秒"

        if was_cancelled:
            self.status_label.setText(f"已取消 · 进度已保存，下次可继续{elapsed}")
        else:
            self.status_label.setText(f"完成: {completed}/{total} 成功{elapsed}")

        self.start_btn.setText("▶ 开始处理")
        self.start_btn.setEnabled(True)
        self.start_btn.setStyleSheet(get_button_style('primary'))

        if self._settings_cache.get('play_sound') and not was_cancelled:
            QApplication.beep()

        # Don't show popup if user explicitly cancelled
        if was_cancelled:
            return

        total_pages = sum(t.total_pages for t in self._tasks.values() if t.status == TaskStatus.COMPLETED)
        warned = sum(
            1 for t in self._tasks.values()
            if t.status == TaskStatus.COMPLETED and t.error_message
        )
        retried = sum(
            1 for t in self._tasks.values()
            if t.status == TaskStatus.COMPLETED and "自动重试成功" in t.error_message
        )
        fallback_tasks = [
            t for t in self._tasks.values()
            if t.status == TaskStatus.COMPLETED and "回填原页" in t.error_message
        ]
        fallback_count = len(fallback_tasks)
        fallback_detail = ""
        if fallback_tasks:
            first_detail = fallback_tasks[0].error_message.split("；")[-1]
            fallback_detail = f"\n回填详情示例：{first_detail[:120]}"

        if failed > 0:
            QMessageBox.warning(
                self, "处理完成",
                f"处理完成\n\n✓ 成功: {completed} 个文件\n✗ 失败: {failed} 个文件\n共处理 {total_pages} 页{elapsed}"
            )
        elif warned > 0:
            QMessageBox.warning(
                self, "处理完成",
                f"全部完成（有警告）\n\n✓ {completed} 个文件处理成功\n↻ {retried} 个文件重试恢复\n⚠ {warned} 个文件存在问题\n↯ {fallback_count} 个文件包含回填页\n共处理 {total_pages} 页{elapsed}{fallback_detail}\n\n提示：鼠标悬停在文件状态上可查看详情"
            )
        else:
            per_page = ""
            if self._processing_start_time and total_pages > 0:
                per_page_sec = delta.total_seconds() / total_pages
                per_page = f"\n平均每页: {per_page_sec:.2f} 秒"

            QMessageBox.information(
                self, "处理完成",
                f"全部完成\n\n✓ {completed} 个文件处理成功\n共处理 {total_pages} 页{elapsed}{per_page}"
            )

        if self._settings_cache.get('auto_open') and completed > 0:
            for task in self._tasks.values():
                if task.status == TaskStatus.COMPLETED:
                    self._open_file(task.output_path)
                    break

        self._update_ui_state()

    def _open_log_folder(self):
        """打開日誌文件夾"""
        log_dir = Path.home() / ".ocr_tool" / "logs"
        log_dir.mkdir(parents=True, exist_ok=True)
        if sys.platform == "darwin":
            subprocess.Popen(["open", str(log_dir)])
        elif sys.platform == "win32":
            subprocess.Popen(["explorer", str(log_dir)])
        else:
            subprocess.Popen(["xdg-open", str(log_dir)])

    def _open_folder(self, file_path: str):
        folder = Path(file_path).parent
        if sys.platform == 'darwin':
            subprocess.run(['open', str(folder)])
        elif sys.platform == 'win32':
            subprocess.run(['explorer', str(folder)])
        else:
            subprocess.run(['xdg-open', str(folder)])

    def _open_file(self, file_path: str):
        if sys.platform == 'darwin':
            subprocess.run(['open', file_path])
        elif sys.platform == 'win32':
            os.startfile(file_path)
        else:
            subprocess.run(['xdg-open', file_path])

    def _update_ui_state(self):
        task_count = len(self._tasks)
        is_processing = bool(self._current_worker and self._current_worker.isRunning())
        pending_count = sum(1 for t in self._tasks.values() if t.status == TaskStatus.PENDING)
        completed = sum(1 for t in self._tasks.values() if t.status == TaskStatus.COMPLETED)

        # Update queue count display
        if task_count == 0:
            self.queue_count_label.setText("")
        elif completed > 0:
            self.queue_count_label.setText(f"{completed}/{task_count} 完成")
        else:
            self.queue_count_label.setText(f"{task_count} 个文件")

        self.clear_btn.setEnabled(bool(task_count > 0 and not is_processing))
        self.start_btn.setEnabled(bool(pending_count > 0 or is_processing))

        if not is_processing:
            if pending_count > 0:
                self.start_btn.setText(f"▶ 开始处理 ({pending_count})")
            else:
                self.start_btn.setText("▶ 开始处理")

    def _show_about(self):
        QMessageBox.about(
            self, "关于",
            f"<h3 style='font-weight: 600; margin-bottom: 4px; color: {COLORS['text_primary']};'>智能 OCR</h3>"
            f"<p style='color: {COLORS['accent_primary']}; font-size: 12px; margin: 0;'>数字文献学</p>"
            f"<p style='color: {COLORS['text_tertiary']}; font-size: 11px;'>版本 {self.VERSION}</p>"
            f"<br>"
            f"<p style='color: {COLORS['text_primary']}; font-size: 13px;'>将扫描版 PDF 转换为可搜索文档</p>"
            f"<p style='color: {COLORS['text_secondary']}; font-size: 11px;'>OCR 引擎: PaddleOCR 3.0</p>"
            f"<p style='color: {COLORS['text_secondary']}; font-size: 11px;'>支持中文 · 日文 · 英文</p>"
        )

    def closeEvent(self, event):
        if self._current_worker and self._current_worker.isRunning():
            reply = QMessageBox.question(
                self, "确认退出",
                "正在处理文件，确定要退出吗？\n\n进度会自动保存，下次可继续处理。",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
            )
            if reply == QMessageBox.StandardButton.No:
                event.ignore()
                return

            self._current_worker.request_stop()
            # Disconnect signals to prevent stale callbacks during shutdown
            try:
                self._current_worker.progress.disconnect()
                self._current_worker.task_complete.disconnect()
                self._current_worker.task_status.disconnect()
                self._current_worker.all_complete.disconnect()
                self._current_worker.model_download_needed.disconnect()
            except RuntimeError:
                pass

            # Show saving progress dialog while waiting for worker to finish
            progress_dialog = QProgressDialog(
                "正在保存进度，请稍候...", "强制退出", 0, 0, self
            )
            progress_dialog.setWindowTitle("保存中")
            progress_dialog.setWindowModality(Qt.WindowModality.WindowModal)
            progress_dialog.setMinimumDuration(0)
            progress_dialog.setValue(0)
            progress_dialog.show()

            # Wait up to 30 seconds for clean shutdown
            max_wait_ms = 30000
            interval_ms = 200
            elapsed = 0
            while elapsed < max_wait_ms:
                if self._current_worker.wait(interval_ms):
                    break  # Worker finished cleanly
                elapsed += interval_ms
                QApplication.processEvents()
                if progress_dialog.wasCanceled():
                    break  # User clicked "强制退出"

            progress_dialog.close()

        event.accept()
