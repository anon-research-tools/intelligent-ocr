"""
File Queue Widget - Based on Pencil Design File
Modern file list with status dots and progress bars
"""
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel,
    QListWidget, QListWidgetItem, QProgressBar, QMenu,
    QAbstractItemView, QStyledItemDelegate, QStyleOptionViewItem, QFrame,
    QPushButton, QDialog
)
from PySide6.QtCore import Qt, Signal, QSize, QModelIndex
from PySide6.QtGui import QColor

from core.task_manager import Task, TaskStatus, LANGUAGE_DISPLAY
from ..styles import COLORS, RADIUS, get_button_style


class LanguagePickerDialog(QDialog):
    """Compact language picker for a single file."""

    def __init__(self, current_languages: list[str], filename: str, parent=None):
        super().__init__(parent)
        self.setWindowTitle("设置语言")
        self.setModal(True)
        self.setFixedWidth(320)
        self._languages = list(current_languages)
        self._checkboxes: dict[str, QPushButton] = {}
        self._setup_ui(filename)

    def _setup_ui(self, filename: str):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(16)

        # Title
        title = QLabel(f"识别语言 — {filename}")
        title.setWordWrap(True)
        title.setStyleSheet(f"""
            font-size: 14px;
            font-weight: 600;
            color: {COLORS['text_primary']};
            font-family: 'Helvetica Neue', 'PingFang SC';
        """)
        layout.addWidget(title)

        # Language buttons
        lang_row = QHBoxLayout()
        lang_row.setSpacing(8)

        langs = [("ch", "中文"), ("en", "英文"), ("japan", "日文")]
        for code, label in langs:
            btn = QPushButton(label)
            btn.setCheckable(True)
            btn.setChecked(code in self._languages)
            btn.setFixedSize(72, 40)
            btn.setStyleSheet(self._btn_style(code in self._languages))
            btn.toggled.connect(lambda checked, c=code, b=btn: self._on_toggle(c, checked, b))
            lang_row.addWidget(btn)
            self._checkboxes[code] = btn

        lang_row.addStretch()
        layout.addLayout(lang_row)

        # Buttons
        btn_row = QHBoxLayout()
        btn_row.setSpacing(8)
        btn_row.addStretch()

        cancel_btn = QPushButton("取消")
        cancel_btn.setFixedSize(70, 34)
        cancel_btn.setStyleSheet(get_button_style('secondary'))
        cancel_btn.clicked.connect(self.reject)

        ok_btn = QPushButton("确定")
        ok_btn.setFixedSize(70, 34)
        ok_btn.setStyleSheet(get_button_style('primary'))
        ok_btn.clicked.connect(self.accept)

        btn_row.addWidget(cancel_btn)
        btn_row.addWidget(ok_btn)
        layout.addLayout(btn_row)

    def _btn_style(self, selected: bool) -> str:
        if selected:
            return f"""
                QPushButton {{
                    background-color: {COLORS['accent_light']};
                    border: 2px solid {COLORS['accent_primary']};
                    border-radius: 6px;
                    color: {COLORS['accent_primary']};
                    font-size: 13px;
                    font-weight: 600;
                    font-family: 'Helvetica Neue', 'PingFang SC';
                }}
            """
        return f"""
            QPushButton {{
                background-color: {COLORS['bg_primary']};
                border: 1px solid {COLORS['border_subtle']};
                border-radius: 6px;
                color: {COLORS['text_secondary']};
                font-size: 13px;
                font-family: 'Helvetica Neue', 'PingFang SC';
            }}
            QPushButton:hover {{
                border-color: {COLORS['accent_primary']};
                color: {COLORS['accent_primary']};
            }}
        """

    def _on_toggle(self, code: str, checked: bool, btn: QPushButton):
        btn.setStyleSheet(self._btn_style(checked))
        if checked and code not in self._languages:
            self._languages.append(code)
        elif not checked and code in self._languages:
            self._languages.remove(code)

    def get_languages(self) -> list[str]:
        result = [c for c in ['ch', 'en', 'japan'] if c in self._languages]
        return result if result else ['ch']


class TransparentDelegate(QStyledItemDelegate):
    """Custom delegate that paints a solid white background,
    preventing any gray stripes from showing through."""

    def paint(self, painter, option: QStyleOptionViewItem, index: QModelIndex):
        # Save painter state
        painter.save()
        # Paint solid white background to cover any gray stripes
        painter.fillRect(option.rect, QColor(COLORS['bg_surface']))
        painter.restore()
        # Don't call super().paint() - let the item widget render everything

    def sizeHint(self, option: QStyleOptionViewItem, index: QModelIndex) -> QSize:
        return QSize(0, 60)


