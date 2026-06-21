# Jetson Preflight Report

Generated: 2026-06-21T11:37:26.569531+08:00

This preflight is read-only. Missing components are recorded and are not installed automatically.

## Platform

```text
PRETTY_NAME="Ubuntu 22.04.5 LTS"
NAME="Ubuntu"
VERSION_ID="22.04"
VERSION="22.04.5 LTS (Jammy Jellyfish)"
VERSION_CODENAME=jammy
ID=ubuntu
ID_LIKE=debian
HOME_URL="https://www.ubuntu.com/"
SUPPORT_URL="https://help.ubuntu.com/"
BUG_REPORT_URL="https://bugs.launchpad.net/ubuntu/"
PRIVACY_POLICY_URL="https://www.ubuntu.com/legal/terms-and-policies/privacy-policy"
UBUNTU_CODENAME=jammy
```

## NVIDIA release

```text
# R36 (release), REVISION: 4.3, GCID: 38968081, BOARD: generic, EABI: aarch64, DATE: Wed Jan  8 01:49:37 UTC 2025
# KERNEL_VARIANT: oot
TARGET_USERSPACE_LIB_DIR=nvidia
TARGET_USERSPACE_LIB_DIR_PATH=usr/lib/aarch64-linux-gnu/nvidia
```

## Python and OpenCV

```text
Python: 3.10.12 (main, Nov  6 2024, 20:22:13) [GCC 11.4.0]
Executable: /usr/bin/python3
NumPy: 1.21.5
OpenCV: 4.5.4
cv2.ximgproc: True
cv2.cuda: True
cv2.cuda device count: 0
```

## Video group

`user=pinggu_auar groups=['adm', 'audio', 'cdrom', 'dip', 'gdm', 'gpio', 'i2c', 'lpadmin', 'pinggu_auar', 'plugdev', 'render', 'sambashare', 'sudo', 'video', 'weston-launch'] video_member=True`

## Power and clocks

No mode was changed and no nvpmodel ID is hard-coded.
- 25W mode mentioned by nvpmodel: `True`
- MAXN SUPER mentioned by nvpmodel: `False`

```text
$ sudo -n nvpmodel -q --verbose
exit=0
NVPM VERB: Config file: /etc/nvpmodel.conf
NVPM VERB: parsing done for /etc/nvpmodel.conf
NVPM VERB: Current mode: NV Power Mode: 25W
1
NVPM VERB: PARAM CPU_ONLINE: ARG CORE_0: PATH /sys/devices/system/cpu/cpu0/online: REAL_VAL: 1 CONF_VAL: 1
NVPM VERB: PARAM CPU_ONLINE: ARG CORE_1: PATH /sys/devices/system/cpu/cpu1/online: REAL_VAL: 1 CONF_VAL: 1
NVPM VERB: PARAM CPU_ONLINE: ARG CORE_2: PATH /sys/devices/system/cpu/cpu2/online: REAL_VAL: 1 CONF_VAL: 1
NVPM VERB: PARAM CPU_ONLINE: ARG CORE_3: PATH /sys/devices/system/cpu/cpu3/online: REAL_VAL: 1 CONF_VAL: 1
NVPM VERB: PARAM CPU_ONLINE: ARG CORE_4: PATH /sys/devices/system/cpu/cpu4/online: REAL_VAL: 1 CONF_VAL: 1
NVPM VERB: PARAM CPU_ONLINE: ARG CORE_5: PATH /sys/devices/system/cpu/cpu5/online: REAL_VAL: 1 CONF_VAL: 1
NVPM VERB: PARAM FBP_POWER_GATING: ARG FBP_PG_MASK: PATH /sys/devices/platform/gpu.0/fbp_pg_mask: REAL_VAL: 2 CONF_VAL: 2
NVPM VERB: PARAM TPC_POWER_GATING: ARG TPC_PG_MASK: PATH /sys/devices/platform/gpu.0/tpc_pg_mask: REAL_VAL: 240 CONF_VAL: 240
NVPM VERB: PARAM GPU_POWER_CONTROL_ENABLE: ARG GPU_PWR_CNTL_EN: PATH /sys/devices/platform/gpu.0/power/control: REAL_VAL: auto CONF_VAL: on
NVPM VERB: PARAM CPU_A78_0: ARG MIN_FREQ: PATH /sys/devices/system/cpu/cpu0/cpufreq/scaling_min_freq: REAL_VAL: 729600 CONF_VAL: 729600
NVPM VERB: PARAM CPU_A78_0: ARG MAX_FREQ: PATH /sys/devices/system/cpu/cpu0/cpufreq/scaling_max_freq: REAL_VAL: 1344000 CONF_VAL: 1344000
NVPM VERB: PARAM CPU_A78_1: ARG MIN_FREQ: PATH /sys/devices/system/cpu/cpu1/cpufreq/scaling_min_freq: REAL_VAL: 729600 CONF_VAL: 729600
NVPM VERB: PARAM CPU_A78_1: ARG MAX_FREQ: PATH /sys/devices/system/cpu/cpu1/cpufreq/scaling_max_freq: REAL_VAL: 1344000 CONF_VAL: 1344000
NVPM VERB: PARAM CPU_A78_2: ARG MIN_FREQ: PATH /sys/devices/system/cpu/cpu2/cpufreq/scaling_min_freq: REAL_VAL: 729600 CONF_VAL: 729600
NVPM VERB: PARAM CPU_A78_2: ARG MAX_FREQ: PATH /sys/devices/system/cpu/cpu2/cpufreq/scaling_max_freq: REAL_VAL: 1344000 CONF_VAL: 1344000
NVPM VERB: PARAM CPU_A78_3: ARG MIN_FREQ: PATH /sys/devices/system/cpu/cpu3/cpufreq/scaling_min_freq: REAL_VAL: 729600 CONF_VAL: 729600
NVPM VERB: PARAM CPU_A78_3: ARG MAX_FREQ: PATH /sys/devices/system/cpu/cpu3/cpufreq/scaling_max_freq: REAL_VAL: 1344000 CONF_VAL: 1344000
NVPM VERB: PARAM CPU_A78_4: ARG MIN_FREQ: PATH /sys/devices/system/cpu/cpu4/cpufreq/scaling_min_freq: REAL_VAL: 729600 CONF_VAL: 729600
NVPM VERB: PARAM CPU_A78_4: ARG MAX_FREQ: PATH /sys/devices/system/cpu/cpu4/cpufreq/scaling_max_freq: REAL_VAL: 1344000 CONF_VAL: 1344000
NVPM VERB: PARAM CPU_A78_5: ARG MIN_FREQ: PATH /sys/devices/system/cpu/cpu5/cpufreq/scaling_min_freq: REAL_VAL: 729600 CONF_VAL: 729600
NVPM VERB: PARAM CPU_A78_5: ARG MAX_FREQ: PATH /sys/devices/system/cpu/cpu5/cpufreq/scaling_max_freq: REAL_VAL: 1344000 CONF_VAL: 1344000
NVPM VERB: PARAM GPU: ARG MIN_FREQ: PATH /sys/devices/platform/17000000.gpu/devfreq_dev/min_freq: REAL_VAL: 306000000 CONF_VAL: 0
NVPM VERB: PARAM GPU: ARG MAX_FREQ: PATH /sys/devices/platform/17000000.gpu/devfreq_dev/max_freq: REAL_VAL: 918000000 CONF_VAL: 918000000
NVPM VERB: PARAM GPU_POWER_CONTROL_DISABLE: ARG GPU_PWR_CNTL_DIS: PATH /sys/devices/platform/gpu.0/power/control: REAL_VAL: auto CONF_VAL: auto
NVPM VERB: PARAM EMC: ARG MAX_FREQ: PATH /sys/kernel/nvpmodel_clk_cap/emc: REAL_VAL: 3199000000 CONF_VAL: 3199000000
```

