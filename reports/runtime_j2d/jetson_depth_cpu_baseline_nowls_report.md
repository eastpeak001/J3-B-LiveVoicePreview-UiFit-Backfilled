# Jetson Depth CPU Baseline Report

- Generated: 2026-06-21T13:35:49
- Status: **PASS**
- Duration: 30.058 s

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

- Capture frames: 1552
- Processed depth frames: 48
- Measured capture FPS: 51.634
- Measured depth FPS: 1.597
- Average processing latency: 622.771 ms
- P95 processing latency: 639.659 ms
- Average end-to-end latency: 631.306 ms
- P95 end-to-end latency: 649.802 ms
- Average SGBM (left+right) time: 504.387 ms
- P95 SGBM (left+right) time: 515.571 ms
- WLS requested/active: False/False
- Acceleration: CPU StereoSGBM; no CUDA/VPI path invoked

## Depth validity

- Mean valid depth pixel ratio: 23.421755%
- Median ROI depth: 818.476 mm
- Frames with sign check failure: 0
- Median Q/formula relative error: 0.000000062

## System and reliability

- CPU mean/peak: 73.64% / 80.10%
- Memory mean/peak: 30.16% / 30.30%
- Temperature before: `{"cv0-thermal": "unavailable: <read failed: TypeError: can't concat NoneType to bytes>", "cpu-thermal": 49.062, "soc2-thermal": 48.812, "soc0-thermal": 49.781, "cv1-thermal": "unavailable: <read failed: TypeError: can't concat NoneType to bytes>", "gpu-thermal": 49.906, "tj-thermal": 50.5, "soc1-thermal": 50.5, "cv2-thermal": "unavailable: <read failed: TypeError: can't concat NoneType to bytes>"}`
- Temperature after: `{"cv0-thermal": "unavailable: <read failed: TypeError: can't concat NoneType to bytes>", "cpu-thermal": 53.406, "soc2-thermal": 51.718, "soc0-thermal": 52.218, "cv1-thermal": "unavailable: <read failed: TypeError: can't concat NoneType to bytes>", "gpu-thermal": 52.812, "tj-thermal": 53.625, "soc1-thermal": 53.625, "cv2-thermal": "unavailable: <read failed: TypeError: can't concat NoneType to bytes>"}`
- Read failures: 0
- Repeated frames: 0
- Intervals over 100 ms: 0
- P95 capture interval: 19.900 ms
- New USB/kernel error count: 0
- Camera released: True
- Runtime exception: none
