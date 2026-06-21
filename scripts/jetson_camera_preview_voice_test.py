from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path
from typing import Any

import cv2
import numpy as np

from jetson_asr_common import DEFAULT_CONFIG_PATH, load_asr_config
from jetson_asr_live_command_test import DEFAULT_REPORT_DIR, LiveAsrSession, local_timestamp


PACKAGE_ROOT = Path(__file__).resolve().parents[1]
CAMERA_PROBE_REPORT = PACKAGE_ROOT / "reports" / "runtime_j2" / "camera_probe.json"


def choose_camera(camera_index: int | None) -> str:
    if camera_index is not None:
        return f"/dev/video{camera_index}"
    if CAMERA_PROBE_REPORT.is_file():
        try:
            payload = json.loads(CAMERA_PROBE_REPORT.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            payload = []
        candidates = [
            item
            for item in payload
            if isinstance(item, dict)
            and item.get("capture_capable") is True
            and item.get("supports_mjpg_2560x720_60") is True
            and isinstance(item.get("device"), str)
        ]
        if len(candidates) == 1:
            return str(candidates[0]["device"])
    return "/dev/video0"


def open_camera(device: str) -> cv2.VideoCapture:
    capture = cv2.VideoCapture(device, cv2.CAP_V4L2)
    capture.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc(*"MJPG"))
    capture.set(cv2.CAP_PROP_FRAME_WIDTH, 2560.0)
    capture.set(cv2.CAP_PROP_FRAME_HEIGHT, 720.0)
    capture.set(cv2.CAP_PROP_FPS, 60.0)
    return capture


def fit_preview(
    frame: Any,
    window_width: int,
    window_height: int,
    fit_window: bool,
) -> tuple[Any, tuple[int, int, int, int]]:
    source_height, source_width = frame.shape[:2]
    if not fit_window:
        return frame.copy(), (0, 0, source_width, source_height)
    scale = min(window_width / source_width, window_height / source_height)
    display_width = max(1, int(round(source_width * scale)))
    display_height = max(1, int(round(source_height * scale)))
    interpolation = cv2.INTER_AREA if scale < 1.0 else cv2.INTER_LINEAR
    resized = cv2.resize(frame, (display_width, display_height), interpolation=interpolation)
    canvas = np.zeros((window_height, window_width, 3), dtype=frame.dtype)
    offset_x = (window_width - display_width) // 2
    offset_y = (window_height - display_height) // 2
    canvas[offset_y:offset_y + display_height, offset_x:offset_x + display_width] = resized
    return canvas, (offset_x, offset_y, display_width, display_height)


def truncate_overlay_line(line: str, font_scale: float, maximum_width: int) -> str:
    safe_line = line.encode("ascii", errors="backslashreplace").decode("ascii")
    if cv2.getTextSize(safe_line, cv2.FONT_HERSHEY_SIMPLEX, font_scale, 1)[0][0] <= maximum_width:
        return safe_line
    while safe_line and cv2.getTextSize(
        safe_line + "...", cv2.FONT_HERSHEY_SIMPLEX, font_scale, 1
    )[0][0] > maximum_width:
        safe_line = safe_line[:-1]
    return safe_line + "..."


def overlay_text(
    frame: Any,
    lines: list[str],
    font_scale: float,
    content_rect: tuple[int, int, int, int],
) -> Any:
    left, top, width, height = content_rect
    margin = max(6, int(round(12 * font_scale / 0.6)))
    line_step = max(18, int(round(34 * font_scale)))
    x = left + margin
    y = top + margin + line_step
    maximum_width = max(20, width - margin * 2)
    maximum_y = top + height - margin
    for line in lines:
        if y > maximum_y:
            break
        safe_line = truncate_overlay_line(line, font_scale, maximum_width)
        (text_width, text_height), baseline = cv2.getTextSize(
            safe_line, cv2.FONT_HERSHEY_SIMPLEX, font_scale, 1
        )
        cv2.rectangle(
            frame,
            (x - 3, max(top, y - text_height - 3)),
            (min(left + width - 1, x + text_width + 3), min(maximum_y, y + baseline + 3)),
            (0, 0, 0),
            cv2.FILLED,
        )
        cv2.putText(
            frame, safe_line, (x, y), cv2.FONT_HERSHEY_SIMPLEX,
            font_scale, (0, 255, 0), 1, cv2.LINE_AA,
        )
        y += line_step
    return frame


def destroy_windows_safely() -> None:
    try:
        cv2.destroyAllWindows()
    except cv2.error:
        pass