jetson_clocks status:

```text
$ sudo -n jetson_clocks --show
exit=0
SOC family:tegra234  Machine:NVIDIA Jetson Orin Nano Engineering Reference Developer Kit Super
Online CPUs: 0-5
cpu0:  Online=1 Governor=schedutil MinFreq=729600 MaxFreq=1344000 CurrentFreq=729600 IdleStates: WFI=1 c7=1 
cpu1:  Online=1 Governor=schedutil MinFreq=729600 MaxFreq=1344000 CurrentFreq=729600 IdleStates: WFI=1 c7=1 
cpu2:  Online=1 Governor=schedutil MinFreq=729600 MaxFreq=1344000 CurrentFreq=1190400 IdleStates: WFI=1 c7=1 
cpu3:  Online=1 Governor=schedutil MinFreq=729600 MaxFreq=1344000 CurrentFreq=729600 IdleStates: WFI=1 c7=1 
cpu4:  Online=1 Governor=schedutil MinFreq=729600 MaxFreq=1344000 CurrentFreq=1190400 IdleStates: WFI=1 c7=1 
cpu5:  Online=1 Governor=schedutil MinFreq=729600 MaxFreq=1344000 CurrentFreq=1190400 IdleStates: WFI=1 c7=1 
GPU MinFreq=306000000 MaxFreq=918000000 CurrentFreq=306000000
Active GPU TPCs: 4
EMC MinFreq=204000000 MaxFreq=3199000000 CurrentFreq=2133000000 FreqOverride=0
FAN Dynamic Speed Control=nvfancontrol hwmon0_pwm1=69
NV Power Mode: 25W
```

Temperature readings:

```text
/sys/class/thermal/thermal_zone0/temp: 49468
/sys/class/thermal/thermal_zone1/temp: 50125
/sys/class/thermal/thermal_zone2/temp: <read failed: TypeError: can't concat NoneType to bytes>
/sys/class/thermal/thermal_zone3/temp: <read failed: TypeError: can't concat NoneType to bytes>
/sys/class/thermal/thermal_zone4/temp: <read failed: TypeError: can't concat NoneType to bytes>
/sys/class/thermal/thermal_zone5/temp: 50031
/sys/class/thermal/thermal_zone6/temp: 50531
/sys/class/thermal/thermal_zone7/temp: 48906
/sys/class/thermal/thermal_zone8/temp: 50531
```

## Camera and multimedia summary

```text
$ sh -c ls -l /dev/video* 2>&1 || true
exit=0
crw-rw----+ 1 root video 81, 0 11月 22  2023 /dev/video0
crw-rw----+ 1 root video 81, 1 11月 22  2023 /dev/video1
$ sh -c command -v v4l2-ctl || true
exit=0
/usr/bin/v4l2-ctl
$ gst-launch-1.0 --version
exit=0
gst-launch-1.0 version 1.20.3
GStreamer 1.20.3
https://launchpad.net/distros/ubuntu/+source/gstreamer1.0
```

## Detailed evidence

See `jetson_preflight_raw.txt` and `opencv_build_information.txt`.
