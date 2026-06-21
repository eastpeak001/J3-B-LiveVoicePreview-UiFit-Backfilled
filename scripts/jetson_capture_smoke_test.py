from __future__ import annotations

import argparse
import hashlib
import re
import subprocess
import time
from pathlib import Path

import cv2
import numpy as np
import psutil
import yaml

PACKAGE_ROOT = Path(__file__).resolve().parents[1]
SMOKE_TEST_DEVICE = "/dev/video0"


def force_v4l2_mode(device: str, width: int, height: int, fps: float, fourcc: str) -> None:
    subprocess.run(
        [
            "v4l2-ctl",
            "-d",
            device,
            f"--set-fmt-video=width={width},height={height},pixelformat={fourcc}",
            f"--set-parm={fps:g}",
        ],
        check=True,
        text=True,
        capture_output=True,
    )


def get_v4l2_fps(device: str) -> float:
    result = subprocess.run(
        ["v4l2-ctl", "-d", device, "--get-parm"],
        check=True,
        text=True,
        capture_output=True,
    )
    output = result.stdout + result.stderr
    match = re.search(r"Frames per second:\s*([0-9]+(?:\.[0-9]+)?)", output, re.IGNORECASE)
    if not match:
        raise RuntimeError(f"Could not parse V4L2 frame rate from --get-parm output: {output.strip()}")
    return float(match.group(1))


def open_capture(device: str, width: int, height: int, fps: float, fourcc: str) -> cv2.VideoCapture:
    cap = cv2.VideoCapture(device, cv2.CAP_V4L2)
    if not cap.isOpened():
        cap.release()
        raise RuntimeError(f"Could not open {device} with CAP_V4L2")
    cap.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc(*fourcc))
    cap.set(cv2.CAP_PROP_FRAME_WIDTH, float(width))
    cap.set(cv2.CAP_PROP_FRAME_HEIGHT, float(height))
    cap.set(cv2.CAP_PROP_FPS, float(fps))
    return cap


def fourcc_text(value: float) -> str:
    number = int(value) & 0xFFFFFFFF
    return bytes((number >> (8 * index)) & 0xFF for index in range(4)).decode("ascii", errors="replace")


def choose_device(requested: str) -> str:
    return SMOKE_TEST_DEVICE if requested == "auto" else requested


def main() -> int:
    parser = argparse.ArgumentParser(description="60-second V4L2 SBS capture smoke test; no depth processing")
    parser.add_argument("--device", default="auto")
    parser.add_argument("--duration", type=float, default=60.0)
    parser.add_argument("--config", type=Path, default=PACKAGE_ROOT / "config" / "depth_runtime_jetson.yaml")
    args = parser.parse_args()
    config = yaml.safe_load(args.config.resolve().read_text(encoding="utf-8"))
    camera = config["camera"]
    requested_device = args.device
    if requested_device == "auto" and camera.get("preferred_device"):
        requested_device = str(camera["preferred_device"])
    device = choose_device(requested_device)
    width = int(camera["width"])
    height = int(camera["height"])
    fps = float(camera["fps"])
    fourcc = str(camera["fourcc"])

    force_v4l2_mode(device, width, height, fps, fourcc)
    cap = open_capture(device, width, height, fps, fourcc)
    v4l2_fps_checks = [get_v4l2_fps(device)]
    reopened = False
    if v4l2_fps_checks[-1] <= 5.5:
        cap.release()
        force_v4l2_mode(device, width, height, fps, fourcc)
        cap = open_capture(device, width, height, fps, fourcc)
        v4l2_fps_checks.append(get_v4l2_fps(device))
        reopened = True

    actual = {
        "width": int(cap.get(cv2.CAP_PROP_FRAME_WIDTH)),
        "height": int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT)),
        "fourcc": fourcc_text(cap.get(cv2.CAP_PROP_FOURCC)),
    }
    opencv_fps = float(cap.get(cv2.CAP_PROP_FPS))
    v4l2_fps = v4l2_fps_checks[-1]
    process = psutil.Process()
    process.cpu_percent(None)
    failures = 0
    try:
        warmed = 0
        while warmed < int(camera["warmup_frames"]):
            ok, frame = cap.read()
            if ok and frame is not None and frame.shape[:2] == (720, 2560):
                warmed += 1
            else:
                failures += 1
        start = time.perf_counter()
        previous_time = start
        previous_digest = None
        intervals: list[float] = []
        frame_count = 0
        repeated = 0
        stalls = 0
        saved_frame = None
        while time.perf_counter() - start < args.duration:
            ok, frame = cap.read()
            now = time.perf_counter()
            if not ok or frame is None:
                failures += 1
                continue
            interval = now - previous_time
            previous_time = now
            intervals.append(interval)
            stalls += int(interval > 0.100)
            digest_frame = cv2.resize(frame, (160, 45), interpolation=cv2.INTER_AREA)
            digest = hashlib.sha256(digest_frame.tobytes()).digest()
            repeated += int(digest == previous_digest)
            previous_digest = digest
            frame_count += 1
            if saved_frame is None:
                saved_frame = frame.copy()
        elapsed = time.perf_counter() - start
        if saved_frame is None or saved_frame.shape[:2] != (720, 2560):
            raise RuntimeError("No valid 2560x720 SBS frame was captured")
        physical_left = saved_frame[:, :1280]
        physical_right = saved_frame[:, 1280:]
        output_dir = PACKAGE_ROOT / "outputs" / "smoke"
        output_dir.mkdir(parents=True, exist_ok=True)
        cv2.imwrite(str(output_dir / "raw_sbs.png"), saved_frame)
        cv2.imwrite(str(output_dir / "physical_left.png"), physical_left)
        cv2.imwrite(str(output_dir / "physical_right.png"), physical_right)
        p95_ms = float(np.percentile(np.asarray(intervals), 95) * 1000.0) if intervals else float("nan")
        lines = [
            "# Jetson Capture Smoke Test",
            "",
            f"- Device: `{device}`",
            f"- Requested: MJPG {camera['width']}x{camera['height']} at {camera['fps']} FPS",
            f"- Actual: `{actual}`",
            f"- OpenCV reported FPS: {opencv_fps:.3f}",
            f"- V4L2 reported FPS: {v4l2_fps:.3f}",
            f"- VideoCapture reopened after 5 FPS detection: {'yes' if reopened else 'no'}",
            f"- V4L2 FPS checks after OpenCV open: {', '.join(f'{value:.3f}' for value in v4l2_fps_checks)}",
            f"- Duration: {elapsed:.3f} s",
            f"- Frames: {frame_count}",
            f"- Measured FPS: {frame_count / elapsed:.3f}",
            f"- Average FPS: {frame_count / elapsed:.3f}",
            f"- P95 frame interval: {p95_ms:.3f} ms",
            f"- Read failures: {failures}",
            f"- Repeated frames: {repeated}",
            f"- Intervals over 100 ms: {stalls}",
            f"- Process CPU: {process.cpu_percent(None):.1f}%",
            f"- Process RSS: {process.memory_info().rss / (1024 * 1024):.2f} MiB",
            "- Raw shape: 2560x720",
            "- Physical left shape: 1280x720 (raw left half; no swap)",
            "- Physical right shape: 1280x720 (raw right half; no swap)",
        ]
        report = PACKAGE_ROOT / "reports" / "jetson_capture_smoke_report.md"
        report.write_text("\n".join(lines) + "\n", encoding="utf-8")
        print("\n".join(lines))
    finally:
        cap.release()
        print("Camera released.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
