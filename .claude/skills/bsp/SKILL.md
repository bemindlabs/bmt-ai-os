---
name: bsp
description: Board Support Package management (detect, setup, info)
argument-hint: "<board> [detect|setup|info]"
user-invocable: true
allowed-tools: "Bash Read Grep Glob"
---

# Board Support Package

Manage hardware BSPs for ARM64 targets.

## Boards

Parse `$ARGUMENTS` for board name:

- **jetson**: NVIDIA Jetson Orin Nano Super (67 TOPS CUDA)
- **rk3588**: Rockchip RK3588 (6 TOPS RKNN)
- **pi5**: Raspberry Pi 5 + Hailo AI HAT+ (40 TOPS)
- **apple**: Apple Silicon / Asahi Linux (CPU-only)

## Actions

- **detect**: Run `bmt_ai_os/runtime/npu/<board>/detect.sh`
- **setup**: Run `bmt_ai_os/runtime/npu/<board>/setup.sh`
- **info**: Show kernel config, compose override, Buildroot package

## Available BSPs

!`ls bmt_ai_os/runtime/npu/ -d */ 2>/dev/null | sed 's|bmt_ai_os/runtime/npu/||;s|/||'`
