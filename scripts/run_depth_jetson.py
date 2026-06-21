from __future__ import annotations

import argparse
import hashlib
import json
import os
import queue
import re
import shutil
import subprocess
import threading
import time
from collections import deque
from datetime import datetime
from pathlib import Path
from typing import Any

import cv2
import numpy as np
import psutil
import yaml

from depth_core_jetson import StereoDepthProcessor, depth_visual, disparity_visual, load_runtime_config
from jetson_audio_common import kernel_usb_errors, run_command, thermal_snapshot
from jetson_camera_probe import enumerate_devices, select_recommended
from verify_deployment_assets import verify


PACKAGE_ROOT = Path(__file__).resolve().parents[1]
CAMERA_PROBE_STATE = PACKAGE_ROOT / "reports" / "camera_probe.json"
REPORT_PATH = PACKAGE_ROOT / "reports" / "jetson_depth_cpu_baseline_report.md"
CAMERA_SELECTION_SOURCE = "requested"


def recommended_from_probe_state(path: Path = CAMERA_PROBE_STATE) -> str | None:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, UnicodeError):
        return None
    candidates = [
        record["device"]
        for record in payload
        if isinstance(record, dict)
        and isinstance(record.get("device"), str)
        and Path(record["device"]).exists()
        and record.get("capture_capable") is True
        and record.get("supports_mjpg_2560x720_60") is True
        and str(record.get("vid", "")).lower() == "1bcf"
        and str(record.get("pid", "")).lower() == "2d4f"
    ] if isinstance(payload, list) else []
    if len(candidates) > 1:
        raise RuntimeError(f"camera_probe.json has multiple matching target nodes: {candidates}")
    return candidates[0] if candidates else None


def choose_device(requested: str) -> str:
    global CAMERA_SELECTION_SOURCE
    if requested != "auto":
        CAMERA_SELECTION_SOURCE = "requested/config"
        return requested
    probed = recommended_from_probe_state()
    if probed:
        CAMERA_SELECTION_SOURCE = "camera_probe.json"
        return probed
    CAMERA_SELECTION_SOURCE = "live_probe"
    records, _ = enumerate_devices()
    recommended = select_recommended(records)
    if not recommended:
        raise RuntimeError("No unique target-mode V4L2 camera. Run scripts/jetson_camera_probe.py first.")
    return str(recommended["device"])


def force_v4l2_mode(device: str, camera: dict[str, Any]) -> float:
    if not shutil.which("v4l2-ctl"):
        raise RuntimeError("v4l2-ctl is required to force and verify the camera mode")
    subprocess.run(
        [
            "v4l2-ctl", "-d", device,
            f"--set-fmt-video=width={camera['width']},height={camera['height']},pixelformat={camera['fourcc']}",
            f"--set-parm={float(camera['fps']):g}",
        ],
        check=True, text=True, capture_output=True,
    )
    result = subprocess.run(
        ["v4l2-ctl", "-d", device, "--get-parm"],
        check=True, text=True, capture_output=True,
    )
    match = re.search(r"Frames per second:\s*([0-9]+(?:\.[0-9]+)?)", result.stdout + result.stderr, re.I)
    if not match:
        raise RuntimeError("Could not verify V4L2 reported FPS")
    return float(match.group(1))


