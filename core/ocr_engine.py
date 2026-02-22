"""
OCR Engine - PaddleOCR wrapper for multi-language text recognition
"""
from dataclasses import dataclass
from pathlib import Path
from typing import Optional
import numpy as np


@dataclass
class OCRResult:
    """Single OCR detection result"""
    text: str
    bbox: list[list[float]]  # [[x1,y1], [x2,y2], [x3,y3], [x4,y4]]
    confidence: float

    @property
    def x0(self) -> float:
        """Left edge"""
        return min(p[0] for p in self.bbox)

    @property
    def y0(self) -> float:
        """Top edge"""
        return min(p[1] for p in self.bbox)

    @property
    def x1(self) -> float:
        """Right edge"""
        return max(p[0] for p in self.bbox)

    @property
    def y1(self) -> float:
        """Bottom edge"""
        return max(p[1] for p in self.bbox)

    @property
    def width(self) -> float:
        return self.x1 - self.x0

    @property
    def height(self) -> float:
        return self.y1 - self.y0


# Language code mapping for PaddleOCR
LANGUAGE_MAP = {
    'ch': 'ch',           # Chinese
    'en': 'en',           # English
    'japan': 'japan',     # Japanese
    'korean': 'korean',   # Korean
    'french': 'french',   # French
    'german': 'german',   # German
}


class OCREngine:
    """
    PaddleOCR wrapper with multi-language support.

    Usage:
        engine = OCREngine(languages=['ch', 'en'])
        results = engine.recognize(image_array)

        # For faster processing with slightly lower quality:
        engine = OCREngine(languages=['ch'], quality='fast')
    """

    # Model configurations for different quality modes
    MODEL_CONFIGS = {
        'fast': {
            # All mobile models - fastest, lower accuracy
            'text_detection_model_name': 'PP-OCRv4_mobile_det',
            'text_recognition_model_name': 'PP-OCRv4_mobile_rec',
        },
        'balanced': {
            # Mobile detection + server recognition - good balance
            'text_detection_model_name': 'PP-OCRv4_mobile_det',
            'text_recognition_model_name': 'PP-OCRv5_server_rec',
        },
        'high': {
            # All server models - highest accuracy, slowest
            'text_detection_model_name': 'PP-OCRv4_server_det',
            'text_recognition_model_name': 'PP-OCRv5_server_rec',
        },
    }

    def __init__(
        self,
        languages: list[str] = None,
        model_dir: Optional[str] = None,
        use_gpu: bool = False,
        use_angle_cls: bool = True,
        quality: str = 'balanced',
    ):
        """
        Initialize OCR engine.

        Args:
            languages: List of language codes ['ch', 'en', 'japan']
            model_dir: Path to local model directory (optional)
            use_gpu: Whether to use GPU acceleration
            use_angle_cls: Whether to use angle classification
            quality: Quality/speed trade-off: 'fast', 'balanced', or 'high'
                - 'fast': All mobile models, ~3x faster, good for most documents
                - 'balanced': Mobile det + server rec, best quality/speed ratio
                - 'high': All server models, highest accuracy, slowest
        """
        self.languages = languages or ['ch', 'en']
        self.model_dir = Path(model_dir) if model_dir else None
        self.use_gpu = use_gpu
        self.use_angle_cls = use_angle_cls
        self.quality = quality if quality in self.MODEL_CONFIGS else 'balanced'
        self._ocr = None

        self._init_ocr()

    def _init_ocr(self):
        """Initialize PaddleOCR instance"""
        from paddleocr import PaddleOCR

        # Determine primary language (PaddleOCR uses single lang parameter)
        # Chinese model works well for mixed ch+en text
        primary_lang = self.languages[0] if self.languages else 'ch'

        # Get model configuration for selected quality
        model_config = self.MODEL_CONFIGS.get(self.quality, self.MODEL_CONFIGS['balanced'])

        ocr_kwargs = {
            'lang': primary_lang,
            'text_detection_model_name': model_config['text_detection_model_name'],
            'text_recognition_model_name': model_config['text_recognition_model_name'],
            'use_doc_orientation_classify': False,  # 禁用整页旋转检测
            'use_doc_unwarping': False,             # 禁用弯曲矫正
            'use_textline_orientation': True,       # 检测竖排/横排文字
        }

        # Use local models if specified
        if self.model_dir and self.model_dir.exists():
            det_model = self.model_dir / f'{primary_lang}_PP-OCRv4_det'
            rec_model = self.model_dir / f'{primary_lang}_PP-OCRv4_rec'

            if det_model.exists():
                ocr_kwargs['text_detection_model_dir'] = str(det_model)
            if rec_model.exists():
                ocr_kwargs['text_recognition_model_dir'] = str(rec_model)

        self._ocr = PaddleOCR(**ocr_kwargs)

    def recognize(self, image: np.ndarray) -> list[OCRResult]:
        """
        Perform OCR on an image.

        Args:
            image: numpy array (H, W, C) in BGR or RGB format

        Returns:
            List of OCRResult objects
        """
        if self._ocr is None:
            self._init_ocr()

        # Run OCR using new predict API
        results = self._ocr.predict(image)

        if not results:
            return []

        ocr_results = []

        # Handle new API format (PaddleOCR v5+)
        result = results[0]
        if isinstance(result, dict):
            # New API format
            rec_texts = result.get('rec_texts', [])
            rec_scores = result.get('rec_scores', [])
            rec_polys = result.get('rec_polys', [])

            for i, (text, score) in enumerate(zip(rec_texts, rec_scores)):
                if i < len(rec_polys):
                    poly = rec_polys[i]
                    # Convert numpy array to list of points
                    if hasattr(poly, 'tolist'):
                        bbox = poly.tolist()
                    else:
                        bbox = list(poly)

                    ocr_results.append(OCRResult(
                        text=text,
                        bbox=bbox,
                        confidence=float(score)
                    ))
        else:
            # Old API format (fallback)
            for line in result:
                if line is None or len(line) < 2:
                    continue

                bbox = line[0]  # [[x1,y1], [x2,y2], [x3,y3], [x4,y4]]
                text_info = line[1]  # (text, confidence)

                if text_info and len(text_info) >= 2:
                    text, confidence = text_info[0], text_info[1]
                    ocr_results.append(OCRResult(
                        text=text,
                        bbox=bbox,
                        confidence=confidence
                    ))

        return ocr_results

    def set_languages(self, languages: list[str]):
        """
        Change language configuration.

        Args:
            languages: New list of language codes
        """
        if languages != self.languages:
            self.languages = languages
            self._ocr = None  # Force re-initialization
            self._init_ocr()

    def __repr__(self):
        return f"OCREngine(languages={self.languages}, quality={self.quality}, use_gpu={self.use_gpu})"
