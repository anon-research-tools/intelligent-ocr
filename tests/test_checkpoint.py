"""
Tests for checkpoint/resume functionality
"""
import os
import tempfile
import time
from pathlib import Path
import pytest

from core.checkpoint import Checkpoint, CheckpointManager


class TestCheckpoint:
    """Tests for Checkpoint dataclass"""

    def test_checkpoint_next_page(self):
        """Test next_page calculation"""
        checkpoint = Checkpoint(
            input_path="/test.pdf",
            output_path="/test_ocr.pdf",
            temp_output_path="/tmp/.test_temp.pdf",
            total_pages=10,
            completed_pages={0, 1, 2},
            skipped_pages={3},
            failed_pages={4},
            started_at="2024-01-01T00:00:00",
            updated_at="2024-01-01T00:00:00",
            dpi=300,
            languages=["ch"],
            input_hash="abc123",
        )

        # Next page should be 5 (0-4 are done)
        assert checkpoint.next_page == 5

    def test_checkpoint_is_complete(self):
        """Test is_complete when all pages processed"""
        checkpoint = Checkpoint(
            input_path="/test.pdf",
            output_path="/test_ocr.pdf",
            temp_output_path="/tmp/.test_temp.pdf",
            total_pages=3,
            completed_pages={0, 2},
            skipped_pages={1},
            failed_pages=set(),
            started_at="2024-01-01T00:00:00",
            updated_at="2024-01-01T00:00:00",
            dpi=300,
            languages=["ch"],
            input_hash="abc123",
        )

        assert checkpoint.is_complete is True
        assert checkpoint.next_page == -1

    def test_checkpoint_progress_percent(self):
        """Test progress percentage calculation"""
        checkpoint = Checkpoint(
            input_path="/test.pdf",
            output_path="/test_ocr.pdf",
            temp_output_path="/tmp/.test_temp.pdf",
            total_pages=10,
            completed_pages={0, 1, 2, 3, 4},
            skipped_pages=set(),
            failed_pages=set(),
            started_at="2024-01-01T00:00:00",
            updated_at="2024-01-01T00:00:00",
            dpi=300,
            languages=["ch"],
            input_hash="abc123",
        )

        assert checkpoint.progress_percent == 50

    def test_checkpoint_to_dict_from_dict(self):
        """Test serialization/deserialization"""
        original = Checkpoint(
            input_path="/test.pdf",
            output_path="/test_ocr.pdf",
            temp_output_path="/tmp/.test_temp.pdf",
            total_pages=10,
            completed_pages={0, 1, 2},
            skipped_pages={3, 4},
            failed_pages={5},
            started_at="2024-01-01T00:00:00",
            updated_at="2024-01-01T00:00:00",
            dpi=300,
            languages=["ch", "en"],
            input_hash="abc123",
        )

        # Convert to dict and back
        data = original.to_dict()
        restored = Checkpoint.from_dict(data)

        assert restored.input_path == original.input_path
        assert restored.completed_pages == original.completed_pages
        assert restored.skipped_pages == original.skipped_pages
        assert restored.failed_pages == original.failed_pages


