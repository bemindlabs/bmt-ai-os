# BMT AI OS — Project Makefile
# BMTOS-16: Build bootable ARM64 image pipeline
#
# Targets:
#   build        Build the ARM64 OS image
#   qemu-test    Boot and test the image in QEMU
#   clean        Remove build output
#   help         Show this help

# ─── Variables ────────────────────────────────────────────────────────────────

# Build target: qemu | jetson | rk3588 | pi5 | apple-silicon
TARGET ?= qemu

# Buildroot version (pinned; override via environment or CLI)
BUILDROOT_VERSION ?= 2024.02.9

# Path to the built image
IMAGE ?= output/images/bmt-ai-os-arm64.img

# Boot timeout for QEMU test (seconds)
QEMU_TIMEOUT ?= 60

# Additional flags forwarded to build.sh / qemu-test.sh
BUILD_EXTRA_FLAGS ?=
QEMU_EXTRA_FLAGS  ?=

# Internal paths
SCRIPTS_DIR := scripts
BUILD_SCRIPT  := $(SCRIPTS_DIR)/build.sh
QEMU_SCRIPT   := $(SCRIPTS_DIR)/qemu-test.sh

# ─── Phony Targets ────────────────────────────────────────────────────────────

.PHONY: build qemu-test clean menuconfig help

# ─── Default ──────────────────────────────────────────────────────────────────

.DEFAULT_GOAL := help

# ─── build ────────────────────────────────────────────────────────────────────

## build: Build the BMT AI OS ARM64 image for the specified TARGET.
##        Set TARGET=qemu (default), jetson, rk3588, pi5, or apple-silicon.
##        Example: make build TARGET=jetson
build:
	@chmod +x $(BUILD_SCRIPT)
	TARGET=$(TARGET) \
	BUILDROOT_VERSION=$(BUILDROOT_VERSION) \
	$(BUILD_SCRIPT) $(BUILD_EXTRA_FLAGS)

# ─── qemu-test ────────────────────────────────────────────────────────────────

## qemu-test: Boot the built image in QEMU and verify the login prompt appears.
##            Add QEMU_EXTRA_FLAGS=--smoke-tests to check service ports.
##            Add QEMU_EXTRA_FLAGS=--interactive to keep QEMU open.
##            Example: make qemu-test QEMU_TIMEOUT=120
qemu-test:
	@chmod +x $(QEMU_SCRIPT)
	$(QEMU_SCRIPT) \
		--image $(IMAGE) \
		--timeout $(QEMU_TIMEOUT) \
		$(QEMU_EXTRA_FLAGS)

# ─── menuconfig ───────────────────────────────────────────────────────────────

## menuconfig: Open Buildroot's interactive configuration menu.
menuconfig:
	@chmod +x $(BUILD_SCRIPT)
	TARGET=$(TARGET) \
	BUILDROOT_VERSION=$(BUILDROOT_VERSION) \
	$(BUILD_SCRIPT) --menuconfig

# ─── clean ────────────────────────────────────────────────────────────────────

## clean: Remove the output/ directory (build artefacts).
##        Does NOT remove the downloaded Buildroot archive.
clean:
	@echo "Removing output/ directory..."
	@rm -rf output/
	@echo "Done."

# ─── distclean ────────────────────────────────────────────────────────────────

## distclean: Remove output/ AND downloaded Buildroot archives/sources.
distclean: clean
	@echo "Removing Buildroot source directories and archives..."
	@rm -rf buildroot-*/
	@rm -f  buildroot-*.tar.gz buildroot-*.tar.gz.sha256
	@echo "Done."

# ─── help ─────────────────────────────────────────────────────────────────────

## help: Show this help message.
help:
	@echo ""
	@echo "BMT AI OS — ARM64 Image Build Pipeline"
	@echo "======================================="
	@echo ""
	@echo "Usage:"
	@echo "  make <target> [VARIABLE=value ...]"
	@echo ""
	@echo "Targets:"
	@grep -E '^## ' $(MAKEFILE_LIST) | sed 's/^## /  /' | column -t -s ':'
	@echo ""
	@echo "Variables:"
	@echo "  TARGET              Build target (default: $(TARGET))"
	@echo "                        qemu | jetson | rk3588 | pi5 | apple-silicon"
	@echo "  BUILDROOT_VERSION   Buildroot version (default: $(BUILDROOT_VERSION))"
	@echo "  IMAGE               Image path for qemu-test (default: $(IMAGE))"
	@echo "  QEMU_TIMEOUT        Boot timeout in seconds (default: $(QEMU_TIMEOUT))"
	@echo "  BUILD_EXTRA_FLAGS   Extra flags forwarded to build.sh"
	@echo "  QEMU_EXTRA_FLAGS    Extra flags forwarded to qemu-test.sh"
	@echo ""
	@echo "Examples:"
	@echo "  make build                              # Build QEMU test image"
	@echo "  make build TARGET=jetson                # Build Jetson Orin image"
	@echo "  make build TARGET=rk3588 --jobs 1      # Build RK3588 image"
	@echo "  make qemu-test                          # Boot test (60s timeout)"
	@echo "  make qemu-test QEMU_TIMEOUT=120 QEMU_EXTRA_FLAGS='--smoke-tests'"
	@echo "  make qemu-test QEMU_EXTRA_FLAGS='--interactive'"
	@echo "  make menuconfig TARGET=pi5              # Configure for Pi 5"
	@echo "  make clean                              # Remove build output"
	@echo "  make distclean                          # Remove output + sources"
	@echo ""
