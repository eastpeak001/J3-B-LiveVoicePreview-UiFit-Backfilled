# Jetson Depth CPU Baseline Report

- Generated: 2026-06-21T13:32:04
- Status: **PASS**
- Duration: 30.700 s

## Camera and inputs

- Selected camera device: `/dev/video0`
- Camera selected from: camera_probe.json
- GUI enabled/disabled: disabled
- GUI requested: False
- GUI disabled reason: not requested
- Calibration file: `config/calibration_canonical.yaml`
- Maps file: `config/calibration_maps_canonical.npz`
- Canonical order: raw SBS left = physical left; raw SBS right = physical right; swap_left_right=false
- Negotiated mode: `2560x720 MJPG`
- V4L2 reported FPS: 60.000
- OpenCV reported FPS: 60.000
- Latest-frame-only queue size: 1

## Performance

- Capture frames: 1246
- Processed depth frames: 39
- Measured capture FPS: 40.586
- Measured depth FPS: 1.270
- Average processing latency: 782.853 ms
- P95 processing latency: 842.580 ms
- Average end-to-end latency: 794.812 ms
- P95 end-to-end latency: 848.223 ms
- Average SGBM (left+right) time: 597.965 ms
- P95 SGBM (left+right) time: 642.724 ms
- WLS requested/active: True/True
- Acceleration: CPU StereoSGBM; no CUDA/VPI path invoked

## Depth validity

- Mean valid depth pixel ratio: 23.448790%
- Median ROI depth: 1559.976 mm
- Frames with sign check failure: 0
- Median Q/formula relative error: 0.000000066

## System and reliability

- CPU mean/peak: 73.83% / 79.20%
- Memory mean/peak: 30.29% / 30.50%
- Temperature before: `{"cv0-thermal": "unavailable: <read failed: TypeError: can't concat NoneType to bytes>", "cpu-thermal": 48.531, "soc2-thermal": 48.343, "soc0-thermal": 49.312, "cv1-thermal": "unavailable: <read failed: TypeError: can't concat NoneType to bytes>", "gpu-thermal": 49.343, "tj-thermal": 50.031, "soc1-thermal": 50.031, "cv2-thermal": "unavailable: <read failed: TypeError: can't concat NoneType to bytes>"}`
- Temperature after: `{"cv0-thermal": "unavailable: <read failed: TypeError: can't concat NoneType to bytes>", "cpu-thermal": 51.375, "soc2-thermal": 50.218, "soc0-thermal": 50.968, "cv1-thermal": "unavailable: <read failed: TypeError: can't concat NoneType to bytes>", "gpu-thermal": 51.593, "tj-thermal": 52.031, "soc1-thermal": 52.031, "cv2-thermal": "unavailable: <read failed: TypeError: can't concat NoneType to bytes>"}`
- Read failures: 0
- Repeated frames: 0
- Intervals over 100 ms: 0
- P95 capture interval: 25.319 ms
- New USB/kernel error count: 0
- Camera released: True
- Runtime exception: none
