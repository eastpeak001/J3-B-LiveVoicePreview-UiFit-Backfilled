from __future__ import annotations

import argparse
import os
import platform
import re
import subprocess
import sys
from datetime import datetime
from pathlib import Path


PACKAGE_ROOT = Path(__file__).resolve().parents[1]


def run(command: list[str], timeout: int = 20) -> str:
    try:
        completed = subprocess.run(command, text=True, capture_output=True, timeout=timeout, check=False)
        output = completed.stdout
        if completed.stderr:
            output += ("\n" if output else "") + completed.stderr
        return f"$ {' '.join(command)}\nexit={completed.returncode}\n{output.strip()}"
    except (OSError, subprocess.TimeoutExpired) as exc:
        return f"$ {' '.join(command)}\nERROR: {type(exc).__name__}: {exc}"


def read_file(path: str) -> str:
    target = Path(path)
    try:
        return target.read_text(encoding="utf-8", errors="replace").strip()
    except Exception as exc:
        return f"<read failed: {type(exc).__name__}: {exc}>"


def glob_text(pattern: str) -> str:
    paths = sorted(Path("/").glob(pattern.lstrip("/")))
    if not paths:
        return "NO_MATCHES"
    lines = []
    for path in paths:
        try:
            if path.is_file():
                lines.append(f"{path}: {read_file(str(path))}")
        except Exception as exc:
            lines.append(f"{path}: <read failed: {type(exc).__name__}: {exc}>")
    return "\n".join(lines)


def python_environment() -> tuple[str, str]:
    lines = [f"Python: {sys.version}", f"Executable: {sys.executable}"]
    build_info = "OpenCV unavailable"
    try:
        import numpy as np

        lines.append(f"NumPy: {np.__version__}")
    except Exception as exc:
        lines.append(f"NumPy: unavailable ({exc})")
    try:
        import cv2

        lines.append(f"OpenCV: {cv2.__version__}")
        lines.append(f"cv2.ximgproc: {hasattr(cv2, 'ximgproc')}")
        lines.append(f"cv2.cuda: {hasattr(cv2, 'cuda')}")
        if hasattr(cv2, "cuda"):
            try:
                lines.append(f"cv2.cuda device count: {cv2.cuda.getCudaEnabledDeviceCount()}")
            except Exception as exc:
                lines.append(f"cv2.cuda device count: ERROR ({exc})")
        build_info = cv2.getBuildInformation()
    except Exception as exc:
        lines.append(f"OpenCV: unavailable ({exc})")
    return "\n".join(lines), build_info


def group_status() -> str:
    try:
        import grp

        names = {grp.getgrgid(group_id).gr_name for group_id in os.getgroups()}
    except (ImportError, KeyError, OSError):
        return "group inspection is available on Linux only"
    return f"user={os.environ.get('USER', 'unknown')} groups={sorted(names)} video_member={'video' in names}"


