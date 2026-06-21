# Jetson J3-B Patch 1 Runtime Validation

- Runtime archive: `StereoCameraValidation_Jetson_J3B_UiFit_Runtime_Result.tar.gz`
- Runtime archive SHA-256: `99D2396021211C305A16A963278E50814EAA6AB8A8D8FFE96478281825B5B9AD`
- Overall result: **PASS**

## Display and camera

- J3-B `display-window` opened successfully on the Jetson local display.
- The 800x450 fit-window configuration was active.
- `left-view-only` displayed the single left view correctly.
- Camera `/dev/video0` opened successfully.
- The captured runtime report records 146 frames at an average 28.393 FPS.
- The earlier J3-B `--no-window` test also passed.

## Runtime compatibility

- The validated environment used NumPy 1.26.4 with system OpenCV `cv2` 4.5.4.
- The NumPy 1.x compatibility repair was effective.
- The deployment requirement remains `numpy>=1.24,<2` to avoid the NumPy 2.x
  `_ARRAY_API` and `numpy.core.multiarray` import failures.

## Live ASR

- Live ASR emitted a valid command event during the returned display test.
- The archived JSON records recognition of `关闭 程序` as `exit_program`.
- Vosk small Chinese can trigger the configured safe commands, but short-command
  stability is only moderate and may require repeated speech.
- A later J3-B2 keyword-spotting comparison is recommended before treating voice
  commands as a high-reliability control interface.
- This result does not add J3-C concurrency, depth processing, pan/tilt,
  robotic-arm, grasping, or movement control.

## Archived evidence

- `jetson_camera_preview_voice.json`
- `jetson_camera_preview_voice_report.md`

No Vosk model, WAV, image, screenshot, cache, or private runtime sample is
included in this backfill.
