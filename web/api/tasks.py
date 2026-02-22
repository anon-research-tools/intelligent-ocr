"""
Task Management for OCR Web API

Handles task storage, background processing, rate limiting, and cleanup.
"""
import asyncio
import os
import uuid
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional, Dict, Callable
from dataclasses import dataclass, field
from enum import Enum
import threading


class TaskStatus(str, Enum):
    PENDING = "pending"
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


@dataclass
class TaskInfo:
    """Information about an OCR processing task"""
    task_id: str
    filename: str
    status: TaskStatus = TaskStatus.PENDING
    progress: int = 0
    current_page: int = 0
    total_pages: int = 0
    message: str = "Waiting in queue"
    created_at: datetime = field(default_factory=datetime.now)
    completed_at: Optional[datetime] = None
    input_path: Optional[str] = None
    output_path: Optional[str] = None
    languages: list = field(default_factory=lambda: ["ch", "en"])
    dpi: int = 300

    def to_dict(self) -> dict:
        """Convert to dictionary for API response"""
        return {
            "task_id": self.task_id,
            "filename": self.filename,
            "status": self.status.value,
            "progress": self.progress,
            "current_page": self.current_page,
            "total_pages": self.total_pages,
            "message": self.message,
        }


class TaskStore:
    """
    Thread-safe task storage with rate limiting and auto-cleanup.

    Security limits:
    - Max file size: 100MB
    - Max queue: 10 tasks
    - Processing timeout: 30 minutes
    - File retention: 1 hour
    """

    MAX_FILE_SIZE = 100 * 1024 * 1024  # 100MB
    MAX_QUEUE_SIZE = 10
    PROCESSING_TIMEOUT_MINUTES = 30
    FILE_RETENTION_HOURS = 1
    CLEANUP_INTERVAL_MINUTES = 10

    def __init__(
        self,
        upload_dir: Optional[Path] = None,
        output_dir: Optional[Path] = None,
    ):
        self.upload_dir = upload_dir or Path(os.getenv("UPLOAD_DIR", "/tmp/ocr_uploads"))
        self.output_dir = output_dir or Path(os.getenv("OUTPUT_DIR", "/tmp/ocr_outputs"))

        self._tasks: Dict[str, TaskInfo] = {}
        self._lock = threading.Lock()
        self._cleanup_task: Optional[asyncio.Task] = None

        # Ensure directories exist
        self.upload_dir.mkdir(parents=True, exist_ok=True)
        self.output_dir.mkdir(parents=True, exist_ok=True)

    def generate_task_id(self) -> str:
        """Generate a unique 8-character task ID"""
        return str(uuid.uuid4())[:8]

    def get_pending_count(self) -> int:
        """Get count of pending and processing tasks"""
        with self._lock:
            return sum(
                1 for t in self._tasks.values()
                if t.status in (TaskStatus.PENDING, TaskStatus.PROCESSING)
            )

    def can_accept_task(self) -> bool:
        """Check if we can accept a new task (rate limiting)"""
        return self.get_pending_count() < self.MAX_QUEUE_SIZE

    def create_task(
        self,
        filename: str,
        languages: list,
        dpi: int,
    ) -> TaskInfo:
        """
        Create a new task and return it.

        Raises:
            ValueError: If queue is full
        """
        if not self.can_accept_task():
            raise ValueError("Queue is full, please try again later")

        task_id = self.generate_task_id()

        # Generate file paths
        safe_filename = Path(filename).name  # Sanitize filename
        input_path = self.upload_dir / f"{task_id}_{safe_filename}"
        output_path = self.output_dir / f"{task_id}_ocr.pdf"

        task = TaskInfo(
            task_id=task_id,
            filename=safe_filename,
            input_path=str(input_path),
            output_path=str(output_path),
            languages=languages,
            dpi=dpi,
        )

        with self._lock:
            self._tasks[task_id] = task

        return task

    def get_task(self, task_id: str) -> Optional[TaskInfo]:
        """Get task by ID"""
        with self._lock:
            return self._tasks.get(task_id)

    def update_task(
        self,
        task_id: str,
        status: Optional[TaskStatus] = None,
        progress: Optional[int] = None,
        current_page: Optional[int] = None,
        total_pages: Optional[int] = None,
        message: Optional[str] = None,
        output_path: Optional[str] = None,
    ) -> bool:
        """Update task fields. Returns True if task exists."""
        with self._lock:
            task = self._tasks.get(task_id)
            if not task:
                return False

            if status is not None:
                task.status = status
                if status in (TaskStatus.COMPLETED, TaskStatus.FAILED, TaskStatus.CANCELLED):
                    task.completed_at = datetime.now()

            if progress is not None:
                task.progress = progress
            if current_page is not None:
                task.current_page = current_page
            if total_pages is not None:
                task.total_pages = total_pages
            if message is not None:
                task.message = message
            if output_path is not None:
                task.output_path = output_path

            return True

    def cancel_task(self, task_id: str) -> bool:
        """
        Cancel a task if it's pending.

        Returns:
            True if cancelled, False if not found or cannot be cancelled
        """
        with self._lock:
            task = self._tasks.get(task_id)
            if not task:
                return False

            if task.status == TaskStatus.PROCESSING:
                return False  # Cannot cancel processing task

            task.status = TaskStatus.CANCELLED
            task.completed_at = datetime.now()

        # Clean up files
        self._cleanup_task_files(task_id)
        return True

    def delete_task(self, task_id: str) -> bool:
        """Remove a task from storage and clean up files"""
        with self._lock:
            task = self._tasks.pop(task_id, None)
            if not task:
                return False

        self._cleanup_task_files(task_id)
        return True

    def _cleanup_task_files(self, task_id: str):
        """Clean up files associated with a task"""
        for dir_path in [self.upload_dir, self.output_dir]:
            for file_path in dir_path.glob(f"{task_id}_*"):
                try:
                    file_path.unlink()
                except Exception:
                    pass

    def cleanup_old_tasks(self):
        """Remove tasks and files older than retention period"""
        cutoff = datetime.now() - timedelta(hours=self.FILE_RETENTION_HOURS)

        # Find and remove old tasks
        to_remove = []
        with self._lock:
            for task_id, task in self._tasks.items():
                if task.completed_at and task.completed_at < cutoff:
                    to_remove.append(task_id)

        for task_id in to_remove:
            self.delete_task(task_id)

        # Clean up orphaned files
        for dir_path in [self.upload_dir, self.output_dir]:
            if not dir_path.exists():
                continue
            for file_path in dir_path.iterdir():
                if file_path.is_file():
                    try:
                        age = datetime.now() - datetime.fromtimestamp(file_path.stat().st_mtime)
                        if age > timedelta(hours=self.FILE_RETENTION_HOURS):
                            file_path.unlink()
                    except Exception:
                        pass

    async def start_cleanup_loop(self):
        """Start the periodic cleanup loop"""
        while True:
            try:
                await asyncio.sleep(self.CLEANUP_INTERVAL_MINUTES * 60)
                self.cleanup_old_tasks()
            except asyncio.CancelledError:
                break
            except Exception as e:
                print(f"Cleanup error: {e}")


