"""
Checkpoint Manager - Support for resume from breakpoint

Saves processing state after each page, allowing recovery if interrupted.
"""
import json
import os
from dataclasses import dataclass, asdict
from datetime import datetime
from pathlib import Path
from typing import Optional
import hashlib


@dataclass
class Checkpoint:
    """Checkpoint data for a processing task"""
    input_path: str
    output_path: str
    temp_output_path: str  # Temporary output file
    total_pages: int
    completed_pages: set[int]  # Set of completed page numbers (O(1) lookup)
    skipped_pages: set[int]   # Set of skipped page numbers (O(1) lookup)
    failed_pages: set[int]    # Set of failed page numbers (O(1) lookup)
    started_at: str
    updated_at: str
    dpi: int
    languages: list[str]
    input_hash: str  # MD5 hash of input file for verification

    @property
    def next_page(self) -> int:
        """Get the next page to process (0-indexed)"""
        # Now O(1) lookups since completed_pages, skipped_pages, failed_pages are sets
        all_done = self.completed_pages | self.skipped_pages | self.failed_pages
        for i in range(self.total_pages):
            if i not in all_done:
                return i
        return -1  # All pages done

    @property
    def is_complete(self) -> bool:
        """Check if all pages are processed"""
        return self.next_page == -1

    @property
    def progress_percent(self) -> int:
        """Get progress percentage"""
        done = len(self.completed_pages) + len(self.skipped_pages) + len(self.failed_pages)
        if self.total_pages == 0:
            return 0
        return int((done / self.total_pages) * 100)

    def to_dict(self) -> dict:
        """Convert to dict for JSON serialization (sets -> lists)"""
        d = asdict(self)
        # Convert sets to lists for JSON compatibility
        d['completed_pages'] = list(self.completed_pages)
        d['skipped_pages'] = list(self.skipped_pages)
        d['failed_pages'] = list(self.failed_pages)
        return d

    @classmethod
    def from_dict(cls, data: dict) -> 'Checkpoint':
        """Create from dict, converting lists back to sets"""
        # Convert lists to sets for O(1) lookup
        data = data.copy()  # Don't modify original
        data['completed_pages'] = set(data.get('completed_pages', []))
        data['skipped_pages'] = set(data.get('skipped_pages', []))
        data['failed_pages'] = set(data.get('failed_pages', []))
        return cls(**data)


