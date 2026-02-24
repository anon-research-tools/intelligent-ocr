"""
Workers - Background processing threads for OCR tasks

Uses optimized pipelined processing for better performance.

NOTE: OCR imports are done lazily in worker threads to avoid
loading PaddleOCR at GUI startup (saves ~500MB memory).
"""
from pathlib import Path
import threading
import time
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
    task_status = Signal(int, str)  # task_id, status_message
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
        use_gpu=None,
        auto_retry_enabled: bool = True,
        max_retries: int = 2,
        image_mode: str = "lossy_85",
        page_retry_limit: int = 2,
        allow_fallback_copy: bool = True,
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
        self.use_gpu = use_gpu
        self.auto_retry_enabled = auto_retry_enabled
        self.max_retries = max(0, int(max_retries))
        self.image_mode = image_mode
        self.page_retry_limit = max(0, int(page_retry_limit))
        self.allow_fallback_copy = allow_fallback_copy
        self._stop_requested = False
        self._cancel_event = threading.Event()

        self._ocr_engine = None
        self._pdf_processor = None
        self._processor_signature = None

    def _init_processor(
        self,
        languages: list[str] | None = None,
        *,
        quality: str | None = None,
        dpi: int | None = None,
        num_workers: int | None = None,
        use_gpu=None,
        image_mode: str | None = None,
    ):
        """Initialize or reinitialize OCR engine and processor (lazy import).

        Args:
            languages: Language list to use. If None, uses self.languages.
                       Pass a new list to reinitialize when languages change.
        """
        langs = languages or self.languages
        effective_quality = quality or self.quality
        effective_dpi = dpi if dpi is not None else self.dpi
        effective_workers = num_workers if num_workers is not None else self.num_workers
        effective_gpu = self.use_gpu if use_gpu is None else use_gpu
        effective_image_mode = image_mode or self.image_mode

        signature = (
            tuple(langs),
            effective_quality,
            effective_dpi,
            effective_workers,
            effective_gpu,
            effective_image_mode,
        )
        if self._processor_signature != signature:
            self._ocr_engine = None
            self._pdf_processor = None

        if self._ocr_engine is None:
            from core.ocr_engine import OCREngine
            from core.pdf_processor import PDFProcessor

            self._ocr_engine = OCREngine(
                languages=langs,
                use_gpu=effective_gpu,
                quality=effective_quality,
            )
            self._pdf_processor = PDFProcessor(
                self._ocr_engine,
                dpi=effective_dpi,
                variants_path=_get_variants_path(),
                num_workers=effective_workers,
                image_mode=effective_image_mode,
                page_retry_limit=self.page_retry_limit,
                allow_fallback_copy=self.allow_fallback_copy,
            )
            self._processor_signature = signature

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
                warning = self._process_task_with_retry(task, task_langs)
                # Pass any non-fatal warnings as the error_message (success=True)
                self.task_complete.emit(task.id, True, warning or "")
            except Exception as e:
                self.task_complete.emit(task.id, False, str(e))

        self.all_complete.emit()

    def _classify_error(self, error_message: str) -> str:
        """Classify errors into retryable / non-retryable / cancelled."""
        if self._stop_requested or self._cancel_event.is_set():
            return "cancelled"

        msg = (error_message or "").lower()
        cancelled_tokens = ["取消", "cancelled", "canceled", "interrupt"]
        if any(token in msg for token in cancelled_tokens):
            return "cancelled"

        non_retry_tokens = [
            "permission denied",
            "权限",
            "无权限",
            "file not found",
            "不存在",
            "无法打开pdf",
            "invalid pdf",
            "损坏",
            "corrupt",
            "encrypted",
            "密码",
        ]
        if any(token in msg for token in non_retry_tokens):
            return "non_retryable"

        retryable_tokens = [
            "timeout",
            "超时",
            "brokenprocesspool",
            "worker",
            "spawn",
            "killed",
            "memory",
            "内存",
            "resource temporarily unavailable",
            "temporarily unavailable",
            "i/o",
            "ioerror",
            "cuda",
            "rocm",
        ]
        if any(token in msg for token in retryable_tokens):
            return "retryable"

        return "non_retryable"

    def _build_attempt_profile(self, attempt_index: int) -> dict:
        """Build processing parameters for each retry attempt."""
        profile = {
            "dpi": self.dpi,
            "quality": self.quality,
            "num_workers": self.num_workers,
            "use_gpu": self.use_gpu,
            "reason": "原始参数",
        }
        if attempt_index == 1:
            profile["num_workers"] = 1
            profile["reason"] = "降级为单进程"
        elif attempt_index >= 2:
            profile["num_workers"] = 1
            profile["quality"] = "fast"
            profile["dpi"] = max(150, self.dpi - 100)
            profile["reason"] = "单进程 + 快速模式 + 降低DPI"
        return profile

    def _process_task_once(self, task: Task, task_langs: list[str], profile: dict) -> str:
        """Process a single task using pipelined or standard processing.

        Returns:
            Warning message string if any non-fatal issues occurred, else "".
        """
        self._init_processor(
            task_langs,
            quality=profile["quality"],
            dpi=profile["dpi"],
            num_workers=profile["num_workers"],
            use_gpu=profile["use_gpu"],
            image_mode=self.image_mode,
        )

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

    def _process_task_with_retry(self, task: Task, task_langs: list[str]) -> str:
        """Run one task with bounded retry and progressive fallback."""
        max_attempts = 1 + (self.max_retries if self.auto_retry_enabled else 0)
        attempt_errors: list[str] = []
        recovered_notes: list[str] = []

        for attempt_index in range(max_attempts):
            profile = self._build_attempt_profile(attempt_index)
            try:
                if attempt_index > 0:
                    self.task_status.emit(
                        task.id,
                        f"重试中 ({attempt_index}/{max_attempts - 1}) · {profile['reason']}"
                    )
                warning = self._process_task_once(task, task_langs, profile)
                if attempt_index > 0:
                    recovered_notes.append(
                        f"已自动重试成功（第{attempt_index + 1}次，{profile['reason']}）"
                    )
                if warning:
                    recovered_notes.append(warning)
                return "；".join(recovered_notes)
            except Exception as exc:
                error_message = str(exc)
                error_kind = self._classify_error(error_message)
                attempt_errors.append(f"尝试{attempt_index + 1}: {error_message}")
                if error_kind == "cancelled":
                    raise Exception("处理已取消")
                if error_kind != "retryable" or attempt_index >= max_attempts - 1:
                    break
                time.sleep(1.5 * (2 ** (attempt_index)))

        raise Exception("；".join(attempt_errors))

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
        use_gpu=None,
        image_mode: str = "lossy_85",
        page_retry_limit: int = 2,
        allow_fallback_copy: bool = True,
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
        self.use_gpu = use_gpu
        self.image_mode = image_mode
        self.page_retry_limit = max(0, int(page_retry_limit))
        self.allow_fallback_copy = allow_fallback_copy
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
                use_gpu=self.use_gpu,
                quality=self.quality,
            )
            processor = PDFProcessor(
                engine,
                dpi=self.dpi,
                variants_path=_get_variants_path(),
                num_workers=self.num_workers,
                image_mode=self.image_mode,
                page_retry_limit=self.page_retry_limit,
                allow_fallback_copy=self.allow_fallback_copy,
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
        Dict with 'quality', 'num_workers', 'use_gpu', retry and image options.
        num_workers=0 means auto-detect.
        use_gpu=None means auto-detect hardware.
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

    # GPU override: 'auto' (None), 'cpu' (False), 'gpu' (True)
    gpu_override = settings.value("performance/gpu_override", "auto")
    use_gpu = None  # auto-detect
    if gpu_override == "cpu":
        use_gpu = False
    elif gpu_override == "gpu":
        use_gpu = True

    # Guardrail: GPU mode uses single worker to avoid process contention.
    is_gpu_mode = False
    if use_gpu is True:
        is_gpu_mode = True
    elif use_gpu is None:
        try:
            from core.hardware import get_device_string
            is_gpu_mode = get_device_string().startswith("gpu")
        except Exception:
            is_gpu_mode = False
    if is_gpu_mode and num_workers > 1:
        num_workers = 1

    return {
        'quality': quality,
        'num_workers': num_workers,
        'use_gpu': use_gpu,
        'auto_retry_enabled': settings.value("performance/auto_retry_enabled", True, type=bool),
        'max_retries': settings.value("performance/max_retries", 2, type=int),
        'image_mode': settings.value("output/image_mode", "lossy_85"),
        'page_retry_limit': settings.value("reliability/page_retry_limit", 2, type=int),
        'allow_fallback_copy': settings.value("reliability/allow_fallback_copy", True, type=bool),
    }
