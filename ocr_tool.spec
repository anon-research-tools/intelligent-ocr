# -*- mode: python ; coding: utf-8 -*-
"""
PyInstaller spec file for 智能 OCR 工具
Optimized for PaddleOCR packaging with reduced bundle size
"""
import sys
import os
from pathlib import Path

_target_arch = os.environ.get('OCR_BUILD_ARCH', 'arm64')

block_cipher = None

# Get the directory containing this spec file
SPEC_DIR = Path(SPECPATH)

# Collect data files
datas = [
    ('desktop/resources', 'resources'),
]

# Collect all PySide6 data (required for Qt to work properly)
from PyInstaller.utils.hooks import collect_all
pyside6_datas, pyside6_binaries, pyside6_hiddenimports = collect_all('PySide6')
datas += pyside6_datas

# Collect all paddleocr data (required for OCR to work)
try:
    paddleocr_datas, paddleocr_binaries, paddleocr_hiddenimports = collect_all('paddleocr')
    datas += paddleocr_datas
except Exception as e:
    print(f"Warning: Could not collect paddleocr: {e}")
    paddleocr_binaries = []
    paddleocr_hiddenimports = []

# Collect all paddlex data (required by new PaddleOCR v5+)
try:
    paddlex_datas, paddlex_binaries, paddlex_hiddenimports = collect_all('paddlex')
    datas += paddlex_datas
except Exception as e:
    print(f"Warning: Could not collect paddlex: {e}")
    paddlex_binaries = []
    paddlex_hiddenimports = []

# Collect pypdfium2 (has native libraries)
try:
    pypdfium2_datas, pypdfium2_binaries, pypdfium2_hiddenimports = collect_all('pypdfium2')
    datas += pypdfium2_datas
except Exception as e:
    print(f"Warning: Could not collect pypdfium2: {e}")
    pypdfium2_binaries = []
    pypdfium2_hiddenimports = []

# Collect openpyxl
try:
    openpyxl_datas, openpyxl_binaries, openpyxl_hiddenimports = collect_all('openpyxl')
    datas += openpyxl_datas
except Exception as e:
    print(f"Warning: Could not collect openpyxl: {e}")
    openpyxl_binaries = []
    openpyxl_hiddenimports = []

# Collect lxml (has native libraries)
try:
    lxml_datas, lxml_binaries, lxml_hiddenimports = collect_all('lxml')
    datas += lxml_datas
except Exception as e:
    print(f"Warning: Could not collect lxml: {e}")
    lxml_binaries = []
    lxml_hiddenimports = []

# Check if models directory exists (local models take precedence)
models_dir = SPEC_DIR / 'models'
if models_dir.exists():
    datas.append(('models', 'models'))

# Hidden imports for PaddleOCR and PySide6
hiddenimports = [
    # PySide6 GUI
    'PySide6',
    'PySide6.QtCore',
    'PySide6.QtGui',
    'PySide6.QtWidgets',
    # PaddleOCR v5+ (uses PaddleX backend)
    'paddleocr',
    'paddleocr._pipelines',
    'paddleocr._pipelines.ocr',
    'paddleocr._models',
    'paddlex',
    'paddlex.inference',
    'paddlex.inference.pipelines',
    'paddlex.modules',
    'paddlex.utils',
    # Paddle core
    'paddle',
    'paddle.fluid',
    'paddle.nn',
    'paddle.optimizer',
    # Image processing
    'skimage',
    'skimage.transform',
    'imgaug',
    'lmdb',
    'cv2',
    'PIL',
    'PIL.Image',
    'shapely',
    'shapely.geometry',
    'pyclipper',
    'scipy',
    'scipy.special',
    'rapidfuzz',
    'yaml',
    # PDF processing
    'fitz',
    'pymupdf',
    'pypdfium2',
    'pypdfium2._helpers',
    # OCR extra deps
    'beautifulsoup4',
    'bs4',
    'einops',
    'ftfy',
    'imagesize',
    'jinja2',
    'lxml',
    'openpyxl',
    'openpyxl.cell',
    'openpyxl.styles',
    'openpyxl.utils',
    'openpyxl.workbook',
    'openpyxl.worksheet',
    'premailer',
    'regex',
    'safetensors',
    'sklearn',
    'sentencepiece',
    'tiktoken',
    'tokenizers',
    # Additional paddlex dependencies
    'et_xmlfile',
    'cssselect',
    'cssutils',
]

# Combine all binaries and hidden imports
all_binaries = pyside6_binaries + paddleocr_binaries + paddlex_binaries + pypdfium2_binaries + openpyxl_binaries + lxml_binaries
all_hiddenimports = hiddenimports + pyside6_hiddenimports + paddleocr_hiddenimports + paddlex_hiddenimports + pypdfium2_hiddenimports + openpyxl_hiddenimports + lxml_hiddenimports

a = Analysis(
    ['main.py'],
    pathex=[str(SPEC_DIR)],
    binaries=all_binaries,
    datas=datas,
    hiddenimports=all_hiddenimports,
    hookspath=[str(SPEC_DIR / 'hooks')],
    hooksconfig={},
    runtime_hooks=[str(SPEC_DIR / 'hooks' / 'rthook_paddlex_deps.py')],
    excludes=[
        # GUI frameworks not used
        'matplotlib',
        'tkinter',
        'PIL.ImageTk',
        # Development tools
        'IPython',
        'jupyter',
        'notebook',
        # Testing (keep unittest - needed by numpy.testing)
        'pytest',
        # CUDA (if not using GPU)
        'cv2.cuda',
    ],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='智能OCR工具',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,  # No console window
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=_target_arch,
    codesign_identity=None,
    entitlements_file=None,
    icon='desktop/resources/icon.ico' if sys.platform == 'win32' else None,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name='智能OCR工具',
)

# macOS app bundle
if sys.platform == 'darwin':
    app = BUNDLE(
        coll,
        name='智能OCR工具.app',
        icon='desktop/resources/icon.icns',
        bundle_identifier='com.smartocr.tool',
        info_plist={
            'CFBundleName': '智能OCR工具',
            'CFBundleDisplayName': '智能 OCR 工具',
            'CFBundleVersion': '2.0.2',
            'CFBundleShortVersionString': '2.0.2',
            'NSHighResolutionCapable': True,
            'LSMinimumSystemVersion': '12.0',
        },
    )
