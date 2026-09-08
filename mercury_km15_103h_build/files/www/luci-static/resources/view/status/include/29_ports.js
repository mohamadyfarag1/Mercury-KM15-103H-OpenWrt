'use strict';
'require baseclass';
'require fs';
'require ui';
'require uci';
'require rpc';
'require network';
'require firewall';

var callGetBuiltinEthernetPorts = rpc.declare({
	object: 'luci',
	method: 'getBuiltinEthernetPorts',
	expect: { result: [] }
});

function isString(v) {
	return typeof(v) === 'string' && v !== '';
}

function resolveVLANChain(ifname, bridges, mapping) {
	while (!mapping[ifname]) {
		var m = ifname.match(/^(.+)\.([^.]+)$/);
		if (!m) break;

		if (bridges[m[1]]) {
			if (bridges[m[1]].vlan_filtering)
				mapping[ifname] = bridges[m[1]].vlans[m[2]];
			else
				mapping[ifname] = bridges[m[1]].ports;
		}
		else if (/^[0-9]{1,4}$/.test(m[2]) && m[2] <= 4095) {
			mapping[ifname] = [ m[1] ];
		}
		else {
			break;
		}

		ifname = m[1];
	}
}

function buildVLANMappings(mapping) {
	var bridge_vlans = uci.sections('network', 'bridge-vlan'),
	    vlan_devices = uci.sections('network', 'device'),
	    bridges = {};

	for (var i = 0, s; (s = bridge_vlans[i]) != null; i++) {
		if (!isString(s.device) || !/^[0-9]{1,4}$/.test(s.vlan) || +s.vlan > 4095)
			continue;

		var aliases = L.toArray(s.alias),
		    ports = L.toArray(s.ports),
		    br = bridges[s.device] = (bridges[s.device] || { ports: [], vlans: {}, vlan_filtering: true });

		br.vlans[s.vlan] = [];

		for (var j = 0; j < ports.length; j++) {
			var port = ports[j].replace(/:[ut*]+$/, '');
			if (br.ports.indexOf(port) === -1)
				br.ports.push(port);
			br.vlans[s.vlan].push(port);
		}

		for (var j = 0; j < aliases.length; j++)
			if (aliases[j] != s.vlan)
				br.vlans[aliases[j]] = br.vlans[s.vlan];
	}

	for (var i = 0, s; (s = vlan_devices[i]) != null; i++) {
		if (s.type == 'bridge') {
			if (!isString(s.name))
				continue;

			var ports = L.toArray(s.ports),
			    br = bridges[s.name] || (bridges[s.name] = { ports: [], vlans: {}, vlan_filtering: false });

			if (s.vlan_filtering == '0')
				br.vlan_filtering = false;
			else if (s.vlan_filtering == '1')
				br.vlan_filtering = true;

			for (var j = 0; j < ports.length; j++)
				if (br.ports.indexOf(ports[j]) === -1)
					br.ports.push(ports[j]);

			mapping[s.name] = br.ports;
		}
		else if (s.type == '8021q' || s.type == '8021ad') {
			if (!isString(s.name) || !isString(s.vid) || !isString(s.ifname))
				continue;

			if (bridges[s.ifname]) {
				if (bridges[s.ifname].vlan_filtering)
					mapping[s.name] = bridges[s.ifname].vlans[s.vid];
				else
					mapping[s.name] = bridges[s.ifname].ports;
			}
			else {
				mapping[s.name] = [ s.ifname ];
			}

			resolveVLANChain(s.ifname, bridges, mapping);
		}
	}

	for (var brname in bridges) {
		for (var i = 0; i < bridges[brname].ports.length; i++)
			resolveVLANChain(bridges[brname].ports[i], bridges, mapping);

		for (var vid in bridges[brname].vlans)
			for (var i = 0; i < bridges[brname].vlans[vid].length; i++)
				resolveVLANChain(bridges[brname].vlans[vid][i], bridges, mapping);
	}
}

function resolveVLANPorts(ifname, mapping, seen) {
	var ports = [];
	if (!seen) seen = {};

	if (mapping[ifname]) {
		for (var i = 0; i < mapping[ifname].length; i++) {
			if (!seen[mapping[ifname][i]]) {
				seen[mapping[ifname][i]] = true;
				ports.push.apply(ports, resolveVLANPorts(mapping[ifname][i], mapping, seen));
			}
		}
	}
	else {
		ports.push(ifname);
	}

	return ports.sort(L.naturalCompare);
}

