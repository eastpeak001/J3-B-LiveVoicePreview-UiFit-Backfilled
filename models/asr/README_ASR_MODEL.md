# J3-A Vosk Chinese model

J3-A expects a local, unpacked Vosk Chinese model at:

```text
models/asr/vosk-model-small-cn-0.22/
```

The model is intentionally not included in the source ZIP. The application does
not download models, contact a speech service, or enable network recognition.

Before running J3-A, obtain the model separately from the official Vosk model
distribution using a trusted computer, verify the downloaded archive as
appropriate for your deployment, and copy the unpacked directory to the path
above. A valid model directory normally contains at least `am/` and `conf/`.

Run the offline WAV test with:

```bash
bash tools/run_asr_offline_fixed_command_test.sh /path/to/input.wav
```

Large model files and test recordings must remain outside source-control and
release ZIPs.
