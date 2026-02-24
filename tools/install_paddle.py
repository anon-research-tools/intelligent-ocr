#!/usr/bin/env python3
"""
install_paddle.py — Detect hardware and print the correct PaddlePaddle pip command.

Run this before installing the OCR tool to get the right package for your GPU.

Usage:
    python tools/install_paddle.py
"""
import os
import platform
import subprocess
import sys


def _run(cmd: list[str], timeout: int = 5) -> tuple[bool, str]:
    """Run a command, return (success, stdout)."""
    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        return result.returncode == 0, result.stdout.strip()
    except (FileNotFoundError, subprocess.TimeoutExpired, Exception):
        return False, ""


def detect_cuda_version() -> str | None:
    """Return CUDA major.minor (e.g. '11.8') or None."""
    # Try nvcc first
    ok, out = _run(["nvcc", "--version"])
    if ok and "release" in out:
        for part in out.split():
            if part.startswith("V") and "." in part:
                ver = part[1:].strip(",")
                try:
                    major, minor = ver.split(".")[:2]
                    return f"{major}.{minor}"
                except ValueError:
                    pass

    # Try nvidia-smi
    ok, out = _run(["nvidia-smi"])
    if ok and "CUDA Version:" in out:
        for line in out.splitlines():
            if "CUDA Version:" in line:
                parts = line.split("CUDA Version:")
                if len(parts) > 1:
                    ver = parts[1].strip().split()[0]
                    try:
                        major, minor = ver.split(".")[:2]
                        return f"{major}.{minor}"
                    except ValueError:
                        pass
    return None


def detect_rocm() -> bool:
    """Return True if ROCm is available."""
    return os.path.exists("/dev/kfd")


def main():
    print("=" * 60)
    print("  OCR Tool — PaddlePaddle 安装助手")
    print("=" * 60)
    print()

    system = platform.system()

    # macOS — CPU only
    if system == "Darwin":
        print("检测到: macOS")
        print()
        print("macOS 不支持 PaddlePaddle GPU 加速（不支持 Metal/MPS）。")
        print("Apple Silicon CPU 已经足够高效，无需 GPU 版本。")
        print()
        print("安装命令:")
        print()
        print("  pip install paddlepaddle paddleocr PyMuPDF PySide6")
        print()
        print("或使用 requirements.txt:")
        print()
        print("  pip install -r requirements.txt")
        return

    # Windows — CUDA only (no ROCm)
    if system == "Windows":
        cuda_ver = detect_cuda_version()
        if cuda_ver:
            major = int(cuda_ver.split(".")[0])
            print(f"检测到: Windows + CUDA {cuda_ver}")
            print()
            if major >= 12:
                req_file = "requirements-cuda12.txt"
                post = "post120"
            else:
                req_file = "requirements-cuda11.txt"
                post = "post118"
            print("安装命令 (先卸载旧版本):")
            print()
            print("  pip uninstall paddlepaddle -y")
            print(f"  pip install paddlepaddle-gpu==2.6.1.{post} "
                  f"-f https://www.paddlepaddle.org.cn/whl/windows/mkl/avx/stable.html")
            print()
            print("或使用 requirements 文件:")
            print()
            print(f"  pip install -r {req_file}")
        else:
            print("检测到: Windows (未找到 CUDA)")
            print()
            print("安装 CPU 版本:")
            print()
            print("  pip install -r requirements.txt")
        return

    # Linux
    cuda_ver = detect_cuda_version()
    rocm_available = detect_rocm()

    if cuda_ver:
        major = int(cuda_ver.split(".")[0])
        print(f"检测到: Linux + NVIDIA CUDA {cuda_ver}")
        print()
        if major >= 12:
            req_file = "requirements-cuda12.txt"
            post = "post120"
            label = "CUDA 12.x"
        else:
            req_file = "requirements-cuda11.txt"
            post = "post118"
            label = "CUDA 11.x"
        print(f"推荐: paddlepaddle-gpu ({label})")
        print()
        print("安装命令 (先卸载旧版本):")
        print()
        print("  pip uninstall paddlepaddle -y")
        print(f"  pip install paddlepaddle-gpu==2.6.1.{post} "
              f"-f https://www.paddlepaddle.org.cn/whl/linux/mkl/avx/stable.html")
        print()
        print("或使用 requirements 文件:")
        print()
        print(f"  pip install -r {req_file}")

    elif rocm_available:
        print("检测到: Linux + AMD GPU (ROCm, /dev/kfd 存在)")
        print()
        print("推荐: paddlepaddle-rocm")
        print()
        print("安装命令 (先卸载旧版本):")
        print()
        print("  pip uninstall paddlepaddle -y")
        print("  pip install paddlepaddle-rocm==2.6.1 "
              "-f https://www.paddlepaddle.org.cn/whl/linux/rocm/stable.html")
        print()
        print("或使用 requirements 文件:")
        print()
        print("  pip install -r requirements-rocm.txt")
        print()
        print("注意: 需要 ROCm 5.7+ 驱动。")

    else:
        print("检测到: Linux (未找到 CUDA 或 ROCm)")
        print()
        print("安装 CPU 版本:")
        print()
        print("  pip install -r requirements.txt")

    print()
    print("安装完成后，运行以下命令验证:")
    print()
    print("  python -c \"from core.hardware import detect_hardware; "
          "i = detect_hardware(); print(i.recommended_device_str, i.warnings)\"")
    print()


if __name__ == "__main__":
    main()
