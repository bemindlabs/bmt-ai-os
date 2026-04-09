# Definition of Done — BMT AI OS

## Code Complete
- [ ] All acceptance criteria met
- [ ] Code compiles/runs without errors on ARM64 target
- [ ] No hardcoded secrets or credentials

## Testing
- [ ] Unit tests pass (where applicable)
- [ ] Integration test with container runtime verified
- [ ] AI stack services respond to health checks
- [ ] Smoke test on target hardware or QEMU emulator

## Code Quality
- [ ] Python code passes linting (ruff/flake8)
- [ ] Shell scripts pass shellcheck
- [ ] Docker Compose config validates (`docker compose config`)
- [ ] Buildroot config builds without warnings

## Documentation
- [ ] SPECIFICATION.md updated if architecture changes
- [ ] Docker Compose services documented
- [ ] Controller API/CLI usage documented

## Review
- [ ] Code reviewed (self-review acceptable for solo)
- [ ] Changes tested in isolation before integration

## Deployment
- [ ] Container images build successfully
- [ ] Services start correctly via Docker Compose
- [ ] System boots on ARM64 (or QEMU) with all services

## Verification
- [ ] Ollama serves inference requests
- [ ] ChromaDB accepts and returns vector queries
- [ ] Controller manages container lifecycle correctly
