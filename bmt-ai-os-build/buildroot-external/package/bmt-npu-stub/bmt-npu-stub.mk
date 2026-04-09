################################################################################
#
# bmt-npu-stub — NPU/GPU hardware acceleration placeholder
#
# This package installs a shell script that detects the NPU backend at
# runtime and exports BMT_NPU_BACKEND for the controller to consume.
# BSP owners should replace this with real driver packages.
#
################################################################################

BMT_NPU_STUB_VERSION = 1.0.0
BMT_NPU_STUB_SITE = $(BR2_EXTERNAL_BMT_AI_OS_PATH)/package/bmt-npu-stub
BMT_NPU_STUB_SITE_METHOD = local
BMT_NPU_STUB_LICENSE = MIT

define BMT_NPU_STUB_INSTALL_TARGET_CMDS
	$(INSTALL) -D -m 0755 $(@D)/detect-npu.sh \
		$(TARGET_DIR)/usr/lib/bmt-ai-os/detect-npu.sh
endef

$(eval $(generic-package))