function buildInterfaceMapping(zones, networks) {
	var vlanmap = {},
	    portmap = {},
	    netmap = {};

	buildVLANMappings(vlanmap);

	for (var i = 0; i < (networks || []).length; i++) {
		var l3dev = networks[i].getDevice();
		if (!l3dev) continue;

		var ports = resolveVLANPorts(l3dev.getName(), vlanmap);
		for (var j = 0; j < ports.length; j++) {
			portmap[ports[j]] = portmap[ports[j]] || { networks: [], zones: [] };
			portmap[ports[j]].networks.push(networks[i]);
		}
		netmap[networks[i].getName()] = networks[i];
	}

	for (var i = 0; i < (zones || []).length; i++) {
		var networknames = zones[i].getNetworks();
		for (var j = 0; j < networknames.length; j++) {
			if (!netmap[networknames[j]]) continue;
			var l3dev = netmap[networknames[j]].getDevice();
			if (!l3dev) continue;

			var ports = resolveVLANPorts(l3dev.getName(), vlanmap);
			for (var k = 0; k < ports.length; k++) {
				portmap[ports[k]] = portmap[ports[k]] || { networks: [], zones: [] };
				if (portmap[ports[k]].zones.indexOf(zones[i]) === -1)
					portmap[ports[k]].zones.push(zones[i]);
			}
		}
	}

	return portmap;
}

function formatSpeed(carrier, speed, duplex, isDisabled) {
	if (isDisabled) {
		return E('span', { 'style': 'color:#ef4444; font-weight:700;' }, [ _('Disabled / معطل') ]);
	}

	if (carrier && speed > 0 && duplex && duplex !== 'unknown') {
		var d = (duplex == 'half') ? '\u202f(H)' : '',
		    e = E('span', { 'title': _('Speed: %d Mibit/s, Duplex: %s').format(speed, duplex) });

		switch (speed) {
		case 10:    e.innerText = '10\u202fM' + d;  break;
		case 100:   e.innerText = '100\u202fM' + d; break;
		case 1000:  e.innerText = '1\u202fGbE' + d; break;
		case 2500:  e.innerText = '2.5\u202fGbE';   break;
		case 5000:  e.innerText = '5\u202fGbE';     break;
		case 10000: e.innerText = '10\u202fGbE';    break;
		default:    e.innerText = '%d\u202fMbE%s'.format(speed, d);
		}
		return e;
	}

	return carrier ? _('Connected / متصل') : _('No link / لا يوجد رابط');
}

function formatStats(portdev) {
	var stats = (portdev && portdev._devstate ? portdev._devstate('stats') : {}) || {};

	return ui.itemlist(E('span'), [
		_('Received bytes'), '%1024mB'.format(stats.rx_bytes || 0),
		_('Received packets'), '%1000mPkts.'.format(stats.rx_packets || 0),
		_('Transmitted bytes'), '%1024mB'.format(stats.tx_bytes || 0),
		_('Transmitted packets'), '%1000mPkts.'.format(stats.tx_packets || 0)
	]);
}

function renderNetworksTooltip(pmap) {
	var res = [ null ], zmap = {};

	if (!pmap)
		return _('Port is not part of any network');

	for (var i = 0; pmap.zones && i < pmap.zones.length; i++) {
		var z = pmap.zones[i];
		if (!z || typeof(z.getNetworks) !== 'function') continue;
		var networknames = z.getNetworks();
		for (var k = 0; k < networknames.length; k++)
			zmap[networknames[k]] = (typeof(z.getName) === 'function') ? z.getName() : '';
	}

	for (var i = 0; pmap.networks && i < pmap.networks.length; i++) {
		var net = pmap.networks[i];
		if (!net || typeof(net.getName) !== 'function') continue;
		var netName = net.getName();
		var l3dev = (typeof(net.getDevice) === 'function') ? net.getDevice() : null;
		var badgeStyle = (firewall && typeof(firewall.getZoneColorStyle) === 'function') ? firewall.getZoneColorStyle(zmap[netName]) : '';
		var span = E('span', { 'class': 'ifacebadge', 'style': 'margin:.125em 0' }, [
			E('span', {
				'class': 'zonebadge',
				'style': badgeStyle
			}, '\u202f'),
			'\u202f', netName, ': '
		]);
		if (l3dev && typeof(l3dev.getType) === 'function') {
			var isUp = (typeof(l3dev.isUp) === 'function') ? l3dev.isUp() : false;
			span.appendChild(E('img', {
				'src': L.resource('icons/%s%s.png'.format(l3dev.getType(), isUp ? '' : '_disabled'))
			}));
		}
		res.push(E('br'), span);
	}

	if (res.length > 2)
		res[0] = _('Part of networks:');
	else if (res.length > 1)
		res[0] = _('Part of network:');
	else
		res[0] = _('Port is not part of any network');

	return E([], res);
}

