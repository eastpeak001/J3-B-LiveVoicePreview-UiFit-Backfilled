from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path
from time import perf_counter
from typing import Any

import cv2
import numpy as np
import yaml

PACKAGE_ROOT = Path(__file__).resolve().parents[1]


@dataclass
class DepthFrame:
    rectified_left: np.ndarray
    rectified_right: np.ndarray
    disparity_raw_fixed: np.ndarray
    disparity_raw_px: np.ndarray
    disparity_wls_fixed: np.ndarray | None
    disparity_wls_px: np.ndarray | None
    active_disparity_px: np.ndarray
    consistency_mask: np.ndarray
    valid_disparity_mask: np.ndarray
    points_3d: np.ndarray
    depth_mm: np.ndarray
    valid_depth_mask: np.ndarray
    sign_ok: bool
    sign_stats: dict[str, float]
    q_formula_relative_error: float
    timings_ms: dict[str, float]


def load_runtime_config(path: Path) -> dict[str, Any]:
    config = yaml.safe_load(path.read_text(encoding="utf-8"))
    if config.get("profile") != "jetson_canonical_physical_order":
        raise ValueError("depth runtime profile must be jetson_canonical_physical_order")
    layout = config["raw_layout"]
    expected = {
        "mode": "horizontal_sbs",
        "left_half_is_physical_left": True,
        "right_half_is_physical_right": True,
        "swap_left_right": False,
        "mirror_horizontal": False,
        "mirror_vertical": False,
    }
    if layout != expected:
        raise ValueError(f"Unsafe raw layout configuration: {layout}")
    validate_sgbm(config["sgbm"])
    return config


def resolve_project_path(value: str | Path) -> Path:
    path = Path(value)
    return path if path.is_absolute() else PACKAGE_ROOT / path


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def validate_frozen_inputs() -> None:
    manifest = PACKAGE_ROOT / "reports" / "windows_source_manifest.sha256"
    required = {
        "config/calibration_canonical.yaml": PACKAGE_ROOT / "config" / "calibration_canonical.yaml",
        "config/calibration_maps_canonical.npz": PACKAGE_ROOT / "config" / "calibration_maps_canonical.npz",
    }
    expected_hashes: dict[str, str] = {}
    for line in manifest.read_text(encoding="utf-8").splitlines():
        expected, relative = line.split(" *", 1)
        expected_hashes[relative] = expected
    for relative, path in required.items():
        expected = expected_hashes.get(relative)
        if expected is None:
            raise RuntimeError(f"Frozen hash missing from manifest: {relative}")
        actual = sha256_file(path)
        if actual != expected:
            raise RuntimeError(f"Canonical input hash changed: {relative}")


def validate_sgbm(params: dict[str, Any]) -> None:
    number = int(params["num_disparities"])
    block = int(params["block_size"])
    if number <= 0 or number % 16:
        raise ValueError("num_disparities must be a positive multiple of 16")
    if block < 3 or block % 2 == 0:
        raise ValueError("block_size must be odd and at least 3")


def sgbm_mode(name: str) -> int:
    modes = {
        "SGBM": cv2.STEREO_SGBM_MODE_SGBM,
        "HH": cv2.STEREO_SGBM_MODE_HH,
        "SGBM_3WAY": cv2.STEREO_SGBM_MODE_SGBM_3WAY,
        "HH4": cv2.STEREO_SGBM_MODE_HH4,
    }
    try:
        return modes[name.upper()]
    except KeyError as exc:
        raise ValueError(f"Unsupported StereoSGBM mode: {name}") from exc


