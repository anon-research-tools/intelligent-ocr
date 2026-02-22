"""
Workers - Background processing threads for OCR tasks

Uses optimized pipelined processing for better performance.

NOTE: OCR imports are done lazily in worker threads to avoid
loading PaddleOCR at GUI startup (saves ~500MB memory).
"""
from pathlib import Path
import threading
from PySide6.QtCore import QThread, Signal, QObject, QSettings


def _get_variants_path() -> str | None:
    """
    Get the path to variants.txt for variant character support.

    Returns:
        Path to variants.txt if it exists, None otherwise.
    """
    # variants.txt is in the ocr_tool directory (same level as desktop/)
    variants_file = Path(__file__).parent.parent / "variants.txt"
    if variants_file.exists():
        return str(variants_file)
    return None

# Lazy imports - these are imported inside methods to avoid loading
# PaddleOCR at GUI startup
# from core.ocr_engine import OCREngine
# from core.pdf_processor import PDFProcessor, ProcessResult
from core.task_manager import Task, TaskStatus


def _run_exports(output_pdf_path: str):
    """
    Run optional exports (TXT, MD, MD+Images) based on user settings.

    Args:
        output_pdf_path: Path to the processed PDF file
    """
    settings = QSettings("SmartOCR", "OCRTool")
    export_txt_enabled = settings.value("export/txt", False, type=bool)
    export_md_enabled = settings.value("export/md", False, type=bool)
    export_md_images_enabled = settings.value("export/md_images", False, type=bool)

    if not export_txt_enabled and not export_md_enabled and not export_md_images_enabled:
        return

    # Lazy import to avoid loading fitz at startup
    from core.pdf_processor import export_txt, export_md, export_md_text_only

    output_path = Path(output_pdf_path)
    base_path = output_path.with_suffix('')  # Remove .pdf extension

    if export_txt_enabled:
        txt_path = str(base_path) + ".txt"
        export_txt(output_pdf_path, txt_path)

    if export_md_enabled:
        md_path = str(base_path) + ".md"
        export_md_text_only(output_pdf_path, md_path)

    if export_md_images_enabled:
        # Use different filename to avoid conflict if both MD options are enabled
        if export_md_enabled:
            md_path = str(base_path) + "_images.md"
        else:
            md_path = str(base_path) + ".md"
        images_dir = str(base_path) + "_images"
        export_md(output_pdf_path, md_path, images_dir)


class OCRWorker(QThread):
    """
    Background thread for OCR processing.

    Uses pipelined processing for improved performance:
    - Prefetches page renders while OCR processes current page
    - Multi-process parallel OCR for multi-core CPU utilization
    - 30-40% speedup without quality loss (up to 3-4x with parallel OCR)
    - Checkpoint/resume support for crash recovery

    Signals:
        progress: (task_id, current_page, total_pages)
        task_complete: (task_id, success, error_message)
        all_complete: ()
    """

    progress = Signal(int, int, int)  # task_id, current_page, total_pages
    task_complete = Signal(int, bool, str)  # task_id, success, error_message
    all_complete = Signal()

    def __init__(
        self,
        tasks: list[Task],
        languages: list[str],
        dpi: int = 300,
        skip_existing_text: bool = True,
        use_pipelined: bool = True,
        quality: str = 'fast',
        enable_checkpoint: bool = True,
        num_workers: int = 1,
        parent=None
    ):
        super().__init__(parent)
        self.tasks = tasks
        self.languages = languages
        self.dpi = dpi
        self.skip_existing_text = skip_existing_text
        self.use_pipelined = use_pipelined
        self.quality = quality
        self.enable_checkpoint = enable_checkpoint
        self.num_workers = num_workers
        self._stop_requested = False
        self._cancel_event = threading.Event()

        self._ocr_engine = None
        self._pdf_processor = None

    def _init_processor(self, languages: list[str] | None = None):
        """Initialize or reinitialize OCR engine and processor (lazy import).

        Args:
            languages: Language list to use. If None, uses self.languages.
                       Pass a new list to reinitialize when languages change.
        """
        langs = languages or self.languages
        # Reinitialize if languages changed
        if self._ocr_engine is not None and langs != self._ocr_engine.languages:
            self._ocr_engine = None
            self._pdf_processor = None

        if self._ocr_engine is None:
            from core.ocr_engine import OCREngine
            from core.pdf_processor import PDFProcessor

            self._ocr_engine = OCREngine(
                languages=langs,
                use_gpu=False,
                quality=self.quality,
            )
            self._pdf_processor = PDFProcessor(
                self._ocr_engine,
                dpi=self.dpi,
                variants_path=_get_variants_path(),
                num_workers=self.num_workers,
            )

    def run(self):
        """Process all tasks, reinitializing OCR engine if language changes."""
        # Initialize with the first task's language
        first_langs = self.tasks[0].languages if self.tasks else self.languages
        try:
            self._init_processor(first_langs)
        except Exception as e:
            for task in self.tasks:
                self.task_complete.emit(task.id, False, f"初始化失败: {str(e)}")
            self.all_complete.emit()
            return

        for task in self.tasks:
            if self._stop_requested:
                break

            try:
                # Reinitialize engine if this task needs different languages
                task_langs = task.languages if task.languages else self.languages
                self._init_processor(task_langs)
                warning = self._process_task(task)
                # Pass any non-fatal warnings as the error_message (success=True)
                self.task_complete.emit(task.id, True, warning or "")
            except Exception as e:
                self.task_complete.emit(task.id, False, str(e))

        self.all_complete.emit()

    def _process_task(self, task: Task) -> str:
        """Process a single task using pipelined or standard processing.

        Returns:
            Warning message string if any non-fatal issues occurred, else "".
        """
        def progress_callback(current_page: int, total_pages: int):
            if not self._stop_requested:
                self.progress.emit(task.id, current_page, total_pages)

        if self.use_pipelined:
            # Use optimized pipelined processing with checkpoint support
            result = self._pdf_processor.process_file_pipelined(
                task.input_path,
                task.output_path,
                progress_callback=progress_callback,
                skip_existing_text=self.skip_existing_text,
                cancel_event=self._cancel_event,
                enable_checkpoint=self.enable_checkpoint,
            )
        else:
            # Use standard processing
            result = self._pdf_processor.process_file(
                task.input_path,
                task.output_path,
                progress_callback=progress_callback,
                skip_existing_text=self.skip_existing_text,
                cancel_event=self._cancel_event,
            )

        if not result.success:
            raise Exception(result.error_message or "处理失败")

        # Run optional exports (TXT, MD)
        _run_exports(task.output_path)

        # Return any non-fatal warnings (e.g., recovered missing pages)
        return "; ".join(result.errors) if result.errors else ""

    def request_stop(self):
        """Request worker to stop after current task"""
        self._stop_requested = True
        self._cancel_event.set()


