from __future__ import annotations

import argparse
import json
from dataclasses import replace
from pathlib import Path

from jetson_asr_common import DEFAULT_CONFIG_PATH, load_asr_config, match_fixed_command


CASES = (
    ("新车 二 车 开始 测距", "start_depth"),
    ("开始 测距", "start_depth"),
    ("启动测距", "start_depth"),
    ("打开测距", "start_depth"),
    ("保存 画面", "save_frame"),
    ("保存图片", "save_frame"),
    ("拍照保存", "save_frame"),
    ("暂停 测距", "stop_depth"),
    ("关闭 测距", "stop_depth"),
    ("停止测距", "stop_depth"),
    ("查看深度", "show_depth"),
    ("打开深度", "show_depth"),
    ("结束程序", "exit_program"),
    ("关闭程序", "exit_program"),
    ("瓶子 测距", None),
    ("测距", None),
    ("今天天气不错", None),
    ("[unk] 请 开始 一下 测距", "start_depth"),
)


def main() -> int:
    parser = argparse.ArgumentParser(description="J3-A Chinese fixed-command matcher self-test")
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG_PATH)
    args = parser.parse_args()
    config = load_asr_config(args.config)
    results = []
    passed = True
    for text, expected in CASES:
        matched = match_fixed_command(text, config.commands)
        actual = matched.command_id if matched else None
        case_passed = actual == expected
        passed = passed and case_passed
        results.append({"text": text, "expected": expected, "actual": actual, "passed": case_passed})
    disabled_commands = tuple(
        replace(command, enabled=False) if command.command_id == "start_depth" else command
        for command in config.commands
    )
    disabled_match = match_fixed_command("开始测距", disabled_commands)
    disabled_passed = disabled_match is None
    passed = passed and disabled_passed
    results.append({
        "text": "开始测距 (start_depth disabled)",
        "expected": None,
        "actual": disabled_match.command_id if disabled_match else None,
        "passed": disabled_passed,
    })
    print(json.dumps({"passed": passed, "cases": results}, ensure_ascii=False, indent=2))
    print(f"J3A_MATCHER_SELF_TEST: {'PASS' if passed else 'FAIL'}")
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
