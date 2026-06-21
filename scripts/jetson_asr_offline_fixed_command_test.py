from __future__ import annotations

import argparse
import json
import sys
import tempfile
import time
from dataclasses import replace
from datetime import datetime
from pathlib import Path
from typing import Any

from jetson_asr_common import (
    DEFAULT_CONFIG_PATH,
    DEFAULT_JSON_REPORT,
    DEFAULT_MARKDOWN_REPORT,
    load_asr_config,
    match_fixed_command,
    recognize_vosk_wav,
    wav_properties,
)
from jetson_audio_common import resample_to_16k


def write_reports(result: dict[str, Any], json_path: Path, markdown_path: Path) -> None:
    json_path.parent.mkdir(parents=True, exist_ok=True)
    markdown_path.parent.mkdir(parents=True, exist_ok=True)
    json_path.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    lines = [
        "# Jetson J3-A Offline Fixed Command ASR Report",
        "",
        f"- Generated: {result['generated_at']}",
        f"- Status: **{result['status']}**",
        f"- Input WAV: `{result['input_wav']}`",
        f"- Model path: `{result['model_path']}`",
        f"- Resampling: {result['resample_method']}",
        f"- Recognition mode: `{result['recognition_mode']}`",
        f"- Audio duration: {result['audio_duration_seconds']:.3f} s",
        f"- Processing time: {result['processing_time_ms']:.3f} ms",
        "",
        "## Recognition",
        "",
        f"- Raw recognized text: `{result['recognized_text']}`",
        f"- command_id: `{result['command_id'] or '--'}`",
        f"- phrase: `{result['phrase'] or '--'}`",
        f"- unknown: {result['unknown']}",
        "",
        "This test reads one WAV file and performs fully offline fixed-command matching. "
        "It does not start depth processing, control hardware, or use a network service.",
    ]
    markdown_path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description="Offline Vosk Chinese fixed-command WAV test")
    parser.add_argument("wav", type=Path, help="Input WAV file")
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG_PATH)
    parser.add_argument("--model", type=Path, help="Override the configured local Vosk model directory")
    parser.add_argument(
        "--grammar", action="store_true",
        help="Opt into Vosk grammar mode; open recognition is the default for Chinese commands",
    )
    parser.add_argument("--json-report", type=Path, default=DEFAULT_JSON_REPORT)
    parser.add_argument("--markdown-report", type=Path, default=DEFAULT_MARKDOWN_REPORT)
    args = parser.parse_args()

    input_wav = args.wav.resolve()
    if not input_wav.is_file():
        raise RuntimeError(f"Input WAV does not exist: {input_wav}")
    config = load_asr_config(args.config)
    if args.model:
        config = replace(config, model_path=args.model.resolve())
    source_properties = wav_properties(input_wav)
    if source_properties["duration_seconds"] > config.max_audio_duration_seconds:
        raise RuntimeError(
            f"Input WAV is {source_properties['duration_seconds']:.3f} s; "
            f"maximum is {config.max_audio_duration_seconds:.3f} s"
        )

    started = time.perf_counter()
    with tempfile.TemporaryDirectory(prefix="jetson_asr_j3a_") as temporary:
        if source_properties["is_16k_mono_s16le"]:
            recognition_wav = input_wav
            resample_method = "not_required"
        else:
            recognition_wav = Path(temporary) / "input_16k_mono.wav"
            resample_method = resample_to_16k(input_wav, recognition_wav)
        normalized_properties = wav_properties(recognition_wav)
        if not normalized_properties["is_16k_mono_s16le"]:
            raise RuntimeError("Resampled WAV is not 16 kHz mono signed 16-bit PCM")
        grammar_enabled = bool(args.grammar or config.grammar_enabled)
        recognized_text = recognize_vosk_wav(recognition_wav, config, use_grammar=grammar_enabled)
    processing_ms = (time.perf_counter() - started) * 1000.0

    matched = match_fixed_command(recognized_text, config.commands)
    result = {
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "status": "PASS",
        "input_wav": str(input_wav),
        "model_path": str(config.model_path),
        "source_audio": source_properties,
        "recognition_audio": normalized_properties,
        "resample_method": resample_method,
        "recognition_mode": "grammar" if grammar_enabled else "open",
        "recognized_text": recognized_text,
        "command_id": matched.command_id if matched else None,
        "phrase": matched.phrase if matched else None,
        "unknown": matched is None,
        "audio_duration_seconds": float(normalized_properties["duration_seconds"]),
        "processing_time_ms": processing_ms,
    }
    write_reports(result, args.json_report.resolve(), args.markdown_report.resolve())
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except RuntimeError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        raise SystemExit(2) from None
