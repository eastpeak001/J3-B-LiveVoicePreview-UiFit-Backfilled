from __future__ import annotations

import argparse
import hashlib
import json
import re
import shutil
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

import cv2
import numpy as np
import psutil
import yaml

from jetson_audio_common import (
    PACKAGE_ROOT,
    REPORT_DIR,
    TARGET_PID,
    TARGET_VID,
    analyze_pcm,
    card_usb_identity,
    discover_target_usb_devices,
    kernel_usb_errors,
    load_probe_state,
    parse_arecord_overruns,
    read_wav,
    resample_to_16k,
    run_command,
    thermal_snapshot,
)
from jetson_camera_probe import enumerate_devices, select_recommended


CAMERA_PROBE_STATE = REPORT_DIR / "camera_probe.json"
CAMERA_SELECTION_SOURCE = "live_probe"


def recommended_from_probe_state(path: Path = CAMERA_PROBE_STATE) -> str | None:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, UnicodeError):
        return None

    if not isinstance(payload, list):
        return None

    candidates: list[str] = []
    for record in payload:
        if not isinstance(record, dict):
            continue
        device = record.get("device")
        vid = record.get("vid")
        pid = record.get("pid")
        if (
            isinstance(device, str)
            and Path(device).exists()
            and record.get("capture_capable") is True
            and record.get("supports_mjpg_2560x720_60") is True
            and isinstance(vid, str)
            and vid.lower() == "1bcf"
            and isinstance(pid, str)
            and pid.lower() == "2d4f"
        ):
            candidates.append(device)

    if len(candidates) > 1:
        raise RuntimeError(
            "Multiple camera_probe.json devices match MJPG 2560x720 at 60 FPS "
            f"for 1BCF:2D4F: {', '.join(candidates)}"
        )
    if not candidates:
        return None
    return candidates[0]


def choose_camera(requested: str) -> str:
    global CAMERA_SELECTION_SOURCE
    if requested != "auto":
        CAMERA_SELECTION_SOURCE = "requested"
        return requested
    probed_device = recommended_from_probe_state()
    if probed_device:
        CAMERA_SELECTION_SOURCE = "camera_probe.json"
        return probed_device
    CAMERA_SELECTION_SOURCE = "live_probe"
    records, _ = enumerate_devices()
    recommended = select_recommended(records)
    if not recommended:
        raise RuntimeError("No unique V4L2 node advertises MJPG 2560x720 at 60 FPS")
    return str(recommended["device"])


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


def frame_digest(frame: np.ndarray) -> bytes:
    small = cv2.resize(frame, (160, 45), interpolation=cv2.INTER_AREA)
    return hashlib.sha256(small.tobytes()).digest()


def target_connected() -> bool:
    return any(
        item.get("vid") == TARGET_VID and item.get("pid") == TARGET_PID
        for item in discover_target_usb_devices()
    )


