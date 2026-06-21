from __future__ import annotations

import hashlib
import json
import math
import os
import re
import shutil
import subprocess
import wave
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np


PACKAGE_ROOT = Path(__file__).resolve().parents[1]
REPORT_DIR = PACKAGE_ROOT / "reports"
TARGET_VID = "1bcf"
TARGET_PID = "2d4f"
TARGET_NAME_TOKENS = ("usb2.0 camera rgb", "usb camera", "usb audio", "microphone")


@dataclass(frozen=True)
class CommandResult:
    command: tuple[str, ...]
    returncode: int
    stdout: str
    stderr: str

    @property
    def combined(self) -> str:
        parts = [part.strip() for part in (self.stdout, self.stderr) if part.strip()]
        return "\n".join(parts)


def run_command(command: list[str], timeout: int = 20) -> CommandResult:
    try:
        completed = subprocess.run(
            command,
            text=True,
            capture_output=True,
            timeout=timeout,
            check=False,
        )
        return CommandResult(tuple(command), completed.returncode, completed.stdout, completed.stderr)
    except (OSError, subprocess.TimeoutExpired) as exc:
        return CommandResult(tuple(command), 127, "", f"{type(exc).__name__}: {exc}")


def command_section(result: CommandResult) -> str:
    return (
        f"$ {' '.join(result.command)}\n"
        f"exit={result.returncode}\n"
        f"{result.combined or '(no output)'}\n"
    )


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8", errors="replace").strip()
    except Exception as exc:
        return f"<read failed: {type(exc).__name__}: {exc}>"


def usb_identity_from_path(path: Path) -> dict[str, str | None]:
    try:
        current = path.resolve()
    except OSError:
        return {"vid": None, "pid": None, "usb_bus_path": None, "product": None}
    for parent in (current, *current.parents):
        vid_path = parent / "idVendor"
        pid_path = parent / "idProduct"
        if vid_path.is_file() and pid_path.is_file():
            return {
                "vid": read_text(vid_path).lower(),
                "pid": read_text(pid_path).lower(),
                "usb_bus_path": str(parent),
                "product": read_text(parent / "product") or None,
            }
    return {"vid": None, "pid": None, "usb_bus_path": None, "product": None}


def discover_target_usb_devices() -> list[dict[str, str | None]]:
    root = Path(os.environ.get("JETSON_AUDIO_SYS_USB_ROOT", "/sys/bus/usb/devices"))
    matches = []
    if not root.is_dir():
        return matches
    for path in root.iterdir():
        identity = usb_identity_from_path(path)
        if identity["vid"] == TARGET_VID and identity["pid"] == TARGET_PID:
            if identity not in matches:
                matches.append(identity)
    return matches


def card_usb_identity(card_index: int) -> dict[str, str | None]:
    root = Path(os.environ.get("JETSON_AUDIO_SYS_SOUND_ROOT", "/sys/class/sound"))
    return usb_identity_from_path(root / f"card{card_index}" / "device")


def parse_arecord_devices(text: str) -> list[dict[str, Any]]:
    pattern = re.compile(
        r"card\s+(?P<card>\d+):\s*(?P<card_id>[^\s]+)\s*\[(?P<card_name>[^]]+)\],\s*"
        r"device\s+(?P<device>\d+):\s*(?P<device_id>[^\[]+)\[(?P<device_name>[^]]+)\]",
        re.IGNORECASE,
    )
    records = []
    for line in text.splitlines():
        match = pattern.search(line)
        if not match:
            continue
        record: dict[str, Any] = match.groupdict()
        record["card"] = int(record["card"])
        record["device"] = int(record["device"])
        record = {key: value.strip() if isinstance(value, str) else value for key, value in record.items()}
        record["usb"] = card_usb_identity(record["card"])
        records.append(record)
    return records


def is_target_alsa_device(record: dict[str, Any]) -> bool:
    usb = record.get("usb") or {}
    return usb.get("vid") == TARGET_VID and usb.get("pid") == TARGET_PID


def recommended_alsa_strings(record: dict[str, Any]) -> tuple[str, str]:
    card_id = re.sub(r"[^A-Za-z0-9_]", "", str(record["card_id"]))
    if not card_id:
        card_id = str(record["card"])
    device = int(record["device"])
    return f"hw:CARD={card_id},DEV={device}", f"plughw:CARD={card_id},DEV={device}"


