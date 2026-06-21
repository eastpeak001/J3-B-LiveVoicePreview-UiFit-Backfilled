from __future__ import annotations

import json
import re
import wave
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml


PACKAGE_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CONFIG_PATH = PACKAGE_ROOT / "config" / "asr_commands_zh.yaml"
DEFAULT_JSON_REPORT = PACKAGE_ROOT / "reports" / "runtime_j3" / "jetson_asr_offline_fixed_command.json"
DEFAULT_MARKDOWN_REPORT = PACKAGE_ROOT / "reports" / "runtime_j3" / "jetson_asr_offline_fixed_command_report.md"


@dataclass(frozen=True)
class FixedCommand:
    command_id: str
    enabled: bool
    phrase: str
    normalized_phrase: str
    keywords: tuple[str, ...]
    normalized_keywords: tuple[str, ...]
    phrases: tuple[str, ...]
    normalized_phrases: tuple[str, ...]
    keyword_groups: tuple[tuple[str, ...], ...]
    normalized_keyword_groups: tuple[tuple[str, ...], ...]


@dataclass(frozen=True)
class AsrConfig:
    model_path: Path
    sample_rate: int
    chunk_frames: int
    max_audio_duration_seconds: float
    grammar_enabled: bool
    commands: tuple[FixedCommand, ...]


def normalize_text(text: str) -> str:
    without_unknown = re.sub(r"\[\s*unk\s*\]", "", text, flags=re.IGNORECASE)
    return re.sub(r"[^0-9A-Za-z\u3400-\u9fff]+", "", without_unknown).lower()


def load_asr_config(path: Path = DEFAULT_CONFIG_PATH) -> AsrConfig:
    config_path = path.resolve()
    payload = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise RuntimeError("ASR configuration must be a YAML mapping")
    asr = payload.get("asr")
    command_records = payload.get("commands")
    if not isinstance(asr, dict) or not isinstance(command_records, list):
        raise RuntimeError("ASR configuration requires 'asr' and 'commands' sections")
    if asr.get("engine") != "vosk":
        raise RuntimeError("J3-A only supports the offline Vosk engine")

    model_value = asr.get("model_path")
    if not isinstance(model_value, str) or not model_value.strip():
        raise RuntimeError("asr.model_path must be a non-empty string")
    model_path = Path(model_value)
    if not model_path.is_absolute():
        model_path = PACKAGE_ROOT / model_path

    commands = []
    command_ids: set[str] = set()
    normalized_phrases: set[str] = set()
    for index, record in enumerate(command_records, start=1):
        if not isinstance(record, dict):
            raise RuntimeError(f"commands[{index}] must be a mapping")
        command_id = record.get("command_id")
        enabled = record.get("enabled", True)
        phrase = record.get("phrase")
        phrases = record.get("phrases", [phrase])
        keywords = record.get("keywords")
        if not isinstance(command_id, str) or not command_id.strip():
            raise RuntimeError(f"commands[{index}].command_id must be a non-empty string")
        if not isinstance(enabled, bool):
            raise RuntimeError(f"commands[{index}].enabled must be true or false")
        if not isinstance(phrase, str) or not phrase.strip():
            raise RuntimeError(f"commands[{index}].phrase must be a non-empty string")
        if (
            not isinstance(phrases, list)
            or not phrases
            or not all(isinstance(value, str) and value.strip() for value in phrases)
        ):
            raise RuntimeError(f"commands[{index}].phrases must be a non-empty string list")
        if phrase not in phrases:
            phrases = [phrase, *phrases]
        if not isinstance(keywords, list) or not keywords:
            raise RuntimeError(f"commands[{index}].keywords must not be empty")
        if all(isinstance(keyword, str) and keyword.strip() for keyword in keywords):
            keyword_groups = [keywords]
        elif all(
            isinstance(group, list)
            and group
            and all(isinstance(keyword, str) and keyword.strip() for keyword in group)
            for group in keywords
        ):
            keyword_groups = keywords
        else:
            raise RuntimeError(
                f"commands[{index}].keywords must be a string list or a list of string lists"
            )
        normalized = normalize_text(phrase)
        normalized_phrase_values = tuple(normalize_text(value) for value in phrases)
        normalized_keyword_groups = tuple(
            tuple(normalize_text(keyword) for keyword in group) for group in keyword_groups
        )
        if (
            not normalized
            or not all(normalized_phrase_values)
            or len(set(normalized_phrase_values)) != len(normalized_phrase_values)
        ):
            raise RuntimeError(f"commands[{index}].phrases must be unique and matchable")
        if any(
            not all(group) or len(set(group)) != len(group)
            for group in normalized_keyword_groups
        ):
            raise RuntimeError(f"commands[{index}].keywords must be unique and matchable")
        if command_id in command_ids or any(
            value in normalized_phrases for value in normalized_phrase_values
        ):
            raise RuntimeError(f"Duplicate ASR command id or phrase at commands[{index}]")
        command_ids.add(command_id)
        normalized_phrases.update(normalized_phrase_values)
        primary_keywords = tuple(keyword_groups[0])
        primary_normalized_keywords = normalized_keyword_groups[0]
        commands.append(
            FixedCommand(
                command_id,
                enabled,
                phrase,
                normalized,
                primary_keywords,
                primary_normalized_keywords,
                tuple(phrases),
                normalized_phrase_values,
                tuple(tuple(group) for group in keyword_groups),
                normalized_keyword_groups,
            )
        )
    if not commands:
        raise RuntimeError("At least one fixed ASR command is required")

    sample_rate = int(asr.get("sample_rate", 16000))
    chunk_frames = int(asr.get("chunk_frames", 4000))
    max_duration = float(asr.get("max_audio_duration_seconds", 120))
    grammar_enabled = asr.get("grammar_enabled", False)
    if sample_rate != 16000:
        raise RuntimeError("J3-A recognizer sample rate must remain 16000 Hz")
    if chunk_frames <= 0 or max_duration <= 0:
        raise RuntimeError("ASR chunk size and maximum duration must be positive")
    if not isinstance(grammar_enabled, bool):
        raise RuntimeError("asr.grammar_enabled must be true or false")
    return AsrConfig(
        model_path.resolve(), sample_rate, chunk_frames, max_duration,
        grammar_enabled, tuple(commands),
    )


