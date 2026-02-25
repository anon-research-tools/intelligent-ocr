"""
PyInstaller runtime hook to bypass PaddleX dependency checks in packaged environment.

This hook patches importlib.metadata to report bundled packages as installed,
preventing paddlex.utils.deps from raising DependencyError.
"""
import sys

# Only apply in frozen/packaged environment
if getattr(sys, 'frozen', False):
    # Fix paddle/base/core.py crash: site.getsitepackages() can return
    # [None, ...] in PyInstaller, causing os.path.sep.join() to fail with
    # "sequence item 0: expected str instance, NoneType found".
    import site as _site
    if hasattr(_site, 'getsitepackages'):
        _orig_getsitepackages = _site.getsitepackages
        def _patched_getsitepackages():
            return [p for p in _orig_getsitepackages() if p is not None]
        _site.getsitepackages = _patched_getsitepackages

    import importlib.metadata
    import importlib.util

    # Packages bundled with the app that might not have proper metadata
    _BUNDLED_PACKAGES = {
        'opencv-contrib-python': '4.10.0',
        'opencv-python': '4.10.0',
        'pypdfium2': '4.30.0',
        'beautifulsoup4': '4.12.0',
        'bs4': '4.12.0',
        'einops': '0.8.0',
        'ftfy': '6.3.0',
        'imagesize': '1.4.0',
        'jinja2': '3.1.0',
        'lxml': '5.3.0',
        'openpyxl': '3.1.0',
        'premailer': '3.10.0',
        'pyclipper': '1.3.0',
        'python-bidi': '0.6.0',
        'regex': '2024.0.0',
        'safetensors': '0.4.0',
        'scikit-learn': '1.5.0',
        'sklearn': '1.5.0',
        'scipy': '1.14.0',
        'sentencepiece': '0.2.0',
        'shapely': '2.0.0',
        'tiktoken': '0.8.0',
        'tokenizers': '0.21.0',
        'paddlepaddle': '3.0.0',
        'paddle': '3.0.0',
        'paddleocr': '3.0.0',
        'paddlex': '3.0.0',
        'pillow': '11.0.0',
        'PIL': '11.0.0',
        'numpy': '2.0.0',
        'fitz': '1.25.0',
        'pymupdf': '1.25.0',
        'cv2': '4.10.0',
        'skimage': '0.24.0',
        'imgaug': '0.4.0',
        'lmdb': '1.5.0',
        'rapidfuzz': '3.10.0',
        'yaml': '6.0.0',
    }

    # Store original functions
    _original_version = importlib.metadata.version
    _original_find_spec = importlib.util.find_spec

    def _patched_version(package_name):
        """Return fake version for bundled packages."""
        # Normalize package name
        normalized = package_name.lower().replace('-', '_').replace('.', '_')
        for bundled_name, version in _BUNDLED_PACKAGES.items():
            bundled_normalized = bundled_name.lower().replace('-', '_').replace('.', '_')
            if normalized == bundled_normalized:
                return version
        return _original_version(package_name)

    def _patched_find_spec(name, package=None):
        """Return a fake spec for bundled packages if not found."""
        result = _original_find_spec(name, package)
        if result is not None:
            return result

        # Check if it's a bundled package
        normalized = name.lower().replace('-', '_').replace('.', '_')
        for bundled_name in _BUNDLED_PACKAGES:
            bundled_normalized = bundled_name.lower().replace('-', '_').replace('.', '_')
            if normalized == bundled_normalized:
                # Return a fake ModuleSpec
                class FakeSpec:
                    def __init__(self, name):
                        self.name = name
                        self.loader = None
                        self.origin = None
                        self.submodule_search_locations = None
                return FakeSpec(name)
        return result

    # Apply patches
    importlib.metadata.version = _patched_version
    importlib.util.find_spec = _patched_find_spec
