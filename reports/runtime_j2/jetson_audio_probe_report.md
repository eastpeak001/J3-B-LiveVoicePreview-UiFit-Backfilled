# Jetson USB Audio Probe Report

- Generated: 2026-06-21T11:41:33
- User: `pinggu_auar`
- User groups: `pinggu_auar, adm, cdrom, sudo, audio, dip, video, plugdev, render, i2c, lpadmin, gdm, sambashare, weston-launch, gpio`
- User belongs to `audio`: True
- `arecord` available: True
- `pactl` available: True
- PipeWire: `active`
- PulseAudio: `active`

## Target identity

- Required VID:PID: `1BCF:2D4F`.
- Matching USB functions: 1
- Matching ALSA capture candidates with exact sysfs VID/PID: 1
- A name match alone is never accepted as authorization to record.

## ALSA capture devices

| Card | Card ID | Card name | Device | Device name | VID:PID | USB path |
|---:|---|---|---:|---|---|---|
| 0 | `RGB` | USB2.0 Camera RGB | 0 | USB Audio | 1bcf:2d4f | `/sys/devices/platform/bus@0/3610000.usb/usb1/1-2/1-2.2` |

## Recommendation

- Hardware capture device: `hw:CARD=RGB,DEV=0`
- Plugin device for compatibility: `plughw:CARD=RGB,DEV=0`
- Selected native test format: `S16_LE`, 44100 Hz, 2 channel(s).
- USB bus path: `/sys/devices/platform/bus@0/3610000.usb/usb1/1-2/1-2.2`
- Result: target USB microphone uniquely confirmed; recording tests may proceed.
