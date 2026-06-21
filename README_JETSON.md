# StereoCameraValidation Jetson J2 Package

This package preserves the J1 stereo-depth preparation and adds J2 read-only USB/ALSA discovery,
native microphone recording, and camera-plus-audio concurrency checks for an NVIDIA Jetson Orin
Nano Super. J2 does not add speech recognition and does not run the depth CPU baseline.

## J2 gated execution order

Run these commands from the extracted package root, one at a time. Review each report and proceed
only after the previous step passes:

```bash
python3 scripts/verify_deployment_assets.py
bash tools/jetson_preflight.sh
bash tools/run_camera_probe.sh
bash tools/run_audio_probe.sh
bash tools/run_capture_smoke_test.sh
bash tools/run_audio_record_test.sh
bash tools/run_camera_audio_concurrent_test.sh
```

Any missing tool, ambiguous device, unexpected format, USB disconnect, or capture error is a stop
condition. The scripts do not run `apt install`, `pip install`, `amixer set`, or any other system
modification. If shell executable bits were not preserved by ZIP extraction, run
`chmod +x tools/*.sh` once before the sequence.

## J2 USB microphone identity

- Required USB VID/PID: `1BCF:2D4F`.
- Expected product names include `USB2.0 Camera RGB`, `USB Camera`, or `USB Audio`.
- A name match alone is insufficient. The audio probe traces the ALSA card through sysfs to the
  exact USB VID/PID and records the USB bus path.
- ALSA card numbers are not stable. Recording uses the probed card ID/device and never hard-codes
  `hw:1,0`.
- Windows observed native/default audio as signed 16-bit PCM, 44.1 kHz stereo. Jetson capabilities
  must be measured again with `arecord --dump-hw-params`.

The audio probe records `lsusb`, `arecord -l/-L`, `/proc/asound`, PipeWire/PulseAudio state,
membership of the `audio` group, and read-only `amixer` output. It never changes capture volume.
If clipping is materially above the Windows reference of `0.006944%`, report it and wait for manual
approval before changing any mixer setting.

The 10-second audio test saves the native WAV and a 16 kHz mono signed-16-bit copy. Resampling uses
an already-installed `ffmpeg` or `sox`; otherwise it falls back to NumPy. It records the five Chinese
test phrases but performs no recognition.

The 60-second concurrency test automatically selects the unique V4L2 node advertising MJPG
2560x720 at 60 FPS, discards 120 frames, captures without SGBM/WLS/depth, and simultaneously records
the confirmed USB microphone. The raw SBS left half remains physical left and the right half remains
physical right; no swap or mirror is applied.

## Frozen validation scope

- Validated metric range: approximately 0.3 to 0.8 m.
- Distances above 1 m have not received reliable metrology validation. No accuracy claim is made there.
- Raw SBS left half is the physical left camera.
- Raw SBS right half is the physical right camera.
- `swap_left_right` must remain `false`.
- Never import the old Windows capture setting `swap_left_right: true`.
- Canonical calibration and maps are checked against `reports/windows_source_manifest.sha256` before depth starts.

## Important OpenCV rule

Use the OpenCV supplied by the JetPack/system environment until preflight results are reviewed. Do not run:

```text
pip install --upgrade opencv-python
pip install --upgrade opencv-contrib-python
```

Those commands can replace NVIDIA's OpenCV build. If `cv2.ximgproc` is unavailable, WLS is disabled automatically and Raw StereoSGBM remains usable. StereoSGBM in this package is explicitly a CPU baseline; it is not claimed to use CUDA.

## Original J1 first three commands

From the extracted package root:

```bash
python3 scripts/verify_deployment_assets.py
bash tools/jetson_preflight.sh
bash tools/run_camera_probe.sh
```

Review the generated reports before opening the camera. The preflight is read-only and never installs packages, changes power modes, or enables clocks. It uses non-interactive sudo queries; run `sudo -v` first only if you want privileged read-only nvpmodel and jetson_clocks output included.

## 60-second camera smoke test

Use the recommended device printed by the camera probe:

```bash
bash tools/run_capture_smoke_test.sh /dev/videoX
```

Equivalent direct command:

```bash
python3 scripts/jetson_capture_smoke_test.py --device /dev/videoX --duration 60
```

The test requests MJPG 2560x720 at 60 FPS, discards 120 warmup frames, checks the negotiated mode, records failures/repeats/stalls, and saves one raw SBS plus its physical left and right halves. It does not rectify or calculate depth.

