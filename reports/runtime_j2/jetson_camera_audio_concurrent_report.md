# Jetson Camera and USB Microphone Concurrent Report

- Generated: 2026-06-21T12:55:43
- Duration: 60.031 s

## Video

- Selected camera device: `/dev/video0`
- Camera selected from: camera_probe.json
- Warmup frames discarded: 120
- Warmup failures: 0
- Negotiated mode: `{'width': 2560, 'height': 720, 'fourcc': 'MJPG'}`
- OpenCV reported FPS: 60.000
- V4L2 reported FPS: 60.000
- Frames: 2195
- Measured video FPS: 36.564
- Average FPS: 36.564
- P95 frame interval: 28.057 ms
- Read failures: 0
- Repeated frames: 0
- Intervals over 100 ms: 0
- Maximum consecutive failures: 0
- Raw left half: physical left camera; raw right half: physical right camera; no swap.
- Camera released: True

## Audio

- Target VID:PID: `1BCF:2D4F`
- ALSA device: `hw:CARD=RGB,DEV=0`
- Native format: 44100 Hz, 2 channel(s), 16-bit PCM
- Duration: 60.000 s
- Audio frames: 2646000
- arecord overrun/xrun count: 0
- Dropped blocks proxy (overruns): 0
- Possible dropout transitions: 0
- RMS: 0.007758
- Peak: 0.074341
- Clipping ratio: 0.000000%
- 16 kHz mono resampling: `sox`
- ALSA capture process exited and file handles closed: True

## System and USB

- Mean CPU: 17.17%
- Peak CPU: 17.80%
- Mean memory use: 27.70%
- Peak memory use: 27.70%
- Temperature before: `{"cv0-thermal": "unavailable: <read failed: TypeError: can't concat NoneType to bytes>", "cpu-thermal": 49.687, "soc2-thermal": 49.062, "soc0-thermal": 50.0, "cv1-thermal": "unavailable: <read failed: TypeError: can't concat NoneType to bytes>", "gpu-thermal": 50.531, "tj-thermal": 50.781, "soc1-thermal": 50.781, "cv2-thermal": "unavailable: <read failed: TypeError: can't concat NoneType to bytes>"}`
- Temperature after: `{"cv0-thermal": "unavailable: <read failed: TypeError: can't concat NoneType to bytes>", "cpu-thermal": 49.718, "soc2-thermal": 49.281, "soc0-thermal": 50.281, "cv1-thermal": "unavailable: <read failed: TypeError: can't concat NoneType to bytes>", "gpu-thermal": 50.562, "tj-thermal": 51.125, "soc1-thermal": 51.125, "cv2-thermal": "unavailable: <read failed: TypeError: can't concat NoneType to bytes>"}`
- Target USB present after test: True
- New kernel USB errors: 0
