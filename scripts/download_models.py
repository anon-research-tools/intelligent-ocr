#!/usr/bin/env python
"""下载均衡模式 OCR 模型，供 PyInstaller 打包使用。"""
import os
import sys
import shutil
from pathlib import Path

MODELS_DIR = Path(__file__).parent.parent / 'models'
MODELS_DIR.mkdir(exist_ok=True)

os.environ['PADDLE_PDX_DISABLE_MODEL_SOURCE_CHECK'] = '1'

REQUIRED_MODELS = [
    'PP-OCRv5_mobile_det',        # balanced 模式检测
    'PP-OCRv5_server_rec',        # balanced 模式识别
    'PP-LCNet_x1_0_textline_ori', # 文本行方向分类
]

print(f"Downloading balanced mode models: {REQUIRED_MODELS}")
print(f"Target: {MODELS_DIR}")

from paddleocr import PaddleOCR

PaddleOCR(
    lang='ch',
    text_detection_model_name='PP-OCRv5_mobile_det',
    text_recognition_model_name='PP-OCRv5_server_rec',
    use_doc_orientation_classify=False,
    use_doc_unwarping=False,
    use_textline_orientation=True,
)

print("Download complete. Copying to models/ ...")

paddlex_cache = Path.home() / '.paddlex' / 'official_models'

for model_name in REQUIRED_MODELS:
    src = paddlex_cache / model_name
    dst = MODELS_DIR / model_name
    if dst.exists():
        shutil.rmtree(dst)  # 确保是最新版
    if src.exists():
        shutil.copytree(src, dst)
        print(f"  OK: {model_name}")
    else:
        print(f"  FATAL: {model_name} not found at {src}")
        sys.exit(1)

# 严格验证
for model_name in REQUIRED_MODELS:
    model_dir = MODELS_DIR / model_name
    has_files = any(model_dir.glob('inference.*'))
    if not has_files:
        print(f"FATAL: {model_name} has no inference files")
        sys.exit(1)

print(f"All {len(REQUIRED_MODELS)} models verified OK")
print(f"models/ contents: {[p.name for p in MODELS_DIR.iterdir()]}")