## CPU depth baseline

After asset verification, preflight, camera probing, and the smoke test pass:

```bash
bash tools/run_depth_cpu_baseline.sh /dev/videoX
```

Headless example:

```bash
bash tools/run_depth_cpu_baseline.sh /dev/videoX --no-gui --duration 60
```

The runtime performs canonical rectification before disparity, uses the validated SGBM parameters, optionally applies WLS, filters invalid disparity, reprojects with Q in millimetres, reports the fixed ROI median, and applies a short temporal median with outlier rejection. Capture FPS and depth FPS are reported separately. A queue of length one keeps only the newest camera frame.

## Power modes

J1 only records current power configuration. It does not switch modes and does not hard-code nvpmodel IDs. The first functional baseline should use the board's documented 25 W mode after manual confirmation. MAXN SUPER comparison belongs to a later performance phase.

## Reports

- `reports/jetson_preflight_report.md`
- `reports/jetson_preflight_raw.txt`
- `reports/opencv_build_information.txt`
- `reports/camera_probe_report.md`
- `reports/v4l2_formats_raw.txt`
- `reports/jetson_capture_smoke_report.md`
- `reports/jetson_audio_probe_report.md`
- `reports/jetson_audio_probe_raw.txt`
- `reports/jetson_audio_record_report.md`
- `reports/jetson_camera_audio_concurrent_report.md`

Do not treat those reports as present or passing until they have been generated on the Jetson itself.

## Troubleshooting and log collection

1. Save terminal output with `command 2>&1 | tee reports/name.log`.
2. If no camera is recommended, inspect `v4l2_formats_raw.txt`, VID/PID, bus path, and all nodes exposed by the same UVC device.
3. If the requested format is not negotiated, stop before depth and report the actual width, height, FPS, and FOURCC.
4. If ximgproc is absent, confirm the log says WLS is disabled and Raw SGBM initialized.
5. If GUI initialization fails, use `--no-gui`; headless support does not change the depth algorithm.
6. Missing tools are recorded by preflight. Do not install or replace system components until the report is reviewed.

## Safe exit

- GUI: press `Q` or `Esc`.
- Headless: press `Ctrl+C`.
- Both paths stop the capture thread, join it, release `cv2.VideoCapture`, and destroy OpenCV windows.

If shell scripts are not executable after ZIP extraction, run:

```bash
chmod +x tools/*.sh
```

## J2.1 hardware validation status

Jetson J2 hardware validation passed. The deployment asset check, preflight,
camera probe, audio probe, camera smoke test, audio recording test, and the
camera-plus-audio concurrent test all completed successfully on the target.

The confirmed minimum host packages are:

- `python3-opencv`
- `python3-numpy`
- `python3-psutil`
- `v4l-utils`
- `alsa-utils`
- `sox`

The camera node must be selected from `reports/runtime_j2/camera_probe.json` at
runtime. `/dev/video0` is the recommended node on the validated unit, but this
device path must not be treated as universal or permanently hard-coded for all
Jetson systems.

The V4L2 device and OpenCV both reported MJPG 2560x720 at 60 FPS. During the
60-second Python/OpenCV camera-and-audio concurrent test, decoded video ran at
36.564 FPS with no failed reads, repeated frames, or stalls over 100 ms. This
approximately 36.5-37 FPS result is an expected software MJPG decode throughput
limit for this test path, and J2 is classified as stable and passing. Future
real-time depth capture must use latest-frame-only processing rather than queue
and process every camera frame.

The ALSA microphone `hw:CARD=RGB,DEV=0` is usable at its native 44100 Hz,
two-channel format and can be converted to 16 kHz mono with SoX. The 60-second
concurrent test recorded no xrun, dropout, clipping, target USB disconnect, or
new kernel USB error.

Whisper, sherpa-onnx, Vosk, and other speech-recognition models are not included
or installed. At the J2.1 checkpoint, the Jetson depth CPU baseline had not yet
been run.

## J2-D and J2-D2 depth CPU baseline

The canonical Jetson depth path has now completed its first hardware CPU
baseline. Both runs used the validated physical camera order, canonical maps,
positive disparity convention, and a latest-frame-only capture queue.

