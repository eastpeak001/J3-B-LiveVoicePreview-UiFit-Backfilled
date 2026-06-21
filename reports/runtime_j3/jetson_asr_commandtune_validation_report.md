# Jetson J3-A CommandTune Runtime Validation

- Validation platform: NVIDIA Jetson
- Runtime result archive: `StereoCameraValidation_Jetson_J3A_CommandTune_Runtime_Result.tar.gz`
- Runtime archive SHA-256: `8A1BE6EDDD3929CB5A357E80D9814BF62BDF1C4CB00E65FEC00B62E25298F423`
- Overall result: **PASS**

## Fixed-command results

| Test | Accepted phrase | Result |
| --- | --- | --- |
| `start_depth` | 开始测距 | PASS |
| `stop_depth` | 暂停测距 | PASS |
| `stop_depth` | 关闭测距 | PASS |
| `save_frame` | 保存画面 | PASS |
| `show_depth` | 显示深度 | PASS |
| `exit_program` | 退出程序 | PASS |
| unknown rejection | 今天 天气 不错 | PASS |

The CommandTune validation confirms that both recommended stop phrases work on
the Jetson. The matcher does not rely on the unreliable `停止测距` or
`结束测距` phrases, and unrelated speech remains unknown.

## Archived runtime evidence

The returned archive contains the final unknown-case reports:

- `jetson_asr_offline_fixed_command.json`
- `jetson_asr_offline_fixed_command_report.md`

They record open recognition of `今天 天气 不错` with no matched command and
`unknown: true`. The complete PASS matrix above records the accompanying Jetson
CommandTune test results confirmed for this runtime session.

No WAV recording, Vosk model, image, screenshot, cache, or other private sample
is stored with this backfilled report.