class FileQueueItem(QWidget):
    """
    Custom widget for displaying a single file in the queue.
    Matches design file with file icon, info, progress, and language tag.
    """

    language_changed = Signal(int, list)  # task_id, new_languages

    def __init__(self, task: Task, parent=None):
        super().__init__(parent)
        self.task = task
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setStyleSheet(f"background-color: {COLORS['bg_surface']};")
        self._setup_ui()
        self.update_display()

    def _setup_ui(self):
        layout = QHBoxLayout(self)
        layout.setContentsMargins(16, 10, 16, 10)
        layout.setSpacing(10)

        # Status dot indicator
        self.status_dot = QLabel()
        self.status_dot.setFixedSize(10, 10)
        self.status_dot.setStyleSheet(f"""
            background-color: {COLORS['text_tertiary']};
            border-radius: 5px;
        """)

        # Info container (filename + progress)
        info_layout = QVBoxLayout()
        info_layout.setSpacing(4)
        info_layout.setContentsMargins(0, 0, 0, 0)

        # Name row (filename + status)
        name_row = QHBoxLayout()
        name_row.setSpacing(8)

        self.filename_label = QLabel()
        self.filename_label.setStyleSheet(f"""
            QLabel {{
                font-size: 13px;
                font-weight: 500;
                color: {COLORS['text_primary']};
                font-family: 'Helvetica Neue', 'PingFang SC';
            }}
        """)

        self.status_label = QLabel()
        self.status_label.setStyleSheet(f"""
            QLabel {{
                font-size: 11px;
                font-weight: 500;
                color: {COLORS['text_tertiary']};
                font-family: 'Helvetica Neue', 'PingFang SC';
            }}
        """)

        name_row.addWidget(self.filename_label, 1)
        name_row.addWidget(self.status_label)

        # Progress bar
        self.progress_bar = QProgressBar()
        self.progress_bar.setFixedHeight(4)
        self.progress_bar.setTextVisible(False)
        self.progress_bar.setVisible(False)
        self.progress_bar.setStyleSheet(f"""
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

        info_layout.addLayout(name_row)
        info_layout.addWidget(self.progress_bar)

        # Language tag button (only for PENDING tasks)
        self.lang_btn = QPushButton()
        self.lang_btn.setFixedSize(42, 24)
        self.lang_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.lang_btn.clicked.connect(self._on_lang_clicked)
        self._update_lang_btn()

        layout.addWidget(self.status_dot)
        layout.addLayout(info_layout, 1)
        layout.addWidget(self.lang_btn)

    def _update_lang_btn(self):
        """Update language button text and style."""
        text = self.task.languages_display
        self.lang_btn.setText(text)
        is_pending = self.task.status == TaskStatus.PENDING
        self.lang_btn.setEnabled(is_pending)
        self.lang_btn.setVisible(True)
        if is_pending:
            self.lang_btn.setStyleSheet(f"""
                QPushButton {{
                    background-color: {COLORS['accent_light']};
                    border: 1px solid {COLORS['accent_primary']}60;
                    border-radius: 4px;
                    color: {COLORS['accent_primary']};
                    font-size: 11px;
                    font-weight: 600;
                    font-family: 'Helvetica Neue', 'PingFang SC';
                    padding: 0px;
                }}
                QPushButton:hover {{
                    background-color: {COLORS['accent_primary']};
                    color: white;
                }}
            """)
        else:
            self.lang_btn.setStyleSheet(f"""
                QPushButton {{
                    background-color: {COLORS['bg_muted']};
                    border: none;
                    border-radius: 4px;
                    color: {COLORS['text_tertiary']};
                    font-size: 11px;
                    font-family: 'Helvetica Neue', 'PingFang SC';
                    padding: 0px;
                }}
            """)

    def _on_lang_clicked(self):
        """Open language picker for this file."""
        dialog = LanguagePickerDialog(
            self.task.languages,
            self.task.filename,
            parent=self
        )
        if dialog.exec():
            new_langs = dialog.get_languages()
            self.task.languages = new_langs
            self._update_lang_btn()
            self.language_changed.emit(self.task.id, new_langs)

    def update_display(self):
        """Update display based on task state"""
        self.filename_label.setText(self.task.filename)

        status = self.task.status
        progress = self.task.progress

        # Color mapping
        color_map = {
            TaskStatus.PENDING: COLORS['text_tertiary'],      # Gray
            TaskStatus.PROCESSING: COLORS['status_processing'],  # Blue
            TaskStatus.COMPLETED: COLORS['status_positive'],     # Green
            TaskStatus.FAILED: COLORS['status_negative'],        # Red
            TaskStatus.CANCELLED: COLORS['text_secondary'],     # Dark gray
        }
        status_color = color_map.get(status, COLORS['text_tertiary'])

        # Update status dot color
        self.status_dot.setStyleSheet(f"""
            background-color: {status_color};
            border-radius: 5px;
        """)

        # Show/hide progress bar
        self.progress_bar.setValue(progress)
        self.progress_bar.setVisible(status == TaskStatus.PROCESSING)
        if status == TaskStatus.COMPLETED:
            self.progress_bar.setStyleSheet(f"""
                QProgressBar {{
                    border: none;
                    border-radius: 2px;
                    background-color: {COLORS['bg_muted']};
                }}
                QProgressBar::chunk {{
                    background-color: {COLORS['status_positive']};
                    border-radius: 2px;
                }}
            """)
            self.progress_bar.setVisible(True)
            self.progress_bar.setValue(100)

        # Update status text
        if status == TaskStatus.PROCESSING and self.task.total_pages > 0:
            status_text = f"处理中 {self.task.current_page}/{self.task.total_pages}"
        else:
            status_text_map = {
                TaskStatus.PENDING: "等待中",
                TaskStatus.PROCESSING: f"处理中 {progress}%",
                TaskStatus.COMPLETED: "已完成",
                TaskStatus.FAILED: "失败",
                TaskStatus.CANCELLED: "已取消",
            }
            status_text = status_text_map.get(status, "")
            # Show warning indicator for completed tasks with non-fatal issues
            if status == TaskStatus.COMPLETED and self.task.error_message:
                status_text = "已完成 ⚠"
        self.status_label.setText(status_text)
        # Show warning tooltip
        if status == TaskStatus.COMPLETED and self.task.error_message:
            self.status_label.setToolTip(self.task.error_message)
        else:
            self.status_label.setToolTip("")

        # Update status color
        self.status_label.setStyleSheet(f"""
            QLabel {{
                font-size: 11px;
                font-weight: 500;
                color: {status_color};
                font-family: 'Helvetica Neue', 'PingFang SC';
            }}
        """)

        # Update language button
        self._update_lang_btn()


class FileQueueWidget(QWidget):
    """
    Widget displaying the file processing queue.
    Matches design file styling.

    Signals:
        remove_requested: Emitted when user requests to remove a task
        reprocess_requested: Emitted when user requests to reprocess a task
        open_folder_requested: Emitted when user wants to open containing folder
    """

    remove_requested = Signal(int)  # task_id
    reprocess_requested = Signal(int)  # task_id
    open_folder_requested = Signal(str)  # file_path
    language_changed = Signal(int, list)  # task_id, new_languages

    def __init__(self, parent=None):
        super().__init__(parent)
        self._task_items: dict[int, tuple[QListWidgetItem, FileQueueItem]] = {}
        self._setup_ui()

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # List widget
        self.list_widget = QListWidget()
        self.list_widget.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.list_widget.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.list_widget.customContextMenuRequested.connect(self._show_context_menu)

        # Use custom delegate to prevent gray background painting
        self.list_widget.setItemDelegate(TransparentDelegate(self.list_widget))

        # Set white background everywhere to prevent gray showing through
        self.list_widget.setAlternatingRowColors(False)
        self.list_widget.setFrameShape(QFrame.Shape.NoFrame)

        # Critical: Set stylesheet on the widget itself and viewport
        self.list_widget.setStyleSheet(f"""
            QListWidget {{
                border: none;
                background-color: {COLORS['bg_surface']};
                outline: none;
            }}
            QListWidget::item {{
                border: none;
                border-bottom: 1px solid {COLORS['border_subtle']};
                background-color: {COLORS['bg_surface']};
                padding: 0px;
                margin: 0px;
            }}
            QListWidget::item:selected {{
                background-color: {COLORS['accent_light']}60;
            }}
            QListWidget::item:hover {{
                background-color: {COLORS['bg_elevated']};
            }}
        """)

        # Set viewport stylesheet directly - this is critical
        self.list_widget.viewport().setStyleSheet(f"background-color: {COLORS['bg_surface']};")
        self.list_widget.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.list_widget.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.list_widget.setUniformItemSizes(True)
        self.list_widget.setSpacing(0)
        self.list_widget.setMinimumHeight(120)

        layout.addWidget(self.list_widget)

    def add_task(self, task: Task):
        """Add a task to the queue display"""
        if task.id in self._task_items:
            return  # Already exists

        item = QListWidgetItem()
        item.setData(Qt.ItemDataRole.UserRole, task.id)
        item.setSizeHint(QSize(0, 60))

        widget = FileQueueItem(task)
        widget.language_changed.connect(self.language_changed)

        self.list_widget.addItem(item)
        self.list_widget.setItemWidget(item, widget)

        self._task_items[task.id] = (item, widget)

    def update_task(self, task: Task):
        """Update display for a task"""
        if task.id in self._task_items:
            _, widget = self._task_items[task.id]
            widget.task = task
            widget.update_display()

    def remove_task(self, task_id: int):
        """Remove a task from the display"""
        if task_id in self._task_items:
            item, widget = self._task_items[task_id]
            row = self.list_widget.row(item)
            self.list_widget.takeItem(row)
            del self._task_items[task_id]

    def clear_all(self):
        """Clear all tasks from display"""
        self.list_widget.clear()
        self._task_items.clear()

    def clear_completed(self):
        """Remove completed tasks from display"""
        to_remove = []
        for task_id, (item, widget) in self._task_items.items():
            if widget.task.status == TaskStatus.COMPLETED:
                to_remove.append(task_id)

        for task_id in to_remove:
            self.remove_task(task_id)

    def get_selected_task_ids(self) -> list[int]:
        """Get IDs of selected tasks"""
        ids = []
        for item in self.list_widget.selectedItems():
            task_id = item.data(Qt.ItemDataRole.UserRole)
            if task_id is not None:
                ids.append(task_id)
        return ids

    def _show_context_menu(self, position):
        """Show context menu for selected items"""
        item = self.list_widget.itemAt(position)
        if not item:
            return

        task_id = item.data(Qt.ItemDataRole.UserRole)
        if task_id not in self._task_items:
            return

        _, widget = self._task_items[task_id]
        task = widget.task

        menu = QMenu(self)
        menu.setStyleSheet(f"""
            QMenu {{
                background-color: {COLORS['bg_surface']};
                border: 1px solid {COLORS['border_subtle']};
                border-radius: {RADIUS['md']}px;
                padding: 8px;
            }}
            QMenu::item {{
                padding: 8px 24px;
                border-radius: {RADIUS['sm']}px;
                font-family: 'Helvetica Neue', 'PingFang SC';
            }}
            QMenu::item:selected {{
                background-color: {COLORS['accent_primary']};
                color: white;
            }}
            QMenu::separator {{
                height: 1px;
                background-color: {COLORS['border_subtle']};
                margin: 6px 12px;
            }}
        """)

        # Set language action (for pending tasks)
        if task.status == TaskStatus.PENDING:
            set_lang_action = menu.addAction(f"设置语言  ({task.languages_display})")
            set_lang_action.triggered.connect(lambda: self._open_lang_picker(task_id))
            menu.addSeparator()

        # Remove action
        if task.status != TaskStatus.PROCESSING:
            remove_action = menu.addAction("移除")
            remove_action.triggered.connect(lambda: self.remove_requested.emit(task_id))

        # Reprocess action
        if task.status in (TaskStatus.COMPLETED, TaskStatus.FAILED, TaskStatus.CANCELLED):
            reprocess_action = menu.addAction("重新处理")
            reprocess_action.triggered.connect(lambda: self.reprocess_requested.emit(task_id))

        menu.addSeparator()

        # Open folder action
        open_folder_action = menu.addAction("打开所在文件夹")
        open_folder_action.triggered.connect(
            lambda: self.open_folder_requested.emit(task.input_path)
        )

        # Open output folder (if completed)
        if task.status == TaskStatus.COMPLETED:
            open_output_action = menu.addAction("打开输出文件夹")
            open_output_action.triggered.connect(
                lambda: self.open_folder_requested.emit(task.output_path)
            )

        menu.exec(self.list_widget.mapToGlobal(position))

    def _open_lang_picker(self, task_id: int):
        """Open language picker dialog for a specific task."""
        if task_id not in self._task_items:
            return
        _, widget = self._task_items[task_id]
        widget._on_lang_clicked()

    def get_task_count(self) -> int:
        """Get total number of tasks"""
        return len(self._task_items)

    def get_pending_count(self) -> int:
        """Get number of pending tasks"""
        return sum(
            1 for _, widget in self._task_items.items()
            if widget.task.status == TaskStatus.PENDING
        )

    def get_completed_count(self) -> int:
        """Get number of completed tasks"""
        return sum(
            1 for _, widget in self._task_items.items()
            if widget.task.status == TaskStatus.COMPLETED
        )
