"""
Parallel OCR Processor - Multi-process OCR for improved performance

Features:
- Automatic optimal worker count detection based on CPU and memory
- ProcessPoolExecutor with pre-warmed OCR engines in each worker
- JPEG compression for efficient inter-process data transfer
- Graceful error handling and fallback

Usage:
    processor = ParallelOCRProcessor(quality='balanced', num_workers=None)
    processor.start()
    results = processor.process_batch([(page_num, img_bytes), ...])
    processor.stop()
"""
from __future__ import annotations

import atexit
import logging
import multiprocessing
import os
import platform
import signal
import threading
import time
from concurrent.futures import ProcessPoolExecutor, as_completed
from dataclasses import dataclass
from typing import Callable, Optional
import cv2
import numpy as np

# NOTE: Do NOT force fork mode here. PaddlePaddle's internal threading/state
# corrupts after fork, causing the recognize() call to hang indefinitely.
# The default 'spawn' mode on macOS Python 3.8+ and Windows works correctly
# when run from a proper .py file (not stdin scripts).
# For stdin scripts (e.g., `python << 'EOF' ... EOF`), spawn mode doesn't work
# due to pickling issues, but that's not our use case for the desktop app.

_logger = logging.getLogger(__name__)

# Global registry: track all active processors for atexit cleanup
_active_processors: list = []
_registry_lock = threading.Lock()


def _atexit_cleanup() -> None:
    """Kill any remaining worker processes when Python exits."""
    with _registry_lock:
        processors = list(_active_processors)
    for processor in processors:
        try:
            processor._force_kill_workers()
        except Exception:
            pass


atexit.register(_atexit_cleanup)


def _detect_optimal_workers() -> int:
    """
    Automatically detect optimal number of worker processes.

    Accounts for:
    - Physical CPU cores (not logical/hyperthreaded)
    - Currently available system memory
    - Already-running OCR worker processes (avoids double-counting)
    - Conservative cap to prevent system instability on laptops

    Returns:
        Optimal number of workers (1–2)
    """
    try:
        import psutil

        cpu_count = psutil.cpu_count(logical=False) or 2

        mem_info = psutil.virtual_memory()
        available_gb = mem_info.available / (1024 ** 3)

        # Deduct memory already consumed by existing OCR spawn workers.
        # Each PaddleOCR worker uses ~1.5–2 GB once models are loaded.
        existing_workers = 0
        try:
            current_pid = os.getpid()
            for proc in psutil.process_iter(['pid', 'cmdline']):
                try:
                    cmdline = proc.info.get('cmdline') or []
                    if (proc.info['pid'] != current_pid
                            and any('spawn_main' in c for c in cmdline)):
                        existing_workers += 1
                except (psutil.NoSuchProcess, psutil.AccessDenied):
                    pass
        except Exception:
            pass

        # Subtract ~1.5 GB per existing worker from available headroom
        adjusted_gb = available_gb - (existing_workers * 1.5)

        # Each new worker needs ~1 GB (500 MB models + working memory)
        memory_based = int(max(0.0, adjusted_gb) / 1.0)

        # Leave at least one core for system / GUI
        cpu_based = max(1, cpu_count - 1)

        # Hard cap at 2: more workers rarely help OCR throughput and
        # can make laptops unresponsive
        return max(1, min(memory_based, cpu_based, 2))

    except ImportError:
        return 1
    except Exception:
        return 1


def get_system_info() -> dict:
    """
    Get system information for display in settings UI.

    Returns:
        Dict with cpu_cores, available_memory_gb, recommended_workers
    """
    try:
        import psutil

        cpu_count = psutil.cpu_count(logical=False) or 2
        cpu_logical = psutil.cpu_count(logical=True) or cpu_count
        mem_info = psutil.virtual_memory()
        available_gb = mem_info.available / (1024 ** 3)
        total_gb = mem_info.total / (1024 ** 3)

        return {
            'cpu_cores': cpu_count,
            'cpu_logical': cpu_logical,
            'available_memory_gb': round(available_gb, 1),
            'total_memory_gb': round(total_gb, 1),
            'recommended_workers': _detect_optimal_workers(),
        }
    except Exception:
        return {
            'cpu_cores': 2,
            'cpu_logical': 4,
            'available_memory_gb': 4.0,
            'total_memory_gb': 8.0,
            'recommended_workers': 2,
        }


# Global OCR engine for each worker process (initialized once per process)
_process_ocr_engine = None
_process_quality = None


def _init_worker(quality: str):
    """
    Initialize OCR engine in worker process.

    Called once when the worker process starts.
    The engine is stored globally in the process and reused for all tasks.

    Args:
        quality: OCR quality mode ('fast', 'balanced', 'high')
    """
    global _process_ocr_engine, _process_quality
    from core.ocr_engine import OCREngine

    _process_quality = quality
    _process_ocr_engine = OCREngine(
        languages=['ch', 'en'],
        use_gpu=False,
        quality=quality,
    )


