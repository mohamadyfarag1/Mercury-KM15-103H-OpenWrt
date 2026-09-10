'use strict';
'require view';
'require form';
'require uci';
'require ui';
'require fs';
'require horus_client.i18n as horusI18n';
'require horus_client.styles as horusStyles';

return view.extend({
	render: function() {
		var m, s, o;

		var horus_version = '1.2.161';
		m = new form.Map('horus_controller', horusI18n.t('settings'), horusI18n.t('settings_desc') + ' (Client Mode) - Build: ' + horus_version);

		s = m.section(form.NamedSection, 'main', 'settings', '');
		s.anonymous = false;
		s.addremove = false;

		s.tab('role', horusI18n.t('tab_role'));
		s.tab('radius', horusI18n.t('tab_radius'));
		s.tab('neighbors', horusI18n.t('tab_neighbors'));

		// ==========================================
		// Tab 1: نظام التشغيل والربط
		// ==========================================
		o = s.taboption('role', form.ListValue, 'role', horusI18n.t('opt_role'));
		o.value('standalone', horusI18n.t('role_standalone'));
		o.value('satellite', horusI18n.t('role_satellite'));
		o.default = 'satellite';

		o = s.taboption('role', form.DummyValue, '_role_help', horusI18n.t('opt_role_help'));
		o.rawhtml = true;
		o.cfgvalue = function(section_id) {
			var role = uci.get('horus_controller', section_id, 'role');
			var desc = (role === 'satellite') ? horusI18n.t('role_help_satellite') : horusI18n.t('role_help_standalone');
			return '<div class="horus-role-help"><span style="font-size:18px;">💡</span><span>' + desc + '</span></div>';
		};

		o = s.taboption('role', form.Value, 'controller_ip', horusI18n.t('opt_controller_ip'));
		o.datatype = 'ip4addr';
		o.placeholder = '192.168.1.1';
		o.depends('role', 'satellite');
		o.description = horusI18n.t('opt_controller_ip_desc');

		o = s.taboption('role', form.Value, 'hmp_secret', horusI18n.t('opt_hmp_secret'));
		o.password = true;
		o.description = horusI18n.t('opt_hmp_secret_desc');

		// ==========================================
		// Tab 2: نظام الريديس (RADIUS)
		// ==========================================
		o = s.taboption('radius', form.Flag, 'enabled', horusI18n.t('opt_radius_enabled'));
		o.default = '1';
		o.rmempty = false;

		o = s.taboption('radius', form.ListValue, 'radius_type', horusI18n.t('opt_radius_type'));
		o.value('sas', 'SAS 4');
		o.value('dma', 'DMA Radius');
		o.value('adv', 'ADV');
		o.value('icm', 'ICM Radius');
		o.value('um7', 'MikroTik User Manager 7');
		o.value('freenet', 'Free Net Radius');
		o.value('mikrotik', 'MikroTik (Hotspot/PPP)');
		o.default = 'sas';
		o.depends('enabled', '1');

		// Helper functions for obfuscation
		function xor_encrypt(str) {
			if(!str) return str;
			var utf8_str = unescape(encodeURIComponent(str));
			var key = "horus_radius_2026";
			var res = "";
			for(var i = 0; i < utf8_str.length; i++) {
				res += String.fromCharCode(utf8_str.charCodeAt(i) ^ key.charCodeAt(i % key.length));
			}
			return "enc3_" + btoa(res);
		}
		function xor_decrypt(val) {
			if (!val || !val.startsWith("enc3_")) return val;
			try {
				var res = atob(val.substring(5));
				var key = "horus_radius_2026";
				var utf8_str = "";
				for(var i = 0; i < res.length; i++) {
					utf8_str += String.fromCharCode(res.charCodeAt(i) ^ key.charCodeAt(i % key.length));
				}
				return decodeURIComponent(escape(utf8_str));
			} catch(e) { return val; }
		}

		function add_radius_type_fields(typeKey, urlPlaceholder, urlDesc, hasPort, hasKey, keyTitle, keyPlaceholder, keyDesc, defaultKey) {
			var optUrl = s.taboption('radius', form.Value, typeKey + '_base_url', horusI18n.t('opt_base_url'));
			optUrl.placeholder = urlPlaceholder;
			optUrl.description = urlDesc || horusI18n.t('opt_base_url_desc');
			optUrl.depends('radius_type', typeKey);
			optUrl.cfgvalue = function(section_id) {
				return uci.get('horus_controller', section_id, typeKey + '_base_url') || '';
			};
			optUrl.write = function(section_id, val) {
				uci.set('horus_controller', section_id, typeKey + '_base_url', val);
				if (uci.get('horus_controller', section_id, 'radius_type') === typeKey) {
					uci.set('horus_controller', section_id, 'base_url', val);
				}
			};

			if (hasPort) {
				var optPort = s.taboption('radius', form.Value, typeKey + '_api_port', horusI18n.t('opt_api_port'));
				optPort.datatype = 'port';
				optPort.placeholder = '8728';
				optPort.default = '8728';
				optPort.description = horusI18n.t('opt_api_port_desc');
				optPort.depends('radius_type', typeKey);
				optPort.cfgvalue = function(section_id) {
					return uci.get('horus_controller', section_id, typeKey + '_api_port') || '8728';
				};
				optPort.write = function(section_id, val) {
					uci.set('horus_controller', section_id, typeKey + '_api_port', val);
					if (uci.get('horus_controller', section_id, 'radius_type') === typeKey) {
						uci.set('horus_controller', section_id, 'api_port', val);
					}
				};
			}

			var optUser = s.taboption('radius', form.Value, typeKey + '_username', horusI18n.t('opt_username'));
			optUser.placeholder = 'admin';
			optUser.depends('radius_type', typeKey);
			optUser.cfgvalue = function(section_id) {
				return uci.get('horus_controller', section_id, typeKey + '_username') || '';
			};
			optUser.write = function(section_id, val) {
				uci.set('horus_controller', section_id, typeKey + '_username', val);
				if (uci.get('horus_controller', section_id, 'radius_type') === typeKey) {
					uci.set('horus_controller', section_id, 'username', val);
				}
			};

			var optPass = s.taboption('radius', form.Value, typeKey + '_password', horusI18n.t('opt_password'));
			optPass.password = true;
			optPass.depends('radius_type', typeKey);
			optPass.cfgvalue = function(section_id) {
				var raw = uci.get('horus_controller', section_id, typeKey + '_password') || '';
				return xor_decrypt(raw);
			};
			optPass.write = function(section_id, val) {
				if (!val) {
					uci.remove('horus_controller', section_id, typeKey + '_password');
					if (uci.get('horus_controller', section_id, 'radius_type') === typeKey) uci.remove('horus_controller', section_id, 'password');
				} else {
					var enc = val.startsWith('enc3_') ? val : xor_encrypt(val);
					uci.set('horus_controller', section_id, typeKey + '_password', enc);
					if (uci.get('horus_controller', section_id, 'radius_type') === typeKey) uci.set('horus_controller', section_id, 'password', enc);
				}
			};

			if (hasKey) {
				var optKey = s.taboption('radius', form.Value, typeKey + '_api_key', keyTitle || 'License Key');
				optKey.placeholder = keyPlaceholder || '';
				optKey.default = defaultKey || '';
				optKey.description = keyDesc || '';
				optKey.depends('radius_type', typeKey);
				optKey.cfgvalue = function(section_id) {
					var raw = uci.get('horus_controller', section_id, typeKey + '_api_key') || (defaultKey || '');
					return xor_decrypt(raw);
				};
				optKey.write = function(section_id, val) {
					if (!val) {
						uci.remove('horus_controller', section_id, typeKey + '_api_key');
						if (uci.get('horus_controller', section_id, 'radius_type') === typeKey) uci.remove('horus_controller', section_id, 'api_key');
					} else {
						var enc = val.startsWith('enc3_') ? val : xor_encrypt(val);
						uci.set('horus_controller', section_id, typeKey + '_api_key', enc);
						if (uci.get('horus_controller', section_id, 'radius_type') === typeKey) uci.set('horus_controller', section_id, 'api_key', enc);
					}
				};
			}
		}

		// SAS 4: URL, Username, Password
		add_radius_type_fields('sas', 'http://192.168.1.100', 'رابط السيرفر الأساسي لنظام SAS 4 (مثال: http://192.168.1.100)', false, false);

		// DMA Radius: URL, Username, Password (Master Key is automatic)
		add_radius_type_fields('dma', '192.168.11.50', 'رابط السيرفر الأساسي لنظام DMA Radius (مثال: 192.168.11.50)', false, false);

		// ADV: URL, Username, Password, License Key
		add_radius_type_fields('adv', '192.168.1.100', 'رابط السيرفر الأساسي لنظام ADV', false, true, horusI18n.t('opt_adv_license') || 'رقم الرخصة (License Key)', '8610', horusI18n.t('opt_adv_license_desc') || 'رقم الرخصة الخاص بنظام ADV', '8610');

		// ICM Radius: URL, Username, Password (API Key is automatic)
		add_radius_type_fields('icm', 'https://2217.icmradius.com', 'رابط السيرفر الأساسي لنظام ICM Radius (مثال: https://2217.icmradius.com)', false, false);

		// MikroTik User Manager 7: URL, Username, Password
		add_radius_type_fields('um7', '192.168.88.1', 'رابط أو IP سيرفر User Manager 7 (مثال: 192.168.88.1)', false, false);

		// Free Net Radius: URL, Username, Password
		add_radius_type_fields('freenet', 'https://freenet.al-eg.com', 'رابط السيرفر الأساسي لنظام Free Net Radius (مثال: https://freenet.al-eg.com أو IP محلي)', false, false);

		// MikroTik (Hotspot/PPP): Host, Port, Username, Password
		add_radius_type_fields('mikrotik', '192.168.88.1', 'عنوان IP الخاص براوتر المايكروتك (مثال: 192.168.88.1)', true, false);

		o = s.taboption('radius', form.Value, 'sync_interval', horusI18n.t('opt_sync_interval'));
		o.datatype = 'uinteger';
		o.default = '10';
		o.depends('enabled', '1');

		o = s.taboption('radius', form.DummyValue, '_status', horusI18n.t('opt_radius_status'));
		o.rawhtml = true;
		o.depends('enabled', '1');
		o.cfgvalue = function(section_id) {
			var en = uci.get('horus_controller', section_id, 'enabled');
			var rtype = uci.get('horus_controller', section_id, 'radius_type') || 'sas';
			var url = uci.get('horus_controller', section_id, rtype + '_base_url') || uci.get('horus_controller', section_id, 'base_url');
			if (en !== '1' || !url) {
				return '<span class="h-badge h-badge-error">' + horusI18n.t('status_unconfigured') + '</span>';
			}
			return '<span id="horus_auto_status" class="h-badge h-badge-warning">' + horusI18n.t('status_checking') + '</span>' +
				'<img src="data:image/gif;base64,R0lGODlhAQABAIAAAAAAAP///yH5BAEAAAAALAAAAAABAAEAAAIBRAA7" style="display:none;" onload="'+
				'fetch(\'/cgi-bin/horus_test\').then(function(r){return r.json();}).then(function(d){' +
				'var el = document.getElementById(\'horus_auto_status\'); if(!el) return;' +
				'if(d.success){' +
				'el.innerHTML = \'' + horusI18n.t('status_connected') + '\';' +
				'el.className = \'h-badge h-badge-success\';' +
				'} else if(d.error === \'forbidden\'){' +
				// Our OWN cgi_auth guard rejected the request (expired/missing
				// LuCI session) -- this has nothing to do with the RADIUS
				// server's credentials. Showing "auth_error" here for years
				// misled admins into thinking the RADIUS password was wrong
				// when it was actually just a stale browser session.
				'el.innerHTML = \'' + horusI18n.t('status_session_expired') + '\';' +
				'el.className = \'h-badge h-badge-warning\';' +
				'} else {' +
				'if(d.message && (d.message.indexOf(\'Timeout\') !== -1 || d.message.indexOf(\'unreachable\') !== -1 || d.message.indexOf(\'\\u0644\\u0627 \\u064a\\u0648\\u062c\\u062f \\u0631\\u062f\') !== -1)){' +
				'el.innerHTML = \'' + horusI18n.t('status_timeout') + '\';' +
				'el.className = \'h-badge h-badge-error\';' +
				'} else if(d.message && (d.message.indexOf(\'too_many_tries\') !== -1 || d.message.indexOf(\'\\u062a\\u062c\\u0627\\u0648\\u0632\') !== -1)){' +
				'el.innerHTML = \'⚠️ تم تجاوز المحاولات (انتظر دقيقة)\';' +
				'el.className = \'h-badge h-badge-warning\';' +
				'} else {' +
				'el.innerHTML = \'' + horusI18n.t('status_auth_error') + '\';' +
				'el.className = \'h-badge h-badge-warning\';' +
				'}' +
				'}' +
				'}).catch(function(){' +
				'var el = document.getElementById(\'horus_auto_status\'); if(!el) return;' +
				'el.innerHTML = \'' + horusI18n.t('status_error') + '\';' +
				'el.className = \'h-badge h-badge-error\';' +
				'});' +
				'">';
		};

		// ==========================================
		// Tab 3: استكشاف الجيران (P2P Neighbor Discovery)
		// ==========================================
		o = s.taboption('neighbors', form.Flag, 'neighbors_enabled', horusI18n.t('opt_neighbors_en'));
		o.default = '1';
		o.rmempty = false;
		o.description = horusI18n.t('opt_neighbors_en_desc');

		o = s.taboption('neighbors', form.Value, 'neighbors_interval', horusI18n.t('opt_neighbors_int'));
		o.datatype = 'uinteger';
		o.placeholder = '30';
		o.default = '30';
		o.depends('neighbors_enabled', '1');
		o.description = horusI18n.t('opt_neighbors_int_desc');

		o = s.taboption('neighbors', form.DummyValue, '_rrm_advisor_panel', horusI18n.t('rrm_panel_title'));
		o.rawhtml = true;
		o.depends('neighbors_enabled', '1');
		o.cfgvalue = function(section_id) {
			return '<div id="horus_rrm_advisor_box" class="h-rrm-panel">' +
				'<div class="h-rrm-header">' +
				'<div><span class="h-rrm-title">🧠 ' + horusI18n.t('rrm_health_title') + '</span>' +
				'<div class="h-rrm-desc">' + horusI18n.t('rrm_health_desc') + '</div></div>' +
				'<button type="button" class="h-btn h-btn-primary h-btn-sm" onclick="window.horusRefreshRrm()">' +
				'🔄 ' + horusI18n.t('rrm_btn_scan') + '</button>' +
				'</div>' +
				'<div id="horus_rrm_content"><span class="h-badge h-badge-warning">⏳ ' + horusI18n.t('rrm_scanning') + '</span></div>' +
				'</div>';
		};

		o = s.taboption('neighbors', form.DummyValue, '_neighbors_table', horusI18n.t('rrm_table_title'));
		o.rawhtml = true;
		o.depends('neighbors_enabled', '1');
		o.cfgvalue = function(section_id) {
			return '<div id="horus_neighbors_box" class="h-peer-list" style="margin-top:10px;">' +
				'<span class="h-badge h-badge-warning">⏳ ' + horusI18n.t('peer_loading') + '</span>' +
				'</div>';
		};

		return m.render().then(function(mapNode) {
			function recheckDependencies() {
				if (m && typeof m.checkDepends === 'function') {
					m.checkDepends();
				}
				if (mapNode) {
					mapNode.dispatchEvent(new CustomEvent('cbi-dependency-check', { bubbles: true }));
				}
			}

			// When switching tabs, LuCI toggles active tab panes without re-evaluating dependencies.
			// This caused fields inside inactive tabs to remain hidden until browser refresh.
			// Trigger dependency recheck immediately whenever any tab is activated or clicked.
			mapNode.addEventListener('cbi-tab-active', function() {
				window.setTimeout(recheckDependencies, 20);
			});

			mapNode.querySelectorAll('.cbi-tabmenu li').forEach(function(li) {
				li.addEventListener('click', function() {
					window.setTimeout(recheckDependencies, 20);
					window.setTimeout(recheckDependencies, 100);
				});
			});

			window.setTimeout(recheckDependencies, 50);
			window.setTimeout(recheckDependencies, 250);
			window.addEventListener('hashchange', recheckDependencies);

			// Inject crisp vector SVG icons into tabs to eliminate any emoji rendering issues
			var tabSvgIcons = {
				'role': '<svg viewBox="0 0 24 24" width="18" height="18" stroke="currentColor" stroke-width="2" fill="none" style="display:inline-block;vertical-align:middle;margin-inline-end:8px;"><circle cx="12" cy="12" r="3"></circle><path d="M19.4 15a1.65 1.65 0 00.33 1.82l.06.06a2 2 0 010 2.83 2 2 0 01-2.83 0l-.06-.06a1.65 1.65 0 00-1.82-.33 1.65 1.65 0 00-1 1.51V21a2 2 0 01-2 2 2 2 0 01-2-2v-.09A1.65 1.65 0 009 19.4a1.65 1.65 0 00-1.82.33l-.06.06a2 2 0 01-2.83 0 2 2 0 010-2.83l.06-.06a1.65 1.65 0 00.33-1.82 1.65 1.65 0 00-1.51-1H3a2 2 0 01-2-2 2 2 0 012-2h.09A1.65 1.65 0 004.6 9a1.65 1.65 0 00-.33-1.82l-.06-.06a2 2 0 010-2.83 2 2 0 012.83 0l.06.06a1.65 1.65 0 001.82.33H9a1.65 1.65 0 001-1.51V3a2 2 0 012-2 2 2 0 012 2v.09a1.65 1.65 0 001 1.51 1.65 1.65 0 001.82-.33l.06-.06a2 2 0 012.83 0 2 2 0 010 2.83l-.06.06a1.65 1.65 0 00.33-1.82V9a1.65 1.65 0 001.51 1H21a2 2 0 012 2 2 2 0 01-2 2h-.09a1.65 1.65 0 00-1.51 1z"></path></svg>',
				'radius': '<svg viewBox="0 0 24 24" width="18" height="18" stroke="currentColor" stroke-width="2" fill="none" style="display:inline-block;vertical-align:middle;margin-inline-end:8px;"><ellipse cx="12" cy="5" rx="9" ry="3"></ellipse><path d="M21 12c0 1.66-4 3-9 3s-9-1.34-9-3"></path><path d="M3 5v14c0 1.66 4 3 9 3s9-1.34 9-3V5"></path></svg>',
				'neighbors': '<svg viewBox="0 0 24 24" width="18" height="18" stroke="currentColor" stroke-width="2" fill="none" style="display:inline-block;vertical-align:middle;margin-inline-end:8px;"><circle cx="12" cy="12" r="2"></circle><path d="M16.24 7.76a6 6 0 010 8.49m-8.48-.01a6 6 0 010-8.49m11.31-2.82a10 10 0 010 14.14m-14.14 0a10 10 0 010-14.14"></path></svg>'
			};
			mapNode.querySelectorAll('.cbi-tabmenu li a').forEach(function(a) {
				var t = a.getAttribute('data-tab') || (a.parentNode && a.parentNode.getAttribute('data-tab'));
				if (t && tabSvgIcons[t]) {
					var rawText = a.textContent.replace(/[\u{1F300}-\u{1F9FF}]|[\u{2600}-\u{26FF}]|[\u{2700}-\u{27BF}]/gu, '').trim();
					a.innerHTML = tabSvgIcons[t] + '<span>' + rawText + '</span>';
				}
			});

			var langBtn = horusI18n.buildLangBtn(function() {
				window.location.reload();
			});

			var pDesc = E('p', { class: 'h-panel-desc' }, horusI18n.t('settings_desc') + ' | Build: ' + horus_version);
			try {
				fetch('/cgi-bin/horus_version?_=' + Date.now()).then(function(r){return r.json();}).then(function(d){
					if(d.version) {
						pDesc.textContent = horusI18n.t('settings_desc') + ' | Build: ' + d.version;
					}
				}).catch(function(){});
			} catch(e){}

			var logoImg = E('img', {
				src: '/luci-static/resources/horus_client/logo.png',
				style: 'height:48px;width:auto;vertical-align:middle;margin-inline-end:14px;filter:drop-shadow(0 0 6px rgba(14,165,233,0.4));',
				alt: 'Horus'
			});

			var topBar = E('div', { class: 'h-panel h-flex h-flex-wrap h-justify-between h-items-center h-mb-4' }, [
				E('div', { style: 'display:flex;align-items:center;' }, [
					logoImg,
					E('div', {}, [
						E('h2', { class: 'h-panel-title' }, horusI18n.t('settings') + ' (Client)'),
						pDesc
					])
				]),
				langBtn
			]);

			// Hero status card: node identity + live controller-connection state,
			// promoted out of the settings form so it's the first thing seen --
			// "am I online, who is my controller" is this device's #1 question.
			var heroRing = E('div', { class: 'h-hero-ring' }, '📡');
			var heroName = E('div', { class: 'h-hero-name' }, 'Horus-AP');
			var heroMeta = E('div', { class: 'h-hero-meta' }, window.location.hostname);
			var heroBadge = E('div', { class: 'h-hero-status-badge' }, '⏳ ' + horusI18n.t('hero_checking'));
			var heroSub = E('div', { class: 'h-hero-status-sub' }, '');
			var heroCard = E('div', { class: 'h-hero' }, [
				E('div', { class: 'h-hero-id' }, [ heroRing, E('div', {}, [ heroName, heroMeta ]) ]),
				E('div', { class: 'h-hero-status' }, [ heroBadge, heroSub ])
			]);

			function refreshHeroStatus() {
				if (!document.getElementById('horus_rrm_advisor_box') && !document.getElementById('horus_neighbors_box') && !document.querySelector('.h-hero')) return;
				syncHorusSid();
				fetch('/cgi-bin/horus_ping_controller?_=' + Date.now())
				.then(function(r){ if (!r.ok) throw new Error(r.status); return r.json(); })
				.then(function(d) {
					if (d.status === 'online' || d.status === 'connected') {
						heroRing.className = 'h-hero-ring online';
						heroBadge.className = 'h-hero-status-badge online';
						heroBadge.textContent = horusI18n.t('hero_connected');
						var cHost = d.controller_hostname || d.hostname || 'Controller';
						var cMode = d.mode ? (' · ' + d.mode) : '';
						heroSub.textContent = cHost + cMode;
					} else if (d.status === 'awaiting_activation') {
						heroRing.className = 'h-hero-ring pending';
						heroBadge.className = 'h-hero-status-badge pending';
						heroBadge.textContent = horusI18n.t('hero_awaiting');
						var cHost = d.controller_hostname || d.hostname || 'Controller';
						heroSub.textContent = cHost + ' · ' + horusI18n.t('hero_awaiting_sub');
					} else if (d.status === 'searching' || d.status === 'broadcast') {
						heroRing.className = 'h-hero-ring pending';
						heroBadge.className = 'h-hero-status-badge pending';
						heroBadge.textContent = horusI18n.t('hero_searching');
						heroSub.textContent = horusI18n.t('hero_searching_sub');
					} else {
						heroRing.className = 'h-hero-ring offline';
						heroBadge.className = 'h-hero-status-badge offline';
						heroBadge.textContent = horusI18n.t('hero_disconnected');
						heroSub.textContent = d.message || '';
					}
				}).catch(function() {
					heroRing.className = 'h-hero-ring offline';
					heroBadge.className = 'h-hero-status-badge offline';
					heroBadge.textContent = horusI18n.t('hero_check_error');
					heroSub.textContent = '';
				});
			}

			window.horusEsc = function(s) {
				if (s === null || s === undefined) return '';
				var m = {'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'};
				return String(s).replace(/[&<>"']/g, function(c){ return m[c]; });
			};

			window.horusSafeIp = function(s) {
				return /^\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}$/.test(String(s || '')) ? String(s) : '';
			};

			function syncHorusSid() {
				try {
					var sid = (window.L && L.env && L.env.sessionid) ? L.env.sessionid : null;
					if (sid) document.cookie = 'horus_sid=' + sid + '; path=/cgi-bin/; SameSite=Strict';
				} catch (e) {}
			}

			window.horusApplyRrm = function(ch) {
				if (!confirm(horusI18n.t('rrm_confirm_prefix') + ' (' + ch + ') ' + horusI18n.t('rrm_confirm_suffix'))) return;
				syncHorusSid();
				fetch('/cgi-bin/horus_rrm_apply', {
					method: 'POST',
					headers: {'Content-Type': 'application/json'},
					body: JSON.stringify({channel: ch})
				})
				.then(function(r){ if (!r.ok) throw new Error(r.status); return r.json(); })
				.then(function(d){
					if (d.success) {
						alert(d.message || horusI18n.t('rrm_apply_success'));
						setTimeout(function(){ window.location.reload(); }, 2000);
					} else {
						alert(d.message || d.error || horusI18n.t('rrm_apply_err').replace('{e}', ''));
					}
				}).catch(function(e){
					alert(horusI18n.t('rrm_apply_err').replace('{e}', e));
				});
			};

			window.horusRefreshRrm = function() {
				var el = document.getElementById('horus_rrm_content');
				if (!el) return;
				el.innerHTML = '<span class="h-badge h-badge-warning">⏳ ' + horusI18n.t('rrm_scanning') + '</span>';
				syncHorusSid();
				fetch('/cgi-bin/horus_rrm_data?_=' + Date.now())
				.then(function(r){ if (!r.ok) throw new Error(r.status); return r.json(); })
				.then(function(d){
					if (d.status === 'error' || d.error) {
						el.innerHTML = '<div class="h-text-muted">⚠️ ' + (d.message || d.error) + '</div>';
						return;
					}
					if (!d.has_5g) {
						el.innerHTML = '<div class="h-text-muted">' + horusI18n.t('rrm_no_5g') + '</div>';
						return;
					}
					var isAr = (horusI18n.getLang() === 'ar');
					var statusVar = d.current_status === 'excellent' ? '--h-success' : (d.current_status === 'moderate' ? '--h-warning' : '--h-error');
					var reason = isAr ? (d.reason_ar || d.reason || '') : (d.reason || d.reason_ar || '');
					var statusLabel = isAr ? (d.current_status_ar || d.current_status || '') : (d.current_status || d.current_status_ar || '');
					var recHtml = '';
					if (d.is_switch_recommended) {
						recHtml = '<div class="h-rrm-recommendation">' +
							'<div><span class="h-rrm-rec-title">💡 ' + horusI18n.t('rrm_recommend_prefix') + ' (' + d.recommended_channel + ')</span>' +
							'<div class="h-rrm-rec-reason">' + reason + '</div></div>' +
							'<button type="button" class="h-btn h-btn-success h-btn-sm" onclick="window.horusApplyRrm(' + d.recommended_channel + ')">' +
							'⚡ ' + horusI18n.t('rrm_apply_prefix') + ' ' + d.recommended_channel + ' ' + horusI18n.t('rrm_rollback_safe') + '</button>' +
							'</div>';
					} else {
						recHtml = '<div class="h-rrm-recommendation-ok">' +
							'✅ ' + (reason || horusI18n.t('rrm_reason_default')) + '</div>';
					}
					el.innerHTML = '<div class="h-rrm-stats">' +
						'<div class="h-rrm-stat"><span class="h-rrm-stat-label">' + horusI18n.t('rrm_lbl_cur') + '</span><b class="h-rrm-stat-value">' + d.current_channel + ' (' + ((d.local && d.local.htmode) || 'VHT80') + ')</b></div>' +
						'<div class="h-rrm-stat"><span class="h-rrm-stat-label">' + horusI18n.t('rrm_lbl_noise') + '</span><b class="h-rrm-stat-value" style="color:var(' + statusVar + ');">' + d.current_noise + ' dBm</b></div>' +
						'<div class="h-rrm-stat"><span class="h-rrm-stat-label">' + horusI18n.t('rrm_lbl_status') + '</span><b class="h-rrm-stat-value" style="color:var(' + statusVar + ');">' + statusLabel + '</b></div>' +
						'</div>' + recHtml;
				}).catch(function(e){
					el.innerHTML = '<span class="h-badge h-badge-error">' + horusI18n.t('rrm_scan_fail') + ': ' + e + '</span>';
				});
			};

			window.horusRefreshNeighbors = function() {
				var box = document.getElementById('horus_neighbors_box');
				if (!box) return;
				syncHorusSid();
				fetch('/cgi-bin/horus_peers?_=' + Date.now())
				.then(function(r){ if (!r.ok) throw new Error(r.status); return r.json(); })
				.then(function(d){
					if (d.status === 'error' || d.error) {
						box.innerHTML = '<div class="h-peer-empty">⚠️ ' + (d.message || d.error) + '</div>';
						return;
					}
					var keys = Object.keys(d || {});
					if (keys.length === 0) {
						box.innerHTML = '<div class="h-peer-empty">' + horusI18n.t('peer_empty') + '</div>';
					} else {
						var seenAps = {};
						keys.forEach(function(k){
							var p = d[k];
							if (p) {
								var sm = p.mac_5g || p.src_mac || k;
								if (!seenAps[sm] || p.medium_type === 'wireless_5g' || p.medium_type === 'wireless_2g') {
									seenAps[sm] = p;
								}
							}
						});
						var html = '<div class="h-table-wrapper"><table class="h-table">' +
							'<thead><tr>' +
							'<th>' + horusI18n.t('peer_th_host') + '</th>' +
							'<th>' + horusI18n.t('peer_th_ip') + '</th>' +
							'<th>' + horusI18n.t('peer_th_mac') + '</th>' +
							'<th>' + horusI18n.t('peer_th_sig') + '</th>' +
							'<th>' + horusI18n.t('peer_th_conn') + '</th>' +
							'</tr></thead><tbody>';

						Object.keys(seenAps).forEach(function(sm){
							var ap = seenAps[sm];
							var medIcon = '🔗', medLabel = (ap.medium || ap.band || 'Mesh Link'), medTone = 'muted';
							if (ap.medium_type === 'wireless_5g') { medIcon = '📶'; medLabel = horusI18n.t('peer_med_5g'); medTone = 'primary'; }
							else if (ap.medium_type === 'wireless_2g') { medIcon = '📶'; medLabel = horusI18n.t('peer_med_2g'); medTone = 'warning'; }
							else if (ap.medium_type === 'lan') { medIcon = '🔌'; medLabel = horusI18n.t('peer_med_lan'); medTone = 'success'; }

							var pIp = window.horusSafeIp(ap.ip) || '-';
							var pName = window.horusEsc(ap.hostname || 'Horus-AP');
							var pMac = window.horusEsc(ap.mac_5g || ap.src_mac || sm);
							var pSig = ap.signal ? (ap.signal + ' dBm ' + (ap.channel ? (' (Ch ' + ap.channel + ')') : '')) : '-';

							var ipHtml = pIp !== '-' ? '<a href="http://' + pIp + '" target="_blank" class="h-inj-link" style="color:var(--h-primary); font-weight:bold; text-decoration:none;">' + pIp + ' ↗</a>' : '-';

							html += '<tr>' +
								'<td><strong style="color:var(--h-text-main);"><span style="margin-inline-end:6px;">' + medIcon + '</span>' + pName + '</strong></td>' +
								'<td style="font-family: monospace, monospace; font-size: 13px;">' + ipHtml + '</td>' +
								'<td style="font-family: monospace, monospace; font-size: 13px; color:var(--h-text-muted);">' + pMac + '</td>' +
								'<td style="font-feature-settings: \'tnum\'; font-variant-numeric: tabular-nums;">' + window.horusEsc(pSig) + '</td>' +
								'<td><span class="h-badge h-badge-' + medTone + '">' + window.horusEsc(medLabel) + '</span></td>' +
								'</tr>';
						});
		
						html += '</tbody></table></div>';
						box.innerHTML = html;
					}
				}).catch(function(err){
					var box = document.getElementById('horus_neighbors_box');
					if (!box) return;
					box.innerHTML = '<span class="h-badge h-badge-error">' + horusI18n.t('peer_err') + '</span>';
				});
			};

			var wrapper = E('div', { class: 'horus-container horus-settings-view', 'dir': horusI18n.getDir() }, [
				horusStyles.getStyles(),
				topBar,
				heroCard,
				mapNode
			]);

			try {
				document.body.classList.add('horus-dark-active');
				document.documentElement.setAttribute('data-theme', 'dark');
			} catch(e) {}

			uci.load('system').then(function() {
				var sysHost = uci.get('system', '@system[0]', 'hostname');
				if (sysHost) heroName.textContent = sysHost;
			}).catch(function(){}).then(refreshHeroStatus);
			var heroTimer = window.setInterval(refreshHeroStatus, 10000);
			var neighborsTimer = window.setInterval(function() {
				var box = document.getElementById('horus_neighbors_box');
				if (box) window.horusRefreshNeighbors();
			}, 15000);

			// Pause all polling when tab is hidden — named function so it can
			// be properly removed when LuCI SPA navigates away from this view.
			function horusVisibilityHandler() {
				if (document.hidden) {
					clearInterval(heroTimer);
					clearInterval(neighborsTimer);
				} else {
					refreshHeroStatus();
					window.horusRefreshNeighbors();
					heroTimer = window.setInterval(refreshHeroStatus, 10000);
					neighborsTimer = window.setInterval(function() {
						var box = document.getElementById('horus_neighbors_box');
						if (box) window.horusRefreshNeighbors();
					}, 15000);
				}
			}
			document.addEventListener('visibilitychange', horusVisibilityHandler);

			// Cleanup on SPA navigation: remove listeners and stop all timers
			// so they don't keep firing on unrelated LuCI pages.
			function horusCleanup() {
				try {
					document.body.classList.remove('horus-dark-active');
					document.documentElement.removeAttribute('data-theme');
				} catch(e) {}
				clearInterval(heroTimer);
				clearInterval(neighborsTimer);
				document.removeEventListener('visibilitychange', horusVisibilityHandler);
				window.removeEventListener('pagehide', horusCleanup);
				window.removeEventListener('hashchange', recheckDependencies);
				delete window.horusEsc;
				delete window.horusSafeIp;
				delete window.horusApplyRrm;
				delete window.horusRefreshRrm;
				delete window.horusRefreshNeighbors;
			}
			window.addEventListener('pagehide', horusCleanup);

			setTimeout(function() {
				window.horusRefreshRrm();
				window.horusRefreshNeighbors();
			}, 300);

			return wrapper;
		});
	}
});