def require_vosk_model(model_path: Path) -> None:
    if not model_path.is_dir():
        raise RuntimeError(
            "Vosk model not found. Expected model directory: "
            f"{model_path}. No model was downloaded; network access is not used."
        )
    required_entries = ("am", "conf")
    missing = [name for name in required_entries if not (model_path / name).exists()]
    if missing:
        raise RuntimeError(
            f"Vosk model directory is incomplete at {model_path}; missing: {', '.join(missing)}"
        )


def wav_properties(path: Path) -> dict[str, Any]:
    try:
        with wave.open(str(path), "rb") as handle:
            channels = handle.getnchannels()
            sample_width = handle.getsampwidth()
            sample_rate = handle.getframerate()
            frame_count = handle.getnframes()
            compression = handle.getcomptype()
    except (OSError, wave.Error) as exc:
        raise RuntimeError(f"Could not read WAV file {path}: {exc}") from exc
    duration = frame_count / sample_rate if sample_rate > 0 else 0.0
    return {
        "channels": channels,
        "sample_width_bytes": sample_width,
        "sample_rate": sample_rate,
        "frame_count": frame_count,
        "duration_seconds": duration,
        "compression": compression,
        "is_16k_mono_s16le": (
            channels == 1 and sample_width == 2 and sample_rate == 16000 and compression == "NONE"
        ),
    }


def match_fixed_command(text: str, commands: tuple[FixedCommand, ...]) -> FixedCommand | None:
    normalized = normalize_text(text)
    if not normalized:
        return None
    enabled_commands = [command for command in commands if command.enabled]
    exact = [
        command for command in enabled_commands if normalized in command.normalized_phrases
    ]
    if len(exact) == 1:
        return exact[0]
    contained = [
        command
        for command in enabled_commands
        if any(phrase in normalized for phrase in command.normalized_phrases)
    ]
    if len(contained) == 1:
        return contained[0]
    keyword_matches = [
        command
        for command in enabled_commands
        if any(
            all(keyword in normalized for keyword in group)
            for group in command.normalized_keyword_groups
        )
    ]
    return keyword_matches[0] if len(keyword_matches) == 1 else None


def recognize_vosk_wav(path: Path, config: AsrConfig, use_grammar: bool | None = None) -> str:
    require_vosk_model(config.model_path)
    try:
        from vosk import KaldiRecognizer, Model, SetLogLevel
    except ImportError as exc:
        raise RuntimeError(
            "Python package 'vosk' is not installed. Install requirements-jetson.txt locally; "
            "the application will not download packages or models."
        ) from exc

    SetLogLevel(-1)
    model = Model(str(config.model_path))
    grammar_enabled = config.grammar_enabled if use_grammar is None else use_grammar
    if grammar_enabled:
        grammar = [
            phrase
            for command in config.commands
            if command.enabled
            for phrase in command.phrases
        ]
        grammar.append("[unk]")
        recognizer = KaldiRecognizer(model, config.sample_rate, json.dumps(grammar, ensure_ascii=False))
    else:
        recognizer = KaldiRecognizer(model, config.sample_rate)
    texts = []
    with wave.open(str(path), "rb") as handle:
        while True:
            payload = handle.readframes(config.chunk_frames)
            if not payload:
                break
            if recognizer.AcceptWaveform(payload):
                result = json.loads(recognizer.Result())
                if result.get("text"):
                    texts.append(str(result["text"]))
    final = json.loads(recognizer.FinalResult())
    if final.get("text"):
        texts.append(str(final["text"]))
    return " ".join(texts).strip()
