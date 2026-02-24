"""
Hardware detection for GPU acceleration support.

Detects CUDA (NVIDIA) and ROCm (AMD) availability through PaddlePaddle.
Provides cached device string for OCR engine initialization.

Note: macOS does not support GPU acceleration via PaddlePaddle
(neither Metal nor MPS). Apple Silicon is already optimal as CPU.
"""
from __future__ import annotations

import logging
import platform
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

_logger = logging.getLogger(__name__)

# Module-level cache for device string (cleared by clear_cache())
_cached_device_str: Optional[str] = None


@dataclass
class HardwareInfo:
    """Result of hardware detection."""
    is_cuda_compiled: bool = False
    cuda_gpu_count: int = 0
    cuda_version: str = ""
    is_rocm_compiled: bool = False
    rocm_available: bool = False
    recommended_backend: str = "cpu"      # 'cuda', 'rocm', 'cpu'
    recommended_device_str: str = "cpu"
    warnings: list = field(default_factory=list)


def detect_hardware() -> HardwareInfo:
    """
    Probe hardware and PaddlePaddle build flags to determine best device.

    This is uncached — imports paddle each call to get fresh info.
    Use get_device_string() for the fast cached path.

    Returns:
        HardwareInfo with detection results and any warnings.
    """
    info = HardwareInfo()

    # macOS: PaddlePaddle does not support Metal/MPS — CPU only
    if platform.system() == "Darwin":
        info.recommended_backend = "cpu"
        info.recommended_device_str = "cpu"
        return info

    try:
        import paddle  # type: ignore

        # --- CUDA detection ---
        try:
            info.is_cuda_compiled = paddle.device.is_compiled_with_cuda()
        except Exception:
            info.is_cuda_compiled = False

        if info.is_cuda_compiled:
            try:
                info.cuda_gpu_count = paddle.device.cuda.device_count()
            except Exception:
                info.cuda_gpu_count = 0

            try:
                info.cuda_version = str(paddle.version.cuda())
            except Exception:
                info.cuda_version = "unknown"

            if info.cuda_gpu_count > 0:
                info.recommended_backend = "cuda"
                info.recommended_device_str = "gpu:0"
                _logger.info(
                    "hardware: CUDA available — %d GPU(s), CUDA %s",
                    info.cuda_gpu_count, info.cuda_version,
                )
            else:
                info.warnings.append(
                    "PaddlePaddle 编译了 CUDA 支持，但未检测到可用 GPU。"
                    "请确认 NVIDIA 驱动和 CUDA 版本与 PaddlePaddle 匹配。"
                    "运行 tools/install_paddle.py 获取安装指引。"
                )
                _logger.warning("hardware: CUDA compiled but no GPUs found")

        # --- ROCm detection (AMD) ---
        try:
            info.is_rocm_compiled = paddle.device.is_compiled_with_rocm()
        except AttributeError:
            info.is_rocm_compiled = False

        if info.is_rocm_compiled and info.recommended_backend == "cpu":
            # /dev/kfd is the AMD GPU kernel driver character device
            kfd_exists = Path("/dev/kfd").exists()
            info.rocm_available = kfd_exists

            if kfd_exists:
                # Extra verification: try rocm-smi (best-effort)
                try:
                    subprocess.run(
                        ["rocm-smi", "--showuse"],
                        capture_output=True, timeout=5
                    )
                except (FileNotFoundError, subprocess.TimeoutExpired, Exception):
                    pass  # /dev/kfd presence is sufficient

                info.recommended_backend = "rocm"
                info.recommended_device_str = "gpu:0"
                _logger.info("hardware: ROCm available — using gpu:0")
            else:
                info.warnings.append(
                    "PaddlePaddle 编译了 ROCm 支持，但未找到 /dev/kfd（AMD GPU 驱动节点）。"
                    "请确认已安装 ROCm 驱动，并运行 tools/install_paddle.py 获取帮助。"
                )
                _logger.warning("hardware: ROCm compiled but /dev/kfd not found")

    except ImportError:
        # paddle not installed — default to cpu
        info.warnings.append("未找到 PaddlePaddle，将使用 CPU 模式。")

    return info


def get_device_string(force_cpu: bool = False) -> str:
    """
    Return the device string for PaddleOCR initialization.

    Cached after the first call. Use clear_cache() to reset.

    Args:
        force_cpu: If True, always returns 'cpu' regardless of hardware.

    Returns:
        'cpu' or 'gpu:0'
    """
    global _cached_device_str

    if force_cpu:
        return "cpu"

    if _cached_device_str is None:
        info = detect_hardware()
        _cached_device_str = info.recommended_device_str
        for warning in info.warnings:
            _logger.warning("hardware: %s", warning)

    return _cached_device_str


def clear_cache() -> None:
    """Clear the cached device string. Call when user changes GPU override in settings."""
    global _cached_device_str
    _cached_device_str = None
