################################################################################
#
# containerd — industry-standard container runtime (ARM64)
# BMTOS-2a | Epic: BMTOS-EPIC-3 (OS Foundation & Infrastructure)
#
# Builds containerd and runc from source for aarch64. The containerd binary
# provides the container runtime; runc provides the low-level OCI executor.
#
# At install time, the OpenRC init script and config.toml are copied from
# the BMT AI OS external tree into the target rootfs.
#
################################################################################

CONTAINERD_VERSION = $(call qstrip,$(BR2_PACKAGE_CONTAINERD_VERSION))
CONTAINERD_SITE = https://github.com/containerd/containerd/archive/refs/tags
CONTAINERD_SOURCE = v$(CONTAINERD_VERSION).tar.gz
CONTAINERD_LICENSE = Apache-2.0
CONTAINERD_LICENSE_FILES = LICENSE
CONTAINERD_DEPENDENCIES = host-go runc

# Go build environment for cross-compilation to ARM64.
CONTAINERD_GOENV = \
	GOARCH=arm64 \
	GOOS=linux \
	CGO_ENABLED=0 \
	GOFLAGS="-trimpath"

define CONTAINERD_BUILD_CMDS
	cd $(@D) && $(CONTAINERD_GOENV) $(HOST_DIR)/bin/go build \
		-o bin/containerd \
		-ldflags "-s -w -X github.com/containerd/containerd/v2/version.Version=$(CONTAINERD_VERSION)" \
		./cmd/containerd
	cd $(@D) && $(CONTAINERD_GOENV) $(HOST_DIR)/bin/go build \
		-o bin/containerd-shim-runc-v2 \
		-ldflags "-s -w" \
		./cmd/containerd-shim-runc-v2
	cd $(@D) && $(CONTAINERD_GOENV) $(HOST_DIR)/bin/go build \
		-o bin/ctr \
		-ldflags "-s -w" \
		./cmd/ctr
endef

define CONTAINERD_INSTALL_TARGET_CMDS
	# Install containerd binaries.
	$(INSTALL) -D -m 0755 $(@D)/bin/containerd \
		$(TARGET_DIR)/usr/bin/containerd
	$(INSTALL) -D -m 0755 $(@D)/bin/containerd-shim-runc-v2 \
		$(TARGET_DIR)/usr/bin/containerd-shim-runc-v2
	$(INSTALL) -D -m 0755 $(@D)/bin/ctr \
		$(TARGET_DIR)/usr/bin/ctr

	# Install containerd configuration.
	$(INSTALL) -D -m 0644 \
		$(BR2_EXTERNAL_BMT_AI_OS_PATH)/package/containerd/config.toml \
		$(TARGET_DIR)/etc/containerd/config.toml

	# Install OpenRC init script.
	$(INSTALL) -D -m 0755 \
		$(BR2_EXTERNAL_BMT_AI_OS_PATH)/package/containerd/containerd.initd \
		$(TARGET_DIR)/etc/init.d/containerd

	# Create persistent data and runtime state directories.
	$(INSTALL) -d -m 0711 $(TARGET_DIR)/var/lib/containerd
	$(INSTALL) -d -m 0711 $(TARGET_DIR)/run/containerd
endef

$(eval $(generic-package))

################################################################################
#
# runc — OCI container runtime
#
################################################################################

RUNC_VERSION = 1.2.5
RUNC_SITE = https://github.com/opencontainers/runc/archive/refs/tags
RUNC_SOURCE = v$(RUNC_VERSION).tar.gz
RUNC_LICENSE = Apache-2.0
RUNC_LICENSE_FILES = LICENSE
RUNC_DEPENDENCIES = host-go

RUNC_GOENV = \
	GOARCH=arm64 \
	GOOS=linux \
	CGO_ENABLED=0 \
	GOFLAGS="-trimpath"

define RUNC_BUILD_CMDS
	cd $(@D) && $(RUNC_GOENV) $(HOST_DIR)/bin/go build \
		-o runc \
		-ldflags "-s -w -X main.version=$(RUNC_VERSION)" \
		.
endef

define RUNC_INSTALL_TARGET_CMDS
	$(INSTALL) -D -m 0755 $(@D)/runc $(TARGET_DIR)/usr/bin/runc
endef

$(eval $(generic-package))
