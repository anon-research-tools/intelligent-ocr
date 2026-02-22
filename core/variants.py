"""
Variant Character Mapper - Maps variant Chinese characters to canonical forms

This module enables searching for variant characters (異體字/异体字) in OCR-processed PDFs.
When text contains characters like "蔵", searching for "藏" will also match because both
forms are inserted into the PDF's searchable text layer.

Usage:
    mapper = VariantMapper("variants.txt")
    normalized = mapper.normalize("大藏經")  # Returns canonical form
"""
from pathlib import Path
from typing import Optional


class VariantMapper:
    """
    Maps variant characters to their canonical forms.

    Each line in the variants file contains characters that are variants of each other.
    The first character on each line is treated as the canonical (正字) form.

    Example variants.txt line:
        藏蔵臧  → All map to '藏' (first char is canonical)
    """

    def __init__(self, variants_path: Optional[str] = None):
        """
        Initialize the variant mapper.

        Args:
            variants_path: Path to variants.txt file. If None or file doesn't exist,
                          the mapper becomes a no-op (normalize returns input unchanged).
        """
        self.char_to_canonical: dict[str, str] = {}
        self._loaded = False

        if variants_path:
            self._load_variants(variants_path)

    def _load_variants(self, path: str) -> None:
        """
        Load variant character mappings from file.

        Each line contains characters that are variants of each other.
        The first character is used as the canonical form.

        Args:
            path: Path to variants.txt file
        """
        try:
            variants_file = Path(path)
            if not variants_file.exists():
                return

            with open(variants_file, 'r', encoding='utf-8') as f:
                for line in f:
                    # Strip whitespace and skip empty lines
                    line = line.strip()
                    if not line:
                        continue

                    # Each character in the line is a variant
                    chars = list(line)
                    if len(chars) < 2:
                        continue  # Need at least 2 chars for variants

                    # First character is the canonical form
                    canonical = chars[0]

                    # Map all characters (including canonical) to canonical
                    for c in chars:
                        self.char_to_canonical[c] = canonical

            self._loaded = True

        except Exception:
            # If loading fails, mapper becomes a no-op
            self.char_to_canonical = {}
            self._loaded = False

    def normalize(self, text: str) -> str:
        """
        Convert variant characters in text to their canonical forms.

        Args:
            text: Input text possibly containing variant characters

        Returns:
            Text with variant characters replaced by canonical forms.
            Characters not in the variants table are unchanged.
        """
        if not self._loaded or not self.char_to_canonical:
            return text

        return ''.join(self.char_to_canonical.get(c, c) for c in text)

    def has_variants(self, text: str) -> bool:
        """
        Check if text contains any characters that have variants.

        Args:
            text: Input text to check

        Returns:
            True if any character in text has a variant mapping
        """
        if not self._loaded or not self.char_to_canonical:
            return False

        return any(c in self.char_to_canonical for c in text)

    def needs_normalization(self, text: str) -> bool:
        """
        Check if normalizing text would change it.

        This is more efficient than comparing normalize(text) != text
        because it short-circuits on first difference.

        Args:
            text: Input text to check

        Returns:
            True if normalize(text) would produce a different string
        """
        if not self._loaded or not self.char_to_canonical:
            return False

        for c in text:
            if c in self.char_to_canonical and self.char_to_canonical[c] != c:
                return True
        return False

    @property
    def is_loaded(self) -> bool:
        """Return True if variants file was successfully loaded."""
        return self._loaded

    @property
    def variant_count(self) -> int:
        """Return the number of variant characters mapped."""
        return len(self.char_to_canonical)
