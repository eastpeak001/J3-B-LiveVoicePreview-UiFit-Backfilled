from __future__ import annotations

import argparse
import getpass
import json
import os
import shutil
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

from jetson_audio_common import (
    REPORT_DIR,
    TARGET_PID,
    TARGET_VID,
    card_usb_identity,
    choose_native_format,
    command_section,
    discover_target_usb_devices,
    is_target_alsa_device,
    parse_arecord_devices,
    parse_hw_params,
    recommended_alsa_strings,
    run_command,
)


def fail_simulation(message: str, code: int) -> int:
    print(f"AUDIO_PROBE_FAIL: {message}", file=sys.stderr)
    return code


def collect_probe() -> tuple[dict[str, Any], str]:
    raw_sections = []
    commands = [
        ["lsusb"],
        ["arecord", "-l"],
        ["arecord", "-L"],
        ["id", "-nG"],
        ["amixer"],
    ]
    if shutil.which("pactl"):
        commands.append(["pactl", "list", "sources", "short"])
    if shutil.which("systemctl"):
        commands.extend([
            ["systemctl", "--user", "is-active", "pipewire"],
            ["systemctl", "--user", "is-active", "pulseaudio"],
        ])
    results = {}
    for command in commands:
        result = run_command(command)
        results[" ".join(command)] = result
        raw_sections.append(command_section(result))

    proc_root = Path(os.environ.get("JETSON_AUDIO_PROC_ASOUND_ROOT", "/proc/asound"))
    for name in ("cards", "pcm"):
        path = proc_root / name
        text = path.read_text(encoding="utf-8", errors="replace") if path.is_file() else "unavailable"
        raw_sections.append(f"$ cat {path}\n{text}\n")

    usb_devices = discover_target_usb_devices()
    arecord_list = results.get("arecord -l")
    alsa_devices = parse_arecord_devices(arecord_list.combined if arecord_list else "")
    targets = [record for record in alsa_devices if is_target_alsa_device(record)]
    target = targets[0] if len(targets) == 1 else None
    capabilities: dict[str, Any] = {}
    capability_result = None
    if target:
        hardware, plug = recommended_alsa_strings(target)
        target.update({
            "vid": TARGET_VID,
            "pid": TARGET_PID,
            "alsa_hw": hardware,
            "alsa_plughw": plug,
        })
        capability_result = run_command([
            "arecord", "--dump-hw-params", "-D", hardware, "-d", "1", "-t", "raw", "/dev/null"
        ], timeout=10)
        raw_sections.append(command_section(capability_result))
        capabilities = parse_hw_params(capability_result.combined)
        try:
            rate, channels, sample_format = choose_native_format(capabilities)
            target.update({
                "selected_sample_rate": rate,
                "selected_channels": channels,
                "selected_format": sample_format,
            })
        except RuntimeError as exc:
            target["format_error"] = str(exc)

        card_number = int(target["card"])
        amixer_result = run_command(["amixer", "-c", str(card_number), "contents"])
        raw_sections.append(command_section(amixer_result))

    groups_text = results.get("id -nG").combined if results.get("id -nG") else ""
    state = {
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "user": getpass.getuser(),
        "user_groups": groups_text.split(),
        "user_in_audio_group": "audio" in groups_text.split(),
        "target_vid": TARGET_VID,
        "target_pid": TARGET_PID,
        "target_usb_devices": usb_devices,
        "alsa_capture_devices": alsa_devices,
        "target_candidate_count": len(targets),
        "target_found": target is not None and "format_error" not in target,
        "target": target,
        "capabilities": capabilities,
        "arecord_available": shutil.which("arecord") is not None,
        "pactl_available": shutil.which("pactl") is not None,
        "pipewire_status": results.get("systemctl --user is-active pipewire").combined
        if results.get("systemctl --user is-active pipewire") else "not queried",
        "pulseaudio_status": results.get("systemctl --user is-active pulseaudio").combined
        if results.get("systemctl --user is-active pulseaudio") else "not queried",
    }
    return state, "\n".join(raw_sections)


