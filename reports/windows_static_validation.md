# Windows J1 Static Validation

Generated during J1 package preparation on 2026-06-19.

- Python compileall: PASS
- Jetson runtime YAML load: PASS
- Canonical YAML parse: PASS
- Canonical NPZ load and map/Q shape checks: PASS
- T_x negative, P2[0,3] negative, Q[3,2] positive: PASS
- Canonical package hashes match the frozen Windows source manifest: PASS
- Package text contains no Windows absolute paths: PASS
- Simulated no-ximgproc initialization: PASS; WLS disabled and Raw StereoSGBM initialized
- Simulated no-ximgproc processing on a frozen raw SBS frame: PASS; positive disparity ratio 1.0
- Fake Jetson runtime reports generated on Windows: NO

This report is static Windows evidence only. It is not a Jetson preflight, camera smoke test, or Jetson performance result.
