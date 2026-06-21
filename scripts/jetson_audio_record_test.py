from __future__ import annotations

import argparse
import json
import shutil
import sys
from datetime import datetime
from pathlib import Path

from jetson_audio_common import (
    PACKAGE_ROOT,
    REPORT_DIR,
    TARGET_PID,
    TARGET_VID,
    analyze_pcm,
    card_usb_identity,
    discover_target_usb_devices,
    load_probe_state,
    parse_arecord_overruns,
    read_wav,
    resample_to_16k,
    run_command,
    sha256_file,
)


PROMPT = ("开始测距", "停止测距", "保存画面", "显示深度", "退出程序")


def target_is_still_connected() -> bool:
    return any(
        item.get("vid") == TARGET_VID and item.get("pid") == TARGET_PID
        for item in discover_target_usb_devices()
    )


def main() -> int:
    parser = argparse.ArgumentParser(description="Record the confirmed USB camera microphone with ALSA")
    parser.add_argument("--duration", type=int, default=10)
    parser.add_argument("--probe-state", type=Path, default=REPORT_DIR / "jetson_audio_probe.json")
    parser.add_argument("--output-dir", type=Path, default=PACKAGE_ROOT / "outputs" / "audio")
    parser.add_argument("--force-numpy-resampler", action="store_true")
    args = parser.parse_args()
    if shutil.which("arecord") is None:
        print("AUDIO_RECORD_FAIL: arecord is unavailable; no package will be installed", file=sys.stderr)
        return 3
    state = load_probe_state(args.probe_state)
    target = state["target"]
    if not target_is_still_connected():
        print("AUDIO_RECORD_FAIL: target USB microphone 1BCF:2D4F disconnected", file=sys.stderr)
        return 4
    current_card_usb = card_usb_identity(int(target["card"]))
    if current_card_usb.get("vid") != TARGET_VID or current_card_usb.get("pid") != TARGET_PID:
        print("AUDIO_RECORD_FAIL: ALSA card mapping changed; rerun audio probe", file=sys.stderr)
        return 4
    output_dir = args.output_dir.resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    native_path = output_dir / "mic_native.wav"
    normalized_path = output_dir / "mic_16k_mono.wav"
    metadata_path = output_dir / "mic_record_metadata.json"
    temporary_path = output_dir / ".mic_native.partial.wav"
    temporary_path.unlink(missing_ok=True)
    rate = int(target["selected_sample_rate"])
    channels = int(target["selected_channels"])
    sample_format = str(target["selected_format"])
    print("请朗读以下短句，每句之间停顿约 1 秒：")
    print(" / ".join(PROMPT))
    command = [
        "arecord", "-D", str(target["alsa_hw"]), "-f", sample_format,
        "-r", str(rate), "-c", str(channels), "-d", str(args.duration),
        "-t", "wav", str(temporary_path),
    ]
    result = run_command(command, timeout=args.duration + 20)
    if result.returncode != 0 or not temporary_path.is_file():
        temporary_path.unlink(missing_ok=True)
        print(f"AUDIO_RECORD_FAIL: arecord exit={result.returncode}: {result.combined}", file=sys.stderr)
        return 5
    temporary_path.replace(native_path)
    samples, actual_rate, actual_channels, bit_depth = read_wav(native_path)
    if actual_rate != rate or actual_channels != channels or bit_depth != 16:
        print(
            f"AUDIO_RECORD_FAIL: WAV header mismatch: {actual_rate} Hz, "
            f"{actual_channels} channels, {bit_depth}-bit",
            file=sys.stderr,
        )
        return 6
    method = resample_to_16k(native_path, normalized_path, args.force_numpy_resampler)
    normalized_samples, normalized_rate, normalized_channels, normalized_bits = read_wav(normalized_path)
    metrics = analyze_pcm(samples, actual_rate)
    overruns = parse_arecord_overruns(result.combined)
    metadata = {
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "target_vid": TARGET_VID,
        "target_pid": TARGET_PID,
        "alsa_device": target["alsa_hw"],
        "alsa_plugin_device": target["alsa_plughw"],
        "usb_bus_path": target["usb"]["usb_bus_path"],
        "requested_duration_seconds": args.duration,
        "native_sample_rate": actual_rate,
        "native_channels": actual_channels,
        "native_bit_depth": bit_depth,
        "native_sample_format": sample_format,
        "native_wav_header_valid": True,
        "native_wav_sha256": sha256_file(native_path),
        "output_sample_rate": normalized_rate,
        "output_channels": normalized_channels,
        "output_bit_depth": normalized_bits,
        "normalized_wav_sha256": sha256_file(normalized_path),
        "resampling_method": method,
        "arecord_returncode": result.returncode,
        "arecord_overrun_count": overruns,
        "spoken_prompt": list(PROMPT),
        **metrics,
    }
    metadata_path.write_text(json.dumps(metadata, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    lines = [
        "# Jetson ALSA Microphone Recording Report",
        "",
        f"- Generated: {metadata['generated_at']}",
        f"- Target: `{TARGET_VID.upper()}:{TARGET_PID.upper()}` at `{metadata['usb_bus_path']}`",
        f"- ALSA hardware device: `{metadata['alsa_device']}`",
        f"- Native WAV: `{native_path.relative_to(PACKAGE_ROOT)}`",
        f"- Native format: {actual_rate} Hz, {actual_channels} channel(s), {bit_depth}-bit PCM",
        f"- Native duration: {metrics['duration_seconds']:.3f} s",
        f"- 16 kHz mono WAV: `{normalized_path.relative_to(PACKAGE_ROOT)}`",
        f"- Resampling method: `{method}`",
        f"- RMS: {metrics['rms']:.6f}",
        f"- Peak: {metrics['peak']:.6f}",
        f"- Clipping ratio: {metrics['clipping_ratio']:.6%}",
        f"- Silence ratio: {metrics['silence_ratio']:.2%}",
        f"- DC offset: {metrics['dc_offset']:.6f}",
        f"- Possible dropout transitions: {metrics['possible_dropout_transitions']}",
        f"- arecord overrun/xrun count: {overruns}",
        "- WAV header valid: True",
        "- Speech content was recorded but not recognized or interpreted.",
    ]
    report_path = REPORT_DIR / "jetson_audio_record_report.md"
    report_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print("\n".join(lines))
    print("JETSON_AUDIO_RECORD: PASS")
    return 0 if overruns == 0 else 2


if __name__ == "__main__":
    raise SystemExit(main())
