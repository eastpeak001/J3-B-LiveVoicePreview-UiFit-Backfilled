from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

from jetson_asr_common import (
    DEFAULT_CONFIG_PATH,
    AsrConfig,
    load_asr_config,
    match_fixed_command,
    require_vosk_model,
)


PACKAGE_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_REPORT_DIR = PACKAGE_ROOT / "reports" / "runtime_j3b"


def local_timestamp() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


@dataclass
class LiveAsrState:
    started_at: str = ""
    ended_at: str | None = None
    latest_recognized_text: str = ""
    latest_command_id: str | None = None
    latest_phrase: str | None = None
    latest_unknown: bool = False
    asr_events: int = 0
    command_events: int = 0
    unknown_count: int = 0
    audio_bytes: int = 0
    errors: list[str] = field(default_factory=list)
    command_history: list[dict[str, Any]] = field(default_factory=list)
    asr_history: list[dict[str, Any]] = field(default_factory=list)
    exit_requested: bool = False
    running: bool = False


class LiveAsrSession:
    def __init__(
        self,
        config: AsrConfig,
        audio_device: str = "plughw:0,0",
        command_cooldown_ms: int = 800,
    ) -> None:
        if command_cooldown_ms < 0:
            raise ValueError("command_cooldown_ms must be non-negative")
        self.config = config
        self.audio_device = audio_device
        self.command_cooldown_ms = command_cooldown_ms
        self._state = LiveAsrState()
        self._state_lock = threading.Lock()
        self._process_lock = threading.Lock()
        self._process: subprocess.Popen[bytes] | None = None
        self._stop_event = threading.Event()
        self._finished_event = threading.Event()
        self._thread: threading.Thread | None = None
        self._last_command_times: dict[str, float] = {}
        self._started_monotonic = 0.0

    def start(self) -> None:
        if self._thread is not None:
            raise RuntimeError("Live ASR session has already been started")
        self._started_monotonic = time.monotonic()
        with self._state_lock:
            self._state.started_at = local_timestamp()
            self._state.running = True
        self._thread = threading.Thread(target=self._worker, name="jetson-live-asr", daemon=True)
        self._thread.start()

    def stop(self, timeout: float = 5.0) -> None:
        self._stop_event.set()
        with self._process_lock:
            process = self._process
        if process is not None and process.poll() is None:
            process.terminate()
        if self._thread is not None:
            self._thread.join(timeout=timeout)
            if self._thread.is_alive():
                self._append_error("ASR worker did not stop within the timeout")
                with self._process_lock:
                    process = self._process
                if process is not None and process.poll() is None:
                    process.kill()
                self._thread.join(timeout=1.0)

    def snapshot(self) -> dict[str, Any]:
        with self._state_lock:
            payload = {
                "started_at": self._state.started_at,
                "ended_at": self._state.ended_at,
                "latest_recognized_text": self._state.latest_recognized_text,
                "latest_command_id": self._state.latest_command_id,
                "latest_phrase": self._state.latest_phrase,
                "latest_unknown": self._state.latest_unknown,
                "asr_events": self._state.asr_events,
                "command_events": self._state.command_events,
                "unknown_count": self._state.unknown_count,
                "audio_bytes": self._state.audio_bytes,
                "errors": list(self._state.errors),
                "command_history": list(self._state.command_history),
                "asr_history": list(self._state.asr_history),
                "exit_requested": self._state.exit_requested,
                "running": self._state.running,
            }
        elapsed = time.monotonic() - self._started_monotonic if self._started_monotonic else 0.0
        payload["duration_seconds"] = max(0.0, elapsed)
        payload["audio_device"] = self.audio_device
        payload["sample_rate"] = self.config.sample_rate
        payload["command_cooldown_ms"] = self.command_cooldown_ms
        return payload

    @property
    def finished(self) -> bool:
        return self._finished_event.is_set()

    def _append_error(self, message: str) -> None:
        with self._state_lock:
            self._state.errors.append(message)
        print(f"ASR_ERROR: {message}", file=sys.stderr, flush=True)

    def _record_text(self, recognized_text: str) -> None:
        text = recognized_text.strip()
        if not text:
            return
        matched = match_fixed_command(text, self.config.commands)
        now = time.monotonic()
        command_emitted = False
        event: dict[str, Any] | None = None
        if matched is not None:
            last_time = self._last_command_times.get(matched.command_id, float("-inf"))
            if (now - last_time) * 1000.0 >= self.command_cooldown_ms:
                self._last_command_times[matched.command_id] = now
                command_emitted = True
                event = {
                    "type": "command",
                    "timestamp": local_timestamp(),
                    "recognized_text": text,
                    "command_id": matched.command_id,
                    "phrase": matched.phrase,
                }
        with self._state_lock:
            self._state.asr_events += 1
            self._state.latest_recognized_text = text
            self._state.latest_command_id = matched.command_id if matched else None
            self._state.latest_phrase = matched.phrase if matched else None
            self._state.latest_unknown = matched is None
            self._state.asr_history.append({
                "timestamp": local_timestamp(),
                "recognized_text": text,
                "command_id": matched.command_id if matched else None,
                "unknown": matched is None,
            })
            del self._state.asr_history[:-20]
            if matched is None:
                self._state.unknown_count += 1
            if command_emitted and event is not None:
                self._state.command_events += 1
                self._state.command_history.append(event)
                if matched is not None and matched.command_id == "exit_program":
                    self._state.exit_requested = True
                    self._stop_event.set()
        if event is not None:
            print(json.dumps(event, ensure_ascii=False), flush=True)
        elif matched is None:
            print(f"ASR_UNKNOWN: {text}", flush=True)

    def _worker(self) -> None:
        process: subprocess.Popen[bytes] | None = None
        try:
            if shutil.which("arecord") is None:
                raise RuntimeError("arecord is unavailable; install alsa-utils on the Jetson")
            require_vosk_model(self.config.model_path)
            try:
                from vosk import KaldiRecognizer, Model, SetLogLevel
            except ImportError as exc:
                raise RuntimeError("Python package 'vosk' is not installed") from exc
            SetLogLevel(-1)
            model = Model(str(self.config.model_path))
            recognizer = KaldiRecognizer(model, self.config.sample_rate)
            command = [
                "arecord",
                "-q",
                "-D",
                self.audio_device,
                "-t",
                "raw",
                "-f",
                "S16_LE",
                "-c",
                "1",
                "-r",
                str(self.config.sample_rate),
            ]
            process = subprocess.Popen(
                command,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                bufsize=0,
            )
            with self._process_lock:
                self._process = process
            if process.stdout is None:
                raise RuntimeError("arecord stdout pipe was not created")
            chunk_bytes = max(2, self.config.chunk_frames * 2)
            while not self._stop_event.is_set():
                payload = process.stdout.read(chunk_bytes)
                if not payload:
                    if process.poll() is not None:
                        break
                    continue
                with self._state_lock:
                    self._state.audio_bytes += len(payload)
                if recognizer.AcceptWaveform(payload):
                    result = json.loads(recognizer.Result())
                    self._record_text(str(result.get("text", "")))
            final_result = json.loads(recognizer.FinalResult())
            self._record_text(str(final_result.get("text", "")))
            if not self._stop_event.is_set() and process.poll() not in (None, 0):
                stderr = process.stderr.read().decode("utf-8", errors="replace") if process.stderr else ""
                raise RuntimeError(f"arecord exited with code {process.returncode}: {stderr.strip()}")
        except Exception as exc:
            self._append_error(f"{type(exc).__name__}: {exc}")
        finally:
            if process is not None and process.poll() is None:
                process.terminate()
                try:
                    process.wait(timeout=2.0)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(timeout=1.0)
            with self._process_lock:
                self._process = None
            with self._state_lock:
                self._state.running = False
                self._state.ended_at = local_timestamp()
            self._finished_event.set()


