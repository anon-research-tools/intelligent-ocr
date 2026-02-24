#!/usr/bin/env python
"""
下载均衡模式 OCR 模型，供 PyInstaller 打包使用。

CI 构建时调用：
    python scripts/download_models.py

会将 PP-OCRv4_mobile_det 和 PP-OCRv5_server_rec 下载到 models/ 目录，
PyInstaller 打包时自动包含这两个模型（见 ocr_tool.spec）。
"""
import os
import sys
import shutil
from pathlib import Path

MODELS_DIR = Path(__file__).parent.parent / 'models'
MODELS_DIR.mkdir(exist_ok=True)

os.environ['PADDLE_PDX_DISABLE_MODEL_SOURCE_CHECK'] = '1'

print("Downloading balanced mode models (PP-OCRv4_mobile_det + PP-OCRv5_server_rec)...")
print(f"Models will be saved to: {MODELS_DIR}")

from paddleocr import PaddleOCR

PaddleOCR(
    lang='ch',
    text_detection_model_name='PP-OCRv4_mobile_det',
    text_recognition_model_name='PP-OCRv5_server_rec',
    use_doc_orientation_classify=False,
    use_doc_unwarping=False,
    use_textline_orientation=True,
)

print("Download complete. Copying to models/ ...")

paddlex_cache = Path.home() / '.paddlex' / 'official_models'

for model_name in ['PP-OCRv4_mobile_det', 'PP-OCRv5_server_rec']:
    src = paddlex_cache / model_name
    dst = MODELS_DIR / model_name
    if src.exists() and not dst.exists():
        shutil.copytree(src, dst)
        print(f"Copied {model_name} -> models/{model_name}")
    elif dst.exists():
        print(f"Already exists: models/{model_name}")
    else:
        print(f"Warning: {model_name} not found in PaddleX cache at {src}")

contents = [p.name for p in MODELS_DIR.iterdir()]
print(f"Done. models/ contents: {contents}")