def parse_hw_params(text: str) -> dict[str, Any]:
    result: dict[str, Any] = {
        "formats": [], "rates": [], "rate_min": None, "rate_max": None,
        "channels_min": None, "channels_max": None,
    }
    format_match = re.search(r"FORMAT:\s*([^\n]+)", text)
    if format_match:
        result["formats"] = re.findall(r"[A-Z0-9_]+", format_match.group(1))
    rate_match = re.search(r"RATE:\s*([^\n]+)", text)
    if rate_match:
        values = [int(value) for value in re.findall(r"\b\d{4,6}\b", rate_match.group(1))]
        result["rates"] = values
        if values:
            result["rate_min"] = min(values)
            result["rate_max"] = max(values)
    channels_match = re.search(r"CHANNELS:\s*([^\n]+)", text)
    if channels_match:
        values = [int(value) for value in re.findall(r"\d+", channels_match.group(1))]
        if values:
            result["channels_min"] = min(values)
            result["channels_max"] = max(values)
    return result


def choose_native_format(capabilities: dict[str, Any]) -> tuple[int, int, str]:
    formats = capabilities.get("formats") or []
    if formats and "S16_LE" not in formats:
        raise RuntimeError(f"Target microphone does not advertise S16_LE: {formats}")
    rates = capabilities.get("rates") or []
    rate_min = capabilities.get("rate_min")
    rate_max = capabilities.get("rate_max")
    channels_min = capabilities.get("channels_min")
    channels_max = capabilities.get("channels_max")
    for rate in (44100, 48000):
        rate_in_range = rate_min is not None and rate_max is not None and rate_min <= rate <= rate_max
        if rates and rate not in rates and not rate_in_range:
            continue
        for channels in (2, 1):
            if channels_min is not None and channels < channels_min:
                continue
            if channels_max is not None and channels > channels_max:
                continue
            return rate, channels, "S16_LE"
    raise RuntimeError(f"No supported 44.1/48 kHz S16_LE mono/stereo format: {capabilities}")


def load_probe_state(path: Path | None = None) -> dict[str, Any]:
    state_path = path or REPORT_DIR / "jetson_audio_probe.json"
    if not state_path.is_file():
        raise RuntimeError("Audio probe state is missing; run tools/run_audio_probe.sh first")
    state = json.loads(state_path.read_text(encoding="utf-8"))
    if not state.get("target_found"):
        raise RuntimeError("Audio probe did not confirm the target USB microphone")
    target = state.get("target") or {}
    if str(target.get("vid", "")).lower() != TARGET_VID or str(target.get("pid", "")).lower() != TARGET_PID:
        raise RuntimeError("Refusing audio capture: probe state VID/PID is not 1BCF:2D4F")
    return state


def write_wav(path: Path, samples: np.ndarray, sample_rate: int) -> None:
    data = np.asarray(samples, dtype=np.int16)
    if data.ndim == 1:
        data = data[:, None]
    path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(path), "wb") as handle:
        handle.setnchannels(data.shape[1])
        handle.setsampwidth(2)
        handle.setframerate(sample_rate)
        handle.writeframes(data.astype("<i2", copy=False).tobytes())


def read_wav(path: Path) -> tuple[np.ndarray, int, int, int]:
    with wave.open(str(path), "rb") as handle:
        channels = handle.getnchannels()
        sample_width = handle.getsampwidth()
        sample_rate = handle.getframerate()
        frame_count = handle.getnframes()
        payload = handle.readframes(frame_count)
    if sample_width != 2:
        raise RuntimeError(f"Expected 16-bit PCM WAV, got {sample_width * 8}-bit")
    samples = np.frombuffer(payload, dtype="<i2").reshape(-1, channels).copy()
    return samples, sample_rate, channels, sample_width * 8


def mono_samples(samples: np.ndarray) -> np.ndarray:
    if samples.ndim == 1 or samples.shape[1] == 1:
        return samples.reshape(-1).astype(np.int16, copy=False)
    return np.rint(samples.astype(np.float64).mean(axis=1)).clip(-32768, 32767).astype(np.int16)