class CheckpointManager:
    """
    Manages checkpoints for OCR processing tasks.

    Saves progress after each page, allowing resume if interrupted.
    """

    def __init__(self, checkpoint_dir: Optional[str] = None):
        """
        Initialize checkpoint manager.

        Args:
            checkpoint_dir: Directory for checkpoint files.
                           Defaults to ~/.ocr_tool/checkpoints/
        """
        if checkpoint_dir:
            self.checkpoint_dir = Path(checkpoint_dir)
        else:
            self.checkpoint_dir = Path.home() / ".ocr_tool" / "checkpoints"
        self.checkpoint_dir.mkdir(parents=True, exist_ok=True)

    def _get_checkpoint_path(self, input_path: str) -> Path:
        """Get checkpoint file path for an input file"""
        # Use hash of input path to create unique checkpoint filename
        path_hash = hashlib.md5(input_path.encode()).hexdigest()[:12]
        filename = Path(input_path).stem[:20]  # First 20 chars of filename
        return self.checkpoint_dir / f"{filename}_{path_hash}.checkpoint.json"

    def _get_file_hash(self, file_path: str) -> str:
        """Get MD5 hash of file (first 1MB + last 1MB + file size for better verification)"""
        try:
            hasher = hashlib.md5()
            file_size = os.path.getsize(file_path)

            with open(file_path, 'rb') as f:
                # Hash first 1MB
                hasher.update(f.read(1024 * 1024))

                # For larger files, also hash last 1MB
                if file_size > 2 * 1024 * 1024:
                    f.seek(-1024 * 1024, 2)  # Seek to last 1MB
                    hasher.update(f.read(1024 * 1024))

                # Include file size in hash
                hasher.update(str(file_size).encode())

            return hasher.hexdigest()
        except Exception:
            return ""

    def create_checkpoint(
        self,
        input_path: str,
        output_path: str,
        total_pages: int,
        dpi: int,
        languages: list[str],
    ) -> Checkpoint:
        """
        Create a new checkpoint for a processing task.

        Args:
            input_path: Path to input PDF
            output_path: Path for final output PDF
            total_pages: Total number of pages
            dpi: DPI setting
            languages: Language settings

        Returns:
            New Checkpoint object
        """
        # Create temp output path
        output_p = Path(output_path)
        temp_output = str(output_p.parent / f".{output_p.stem}_temp{output_p.suffix}")

        now = datetime.now().isoformat()
        checkpoint = Checkpoint(
            input_path=input_path,
            output_path=output_path,
            temp_output_path=temp_output,
            total_pages=total_pages,
            completed_pages=set(),
            skipped_pages=set(),
            failed_pages=set(),
            started_at=now,
            updated_at=now,
            dpi=dpi,
            languages=languages,
            input_hash=self._get_file_hash(input_path),
        )

        self.save_checkpoint(checkpoint)
        return checkpoint

    def save_checkpoint(self, checkpoint: Checkpoint):
        """Save checkpoint to file"""
        checkpoint.updated_at = datetime.now().isoformat()
        checkpoint_path = self._get_checkpoint_path(checkpoint.input_path)

        # Write atomically (write to temp, then rename)
        temp_path = checkpoint_path.with_suffix('.tmp')
        with open(temp_path, 'w', encoding='utf-8') as f:
            json.dump(checkpoint.to_dict(), f, ensure_ascii=False, indent=2)
        try:
            temp_path.rename(checkpoint_path)
        except OSError:
            temp_path.unlink(missing_ok=True)  # Clean up temp file on failure
            raise

    def load_checkpoint(self, input_path: str) -> Optional[Checkpoint]:
        """
        Load checkpoint for an input file if it exists.

        Args:
            input_path: Path to input PDF

        Returns:
            Checkpoint if exists and valid, None otherwise
        """
        checkpoint_path = self._get_checkpoint_path(input_path)

        if not checkpoint_path.exists():
            return None

        try:
            with open(checkpoint_path, 'r', encoding='utf-8') as f:
                data = json.load(f)

            checkpoint = Checkpoint.from_dict(data)

            # Verify input file hasn't changed
            current_hash = self._get_file_hash(input_path)
            if current_hash and checkpoint.input_hash and current_hash != checkpoint.input_hash:
                # Input file changed, checkpoint invalid
                self.delete_checkpoint(input_path)
                return None

            # Check if temp output exists
            if not Path(checkpoint.temp_output_path).exists():
                # Temp output missing, need to restart
                self.delete_checkpoint(input_path)
                return None

            return checkpoint

        except Exception:
            # Corrupted checkpoint, delete it
            self.delete_checkpoint(input_path)
            return None

    def delete_checkpoint(self, input_path: str):
        """Delete checkpoint for an input file"""
        checkpoint_path = self._get_checkpoint_path(input_path)
        try:
            checkpoint_path.unlink(missing_ok=True)
        except Exception:
            pass

    def mark_page_completed(self, checkpoint: Checkpoint, page_num: int):
        """Mark a page as completed and save"""
        checkpoint.completed_pages.add(page_num)  # O(1) add, set handles duplicates
        self.save_checkpoint(checkpoint)

    def mark_page_skipped(self, checkpoint: Checkpoint, page_num: int):
        """Mark a page as skipped and save"""
        checkpoint.skipped_pages.add(page_num)  # O(1) add, set handles duplicates
        self.save_checkpoint(checkpoint)

    def mark_page_failed(self, checkpoint: Checkpoint, page_num: int):
        """Mark a page as failed and save"""
        checkpoint.failed_pages.add(page_num)  # O(1) add, set handles duplicates
        self.save_checkpoint(checkpoint)

    def get_incomplete_tasks(self) -> list[Checkpoint]:
        """Get list of incomplete checkpoints"""
        incomplete = []
        for checkpoint_file in self.checkpoint_dir.glob("*.checkpoint.json"):
            try:
                with open(checkpoint_file, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                checkpoint = Checkpoint.from_dict(data)
                if not checkpoint.is_complete:
                    incomplete.append(checkpoint)
            except Exception:
                continue
        return incomplete

    def cleanup_temp_files(self, checkpoint: Checkpoint):
        """Clean up temporary files after successful completion"""
        try:
            temp_path = Path(checkpoint.temp_output_path)
            if temp_path.exists():
                temp_path.unlink()
        except Exception:
            pass
        self.delete_checkpoint(checkpoint.input_path)

    def cleanup_stale_checkpoints(self, max_age_hours: int = 24):
        """
        Clean up stale checkpoint files older than max_age_hours.

        Should be called at program startup to clean up orphaned files
        from previous crashes.
        """
        now = datetime.now()
        cleaned = 0

        for checkpoint_file in self.checkpoint_dir.glob("*.checkpoint.json"):
            try:
                with open(checkpoint_file, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                checkpoint = Checkpoint.from_dict(data)

                # Parse updated_at timestamp
                updated = datetime.fromisoformat(checkpoint.updated_at)
                age_hours = (now - updated).total_seconds() / 3600

                if age_hours > max_age_hours:
                    # Clean up stale checkpoint and its temp file
                    temp_path = Path(checkpoint.temp_output_path)
                    if temp_path.exists():
                        temp_path.unlink()
                    checkpoint_file.unlink()
                    cleaned += 1

            except Exception:
                # Corrupted checkpoint, delete it
                try:
                    checkpoint_file.unlink()
                    cleaned += 1
                except Exception:
                    pass

        return cleaned


# Global checkpoint manager instance
_checkpoint_manager: Optional[CheckpointManager] = None


def get_checkpoint_manager() -> CheckpointManager:
    """Get or create the global checkpoint manager"""
    global _checkpoint_manager
    if _checkpoint_manager is None:
        _checkpoint_manager = CheckpointManager()
    return _checkpoint_manager
