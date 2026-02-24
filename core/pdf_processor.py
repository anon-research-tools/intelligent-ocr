"""
PDF Processor - Convert scanned PDFs to searchable PDFs with OCR

Features:
- Pipeline parallel processing (prefetch rendering)
- Multi-process parallel OCR for improved performance
- Smart blank page detection
- Memory optimization
- Batch text insertion
- Checkpoint/resume support (断点续传)
- Stability improvements
"""
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
import unicodedata
from typing import Callable, Optional
from concurrent.futures import ThreadPoolExecutor
from queue import Queue, Full
import threading
import time
import numpy as np
import gc
import json
import os
import traceback
import signal
import cv2

import fitz  # PyMuPDF

from .ocr_engine import OCREngine, OCRResult
from .checkpoint import Checkpoint, get_checkpoint_manager
from .variants import VariantMapper


@dataclass
class ProcessResult:
    """Result of processing a PDF file"""
    success: bool
    input_path: str
    output_path: str
    total_pages: int = 0
    processed_pages: int = 0
    skipped_pages: int = 0
    error_message: str = ""
    errors: list[str] = field(default_factory=list)
    # Timing information
    start_time: Optional[datetime] = None
    end_time: Optional[datetime] = None
    elapsed_seconds: float = 0.0
    # Resume information
    resumed_from_checkpoint: bool = False
    resumed_from_page: int = 0
    fallback_pages: list[int] = field(default_factory=list)
    page_retry_stats: dict[int, int] = field(default_factory=dict)
    queue_stall_events: int = 0

    @property
    def has_errors(self) -> bool:
        return bool(self.errors) or bool(self.error_message)

    @property
    def elapsed_formatted(self) -> str:
        """Return elapsed time as formatted string (e.g., '2分30秒')"""
        if self.elapsed_seconds <= 0:
            return "0秒"
        minutes = int(self.elapsed_seconds // 60)
        seconds = int(self.elapsed_seconds % 60)
        if minutes > 0:
            return f"{minutes}分{seconds}秒"
        return f"{seconds}秒"

    @property
    def per_page_seconds(self) -> float:
        """Return average seconds per page"""
        if self.processed_pages > 0:
            return self.elapsed_seconds / self.processed_pages
        return 0.0

    def to_dict(self) -> dict:
        """Convert to dictionary for JSON serialization"""
        return {
            "success": self.success,
            "input_path": self.input_path,
            "output_path": self.output_path,
            "total_pages": self.total_pages,
            "processed_pages": self.processed_pages,
            "skipped_pages": self.skipped_pages,
            "error_message": self.error_message,
            "errors": self.errors,
            "start_time": self.start_time.isoformat() if self.start_time else None,
            "end_time": self.end_time.isoformat() if self.end_time else None,
            "elapsed_seconds": self.elapsed_seconds,
            "elapsed_formatted": self.elapsed_formatted,
            "per_page_seconds": self.per_page_seconds,
            "resumed_from_checkpoint": self.resumed_from_checkpoint,
            "resumed_from_page": self.resumed_from_page,
            "fallback_pages": self.fallback_pages,
            "page_retry_stats": self.page_retry_stats,
            "queue_stall_events": self.queue_stall_events,
        }


class OCRLogger:
    """Simple logger for OCR processing statistics"""

    def __init__(self, log_dir: Optional[str] = None):
        """
        Initialize OCR logger.

        Args:
            log_dir: Directory for log files. Defaults to ~/.ocr_tool/logs/
        """
        if log_dir:
            self.log_dir = Path(log_dir)
        else:
            self.log_dir = Path.home() / ".ocr_tool" / "logs"
        self.log_dir.mkdir(parents=True, exist_ok=True)

    def log_result(self, result: ProcessResult):
        """
        Log a processing result to file.

        Args:
            result: ProcessResult to log
        """
        # Create log entry
        entry = {
            "timestamp": datetime.now().isoformat(),
            **result.to_dict()
        }

        # Append to daily log file
        log_file = self.log_dir / f"ocr_{datetime.now().strftime('%Y%m%d')}.jsonl"
        with open(log_file, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")

    def log_debug(self, message: str, page_num: int = None, file_path: str = None):
        """
        记录调试信息（仅在 OCR_DEBUG=1 时）

        Args:
            message: 调试消息内容（如堆栈跟踪）
            page_num: 可选的页码
            file_path: 可选的文件路径
        """
        if not os.environ.get('OCR_DEBUG'):
            return
        debug_file = self.log_dir / f"debug_{datetime.now().strftime('%Y%m%d')}.log"
        with open(debug_file, 'a', encoding='utf-8') as f:
            timestamp = datetime.now().isoformat()
            context = ""
            if page_num is not None:
                context += f" Page {page_num}"
            if file_path:
                context += f" in {file_path}"
            f.write(f"[{timestamp}]{context}\n{message}\n\n")

    def get_today_stats(self) -> dict:
        """Get statistics for today's processing"""
        log_file = self.log_dir / f"ocr_{datetime.now().strftime('%Y%m%d')}.jsonl"
        if not log_file.exists():
            return {"total_files": 0, "total_pages": 0, "total_seconds": 0}

        total_files = 0
        total_pages = 0
        total_seconds = 0.0

        with open(log_file, "r", encoding="utf-8") as f:
            for line in f:
                try:
                    entry = json.loads(line)
                    if entry.get("success"):
                        total_files += 1
                        total_pages += entry.get("processed_pages", 0)
                        total_seconds += entry.get("elapsed_seconds", 0)
                except json.JSONDecodeError:
                    continue

        return {
            "total_files": total_files,
            "total_pages": total_pages,
            "total_seconds": total_seconds,
            "total_formatted": ProcessResult(
                success=True, input_path="", output_path="",
                elapsed_seconds=total_seconds
            ).elapsed_formatted,
        }


# Global logger instance
_logger: Optional[OCRLogger] = None


def get_logger() -> OCRLogger:
    """Get or create the global OCR logger"""
    global _logger
    if _logger is None:
        _logger = OCRLogger()
    return _logger


def export_txt(pdf_path: str, txt_path: str) -> bool:
    """
    Export text from a searchable PDF to a plain text file.

    Each page is separated by a line of dashes.

    Args:
        pdf_path: Path to input PDF (should be searchable)
        txt_path: Path for output TXT file

    Returns:
        True if export succeeded
    """
    try:
        doc = fitz.open(pdf_path)
        try:
            with open(txt_path, 'w', encoding='utf-8') as f:
                for page_num in range(len(doc)):
                    page = doc[page_num]
                    text = page.get_text().strip()

                    f.write(f"--- 第 {page_num + 1} 页 ---\n\n")
                    f.write(text)
                    f.write("\n\n")
        finally:
            doc.close()
        return True
    except Exception:
        return False


def export_md_text_only(pdf_path: str, md_path: str) -> bool:
    """
    Export text from a searchable PDF to Markdown (text only, no images).

    Args:
        pdf_path: Path to input PDF (should be searchable)
        md_path: Path for output Markdown file

    Returns:
        True if export succeeded
    """
    try:
        doc = fitz.open(pdf_path)
        try:
            with open(md_path, 'w', encoding='utf-8') as f:
                # Write header
                pdf_name = Path(pdf_path).stem
                f.write(f"# {pdf_name}\n\n")

                for page_num in range(len(doc)):
                    page = doc[page_num]
                    text = page.get_text().strip()

                    # Write page header
                    f.write(f"## 第 {page_num + 1} 页\n\n")

                    # Write text
                    if text:
                        f.write(text)
                        f.write("\n\n")

                    f.write("---\n\n")
        finally:
            doc.close()
        return True
    except Exception:
        return False


def export_md(pdf_path: str, md_path: str, images_dir: str) -> bool:
    """
    Export text from a searchable PDF to Markdown with image references.

    Creates an images directory and saves each page as PNG.
    The Markdown file includes image references for each page.

    Args:
        pdf_path: Path to input PDF (should be searchable)
        md_path: Path for output Markdown file
        images_dir: Directory to save page images

    Returns:
        True if export succeeded
    """
    try:
        # Create images directory
        images_path = Path(images_dir)
        images_path.mkdir(parents=True, exist_ok=True)

        doc = fitz.open(pdf_path)
        try:
            # Get the images folder name for relative paths
            images_folder_name = images_path.name

            with open(md_path, 'w', encoding='utf-8') as f:
                # Write header
                pdf_name = Path(pdf_path).stem
                f.write(f"# {pdf_name}\n\n")

                for page_num in range(len(doc)):
                    page = doc[page_num]

                    # Save page as PNG
                    zoom = 2.0  # 144 DPI for good quality
                    mat = fitz.Matrix(zoom, zoom)
                    pix = page.get_pixmap(matrix=mat, alpha=False)
                    image_filename = f"page_{page_num + 1:03d}.png"
                    image_path = images_path / image_filename
                    pix.save(str(image_path))

                    # Get text
                    text = page.get_text().strip()

                    # Write page header and image
                    f.write(f"## 第 {page_num + 1} 页\n\n")
                    f.write(f"![第 {page_num + 1} 页]({images_folder_name}/{image_filename})\n\n")

                    # Write text
                    if text:
                        f.write(text)
                        f.write("\n\n")

                    f.write("---\n\n")
        finally:
            doc.close()
        return True
    except Exception:
        return False


def validate_pdf(path: str) -> tuple[bool, str]:
    """
    Validate that a PDF file can be opened and has pages.

    Call this before adding a file to the processing queue to provide
    early, friendly error messages rather than failing mid-processing.

    Args:
        path: Path to PDF file

    Returns:
        Tuple of (is_valid, error_message).
        is_valid is True if file is a valid non-empty PDF.
        error_message is "" if valid, human-readable message otherwise.
    """
    try:
        doc = fitz.open(path)
        try:
            page_count = len(doc)
        finally:
            doc.close()
        if page_count == 0:
            return False, "PDF文件没有页面"
        return True, ""
    except Exception as e:
        return False, f"无法打开PDF文件: {e}"


class PDFProcessor:
    """
    Process PDFs to make them searchable using OCR.

    Creates dual-layer PDFs with:
    - Original image layer (visible)
    - Hidden text layer (searchable)

    Performance optimizations:
    - Pipeline parallel processing for 30-40% speedup
    - Multi-process parallel OCR for multi-core CPU utilization
    - Smart blank page detection
    - Memory optimization with immediate release
    """

    def __init__(
        self,
        ocr_engine: OCREngine,
        dpi: int = 300,
        min_confidence: float = 0.5,
        prefetch_pages: int = 4,
        blank_page_threshold: float = 0.5,
        variants_path: Optional[str] = None,
        num_workers: int = 1,
        image_mode: str = "lossy_85",
        page_retry_limit: int = 2,
        allow_fallback_copy: bool = True,
    ):
        """
        Initialize PDF processor.

        Args:
            ocr_engine: OCREngine instance for text recognition
            dpi: Resolution for rendering PDF pages
            min_confidence: Minimum confidence threshold for OCR results
            prefetch_pages: Number of pages to prefetch in pipeline mode
            blank_page_threshold: Edge detection threshold for blank page detection
                Lower values = more strict (only skip truly blank pages)
                Default 0.5 is very conservative to avoid false positives
            variants_path: Path to variants.txt file for variant character support.
                When provided, normalized text is also inserted for better search.
            num_workers: Number of parallel OCR worker processes.
                1 = single-process mode (original behavior)
                >1 = multi-process parallel OCR for faster processing
                Use parallel_ocr._detect_optimal_workers() to auto-detect.
            image_mode: Output image insertion mode.
                - "lossy_85": JPEG quality 85 (smaller output, faster save)
                - "lossless": use source pixmap (best quality, larger output)
            page_retry_limit: Page-level OCR retry limit before fallback.
            allow_fallback_copy: Whether to copy original page after retry exhaustion.
        """
        self.ocr_engine = ocr_engine
        self.dpi = dpi
        self.min_confidence = min_confidence
        self.prefetch_pages = prefetch_pages
        self.blank_page_threshold = blank_page_threshold
        self.variant_mapper = VariantMapper(variants_path) if variants_path else None
        self.num_workers = max(1, num_workers)
        self.image_mode = image_mode if image_mode in {"lossy_85", "lossless"} else "lossy_85"
        self.page_retry_limit = max(0, int(page_retry_limit))
        self.allow_fallback_copy = allow_fallback_copy

    def _insert_page_image(self, page, rect, pix):
        """Insert page image using configured output mode."""
        if self.image_mode == "lossless":
            page.insert_image(rect, pixmap=pix)
            return
        page.insert_image(rect, stream=pix.tobytes("jpeg", jpg_quality=85))

    def check_existing_text(self, pdf_path: str) -> bool:
        """
        Check if PDF already has extractable text.

        Args:
            pdf_path: Path to PDF file

        Returns:
            True if PDF has significant text content
        """
        try:
            doc = fitz.open(pdf_path)
            try:
                total_chars = 0

                for page in doc:
                    text = page.get_text()
                    total_chars += len(text.strip())

                    # If we find substantial text, it's not a scanned PDF
                    if total_chars > 100:
                        return True

                return False
            finally:
                doc.close()

        except Exception:
            return False

    def process_file(
        self,
        input_path: str,
        output_path: str,
        progress_callback: Optional[Callable[[int, int], None]] = None,
        skip_existing_text: bool = True,
        log_result: bool = True,
        cancel_event=None,
    ) -> ProcessResult:
        """
        Process a single PDF file.

        Args:
            input_path: Path to input PDF
            output_path: Path for output PDF
            progress_callback: Called with (current_page, total_pages)
            skip_existing_text: Skip pages that already have text
            log_result: Whether to log the result to file
            cancel_event: Optional threading.Event; if set, processing stops early

        Returns:
            ProcessResult with processing details
        """
        input_path = str(input_path)
        output_path = str(output_path)

        # Start timing
        start_time = datetime.now()

        result = ProcessResult(
            success=False,
            input_path=input_path,
            output_path=output_path,
            start_time=start_time,
        )

        input_doc = None
        output_doc = None
        try:
            # Open input PDF
            input_doc = fitz.open(input_path)
            result.total_pages = len(input_doc)

            # Create output PDF
            output_doc = fitz.open()

            for page_num in range(len(input_doc)):
                if cancel_event is not None and cancel_event.is_set():
                    result.error_message = "已取消"
                    result.success = False
                    return result

                if progress_callback:
                    progress_callback(page_num + 1, result.total_pages)

                try:
                    page = input_doc[page_num]

                    # Check if page already has text
                    if skip_existing_text and len(page.get_text().strip()) > 50:
                        # Copy page as-is
                        output_doc.insert_pdf(input_doc, from_page=page_num, to_page=page_num)
                        result.skipped_pages += 1
                        continue

                    # Process page with OCR
                    self._process_page(page, output_doc)
                    result.processed_pages += 1

                except Exception as e:
                    result.errors.append(f"Page {page_num + 1}: {str(e)}")
                    # Try to copy original page on error
                    try:
                        output_doc.insert_pdf(input_doc, from_page=page_num, to_page=page_num)
                    except Exception:
                        pass

            # Save output
            output_doc.save(output_path, garbage=4, deflate=True)
            result.success = True

        except Exception as e:
            result.error_message = str(e)
            result.success = False
        finally:
            if output_doc is not None:
                output_doc.close()
            if input_doc is not None:
                input_doc.close()

        # Record timing
        result.end_time = datetime.now()
        result.elapsed_seconds = (result.end_time - start_time).total_seconds()

        # Log result
        if log_result:
            try:
                get_logger().log_result(result)
            except Exception:
                pass  # Don't fail if logging fails

        return result

    def _process_page(self, page: fitz.Page, output_doc: fitz.Document):
        """
        Process a single page: render, OCR, and create searchable page.

        Args:
            page: Input page
            output_doc: Output document to add processed page to
        """
        rect = page.rect

        # Render page to image at specified DPI
        zoom = self.dpi / 72.0  # PDF default is 72 DPI
        mat = fitz.Matrix(zoom, zoom)
        pix = page.get_pixmap(matrix=mat, alpha=False)

        # Convert pixmap to numpy array for OCR
        img_array = np.frombuffer(pix.samples, dtype=np.uint8)
        img_array = img_array.reshape(pix.height, pix.width, pix.n)

        # Convert RGB to BGR for PaddleOCR (expects BGR)
        if pix.n == 3:
            img_array = img_array[:, :, ::-1].copy()

        # Run OCR
        ocr_results = self.ocr_engine.recognize(img_array)

        # Create new page in output document
        new_page = output_doc.new_page(width=rect.width, height=rect.height)

        # Insert original image
        self._insert_page_image(new_page, rect, pix)

        # Add invisible text layer
        self._add_text_layer(new_page, ocr_results, pix.height, rect.height, zoom)

    def _add_text_layer(
        self,
        page: fitz.Page,
        ocr_results: list[OCRResult],
        img_height: float,
        page_height: float,
        zoom: float,
    ):
        """
        Add invisible text layer to page.

        If variant_mapper is configured, also inserts normalized text at the same
        position for variant character search support.

        Args:
            page: Output page to add text to
            ocr_results: OCR results with bounding boxes
            img_height: Height of rendered image in pixels
            page_height: Height of PDF page in points
            zoom: Zoom factor used for rendering
        """
        for result in ocr_results:
            if result.confidence < self.min_confidence:
                continue

            text = unicodedata.normalize('NFKC', result.text.strip())
            if not text:
                continue

            # Convert image coordinates to PDF coordinates
            # PyMuPDF uses top-left origin (same as image), so just scale
            x0 = result.x0 / zoom
            y0 = result.y0 / zoom
            x1 = result.x1 / zoom
            y1 = result.y1 / zoom

            rect_width = x1 - x0
            rect_height = y1 - y0

            # Calculate appropriate font size
            # Estimate character width (CJK characters are roughly square)
            char_count = len(text)

            # Check if text is likely vertical (height > width * 2)
            is_vertical = rect_height > rect_width * 2

            if is_vertical:
                # For vertical text, font size based on width
                fontsize = min(rect_width * 0.9, rect_height / char_count * 0.9)
            else:
                # For horizontal text, font size based on height and width
                fontsize = min(rect_height * 0.9, rect_width / char_count * 1.5)

            fontsize = max(4, min(fontsize, 72))

            # Prepare texts to insert: original + normalized (if different)
            texts_to_insert = [text]
            if self.variant_mapper and self.variant_mapper.needs_normalization(text):
                normalized_text = self.variant_mapper.normalize(text)
                texts_to_insert.append(normalized_text)

            for insert_text in texts_to_insert:
                try:
                    if is_vertical:
                        # For vertical text: use rotate=270 to flow text top-to-bottom
                        # This keeps text searchable as a unit while positioning correctly
                        # Insert at top-right of the text column, text flows downward
                        point = fitz.Point(x1, y0)
                        page.insert_text(
                            point,
                            insert_text,
                            fontsize=fontsize,
                            fontname="china-s",
                            render_mode=3,  # Invisible text
                            rotate=270,     # Text flows top to bottom
                        )
                    else:
                        # For horizontal text: use textbox as before
                        text_rect = fitz.Rect(x0, y0, x1, y1)
                        rc = page.insert_textbox(
                            text_rect,
                            insert_text,
                            fontsize=fontsize,
                            fontname="china-s",
                            align=fitz.TEXT_ALIGN_LEFT,
                            render_mode=3,
                        )
                        if rc < 0:
                            fontsize_small = fontsize * 0.5
                            page.insert_textbox(
                                text_rect,
                                insert_text,
                                fontsize=fontsize_small,
                                fontname="china-s",
                                align=fitz.TEXT_ALIGN_LEFT,
                                render_mode=3,
                            )
                except Exception:
                    # Fallback: use insert_text at the start of rect
                    try:
                        point = fitz.Point(x0, y0 + fontsize)
                        page.insert_text(
                            point,
                            insert_text,
                            fontsize=min(fontsize, 12),
                            fontname="china-s",
                            render_mode=3,
                        )
                    except Exception:
                        pass

    def process_folder(
        self,
        input_folder: str,
        output_folder: Optional[str] = None,
        suffix: str = "_ocr",
        progress_callback: Optional[Callable[[str, int, int], None]] = None,
    ) -> list[ProcessResult]:
        """
        Process all PDFs in a folder.

        Args:
            input_folder: Path to folder containing PDFs
            output_folder: Output folder (same as input if None)
            suffix: Suffix to add to output filenames
            progress_callback: Called with (filename, current_page, total_pages)

        Returns:
            List of ProcessResult for each file
        """
        input_folder = Path(input_folder)
        output_folder = Path(output_folder) if output_folder else input_folder

        output_folder.mkdir(parents=True, exist_ok=True)

        results = []
        pdf_files = list(input_folder.glob("*.pdf")) + list(input_folder.glob("*.PDF"))

        for pdf_file in pdf_files:
            output_name = pdf_file.stem + suffix + ".pdf"
            output_path = output_folder / output_name

            def page_callback(current, total):
                if progress_callback:
                    progress_callback(pdf_file.name, current, total)

            result = self.process_file(
                str(pdf_file),
                str(output_path),
                progress_callback=page_callback,
            )
            results.append(result)

        return results

    # ========== Performance Optimized Methods ==========

    def _is_blank_page(self, pix: fitz.Pixmap) -> bool:
        """
        Detect if a page is blank using edge detection.

        Does NOT affect OCR quality - only skips truly blank pages.

        Args:
            pix: Rendered page pixmap

        Returns:
            True if page appears to be blank
        """
        # Convert pixmap to numpy array
        img = np.frombuffer(pix.samples, dtype=np.uint8)
        img = img.reshape(pix.height, pix.width, pix.n)

        # Convert to grayscale
        if pix.n >= 3:
            gray = np.mean(img[:, :, :3], axis=2)
        else:
            gray = img[:, :, 0].astype(np.float32)

        # Calculate edge response using simple gradient
        # This is much faster than cv2.Canny and sufficient for blank detection
        grad_x = np.abs(np.diff(gray, axis=1))
        grad_y = np.abs(np.diff(gray, axis=0))

        # Average edge magnitude
        edge_magnitude = (np.mean(grad_x) + np.mean(grad_y)) / 2

        # If edge response is very low, the page is blank
        return edge_magnitude < self.blank_page_threshold

    def _adaptive_zoom(
        self,
        page: fitz.Page,
        base_zoom: float,
        max_pixels: int = 100_000_000,
        max_side: int = 3800,
    ) -> float:
        """
        Calculate adaptive zoom factor to prevent OOM and PaddleOCR rescaling waste.

        Args:
            page: PDF page
            base_zoom: Base zoom factor (dpi / 72)
            max_pixels: Maximum pixels allowed (default 100M = ~380MB for RGB)
            max_side: Maximum pixels per side (default 3800, just under PaddleOCR's
                      4000px internal limit to avoid silent quality-degrading rescale)

        Returns:
            Adjusted zoom factor
        """
        rect = page.rect
        base_width = rect.width * base_zoom
        base_height = rect.height * base_zoom
        base_pixels = base_width * base_height

        zoom = base_zoom

        # Cap per-side to avoid PaddleOCR's silent 4000px rescale (wastes render work)
        if max(base_width, base_height) > max_side:
            side_scale = max_side / max(base_width, base_height)
            zoom = base_zoom * side_scale
            base_width *= side_scale
            base_height *= side_scale
            base_pixels = base_width * base_height

        # Cap total pixels to prevent OOM
        if base_pixels > max_pixels:
            scale = (max_pixels / base_pixels) ** 0.5
            zoom *= scale

        return zoom

    def _pix_to_bgr_array(self, pix: fitz.Pixmap) -> np.ndarray:
        """
        Convert PyMuPDF Pixmap to BGR numpy array for OCR.

        This conversion is done in the main thread just before OCR to avoid
        storing both pix and img_array in the render queue (memory optimization).

        Args:
            pix: PyMuPDF Pixmap object

        Returns:
            BGR numpy array suitable for PaddleOCR
        """
        # Convert pixmap to numpy array
        img_array = np.frombuffer(pix.samples, dtype=np.uint8)
        img_array = img_array.reshape(pix.height, pix.width, pix.n)

        # Convert RGB to BGR for PaddleOCR
        if pix.n == 3:
            img_array = img_array[:, :, ::-1].copy()

        return img_array

    def _compress_image_for_parallel(self, img_array: np.ndarray, quality: int = 95) -> bytes:
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

    def _render_page_to_pixmap(
        self,
        page: fitz.Page,
        zoom: float
    ) -> tuple[fitz.Pixmap, fitz.Rect, float]:
        """
        Render a page to Pixmap for later OCR processing.

        Uses adaptive DPI to prevent OOM on very large pages.
        The Pixmap can be converted to numpy array using _pix_to_bgr_array()
        in the main thread just before OCR (memory optimization).

        Args:
            page: PDF page to render
            zoom: Zoom factor for rendering

        Returns:
            Tuple of (pixmap, page_rect, actual_zoom)
            Note: actual_zoom may differ from requested zoom for large pages
                  to prevent OOM. Callers must use actual_zoom for coordinate
                  conversions to avoid misalignment.
        """
        rect = page.rect

        # Apply adaptive zoom to prevent OOM
        actual_zoom = self._adaptive_zoom(page, zoom)
        mat = fitz.Matrix(actual_zoom, actual_zoom)
        pix = page.get_pixmap(matrix=mat, alpha=False)

        return pix, rect, actual_zoom

    def _add_text_layer_batched(
        self,
        page: fitz.Page,
        ocr_results: list[OCRResult],
        zoom: float,
    ):
        """
        Add invisible text layer with batched operations.

        Optimized version that collects all text operations first,
        then applies them in sequence for better performance.

        If variant_mapper is configured, also inserts normalized text at the same
        position for variant character search support.

        Args:
            page: Output page to add text to
            ocr_results: OCR results with bounding boxes
            zoom: Zoom factor used for rendering
        """
        # Collect all valid text operations first
        # Format: (x0, y0, x1, y1, text, fontsize, is_vertical)
        text_operations = []

        for result in ocr_results:
            if result.confidence < self.min_confidence:
                continue

            text = unicodedata.normalize('NFKC', result.text.strip())
            if not text:
                continue

            # Convert image coordinates to PDF coordinates
            # PyMuPDF uses top-left origin (same as image), so just scale
            x0 = result.x0 / zoom
            y0 = result.y0 / zoom
            x1 = result.x1 / zoom
            y1 = result.y1 / zoom

            rect_width = x1 - x0
            rect_height = y1 - y0

            # Calculate appropriate font size
            char_count = len(text)
            is_vertical = rect_height > rect_width * 2

            if is_vertical:
                fontsize = min(rect_width * 0.9, rect_height / char_count * 0.9)
            else:
                fontsize = min(rect_height * 0.9, rect_width / char_count * 1.5)

            fontsize = max(4, min(fontsize, 72))

            # Add original text
            text_operations.append((x0, y0, x1, y1, text, fontsize, is_vertical))

            # Add normalized text if different (for variant character search)
            if self.variant_mapper and self.variant_mapper.needs_normalization(text):
                normalized_text = self.variant_mapper.normalize(text)
                text_operations.append((x0, y0, x1, y1, normalized_text, fontsize, is_vertical))

        # Apply all text operations
        for x0, y0, x1, y1, text, fontsize, is_vertical in text_operations:
            try:
                if is_vertical:
                    # For vertical text: use rotate=270 to flow text top-to-bottom
                    # This keeps text searchable as a unit while positioning correctly
                    point = fitz.Point(x1, y0)
                    page.insert_text(
                        point,
                        text,
                        fontsize=fontsize,
                        fontname="china-s",
                        render_mode=3,  # Invisible text
                        rotate=270,     # Text flows top to bottom
                    )
                else:
                    # For horizontal text: use textbox
                    text_rect = fitz.Rect(x0, y0, x1, y1)
                    rc = page.insert_textbox(
                        text_rect,
                        text,
                        fontsize=fontsize,
                        fontname="china-s",
                        align=fitz.TEXT_ALIGN_LEFT,
                        render_mode=3,
                    )
                    if rc < 0:
                        page.insert_textbox(
                            text_rect,
                            text,
                            fontsize=fontsize * 0.5,
                            fontname="china-s",
                            align=fitz.TEXT_ALIGN_LEFT,
                            render_mode=3,
                        )
            except Exception:
                try:
                    point = fitz.Point(x0, y0 + fontsize)
                    page.insert_text(
                        point,
                        text,
                        fontsize=min(fontsize, 12),
                        fontname="china-s",
                        render_mode=3,
                    )
                except Exception:
                    pass

    def process_file_pipelined(
        self,
        input_path: str,
        output_path: str,
        progress_callback: Optional[Callable[[int, int], None]] = None,
        skip_existing_text: bool = True,
        cancel_event: Optional[threading.Event] = None,
        log_result: bool = True,
        enable_checkpoint: bool = True,
    ) -> ProcessResult:
        """
        Process a PDF file using pipelined parallel processing.

        This optimized version prefetches page renders while OCR processes
        the current page, achieving 30-40% speedup without quality loss.

        Features:
        - Pipeline parallel processing for 30-40% speedup
        - Multi-process parallel OCR (when num_workers > 1)
        - Checkpoint/resume support (断点续传)
        - Automatic recovery from interruptions
        - Memory-efficient processing

        Pipeline stages:
        1. Render thread: Prefetches next N pages in background
        2. Main thread: Performs OCR (serial or parallel based on num_workers)
        3. Output: Generates searchable PDF pages

        Args:
            input_path: Path to input PDF
            output_path: Path for output PDF
            progress_callback: Called with (current_page, total_pages)
            skip_existing_text: Skip pages that already have text
            cancel_event: Optional event to signal cancellation
            log_result: Whether to log the result to file
            enable_checkpoint: Enable checkpoint/resume support

        Returns:
            ProcessResult with processing details
        """
        input_path = str(input_path)
        output_path = str(output_path)

        # Start timing
        start_time = datetime.now()

        result = ProcessResult(
            success=False,
            input_path=input_path,
            output_path=output_path,
            start_time=start_time,
        )

        checkpoint = None
        checkpoint_mgr = None
        temp_output_path = None

        try:
            # Open input PDF
            input_doc = fitz.open(input_path)
            result.total_pages = len(input_doc)

            zoom = self.dpi / 72.0

            # Check for existing checkpoint
            if enable_checkpoint:
                checkpoint_mgr = get_checkpoint_manager()
                checkpoint = checkpoint_mgr.load_checkpoint(input_path)

                if checkpoint:
                    # Validate checkpoint matches current settings
                    if (checkpoint.total_pages != result.total_pages or
                        checkpoint.dpi != self.dpi):
                        # Settings changed, start fresh
                        checkpoint_mgr.delete_checkpoint(input_path)
                        checkpoint = None
                    else:
                        # Resume from checkpoint
                        result.resumed_from_checkpoint = True
                        result.resumed_from_page = checkpoint.next_page
                        result.processed_pages = len(checkpoint.completed_pages)
                        result.skipped_pages = len(checkpoint.skipped_pages)
                        temp_output_path = checkpoint.temp_output_path

                if not checkpoint:
                    # Create new checkpoint
                    checkpoint = checkpoint_mgr.create_checkpoint(
                        input_path=input_path,
                        output_path=output_path,
                        total_pages=result.total_pages,
                        dpi=self.dpi,
                        languages=self.ocr_engine.languages if hasattr(self.ocr_engine, 'languages') else ['ch'],
                    )
                    temp_output_path = checkpoint.temp_output_path

            # Open or create output PDF
            if temp_output_path and Path(temp_output_path).exists() and result.resumed_from_checkpoint:
                # Resume: open existing temp file
                try:
                    output_doc = fitz.open(temp_output_path)

                    # Validate temp file has expected page count
                    expected_pages = len(checkpoint.completed_pages) + len(checkpoint.skipped_pages) + len(checkpoint.failed_pages)
                    if len(output_doc) != expected_pages:
                        raise ValueError(f"Temp file page count mismatch: {len(output_doc)} vs {expected_pages}")

                except Exception:
                    # Temp file corrupted or unreadable, start fresh
                    try:
                        output_doc.close()
                    except Exception:
                        pass
                    output_doc = fitz.open()
                    checkpoint_mgr.delete_checkpoint(input_path)
                    checkpoint = checkpoint_mgr.create_checkpoint(
                        input_path=input_path,
                        output_path=output_path,
                        total_pages=result.total_pages,
                        dpi=self.dpi,
                        languages=self.ocr_engine.languages if hasattr(self.ocr_engine, 'languages') else ['ch'],
                    )
                    temp_output_path = checkpoint.temp_output_path
                    result.resumed_from_checkpoint = False
                    result.resumed_from_page = 0
                    result.processed_pages = 0
                    result.skipped_pages = 0
            else:
                # Fresh start: create new document
                output_doc = fitz.open()

            # Determine starting page for render thread
            start_page = 0
            if checkpoint and result.resumed_from_checkpoint:
                start_page = checkpoint.next_page
                if start_page < 0:
                    # All pages done, just finalize
                    start_page = result.total_pages

            # Queue for prefetched page data (memory optimized - no img_array)
            # Format: (page_num, pix, rect, actual_zoom, should_skip, has_existing_text)
            # Note: actual_zoom may differ from requested zoom for large pages (adaptive DPI)
            # Note: img_array is NOT stored in queue to save memory; convert pix -> img_array
            #       in main thread using _pix_to_bgr_array() just before OCR
            render_queue: Queue = Queue(maxsize=self.prefetch_pages)
            render_error = [None]  # Use list to allow modification in thread
            ocr_completed_pages: set[int] = set()
            fallback_pages: set[int] = set()

            def _record_retry(page_num: int):
                key = page_num + 1
                result.page_retry_stats[key] = result.page_retry_stats.get(key, 0) + 1

            def _copy_page_with_fallback(page_num: int, reason: str):
                """Copy original page after retry exhaustion and record details."""
                if not self.allow_fallback_copy:
                    raise RuntimeError(f"Page {page_num + 1}: {reason}")

                try:
                    output_doc.insert_pdf(input_doc, from_page=page_num, to_page=page_num)
                    fallback_pages.add(page_num)
                    result.fallback_pages = sorted(p + 1 for p in fallback_pages)
                    result.errors.append(f"Page {page_num + 1}: OCR失败后回填原页（{reason}）")
                    if checkpoint and checkpoint_mgr:
                        checkpoint_mgr.mark_page_failed(checkpoint, page_num)
                    if progress_callback:
                        progress_callback(page_num + 1, result.total_pages)
                except Exception as copy_exc:
                    raise RuntimeError(
                        f"Page {page_num + 1}: 回填原页失败（{copy_exc}）"
                    ) from copy_exc

            def _recognize_with_retry(page_num: int, pix) -> list:
                """Run OCR with bounded retry on a single page image."""
                last_error: Optional[Exception] = None
                for attempt in range(self.page_retry_limit + 1):
                    if cancel_event and cancel_event.is_set():
                        raise RuntimeError("处理已取消")
                    try:
                        img_array = self._pix_to_bgr_array(pix)
                        ocr_results = self.ocr_engine.recognize(img_array)
                        del img_array
                        return ocr_results
                    except Exception as exc:
                        last_error = exc
                        _record_retry(page_num)
                        if attempt < self.page_retry_limit:
                            time.sleep(0.5 * (2 ** attempt))
                        continue
                raise RuntimeError(str(last_error) if last_error else "OCR失败")

            def render_worker():
                """Background thread that prefetches page renders"""
                def safe_put(item):
                    """Put item to queue with timeout, checking cancel_event to avoid deadlock.

                    When user cancels, the main thread may stop consuming from the queue.
                    Without timeout, put() would block forever if queue is full, causing deadlock
                    since main thread is waiting for render_thread.join().

                    Returns:
                        True if item was put successfully, False if cancelled or max retries exceeded.
                    """
                    retry_count = 0
                    max_retries = 120  # 120 * 0.5s = 60 seconds max wait (OCR can take 10-30s per page)
                    while retry_count < max_retries:
                        if cancel_event and cancel_event.is_set():
                            return False  # Cancelled, don't put
                        try:
                            render_queue.put(item, timeout=0.5)
                            return True
                        except Full:
                            # Queue full, retry after checking cancel
                            retry_count += 1
                        except Exception:
                            retry_count += 1
                    # Max retries exceeded - return False
                    result.queue_stall_events += 1
                    return False

                try:
                    for page_num in range(start_page, len(input_doc)):
                        if cancel_event and cancel_event.is_set():
                            break

                        # Skip already processed pages (from checkpoint)
                        if checkpoint:
                            if (page_num in checkpoint.completed_pages or
                                page_num in checkpoint.skipped_pages or
                                page_num in checkpoint.failed_pages):
                                continue

                        page = input_doc[page_num]

                        # Check if page already has text
                        has_existing_text = len(page.get_text().strip()) > 50

                        if skip_existing_text and has_existing_text:
                            # Signal to skip this page (actual_zoom=0.0 as placeholder, won't be used)
                            if not safe_put((page_num, None, None, 0.0, True, True)):
                                break  # Cancelled
                            continue

                        # Render page to Pixmap only (no img_array to save memory)
                        pix = None  # Initialize for cleanup
                        try:
                            # Check memory pressure - reduce DPI if memory is low
                            try:
                                import psutil
                                mem = psutil.virtual_memory()
                                if mem.available < 500 * 1024 * 1024:  # <500MB available
                                    effective_zoom = max(zoom * 0.8, 1.0)
                                else:
                                    effective_zoom = zoom
                            except ImportError:
                                effective_zoom = zoom
                            pix, rect, actual_zoom = self._render_page_to_pixmap(page, effective_zoom)

                            # Check for blank page
                            is_blank = self._is_blank_page(pix)

                            if not safe_put((
                                page_num,
                                pix,
                                rect,
                                actual_zoom,  # May differ from zoom for large pages
                                is_blank,     # should_skip if blank
                                False,        # not existing text skip
                            )):
                                # Put failed (cancelled or max retries) - release pixmap
                                pix = None
                                break  # Cancelled
                        except Exception as e:
                            # Release pixmap on error
                            pix = None
                            # On render error, signal to copy original page
                            if not safe_put((page_num, None, None, 0.0, False, False, str(e))):
                                break  # Cancelled

                except Exception as e:
                    render_error[0] = e
                finally:
                    # Signal end of rendering (use safe_put to avoid deadlock on cancel)
                    safe_put(None)

            # Start render thread
            render_thread = threading.Thread(target=render_worker, daemon=True)
            render_thread.start()

            # Main loop: OCR and output generation
            pages_since_save = 0
            save_interval = 10  # Save temp file every 10 pages (balance between I/O and recovery)

            # Choose processing mode based on num_workers
            use_parallel_ocr = self.num_workers > 1

            if use_parallel_ocr:
                # Multi-process parallel OCR mode
                from .parallel_ocr import ParallelOCRProcessor, compress_image_for_transfer

                parallel_processor = ParallelOCRProcessor(
                    quality=self.ocr_engine.quality if hasattr(self.ocr_engine, 'quality') else 'balanced',
                    num_workers=self.num_workers,
                )
                parallel_processor.start()

                try:
                    # Batch collection for parallel OCR
                    batch_size = self.num_workers * 2  # Optimal batch size
                    batch_tasks = []  # [(page_num, img_bytes), ...]
                    batch_pixmaps = {}  # page_num -> (pix, rect, actual_zoom)
                    pending_skip_pages = []  # Pages to skip (existing text or blank)
                    inserted_page_order = []  # Track insertion order for final sort

                    def process_ocr_batch():
                        """Process collected batch with parallel OCR"""
                        nonlocal pages_since_save

                        if not batch_tasks:
                            return

                        # Run parallel OCR
                        ocr_results_map = parallel_processor.process_batch(batch_tasks)

                        # Process results in page order
                        for page_num in sorted(batch_pixmaps.keys()):
                            if cancel_event and cancel_event.is_set():
                                break

                            pix, rect, actual_zoom = batch_pixmaps[page_num]
                            ocr_results = ocr_results_map.get(page_num)
                            if ocr_results is None:
                                try:
                                    ocr_results = _recognize_with_retry(page_num, pix)
                                except Exception as retry_exc:
                                    _copy_page_with_fallback(page_num, str(retry_exc))
                                    inserted_page_order.append(page_num)
                                    pix = None
                                    continue

                            try:
                                # Create new page in output document
                                new_page = output_doc.new_page(width=rect.width, height=rect.height)

                                # Insert original image
                                self._insert_page_image(new_page, rect, pix)

                                # Add invisible text layer
                                # Convert OCRResultDict to compatible format
                                self._add_text_layer_batched(new_page, ocr_results, actual_zoom)

                                result.processed_pages += 1
                                ocr_completed_pages.add(page_num)
                                inserted_page_order.append(page_num)

                                # Mark page as completed in checkpoint
                                if checkpoint and checkpoint_mgr:
                                    checkpoint_mgr.mark_page_completed(checkpoint, page_num)

                                # Progress callback
                                if progress_callback:
                                    progress_callback(page_num + 1, result.total_pages)

                            except Exception as e:
                                error_msg = str(e)
                                full_error = traceback.format_exc()
                                get_logger().log_debug(full_error, page_num=page_num + 1, file_path=input_path)
                                _copy_page_with_fallback(page_num, error_msg)
                                inserted_page_order.append(page_num)

                            finally:
                                # Memory cleanup
                                pix = None

                        # Periodic save (use garbage=0/deflate=False for speed)
                        pages_since_save += len(batch_tasks)
                        if pages_since_save >= save_interval and temp_output_path:
                            try:
                                output_doc.save(temp_output_path, garbage=0, deflate=False, incremental=False)
                                pages_since_save = 0
                            except Exception:
                                pass

                        # Clear batch
                        batch_tasks.clear()
                        batch_pixmaps.clear()
                        gc.collect()

                    def process_skip_pages():
                        """Process pending skip pages in order"""
                        for skip_item in pending_skip_pages:
                            page_num, is_existing = skip_item
                            output_doc.insert_pdf(input_doc, from_page=page_num, to_page=page_num)
                            inserted_page_order.append(page_num)
                            result.skipped_pages += 1
                            if checkpoint and checkpoint_mgr:
                                checkpoint_mgr.mark_page_skipped(checkpoint, page_num)
                            if progress_callback:
                                progress_callback(page_num + 1, result.total_pages)
                        pending_skip_pages.clear()

                    while True:
                        if cancel_event and cancel_event.is_set():
                            break

                        item = render_queue.get()
                        if item is None:
                            # End of pages - process remaining batch
                            process_skip_pages()
                            process_ocr_batch()
                            break

                        # Handle potential error in render (7 items = error tuple)
                        if len(item) == 7:
                            page_num, _, _, _, _, _, error_msg = item
                            _copy_page_with_fallback(page_num, f"渲染失败: {error_msg}")
                            continue

                        # Normal tuple: 6 items
                        page_num, pix, rect, actual_zoom, should_skip, is_existing_text = item

                        if is_existing_text or should_skip:
                            # Queue skip pages to process in order later
                            pending_skip_pages.append((page_num, is_existing_text))
                            continue

                        # Compress image for inter-process transfer
                        img_array = self._pix_to_bgr_array(pix)
                        img_bytes = self._compress_image_for_parallel(img_array)
                        del img_array

                        batch_tasks.append((page_num, img_bytes))
                        batch_pixmaps[page_num] = (pix, rect, actual_zoom)

                        # Process batch when full
                        if len(batch_tasks) >= batch_size:
                            process_skip_pages()
                            process_ocr_batch()

                finally:
                    parallel_processor.stop()

                # Fix page order: skip pages inserted before OCR batches can cause wrong order.
                # e.g. pages [0(ocr),1(skip),2(ocr)] get inserted as [1,0,2] instead of [0,1,2].
                if (inserted_page_order and
                        inserted_page_order != sorted(inserted_page_order) and
                        len(inserted_page_order) == len(output_doc)):
                    sort_indices = sorted(range(len(inserted_page_order)),
                                         key=lambda i: inserted_page_order[i])
                    output_doc.select(sort_indices)

            else:
                # Single-process mode (original behavior)
                while True:
                    if cancel_event and cancel_event.is_set():
                        break

                    item = render_queue.get()
                    if item is None:
                        break  # End of pages

                    # Handle potential error in render (7 items = error tuple)
                    if len(item) == 7:
                        page_num, _, _, _, _, _, error_msg = item
                        _copy_page_with_fallback(page_num, f"渲染失败: {error_msg}")
                        continue

                    # Normal tuple: 6 items (no img_array - memory optimized)
                    # Format: (page_num, pix, rect, actual_zoom, should_skip, is_existing_text)
                    page_num, pix, rect, actual_zoom, should_skip, is_existing_text = item

                    if progress_callback:
                        progress_callback(page_num + 1, result.total_pages)

                    try:
                        if is_existing_text:
                            # Page has existing text, copy as-is
                            output_doc.insert_pdf(input_doc, from_page=page_num, to_page=page_num)
                            result.skipped_pages += 1
                            if checkpoint and checkpoint_mgr:
                                checkpoint_mgr.mark_page_skipped(checkpoint, page_num)
                            continue

                        if should_skip:
                            # Blank page - still copy but count as skipped
                            output_doc.insert_pdf(input_doc, from_page=page_num, to_page=page_num)
                            result.skipped_pages += 1
                            if checkpoint and checkpoint_mgr:
                                checkpoint_mgr.mark_page_skipped(checkpoint, page_num)
                            continue

                        # Run OCR with page-level retry
                        ocr_results = _recognize_with_retry(page_num, pix)

                        # Create new page in output document
                        new_page = output_doc.new_page(width=rect.width, height=rect.height)

                        # Insert original image
                        self._insert_page_image(new_page, rect, pix)

                        # Add invisible text layer (batched)
                        # Use actual_zoom (not the requested zoom) for correct coordinate conversion
                        self._add_text_layer_batched(new_page, ocr_results, actual_zoom)

                        result.processed_pages += 1
                        ocr_completed_pages.add(page_num)

                        # Mark page as completed in checkpoint
                        if checkpoint and checkpoint_mgr:
                            checkpoint_mgr.mark_page_completed(checkpoint, page_num)

                        # Periodic save to temp file for recovery.
                        # Use garbage=0/deflate=False for speed: a slow save here blocks
                        # the main thread from reading the render queue, which can cause
                        # safe_put() in the render thread to timeout and drop pages.
                        pages_since_save += 1
                        if pages_since_save >= save_interval and temp_output_path:
                            try:
                                output_doc.save(temp_output_path, garbage=0, deflate=False, incremental=False)
                                pages_since_save = 0
                            except Exception:
                                pass  # Don't fail if temp save fails

                        # Memory cleanup - release large objects immediately
                        pix = None

                    except Exception as e:
                        error_msg = str(e)
                        # Log full traceback for debugging (when OCR_DEBUG=1)
                        full_error = traceback.format_exc()
                        get_logger().log_debug(full_error, page_num=page_num + 1, file_path=input_path)
                        _copy_page_with_fallback(page_num, error_msg)

            # Wait for render thread to finish
            render_thread.join(timeout=5.0)

            # Check for render errors
            if render_error[0]:
                result.errors.append(f"Render error: {str(render_error[0])}")
            if result.queue_stall_events > 0:
                result.errors.append(
                    f"渲染队列发生阻塞事件 {result.queue_stall_events} 次"
                )

            # Check if cancelled
            was_cancelled = cancel_event and cancel_event.is_set()

            if was_cancelled:
                # Cancelled - save progress to temp file for later resume.
                # Use garbage=0, deflate=False for fast save (user is waiting for cancel to complete;
                # the file is a temp checkpoint, not the final output, so size doesn't matter).
                if temp_output_path and checkpoint and checkpoint_mgr:
                    try:
                        output_doc.save(temp_output_path, garbage=0, deflate=False, incremental=False)
                        checkpoint_mgr.save_checkpoint(checkpoint)
                    except Exception:
                        pass
                output_doc.close()
                input_doc.close()
                result.success = False
                result.error_message = "处理已取消，进度已保存"
            else:
                # Validate output has all pages before saving.
                # If page production fell behind (queue stall / unexpected break),
                # fill gaps explicitly and record fallback pages.
                if len(output_doc) < result.total_pages:
                    missing_start = len(output_doc)
                    for page_num in range(missing_start, result.total_pages):
                        _copy_page_with_fallback(page_num, "输出页缺失补齐")

                if result.fallback_pages:
                    result.errors.append(
                        f"警告: 共{len(result.fallback_pages)}页OCR失败后回填原页: "
                        f"{', '.join(map(str, result.fallback_pages[:20]))}"
                        f"{' ...' if len(result.fallback_pages) > 20 else ''}"
                    )

                if len(output_doc) != result.total_pages:
                    raise RuntimeError(
                        f"输出页数校验失败: {len(output_doc)} / {result.total_pages}"
                    )

                # Completed - save final output
                output_doc.save(output_path, garbage=4, deflate=True)
                output_doc.close()
                input_doc.close()

                result.success = True

                # Clean up checkpoint on success
                if checkpoint and checkpoint_mgr:
                    checkpoint_mgr.cleanup_temp_files(checkpoint)

        except Exception as e:
            result.error_message = str(e)
            result.success = False

            # Save progress on error for later resume
            if checkpoint and checkpoint_mgr and temp_output_path:
                try:
                    if 'output_doc' in dir() and output_doc:
                        output_doc.save(temp_output_path, garbage=4, deflate=True)
                        checkpoint_mgr.save_checkpoint(checkpoint)
                        output_doc.close()
                except Exception:
                    pass
                try:
                    if 'input_doc' in dir() and input_doc:
                        input_doc.close()
                except Exception:
                    pass

        # Record timing
        result.end_time = datetime.now()
        result.elapsed_seconds = (result.end_time - start_time).total_seconds()

        # Log result
        if log_result:
            try:
                get_logger().log_result(result)
            except Exception:
                pass  # Don't fail if logging fails

        return result
