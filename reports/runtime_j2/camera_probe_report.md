# Jetson V4L2 Camera Probe

Target mode: MJPG 2560x720 at 60 FPS.

| Device | Name | Driver | Bus | VID:PID | Capture | Target mode |
|---|---|---|---|---|---|---|
| `/dev/video0` | USB2.0 Camera RGB: USB2.0 Camer | uvcvideo | usb-3610000.usb-2.2 | 1bcf:2d4f | True | True |
| `/dev/video1` | USB2.0 Camera RGB: USB2.0 Camer | uvcvideo | usb-3610000.usb-2.2 | 1bcf:2d4f | True | False |

## Recommendation

Use `/dev/video0` because it is a video-capture node and uniquely advertises MJPG 2560x720 at 60 FPS.
