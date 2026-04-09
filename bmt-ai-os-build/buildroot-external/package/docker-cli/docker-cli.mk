################################################################################
#
# docker-cli — Docker Engine (daemon + CLI + compose) for ARM64
# BMTOS-2a | Epic: BMTOS-EPIC-3 (OS Foundation & Infrastructure)
#
# Builds the Docker daemon (dockerd), CLI client (docker), and the Compose
# plugin from source for aarch64. The daemon connects to containerd and
# provides the high-level Docker API used by the BMT AI OS AI stack.
#
################################################################################

DOCKER_CLI_VERSION = $(call qstrip,$(BR2_PACKAGE_DOCKER_CLI_VERSION))
DOCKER_CLI_SOURCE = v$(DOCKER_CLI_VERSION).tar.gz
DOCKER_CLI_LICENSE = Apache-2.0
DOCKER_CLI_LICENSE_FILES = LICENSE
DOCKER_CLI_DEPENDENCIES = host-go containerd

# ---------------------------------------------------------------------------
# Docker daemon (dockerd) — built from moby/moby
# ---------------------------------------------------------------------------
DOCKER_CLI_MOBY_SITE = https://github.com/moby/moby/archive/refs/tags
DOCKER_CLI_MOBY_SOURCE = v$(DOCKER_CLI_VERSION).tar.gz

# ---------------------------------------------------------------------------
# Docker CLI (docker) — built from docker/cli
# ---------------------------------------------------------------------------
DOCKER_CLI_SITE = https://github.com/docker/cli/archive/refs/tags

# ---------------------------------------------------------------------------
# Docker Compose plugin — built from docker/compose
# ---------------------------------------------------------------------------
DOCKER_CLI_COMPOSE_VERSION = 2.35.1
DOCKER_CLI_COMPOSE_SITE = https://github.com/docker/compose/archive/refs/tags
DOCKER_CLI_COMPOSE_SOURCE = v$(DOCKER_CLI_COMPOSE_VERSION).tar.gz

# Go cross-compilation environment for ARM64.
DOCKER_CLI_GOENV = \
	GOARCH=arm64 \
	GOOS=linux \
	CGO_ENABLED=0 \
	GOFLAGS="-trimpath"

# Build timestamp for version info.
DOCKER_CLI_BUILDTIME = $(shell date -u +"%Y-%m-%dT%H:%M:%SZ")

define DOCKER_CLI_BUILD_CMDS
	# --- Build dockerd (daemon) ---
	cd $(@D)/moby && $(DOCKER_CLI_GOENV) $(HOST_DIR)/bin/go build \
		-o dockerd \
		-ldflags "-s -w \
			-X github.com/docker/docker/dockerversion.Version=$(DOCKER_CLI_VERSION) \
			-X github.com/docker/docker/dockerversion.BuildTime=$(DOCKER_CLI_BUILDTIME)" \
		./cmd/dockerd

	# --- Build docker (CLI client) ---
	cd $(@D)/cli && $(DOCKER_CLI_GOENV) $(HOST_DIR)/bin/go build \
		-o docker \
		-ldflags "-s -w \
			-X github.com/docker/cli/cli/version.Version=$(DOCKER_CLI_VERSION) \
			-X github.com/docker/cli/cli/version.BuildTime=$(DOCKER_CLI_BUILDTIME)" \
		./cmd/docker

	# --- Build docker-compose plugin ---
	cd $(@D)/compose && $(DOCKER_CLI_GOENV) $(HOST_DIR)/bin/go build \
		-o docker-compose \
		-ldflags "-s -w \
			-X github.com/docker/compose/v2/internal.Version=$(DOCKER_CLI_COMPOSE_VERSION)" \
		./cmd
endef

define DOCKER_CLI_INSTALL_TARGET_CMDS
	# Install Docker daemon.
	$(INSTALL) -D -m 0755 $(@D)/moby/dockerd \
		$(TARGET_DIR)/usr/bin/dockerd

	# Install Docker CLI.
	$(INSTALL) -D -m 0755 $(@D)/cli/docker \
		$(TARGET_DIR)/usr/bin/docker

	# Install Docker Compose as a CLI plugin.
	$(INSTALL) -D -m 0755 $(@D)/compose/docker-compose \
		$(TARGET_DIR)/usr/libexec/docker/cli-plugins/docker-compose

	# Install Docker daemon configuration.
	$(INSTALL) -D -m 0644 \
		$(BR2_EXTERNAL_BMT_AI_OS_PATH)/package/docker-cli/daemon.json \
		$(TARGET_DIR)/etc/docker/daemon.json

	# Install OpenRC init script for Docker daemon.
	$(INSTALL) -D -m 0755 \
		$(BR2_EXTERNAL_BMT_AI_OS_PATH)/package/docker-cli/docker.initd \
		$(TARGET_DIR)/etc/init.d/docker

	# Create data and runtime directories.
	$(INSTALL) -d -m 0710 $(TARGET_DIR)/var/lib/docker
	$(INSTALL) -d -m 0710 $(TARGET_DIR)/run/docker
endef

$(eval $(generic-package))
