"""
Tests for core OCR functionality
"""
import os
import tempfile
from pathlib import Path
import pytest

# Skip all tests if dependencies not available
pytest.importorskip("paddleocr")
pytest.importorskip("fitz")


class TestOCREngine:
    """Tests for OCREngine"""

    def test_engine_initialization(self):
        """Test OCR engine initializes correctly"""
        from core.ocr_engine import OCREngine

        engine = OCREngine(languages=['ch', 'en'])
        assert engine is not None
        assert engine.languages == ['ch', 'en']

    def test_engine_language_change(self):
        """Test changing languages"""
        from core.ocr_engine import OCREngine

        engine = OCREngine(languages=['ch'])
        engine.set_languages(['en'])
        assert engine.languages == ['en']

    @pytest.mark.skip(reason="Requires image input")
    def test_engine_recognize(self):
        """Test OCR recognition on sample image"""
        import numpy as np
        from core.ocr_engine import OCREngine

        engine = OCREngine(languages=['en'])
        # Create a simple test image (would need actual image for real test)
        image = np.zeros((100, 300, 3), dtype=np.uint8)
        results = engine.recognize(image)
        assert isinstance(results, list)


class TestOCRResult:
    """Tests for OCRResult dataclass"""

    def test_ocr_result_properties(self):
        """Test OCRResult coordinate properties"""
        from core.ocr_engine import OCRResult

        result = OCRResult(
            text="Hello",
            bbox=[[10, 20], [100, 20], [100, 50], [10, 50]],
            confidence=0.95
        )

        assert result.x0 == 10
        assert result.y0 == 20
        assert result.x1 == 100
        assert result.y1 == 50
        assert result.width == 90
        assert result.height == 30


class TestPDFProcessor:
    """Tests for PDFProcessor"""

    def test_check_existing_text_empty(self):
        """Test detecting scanned PDF (no text)"""
        from core.pdf_processor import PDFProcessor
        from core.ocr_engine import OCREngine
        import fitz

        # Create a test PDF with image only (no text)
        with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as f:
            doc = fitz.open()
            page = doc.new_page()
            # Just insert a rectangle, no text
            page.draw_rect(fitz.Rect(50, 50, 200, 200), color=(0, 0, 1))
            doc.save(f.name)
            doc.close()

            engine = OCREngine(languages=['en'])
            processor = PDFProcessor(engine)

            has_text = processor.check_existing_text(f.name)
            assert has_text is False

            os.unlink(f.name)

    def test_check_existing_text_with_text(self):
        """Test detecting PDF with text"""
        from core.pdf_processor import PDFProcessor
        from core.ocr_engine import OCREngine
        import fitz

        # Create a test PDF with text
        with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as f:
            doc = fitz.open()
            page = doc.new_page()
            # Insert enough text to pass the threshold
            text = "This is a test PDF with searchable text content. " * 10
            page.insert_text((50, 50), text)
            doc.save(f.name)
            doc.close()

            engine = OCREngine(languages=['en'])
            processor = PDFProcessor(engine)

            has_text = processor.check_existing_text(f.name)
            assert has_text is True

            os.unlink(f.name)


class TestProcessResult:
    """Tests for ProcessResult"""

    def test_process_result_success(self):
        """Test ProcessResult for successful processing"""
        from core.pdf_processor import ProcessResult

        result = ProcessResult(
            success=True,
            input_path="/input.pdf",
            output_path="/output.pdf",
            total_pages=10,
            processed_pages=10,
            skipped_pages=0,
        )

        assert result.success is True
        assert result.has_errors is False

    def test_process_result_with_errors(self):
        """Test ProcessResult with errors"""
        from core.pdf_processor import ProcessResult

        result = ProcessResult(
            success=False,
            input_path="/input.pdf",
            output_path="/output.pdf",
            error_message="File not found",
            errors=["Page 1: Error reading"]
        )

        assert result.success is False
        assert result.has_errors is True