CPU StereoSGBM with WLS processed depth at approximately 1.27 FPS. Mean
processing latency was approximately 783 ms. CPU Raw StereoSGBM with WLS
disabled processed depth at approximately 1.60 FPS with mean processing latency
of approximately 623 ms.

The no-WLS run was approximately 25.7% faster than the WLS run, while the mean
valid depth ratio was effectively unchanged at approximately 23.4%. Both runs
completed without camera read failures, repeated frames, capture stalls over
100 ms, new USB errors, or camera-release failures.

The CPU baseline proves that the canonical depth chain is functionally viable,
but it is not suitable for high-frame-rate real-time depth at the current full
resolution. The next real-time implementation should:

- retain latest-frame-only capture;
- use Raw SGBM/no-WLS by default;
- keep WLS as an optional display enhancement;
- design the UI around a deliberately low depth refresh rate;
- evaluate ROI processing, lower resolution, parameter tuning, and later
  CUDA/VPI acceleration separately.

J3 fixed-command offline speech recognition may proceed, but audio capture and
recognition must never block the camera capture or depth-processing threads.

## J3-A offline Chinese fixed-command ASR

J3-A adds an isolated WAV-file validation path using Vosk. It is fully offline:
no network speech service, Whisper model, hardware control, or depth-loop change
is included. The accepted command phrases are defined in
`config/asr_commands_zh.yaml` and currently cover:

- `开始测距` (`start_depth`)
- `暂停测距` or `关闭测距` (`stop_depth`)
- `保存画面` (`save_frame`)
- `显示深度` (`show_depth`)
- `退出程序` (`exit_program`)

Install the small Python runtime dependency from the deployment requirements:

```bash
python3 -m pip install -r requirements-jetson.txt
```

Place a separately obtained Vosk Chinese model at the configured local path,
which defaults to `models/asr/vosk-model-small-cn-0.22/`. The model is not part
of this source package and is never downloaded automatically. See
`models/asr/README_ASR_MODEL.md` for the expected layout.

Run one WAV through the fixed-command test:

```bash
bash tools/run_asr_offline_fixed_command_test.sh /path/to/input.wav
```

On the validated Jetson, record from the USB camera microphone with
`plughw:0,0` (or the equivalent `plughw:CARD=RGB,DEV=0` name discovered by the
audio probe). The generic `default` ALSA device may select a different source
and can produce a silent recording.

Chinese fixed-command recognition uses open Vosk decoding by default:

```python
KaldiRecognizer(model, sample_rate)
```

The recognized text is normalized by removing whitespace, punctuation, and
`[unk]`, then matched in this order: exact phrase, contained phrase, and all
configured keywords. This allows text such as `新车 二 车 开始 测距` to match
`start_depth` while unrelated speech remains unknown. Each command's fallback
keywords are defined alongside its phrase in `config/asr_commands_zh.yaml`.
For the primary `stop_depth` phrases, use `暂停测距` or `关闭测距`. Jetson field
tests found `停止测距` and `结束测距` less stable; J3-B keeps `停止测距` only as
an additional fallback alias. A bare `测距` never triggers the stop command.
Only the five safe software commands `start_depth`, `stop_depth`, `save_frame`,
`show_depth`, and `exit_program` are enabled in J3-A. Future commands may be
listed with `enabled: false`; disabled commands are excluded from both matching
and optional grammar construction. Pan/tilt, robotic-arm, grasping, and movement
commands are not enabled or implemented.

Vosk grammar mode remains available only as an explicit diagnostic option:

```bash
bash tools/run_asr_offline_fixed_command_test.sh /path/to/input.wav --grammar
```

Some Chinese models report `Ignoring word missing in vocabulary` when complete
Chinese command phrases are supplied as grammar entries. For this reason,
grammar mode is not the default J3-A path. The matcher can be tested without a
Vosk model or WAV file:

```bash
python3 scripts/jetson_asr_matcher_self_test.py
```

The test accepts any WAV format readable by the existing audio helper. Input
that is not 16 kHz mono signed 16-bit PCM is converted into a temporary WAV via
`jetson_audio_common.resample_to_16k`; the temporary audio is removed after the
test. Results are written to:

- `reports/runtime_j3/jetson_asr_offline_fixed_command.json`
- `reports/runtime_j3/jetson_asr_offline_fixed_command_report.md`

