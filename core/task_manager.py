"""
Task Manager - Queue and process multiple PDF files
"""
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Callable, Optional
import threading
import queue
import time


class TaskStatus(Enum):
    PENDING = "pending"
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


# Language display names for UI
LANGUAGE_DISPLAY = {
    'ch': '中',
    'en': '英',
    'japan': '日',
    'korean': '韩',
    'french': '法',
    'german': '德',
}


@dataclass
class Task:
    """A single OCR processing task"""
    id: int
    input_path: str
    output_path: str
    status: TaskStatus = TaskStatus.PENDING
    progress: int = 0  # 0-100
    current_page: int = 0
    total_pages: int = 0
    error_message: str = ""
    languages: list[str] = field(default_factory=lambda: ['ch', 'en'])

    @property
    def filename(self) -> str:
        return Path(self.input_path).name

    @property
    def languages_display(self) -> str:
        """Short display string, e.g. '中+英' or '日'"""
        parts = [LANGUAGE_DISPLAY.get(lang, lang) for lang in self.languages]
        return '+'.join(parts) if parts else '中'


@dataclass
class TaskManagerConfig:
    """Configuration for TaskManager"""
    output_dir: Optional[str] = None  # None = same as input
    output_suffix: str = "_ocr"
    languages: list[str] = field(default_factory=lambda: ['ch', 'en'])
    dpi: int = 300
    skip_existing_text: bool = True