def main() -> int:
    parser = argparse.ArgumentParser(description="Read-only Jetson platform preflight")
    parser.add_argument("--report-dir", type=Path, default=PACKAGE_ROOT / "reports")
    args = parser.parse_args()
    args.report_dir.mkdir(parents=True, exist_ok=True)
    python_info, build_info = python_environment()
    (args.report_dir / "opencv_build_information.txt").write_text(build_info + "\n", encoding="utf-8")
    commands = {
        "uname": ["uname", "-a"],
        "pip": [sys.executable, "-m", "pip", "--version"],
        "JetPack packages": ["dpkg-query", "-W", "-f=${binary:Package}\t${Version}\n", "nvidia-jetpack", "nvidia-l4t-core"],
        "nvcc": ["nvcc", "--version"],
        "tegrastats path": ["sh", "-c", "command -v tegrastats || true"],
        "nvpmodel verbose": ["sudo", "-n", "nvpmodel", "-q", "--verbose"],
        "nvpmodel fallback": ["sudo", "-n", "nvpmodel", "-q"],
        "jetson_clocks": ["sudo", "-n", "jetson_clocks", "--show"],
        "lsusb": ["lsusb"],
        "video nodes": ["sh", "-c", "ls -l /dev/video* 2>&1 || true"],
        "v4l2-ctl path": ["sh", "-c", "command -v v4l2-ctl || true"],
        "GStreamer": ["gst-launch-1.0", "--version"],
        "GStreamer v4l2src": ["gst-inspect-1.0", "v4l2src"],
        "disk": ["df", "-hT"],
        "memory": ["free", "-h"],
        "swap": ["swapon", "--show"],
        "CUDA libraries": ["sh", "-c", "ldconfig -p 2>/dev/null | grep -E 'libcuda|libcudart' || true"],
    }
    raw_sections = [
        f"Generated: {datetime.now().astimezone().isoformat()}",
        f"platform: {platform.platform()}",
        "===== /etc/os-release =====\n" + read_file("/etc/os-release"),
        "===== /etc/nv_tegra_release =====\n" + read_file("/etc/nv_tegra_release"),
        "===== Python environment =====\n" + python_info,
        "===== User groups =====\n" + group_status(),
        "===== Temperatures =====\n" + glob_text("sys/class/thermal/thermal_zone*/temp"),
        "===== Thermal types =====\n" + glob_text("sys/class/thermal/thermal_zone*/type"),
        "===== Fan state =====\n" + glob_text("sys/class/hwmon/hwmon*/pwm*"),
    ]
    command_outputs = {
        title: run(command)
        for title, command in commands.items()
        if title != "nvpmodel fallback"
    }
    verbose_result = command_outputs["nvpmodel verbose"]
    if "ERROR:" in verbose_result or "exit=0" not in verbose_result:
        command_outputs["nvpmodel fallback"] = run(commands["nvpmodel fallback"])
    else:
        command_outputs["nvpmodel fallback"] = "NOT RUN: verbose query succeeded"
    for title, output in command_outputs.items():
        raw_sections.append(f"===== {title} =====\n{output}")
    raw = "\n\n".join(raw_sections) + "\n"
    (args.report_dir / "jetson_preflight_raw.txt").write_text(raw, encoding="utf-8")
    nvpmodel_output = command_outputs["nvpmodel verbose"]
    if "ERROR:" in nvpmodel_output or "exit=0" not in nvpmodel_output:
        nvpmodel_output = command_outputs["nvpmodel fallback"]
    temperature_output = glob_text("sys/class/thermal/thermal_zone*/temp")
    has_25w = bool(re.search(r"(?i)25\s*W", nvpmodel_output))
    has_maxn_super = bool(re.search(r"(?i)MAXN\s*SUPER", nvpmodel_output))
    report = [
        "# Jetson Preflight Report",
        "",
        f"Generated: {datetime.now().astimezone().isoformat()}",
        "",
        "This preflight is read-only. Missing components are recorded and are not installed automatically.",
        "",
        "## Platform",
        "",
        "```text",
        read_file("/etc/os-release"),
        "```",
        "",
        "## NVIDIA release",
        "",
        "```text",
        read_file("/etc/nv_tegra_release"),
        "```",
        "",
        "## Python and OpenCV",
        "",
        "```text",
        python_info,
        "```",
        "",
        "## Video group",
        "",
        f"`{group_status()}`",
        "",
        "## Power and clocks",
        "",
        "No mode was changed and no nvpmodel ID is hard-coded.",
        f"- 25W mode mentioned by nvpmodel: `{has_25w}`",
        f"- MAXN SUPER mentioned by nvpmodel: `{has_maxn_super}`",
        "",
        "```text",
        nvpmodel_output,
        "```",
        "",
        "jetson_clocks status:",
        "",
        "```text",
        command_outputs["jetson_clocks"],
        "```",
        "",
        "Temperature readings:",
        "",
        "```text",
        temperature_output,
        "```",
        "",
        "## Camera and multimedia summary",
        "",
        "```text",
        command_outputs["video nodes"],
        command_outputs["v4l2-ctl path"],
        command_outputs["GStreamer"],
        "```",
        "",
        "## Detailed evidence",
        "",
        "See `jetson_preflight_raw.txt` and `opencv_build_information.txt`.",
    ]
    (args.report_dir / "jetson_preflight_report.md").write_text("\n".join(report) + "\n", encoding="utf-8")
    print(f"Reports written to {args.report_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
