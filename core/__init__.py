# OCR Tool Core Module
# NOTE: Heavy imports (OCREngine, PDFProcessor) are NOT eagerly loaded here.
# Import them directly from their modules to avoid loading PaddleOCR at startup:
#   from core.ocr_engine import OCREngine
#   from core.pdf_processor import PDFProcessor
