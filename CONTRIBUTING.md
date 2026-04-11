# Contributing to BMT AI OS

Thank you for your interest in contributing to BMT AI OS! This document provides guidelines for contributing to the project.

## Getting Started

1. Fork the repository
2. Clone your fork: `git clone git@github.com:YOUR_USERNAME/bmt-ai-os.git`
3. Create a feature branch: `git checkout -b feature/your-feature-name`
4. Make your changes
5. Push to your fork: `git push origin feature/your-feature-name`
6. Open a Pull Request

## Development Setup

### Prerequisites

- Docker & Docker Compose
- Python 3.10+
- Node.js 18+ & npm

### Run Locally

```bash
# Start AI stack
cd bmt_ai_os/ai-stack
docker compose up -d

# Run controller
pip install -e .
BMT_COMPOSE_FILE=$(pwd)/bmt_ai_os/ai-stack/docker-compose.yml \
  PYTHONPATH=$(pwd) python3 -m bmt_ai_os.controller.main
```

## Project Structure

- `bmt_ai_os/` — Runtime components (kernel, controller, AI stack, dashboard)
- `bmt-ai-os-build/` — Build infrastructure (Buildroot, BitBake layers)
- `.scrum/` — Project management (backlog, epics, sprints)

## Backlog & Issues

We track work using a scrum backlog in `.scrum/backlog.json`. Story IDs use the `BMTOS-{n}` format. When opening a PR, reference the relevant story ID if applicable.

## Code Style

- **Python**: Follow PEP 8. Use `ruff` for linting.
- **TypeScript/JavaScript**: Use ESLint + Prettier. Dashboard uses Next.js conventions.
- **Shell scripts**: Pass `shellcheck`.
- **Buildroot configs**: Follow Buildroot naming conventions (`BR2_PACKAGE_*`).

## Pull Request Guidelines

- Keep PRs focused on a single change
- Include a clear description of what and why
- Reference the BMTOS story ID if applicable
- Ensure Docker Compose config validates: `docker compose -f bmt_ai_os/ai-stack/docker-compose.yml config`

## Hardware Testing

If your change affects hardware-specific code, note which target you tested on:
- Jetson Orin Nano Super (CUDA)
- Rockchip RK3588 (RKNN NPU)
- Raspberry Pi 5 + AI HAT+ 2 (Hailo-10H)
- QEMU ARM64 (emulated)

## Reporting Issues

- Use GitHub Issues
- Include: OS, hardware target, steps to reproduce, expected vs actual behavior
- For security issues, email security@bemind.tech instead of opening a public issue

## License

By contributing, you agree that your contributions will be licensed under the MIT License.