The JSON result contains the recognition mode, raw recognized text, matched
`command_id`, matched phrase, `unknown` status, audio duration, and processing time. Missing Vosk
packages or model files produce explicit local errors and never trigger a
download. This single-file test keeps recognition separate from depth runtime;
a later concurrent implementation must use a bounded queue or latest-item state
so ASR cannot block camera capture or depth processing.

## J3-B live fixed commands and local camera preview

J3-B validates live microphone command events while independently reading the
camera for a local preview. It reuses the J3-A Vosk open-recognition path and
OpenMatch matcher. It does not run SGBM, WLS, depth processing, a network speech
service, or any hardware-control command.

### J3-B NumPy and OpenCV compatibility

The validated Jetson system OpenCV 4.5.4 build requires NumPy 1.x. Keep the
deployment requirement at `numpy>=1.24,<2`; installing NumPy 2.x can make
`import cv2` fail with `_ARRAY_API not found` or
`ImportError: numpy.core.multiarray failed to import`. Repair that environment
without replacing the JetPack OpenCV build:

```bash
python3 -m pip install --user --force-reinstall "numpy<2"
```

The validated USB microphone should be opened through `plughw:0,0` by default:

```bash
bash tools/run_asr_live_command_test.sh \
  --audio-device plughw:0,0 --duration 60
```

The generic ALSA `default` device may select the wrong source and can record
silence. Live command events are limited to the five enabled safe software
commands in `config/asr_commands_zh.yaml`; unknown speech emits no command.
The default per-command cooldown is 800 ms.

Run microphone recognition with the J2-probed camera preview:

```bash
bash tools/run_camera_preview_voice_test.sh \
  --camera-index 0 \
  --audio-device plughw:0,0 \
  --duration 60 \
  --display-window \
  --window-width 960 \
  --window-height 540 \
  --fit-window \
  --overlay-scale 0.6
```

The camera defaults to the unique MJPG 2560x720@60 node recorded in
`reports/runtime_j2/camera_probe.json`. Use `--camera-index N` to override it.
The preview overlays average FPS, the latest recognition state, command ID, and
runtime. Press `q`, say the enabled `exit_program` phrase, or press `Ctrl+C` to
exit safely.

The default fit mode preserves aspect ratio and adds black letterbox areas when
needed, so the full preview and overlay remain visible on the Jetson display.
For a smaller screen, show only the physical-left half of the SBS frame:

```bash
bash tools/run_camera_preview_voice_test.sh \
  --camera-index 0 --audio-device plughw:0,0 --duration 60 \
  --display-window --window-width 800 --window-height 450 \
  --fit-window --overlay-scale 0.6 --left-view-only
```

J3-B accepts the original five safe commands plus conservative speech aliases:
`启动测距`, `打开测距`, `停止测距`, `保存图片`, `拍照保存`, `查看深度`,
`打开深度`, `结束程序`, and `关闭程序`. A bare `测距`, `瓶子测距`, and
unrelated speech remain unknown and never emit command events. No pan/tilt,
robotic-arm, grasping, movement, or navigation command is configured.

A local window requires `DISPLAY` or `WAYLAND_DISPLAY`. For SSH or other
headless sessions, use:

```bash
bash tools/run_camera_preview_voice_test.sh --no-window --duration 60
```

If display access is unavailable while window mode was requested, the script
reports the condition and continues headless. ASR and camera handling are
independent: an ASR failure does not terminate camera preview, and a camera-open
failure does not terminate ASR. Runtime reports are written under
`reports/runtime_j3b/`. J3-B only validates real-time command events and camera
preview; it does not alter the J3-A offline test or the default depth runtime.

## ZIP permissions on Jetson

Jetson deployment ZIP files must be built with `tools/package_jetson_deployment.py`.
The packager writes explicit Unix metadata: directories and `tools/*.sh` use
mode `0755`, while regular files use `0644`. It then verifies every member and
the explicit `models/asr/` directory entry before accepting the ZIP. Do not use
Windows `Compress-Archive` for release packages because it does not reliably
preserve Linux directory execute permissions.

After extracting on Jetson, these commands safely repair permissions if the
archive was processed by another ZIP tool:

```bash
find . -type d -exec chmod u+rwx,g+rx,o+rx {} \;
find tools -type f -name "*.sh" -exec chmod u+x {} \;
```

The first command restores traversal and owner-write access, allowing the Vosk
model directory to be created under `models/asr/`. The second guarantees that
all launch scripts are executable by the current user.
