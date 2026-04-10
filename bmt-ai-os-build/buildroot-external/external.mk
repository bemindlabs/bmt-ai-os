# bmt-ai-os-build/buildroot-external/external.mk
# BMT AI OS Buildroot external tree — package inclusion
#
# Buildroot automatically includes this file when BR2_EXTERNAL is set to
# this directory. Add new package .mk files here as they are created under
# package/<name>/<name>.mk.

# Include all BMT AI OS package makefiles discovered under package/
include $(sort $(wildcard $(BR2_EXTERNAL_BMT_AI_OS_PATH)/package/*/*.mk))
