"""
OCR Engine - PaddleOCR wrapper for multi-language text recognition
"""
from dataclasses import dataclass
from pathlib import Path
from typing import Optional
import numpy as np

# Workaround for PaddlePaddle 3.3.0+ PIR→oneDNN regression.
# The bug is in PIR executor's oneDNN conversion (ConvertPirAttribute2RuntimeAttribute).
# Disabling PIR *before* importing paddle lets oneDNN still work via the old executor,
# preserving performance. FLAGS_enable_pir_api must be set before `import paddle`.
# See: https://github.com/PaddlePaddle/Paddle/issues/77340
import os as _os
if 'FLAGS_enable_pir_api' not in _os.environ:
    try:
        from importlib.metadata import version as _pkg_version
        _paddle_ver = _pkg_version('paddlepaddle')
        _major, _minor = (int(x) for x in _paddle_ver.split('.')[:2])
        if _major >= 3 and _minor >= 3:
            _os.environ['FLAGS_enable_pir_api'] = '0'
    except Exception:
        pass


def _get_bundled_models_dir() -> Optional[Path]:
    """Return the models/ path bundled inside a PyInstaller frozen app, or None.

    On Windows, PaddlePaddle's C++ inference engine cannot load models from
    paths containing non-ASCII characters (e.g. Chinese install dir).
    If detected, models are copied to an ASCII-safe cache directory.
    """
    import sys
    if not getattr(sys, 'frozen', False):
        return None
    bundled = Path(sys._MEIPASS) / 'models'
    if not bundled.exists():
        return None

    # Check if path contains non-ASCII characters (Windows issue)
    if sys.platform == 'win32':
        try:
            str(bundled).encode('ascii')
        except UnicodeEncodeError:
            return _copy_models_to_ascii_path(bundled)

    return bundled


def _copy_models_to_ascii_path(src_dir: Path) -> Path:
    """Copy models to an ASCII-safe cache directory for Windows compatibility."""
    import shutil
    import logging
    logger = logging.getLogger(__name__)

    # Use LOCALAPPDATA which is typically C:\Users\<ascii_username>\AppData\Local
    import os
    cache_base = Path(os.environ.get('LOCALAPPDATA', Path.home() / 'AppData' / 'Local'))
    cache_dir = cache_base / 'SmartOCR' / 'models'

    # Check if cache_dir itself has non-ASCII (unlikely but possible)
    try:
        str(cache_dir).encode('ascii')
    except UnicodeEncodeError:
        # Fallback to temp dir
        import tempfile
        cache_dir = Path(tempfile.gettempdir()) / 'SmartOCR' / 'models'

    cache_dir.mkdir(parents=True, exist_ok=True)

    for model_subdir in src_dir.iterdir():
        if not model_subdir.is_dir():
            continue
        dst = cache_dir / model_subdir.name
        if dst.exists():
            # Check if source is newer (by comparing a key file)
            src_marker = model_subdir / 'inference.pdiparams'
            dst_marker = dst / 'inference.pdiparams'
            if src_marker.exists() and dst_marker.exists():
                if src_marker.stat().st_size == dst_marker.stat().st_size:
                    continue  # Already up to date
            shutil.rmtree(dst)
        logger.info(f"Copying model {model_subdir.name} to ASCII-safe path: {dst}")
        shutil.copytree(model_subdir, dst)

    return cache_dir