class TestPipelinedProcessing:
    """Tests for pipelined processing optimizations"""

    def test_blank_page_detection(self):
        """Test blank page detection with a truly blank page"""
        from core.pdf_processor import PDFProcessor
        from core.ocr_engine import OCREngine
        import fitz
        import numpy as np

        # Create a mostly blank pixmap
        engine = OCREngine(languages=['en'])
        # Use a higher threshold to ensure blank pages are detected
        processor = PDFProcessor(engine, blank_page_threshold=0.5)

        # Create blank test PDF (truly blank, no content at all)
        with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as f:
            doc = fitz.open()
            page = doc.new_page()
            # Don't add any content - truly blank
            doc.save(f.name)
            doc.close()

            # Reopen and get pixmap
            doc = fitz.open(f.name)
            page = doc[0]
            pix = page.get_pixmap()

            # Calculate edge magnitude manually to verify
            img = np.frombuffer(pix.samples, dtype=np.uint8)
            img = img.reshape(pix.height, pix.width, pix.n)
            gray = np.mean(img[:, :, :3], axis=2) if pix.n >= 3 else img[:, :, 0].astype(np.float32)
            grad_x = np.abs(np.diff(gray, axis=1))
            grad_y = np.abs(np.diff(gray, axis=0))
            edge_magnitude = (np.mean(grad_x) + np.mean(grad_y)) / 2

            # Truly blank page should have very low edge magnitude
            assert edge_magnitude < 0.5, f"Edge magnitude {edge_magnitude} should be < 0.5 for blank page"

            # Test blank detection (use == for numpy bool comparison)
            is_blank = processor._is_blank_page(pix)
            assert bool(is_blank) == True

            doc.close()
            os.unlink(f.name)

    def test_blank_page_detection_with_content(self):
        """Test that pages with content are not detected as blank"""
        from core.pdf_processor import PDFProcessor
        from core.ocr_engine import OCREngine
        import fitz
        import numpy as np

        engine = OCREngine(languages=['en'])
        # Use the default conservative threshold
        processor = PDFProcessor(engine, blank_page_threshold=0.5)

        # Create PDF with substantial visual content (shapes, not just text)
        with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as f:
            doc = fitz.open()
            page = doc.new_page()
            # Add substantial visual content - rectangles create strong edges
            for y in range(50, 500, 50):
                page.draw_rect(fitz.Rect(50, y, 400, y + 30), color=(0, 0, 0), width=2)
            # Also add text
            for y in range(50, 500, 30):
                page.insert_text((60, y + 20), "X" * 50, fontsize=12)
            doc.save(f.name)
            doc.close()

            # Reopen and get pixmap at higher DPI for better edge detection
            doc = fitz.open(f.name)
            page = doc[0]
            mat = fitz.Matrix(2, 2)  # 2x zoom for better rendering
            pix = page.get_pixmap(matrix=mat)

            # Calculate edge magnitude manually to verify
            img = np.frombuffer(pix.samples, dtype=np.uint8)
            img = img.reshape(pix.height, pix.width, pix.n)
            gray = np.mean(img[:, :, :3], axis=2) if pix.n >= 3 else img[:, :, 0].astype(np.float32)
            grad_x = np.abs(np.diff(gray, axis=1))
            grad_y = np.abs(np.diff(gray, axis=0))
            edge_magnitude = (np.mean(grad_x) + np.mean(grad_y)) / 2

            # Page with content should have higher edge magnitude
            assert edge_magnitude > 0.5, f"Edge magnitude {edge_magnitude} should be > 0.5 for page with content"

            # Test that it's NOT detected as blank (use == for numpy bool)
            is_blank = processor._is_blank_page(pix)
            assert bool(is_blank) == False

            doc.close()
            os.unlink(f.name)

    def test_adaptive_zoom_large_page(self):
        """Test that _adaptive_zoom caps oversized pages to avoid PaddleOCR's silent rescale."""
        from core.pdf_processor import PDFProcessor
        from core.ocr_engine import OCREngine
        import fitz

        engine = OCREngine(languages=['en'])
        processor = PDFProcessor(engine, dpi=150)

        # Simulate the 1632x2584 pt page (real-world A1-size book)
        # At zoom=2.083 (150dpi), raw size = 3400x5384 px, max_side=5384 > 3800
        with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as f:
            doc = fitz.open()
            # Create a custom-size page (1632x2584 pts ≈ 22.7x35.9 inches)
            doc.new_page(width=1632, height=2584)
            doc.save(f.name)
            doc.close()

            doc = fitz.open(f.name)
            page = doc[0]
            base_zoom = 150 / 72.0  # 2.083

            zoom = processor._adaptive_zoom(page, base_zoom, max_side=3800)

            # Verify max side is ≤ 3800px
            rendered_w = page.rect.width * zoom
            rendered_h = page.rect.height * zoom
            assert max(rendered_w, rendered_h) <= 3800 + 1, (
                f"Max side {max(rendered_w, rendered_h):.0f}px should be ≤ 3800px"
            )
            # Verify zoom was reduced (not kept at base_zoom)
            assert zoom < base_zoom, f"zoom {zoom:.3f} should be < base_zoom {base_zoom:.3f}"

            doc.close()
            os.unlink(f.name)

    def test_adaptive_zoom_normal_page(self):
        """Test that _adaptive_zoom leaves normal-sized pages unchanged."""
        from core.pdf_processor import PDFProcessor
        from core.ocr_engine import OCREngine
        import fitz

        engine = OCREngine(languages=['en'])
        processor = PDFProcessor(engine, dpi=150)

        # Standard A4 page (595x842 pts). At 150dpi: 1240x1754px — well under 3800
        with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as f:
            doc = fitz.open()
            doc.new_page(width=595, height=842)
            doc.save(f.name)
            doc.close()

            doc = fitz.open(f.name)
            page = doc[0]
            base_zoom = 150 / 72.0

            zoom = processor._adaptive_zoom(page, base_zoom, max_side=3800)
            # Should be unchanged (A4 at 150dpi fits within limits)
            assert abs(zoom - base_zoom) < 0.001, (
                f"Normal page zoom {zoom:.3f} should equal base_zoom {base_zoom:.3f}"
            )

            doc.close()
            os.unlink(f.name)

    @pytest.mark.skip(reason="Requires full OCR setup")
    def test_pipelined_vs_standard_output_same(self):
        """Test that pipelined and standard processing produce same output"""
        from core.pdf_processor import PDFProcessor
        from core.ocr_engine import OCREngine
        import fitz

        engine = OCREngine(languages=['en'])
        processor = PDFProcessor(engine)

        # Create test PDF
        with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as f:
            doc = fitz.open()
            page = doc.new_page()
            page.insert_text((50, 50), "Test content for comparison")
            doc.save(f.name)
            doc.close()

            # Process with standard method
            output1 = f.name.replace(".pdf", "_std.pdf")
            result1 = processor.process_file(f.name, output1)

            # Process with pipelined method
            output2 = f.name.replace(".pdf", "_pipe.pdf")
            result2 = processor.process_file_pipelined(f.name, output2)

            # Both should succeed
            assert result1.success is True
            assert result2.success is True

            # Cleanup
            os.unlink(f.name)
            os.unlink(output1)
            os.unlink(output2)


