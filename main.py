#!/usr/bin/env python3
"""
智能 OCR 工具 - 将扫描版 PDF 转换为可搜索 PDF

Usage:
    python main.py              # Launch GUI
    python main.py input.pdf    # Process single file
"""
import os
import sys
from pathlib import Path

# Skip PaddleOCR network connectivity check (speeds up startup)
os.environ['PADDLE_PDX_DISABLE_MODEL_SOURCE_CHECK'] = 'True'


def _setup_exception_handler():
    """Set up global uncaught exception handler for crash logging."""
    import traceback
    from datetime import datetime

    def global_exception_handler(exc_type, exc_value, exc_tb):
        # Don't catch KeyboardInterrupt
        if issubclass(exc_type, KeyboardInterrupt):
            sys.__excepthook__(exc_type, exc_value, exc_tb)
            return

        # Format the traceback
        error_msg = ''.join(traceback.format_exception(exc_type, exc_value, exc_tb))

        # Write crash log
        try:
            log_dir = Path.home() / ".ocr_tool" / "logs"
            log_dir.mkdir(parents=True, exist_ok=True)
            crash_log = log_dir / f"crash_{datetime.now().strftime('%Y%m%d_%H%M%S')}.log"
            crash_log.write_text(error_msg, encoding='utf-8')
        except Exception:
            pass  # Don't fail in the exception handler itself

        # Try to show a Qt dialog if Qt is running
        try:
            from PySide6.QtWidgets import QApplication, QMessageBox
            app = QApplication.instance()
            if app is not None:
                msg = QMessageBox()
                msg.setIcon(QMessageBox.Icon.Critical)
                msg.setWindowTitle("程序发生错误")
                msg.setText("程序遇到意外错误，已自动保存崩溃日志。")
                msg.setInformativeText(
                    f"错误类型: {exc_type.__name__}\n"
                    f"错误信息: {str(exc_value)}\n\n"
                    f"崩溃日志已保存到:\n{log_dir}"
                )
                msg.setDetailedText(error_msg)
                msg.exec()
        except Exception:
            pass

        # Also print to stderr
        sys.__excepthook__(exc_type, exc_value, exc_tb)

    sys.excepthook = global_exception_handler


def _cleanup_stale_files():
    """Clean up stale checkpoint files from previous crashes"""
    try:
        from core.checkpoint import get_checkpoint_manager
        mgr = get_checkpoint_manager()
        cleaned = mgr.cleanup_stale_checkpoints(max_age_hours=24)
        if cleaned > 0:
            print(f"已清理 {cleaned} 个过期的检查点文件")
    except Exception:
        pass  # Don't fail startup if cleanup fails


def main():
    """Main entry point"""
    _setup_exception_handler()
    # Clean up stale files from previous crashes
    _cleanup_stale_files()

    # Check for command line arguments
    if len(sys.argv) > 1:
        # CLI mode - process file directly
        input_path = sys.argv[1]
        if input_path in ('-h', '--help'):
            print(__doc__)
            print("Options:")
            print("  -h, --help       Show this help message")
            print("  --smoke-test     Verify packaged app can import all modules")
            print("  <file.pdf>       Process a single PDF file")
            return 0

        if input_path == '--smoke-test':
            return smoke_test()

        return cli_process(input_path)

    # GUI mode
    return gui_main()


def smoke_test():
    """Verify all critical imports and native libs work in the packaged app.

    Used by CI after PyInstaller build to catch missing modules early.
    Returns 0 on success, 1 on failure.
    """
    print("Smoke test: importing paddleocr...")
    try:
        from paddleocr import PaddleOCR
        print("  OK: paddleocr")
    except ImportError as e:
        print(f"  FAIL: {e}")
        return 1

    print("Smoke test: importing core modules...")
    try:
        from core.ocr_engine import OCREngine
        from core.pdf_processor import PDFProcessor
        print("  OK: core modules")
    except ImportError as e:
        print(f"  FAIL: {e}")
        return 1

    print("Smoke test: verifying paddle inference native libs...")
    try:
        import paddle.inference
        # This triggers loading of native libs (mklml.dll on Windows)
        config = paddle.inference.Config()
        print("  OK: paddle.inference native libs")
    except Exception as e:
        print(f"  FAIL: {e}")
        return 1

    print("Smoke test: verifying OCR engine initialization...")
    try:
        engine = OCREngine(languages=['ch', 'en'], quality='balanced')
        # Force initialization (loads models via PaddleOCR)
        engine._init_ocr()
        print("  OK: OCR engine initialized successfully")
    except Exception as e:
        print(f"  FAIL: {e}")
        return 1

    print("Smoke test: all checks passed")
    return 0


def gui_main():
    """Launch the GUI application"""
    from PySide6.QtWidgets import QApplication
    from PySide6.QtCore import Qt
    from desktop.main_window import MainWindow

    # Enable High DPI support
    QApplication.setHighDpiScaleFactorRoundingPolicy(
        Qt.HighDpiScaleFactorRoundingPolicy.PassThrough
    )

    app = QApplication(sys.argv)
    app.setApplicationName("智能OCR工具")
    app.setOrganizationName("SmartOCR")

    # Set application style
    app.setStyle("Fusion")

    window = MainWindow()
    window.show()

    return app.exec()


def cli_process(input_path: str):
    """
    Process a single PDF file from command line.

    Uses pipelined processing for improved performance.
    """
    from core.ocr_engine import OCREngine
    from core.pdf_processor import PDFProcessor

    input_path = Path(input_path)
    if not input_path.exists():
        print(f"Error: File not found: {input_path}")
        return 1

    if input_path.suffix.lower() != '.pdf':
        print(f"Error: Not a PDF file: {input_path}")
        return 1

    output_path = input_path.parent / f"{input_path.stem}_ocr.pdf"

    print(f"Processing: {input_path}")
    print(f"Output: {output_path}")
    print()

    try:
        # Initialize OCR engine
        print("Initializing OCR engine...")
        engine = OCREngine(languages=['ch', 'en'])
        processor = PDFProcessor(engine, dpi=150)  # Use lower DPI for faster processing

        # Progress callback
        def progress(current: int, total: int):
            percent = int((current / total) * 100)
            bar = '=' * (percent // 2) + '>' + ' ' * (50 - percent // 2)
            print(f"\rPage {current}/{total} [{bar}] {percent}%", end='', flush=True)

        # Process file using pipelined processing
        result = processor.process_file_pipelined(
            str(input_path),
            str(output_path),
            progress_callback=progress,
        )

        print()  # New line after progress

        if result.success:
            print(f"\n{'='*50}")
            print(f"处理完成!")
            print(f"{'='*50}")
            print(f"  处理页数: {result.processed_pages}")
            if result.skipped_pages > 0:
                print(f"  跳过页数: {result.skipped_pages} (已有文字或空白)")
            print(f"  总用时: {result.elapsed_formatted}")
            print(f"  平均每页: {result.per_page_seconds:.2f}秒")
            print(f"  输出文件: {output_path}")
            print(f"{'='*50}")
            print(f"日志已保存到: ~/.ocr_tool/logs/")
            return 0
        else:
            print(f"\nError: {result.error_message}")
            return 1

    except Exception as e:
        import traceback
        print(f"\nError: {e}")
        traceback.print_exc()
        return 1


if __name__ == "__main__":
    from multiprocessing import freeze_support
    freeze_support()  # Required for Windows and PyInstaller multiprocessing
    sys.exit(main())