class SingleFileWorker(QThread):
    """
    Worker for processing a single file (for quick testing).

    Uses pipelined processing for improved performance.
    Supports checkpoint/resume for crash recovery.
    Supports multi-process parallel OCR when num_workers > 1.

    Signals:
        progress: (current_page, total_pages)
        complete: (success, output_path, error_message)
    """

    progress = Signal(int, int)  # current_page, total_pages
    complete = Signal(bool, str, str)  # success, output_path, error_message

    def __init__(
        self,
        input_path: str,
        output_path: str,
        languages: list[str],
        dpi: int = 300,
        use_pipelined: bool = True,
        enable_checkpoint: bool = True,
        quality: str = 'balanced',
        num_workers: int = 1,
        parent=None
    ):
        super().__init__(parent)
        self.input_path = input_path
        self.output_path = output_path
        self.languages = languages
        self.dpi = dpi
        self.use_pipelined = use_pipelined
        self.enable_checkpoint = enable_checkpoint
        self.quality = quality
        self.num_workers = num_workers
        self._stop_requested = False
        self._cancel_event = threading.Event()

    def run(self):
        """Process the file using pipelined processing with checkpoint support"""
        try:
            # Lazy import to avoid loading PaddleOCR at GUI startup
            from core.ocr_engine import OCREngine
            from core.pdf_processor import PDFProcessor

            engine = OCREngine(
                languages=self.languages,
                use_gpu=False,
                quality=self.quality,
            )
            processor = PDFProcessor(
                engine,
                dpi=self.dpi,
                variants_path=_get_variants_path(),
                num_workers=self.num_workers,
            )

            def progress_callback(current: int, total: int):
                if not self._stop_requested:
                    self.progress.emit(current, total)

            if self.use_pipelined:
                result = processor.process_file_pipelined(
                    self.input_path,
                    self.output_path,
                    progress_callback=progress_callback,
                    cancel_event=self._cancel_event,
                    enable_checkpoint=self.enable_checkpoint,
                )
            else:
                result = processor.process_file(
                    self.input_path,
                    self.output_path,
                    progress_callback=progress_callback,
                )

            if result.success:
                # Run optional exports (TXT, MD)
                _run_exports(self.output_path)
                self.complete.emit(True, self.output_path, "")
            else:
                self.complete.emit(False, "", result.error_message)

        except Exception as e:
            self.complete.emit(False, "", str(e))

    def request_stop(self):
        """Request worker to stop"""
        self._stop_requested = True
        self._cancel_event.set()


def get_performance_settings() -> dict:
    """
    Get performance settings from QSettings.

    Returns:
        Dict with 'quality' and 'num_workers' keys.
        num_workers=0 means auto-detect.
    """
    settings = QSettings("SmartOCR", "OCRTool")
    quality = settings.value("performance/quality", "balanced")
    num_workers = settings.value("performance/num_workers", 0, type=int)

    # Handle auto-detect (0 = auto)
    if num_workers == 0:
        try:
            from core.parallel_ocr import _detect_optimal_workers
            num_workers = _detect_optimal_workers()
        except Exception:
            num_workers = 1  # Fallback to single-process

    return {
        'quality': quality,
        'num_workers': num_workers,
    }
