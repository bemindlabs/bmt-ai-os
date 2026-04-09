################################################################################
#
# chromadb — vector store for RAG (canonical DB for BMT AI OS)
# BMTOS-16 stub: replace with pip-based or wheel build when packaging
#
################################################################################

CHROMADB_VERSION = 0.6.3
CHROMADB_SOURCE = chromadb-$(CHROMADB_VERSION).tar.gz
CHROMADB_SITE = https://files.pythonhosted.org/packages/source/c/chromadb
CHROMADB_LICENSE = Apache-2.0
CHROMADB_LICENSE_FILES = LICENSE
CHROMADB_SETUP_TYPE = setuptools
CHROMADB_DEPENDENCIES = python3 python3-pip

define CHROMADB_INSTALL_TARGET_CMDS
	$(TARGET_DIR)/usr/bin/pip3 install --no-index \
		--find-links=$(@D) chromadb==$(CHROMADB_VERSION) || true
	$(INSTALL) -D -m 0755 $(BR2_EXTERNAL_BMT_AI_OS_PATH)/package/chromadb/S61chromadb \
		$(TARGET_DIR)/etc/init.d/S61chromadb
endef

$(eval $(generic-package))