class BackgroundProcessor:
    """
    Handles background PDF processing with asyncio.
    """

    def __init__(self, task_store: TaskStore):
        self.task_store = task_store
        self._ocr_engine = None
        self._pdf_processor = None
        self._init_lock = threading.Lock()

    def _init_processor(self, languages: list, dpi: int):
        """Initialize OCR engine and PDF processor (lazy, cached)"""
        # Import here to avoid circular imports and delay loading
        import sys
        sys.path.insert(0, str(Path(__file__).parent.parent.parent))

        from core.ocr_engine import OCREngine
        from core.pdf_processor import PDFProcessor

        with self._init_lock:
            # Create new engine for these settings
            engine = OCREngine(languages=languages, use_gpu=False)
            processor = PDFProcessor(engine, dpi=dpi)
            return engine, processor

    def process_pdf_sync(
        self,
        task_id: str,
        input_path: str,
        output_path: str,
        languages: list,
        dpi: int,
    ):
        """
        Synchronous PDF processing (runs in thread pool).
        """
        task = self.task_store.get_task(task_id)
        if not task:
            return

        try:
            self.task_store.update_task(
                task_id,
                status=TaskStatus.PROCESSING,
                message="Initializing OCR engine...",
            )

            _, processor = self._init_processor(languages, dpi)

            def progress_callback(current: int, total: int):
                progress = int((current / total) * 100) if total > 0 else 0
                self.task_store.update_task(
                    task_id,
                    progress=progress,
                    current_page=current,
                    total_pages=total,
                    message=f"Processing page {current}/{total}",
                )

            # Use pipelined processing for better performance
            result = processor.process_file_pipelined(
                input_path,
                output_path,
                progress_callback=progress_callback,
            )

            if result.success:
                self.task_store.update_task(
                    task_id,
                    status=TaskStatus.COMPLETED,
                    progress=100,
                    output_path=output_path,
                    message=f"Completed, {result.processed_pages} pages processed",
                )
            else:
                self.task_store.update_task(
                    task_id,
                    status=TaskStatus.FAILED,
                    message=result.error_message or "Processing failed",
                )

        except Exception as e:
            self.task_store.update_task(
                task_id,
                status=TaskStatus.FAILED,
                message=str(e),
            )

        finally:
            # Clean up input file
            try:
                Path(input_path).unlink(missing_ok=True)
            except Exception:
                pass

    async def process_pdf_async(
        self,
        task_id: str,
        input_path: str,
        output_path: str,
        languages: list,
        dpi: int,
    ):
        """Async wrapper for PDF processing"""
        loop = asyncio.get_event_loop()
        await loop.run_in_executor(
            None,
            self.process_pdf_sync,
            task_id, input_path, output_path, languages, dpi,
        )


# Global instances (initialized in app startup)
task_store: Optional[TaskStore] = None
background_processor: Optional[BackgroundProcessor] = None


def init_task_system(upload_dir: Optional[Path] = None, output_dir: Optional[Path] = None):
    """Initialize the task management system"""
    global task_store, background_processor
    task_store = TaskStore(upload_dir, output_dir)
    background_processor = BackgroundProcessor(task_store)
    return task_store, background_processor


def get_task_store() -> TaskStore:
    """Get the global task store instance"""
    if task_store is None:
        raise RuntimeError("Task system not initialized")
    return task_store


def get_processor() -> BackgroundProcessor:
    """Get the global background processor instance"""
    if background_processor is None:
        raise RuntimeError("Task system not initialized")
    return background_processor