class LatestFrameCapture:
    def __init__(self, device: str, camera: dict[str, Any], queue_size: int = 1):
        self.cap = cv2.VideoCapture(device, cv2.CAP_V4L2)
        if not self.cap.isOpened():
            self.cap.release()
            raise RuntimeError(f"Could not open {device} with CAP_V4L2")
        # Keep this order aligned with the mode sequence validated by J2.1.
        self.cap.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc(*camera["fourcc"]))
        self.cap.set(cv2.CAP_PROP_FRAME_WIDTH, float(camera["width"]))
        self.cap.set(cv2.CAP_PROP_FRAME_HEIGHT, float(camera["height"]))
        self.cap.set(cv2.CAP_PROP_FPS, float(camera["fps"]))
        self.frames: queue.Queue[tuple[float, np.ndarray]] = queue.Queue(maxsize=queue_size)
        self.stop_event = threading.Event()
        self.capture_count = 0
        self.read_failures = 0
        self.repeated_frames = 0
        self.stalls_over_100ms = 0
        self.intervals: list[float] = []
        self._previous_time: float | None = None
        self._previous_digest: bytes | None = None
        self.started = 0.0
        self.released = False
        self.thread = threading.Thread(target=self._worker, name="v4l2-latest-frame", daemon=True)

    def warmup(self, count: int) -> None:
        successful = 0
        while successful < count:
            ok, frame = self.cap.read()
            if ok and frame is not None and frame.shape[:2] == (720, 2560):
                successful += 1
            else:
                self.read_failures += 1

    def start(self) -> None:
        self.started = time.perf_counter()
        self.thread.start()

    def _worker(self) -> None:
        while not self.stop_event.is_set():
            ok, frame = self.cap.read()
            if not ok or frame is None or frame.shape[:2] != (720, 2560):
                self.read_failures += 1
                continue
            self.capture_count += 1
            captured_at = time.perf_counter()
            if self._previous_time is not None:
                interval = captured_at - self._previous_time
                self.intervals.append(interval)
                self.stalls_over_100ms += int(interval > 0.100)
            self._previous_time = captured_at
            digest = hashlib.blake2b(frame[::16, ::16].tobytes(), digest_size=8).digest()
            self.repeated_frames += int(digest == self._previous_digest)
            self._previous_digest = digest
            item = (captured_at, frame)
            if self.frames.full():
                try:
                    self.frames.get_nowait()
                except queue.Empty:
                    pass
            try:
                self.frames.put_nowait(item)
            except queue.Full:
                pass

    def get(self, timeout: float = 2.0) -> tuple[float, np.ndarray]:
        return self.frames.get(timeout=timeout)

    def capture_fps(self) -> float:
        elapsed = time.perf_counter() - self.started
        return self.capture_count / elapsed if elapsed > 0 else 0.0

    def close(self) -> None:
        self.stop_event.set()
        if self.thread.is_alive():
            self.thread.join(timeout=3.0)
        self.cap.release()
        self.released = not self.cap.isOpened() and not self.thread.is_alive()


class TemporalMedian:
    def __init__(self, window: int, absolute_mm: float, relative: float):
        self.values: deque[float] = deque(maxlen=window)
        self.absolute_mm = absolute_mm
        self.relative = relative
        self.rejected = 0

    def update(self, value: float) -> tuple[float, bool]:
        if not np.isfinite(value):
            return (float(np.median(self.values)) if self.values else float("nan"), False)
        if self.values:
            center = float(np.median(self.values))
            threshold = max(self.absolute_mm, abs(center) * self.relative)
            if abs(value - center) > threshold:
                self.rejected += 1
                return center, False
        self.values.append(value)
        return float(np.median(self.values)), True


def roi_median(frame, roi: dict[str, int]) -> tuple[float, float]:
    x, y, width, height = (int(roi[key]) for key in ("x", "y", "width", "height"))
    mask = frame.valid_depth_mask[y : y + height, x : x + width]
    values = frame.depth_mm[y : y + height, x : x + width][mask]
    return (float(np.median(values)) if values.size else float("nan"), float(np.mean(mask)))


def render(frame, config: dict[str, Any], capture_fps: float, depth_fps: float, temporal_mm: float, accepted: bool) -> np.ndarray:
    disparity = disparity_visual(
        frame.active_disparity_px,
        frame.valid_disparity_mask,
        float(config["sgbm"]["num_disparities"]),
    )
    depth = depth_visual(
        frame.depth_mm,
        frame.valid_depth_mask,
        float(config["depth"]["minimum_mm"]),
        float(config["depth"]["maximum_mm"]),
    )
    top = np.hstack((frame.rectified_left, frame.rectified_right))
    bottom = np.hstack((disparity, depth))
    canvas = np.vstack((top, bottom))
    display = cv2.resize(canvas, (1280, 720), interpolation=cv2.INTER_AREA)
    lines = [
        "JETSON CPU BASELINE - StereoSGBM is not GPU accelerated",
        "RAW left half = physical left | RAW right half = physical right | swap OFF",
        f"capture FPS={capture_fps:.2f} depth FPS={depth_fps:.2f} WLS={'ON' if frame.disparity_wls_px is not None else 'OFF'}",
        f"ROI temporal depth={temporal_mm:.1f} mm sample={'accepted' if accepted else 'rejected'} sign={'OK' if frame.sign_ok else 'ERROR'}",
        "Q/Esc: quit",
    ]
    for index, text in enumerate(lines):
        cv2.putText(display, text, (12, 28 + index * 26), cv2.FONT_HERSHEY_SIMPLEX, 0.62, (0, 255, 255), 2, cv2.LINE_AA)
    return display