class TaskManager:
    """
    Manage a queue of PDF processing tasks.

    Usage:
        manager = TaskManager(config)
        manager.on_progress = lambda task: print(f"{task.filename}: {task.progress}%")
        manager.on_complete = lambda task: print(f"Done: {task.filename}")

        manager.add_files(["/path/to/file.pdf"])
        manager.start()
    """

    def __init__(self, config: Optional[TaskManagerConfig] = None):
        self.config = config or TaskManagerConfig()
        self._tasks: dict[int, Task] = {}
        self._task_queue: queue.Queue = queue.Queue()
        self._next_id = 1
        self._worker_thread: Optional[threading.Thread] = None
        self._stop_event = threading.Event()
        self._current_task: Optional[Task] = None
        self._tasks_lock = threading.Lock()

        # Callbacks
        self.on_progress: Optional[Callable[[Task], None]] = None
        self.on_file_complete: Optional[Callable[[Task], None]] = None
        self.on_all_complete: Optional[Callable[[], None]] = None
        self.on_error: Optional[Callable[[Task, str], None]] = None

        # OCR engine and processor (lazy initialization)
        self._ocr_engine = None
        self._pdf_processor = None

    def _init_processor(self):
        """Initialize OCR engine and PDF processor"""
        if self._ocr_engine is None:
            from .ocr_engine import OCREngine
            from .pdf_processor import PDFProcessor

            self._ocr_engine = OCREngine(
                languages=self.config.languages,
                use_gpu=False,
            )
            self._pdf_processor = PDFProcessor(
                self._ocr_engine,
                dpi=self.config.dpi,
            )

    def add_file(self, path: str) -> Optional[Task]:
        """
        Add a single file to the queue.

        Args:
            path: Path to PDF file

        Returns:
            Created Task object, or None if file is invalid
        """
        path = Path(path)
        if not path.exists() or path.suffix.lower() != '.pdf':
            return None

        # Skip hidden files (e.g. .filename_ocr_temp.pdf created by checkpoint system)
        if path.name.startswith('.'):
            return None

        # Determine output path
        if self.config.output_dir:
            output_dir = Path(self.config.output_dir)
            output_dir.mkdir(parents=True, exist_ok=True)
        else:
            output_dir = path.parent

        output_name = path.stem + self.config.output_suffix + ".pdf"
        output_path = output_dir / output_name

        task = Task(
            id=self._next_id,
            input_path=str(path),
            output_path=str(output_path),
        )
        self._next_id += 1

        with self._tasks_lock:
            self._tasks[task.id] = task
        self._task_queue.put(task.id)

        return task

    def add_files(self, paths: list[str]) -> list[Task]:
        """
        Add multiple files to the queue.

        Args:
            paths: List of file paths

        Returns:
            List of created Task objects
        """
        tasks = []
        for path in paths:
            task = self.add_file(path)
            if task:
                tasks.append(task)
        return tasks

    def add_folder(self, folder_path: str, recursive: bool = True) -> list[Task]:
        """
        Add all PDFs from a folder.

        Args:
            folder_path: Path to folder
            recursive: Include subdirectories

        Returns:
            List of created Task objects
        """
        folder = Path(folder_path)
        if not folder.is_dir():
            return []

        pattern = "**/*.pdf" if recursive else "*.pdf"
        pdf_files = list(folder.glob(pattern)) + list(folder.glob(pattern.upper()))

        return self.add_files([str(f) for f in pdf_files])

    def get_task(self, task_id: int) -> Optional[Task]:
        """Get task by ID"""
        with self._tasks_lock:
            return self._tasks.get(task_id)

    def get_all_tasks(self) -> list[Task]:
        """Get all tasks"""
        with self._tasks_lock:
            return list(self._tasks.values())

    def get_pending_count(self) -> int:
        """Get number of pending tasks"""
        with self._tasks_lock:
            return sum(1 for t in self._tasks.values() if t.status == TaskStatus.PENDING)

    def start(self):
        """Start processing queue in background thread"""
        if self._worker_thread and self._worker_thread.is_alive():
            return  # Already running

        self._stop_event.clear()
        self._worker_thread = threading.Thread(target=self._worker_loop, daemon=True)
        self._worker_thread.start()

    def stop(self):
        """Stop processing (completes current task)"""
        self._stop_event.set()
        if self._worker_thread:
            self._worker_thread.join(timeout=1.0)

    def cancel(self):
        """Cancel all pending tasks"""
        self._stop_event.set()

        # Mark pending tasks as cancelled
        with self._tasks_lock:
            for task in self._tasks.values():
                if task.status == TaskStatus.PENDING:
                    task.status = TaskStatus.CANCELLED

        # Clear queue
        while not self._task_queue.empty():
            try:
                self._task_queue.get_nowait()
            except queue.Empty:
                break

    def clear(self):
        """Clear all tasks"""
        self.cancel()
        with self._tasks_lock:
            self._tasks.clear()
        self._next_id = 1

    def remove_task(self, task_id: int) -> bool:
        """Remove a task from the queue"""
        with self._tasks_lock:
            task = self._tasks.get(task_id)
            if not task:
                return False

            if task.status == TaskStatus.PROCESSING:
                return False  # Can't remove active task

            del self._tasks[task_id]
            return True

    def _worker_loop(self):
        """Background worker thread"""
        self._init_processor()

        while not self._stop_event.is_set():
            try:
                task_id = self._task_queue.get(timeout=0.5)
            except queue.Empty:
                # Check if all tasks are done
                with self._tasks_lock:
                    tasks_snapshot = list(self._tasks.values())
                if tasks_snapshot and all(t.status in (TaskStatus.COMPLETED, TaskStatus.FAILED, TaskStatus.CANCELLED)
                       for t in tasks_snapshot if t.status != TaskStatus.PENDING):
                    if self.on_all_complete and tasks_snapshot:
                        self.on_all_complete()
                continue

            with self._tasks_lock:
                task = self._tasks.get(task_id)
            if not task or task.status != TaskStatus.PENDING:
                continue

            self._current_task = task
            task.status = TaskStatus.PROCESSING

            try:
                self._run_task_with_timeout(task, timeout_seconds=1800)
                task.status = TaskStatus.COMPLETED
                task.progress = 100

                if self.on_file_complete:
                    self.on_file_complete(task)

            except Exception as e:
                task.status = TaskStatus.FAILED
                task.error_message = str(e)

                if self.on_error:
                    self.on_error(task, str(e))

            finally:
                self._current_task = None

        # Final completion check
        with self._tasks_lock:
            tasks_snapshot = list(self._tasks.values())
        if self.on_all_complete and tasks_snapshot:
            pending = sum(1 for t in tasks_snapshot if t.status == TaskStatus.PENDING)
            if pending == 0:
                self.on_all_complete()

    def _run_task_with_timeout(self, task: Task, timeout_seconds: float):
        """Run _process_task in a daemon thread with timeout protection."""
        error_holder: list[Optional[Exception]] = [None]

        def _run():
            try:
                self._process_task(task)
            except Exception as e:
                error_holder[0] = e

        thread = threading.Thread(target=_run, daemon=True)
        thread.start()
        thread.join(timeout=timeout_seconds)

        if thread.is_alive():
            raise TimeoutError(
                f"处理超时（超过 {int(timeout_seconds // 60)} 分钟），文件可能已损坏"
            )
        if error_holder[0] is not None:
            raise error_holder[0]

    def _process_task(self, task: Task):
        """Process a single task"""
        def progress_callback(current_page: int, total_pages: int):
            task.current_page = current_page
            task.total_pages = total_pages
            task.progress = int((current_page / total_pages) * 100) if total_pages > 0 else 0

            if self.on_progress:
                self.on_progress(task)

        result = self._pdf_processor.process_file(
            task.input_path,
            task.output_path,
            progress_callback=progress_callback,
            skip_existing_text=self.config.skip_existing_text,
        )

        if not result.success:
            raise Exception(result.error_message or "Processing failed")

    def is_running(self) -> bool:
        """Check if worker thread is active"""
        return self._worker_thread is not None and self._worker_thread.is_alive()

    def update_config(self, **kwargs):
        """
        Update configuration.

        Args:
            **kwargs: Config fields to update (languages, dpi, etc.)
        """
        for key, value in kwargs.items():
            if hasattr(self.config, key):
                setattr(self.config, key, value)

        # Reset processor if languages changed
        if 'languages' in kwargs:
            self._ocr_engine = None
            self._pdf_processor = None
