# Windows J2 Static Validation

Generated on 2026-06-20. This records Windows-side static and simulated checks only. It is not a
Jetson runtime report and does not claim that ALSA, V4L2, USB concurrency, thermals, or kernel logs
have passed on the board.

## Passed checks

- Python `compileall`: PASS for all files under `scripts/`.
- Frozen deployment assets and Canonical hashes: PASS.
- Missing `arecord`: exits 3 with a clear stop message and installs nothing.
- Missing target microphone: exits 4 and refuses fallback to another device.
- Synthetic ALSA/sysfs topology: only the card whose USB parent is `1BCF:2D4F` is selected.
- Synthetic non-target topology: zero recording candidates are returned.
- ALSA capability parser: S16_LE, 8-48 kHz, 1-2 channels selects 44.1 kHz stereo.
- NumPy-only fallback: 44.1 kHz stereo PCM becomes exactly 16 kHz mono 16-bit PCM.
- Windows absolute path and forbidden automatic-install/mixer-command scans: PASS.
- Seven shell files passed shebang, LF-ending, strict-mode, and balanced-quoting checks.
- `pip check`: PASS in the Windows validation environment.

## Host limitation

Windows has the WSL launcher but no installed Linux distribution, and no Git Bash/MSYS bash was
present. A native `bash -n` run was therefore unavailable. The first Jetson execution must still
run the scripts with the board's Bash.

## Deliberately not executed on Windows

- No real ALSA, `arecord`, `amixer`, PipeWire/PulseAudio, or Jetson V4L2 probe.
- No Jetson recording or camera/audio concurrency test.
- No Jetson runtime report was pre-generated or marked passing.
- No installation, mixer change, depth baseline, speech model, or command recognition.
