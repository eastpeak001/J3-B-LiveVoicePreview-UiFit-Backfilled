# Jetson J3-A Offline Fixed Command ASR Report

- Generated: 2026-06-21T16:18:26
- Status: **PASS**
- Input WAV: `/home/pinggu_auar/asr_test_wavs/test_unknown_usb.wav`
- Model path: `/home/pinggu_auar/StereoCameraValidation_Jetson/J3A_commandtune_test/StereoCameraValidation_Jetson_J3_A_CommandTune_Package/models/asr/vosk-model-small-cn-0.22`
- Resampling: not_required
- Recognition mode: `open`
- Audio duration: 4.000 s
- Processing time: 3130.557 ms

## Recognition

- Raw recognized text: `今天 天气 不错`
- command_id: `--`
- phrase: `--`
- unknown: True

This test reads one WAV file and performs fully offline fixed-command matching. It does not start depth processing, control hardware, or use a network service.
