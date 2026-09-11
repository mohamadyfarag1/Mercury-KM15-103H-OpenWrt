'use strict';
'require baseclass';
'require fs';
'require ui';
'require uci';
'require rpc';
'require network';
'require firewall';
'require poll';

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

function formatBytes(bytes) {
	bytes = parseInt(bytes, 10) || 0;
	if (bytes >= 1073741824) return (bytes / 1073741824).toFixed(1) + ' GB';
	if (bytes >= 1048576) return (bytes / 1048576).toFixed(1) + ' MB';
	if (bytes >= 1024) return (bytes / 1024).toFixed(1) + ' KB';
	return bytes + ' B';
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

function fetchStatus() {
	return fetch('/cgi-bin/port_action?action=status').then(function(res) {
		if (!res.ok) throw new Error('HTTP ' + res.status);
		return res.json();
	}).catch(function() {
		return fs.exec('/usr/bin/port_control', [ 'status' ]).then(function(res) {
			return JSON.parse(res.stdout || '{}');
		});
	});
}

var _lastCpuTotal = null;
var _lastCpuIdle = null;

function calculateCpuUsage(statLine) {
	if (!statLine) return null;
	var parts = statLine.trim().split(/\s+/);
	if (parts[0] !== 'cpu' || parts.length < 5) return null;

	var user = parseInt(parts[1], 10) || 0;
	var nice = parseInt(parts[2], 10) || 0;
	var sys  = parseInt(parts[3], 10) || 0;
	var idle = parseInt(parts[4], 10) || 0;
	var iow  = parseInt(parts[5], 10) || 0;
	var irq  = parseInt(parts[6], 10) || 0;
	var sirq = parseInt(parts[7], 10) || 0;
	var stl  = parseInt(parts[8], 10) || 0;

	var total = user + nice + sys + idle + iow + irq + sirq + stl;
	var idleAll = idle + iow;

	var res = null;
	if (_lastCpuTotal !== null && total > _lastCpuTotal) {
		var diffTotal = total - _lastCpuTotal;
		var diffIdle = idleAll - _lastCpuIdle;
		var used = (diffTotal > 0) ? Math.max(0, Math.min(100, Math.round((1 - (diffIdle / diffTotal)) * 100))) : 0;
		res = {
			used: used,
			free: 100 - used
		};
	}

	_lastCpuTotal = total;
	_lastCpuIdle = idleAll;
	return res;
}

function getTempColor(temp) {
	if (temp >= 80) return '#ef4444'; // Red: Hot (>= 80°C)
	if (temp >= 65) return '#f59e0b'; // Amber: Warm (65-79°C)
	return '#10b981'; // Green: Normal (< 65°C)
}

return baseclass.extend({
	title: '',

	// Fast non-blocking load: only reads lightweight static/cached configurations
	load: function() {
		return Promise.all([
			L.resolveDefault(callGetBuiltinEthernetPorts(), []),
			L.resolveDefault(fs.read('/etc/board.json'), '{}'),
			L.resolveDefault(firewall.getZones(), []),
			L.resolveDefault(network.getNetworks(), []),
			L.resolveDefault(uci.load('network'), null),
			L.resolveDefault(uci.load('wireless'), null),
			L.resolveDefault(fs.list('/etc/horus/disabled_ports'), [])
		]);
	},

	render: function(data) {
		var container = E('div', {
			'class': 'km15-status-cards',
			'style': 'display:flex; flex-wrap:wrap; justify-content:center; gap:8px; margin-bottom:1.5em; align-items:stretch;'
		});

		try {
			var board = JSON.parse(data[1] || '{}'),
			    known_ports = [],
			    port_map = buildInterfaceMapping(data[2], data[3]),
			    disabled_ports_files = data[6] || [];

			var disabledMap = {};
			disabled_ports_files.forEach(function(f) {
				if (f && f.name) disabledMap[f.name] = true;
			});

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

			// 1. CPU Dashboard Box
			var cpuCard = E('div', {
				'class': 'ifacebox',
				'id': 'km15-card-cpu',
				'style': 'margin:.35em; width:124px; min-width:124px; max-width:124px; border-radius:8px; overflow:hidden; box-shadow:0 1px 3px rgba(0,0,0,0.1); border:1px solid #99f6e4; display:flex; flex-direction:column; justify-content:space-between;'
			}, [
				E('div', {
					'class': 'ifacebox-head',
					'style': 'background:#0f766e; color:#fff; font-weight:bold; font-size:12px; height:24px; line-height:24px; text-align:center;'
				}, [ _('CPU / المعالج') ]),
				E('div', {
					'class': 'ifacebox-body',
					'style': 'height:78px; padding:4px 6px; background:#fff; display:flex; flex-direction:column; justify-content:center; align-items:center;'
				}, [
					E('div', {
						'id': 'km15-cpu-temp',
						'style': 'margin-bottom:4px; font-size:10px; font-weight:700; padding:1px 8px; border-radius:10px; color:#fff; background:#10b981;',
						'title': _('CPU Temperature / درجة حرارة المعالج')
					}, [ '🌡️ --°C' ]),
					E('div', {
						'style': 'width:100%; background:#e2e8f0; border-radius:4px; height:7px; overflow:hidden; margin-bottom:4px;'
					}, [
						E('div', {
							'id': 'km15-cpu-bar',
							'style': 'width:0%; height:100%; background:#10b981; transition:width 0.4s ease, background 0.4s ease;'
						})
					]),
					E('div', { 'style': 'font-size:10px; font-weight:700; color:#1e293b; line-height:1.2; text-align:center;' }, [
						E('span', { 'id': 'km15-cpu-used', 'style': 'color:#0f766e;' }, [ _('Used: --%') ]),
						E('br'),
						E('span', { 'id': 'km15-cpu-free', 'style': 'color:#64748b; font-weight:600;' }, [ _('Free: --%') ])
					])
				]),
				E('div', { 'class': 'ifacebox-head', 'style': 'height:3px; background:#0f766e;' }),
				E('div', {
					'class': 'ifacebox-body',
					'style': 'padding:6px 4px; background:#f8fafc; border-top:1px solid #f1f5f9; display:flex; flex-direction:column; justify-content:space-between; flex:1;'
				}, [
					E('div', { 'style': 'text-align:center; font-size:10px; line-height:1.4; color:#475569; min-height:38px;' }, [
						E('div', { 'id': 'km15-cpu-load', 'style': 'font-weight:600; color:#334155; margin-bottom:2px;' }, [ 'Load: --' ]),
						E('div', { 'style': 'font-size:9px; color:#64748b;' }, [ 'MT7621AT @ 880M' ]),
						E('div', { 'style': 'font-size:9px; color:#10b981; font-weight:700;' }, [ '● Live' ])
					])
				])
			]);
			container.appendChild(cpuCard);

			// 2. Ethernet Port Cards (WAN, LAN1..4)
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

				var iconState = isDisabled ? 'down' : (carrier ? 'up' : 'down');
				var headerBg = (devname === 'wan') ? '#0284c7' : '#0ea5e9';
				var isWan = (devname === 'wan');
				var portLabel = isWan ? 'WAN' : devname.toUpperCase();

				var actionBtn = E('button', {
					'id': 'km15-btn-' + devname,
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
								window.setTimeout(doLiveUpdate, 800);
							}).catch(function(e) {
								ui.addNotification(null, E('p', 'Error: ' + e));
								ev.target.disabled = false;
							});
						}
					}
				}, [ isDisabled ? _('Enable / تفعيل') : _('Disable / إيقاف') ]);

				var tx_b = port.netdev ? (port.netdev.getTXBytes() || 0) : 0;
				var rx_b = port.netdev ? (port.netdev.getRXBytes() || 0) : 0;

				var portCard = E('div', {
					'class': 'ifacebox',
					'id': 'km15-card-' + devname,
					'style': 'margin:.35em; width:124px; min-width:124px; max-width:124px; border-radius:8px; overflow:hidden; box-shadow:0 1px 3px rgba(0,0,0,0.1); border:1px solid ' + (isDisabled ? '#f87171' : '#cbd5e1') + '; display:flex; flex-direction:column; justify-content:space-between;'
				}, [
					E('div', {
						'class': 'ifacebox-head',
						'style': 'background:' + headerBg + '; color:#fff; font-weight:bold; font-size:12px; height:24px; line-height:24px; text-align:center;'
					}, [ portLabel ]),
					E('div', { 'class': 'ifacebox-body', 'style': 'height:78px; padding:6px 4px; background:#fff; display:flex; flex-direction:column; justify-content:center; align-items:center;' }, [
						E('img', {
							'id': 'km15-icon-' + devname,
							'src': L.resource('icons/port_%s.png').format(iconState),
							'style': 'height:26px; width:26px; vertical-align:middle;' + (isDisabled ? 'filter:grayscale(100%) opacity(50%);' : '')
						}),
						E('div', { 'id': 'km15-speed-' + devname, 'style': 'font-size:11px; margin-top:5px; font-weight:600; line-height:1.2;' }, [ formatSpeed(carrier, speed, duplex, isDisabled) ])
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
							E('span', { 'style': 'color:#10b981;' }, '\u25b2 '),
							E('span', { 'id': 'km15-tx-' + devname }, [ formatBytes(tx_b) ]),
							E('br'),
							E('span', { 'style': 'color:#3b82f6;' }, '\u25bc '),
							E('span', { 'id': 'km15-rx-' + devname }, [ formatBytes(rx_b) ]),
							port.netdev ? E('span', { 'class': 'cbi-tooltip' }, formatStats(port.netdev)) : ''
						]),
						actionBtn
					])
				]);

				container.appendChild(portCard);
			});

			// 3. Wi-Fi Radios (Wi-Fi 2.4G, Wi-Fi 5G)
			var radios = [
				{ id: 'radio0', label: 'Wi-Fi 2.4G', default_ssid: 'Horus-2.4G' },
				{ id: 'radio1', label: 'Wi-Fi 5G',  default_ssid: 'Horus-5G' }
			];

			radios.forEach(function(r) {
				var isDisabled = false;
				var channel = 'Auto';
				var htmode = '';
				var iface_ssid = r.default_ssid;

				try {
					if (uci.get('wireless', r.id, 'disabled') === '1') isDisabled = true;
					channel = uci.get('wireless', r.id, 'channel') || channel;
					htmode = uci.get('wireless', r.id, 'htmode') || '';

					var ifaces = uci.sections('wireless', 'wifi-iface') || [];
					for (var j = 0; j < ifaces.length; j++) {
						if (ifaces[j].device === r.id) {
							iface_ssid = ifaces[j].ssid || iface_ssid;
							break;
						}
					}
				} catch (e) {}

				var wifiActionBtn = E('button', {
					'id': 'km15-wifibtn-' + r.id,
					'class': 'btn btn-sm ' + (isDisabled ? 'btn-primary' : 'btn-danger'),
					'style': 'width:100%; font-size:11px; height:26px; padding:2px 4px; margin-top:6px; font-weight:700; border-radius:4px; cursor:pointer; display:flex; align-items:center; justify-content:center;',
					'click': function(ev) {
						ev.preventDefault();
						ev.target.disabled = true;
						ev.target.innerText = '...';
						executeWifiAction(r.id).then(function() {
							window.setTimeout(doLiveUpdate, 1500);
						}).catch(function(e) {
							ui.addNotification(null, E('p', 'Error: ' + e));
							ev.target.disabled = false;
						});
					}
				}, [ isDisabled ? _('Turn On / تشغيل') : _('Turn Off / إيقاف') ]);

				var statusBadge = E('span', {
					'id': 'km15-wifistate-' + r.id,
					'style': 'display:inline-block; font-size:10px; font-weight:700; padding:1px 8px; border-radius:10px; color:#fff; background:' + (isDisabled ? '#94a3b8' : '#10b981') + ';'
				}, [ isDisabled ? 'OFF' : 'ON' ]);

				var tempBadge = E('span', {
					'id': 'km15-wifitemp-' + r.id,
					'style': 'display:inline-block; margin-left:4px; font-size:10px; font-weight:700; padding:1px 6px; border-radius:10px; color:#fff; background:#10b981;',
					'title': _('Wireless Radio Temperature / درجة حرارة الكارت')
				}, [ '🌡️ --°C' ]);

				var wifiCard = E('div', {
					'class': 'ifacebox',
					'id': 'km15-card-' + r.id,
					'style': 'margin:.35em; width:124px; min-width:124px; max-width:124px; border-radius:8px; overflow:hidden; box-shadow:0 1px 3px rgba(0,0,0,0.1); border:1px solid ' + (isDisabled ? '#cbd5e1' : '#60a5fa') + '; display:flex; flex-direction:column; justify-content:space-between;'
				}, [
					E('div', {
						'class': 'ifacebox-head',
						'style': 'background:' + (r.id === 'radio1' ? '#4f46e5' : '#2563eb') + '; color:#fff; font-weight:bold; font-size:12px; height:24px; line-height:24px; text-align:center;'
					}, [ r.label ]),
					E('div', { 'class': 'ifacebox-body', 'style': 'height:78px; padding:6px 4px; background:#fff; display:flex; flex-direction:column; justify-content:center; align-items:center;' }, [
						E('div', { 'style': 'margin-bottom:3px; display:flex; align-items:center; justify-content:center;' }, [ statusBadge, tempBadge ]),
						E('div', { 'id': 'km15-wifissid-' + r.id, 'style': 'font-size:12px; font-weight:700; color:#1e293b; overflow:hidden; text-overflow:ellipsis; white-space:nowrap; max-width:116px; margin-bottom:2px;' }, [ iface_ssid ]),
						E('div', { 'id': 'km15-wifichan-' + r.id, 'style': 'font-size:10px; color:#64748b; overflow:hidden; text-overflow:ellipsis; white-space:nowrap; max-width:116px;' }, [
							isDisabled ? _('Disabled / معطل') : (channel + (htmode ? ' (' + htmode + ')' : ''))
						])
					]),
					E('div', { 'id': 'km15-wifibar-' + r.id, 'class': 'ifacebox-head', 'style': 'height:3px; background:' + (isDisabled ? '#cbd5e1' : '#10b981') + ';' }),
					E('div', { 'class': 'ifacebox-body', 'style': 'padding:6px 4px; background:#f8fafc; border-top:1px solid #f1f5f9; display:flex; flex-direction:column; justify-content:space-between; flex:1;' }, [
						E('div', { 'style': 'text-align:left; font-size:11px; line-height:1.4; color:#475569; min-height:38px;' }, [
							E('span', { 'style': 'color:#10b981;' }, '\u25b2 '),
							E('span', { 'id': 'km15-wifitx-' + r.id }, [ '0 B' ]),
							E('br'),
							E('span', { 'style': 'color:#3b82f6;' }, '\u25bc '),
							E('span', { 'id': 'km15-wifirx-' + r.id }, [ '0 B' ])
						]),
						wifiActionBtn
					])
				]);

				container.appendChild(wifiCard);
			});

			// Asynchronous in-place DOM updater function
			function applyLiveStatus(st) {
				if (!st) return;

				// Update CPU card
				if (st.cpu) {
					var cpuUsage = calculateCpuUsage(st.cpu.stat);
					var usedElem = document.getElementById('km15-cpu-used');
					var freeElem = document.getElementById('km15-cpu-free');
					var barElem  = document.getElementById('km15-cpu-bar');

					if (cpuUsage && usedElem && freeElem && barElem) {
						usedElem.innerText = _('Used: %d%').format(cpuUsage.used);
						freeElem.innerText = _('Free: %d%').format(cpuUsage.free);
						barElem.style.width = cpuUsage.used + '%';
						barElem.style.background = (cpuUsage.used >= 85) ? '#ef4444' : ((cpuUsage.used >= 60) ? '#f59e0b' : '#10b981');
					} else if (st.cpu.loadavg && usedElem && usedElem.innerText.indexOf('--%') !== -1) {
						var l1 = parseFloat(st.cpu.loadavg.split(' ')[0]) || 0;
						var estUsed = Math.min(100, Math.round(l1 * 50));
						usedElem.innerText = _('Used: ~%d%').format(estUsed);
						freeElem.innerText = _('Free: ~%d%').format(100 - estUsed);
						if (barElem) barElem.style.width = estUsed + '%';
					}

					var tempElem = document.getElementById('km15-cpu-temp');
					if (tempElem) {
						var cTemp = parseInt(st.cpu.temp, 10) || 0;
						if (cTemp > 0 && cTemp < 150) {
							tempElem.innerText = '🌡️ ' + cTemp + '°C';
							tempElem.style.background = getTempColor(cTemp);
						} else {
							tempElem.innerText = '🌡️ --°C';
						}
					}

					var loadElem = document.getElementById('km15-cpu-load');
					if (loadElem && st.cpu.loadavg) {
						var lparts = st.cpu.loadavg.split(/\s+/);
						loadElem.innerText = 'Load: ' + (lparts.slice(0, 2).join(', ') || '--');
					}
				}

				// Update Ethernet port cards
				if (st.ports) {
					for (var p in st.ports) {
						var cp = st.ports[p];
						var cardNode = document.getElementById('km15-card-' + p);
						var iconNode = document.getElementById('km15-icon-' + p);
						var speedNode = document.getElementById('km15-speed-' + p);
						var btnNode = document.getElementById('km15-btn-' + p);
						var txNode = document.getElementById('km15-tx-' + p);
						var rxNode = document.getElementById('km15-rx-' + p);

						var isDis = !!cp.disabled;
						var car   = !!cp.carrier;
						var sp    = parseInt(cp.speed, 10) || 0;
						var dup   = cp.duplex || '';

						if (cardNode) {
							cardNode.style.borderColor = isDis ? '#f87171' : (car ? '#60a5fa' : '#cbd5e1');
						}

						if (iconNode) {
							var icState = isDis ? 'down' : (car ? 'up' : 'down');
							iconNode.src = L.resource('icons/port_%s.png').format(icState);
							iconNode.style.filter = isDis ? 'grayscale(100%) opacity(50%)' : '';
						}

						if (speedNode) {
							speedNode.innerText = '';
							speedNode.appendChild(formatSpeed(car, sp, dup, isDis));
						}

						if (btnNode) {
							btnNode.disabled = false;
							btnNode.className = 'btn btn-sm ' + (isDis ? 'btn-primary' : 'btn-danger');
							btnNode.innerText = isDis ? _('Enable / تفعيل') : _('Disable / إيقاف');
						}

						if (txNode && cp.tx_bytes !== undefined) txNode.innerText = formatBytes(cp.tx_bytes);
						if (rxNode && cp.rx_bytes !== undefined) rxNode.innerText = formatBytes(cp.rx_bytes);
					}
				}

				// Update Wireless cards
				if (st.wireless) {
					for (var r in st.wireless) {
						var rw = st.wireless[r];
						var wCardNode  = document.getElementById('km15-card-' + r);
						var wStateNode = document.getElementById('km15-wifistate-' + r);
						var wTempNode  = document.getElementById('km15-wifitemp-' + r);
						var wSsidNode  = document.getElementById('km15-wifissid-' + r);
						var wChanNode  = document.getElementById('km15-wifichan-' + r);
						var wBarNode   = document.getElementById('km15-wifibar-' + r);
						var wBtnNode   = document.getElementById('km15-wifibtn-' + r);
						var wTxNode    = document.getElementById('km15-wifitx-' + r);
						var wRxNode    = document.getElementById('km15-wifirx-' + r);

						var isDis = (rw.disabled === 1 || rw.disabled === '1');

						if (wCardNode) {
							wCardNode.style.borderColor = isDis ? '#cbd5e1' : '#60a5fa';
						}

						if (wStateNode) {
							wStateNode.innerText = isDis ? 'OFF' : 'ON';
							wStateNode.style.background = isDis ? '#94a3b8' : '#10b981';
						}

						if (wTempNode) {
							var t = parseInt(rw.temp, 10) || 0;
							if (t > 0 && t < 150) {
								wTempNode.innerText = '🌡️ ' + t + '°C';
								wTempNode.style.background = getTempColor(t);
								wTempNode.style.display = 'inline-block';
							} else {
								wTempNode.innerText = '🌡️ --°C';
							}
						}

						if (wSsidNode && rw.ssid) {
							wSsidNode.innerText = rw.ssid;
						}

						if (wChanNode) {
							if (isDis) {
								wChanNode.innerText = _('Disabled / معطل');
							} else {
								var chStr = rw.channel ? ('CH ' + rw.channel) : 'Auto';
								if (rw.htmode) chStr += ' (' + rw.htmode + ')';
								if (rw.clients !== undefined && rw.clients > 0) {
									chStr += ' • ' + rw.clients + ' ' + _('clients');
								}
								wChanNode.innerText = chStr;
							}
						}

						if (wBarNode) {
							wBarNode.style.background = isDis ? '#cbd5e1' : '#10b981';
						}

						if (wBtnNode) {
							wBtnNode.disabled = false;
							wBtnNode.className = 'btn btn-sm ' + (isDis ? 'btn-primary' : 'btn-danger');
							wBtnNode.innerText = isDis ? _('Turn On / تشغيل') : _('Turn Off / إيقاف');
						}

						if (wTxNode && rw.tx_bytes !== undefined) wTxNode.innerText = formatBytes(rw.tx_bytes);
						if (wRxNode && rw.rx_bytes !== undefined) wRxNode.innerText = formatBytes(rw.rx_bytes);
					}
				}
			}

			function doLiveUpdate() {
				return fetchStatus().then(function(res) {
					applyLiveStatus(res);
				}).catch(function(e) {
					console.warn('km15 live update error:', e);
				});
			}

			// Immediate non-blocking update (50ms after render)
			window.setTimeout(doLiveUpdate, 50);

			// Fast follow-up at 1.2s to compute initial CPU delta percentage
			window.setTimeout(doLiveUpdate, 1200);

			// Periodic live update every 3 seconds
			poll.add(doLiveUpdate, 3);

			return container;
		} catch (err) {
			console.error('Error rendering 29_ports:', err);
			return container;
		}
	}
});