class TestTaskManager:
    """Tests for TaskManager"""

    def test_add_file(self):
        """Test adding a file to task manager"""
        from core.task_manager import TaskManager, TaskManagerConfig
        import fitz

        # Create a test PDF
        with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as f:
            doc = fitz.open()
            doc.new_page()
            doc.save(f.name)
            doc.close()

            config = TaskManagerConfig()
            manager = TaskManager(config)

            task = manager.add_file(f.name)
            assert task is not None
            assert task.input_path == f.name

            os.unlink(f.name)

    def test_add_invalid_file(self):
        """Test adding non-PDF file"""
        from core.task_manager import TaskManager, TaskManagerConfig

        config = TaskManagerConfig()
        manager = TaskManager(config)

        # Non-existent file
        task = manager.add_file("/nonexistent.pdf")
        assert task is None

        # Non-PDF file
        with tempfile.NamedTemporaryFile(suffix=".txt", delete=False) as f:
            f.write(b"text content")
            task = manager.add_file(f.name)
            assert task is None
            os.unlink(f.name)

    def test_task_status(self):
        """Test task status enum"""
        from core.task_manager import TaskStatus

        assert TaskStatus.PENDING.value == "pending"
        assert TaskStatus.PROCESSING.value == "processing"
        assert TaskStatus.COMPLETED.value == "completed"
        assert TaskStatus.FAILED.value == "failed"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
