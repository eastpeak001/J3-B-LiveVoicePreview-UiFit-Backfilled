from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
from pathlib import Path
from typing import Any


PACKAGE_ROOT = Path(__file__).resolve().parents[1]
REPORT_DIR = PACKAGE_ROOT / "reports"
TARGET_SIZE = (2560, 720)
TARGET_FPS = 60.0


def natural_video_key(path: Path) -> tuple[str, int]:
    match = re.search(r"(\d+)$", path.name)
    return path.name.rstrip("0123456789"), int(match.group(1)) if match else -1


def run(command: list[str], timeout: int = 15) -> tuple[int, str]:
    try:
        completed = subprocess.run(command, text=True, capture_output=True, timeout=timeout, check=False)
        output = completed.stdout
        if completed.stderr:
            output += ("\n" if output else "") + completed.stderr
        return completed.returncode, output.strip()
    except (OSError, subprocess.TimeoutExpired) as exc:
        return 127, f"{type(exc).__name__}: {exc}"


def usb_identity(video_path: Path) -> dict[str, str | None]:
    sys_path = Path("/sys/class/video4linux") / video_path.name / "device"
    identity: dict[str, str | None] = {"vid": None, "pid": None, "usb_bus_path": None}
    try:
        current = sys_path.resolve()
    except OSError:
        return identity
    identity["usb_bus_path"] = str(current)
    for parent in (current, *current.parents):
        vendor = parent / "idVendor"
        product = parent / "idProduct"
        if vendor.is_file() and product.is_file():
            identity["vid"] = vendor.read_text().strip()
            identity["pid"] = product.read_text().strip()
            identity["usb_bus_path"] = str(parent)
            break
    return identity


def supports_target_mode(formats: str) -> bool:
    mjpg = bool(re.search(r"(?i)(MJPG|Motion-JPEG)", formats))
    size = bool(re.search(r"Size:\s*Discrete\s+2560x720", formats))
    fps = bool(re.search(r"\(60(?:\.0+)?\s*fps\)", formats))
    return mjpg and size and fps


def enumerate_devices() -> tuple[list[dict[str, Any]], str]:
    tool = shutil.which("v4l2-ctl")
    records: list[dict[str, Any]] = []
    raw_sections = []
    for device in sorted(Path("/dev").glob("video*"), key=natural_video_key):
        identity = usb_identity(device)
        if tool:
            _, details = run([tool, "-D", "-d", str(device)])
            _, formats = run([tool, "--list-formats-ext", "-d", str(device)])
        else:
            details = "v4l2-ctl not installed"
            formats = "v4l2-ctl not installed"
        raw_sections.append(f"===== {device} DETAILS =====\n{details}\n===== {device} FORMATS =====\n{formats}\n")
        name_match = re.search(r"Card type\s*:\s*(.+)", details)
        driver_match = re.search(r"Driver name\s*:\s*(.+)", details)
        bus_match = re.search(r"Bus info\s*:\s*(.+)", details)
        capture_capable = bool(re.search(r"Video Capture", details)) and not bool(
            re.search(r"Metadata Capture", details) and not re.search(r"Video Capture\s*\n", details)
        )
        records.append(
            {
                "device": str(device),
                "name": name_match.group(1).strip() if name_match else "unknown",
                "driver": driver_match.group(1).strip() if driver_match else "unknown",
                "bus_info": bus_match.group(1).strip() if bus_match else identity["usb_bus_path"],
                "vid": identity["vid"],
                "pid": identity["pid"],
                "capture_capable": capture_capable,
                "supports_mjpg_2560x720_60": supports_target_mode(formats),
            }
        )
    return records, "\n".join(raw_sections)


def select_recommended(records: list[dict[str, Any]]) -> dict[str, Any] | None:
    candidates = [
        record for record in records
        if record["capture_capable"] and record["supports_mjpg_2560x720_60"]
    ]
    return candidates[0] if len(candidates) == 1 else None


def write_reports(records: list[dict[str, Any]], raw: str, report_dir: Path = REPORT_DIR) -> None:
    report_dir.mkdir(parents=True, exist_ok=True)
    (report_dir / "v4l2_formats_raw.txt").write_text(raw + "\n", encoding="utf-8")
    recommended = select_recommended(records)
    lines = [
        "# Jetson V4L2 Camera Probe",
        "",
        "Target mode: MJPG 2560x720 at 60 FPS.",
        "",
        "| Device | Name | Driver | Bus | VID:PID | Capture | Target mode |",
        "|---|---|---|---|---|---|---|",
    ]
    for record in records:
        lines.append(
            f"| `{record['device']}` | {record['name']} | {record['driver']} | {record['bus_info']} | "
            f"{record['vid'] or '--'}:{record['pid'] or '--'} | {record['capture_capable']} | "
            f"{record['supports_mjpg_2560x720_60']} |"
        )
    lines.extend(["", "## Recommendation", ""])
    if recommended:
        lines.append(
            f"Use `{recommended['device']}` because it is a video-capture node and uniquely advertises MJPG 2560x720 at 60 FPS."
        )
    else:
        matching = [record for record in records if record["supports_mjpg_2560x720_60"]]
        lines.append(
            "No unique automatic recommendation. "
            + ("Multiple target-mode nodes require manual VID/PID and bus selection." if matching else "No node advertised the target mode.")
        )
    (report_dir / "camera_probe_report.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    (report_dir / "camera_probe.json").write_text(json.dumps(records, indent=2), encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description="Probe Jetson V4L2 camera nodes without opening them")
    parser.add_argument("--report-dir", type=Path, default=REPORT_DIR)
    args = parser.parse_args()
    records, raw = enumerate_devices()
    write_reports(records, raw, args.report_dir)
    recommended = select_recommended(records)
    if recommended:
        print(f"RECOMMENDED_DEVICE={recommended['device']}")
        return 0
    print("RECOMMENDED_DEVICE=NONE")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