def _ocr_task(task_data: tuple) -> tuple[int, list[dict], Optional[str]]:
    """
    OCR worker function - runs in subprocess.

    Args:
        task_data: Tuple of (page_num, img_bytes)
            - page_num: Page number (0-indexed)
            - img_bytes: JPEG-compressed image bytes

    Returns:
        Tuple of (page_num, ocr_results, error_message)
        - page_num: Same as input
        - ocr_results: List of OCRResult dicts (serializable)
        - error_message: None if success, error string if failed
    """
    global _process_ocr_engine

    page_num, img_bytes = task_data

    try:
        if _process_ocr_engine is None:
            return page_num, [], "OCR engine not initialized"

        # Decode JPEG image
        img_array = cv2.imdecode(
            np.frombuffer(img_bytes, dtype=np.uint8),
            cv2.IMREAD_COLOR
        )

        if img_array is None:
            return page_num, [], "Failed to decode image"

        # Run OCR
        results = _process_ocr_engine.recognize(img_array)

        # Serialize OCRResult objects to dicts for inter-process transfer
        serialized_results = []
        for r in results:
            serialized_results.append({
                'text': r.text,
                'bbox': r.bbox,
                'confidence': r.confidence,
            })

        return page_num, serialized_results, None

    except Exception as e:
        return page_num, [], str(e)


def compress_image_for_transfer(img_array: np.ndarray, quality: int = 95) -> bytes:
    """
    Compress image to JPEG for efficient inter-process transfer.

    JPEG compression reduces data size by ~10x compared to raw numpy,
    significantly improving process pool performance.

    Args:
        img_array: BGR numpy array
        quality: JPEG quality (0-100), 95 is good balance

    Returns:
        JPEG-encoded bytes
    """
    _, encoded = cv2.imencode('.jpg', img_array, [cv2.IMWRITE_JPEG_QUALITY, quality])
    return encoded.tobytes()


@dataclass
class OCRResultDict:
    """OCR result in dict form (for deserialization)"""
    text: str
    bbox: list
    confidence: float

    @property
    def x0(self) -> float:
        return min(p[0] for p in self.bbox)

    @property
    def y0(self) -> float:
        return min(p[1] for p in self.bbox)

    @property
    def x1(self) -> float:
        return max(p[0] for p in self.bbox)

    @property
    def y1(self) -> float:
        return max(p[1] for p in self.bbox)