def write_live_asr_reports(result: dict[str, Any], report_dir: Path) -> None:
    report_dir.mkdir(parents=True, exist_ok=True)
    json_path = report_dir / "jetson_asr_live_command.json"
    markdown_path = report_dir / "jetson_asr_live_command_report.md"
    json_path.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    lines = [
        "# Jetson J3-B Live Fixed-command ASR Report",
        "",
        f"- Status: **{result['status']}**",
        f"- Start: {result['started_at']}",
        f"- End: {result['ended_at']}",
        f"- Duration: {result['duration_seconds']:.3f} s",
        f"- Audio device: `{result['audio_device']}`",
        f"- Sample rate: {result['sample_rate']} Hz mono S16_LE",
        f"- ASR events: {result['asr_events']}",
        f"- Command events: {result['command_events']}",
        f"- Unknown count: {result['unknown_count']}",
        f"- Errors: {len(result['errors'])}",
        "",
        "Unknown recognition results never emit command events. This test does not run depth "
        "processing or control hardware.",
    ]
    if result["errors"]:
        lines.extend(["", "## Errors", "", *[f"- {item}" for item in result["errors"]]])
    markdown_path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description="Jetson J3-B live microphone fixed-command test")
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG_PATH)
    parser.add_argument("--audio-device", default="plughw:0,0")
    parser.add_argument("--duration", type=float, default=60.0)
    parser.add_argument("--command-cooldown-ms", type=int, default=800)
    parser.add_argument("--report-dir", type=Path, default=DEFAULT_REPORT_DIR)
    args = parser.parse_args()
    if args.duration <= 0:
        raise RuntimeError("--duration must be positive")
    config = load_asr_config(args.config)
    session = LiveAsrSession(config, args.audio_device, args.command_cooldown_ms)
    session.start()
    try:
        deadline = time.monotonic() + args.duration
        while time.monotonic() < deadline and not session.finished:
            if session.snapshot()["exit_requested"]:
                break
            time.sleep(0.1)
    except KeyboardInterrupt:
        print("Ctrl+C received; stopping live ASR", file=sys.stderr)
    finally:
        session.stop()
    result = session.snapshot()
    result["status"] = "PASS" if not result["errors"] else "FAIL"
    write_live_asr_reports(result, args.report_dir.resolve())
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result["status"] == "PASS" else 1


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except RuntimeError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        raise SystemExit(2) from None
