from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from pathlib import Path
import numpy as np
import yaml


PACKAGE_ROOT = Path(__file__).resolve().parents[1]
WINDOWS_PATH_PATTERN = re.compile(r"(?i)\b[a-z]:[\\/]")


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def read_manifest() -> dict[str, str]:
    path = PACKAGE_ROOT / "reports" / "windows_source_manifest.sha256"
    result: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        expected, relative = line.split(" *", 1)
        result[relative] = expected
    return result


def verify_no_windows_paths() -> list[str]:
    failures = []
    for path in PACKAGE_ROOT.rglob("*"):
        if not path.is_file() or path.suffix.lower() not in {".py", ".yaml", ".yml", ".md", ".txt", ".sh"}:
            continue
        text = path.read_text(encoding="utf-8", errors="replace")
        if WINDOWS_PATH_PATTERN.search(text):
            failures.append(str(path.relative_to(PACKAGE_ROOT)))
    return failures


def verify(simulate_no_ximgproc: bool = False) -> list[str]:
    errors: list[str] = []
    calibration_path = PACKAGE_ROOT / "config" / "calibration_canonical.yaml"
    maps_path = PACKAGE_ROOT / "config" / "calibration_maps_canonical.npz"
    runtime_path = PACKAGE_ROOT / "config" / "depth_runtime_jetson.yaml"
    asr_config_path = PACKAGE_ROOT / "config" / "asr_commands_zh.yaml"
    required_j3a_paths = (
        asr_config_path,
        PACKAGE_ROOT / "scripts" / "jetson_asr_common.py",
        PACKAGE_ROOT / "scripts" / "jetson_asr_offline_fixed_command_test.py",
        PACKAGE_ROOT / "scripts" / "jetson_asr_matcher_self_test.py",
        PACKAGE_ROOT / "tools" / "run_asr_offline_fixed_command_test.sh",
        PACKAGE_ROOT / "models" / "asr" / "README_ASR_MODEL.md",
    )
    required_j3b_paths = (
        PACKAGE_ROOT / "scripts" / "jetson_asr_live_command_test.py",
        PACKAGE_ROOT / "scripts" / "jetson_camera_preview_voice_test.py",
        PACKAGE_ROOT / "tools" / "run_asr_live_command_test.sh",
        PACKAGE_ROOT / "tools" / "run_camera_preview_voice_test.sh",
        PACKAGE_ROOT / "tools" / "package_jetson_deployment.py",
        PACKAGE_ROOT / "reports" / "runtime_j3b" / ".gitkeep",
    )
    for path in (
        calibration_path,
        maps_path,
        runtime_path,
        *required_j3a_paths,
        *required_j3b_paths,
    ):
        if not path.is_file():
            errors.append(f"missing: {path.relative_to(PACKAGE_ROOT)}")
    if errors:
        return errors

    calibration = yaml.safe_load(calibration_path.read_text(encoding="utf-8"))
    runtime = yaml.safe_load(runtime_path.read_text(encoding="utf-8"))
    if int(calibration.get("image_width", 0)) != 1280 or int(calibration.get("image_height", 0)) != 720:
        errors.append("canonical image size is not 1280x720")
    if float(calibration["T"][0]) >= 0:
        errors.append("canonical T_x must be negative")
    if float(calibration["P2"][0][3]) >= 0:
        errors.append("canonical P2[0,3] must be negative")
    expected_layout = {
        "mode": "horizontal_sbs",
        "left_half_is_physical_left": True,
        "right_half_is_physical_right": True,
        "swap_left_right": False,
        "mirror_horizontal": False,
        "mirror_vertical": False,
    }
    if runtime.get("raw_layout") != expected_layout:
        errors.append("unsafe raw_layout: canonical physical order is not exact")
    if runtime.get("profile") != "jetson_canonical_physical_order":
        errors.append("unexpected Jetson runtime profile")

    asr_config = yaml.safe_load(asr_config_path.read_text(encoding="utf-8"))
    asr = asr_config.get("asr") if isinstance(asr_config, dict) else None
    commands = asr_config.get("commands") if isinstance(asr_config, dict) else None
    profile = asr_config.get("profile") if isinstance(asr_config, dict) else None
    if profile != "jetson_vosk_offline_fixed_commands_zh":
        errors.append("unexpected J3-A ASR profile")
    if not isinstance(asr, dict) or asr.get("engine") != "vosk":
        errors.append("J3-A ASR engine must be vosk")
    else:
        model_path = asr.get("model_path")
        if (
            not isinstance(model_path, str)
            or not model_path
            or re.match(r"(?i)^[a-z][a-z0-9+.-]*://", model_path)
            or Path(model_path).is_absolute()
        ):
            errors.append("J3-A model_path must be a non-empty local relative path")
        try:
            sample_rate = int(asr.get("sample_rate", 0))
        except (TypeError, ValueError):
            sample_rate = 0
        if sample_rate != 16000:
            errors.append("J3-A ASR sample rate must be 16000 Hz")
        if asr.get("grammar_enabled") is not False:
            errors.append("J3-A Chinese grammar mode must be disabled by default")
    if not isinstance(commands, list) or not commands:
        errors.append("J3-A fixed command list is empty")
    else:
        command_ids = [record.get("command_id") for record in commands if isinstance(record, dict)]
        enabled_values = [record.get("enabled", True) for record in commands if isinstance(record, dict)]
        phrases = [record.get("phrase") for record in commands if isinstance(record, dict)]
        phrase_lists = [record.get("phrases", [record.get("phrase")]) for record in commands if isinstance(record, dict)]
        keywords = [record.get("keywords") for record in commands if isinstance(record, dict)]
        if len(command_ids) != len(commands) or not all(isinstance(value, str) and value for value in command_ids):
            errors.append("J3-A command_id values must be non-empty strings")
        elif len(set(command_ids)) != len(command_ids):
            errors.append("J3-A command_id values must be unique")
        if len(enabled_values) != len(commands) or not all(isinstance(value, bool) for value in enabled_values):
            errors.append("J3-A enabled values must be true or false")
        elif not any(enabled_values):
            errors.append("J3-A must have at least one enabled command")
        else:
            enabled_ids = {
                command_id
                for command_id, enabled in zip(command_ids, enabled_values)
                if enabled and isinstance(command_id, str)
            }
            safe_ids = {"start_depth", "stop_depth", "save_frame", "show_depth", "exit_program"}
            if enabled_ids != safe_ids:
                errors.append("J3-A enabled command set must contain exactly the five safe software commands")
        if len(phrases) != len(commands) or not all(isinstance(value, str) and value for value in phrases):
            errors.append("J3-A phrase values must be non-empty strings")
        elif len(set(phrases)) != len(phrases):
            errors.append("J3-A phrase values must be unique")
        if len(phrase_lists) != len(commands) or not all(
            isinstance(value, list)
            and value
            and all(isinstance(phrase, str) and phrase for phrase in value)
            for value in phrase_lists
        ):
            errors.append("J3-A phrases must be non-empty string lists")
        if len(keywords) != len(commands) or not all(
            isinstance(value, list)
            and value
            and (
                all(isinstance(keyword, str) and keyword for keyword in value)
                or all(
                    isinstance(group, list)
                    and group
                    and all(isinstance(keyword, str) and keyword for keyword in group)
                    for group in value
                )
            )
            for value in keywords
        ):
            errors.append("J3-A keywords must be a string list or list of string lists")

        configured_text = json.dumps(commands, ensure_ascii=False)
        forbidden_command_terms = ("云台", "机械臂", "抓取", "移动", "前进", "后退", "左转", "右转")
        if any(term in configured_text for term in forbidden_command_terms):
            errors.append("J3 command config contains a forbidden hardware or movement term")

    preview_script = (PACKAGE_ROOT / "scripts" / "jetson_camera_preview_voice_test.py").read_text(
        encoding="utf-8"
    )
    required_preview_flags = (
        "--window-width",
        "--window-height",
        "--fit-window",
        "--overlay-scale",
        "--left-view-only",
    )
    missing_preview_flags = [flag for flag in required_preview_flags if flag not in preview_script]
    if missing_preview_flags:
        errors.append("J3-B preview flags missing: " + ", ".join(missing_preview_flags))

    with np.load(maps_path) as maps:
        required_shapes = {
            "map1_left": (720, 1280),
            "map2_left": (720, 1280),
            "map1_right": (720, 1280),
            "map2_right": (720, 1280),
            "Q": (4, 4),
        }
        for key, shape in required_shapes.items():
            if key not in maps or maps[key].shape != shape:
                errors.append(f"{key} shape must be {shape}")
        if "Q" in maps and maps["Q"].shape == (4, 4) and float(maps["Q"][3, 2]) <= 0:
            errors.append("canonical Q[3,2] must be positive")

    manifest = read_manifest()
    for source_relative, local_path in {
        "config/calibration_canonical.yaml": calibration_path,
        "config/calibration_maps_canonical.npz": maps_path,
    }.items():
        expected = manifest.get(source_relative)
        if expected is None:
            errors.append(f"source manifest is missing {source_relative}")
        elif sha256_file(local_path) != expected:
            errors.append(f"hash mismatch: {source_relative}")

    windows_paths = verify_no_windows_paths()
    if windows_paths:
        errors.append("Windows absolute paths found in: " + ", ".join(windows_paths))

    if simulate_no_ximgproc and not errors:
        from depth_core_jetson import StereoDepthProcessor, load_runtime_config

        loaded = load_runtime_config(runtime_path)
        processor = StereoDepthProcessor(loaded, allow_ximgproc=False)
        if processor.ximgproc_available or processor.wls_enabled:
            errors.append("Raw fallback simulation did not disable ximgproc/WLS")
        if processor.left_matcher is None:
            errors.append("Raw StereoSGBM matcher did not initialize without ximgproc")
        else:
            print("NO_XIMGPROC_FALLBACK: PASS (Raw StereoSGBM initialized, WLS disabled)")
    return errors


def main() -> int:
    parser = argparse.ArgumentParser(description="Verify frozen Jetson deployment assets")
    parser.add_argument("--simulate-no-ximgproc", action="store_true")
    args = parser.parse_args()
    errors = verify(args.simulate_no_ximgproc)
    if errors:
        for error in errors:
            print(f"FAIL: {error}", file=sys.stderr)
        return 1
    print("DEPLOYMENT_ASSET_VERIFY: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
