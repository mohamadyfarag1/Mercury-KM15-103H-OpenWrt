include $(TOPDIR)/rules.mk

PKG_NAME:=luci-app-horus-client
PKG_VERSION:=1.2.161
PKG_RELEASE:=1

LUCI_TITLE:=LuCI Support for Horus AP Client (Satellite Node)
LUCI_DEPENDS:=+python3-light +python3-urllib +python3-logging +python3-json +python3-openssl +openssl-util
LUCI_PKGARCH:=all

include $(TOPDIR)/feeds/luci/luci.mk

# call BuildPackage - OpenWrt buildroot signature