def write_combined_reports(result: dict[str, Any], report_dir: Path) -> None:
    report_dir.mkdir(parents=True, exist_ok=True)
    json_path = report_dir / "jetson_camera_preview_voice.json"
    markdown_path = report_dir / "jetson_camera_preview_voice_report.md"
    json_path.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    lines = [
        "# Jetson J3-B Camera Preview and Live Voice Report",
        "",
        f"- Status: **{result['status']}**",
        f"- Start: {result['start_time']}",
        f"- End: {result['end_time']}",
        f"- Duration: {result['duration_seconds']:.3f} s",
        f"- Camera device: `{result['camera_device']}`",
        f"- Camera opened: {result['camera_opened']}",
        f"- Display requested/active: {result['display_requested']}/{result['display_active']}",
        f"- Window size: {result['window_width']}x{result['window_height']}",
        f"- Fit window: {result['fit_window']}",
        f"- Overlay scale: {result['overlay_scale']}",
        f"- Left view only: {result['left_view_only']}",
        f"- Displayed frame: {result['displayed_frame_width']}x{result['displayed_frame_height']}",
        f"- Camera frames: {result['camera_frames']}",
        f"- Camera average FPS: {result['camera_fps_avg']:.3f}",
        f"- ASR events: {result['asr_events']}",
        f"- Command events: {result['command_events']}",
        f"- Unknown count: {result['unknown_count']}",
        f"- Errors: {len(result['errors'])}",
        "",
        "The camera is preview-only. No SGBM, WLS, depth calculation, network speech "
        "service, or hardware control is used.",
    ]
    if result["errors"]:
        lines.extend(["", "## Errors", "", *[f"- {item}" for item in result["errors"]]])
    markdown_path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description="Jetson J3-B camera preview plus live voice test")
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG_PATH)
    parser.add_argument("--audio-device", default="plughw:0,0")
    parser.add_argument("--camera-index", type=int)
    parser.add_argument("--duration", type=float, default=60.0)
    parser.add_argument("--command-cooldown-ms", type=int, default=800)
    display_group = parser.add_mutually_exclusive_group()
    display_group.add_argument("--display-window", dest="display_window", action="store_true")
    display_group.add_argument("--no-window", dest="display_window", action="store_false")
    parser.set_defaults(display_window=True)
    parser.add_argument("--window-width", type=int, default=960)
    parser.add_argument("--window-height", type=int, default=540)
    fit_group = parser.add_mutually_exclusive_group()
    fit_group.add_argument("--fit-window", dest="fit_window", action="store_true")
    fit_group.add_argument("--no-fit-window", dest="fit_window", action="store_false")
    parser.set_defaults(fit_window=True)
    parser.add_argument("--overlay-scale", type=float, default=0.6)
    parser.add_argument("--left-view-only", action="store_true")
    parser.add_argument("--report-dir", type=Path, default=DEFAULT_REPORT_DIR)
    args = parser.parse_args()
    if args.duration <= 0:
        raise RuntimeError("--duration must be positive")
    if args.window_width <= 0 or args.window_height <= 0:
        raise RuntimeError("--window-width and --window-height must be positive")
    if args.overlay_scale <= 0:
        raise RuntimeError("--overlay-scale must be positive")

    start_time = local_timestamp()
    started = time.monotonic()
    errors: list[str] = []
    config = load_asr_config(args.config)
    asr = LiveAsrSession(config, args.audio_device, args.command_cooldown_ms)
    asr.start()

    camera_device = choose_camera(args.camera_index)
    display_active = bool(args.display_window)
    if display_active and not (os.environ.get("DISPLAY") or os.environ.get("WAYLAND_DISPLAY")):
        message = "No DISPLAY or WAYLAND_DISPLAY is available; continuing in --no-window mode"
        print(f"DISPLAY_WARNING: {message}", file=sys.stderr)
        errors.append(message)
        display_active = False

    capture: cv2.VideoCapture | None = None
    camera_opened = False
    camera_frames = 0
    camera_started = 0.0
    displayed_frame_width = 0
    displayed_frame_height = 0
    try:
        try:
            capture = open_camera(camera_device)
            camera_opened = capture.isOpened()
        except Exception as exc:
            message = f"Camera open raised {type(exc).__name__}: {exc}; ASR will continue"
            print(f"CAMERA_ERROR: {message}", file=sys.stderr)
            errors.append(message)
            capture = None
            camera_opened = False
        if not camera_opened:
            message = f"Camera could not be opened: {camera_device}; ASR will continue"
            print(f"CAMERA_ERROR: {message}", file=sys.stderr)
            errors.append(message)
        else:
            camera_started = time.monotonic()
        if display_active:
            try:
                cv2.namedWindow("Jetson J3-B Live Voice Preview", cv2.WINDOW_NORMAL)
                cv2.resizeWindow(
                    "Jetson J3-B Live Voice Preview", args.window_width, args.window_height
                )
            except cv2.error as exc:
                message = f"OpenCV window initialization failed; continuing headless: {exc}"
                print(f"DISPLAY_ERROR: {message}", file=sys.stderr)
                errors.append(message)
                display_active = False
        deadline = started + args.duration
        while time.monotonic() < deadline:
            state = asr.snapshot()
            if state["exit_requested"]:
                break
            if camera_opened and capture is not None:
                ok, frame = capture.read()
                if not ok:
                    message = "Camera frame read failed; ASR will continue"
                    print(f"CAMERA_ERROR: {message}", file=sys.stderr)
                    errors.append(message)
                    camera_opened = False
                    capture.release()
                    capture = None
                    continue
                camera_frames += 1
                elapsed_camera = max(time.monotonic() - camera_started, 1e-9)
                fps = camera_frames / elapsed_camera
                if display_active:
                    display_source = frame[:, :frame.shape[1] // 2] if args.left_view_only else frame
                    preview, content_rect = fit_preview(
                        display_source, args.window_width, args.window_height, args.fit_window
                    )
                    displayed_frame_height, displayed_frame_width = preview.shape[:2]
                    event_lines = []
                    for event in state["asr_history"][-3:]:
                        event_label = event["command_id"] or "unknown"
                        event_lines.append(f"event: {event_label} | {event['recognized_text']}")
                    preview = overlay_text(
                        preview,
                        [
                            f"FPS: {fps:.2f}",
                            f"recognized_text: {state['latest_recognized_text'] or '--'}",
                            f"command_id: {state['latest_command_id'] or '--'}",
                            f"unknown: {state['latest_unknown']}",
                            f"runtime: {time.monotonic() - started:.1f}s",
                            *event_lines,
                        ],
                        args.overlay_scale,
                        content_rect,
                    )
                    try:
                        cv2.imshow("Jetson J3-B Live Voice Preview", preview)
                        if cv2.waitKey(1) & 0xFF == ord("q"):
                            break
                    except cv2.error as exc:
                        message = f"OpenCV display failed; continuing headless: {exc}"
                        print(f"DISPLAY_ERROR: {message}", file=sys.stderr)
                        errors.append(message)
                        display_active = False
                        destroy_windows_safely()
            else:
                if asr.finished:
                    break
                time.sleep(0.02)
    except KeyboardInterrupt:
        print("Ctrl+C received; stopping preview and ASR", file=sys.stderr)
    finally:
        if capture is not None:
            capture.release()
        if display_active:
            destroy_windows_safely()
        asr.stop()

    elapsed = max(time.monotonic() - started, 0.0)
    state = asr.snapshot()
    errors.extend(state["errors"])
    subsystem_success = camera_frames > 0 or state["asr_events"] > 0 or state["audio_bytes"] > 0
    status = "PASS" if not errors else ("PARTIAL" if subsystem_success else "FAIL")
    result = {
        "status": status,
        "start_time": start_time,
        "end_time": local_timestamp(),
        "duration_seconds": elapsed,
        "camera_device": camera_device,
        "camera_opened": camera_frames > 0,
        "camera_frames": camera_frames,
        "camera_fps_avg": camera_frames / elapsed if elapsed > 0 else 0.0,
        "display_requested": bool(args.display_window),
        "display_active": display_active,
        "window_width": args.window_width,
        "window_height": args.window_height,
        "fit_window": args.fit_window,
        "overlay_scale": args.overlay_scale,
        "left_view_only": args.left_view_only,
        "displayed_frame_width": displayed_frame_width,
        "displayed_frame_height": displayed_frame_height,
        "audio_device": args.audio_device,
        "asr_events": state["asr_events"],
        "command_events": state["command_events"],
        "unknown_count": state["unknown_count"],
        "latest_recognized_text": state["latest_recognized_text"],
        "latest_command_id": state["latest_command_id"],
        "latest_unknown": state["latest_unknown"],
        "command_history": state["command_history"],
        "errors": errors,
    }
    write_combined_reports(result, args.report_dir.resolve())
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if status in {"PASS", "PARTIAL"} else 1


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except RuntimeError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        raise SystemExit(2) from None
