################################################################################
#
# ollama — local LLM inference server
# BMTOS-16 stub: replace SRC_URI and add real build logic when packaging
#
################################################################################

OLLAMA_VERSION = 0.6.5
OLLAMA_SITE = https://github.com/ollama/ollama/releases/download/v$(OLLAMA_VERSION)
OLLAMA_SOURCE = ollama-linux-arm64
OLLAMA_LICENSE = MIT
OLLAMA_LICENSE_FILES = LICENSE

define OLLAMA_INSTALL_TARGET_CMDS
	$(INSTALL) -D -m 0755 $(@D)/ollama-linux-arm64 $(TARGET_DIR)/usr/bin/ollama
	$(INSTALL) -D -m 0755 $(BR2_EXTERNAL_BMT_AI_OS_PATH)/package/ollama/S60ollama \
		$(TARGET_DIR)/etc/init.d/S60ollama
endef

$(eval $(generic-package))