class ParallelOCRProcessor:
    """
    Multi-process parallel OCR processor.

    Uses ProcessPoolExecutor to distribute OCR work across multiple CPU cores.
    Each worker process has its own OCR engine instance (models loaded once).

    Example:
        with ParallelOCRProcessor(quality='balanced') as processor:
            results = processor.process_batch(tasks, progress_callback)
    """

    def __init__(
        self,
        quality: str = 'balanced',
        num_workers: Optional[int] = None,
    ):
        self.quality = quality
        self.num_workers = num_workers if num_workers is not None else _detect_optimal_workers()
        self._executor: Optional[ProcessPoolExecutor] = None
        self._started = False

    def start(self) -> None:
        """Start the process pool (pre-warms workers with OCR engines)."""
        if self._started:
            return
        self._executor = ProcessPoolExecutor(
            max_workers=self.num_workers,
            initializer=_init_worker,
            initargs=(self.quality,),
        )
        self._started = True
        with _registry_lock:
            if self not in _active_processors:
                _active_processors.append(self)

    def _collect_worker_pids(self) -> list:
        """Return PIDs of currently alive worker processes."""
        pids = []
        if self._executor is None:
            return pids
        try:
            procs = self._executor._processes  # private dict {pid: Process}
            for key, val in procs.items():
                if isinstance(key, int):
                    if val is not None and val.is_alive():
                        pids.append(key)
                elif hasattr(key, 'pid') and hasattr(key, 'is_alive'):
                    if key.is_alive():
                        pids.append(key.pid)
        except Exception:
            pass
        return pids

    def _force_kill_workers(self, pids: Optional[list] = None) -> None:
        """Send SIGKILL to worker PIDs (best-effort)."""
        if pids is None:
            pids = self._collect_worker_pids()
        for pid in pids:
            try:
                os.kill(pid, signal.SIGKILL)
                _logger.warning("ParallelOCR: force-killed worker PID %d", pid)
            except ProcessLookupError:
                pass
            except Exception as exc:
                _logger.debug("ParallelOCR: kill PID %d failed: %s", pid, exc)

    def stop(self) -> None:
        """
        Stop the process pool and release resources.

        Strategy:
        1. Collect worker PIDs before shutdown begins.
        2. Run executor.shutdown(wait=True, cancel_futures=True) in a
           daemon thread with a 15-second timeout.
        3. If shutdown hangs, force-SIGKILL remaining workers.
        """
        if not self._executor:
            self._started = False
            return

        executor = self._executor
        self._executor = None
        self._started = False

        # Deregister from atexit registry
        with _registry_lock:
            try:
                _active_processors.remove(self)
            except ValueError:
                pass

        # Snapshot worker PIDs before shutdown clears them
        worker_pids = []
        try:
            procs = executor._processes
            for key, val in procs.items():
                if isinstance(key, int):
                    worker_pids.append(key)
                elif hasattr(key, 'pid'):
                    worker_pids.append(key.pid)
        except Exception:
            pass

        shutdown_done = threading.Event()

        def _do_shutdown() -> None:
            try:
                try:
                    executor.shutdown(wait=True, cancel_futures=True)
                except TypeError:
                    # Python < 3.9 doesn't have cancel_futures
                    executor.shutdown(wait=True)
            except Exception as exc:
                _logger.debug("ParallelOCR: shutdown() raised: %s", exc)
            finally:
                shutdown_done.set()

        t = threading.Thread(target=_do_shutdown, daemon=True, name="ocr-pool-shutdown")
        t.start()
        t.join(timeout=15.0)

        if not shutdown_done.is_set():
            _logger.warning(
                "ParallelOCR: executor.shutdown() hung after 15 s — "
                "force-killing %d workers: %s",
                len(worker_pids), worker_pids,
            )
            for pid in worker_pids:
                try:
                    os.kill(pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass

    def __del__(self) -> None:
        """Safety net: force-kill workers if object is GC'd without stop()."""
        executor = getattr(self, '_executor', None)
        if executor is not None:
            pids = []
            try:
                for key, val in executor._processes.items():
                    if isinstance(key, int):
                        pids.append(key)
                    elif hasattr(key, 'pid'):
                        pids.append(key.pid)
            except Exception:
                pass
            for pid in pids:
                try:
                    os.kill(pid, signal.SIGKILL)
                except Exception:
                    pass
            try:
                executor.shutdown(wait=False)
            except Exception:
                pass

    def process_batch(
        self,
        tasks: list[tuple[int, bytes]],
        progress_callback: Optional[Callable[[int, int, float, Optional[float]], None]] = None,
    ) -> dict[int, list[OCRResultDict]]:
        """
        Process a batch of pages in parallel.

        Args:
            tasks: List of (page_num, compressed_image_bytes) tuples.
                Images should be JPEG-compressed using compress_image_for_transfer().
            progress_callback: Optional callback called after each page completes.
                Signature: fn(completed_count, total_count, elapsed_time, eta_seconds)

        Returns:
            Dict mapping page_num to list of OCRResultDict objects.
            Failed pages will have empty lists.

        Raises:
            RuntimeError: If processor not started
        """
        if not self._started:
            self.start()

        if not tasks:
            return {}

        results: dict[int, list[OCRResultDict]] = {}
        errors: list[str] = []
        start_time = time.time()

        # Submit all tasks to the pool
        futures = {
            self._executor.submit(_ocr_task, task): task[0]
            for task in tasks
        }

        completed = 0
        total = len(tasks)
        page_times: list[float] = []

        for future in as_completed(futures):
            page_num = futures[future]

            try:
                result_page_num, ocr_results, error_msg = future.result()

                if error_msg:
                    errors.append(f"Page {page_num + 1}: {error_msg}")
                    results[result_page_num] = []
                else:
                    # Convert dicts back to OCRResultDict objects
                    results[result_page_num] = [
                        OCRResultDict(
                            text=r['text'],
                            bbox=r['bbox'],
                            confidence=r['confidence'],
                        )
                        for r in ocr_results
                    ]

            except Exception as e:
                errors.append(f"Page {page_num + 1}: {str(e)}")
                results[page_num] = []

            completed += 1
            elapsed = time.time() - start_time
            page_times.append(elapsed / completed)

            # Calculate ETA
            eta = None
            if page_times and completed < total:
                avg_time_per_page = elapsed / completed
                remaining = total - completed
                eta = avg_time_per_page * remaining

            if progress_callback:
                progress_callback(completed, total, elapsed, eta)

        if errors:
            _logger.warning(
                "Parallel OCR: %d/%d pages failed: %s",
                len(errors), total,
                "; ".join(errors[:5]) + ("..." if len(errors) > 5 else "")
            )

        return results

    def __enter__(self):
        self.start()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.stop()
        return False