class StereoDepthProcessor:
    def __init__(self, config: dict[str, Any], allow_ximgproc: bool = True):
        validate_frozen_inputs()
        self.config = config
        calibration_path = resolve_project_path(config["calibration"]["yaml"])
        maps_path = resolve_project_path(config["calibration"]["maps"])
        self.calibration = yaml.safe_load(calibration_path.read_text(encoding="utf-8"))
        if not self.calibration.get("candidate_valid"):
            raise RuntimeError("Canonical calibration is not marked valid")
        maps = np.load(maps_path)
        self.map1_left = maps["map1_left"]
        self.map2_left = maps["map2_left"]
        self.map1_right = maps["map1_right"]
        self.map2_right = maps["map2_right"]
        self.Q = np.asarray(maps["Q"], dtype=np.float64)
        self.focal_length_px = float(self.calibration["P1"][0][0])
        self.baseline_mm = float(self.calibration["baseline_mm"])
        self.roi_mask = self._build_roi_mask()
        self.ximgproc_available = bool(
            allow_ximgproc
            and
            hasattr(cv2, "ximgproc")
            and hasattr(cv2.ximgproc, "createRightMatcher")
            and hasattr(cv2.ximgproc, "createDisparityWLSFilter")
        )
        self.wls_enabled = bool(config["wls"]["enabled"] and self.ximgproc_available)
        self.active_wls = self.wls_enabled
        self.left_matcher = None
        self.right_matcher = None
        self.wls_filter = None
        self._matcher_signature: tuple[Any, ...] | None = None
        self.rebuild_matchers()

    def _build_roi_mask(self) -> np.ndarray:
        height = int(self.calibration["image_height"])
        width = int(self.calibration["image_width"])
        mask = np.zeros((height, width), dtype=bool)
        left_roi = self.calibration["valid_roi_left"]
        right_roi = self.calibration["valid_roi_right"]
        x0 = max(int(left_roi[0]), int(right_roi[0]))
        y0 = max(int(left_roi[1]), int(right_roi[1]))
        x1 = min(int(left_roi[0] + left_roi[2]), int(right_roi[0] + right_roi[2]), width)
        y1 = min(int(left_roi[1] + left_roi[3]), int(right_roi[1] + right_roi[3]), height)
        if x1 <= x0 or y1 <= y0:
            raise RuntimeError("Canonical valid ROIs do not overlap")
        mask[y0:y1, x0:x1] = True
        return mask

    def current_signature(self) -> tuple[Any, ...]:
        p = self.config["sgbm"]
        w = self.config["wls"]
        return (
            int(p["min_disparity"]),
            int(p["num_disparities"]),
            int(p["block_size"]),
            int(p["uniqueness_ratio"]),
            int(p["speckle_window_size"]),
            int(p["speckle_range"]),
            int(p["disp12_max_diff"]),
            int(p["pre_filter_cap"]),
            str(p["mode"]),
            float(w["lambda"]),
            float(w["sigma_color"]),
        )

    def rebuild_matchers(self) -> None:
        validate_sgbm(self.config["sgbm"])
        signature = self.current_signature()
        if signature == self._matcher_signature:
            return
        p = self.config["sgbm"]
        block = int(p["block_size"])
        channels = 1
        self.left_matcher = cv2.StereoSGBM_create(
            minDisparity=int(p["min_disparity"]),
            numDisparities=int(p["num_disparities"]),
            blockSize=block,
            P1=8 * channels * block * block,
            P2=32 * channels * block * block,
            disp12MaxDiff=int(p["disp12_max_diff"]),
            preFilterCap=int(p["pre_filter_cap"]),
            uniquenessRatio=int(p["uniqueness_ratio"]),
            speckleWindowSize=int(p["speckle_window_size"]),
            speckleRange=int(p["speckle_range"]),
            mode=sgbm_mode(str(p["mode"])),
        )
        if self.ximgproc_available:
            self.right_matcher = cv2.ximgproc.createRightMatcher(self.left_matcher)
            self.wls_filter = cv2.ximgproc.createDisparityWLSFilter(self.left_matcher)
            self.wls_filter.setLambda(float(self.config["wls"]["lambda"]))
            self.wls_filter.setSigmaColor(float(self.config["wls"]["sigma_color"]))
        else:
            self.right_matcher = None
            self.wls_filter = None
            self.wls_enabled = False
            self.active_wls = False
        self._matcher_signature = signature

    @staticmethod
    def split_raw(raw_frame: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
        if raw_frame is None or raw_frame.shape[:2] != (720, 2560):
            raise ValueError(f"Expected raw 2560x720 frame, got {None if raw_frame is None else raw_frame.shape}")
        physical_left = raw_frame[:, :1280]
        physical_right = raw_frame[:, 1280:]
        return physical_left, physical_right

    def rectify(self, raw_frame: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
        physical_left, physical_right = self.split_raw(raw_frame)
        left = cv2.remap(physical_left, self.map1_left, self.map2_left, cv2.INTER_LINEAR)
        right = cv2.remap(physical_right, self.map1_right, self.map2_right, cv2.INTER_LINEAR)
        return left, right

    def _consistency_mask(self, left_px: np.ndarray, right_px: np.ndarray | None) -> np.ndarray:
        if right_px is None:
            return np.ones(left_px.shape, dtype=bool)
        height, width = left_px.shape
        yy, xx = np.indices((height, width))
        right_x = np.rint(xx - left_px).astype(np.int32)
        in_bounds = (right_x >= 0) & (right_x < width)
        sampled = np.full(left_px.shape, np.nan, dtype=np.float32)
        sampled[in_bounds] = right_px[yy[in_bounds], right_x[in_bounds]]
        threshold = float(self.config["consistency"]["maximum_difference_px"])
        return in_bounds & np.isfinite(sampled) & (np.abs(left_px + sampled) <= threshold)

    def process(
        self,
        raw_frame: np.ndarray,
        use_wls: bool | None = None,
        compute_wls: bool = True,
    ) -> DepthFrame:
        self.rebuild_matchers()
        total_start = perf_counter()
        rectify_start = perf_counter()
        rectified_left, rectified_right = self.rectify(raw_frame)
        rectify_ms = (perf_counter() - rectify_start) * 1000.0
        gray_left = cv2.cvtColor(rectified_left, cv2.COLOR_BGR2GRAY)
        gray_right = cv2.cvtColor(rectified_right, cv2.COLOR_BGR2GRAY)

        sgbm_start = perf_counter()
        disparity_raw_fixed = self.left_matcher.compute(gray_left, gray_right)
        disparity_raw_px = disparity_raw_fixed.astype(np.float32) / 16.0
        disparity_right_fixed = None
        disparity_right_px = None
        if self.right_matcher is not None:
            disparity_right_fixed = self.right_matcher.compute(gray_right, gray_left)
            disparity_right_px = disparity_right_fixed.astype(np.float32) / 16.0
        sgbm_ms = (perf_counter() - sgbm_start) * 1000.0

        wls_start = perf_counter()
        disparity_wls_fixed = None
        disparity_wls_px = None
        if compute_wls and self.wls_filter is not None and disparity_right_fixed is not None:
            disparity_wls_fixed = self.wls_filter.filter(
                disparity_raw_fixed,
                gray_left,
                None,
                disparity_right_fixed,
            )
            disparity_wls_px = disparity_wls_fixed.astype(np.float32) / 16.0
        wls_ms = (perf_counter() - wls_start) * 1000.0

        consistency = self._consistency_mask(disparity_raw_px, disparity_right_px)
        use_filtered = self.active_wls if use_wls is None else bool(use_wls)
        active = (
            disparity_wls_px
            if use_filtered and disparity_wls_px is not None
            else disparity_raw_px
        )
        p = self.config["sgbm"]
        min_disparity = float(p["min_disparity"])
        maximum = min_disparity + float(p["num_disparities"])
        finite_disparity = np.isfinite(active)
        valid_disparity = (
            finite_disparity
            & (active > min_disparity)
            & (active < maximum)
            & consistency
            & self.roi_mask
        )

        positive_count = int(np.count_nonzero(disparity_raw_px > min_disparity))
        # StereoSGBM marks invalid pixels as min_disparity - 1. Exclude that
        # sentinel from the sign check instead of misclassifying it as geometry.
        negative_count = int(np.count_nonzero(disparity_raw_px < min_disparity - 1.0))
        sign_values = disparity_raw_px[(disparity_raw_px > min_disparity) & self.roi_mask]
        median_sign = float(np.median(sign_values)) if sign_values.size else float("nan")
        positive_ratio = positive_count / max(positive_count + negative_count, 1)
        sign_ok = bool(
            sign_values.size >= 100
            and median_sign > 0
            and positive_ratio >= 0.8
        )
        sign_stats = {
            "median_positive_disparity_px": median_sign,
            "positive_count": float(positive_count),
            "negative_count": float(negative_count),
            "positive_ratio": float(positive_ratio),
        }

        reproject_start = perf_counter()
        safe_disparity = active.copy()
        safe_disparity[~valid_disparity] = np.nan
        points_3d = cv2.reprojectImageTo3D(safe_disparity, self.Q)
        depth_mm = points_3d[:, :, 2].astype(np.float32)
        depth_config = self.config["depth"]
        valid_depth = (
            valid_disparity
            & np.isfinite(depth_mm)
            & (depth_mm > float(depth_config["minimum_mm"]))
            & (depth_mm < float(depth_config["maximum_mm"]))
        )
        formula_depth = np.full(active.shape, np.nan, dtype=np.float32)
        formula_depth[valid_disparity] = (
            self.focal_length_px * self.baseline_mm / active[valid_disparity]
        )
        compare = valid_depth & np.isfinite(formula_depth) & (formula_depth > 0)
        if np.count_nonzero(compare):
            relative = np.abs(depth_mm[compare] - formula_depth[compare]) / formula_depth[compare]
            q_formula_error = float(np.median(relative))
        else:
            q_formula_error = float("nan")
        if np.isfinite(q_formula_error) and q_formula_error > 1e-3:
            valid_depth[:] = False
            sign_ok = False
        if not sign_ok:
            valid_depth[:] = False
        reproject_ms = (perf_counter() - reproject_start) * 1000.0
        total_ms = (perf_counter() - total_start) * 1000.0
        return DepthFrame(
            rectified_left=rectified_left,
            rectified_right=rectified_right,
            disparity_raw_fixed=disparity_raw_fixed,
            disparity_raw_px=disparity_raw_px,
            disparity_wls_fixed=disparity_wls_fixed,
            disparity_wls_px=disparity_wls_px,
            active_disparity_px=active,
            consistency_mask=consistency,
            valid_disparity_mask=valid_disparity,
            points_3d=points_3d,
            depth_mm=depth_mm,
            valid_depth_mask=valid_depth,
            sign_ok=sign_ok,
            sign_stats=sign_stats,
            q_formula_relative_error=q_formula_error,
            timings_ms={
                "rectify": rectify_ms,
                "sgbm_and_right": sgbm_ms,
                "wls": wls_ms,
                "reproject_and_filter": reproject_ms,
                "total": total_ms,
            },
        )


def disparity_visual(disparity: np.ndarray | None, valid: np.ndarray, maximum: float) -> np.ndarray:
    if disparity is None:
        return np.zeros((*valid.shape, 3), dtype=np.uint8)
    normalized = np.zeros(disparity.shape, dtype=np.uint8)
    clipped = np.clip(disparity, 0, maximum)
    normalized[valid] = np.asarray(clipped[valid] / maximum * 255.0, dtype=np.uint8)
    color = cv2.applyColorMap(normalized, cv2.COLORMAP_TURBO)
    color[~valid] = 0
    return color


def depth_visual(depth_mm: np.ndarray, valid: np.ndarray, minimum: float, maximum: float) -> np.ndarray:
    normalized = np.zeros(depth_mm.shape, dtype=np.uint8)
    inverse_min = 1.0 / maximum
    inverse_max = 1.0 / minimum
    inverse = np.zeros_like(depth_mm, dtype=np.float32)
    inverse[valid] = 1.0 / depth_mm[valid]
    scaled = (inverse - inverse_min) / (inverse_max - inverse_min)
    normalized[valid] = np.asarray(np.clip(scaled[valid], 0, 1) * 255.0, dtype=np.uint8)
    color = cv2.applyColorMap(normalized, cv2.COLORMAP_TURBO)
    color[~valid] = 0
    return color


def measure_neighborhood(frame: DepthFrame, x: int, y: int, config: dict[str, Any]) -> dict[str, Any]:
    size = int(config["measurement"]["window_size"])
    half = size // 2
    height, width = frame.depth_mm.shape
    x0, x1 = max(0, x - half), min(width, x + half + 1)
    y0, y1 = max(0, y - half), min(height, y + half + 1)
    mask = frame.valid_depth_mask[y0:y1, x0:x1]
    points = frame.points_3d[y0:y1, x0:x1][mask]
    depths = frame.depth_mm[y0:y1, x0:x1][mask]
    required = int(config["measurement"]["minimum_valid_pixels"])
    if len(depths) < required:
        return {
            "valid": False,
            "x": x,
            "y": y,
            "valid_pixels": int(len(depths)),
            "required_pixels": required,
            "message": "该位置纹理不足或视差无效，请点击其他位置",
        }
    median_xyz = np.median(points, axis=0)
    median_z = float(np.median(depths))
    mad = float(np.median(np.abs(depths - median_z)))
    return {
        "valid": True,
        "x": x,
        "y": y,
        "window_size": size,
        "valid_pixels": int(len(depths)),
        "X_mm": float(median_xyz[0]),
        "Y_mm": float(median_xyz[1]),
        "Z_mm": median_z,
        "distance_3d_mm": float(np.linalg.norm(median_xyz)),
        "depth_mad_mm": mad,
    }


def fixed16_png(disparity_px: np.ndarray | None, valid: np.ndarray) -> np.ndarray:
    result = np.zeros(valid.shape, dtype=np.uint16)
    if disparity_px is not None:
        result[valid] = np.asarray(np.clip(disparity_px[valid] * 16.0, 0, 65535), dtype=np.uint16)
    return result
