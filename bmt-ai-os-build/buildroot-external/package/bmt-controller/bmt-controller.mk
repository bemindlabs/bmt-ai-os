################################################################################
#
# bmt-controller — AI stack orchestration service
#
################################################################################

BMT_CONTROLLER_VERSION = 1.0.0
BMT_CONTROLLER_SITE = $(BR2_EXTERNAL_BMT_AI_OS_PATH)/../../bmt-ai-os/controller
BMT_CONTROLLER_SITE_METHOD = local
BMT_CONTROLLER_LICENSE = MIT
BMT_CONTROLLER_LICENSE_FILES = ../../LICENSE
BMT_CONTROLLER_DEPENDENCIES = python3 python3-pip

define BMT_CONTROLLER_INSTALL_TARGET_CMDS
	$(INSTALL) -d -m 0755 $(TARGET_DIR)/opt/bmt-ai-os/controller
	$(INSTALL) -D -m 0755 $(@D)/main.py \
		$(TARGET_DIR)/opt/bmt-ai-os/controller/main.py
	# Install OpenRC init script
	$(INSTALL) -D -m 0755 $(BR2_EXTERNAL_BMT_AI_OS_PATH)/package/bmt-controller/S80bmt-controller \
		$(TARGET_DIR)/etc/init.d/S80bmt-controller
endef

$(eval $(generic-package))