def write_reports(state: dict[str, Any], raw: str, report_dir: Path) -> None:
    report_dir.mkdir(parents=True, exist_ok=True)
    (report_dir / "jetson_audio_probe_raw.txt").write_text(raw + "\n", encoding="utf-8")
    (report_dir / "jetson_audio_probe.json").write_text(
        json.dumps(state, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    target = state.get("target")
    lines = [
        "# Jetson USB Audio Probe Report",
        "",
        f"- Generated: {state['generated_at']}",
        f"- User: `{state['user']}`",
        f"- User groups: `{', '.join(state['user_groups']) or '--'}`",
        f"- User belongs to `audio`: {state['user_in_audio_group']}",
        f"- `arecord` available: {state['arecord_available']}",
        f"- `pactl` available: {state['pactl_available']}",
        f"- PipeWire: `{state['pipewire_status']}`",
        f"- PulseAudio: `{state['pulseaudio_status']}`",
        "",
        "## Target identity",
        "",
        "- Required VID:PID: `1BCF:2D4F`.",
        f"- Matching USB functions: {len(state['target_usb_devices'])}",
        f"- Matching ALSA capture candidates with exact sysfs VID/PID: {state['target_candidate_count']}",
        "- A name match alone is never accepted as authorization to record.",
        "",
        "## ALSA capture devices",
        "",
        "| Card | Card ID | Card name | Device | Device name | VID:PID | USB path |",
        "|---:|---|---|---:|---|---|---|",
    ]
    for item in state["alsa_capture_devices"]:
        usb = item.get("usb") or {}
        lines.append(
            f"| {item['card']} | `{item['card_id']}` | {item['card_name']} | {item['device']} | "
            f"{item['device_name']} | {usb.get('vid') or '--'}:{usb.get('pid') or '--'} | "
            f"`{usb.get('usb_bus_path') or '--'}` |"
        )
    lines.extend(["", "## Recommendation", ""])
    if state["target_found"] and target:
        lines.extend([
            f"- Hardware capture device: `{target['alsa_hw']}`",
            f"- Plugin device for compatibility: `{target['alsa_plughw']}`",
            f"- Selected native test format: `{target['selected_format']}`, "
            f"{target['selected_sample_rate']} Hz, {target['selected_channels']} channel(s).",
            f"- USB bus path: `{target['usb']['usb_bus_path']}`",
            "- Result: target USB microphone uniquely confirmed; recording tests may proceed.",
        ])
    elif state["target_candidate_count"] > 1:
        lines.append("- Result: multiple exact target candidates; stop and resolve the physical USB topology manually.")
    elif target and target.get("format_error"):
        lines.append(f"- Result: target found but no accepted native format: `{target['format_error']}`")
    else:
        lines.append("- Result: target USB microphone not confirmed. Stop; do not use another microphone.")
    (report_dir / "jetson_audio_probe_report.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description="Read-only Jetson ALSA/USB microphone probe")
    parser.add_argument("--report-dir", type=Path, default=REPORT_DIR)
    parser.add_argument("--simulate-missing-arecord", action="store_true")
    parser.add_argument("--simulate-no-target", action="store_true")
    args = parser.parse_args()
    if args.simulate_missing_arecord:
        return fail_simulation("arecord is unavailable; no audio device will be selected", 3)
    if args.simulate_no_target:
        return fail_simulation("target USB microphone 1BCF:2D4F is absent; refusing fallback", 4)
    if shutil.which("arecord") is None:
        return fail_simulation("arecord is not installed; stop without installing packages", 3)
    state, raw = collect_probe()
    write_reports(state, raw, args.report_dir)
    if state["target_found"]:
        target = state["target"]
        print(f"RECOMMENDED_ALSA_DEVICE={target['alsa_plughw']}")
        print("JETSON_AUDIO_PROBE: PASS")
        return 0
    print("JETSON_AUDIO_PROBE: FAIL - target microphone was not uniquely confirmed", file=sys.stderr)
    return 4


if __name__ == "__main__":
    raise SystemExit(main())