def main() -> int:
    parser = argparse.ArgumentParser(description="Jetson V4L2 plus ALSA 60-second concurrent test")
    parser.add_argument("--device", default="auto")
    parser.add_argument("--duration", type=int, default=60)
    parser.add_argument("--probe-state", type=Path, default=REPORT_DIR / "jetson_audio_probe.json")
    parser.add_argument("--config", type=Path, default=PACKAGE_ROOT / "config" / "depth_runtime_jetson.yaml")
    parser.add_argument("--force-numpy-resampler", action="store_true")
    args = parser.parse_args()
    if shutil.which("arecord") is None:
        print("CONCURRENT_FAIL: arecord is unavailable; stop without installing packages", file=sys.stderr)
        return 3
    state = load_probe_state(args.probe_state)
    target = state["target"]
    if not target_connected():
        print("CONCURRENT_FAIL: target USB device 1BCF:2D4F is disconnected", file=sys.stderr)
        return 4
    current_card_usb = card_usb_identity(int(target["card"]))
    if current_card_usb.get("vid") != TARGET_VID or current_card_usb.get("pid") != TARGET_PID:
        print("CONCURRENT_FAIL: ALSA card mapping changed; rerun audio probe", file=sys.stderr)
        return 4
    config = yaml.safe_load(args.config.resolve().read_text(encoding="utf-8"))
    camera_config = config["camera"]
    device = choose_camera(args.device)
    width = int(camera_config["width"])
    height = int(camera_config["height"])
    fps = float(camera_config["fps"])
    fourcc = str(camera_config["fourcc"])
    cap = None
    try:
        force_v4l2_mode(device, width, height, fps, fourcc)
        cap = open_capture(device, width, height, fps, fourcc)
        v4l2_fps = get_v4l2_fps(device)
    except (OSError, subprocess.CalledProcessError, RuntimeError) as exc:
        if cap is not None:
            cap.release()
        print(f"CONCURRENT_FAIL: camera setup failed for {device}: {exc}", file=sys.stderr)
        return 5
    actual = {
        "width": int(cap.get(cv2.CAP_PROP_FRAME_WIDTH)),
        "height": int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT)),
        "fourcc": fourcc_text(cap.get(cv2.CAP_PROP_FOURCC)),
    }
    opencv_fps = float(cap.get(cv2.CAP_PROP_FPS))
    if (actual["width"], actual["height"]) != (2560, 720) or actual["fourcc"].upper() != "MJPG":
        cap.release()
        print(f"CONCURRENT_FAIL: camera negotiated unexpected mode {actual}", file=sys.stderr)
        return 6
    warmup_target = int(camera_config.get("warmup_frames", 120))
    warmed = warmup_failures = attempts = 0
    last_warm_frame = None
    while warmed < warmup_target and attempts < warmup_target * 5:
        attempts += 1
        ok, frame = cap.read()
        if ok and frame is not None and frame.shape[:2] == (720, 2560):
            warmed += 1
            last_warm_frame = frame
        else:
            warmup_failures += 1
    if warmed < warmup_target or last_warm_frame is None:
        cap.release()
        print(f"CONCURRENT_FAIL: camera warmup reached only {warmed}/{warmup_target} frames", file=sys.stderr)
        return 7

    output_dir = PACKAGE_ROOT / "outputs" / "concurrent"
    output_dir.mkdir(parents=True, exist_ok=True)
    native_path = output_dir / "audio_native.wav"
    normalized_path = output_dir / "audio_16k_mono.wav"
    partial_path = output_dir / ".audio_native.partial.wav"
    partial_path.unlink(missing_ok=True)
    rate = int(target["selected_sample_rate"])
    channels = int(target["selected_channels"])
    audio_command = [
        "arecord", "-D", str(target["alsa_hw"]), "-f", str(target["selected_format"]),
        "-r", str(rate), "-c", str(channels), "-d", str(args.duration), "-t", "wav", str(partial_path),
    ]
    kernel_before = run_command(["dmesg"], timeout=10).combined if shutil.which("dmesg") else ""
    temperature_before = thermal_snapshot()
    audio_process = subprocess.Popen(audio_command, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    frame_count = failures = repeated = stalls = max_consecutive_failures = consecutive_failures = 0
    intervals: list[float] = []
    cpu_samples: list[float] = []
    memory_samples: list[float] = []
    previous_digest = None
    saved_frame = None
    released = False
    psutil.cpu_percent(interval=None)
    started = previous_time = time.perf_counter()
    next_system_sample = started
    try:
        while time.perf_counter() - started < args.duration:
            ok, frame = cap.read()
            now = time.perf_counter()
            if not ok or frame is None:
                failures += 1
                consecutive_failures += 1
                max_consecutive_failures = max(max_consecutive_failures, consecutive_failures)
                continue
            consecutive_failures = 0
            interval = now - previous_time
            previous_time = now
            intervals.append(interval)
            stalls += int(interval > 0.100)
            digest = frame_digest(frame)
            repeated += int(digest == previous_digest)
            previous_digest = digest
            frame_count += 1
            if saved_frame is None:
                saved_frame = frame.copy()
            if now >= next_system_sample:
                cpu_samples.append(psutil.cpu_percent(interval=None))
                memory_samples.append(psutil.virtual_memory().percent)
                next_system_sample = now + 1.0
    finally:
        cap.release()
        released = not cap.isOpened()
    elapsed = time.perf_counter() - started
    try:
        audio_stdout, audio_stderr = audio_process.communicate(timeout=20)
    except subprocess.TimeoutExpired:
        audio_process.terminate()
        audio_stdout, audio_stderr = audio_process.communicate(timeout=5)
    audio_log = "\n".join(part for part in (audio_stdout.strip(), audio_stderr.strip()) if part)
    if audio_process.returncode != 0 or not partial_path.is_file():
        print(f"CONCURRENT_FAIL: arecord exit={audio_process.returncode}: {audio_log}", file=sys.stderr)
        return 8
    partial_path.replace(native_path)
    if saved_frame is None or saved_frame.shape[:2] != (720, 2560):
        print("CONCURRENT_FAIL: no valid full SBS frame was retained", file=sys.stderr)
        return 9
    physical_left = saved_frame[:, :1280]
    physical_right = saved_frame[:, 1280:]
    cv2.imwrite(str(output_dir / "raw_sbs.png"), saved_frame)
    cv2.imwrite(str(output_dir / "physical_left.png"), physical_left)
    cv2.imwrite(str(output_dir / "physical_right.png"), physical_right)
    samples, actual_rate, actual_channels, bit_depth = read_wav(native_path)
    metrics = analyze_pcm(samples, actual_rate)
    resampling_method = resample_to_16k(native_path, normalized_path, args.force_numpy_resampler)
    overruns = parse_arecord_overruns(audio_log)
    kernel_after = run_command(["dmesg"], timeout=10).combined if shutil.which("dmesg") else ""
    new_kernel_text = kernel_after[len(kernel_before):] if kernel_after.startswith(kernel_before) else kernel_after
    usb_errors = kernel_usb_errors(new_kernel_text)
    usb_present_after = target_connected()
    temperature_after = thermal_snapshot()
    p95_ms = float(np.percentile(np.asarray(intervals), 95) * 1000.0) if intervals else float("nan")
    lines = [
        "# Jetson Camera and USB Microphone Concurrent Report",
        "",
        f"- Generated: {datetime.now().isoformat(timespec='seconds')}",
        f"- Duration: {elapsed:.3f} s",
        "",
        "## Video",
        "",
        f"- Selected camera device: `{device}`",
        f"- Camera selected from: {CAMERA_SELECTION_SOURCE}",
        f"- Warmup frames discarded: {warmed}",
        f"- Warmup failures: {warmup_failures}",
        f"- Negotiated mode: `{actual}`",
        f"- OpenCV reported FPS: {opencv_fps:.3f}",
        f"- V4L2 reported FPS: {v4l2_fps:.3f}",
        f"- Frames: {frame_count}",
        f"- Measured video FPS: {frame_count / elapsed:.3f}",
        f"- Average FPS: {frame_count / elapsed:.3f}",
        f"- P95 frame interval: {p95_ms:.3f} ms",
        f"- Read failures: {failures}",
        f"- Repeated frames: {repeated}",
        f"- Intervals over 100 ms: {stalls}",
        f"- Maximum consecutive failures: {max_consecutive_failures}",
        "- Raw left half: physical left camera; raw right half: physical right camera; no swap.",
        f"- Camera released: {released}",
        "",
        "## Audio",
        "",
        f"- Target VID:PID: `{TARGET_VID.upper()}:{TARGET_PID.upper()}`",
        f"- ALSA device: `{target['alsa_hw']}`",
        f"- Native format: {actual_rate} Hz, {actual_channels} channel(s), {bit_depth}-bit PCM",
        f"- Duration: {metrics['duration_seconds']:.3f} s",
        f"- Audio frames: {metrics['audio_frame_count']}",
        f"- arecord overrun/xrun count: {overruns}",
        f"- Dropped blocks proxy (overruns): {overruns}",
        f"- Possible dropout transitions: {metrics['possible_dropout_transitions']}",
        f"- RMS: {metrics['rms']:.6f}",
        f"- Peak: {metrics['peak']:.6f}",
        f"- Clipping ratio: {metrics['clipping_ratio']:.6%}",
        f"- 16 kHz mono resampling: `{resampling_method}`",
        "- ALSA capture process exited and file handles closed: True",
        "",
        "## System and USB",
        "",
        f"- Mean CPU: {float(np.mean(cpu_samples)) if cpu_samples else 0.0:.2f}%",
        f"- Peak CPU: {max(cpu_samples, default=0.0):.2f}%",
        f"- Mean memory use: {float(np.mean(memory_samples)) if memory_samples else 0.0:.2f}%",
        f"- Peak memory use: {max(memory_samples, default=0.0):.2f}%",
        f"- Temperature before: `{json.dumps(temperature_before, ensure_ascii=False)}`",
        f"- Temperature after: `{json.dumps(temperature_after, ensure_ascii=False)}`",
        f"- Target USB present after test: {usb_present_after}",
        f"- New kernel USB errors: {len(usb_errors)}",
    ]
    lines.extend(f"  - `{line}`" for line in usb_errors)
    report = REPORT_DIR / "jetson_camera_audio_concurrent_report.md"
    report.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print("\n".join(lines))
    passed = (
        failures == 0 and overruns == 0 and usb_present_after and not usb_errors
        and released and abs(metrics["duration_seconds"] - args.duration) <= 0.5
    )
    print(f"JETSON_CAMERA_AUDIO_CONCURRENT: {'PASS' if passed else 'REVIEW'}")
    return 0 if passed else 2


if __name__ == "__main__":
    raise SystemExit(main())