function executePortAction(port, action) {
	var url = '/cgi-bin/port_action?port=' + encodeURIComponent(port) + '&action=' + encodeURIComponent(action);
	return fetch(url).then(function(res) {
		return res.json();
	}).catch(function() {
		return fs.exec('/usr/bin/port_control', [ 'set', port, action ]);
	});
}

function executeWifiAction(radio) {
	var url = '/cgi-bin/port_action?action=toggle_wifi&radio=' + encodeURIComponent(radio);
	return fetch(url).then(function(res) {
		return res.json();
	}).catch(function() {
		return fs.exec('/usr/bin/port_control', [ 'toggle_wifi', radio ]);
	});
}

return baseclass.extend({
	title: '',

	load: function() {
		return Promise.all([
			L.resolveDefault(callGetBuiltinEthernetPorts(), []),
			L.resolveDefault(fs.read('/etc/board.json'), '{}'),
			L.resolveDefault(firewall.getZones(), []),
			L.resolveDefault(network.getNetworks(), []),
			L.resolveDefault(uci.load('network'), null),
			L.resolveDefault(uci.load('wireless'), null),
			L.resolveDefault(fs.list('/etc/horus/disabled_ports'), []),
			L.resolveDefault(network.getWifiDevices(), []),
			L.resolveDefault(fs.exec('/usr/bin/port_control', [ 'status' ]), null),
			L.resolveDefault(network.getWifiNetworks(), [])
		]);
	},

	render: function(data) {
		var cards = [];
		try {
			var board = JSON.parse(data[1] || '{}'),
			    known_ports = [],
			    port_map = buildInterfaceMapping(data[2], data[3]),
			    disabled_ports_files = data[6] || [],
			    wifi_devices = data[7] || [],
			    port_ctl_raw = data[8] ? (data[8].stdout || '') : '',
			    wifi_networks = data[9] || [],
			    port_ctl = null;

			try {
				if (port_ctl_raw) port_ctl = JSON.parse(port_ctl_raw);
			} catch (e) {}

			var disabledMap = {};
			disabled_ports_files.forEach(function(f) {
				if (f && f.name) disabledMap[f.name] = true;
			});

			if (port_ctl && port_ctl.ports) {
				for (var p in port_ctl.ports) {
					if (port_ctl.ports[p].disabled) disabledMap[p] = true;
				}
			}

			if (Array.isArray(data[0]) && data[0].length > 0) {
				known_ports = data[0].map(function(port) {
					return {
						role: port.role,
						device: port.device,
						netdev: network.instantiateDevice(port.device)
					};
				});
			}
			else {
				if (L.isObject(board) && L.isObject(board.network)) {
					for (var k = 'lan'; k != null; k = (k == 'lan') ? 'wan' : null) {
						if (!L.isObject(board.network[k])) continue;
						if (Array.isArray(board.network[k].ports)) {
							for (var i = 0; i < board.network[k].ports.length; i++) {
								known_ports.push({
									role: k,
									device: board.network[k].ports[i],
									netdev: network.instantiateDevice(board.network[k].ports[i])
								});
							}
						}
						else if (typeof(board.network[k].device) == 'string') {
							known_ports.push({
								role: k,
								device: board.network[k].device,
								netdev: network.instantiateDevice(board.network[k].device)
							});
						}
					}
				}
			}

			if (known_ports.length === 0) {
				[ 'lan1', 'lan2', 'lan3', 'lan4', 'wan' ].forEach(function(devname) {
					known_ports.push({
						role: (devname === 'wan') ? 'wan' : 'lan',
						device: devname,
						netdev: network.instantiateDevice(devname)
					});
				});
			}

			known_ports.sort(function(a, b) {
				return L.naturalCompare(a.device, b.device);
			});

			known_ports.forEach(function(port) {
				var devname = port.netdev ? port.netdev.getName() : port.device,
				    speed = port.netdev ? port.netdev.getSpeed() : null,
				    duplex = port.netdev ? port.netdev.getDuplex() : null,
				    carrier = port.netdev ? port.netdev.getCarrier() : false,
				    isDisabled = !!disabledMap[devname],
				    pmap = port_map[devname];
				var pzones = [ null ];
				if (pmap && Array.isArray(pmap.zones) && pmap.zones.length > 0) {
					pzones = pmap.zones.filter(Boolean).sort(function(a, b) {
						var an = (a && typeof(a.getName) === 'function') ? a.getName() : '';
						var bn = (b && typeof(b.getName) === 'function') ? b.getName() : '';
						return L.naturalCompare(an, bn);
					});
					if (pzones.length === 0) pzones = [ null ];
				}

				if (port_ctl && port_ctl.ports && port_ctl.ports[devname]) {
					var cp = port_ctl.ports[devname];
					if (cp.carrier !== undefined) carrier = !!cp.carrier;
					if (cp.speed) speed = parseInt(cp.speed, 10);
					if (cp.duplex) duplex = cp.duplex;
					if (cp.disabled) isDisabled = true;
				}

				var iconState = isDisabled ? 'down' : (carrier ? 'up' : 'down');
				var headerBg = (devname === 'wan') ? '#0284c7' : '#0ea5e9';
				var isWan = (devname === 'wan');
				var portLabel = isWan ? 'WAN' : devname.toUpperCase();

				var actionBtn = E('button', {
					'class': 'btn btn-sm ' + (isDisabled ? 'btn-primary' : 'btn-danger'),
					'style': 'width:100%; font-size:11px; height:26px; padding:2px 4px; margin-top:6px; font-weight:700; border-radius:4px; cursor:pointer; display:flex; align-items:center; justify-content:center;',
					'click': function(ev) {
						ev.preventDefault();
						var nextAction = isDisabled ? 'enable' : 'disable';
						var confirmMsg = isDisabled
							? _('Are you sure you want to enable port %s? / هل تريد تفعيل المنفذ %s؟').format(devname, devname)
							: _('WARNING: Disabling port %s may disconnect you if you are connected through it! Continue? / تحذير: إيقاف المنفذ %s قد يفصل اتصالك بالجهاز! هل تريد المتابعة؟').format(devname, devname);

						if (confirm(confirmMsg)) {
							ev.target.disabled = true;
							ev.target.innerText = '...';
							executePortAction(devname, nextAction).then(function() {
								setTimeout(function() { location.reload(); }, 600);
							}).catch(function(e) {
								ui.addNotification(null, E('p', 'Error: ' + e));
								ev.target.disabled = false;
							});
						}
					}
				}, [ isDisabled ? _('Enable / تفعيل') : _('Disable / إيقاف') ]);

				var tx_b = port.netdev ? (port.netdev.getTXBytes() || 0) : 0;
				var rx_b = port.netdev ? (port.netdev.getRXBytes() || 0) : 0;

				cards.push(E('div', {
					'class': 'ifacebox',
					'style': 'margin:.35em; width:124px; min-width:124px; max-width:124px; border-radius:8px; overflow:hidden; box-shadow:0 1px 3px rgba(0,0,0,0.1); border:1px solid ' + (isDisabled ? '#f87171' : '#cbd5e1') + '; display:flex; flex-direction:column; justify-content:space-between;'
				}, [
					E('div', {
						'class': 'ifacebox-head',
						'style': 'background:' + headerBg + '; color:#fff; font-weight:bold; font-size:12px; height:24px; line-height:24px; text-align:center;'
					}, [ portLabel ]),
					E('div', { 'class': 'ifacebox-body', 'style': 'height:78px; padding:6px 4px; background:#fff; display:flex; flex-direction:column; justify-content:center; align-items:center;' }, [
						E('img', {
							'src': L.resource('icons/port_%s.png').format(iconState),
							'style': 'height:26px; width:26px; vertical-align:middle;' + (isDisabled ? 'filter:grayscale(100%) opacity(50%);' : '')
						}),
						E('div', { 'style': 'font-size:11px; margin-top:5px; font-weight:600; line-height:1.2;' }, [ formatSpeed(carrier, speed, duplex, isDisabled) ])
					]),
					E('div', { 'class': 'ifacebox-head cbi-tooltip-container', 'style': 'display:flex; height:3px;' }, [
						E([], pzones.map(function(zone) {
							return E('div', {
								'class': 'zonebadge',
								'style': 'flex:1;height:3px;opacity:' + (carrier && !isDisabled ? 1 : 0.25) + ';' + firewall.getZoneColorStyle(zone)
							});
						})),
						E('span', { 'class': 'cbi-tooltip left' }, [ renderNetworksTooltip(pmap) ])
					]),
					E('div', { 'class': 'ifacebox-body', 'style': 'padding:6px 4px; background:#f8fafc; border-top:1px solid #f1f5f9; display:flex; flex-direction:column; justify-content:space-between; flex:1;' }, [
						E('div', { 'class': 'cbi-tooltip-container', 'style': 'text-align:left; font-size:11px; line-height:1.4; color:#475569; min-height:38px;' }, [
							E('span', { 'style': 'color:#10b981;' }, '\u25b2 '), '%1024.1mB'.format(tx_b),
							E('br'),
							E('span', { 'style': 'color:#3b82f6;' }, '\u25bc '), '%1024.1mB'.format(rx_b),
							port.netdev ? E('span', { 'class': 'cbi-tooltip' }, formatStats(port.netdev)) : ''
						]),
						actionBtn
					])
				]));
			});

			var radios = [
				{ id: 'radio0', label: 'Wi-Fi 2.4G', freq: '2.4 GHz', default_ssid: 'Horus-2.4G' },
				{ id: 'radio1', label: 'Wi-Fi 5G',  freq: '5 GHz',    default_ssid: 'Horus-5G' }
			];

			radios.forEach(function(r) {
				var isDisabled = false;
				var channel = 'Auto';
				var htmode = '';
				var iface_ssid = r.default_ssid;
				var iface_mode = 'AP';
				var iface_netdev = null;

				for (var wi = 0; wi < wifi_networks.length; wi++) {
					var wn = wifi_networks[wi];
					if (wn && wn.getDeviceName && wn.getDeviceName() === r.id) {
						if (wn.getSSID && wn.getSSID()) iface_ssid = wn.getSSID();
						if (wn.getMode && wn.getMode()) iface_mode = wn.getMode().toUpperCase();
						if (wn.getChannel && wn.getChannel()) channel = wn.getChannel();
						if (wn.isDisabled && wn.isDisabled()) isDisabled = true;
						if (wn.getDevice) {
							var nd = wn.getDevice();
							if (nd) iface_netdev = nd;
						}
						break;
					}
				}

				try {
					if (uci.get('wireless', r.id, 'disabled') === '1') isDisabled = true;
					channel = uci.get('wireless', r.id, 'channel') || channel;
					htmode = uci.get('wireless', r.id, 'htmode') || '';

					var ifaces = uci.sections('wireless', 'wifi-iface') || [];
					for (var j = 0; j < ifaces.length; j++) {
						if (ifaces[j].device === r.id) {
							iface_ssid = ifaces[j].ssid || iface_ssid;
							iface_mode = (ifaces[j].mode || iface_mode).toUpperCase();
							if (ifaces[j].ifname && !iface_netdev)
								iface_netdev = network.instantiateDevice(ifaces[j].ifname);
							break;
						}
					}
				} catch (e) {}

				if (port_ctl && port_ctl.wireless && port_ctl.wireless[r.id]) {
					var rw = port_ctl.wireless[r.id];
					if (rw.disabled !== undefined) isDisabled = (rw.disabled === 1 || rw.disabled === '1');
					if (rw.channel) channel = rw.channel;
					if (rw.htmode) htmode = rw.htmode;
					if (rw.ssid) iface_ssid = rw.ssid;
					if (rw.mode) iface_mode = rw.mode.toUpperCase();
					if (rw.ifname && !iface_netdev) iface_netdev = network.instantiateDevice(rw.ifname);
				}

				if (!iface_netdev) {
					var fallbackName = (r.id === 'radio0') ? 'phy0-ap0' : 'phy1-ap0';
					iface_netdev = network.instantiateDevice(fallbackName);
				}

				var tx_b = iface_netdev ? (iface_netdev.getTXBytes() || 0) : 0;
				var rx_b = iface_netdev ? (iface_netdev.getRXBytes() || 0) : 0;

				var wifiActionBtn = E('button', {
					'class': 'btn btn-sm ' + (isDisabled ? 'btn-primary' : 'btn-danger'),
					'style': 'width:100%; font-size:11px; height:26px; padding:2px 4px; margin-top:6px; font-weight:700; border-radius:4px; cursor:pointer; display:flex; align-items:center; justify-content:center;',
					'click': function(ev) {
						ev.preventDefault();
						ev.target.disabled = true;
						ev.target.innerText = '...';
						executeWifiAction(r.id).then(function() {
							setTimeout(function() { location.reload(); }, 1000);
						}).catch(function(e) {
							ui.addNotification(null, E('p', 'Error: ' + e));
							ev.target.disabled = false;
						});
					}
				}, [ isDisabled ? _('Turn On / تشغيل') : _('Turn Off / إيقاف') ]);

				var statusBadge = E('span', {
					'style': 'display:inline-block; font-size:10px; font-weight:700; padding:1px 8px; border-radius:10px; color:#fff; background:' + (isDisabled ? '#94a3b8' : '#10b981') + ';'
				}, [ isDisabled ? 'OFF' : 'ON' ]);

				var badges = [ statusBadge ];
				var r_temp = (port_ctl && port_ctl.wireless && port_ctl.wireless[r.id] && port_ctl.wireless[r.id].temp !== undefined)
					? parseInt(port_ctl.wireless[r.id].temp, 10) : 0;
				if (r_temp > 0) {
					var tempColor = '#10b981'; // Green: Normal (<65°C)
					if (r_temp >= 80) {
						tempColor = '#ef4444'; // Red: Hot (>=80°C)
					} else if (r_temp >= 65) {
						tempColor = '#f59e0b'; // Amber: Warm (65-79°C)
					}
					badges.push(E('span', {
						'style': 'display:inline-block; margin-left:4px; font-size:10px; font-weight:700; padding:1px 6px; border-radius:10px; color:#fff; background:' + tempColor + ';',
						'title': _('Wireless Radio Temperature / درجة حرارة الكارت')
					}, [ '\ud83c\udf21\ufe0f ' + r_temp + '\u00b0C' ]));
				}

				cards.push(E('div', {
					'class': 'ifacebox',
					'style': 'margin:.35em; width:124px; min-width:124px; max-width:124px; border-radius:8px; overflow:hidden; box-shadow:0 1px 3px rgba(0,0,0,0.1); border:1px solid ' + (isDisabled ? '#cbd5e1' : '#60a5fa') + '; display:flex; flex-direction:column; justify-content:space-between;'
				}, [
					E('div', {
						'class': 'ifacebox-head',
						'style': 'background:' + (r.id === 'radio1' ? '#4f46e5' : '#2563eb') + '; color:#fff; font-weight:bold; font-size:12px; height:24px; line-height:24px; text-align:center;'
					}, [ r.label ]),
					E('div', { 'class': 'ifacebox-body', 'style': 'height:78px; padding:6px 4px; background:#fff; display:flex; flex-direction:column; justify-content:center; align-items:center;' }, [
						E('div', { 'style': 'margin-bottom:3px; display:flex; align-items:center; justify-content:center;' }, badges),
						E('div', { 'style': 'font-size:12px; font-weight:700; color:#1e293b; overflow:hidden; text-overflow:ellipsis; white-space:nowrap; max-width:116px; margin-bottom:2px;' }, [ iface_ssid ]),
						E('div', { 'style': 'font-size:10px; color:#64748b; overflow:hidden; text-overflow:ellipsis; white-space:nowrap; max-width:116px;' }, [
							isDisabled ? _('Disabled / معطل') : (channel + (htmode ? ' (' + htmode + ')' : ''))
						])
					]),
					E('div', { 'class': 'ifacebox-head', 'style': 'height:3px; background:' + (isDisabled ? '#cbd5e1' : '#10b981') + ';' }),
					E('div', { 'class': 'ifacebox-body', 'style': 'padding:6px 4px; background:#f8fafc; border-top:1px solid #f1f5f9; display:flex; flex-direction:column; justify-content:space-between; flex:1;' }, [
						E('div', { 'style': 'text-align:left; font-size:11px; line-height:1.4; color:#475569; min-height:38px;' }, [
							E('span', { 'style': 'color:#10b981;' }, '\u25b2 '), '%1024.1mB'.format(tx_b),
							E('br'),
							E('span', { 'style': 'color:#3b82f6;' }, '\u25bc '), '%1024.1mB'.format(rx_b)
						]),
						wifiActionBtn
					])
				]));
			});

			return E('div', {
				'style': 'display:flex; flex-wrap:wrap; justify-content:center; gap:8px; margin-bottom:1.5em; align-items:stretch;'
			}, cards);
		} catch (err) {
			console.error('Error rendering 29_ports:', err);
			return cards.length ? E('div', {
				'style': 'display:flex; flex-wrap:wrap; justify-content:center; gap:8px; margin-bottom:1.5em; align-items:stretch;'
			}, cards) : E('div');
		}
	}
});