def main() -> int:
    parser = argparse.ArgumentParser(description="Jetson V4L2 CPU StereoSGBM baseline")
    parser.add_argument("--config", type=Path, default=PACKAGE_ROOT / "config" / "depth_runtime_jetson.yaml")
    parser.add_argument("--device", default="auto")
    parser.add_argument("--no-gui", action="store_true")
    parser.add_argument("--duration", type=float, default=0.0, help="Headless runtime in seconds; 0 runs until interrupted")
    parser.add_argument("--disable-wls", action="store_true")
    parser.add_argument("--report-path", type=Path, default=REPORT_PATH)
    args = parser.parse_args()
    errors = verify(False)
    if errors:
        raise RuntimeError("Deployment asset verification failed: " + "; ".join(errors))
    config = load_runtime_config(args.config.resolve())
    if args.disable_wls:
        config["wls"]["enabled"] = False
    gui_requested = bool(config["runtime"].get("gui", True)) and not args.no_gui
    gui_enabled = gui_requested
    gui_disabled_reason = "not requested"
    if gui_enabled and not (os.environ.get("DISPLAY") or os.environ.get("WAYLAND_DISPLAY")):
        gui_enabled = False
        gui_disabled_reason = "no DISPLAY or WAYLAND_DISPLAY"
    processor = StereoDepthProcessor(config)
    requested_device = args.device
    if requested_device == "auto":
        requested_device = str(config["camera"].get("preferred_device") or config["camera"]["device"])
    device = choose_device(requested_device)
    v4l2_fps = force_v4l2_mode(device, config["camera"])
    queue_size = int(config["runtime"]["queue_size"])
    capture = LatestFrameCapture(device, config["camera"], queue_size=queue_size)
    actual_width = int(capture.cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    actual_height = int(capture.cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    opencv_fps = float(capture.cap.get(cv2.CAP_PROP_FPS))
    actual_fourcc_int = int(capture.cap.get(cv2.CAP_PROP_FOURCC))
    actual_fourcc = "".join(chr((actual_fourcc_int >> (8 * index)) & 0xFF) for index in range(4))
    expected_mode = (int(config["camera"]["width"]), int(config["camera"]["height"]), str(config["camera"]["fourcc"]))
    if (actual_width, actual_height, actual_fourcc) != expected_mode:
        capture.close()
        raise RuntimeError(
            f"Camera mode mismatch: got {actual_width}x{actual_height} {actual_fourcc}, expected {expected_mode}"
        )
    temporal_config = config["measurement"]
    temporal = TemporalMedian(
        int(temporal_config["temporal_window"]),
        float(temporal_config["temporal_outlier_absolute_mm"]),
        float(temporal_config["temporal_outlier_relative"]),
    )
    processed = 0
    depth_started = 0.0
    processing_ms: list[float] = []
    end_to_end_ms: list[float] = []
    sgbm_ms: list[float] = []
    valid_ratios: list[float] = []
    roi_depths: list[float] = []
    cpu_samples: list[float] = []
    memory_samples: list[float] = []
    sign_failures = 0
    q_errors: list[float] = []
    temperature_before = thermal_snapshot()
    kernel_before = run_command(["dmesg"], timeout=10).combined if shutil.which("dmesg") else ""
    psutil.cpu_percent(interval=None)
    next_system_sample = 0.0
    failure: Exception | None = None
    try:
        capture.warmup(int(config["camera"]["warmup_frames"]))
        capture.start()
        depth_started = time.perf_counter()
        next_system_sample = depth_started
        while True:
            if args.duration > 0 and time.perf_counter() - depth_started >= args.duration:
                break
            captured_at, raw = capture.get(timeout=3.0)
            frame = processor.process(raw, use_wls=processor.wls_enabled, compute_wls=processor.wls_enabled)
            finished_at = time.perf_counter()
            processed += 1
            current_mm, valid_ratio = roi_median(frame, config["measurement"]["roi"])
            temporal_mm, accepted = temporal.update(current_mm)
            processing_ms.append(float(frame.timings_ms["total"]))
            sgbm_ms.append(float(frame.timings_ms["sgbm_and_right"]))
            end_to_end_ms.append((finished_at - captured_at) * 1000.0)
            valid_ratios.append(float(np.mean(frame.valid_depth_mask)))
            if np.isfinite(current_mm):
                roi_depths.append(current_mm)
            sign_failures += int(not frame.sign_ok)
            if np.isfinite(frame.q_formula_relative_error):
                q_errors.append(frame.q_formula_relative_error)
            if finished_at >= next_system_sample:
                cpu_samples.append(psutil.cpu_percent(interval=None))
                memory_samples.append(psutil.virtual_memory().percent)
                next_system_sample = finished_at + 1.0
            elapsed = time.perf_counter() - depth_started
            depth_fps = processed / elapsed if elapsed > 0 else 0.0
            if gui_enabled:
                try:
                    cv2.imshow("Jetson Stereo Depth CPU Baseline", render(frame, config, capture.capture_fps(), depth_fps, temporal_mm, accepted))
                    key = cv2.waitKey(1) & 0xFF
                    if key in (ord("q"), 27):
                        break
                except cv2.error as exc:
                    gui_enabled = False
                    gui_disabled_reason = f"OpenCV GUI unavailable: {exc}"
                    print(f"GUI disabled: {gui_disabled_reason}")
            if not gui_enabled and processed % 10 == 0:
                print(
                    json.dumps(
                        {
                            "capture_fps": capture.capture_fps(),
                            "depth_fps": depth_fps,
                            "roi_depth_mm": temporal_mm,
                            "roi_valid_ratio": valid_ratio,
                            "temporal_rejected": temporal.rejected,
                            "wls_active": processor.wls_enabled,
                            "cpu_baseline": True,
                        }
                    )
                )
    except KeyboardInterrupt:
        pass
    except Exception as exc:
        failure = exc
    finally:
        capture.close()
        if gui_enabled:
            try:
                cv2.destroyAllWindows()
            except cv2.error as exc:
                gui_enabled = False
                gui_disabled_reason = f"OpenCV GUI cleanup failed: {exc}"
        elapsed = max(time.perf_counter() - depth_started, 1e-9) if depth_started else 0.0
        temperature_after = thermal_snapshot()
        kernel_after = run_command(["dmesg"], timeout=10).combined if shutil.which("dmesg") else ""
        new_kernel_text = kernel_after[len(kernel_before):] if kernel_after.startswith(kernel_before) else kernel_after
        usb_errors = kernel_usb_errors(new_kernel_text)
        capture_p95_interval_ms = float(np.percentile(capture.intervals, 95) * 1000.0) if capture.intervals else float("nan")
        mean_valid = float(np.mean(valid_ratios)) if valid_ratios else 0.0
        roi_median_mm = float(np.median(roi_depths)) if roi_depths else float("nan")
        passed = bool(
            failure is None and processed > 0 and mean_valid > 0 and roi_depths
            and sign_failures == 0 and capture.read_failures == 0 and not usb_errors and capture.released
        )
        status = "PASS" if passed else "FAIL"
        lines = [
            "# Jetson Depth CPU Baseline Report", "",
            f"- Generated: {datetime.now().isoformat(timespec='seconds')}",
            f"- Status: **{status}**", f"- Duration: {elapsed:.3f} s", "",
            "## Camera and inputs", "",
            f"- Selected camera device: `{device}`",
            f"- Camera selected from: {CAMERA_SELECTION_SOURCE}",
            f"- GUI enabled/disabled: {'enabled' if gui_enabled else 'disabled'}",
            f"- GUI requested: {gui_requested}",
            f"- GUI disabled reason: {gui_disabled_reason if not gui_enabled else 'none'}",
            "- Calibration file: `config/calibration_canonical.yaml`",
            "- Maps file: `config/calibration_maps_canonical.npz`",
            "- Canonical order: raw SBS left = physical left; raw SBS right = physical right; swap_left_right=false",
            f"- Negotiated mode: `{actual_width}x{actual_height} {actual_fourcc}`",
            f"- V4L2 reported FPS: {v4l2_fps:.3f}",
            f"- OpenCV reported FPS: {opencv_fps:.3f}",
            f"- Latest-frame-only queue size: {queue_size}", "",
            "## Performance", "",
            f"- Capture frames: {capture.capture_count}",
            f"- Processed depth frames: {processed}",
            f"- Measured capture FPS: {capture.capture_count / elapsed if elapsed else 0.0:.3f}",
            f"- Measured depth FPS: {processed / elapsed if elapsed else 0.0:.3f}",
            f"- Average processing latency: {float(np.mean(processing_ms)) if processing_ms else float('nan'):.3f} ms",
            f"- P95 processing latency: {float(np.percentile(processing_ms, 95)) if processing_ms else float('nan'):.3f} ms",
            f"- Average end-to-end latency: {float(np.mean(end_to_end_ms)) if end_to_end_ms else float('nan'):.3f} ms",
            f"- P95 end-to-end latency: {float(np.percentile(end_to_end_ms, 95)) if end_to_end_ms else float('nan'):.3f} ms",
            f"- Average SGBM (left+right) time: {float(np.mean(sgbm_ms)) if sgbm_ms else float('nan'):.3f} ms",
            f"- P95 SGBM (left+right) time: {float(np.percentile(sgbm_ms, 95)) if sgbm_ms else float('nan'):.3f} ms",
            f"- WLS requested/active: {config['wls']['enabled']}/{processor.wls_enabled}",
            "- Acceleration: CPU StereoSGBM; no CUDA/VPI path invoked", "",
            "## Depth validity", "",
            f"- Mean valid depth pixel ratio: {mean_valid:.6%}",
            f"- Median ROI depth: {roi_median_mm:.3f} mm",
            f"- Frames with sign check failure: {sign_failures}",
            f"- Median Q/formula relative error: {float(np.median(q_errors)) if q_errors else float('nan'):.9f}", "",
            "## System and reliability", "",
            f"- CPU mean/peak: {float(np.mean(cpu_samples)) if cpu_samples else 0.0:.2f}% / {max(cpu_samples, default=0.0):.2f}%",
            f"- Memory mean/peak: {float(np.mean(memory_samples)) if memory_samples else 0.0:.2f}% / {max(memory_samples, default=0.0):.2f}%",
            f"- Temperature before: `{json.dumps(temperature_before, ensure_ascii=False)}`",
            f"- Temperature after: `{json.dumps(temperature_after, ensure_ascii=False)}`",
            f"- Read failures: {capture.read_failures}",
            f"- Repeated frames: {capture.repeated_frames}",
            f"- Intervals over 100 ms: {capture.stalls_over_100ms}",
            f"- P95 capture interval: {capture_p95_interval_ms:.3f} ms",
            f"- New USB/kernel error count: {len(usb_errors)}",
            f"- Camera released: {capture.released}",
            f"- Runtime exception: `{failure!r}`" if failure else "- Runtime exception: none",
        ]
        lines.extend(f"  - `{line}`" for line in usb_errors)
        args.report_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
        print("\n".join(lines))
        print(
            json.dumps(
                {
                    "device": device,
                    "capture_frames": capture.capture_count,
                    "processed_depth_frames": processed,
                    "read_failures": capture.read_failures,
                    "capture_fps": capture.capture_count / elapsed if elapsed else 0.0,
                    "depth_fps": processed / elapsed if elapsed else 0.0,
                    "temporal_rejected": temporal.rejected,
                    "wls_available": processor.ximgproc_available,
                    "cpu_baseline": True,
                    "camera_released": capture.released,
                    "status": status,
                    "report": str(args.report_path),
                },
                indent=2,
            )
        )
    if failure is not None:
        raise failure
    return 0 if passed else 2


if __name__ == "__main__":
    raise SystemExit(main())