class TestCheckpointManager:
    """Tests for CheckpointManager"""

    @pytest.fixture
    def temp_checkpoint_dir(self):
        """Create a temporary checkpoint directory"""
        with tempfile.TemporaryDirectory() as tmpdir:
            yield tmpdir

    @pytest.fixture
    def manager(self, temp_checkpoint_dir):
        """Create a CheckpointManager with temp directory"""
        return CheckpointManager(checkpoint_dir=temp_checkpoint_dir)

    @pytest.fixture
    def temp_pdf(self):
        """Create a temporary PDF file"""
        import fitz
        with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as f:
            doc = fitz.open()
            for _ in range(5):
                doc.new_page()
            doc.save(f.name)
            doc.close()
            yield f.name
        os.unlink(f.name)

    def test_checkpoint_create(self, manager, temp_pdf):
        """Test creating a new checkpoint"""
        output_path = temp_pdf.replace(".pdf", "_ocr.pdf")

        checkpoint = manager.create_checkpoint(
            input_path=temp_pdf,
            output_path=output_path,
            total_pages=5,
            dpi=300,
            languages=["ch", "en"],
        )

        assert checkpoint is not None
        assert checkpoint.input_path == temp_pdf
        assert checkpoint.output_path == output_path
        assert checkpoint.total_pages == 5
        assert checkpoint.dpi == 300
        assert checkpoint.languages == ["ch", "en"]
        assert len(checkpoint.completed_pages) == 0
        assert checkpoint.next_page == 0
        assert checkpoint.input_hash != ""  # Hash should be computed

    def test_checkpoint_mark_completed(self, manager, temp_pdf):
        """Test marking pages as completed"""
        output_path = temp_pdf.replace(".pdf", "_ocr.pdf")

        checkpoint = manager.create_checkpoint(
            input_path=temp_pdf,
            output_path=output_path,
            total_pages=5,
            dpi=300,
            languages=["ch"],
        )

        # Mark page 0 as completed
        manager.mark_page_completed(checkpoint, 0)
        assert 0 in checkpoint.completed_pages
        assert checkpoint.next_page == 1

        # Mark pages 1 and 2
        manager.mark_page_completed(checkpoint, 1)
        manager.mark_page_skipped(checkpoint, 2)
        assert checkpoint.next_page == 3

        # Mark page 3 as failed
        manager.mark_page_failed(checkpoint, 3)
        assert 3 in checkpoint.failed_pages
        assert checkpoint.next_page == 4

    def test_checkpoint_resume(self, manager, temp_pdf):
        """Test loading and resuming from checkpoint"""
        output_path = temp_pdf.replace(".pdf", "_ocr.pdf")

        # Create checkpoint and mark some pages
        checkpoint1 = manager.create_checkpoint(
            input_path=temp_pdf,
            output_path=output_path,
            total_pages=5,
            dpi=300,
            languages=["ch"],
        )

        manager.mark_page_completed(checkpoint1, 0)
        manager.mark_page_completed(checkpoint1, 1)
        manager.mark_page_skipped(checkpoint1, 2)

        # Create temp output file (required for valid checkpoint)
        temp_output = Path(checkpoint1.temp_output_path)
        temp_output.parent.mkdir(parents=True, exist_ok=True)
        temp_output.touch()

        # Load checkpoint (simulating resume)
        checkpoint2 = manager.load_checkpoint(temp_pdf)

        assert checkpoint2 is not None
        assert checkpoint2.completed_pages == {0, 1}
        assert checkpoint2.skipped_pages == {2}
        assert checkpoint2.next_page == 3
        assert checkpoint2.progress_percent == 60

        # Cleanup temp file
        temp_output.unlink(missing_ok=True)

    def test_checkpoint_cleanup(self, manager, temp_pdf):
        """Test cleanup of temp files after completion"""
        output_path = temp_pdf.replace(".pdf", "_ocr.pdf")

        checkpoint = manager.create_checkpoint(
            input_path=temp_pdf,
            output_path=output_path,
            total_pages=3,
            dpi=300,
            languages=["ch"],
        )

        # Create temp output file
        temp_output = Path(checkpoint.temp_output_path)
        temp_output.parent.mkdir(parents=True, exist_ok=True)
        temp_output.touch()

        # Cleanup
        manager.cleanup_temp_files(checkpoint)

        # Temp file should be deleted
        assert not temp_output.exists()

        # Checkpoint should be deleted
        loaded = manager.load_checkpoint(temp_pdf)
        assert loaded is None

    def test_checkpoint_file_changed(self, manager):
        """Test checkpoint invalidation when input file changes"""
        import fitz

        # Create first PDF
        with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as f:
            pdf_path = f.name
            doc = fitz.open()
            for _ in range(3):
                doc.new_page()
            doc.save(pdf_path)
            doc.close()

        output_path = pdf_path.replace(".pdf", "_ocr.pdf")

        try:
            # Create checkpoint
            checkpoint = manager.create_checkpoint(
                input_path=pdf_path,
                output_path=output_path,
                total_pages=3,
                dpi=300,
                languages=["ch"],
            )

            manager.mark_page_completed(checkpoint, 0)

            # Create temp output file (required for valid checkpoint)
            temp_output = Path(checkpoint.temp_output_path)
            temp_output.parent.mkdir(parents=True, exist_ok=True)
            temp_output.touch()

            # Verify checkpoint can be loaded
            loaded = manager.load_checkpoint(pdf_path)
            assert loaded is not None
            assert 0 in loaded.completed_pages

            # Modify the input file (add more pages)
            # Save to a temp file first, then replace (PyMuPDF can't overwrite open file)
            import shutil
            temp_modified = pdf_path + ".modified"
            doc = fitz.open(pdf_path)
            doc.new_page()  # Add an extra page
            doc.save(temp_modified)
            doc.close()
            shutil.move(temp_modified, pdf_path)

            # Checkpoint should be invalidated due to file hash change
            loaded_after_change = manager.load_checkpoint(pdf_path)
            assert loaded_after_change is None

        finally:
            # Cleanup
            os.unlink(pdf_path)
            temp_output.unlink(missing_ok=True)

    def test_cleanup_stale_checkpoints(self, temp_checkpoint_dir):
        """Test cleanup of stale checkpoint files"""
        import json
        from datetime import datetime, timedelta

        manager = CheckpointManager(checkpoint_dir=temp_checkpoint_dir)

        # Create a stale checkpoint file manually
        stale_checkpoint = {
            "input_path": "/old/file.pdf",
            "output_path": "/old/file_ocr.pdf",
            "temp_output_path": "/tmp/.old_temp.pdf",
            "total_pages": 10,
            "completed_pages": [0, 1, 2],
            "skipped_pages": [],
            "failed_pages": [],
            "started_at": (datetime.now() - timedelta(hours=48)).isoformat(),
            "updated_at": (datetime.now() - timedelta(hours=48)).isoformat(),
            "dpi": 300,
            "languages": ["ch"],
            "input_hash": "abc123",
        }

        checkpoint_path = Path(temp_checkpoint_dir) / "stale_test.checkpoint.json"
        with open(checkpoint_path, "w") as f:
            json.dump(stale_checkpoint, f)

        # Verify file exists
        assert checkpoint_path.exists()

        # Cleanup stale checkpoints (older than 24 hours)
        cleaned = manager.cleanup_stale_checkpoints(max_age_hours=24)

        assert cleaned >= 1
        assert not checkpoint_path.exists()


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