def numpy_resample_to_16k(source: Path, destination: Path) -> str:
    samples, sample_rate, _, _ = read_wav(source)
    mono = mono_samples(samples)
    if sample_rate == 16000:
        output = mono.copy()
    else:
        # A short boxcar low-pass limits aliasing before deterministic linear interpolation.
        if sample_rate > 16000:
            width = max(1, int(sample_rate // 16000))
            kernel = np.ones(width, dtype=np.float64) / width
            filtered = np.convolve(mono.astype(np.float64), kernel, mode="same")
        else:
            filtered = mono.astype(np.float64)
        count = int(round(filtered.size * 16000 / sample_rate))
        source_x = np.arange(filtered.size, dtype=np.float64)
        target_x = np.arange(count, dtype=np.float64) * sample_rate / 16000
        output = np.rint(np.interp(target_x, source_x, filtered)).clip(-32768, 32767).astype(np.int16)
    write_wav(destination, output, 16000)
    return "numpy_lowpass_linear"


def resample_to_16k(source: Path, destination: Path, force_numpy: bool = False) -> str:
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.unlink(missing_ok=True)
    if not force_numpy and shutil.which("ffmpeg"):
        result = run_command([
            "ffmpeg", "-nostdin", "-hide_banner", "-loglevel", "error", "-y",
            "-i", str(source), "-ac", "1", "-ar", "16000", "-c:a", "pcm_s16le", str(destination),
        ], timeout=180)
        if result.returncode == 0 and destination.is_file():
            return "ffmpeg"
        destination.unlink(missing_ok=True)
    if not force_numpy and shutil.which("sox"):
        result = run_command(["sox", str(source), "-r", "16000", "-c", "1", "-b", "16", str(destination)], timeout=180)
        if result.returncode == 0 and destination.is_file():
            return "sox"
        destination.unlink(missing_ok=True)
    return numpy_resample_to_16k(source, destination)


def analyze_pcm(samples: np.ndarray, sample_rate: int) -> dict[str, Any]:
    mono = mono_samples(samples)
    if mono.size == 0:
        raise RuntimeError("Captured WAV contains no audio frames")
    normalized = mono.astype(np.float64) / 32768.0
    absolute = np.abs(normalized)
    peak = float(np.max(absolute))
    rms = float(np.sqrt(np.mean(normalized * normalized)))
    silence = absolute <= 0.005
    frame_size = max(1, int(round(sample_rate * 0.02)))
    usable = (mono.size // frame_size) * frame_size
    frame_rms = np.sqrt(np.mean(normalized[:usable].reshape(-1, frame_size) ** 2, axis=1)) if usable else np.array([rms])
    dropout_transitions = int(np.sum((frame_rms[:-1] > 0.01) & (frame_rms[1:] < 0.0005)))
    return {
        "duration_seconds": mono.size / sample_rate,
        "audio_frame_count": int(mono.size),
        "peak": peak,
        "rms": rms,
        "clipping_ratio": float(np.mean(np.abs(mono.astype(np.int32)) >= 32760)),
        "silence_ratio": float(np.mean(silence)),
        "dc_offset": float(np.mean(normalized)),
        "possible_dropout_transitions": dropout_transitions,
    }


def parse_arecord_overruns(text: str) -> int:
    return len(re.findall(r"(?i)overrun|xrun", text))


def thermal_snapshot() -> dict[str, float | str]:
    result: dict[str, float | str] = {}
    root = Path("/sys/class/thermal")
    for zone in root.glob("thermal_zone*"):
        zone_type = read_text(zone / "type")
        name = zone.name if not zone_type or zone_type.startswith("<read failed:") else zone_type
        raw = read_text(zone / "temp")
        if raw.startswith("<read failed:"):
            result[name] = f"unavailable: {raw}"
            continue
        try:
            value = float(raw)
        except (TypeError, ValueError) as exc:
            result[name] = f"unavailable: {type(exc).__name__}: {exc}"
            continue
        if not math.isfinite(value):
            result[name] = f"unavailable: non-finite value {raw!r}"
            continue
        result[name] = value / 1000.0 if value > 1000 else value
    return result


def kernel_usb_errors(text: str) -> list[str]:
    pattern = re.compile(r"(?i)usb.*(reset|disconnect|over-current|bandwidth|not enough bandwidth|error -\d+)")
    return [line for line in text.splitlines() if pattern.search(line)]