def _get_paddlex_cache_dir() -> Path:
    """Return the PaddleX official_models cache directory."""
    import os
    custom = os.environ.get('PADDLE_PDX_MODEL_DIRS', '')
    if custom:
        return Path(custom)
    return Path.home() / '.paddlex' / 'official_models'


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
            'text_detection_model_name': 'PP-OCRv5_mobile_det',
            'text_recognition_model_name': 'PP-OCRv5_mobile_rec',
        },
        'balanced': {
            # Mobile detection + server recognition - good balance
            'text_detection_model_name': 'PP-OCRv5_mobile_det',
            'text_recognition_model_name': 'PP-OCRv5_server_rec',
        },
        'high': {
            # All server models - highest accuracy, slowest
            'text_detection_model_name': 'PP-OCRv5_server_det',
            'text_recognition_model_name': 'PP-OCRv5_server_rec',
        },
    }

    @staticmethod
    def is_model_available(model_name: str) -> bool:
        """Check whether a model is available (bundled or in PaddleX cache).

        PaddleX models contain either inference.pdmodel or inference.pdiparams
        depending on the model format.  We check for either.
        """
        def _has_inference_files(directory: Path) -> bool:
            return (
                (directory / 'inference.pdmodel').exists()
                or (directory / 'inference.pdiparams').exists()
            )

        # 1. Check inside the frozen bundle
        bundled = _get_bundled_models_dir()
        if bundled and _has_inference_files(bundled / model_name):
            return True
        # 2. Check PaddleX cache
        cache = _get_paddlex_cache_dir() / model_name
        return _has_inference_files(cache)

    @staticmethod
    def get_missing_models(quality: str) -> list:
        """Return the list of model names missing for the given quality mode."""
        config = OCREngine.MODEL_CONFIGS.get(quality, OCREngine.MODEL_CONFIGS['balanced'])
        missing = []
        for key in ('text_detection_model_name', 'text_recognition_model_name'):
            model = config[key]
            if not OCREngine.is_model_available(model):
                missing.append(model)
        return missing

    def __init__(
        self,
        languages: list[str] = None,
        model_dir: Optional[str] = None,
        use_gpu: Optional[bool] = None,
        use_angle_cls: bool = True,
        quality: str = 'balanced',
    ):
        """
        Initialize OCR engine.

        Args:
            languages: List of language codes ['ch', 'en', 'japan']
            model_dir: Path to local model directory (optional)
            use_gpu: GPU override.
                None  → auto-detect (uses core.hardware.get_device_string)
                True  → force GPU ('gpu:0')
                False → force CPU
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
        self._device_str = ""

        self._init_ocr()

    def _init_ocr(self):
        """Initialize PaddleOCR instance"""
        import logging
        from paddleocr import PaddleOCR

        # Resolve device string based on use_gpu override
        if self.use_gpu is None:
            # Auto-detect: use hardware module
            from core.hardware import get_device_string
            self._device_str = get_device_string()
        elif self.use_gpu is True:
            self._device_str = "gpu:0"
        else:
            # False → force CPU
            from core.hardware import get_device_string
            self._device_str = get_device_string(force_cpu=True)

        logging.getLogger(__name__).info(
            "OCREngine: initializing with device=%s quality=%s",
            self._device_str, self.quality
        )

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
            'device': self._device_str,
        }

        # Resolve model directories: bundled models > PaddleX cache > auto-download
        bundled_dir = _get_bundled_models_dir()
        paddlex_cache = _get_paddlex_cache_dir()

        for model_key, dir_kwarg in [
            ('text_detection_model_name', 'text_detection_model_dir'),
            ('text_recognition_model_name', 'text_recognition_model_dir'),
        ]:
            model_name = model_config[model_key]
            # 1. Prefer bundled models (frozen app)
            if bundled_dir and (bundled_dir / model_name).exists():
                ocr_kwargs[dir_kwarg] = str(bundled_dir / model_name)
            else:
                # 2. Use PaddleX cache if already downloaded
                cached = paddlex_cache / model_name
                if cached.exists():
                    ocr_kwargs[dir_kwarg] = str(cached)
                # 3. Otherwise let PaddleOCR auto-download (fallback)

        # Resolve textline orientation model path (PP-LCNet_x1_0_textline_ori)
        TEXTLINE_MODEL = 'PP-LCNet_x1_0_textline_ori'
        if bundled_dir and (bundled_dir / TEXTLINE_MODEL).exists():
            ocr_kwargs['textline_orientation_model_dir'] = str(bundled_dir / TEXTLINE_MODEL)
        else:
            cached_tl = paddlex_cache / TEXTLINE_MODEL
            if cached_tl.exists():
                ocr_kwargs['textline_orientation_model_dir'] = str(cached_tl)

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
        return f"OCREngine(languages={self.languages}, quality={self.quality}, device={self._device_str!r})"
