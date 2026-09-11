include $(TOPDIR)/rules.mk

PKG_NAME:=luci-app-horus-client
PKG_VERSION:=1.2.161
PKG_RELEASE:=1

include $(INCLUDE_DIR)/package.mk

define Package/luci-app-horus-client
  SECTION:=luci
  CATEGORY:=LuCI
  TITLE:=Horus AP Client
  DEPENDS:=+lua +python3-light +python3-urllib +python3-logging
endef

define Build/Prepare
	mkdir -p $(PKG_BUILD_DIR)/ipk_root
	tar -xzO -f $(TOPDIR)/package/luci-app-horus-client/luci-app-horus-client_$(PKG_VERSION).ipk ./data.tar.gz | tar -xz -C $(PKG_BUILD_DIR)/ipk_root
endef

define Build/Compile
endef

define Package/luci-app-horus-client/install
	$(CP) $(PKG_BUILD_DIR)/ipk_root/* $(1)/
	$(INSTALL_DIR) $(1)/usr/share/horus-logos/www
	$(CP) ./files/www/* $(1)/usr/share/horus-logos/www/
endef

define Package/luci-app-horus-client/postinst
#!/bin/sh
[ -n "$${IPKG_INSTROOT}" ] || {
	cp -rf /usr/share/horus-logos/www/* /www/ 2>/dev/null || true
}
exit 0
endef

$(eval $(call BuildPackage,luci-app-horus-client))
