// ====================================================================
// RADIUS Sync - Flicker-Free Synchronous LuCI Table Hook (v2.5)
// Real-time updates, cache-clearing on offline/disabled, instant feedback
// ====================================================================

(function() {
    'use strict';

    var cachedMap = {};
    var cachedMapByIp = {};
    var cachedArp = {};
    var currentStatus = 'unknown'; // 'online', 'offline', 'disabled'
    var currentRadiusType = '';
    var isFetching = false;

    function formatSession(secs) {
        secs = parseInt(secs) || 0;
        var d = Math.floor(secs / 86400);
        var h = Math.floor((secs % 86400) / 3600);
        var m = Math.floor((secs % 3600) / 60);
        if (d > 0) return d + 'd ' + h + 'h';
        if (h > 0) return h + 'h ' + m + 'm';
        return m + 'm';
    }

    function formatQuota(bytes) {
        if (bytes === null || bytes === undefined || bytes === '') return null;
        if (typeof bytes === 'string' && /[GMK]B/i.test(bytes)) return bytes;
        var b = parseFloat(bytes);
        if (b < 0) return 'غير محدود';
        if (isNaN(b) || b <= 0) return '0 KB';
        if (b >= 1073741824) {
            return (b / 1073741824).toFixed(2) + ' GB';
        } else if (b >= 1048576) {
            return (b / 1048576).toFixed(1) + ' MB';
        } else {
            return (b / 1024).toFixed(0) + ' KB';
        }
    }

    function calculateRemainingDays(expirStr) {
        if (!expirStr || expirStr === '') return null;
        try {
            var expDate = new Date(expirStr.replace(/-/g, '/'));
            var now = new Date();
            var diffMs = expDate - now;
            var days = Math.ceil(diffMs / (1000 * 60 * 60 * 24));
            return days;
        } catch(e) {
            return null;
        }
    }

    // peer_announce frames are UNSIGNED by design (P2P discovery must work
    // before any adoption), so hostname/ip/medium in them are attacker-
    // controllable by anything on the LAN. They end up inside innerHTML below,
    // so everything interpolated there must go through these first, or a
    // malicious hostname becomes stored XSS in the admin's LuCI session.
    var HTML_ESCAPES = { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' };
    function esc(s) {
        if (s === null || s === undefined) return '';
        return String(s).replace(/[&<>"']/g, function(c) { return HTML_ESCAPES[c]; });
    }
    // For values used in an href, escaping is not enough (javascript: URIs).
    // Only emit something that is literally a dotted-quad IPv4 address.
    function safeIp(s) {
        return /^\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}$/.test(String(s || '')) ? String(s) : '';
    }

    function normalizeMac(mac) {
        if (!mac) return '';
        var clean = String(mac).replace(/[^a-fA-F0-9]/g, '').toUpperCase();
        if (clean.length === 12) {
            return clean.match(/.{1,2}/g).join(':');
        }
        return String(mac).toUpperCase().trim();
    }

    function buildMacMap(raw) {
        var map = {};
        var ipMap = {};
        if (!raw) return { macMap: map, ipMap: ipMap };

        // 1. Process Neighbor AP Peers (P2P Discovery)
        if (raw.peers && typeof raw.peers === 'object') {
            for (var pm in raw.peers) {
                var norm_pm = normalizeMac(pm);
                if (norm_pm) {
                    var pItem = raw.peers[pm];
                    map[norm_pm] = {
                        is_ap_peer: true,
                        hostname: pItem.hostname,
                        ip: pItem.ip,
                        band: pItem.band || '5GHz',
                        medium: pItem.medium || (pItem.medium_type === 'lan' ? 'كابل LAN سلكي 🔌' : 'وايرليس 5GHz 📶'),
                        medium_type: pItem.medium_type || 'wireless_5g',
                        src_mac: pItem.src_mac
                    };
                    if (pItem.ip) {
                        ipMap[pItem.ip] = map[norm_pm];
                    }
                }
            }
        }

        var arpMap = {};
        if (raw && raw.arp && typeof raw.arp === 'object') {
            for (var am in raw.arp) {
                var n_am = normalizeMac(am);
                if (n_am) arpMap[n_am] = raw.arp[am];
            }
        }

        var list = [];
        if (Array.isArray(raw)) {
            list = raw;
        } else if (raw.data && Array.isArray(raw.data)) {
            list = raw.data;
        } else if (typeof raw === 'object') {
            for (var k in raw) {
                if (k !== 'data' && k !== 'status' && k !== 'timestamp' && k !== 'count' && k !== 'peers' && k !== 'arp' && typeof raw[k] === 'object') {
                    var n_k = normalizeMac(k);
                    if (n_k) map[n_k] = raw[k];
                }
            }
            return { macMap: map, ipMap: ipMap, arpMap: arpMap };
        }

        for (var i = 0; i < list.length; i++) {
            var u = list[i];
            if (!u) continue;

            var rawMac = u.mac || u.callingstationid || u.username || '';
            var mac = normalizeMac(rawMac);

            var displayName = u.name || '';
            if (!displayName || displayName === mac || displayName === rawMac) {
                if (u.user_details && u.user_details.firstname && u.user_details.firstname !== '') {
                    displayName = u.user_details.firstname;
                    if (u.user_details.lastname && u.user_details.lastname !== '') {
                        displayName += ' ' + u.user_details.lastname;
                    }
                } else if (u.firstname && u.firstname !== '') {
                    displayName = u.firstname;
                    if (u.lastname && u.lastname !== '') {
                        displayName += ' ' + u.lastname;
                    }
                } else {
                    displayName = u.username || '';
                }
            }

            var profileName = u.profile || u.profile_name || u.user_profile_name || '';
            if (!profileName && u.user_details && u.user_details.profile_details) {
                profileName = u.user_details.profile_details.name || '';
            } else if (!profileName && u.profile_details) {
                profileName = u.profile_details.name || '';
            }

            var expiry = u.expiration || (u.user_details && u.user_details.expiration) || '';
            var ip = u.ip || u.framedipaddress || '';
            var sess = parseInt(u.session || u.uptime || u.acctsessiontime) || 0;
            var quota = (u.quota !== undefined && u.quota !== null && u.quota !== '') ? u.quota : (u.remainingTrafficBytes !== undefined ? u.remainingTrafficBytes : '');
            var balance = (u.balance !== undefined && u.balance !== null && u.balance !== '') ? u.balance : (u.credits !== undefined ? u.credits : (u.user_details && u.user_details.balance ? u.user_details.balance : ''));
            var loan = (u.loan !== undefined && u.loan !== null && u.loan !== '') ? u.loan : (u.user_details && u.user_details.loan_balance ? u.user_details.loan_balance : '');

            var userObj = {
                username: u.username || '',
                name: displayName,
                profile: profileName,
                quota: quota,
                used: (u.used !== undefined && u.used !== null && u.used !== '') ? u.used : '',
                balance: balance,
                loan: loan,
                ip: ip,
                expiration: expiry,
                session: sess
            };

            if (mac && /^([0-9A-F]{2}:){5}[0-9A-F]{2}$/.test(mac)) {
                map[mac] = userObj;
            }
            if (ip && /^[0-9]+\.[0-9]+\.[0-9]+\.[0-9]+$/.test(ip)) {
                ipMap[ip] = userObj;
            }
        }
        return { macMap: map, ipMap: ipMap, arpMap: arpMap };
    }

    function clearInjections() {
        var badges = document.querySelectorAll('.sas-badge-icon');
        for (var b = 0; b < badges.length; b++) {
            badges[b].remove();
        }

        var cells = document.querySelectorAll('[data-sas-done]');
        for (var c = 0; c < cells.length; c++) {
            var orig = cells[c].getAttribute('data-orig-content');
            if (orig !== null) {
                cells[c].innerHTML = orig;
            }
            cells[c].removeAttribute('data-sas-done');
        }
    }

    function injectAll() {
        // NEVER run injector on Horus Controller pages (Horus Controller has its own native UI)
        if (window.location.href.indexOf('horus_controller') !== -1 || document.getElementById('horus-wlc-root')) {
            return;
        }

        var rows = document.querySelectorAll('tr');

        for (var i = 0; i < rows.length; i++) {
            var row = rows[i];

            // Skip any table inside Horus WLC Container
            if (row.closest && (row.closest('#horus-wlc-root') || row.closest('.horus-wlc-container'))) {
                continue;
            }

            // Skip header rows
            if (row.querySelector('th')) continue;

            var cells = row.querySelectorAll('td');
            // Associated stations rows in LuCI have 4 to 6 cells (Network, MAC, Host, Signal, Rate, Action)
            // Wireless overview / interface rows only have 2 or 3 cells.
            if (cells.length < 4) continue;

            // Skip if this row has buttons for Edit, Scan, Restart, Add (interface management actions)
            var btns = row.querySelectorAll('button, input[type="button"], a.cbi-button');
            var hasInterfaceBtn = false;
            for (var b = 0; b < btns.length; b++) {
                var btnText = (btns[b].textContent || btns[b].value || '').trim().toLowerCase();
                if (btnText.indexOf('edit') !== -1 || btnText.indexOf('تعديل') !== -1 ||
                    btnText.indexOf('scan') !== -1 || btnText.indexOf('فحص') !== -1 ||
                    btnText.indexOf('restart') !== -1 || btnText.indexOf('إعادة') !== -1 ||
                    btnText.indexOf('add') !== -1 || btnText.indexOf('إضافة') !== -1) {
                    hasInterfaceBtn = true;
                    break;
                }
            }
            if (hasInterfaceBtn) continue;

            var macCellIndex = -1;
            var matchedMac = '';
            var matchedIp = '';

            for (var c = 0; c < cells.length; c++) {
                var txt = cells[c].textContent.trim();
                var macMatch = txt.match(/([0-9A-Fa-f]{2}[:-]){5}[0-9A-Fa-f]{2}/);
                if (macMatch) {
                    macCellIndex = c;
                    matchedMac = normalizeMac(macMatch[0]);
                }
                var ipMatch = txt.match(/\b(?:192\.168|10\.|172\.(?:1[6-9]|2[0-9]|3[01]))\.[0-9]+\.[0-9]+\b/);
                if (ipMatch) {
                    matchedIp = ipMatch[0];
                }
            }

            if (macCellIndex !== -1 && matchedMac !== '') {
                if (!matchedIp && cachedArp && cachedArp[matchedMac]) {
                    matchedIp = cachedArp[matchedMac];
                }

                var hostCell = (cells.length > macCellIndex + 1) ? cells[macCellIndex + 1] : null;
                if (hostCell && hostCell.querySelector('input[type="button"], button, a.cbi-button')) {
                    continue;
                }

                var info = cachedMap[matchedMac] || (matchedIp ? cachedMapByIp[matchedIp] : null);

                // 1. Check if this client is a Neighbor AP (P2P Discovery)
                if (info && info.is_ap_peer) {
                    if (hostCell) {
                        if (!hostCell.hasAttribute('data-orig-content')) {
                            hostCell.setAttribute('data-orig-content', hostCell.innerHTML);
                        }
                        var peerKey = matchedMac + '_peer_' + info.hostname + '_' + info.ip + '_' + info.medium;
                        if (hostCell.getAttribute('data-sas-done') !== peerKey) {
                            hostCell.setAttribute('data-sas-done', peerKey);
                            var peerIp = safeIp(info.ip);
                            var peerName = esc(info.hostname || 'Horus-AP');
                            var medTone = (info.medium_type === 'wireless_5g' || (info.medium && info.medium.indexOf('5GHz') !== -1)) ? 'tone-primary' : (info.medium_type === 'lan' ? 'tone-success' : 'tone-warning');
                            hostCell.innerHTML = [
                                '<div class="h-inj-cell" style="text-align:start;">',
                                    '<div class="h-inj-title tone-primary" style="font-weight:700; font-size:13px; margin-bottom:4px;">',
                                        '📡 إكسس جار: ' + (peerIp
                                            ? '<a href="http://' + peerIp + '" target="_blank" onclick="event.stopPropagation();" class="h-inj-link" style="color:#0284c7; font-weight:bold; text-decoration:underline; cursor:pointer;" title="فتح لوحة تحكم الإكسس">' + peerName + ' ↗</a>'
                                            : peerName),
                                    '</div>',
                                    '<div class="h-inj-row" style="margin-top:4px; display:inline-flex; align-items:center; flex-wrap:wrap; gap:6px;">',
                                        peerIp ? '<a href="http://' + peerIp + '" target="_blank" onclick="event.stopPropagation();" class="h-inj-chip" style="font-size:12px; font-weight:700; color:#0284c7; background:#e0f2fe; border:1px solid #7dd3fc; padding:2px 8px; border-radius:4px; text-decoration:none; cursor:pointer;" onmouseover="this.style.background=\'#bae6fd\'" onmouseout="this.style.background=\'#e0f2fe\'" title="انقر لفتح لوحة تحكم الإكسس عبر المتصفح">🌐 IP: ' + peerIp + ' ↗</a>' : '',
                                        '<span class="h-inj-chip ' + medTone + '" style="font-size:11px;">⚡ ' + esc(info.medium) + '</span>',
                                    '</div>',
                                '</div>'
                            ].join('');
                        }
                    }

                    var macCell = cells[macCellIndex];
                    var existingBadge = macCell.querySelector('.sas-badge-icon');
                    if (existingBadge) existingBadge.remove();
                    var badge = document.createElement('span');
                    badge.className = 'sas-badge-icon h-inj-badge tone-primary';
                    badge.textContent = 'AP جار 📡';
                    macCell.appendChild(badge);
                    continue;
                }

                if (info && (info.name || info.profile || info.ip)) {
                    if (hostCell) {
                        if (!hostCell.hasAttribute('data-orig-content')) {
                            hostCell.setAttribute('data-orig-content', hostCell.innerHTML);
                        }

                        var displayName = info.name || info.username || 'مشترك';
                        var isCard = (info.username && info.username.length > 3 && /^\d+$/.test(info.username));

                        var quotaHtml = '';
                        if (info.quota !== null && info.quota !== undefined && info.quota !== '') {
                            var qFmt = formatQuota(info.quota);
                            if (qFmt !== null) {
                                quotaHtml += '<span class="h-inj-chip tone-primary">📊 متبقي: ' + qFmt + '</span> ';
                            }
                        } else if (currentRadiusType === 'mikrotik' && info.used) {
                            var uFmt = formatQuota(info.used);
                            if (uFmt !== null) {
                                quotaHtml += '<span class="h-inj-chip tone-primary">📊 مستهلك: ' + uFmt + '</span> ';
                            }
                        }
                        if (info.used && info.quota !== '' && info.quota !== null && info.quota !== undefined && currentRadiusType === 'mikrotik') {
                            var uFmt = formatQuota(info.used);
                            if (uFmt !== null && uFmt !== '0 KB') {
                                quotaHtml += '<span class="h-inj-chip tone-muted" style="opacity:0.9;">📉 مستهلك: ' + uFmt + '</span> ';
                            }
                        }

                        var balanceHtml = '';
                        if (currentRadiusType !== 'mikrotik') {
                            var balNum = parseFloat(info.balance !== undefined && info.balance !== null && info.balance !== '' ? info.balance : 0);
                            balanceHtml = '<span class="h-inj-chip tone-warning">💰 رصيد: ' + (isNaN(balNum) ? '0.00' : balNum.toFixed(2)) + ' ج</span>';
                        }

                        var loanHtml = '';
                        if (info.loan !== undefined && info.loan !== null && info.loan !== '') {
                            var loanNum = parseFloat(info.loan);
                            if (!isNaN(loanNum) && loanNum > 0) {
                                loanHtml = '<span class="h-inj-chip tone-error">💳 سلف: ' + loanNum.toFixed(2) + ' ج</span>';
                            }
                        }

                        var days = calculateRemainingDays(info.expiration);
                        var daysHtml = '';
                        if (days !== null) {
                            var daysClass = days > 3 ? 'tone-purple' : (days > 0 ? 'tone-warning' : 'tone-error');
                            daysHtml = '<span class="h-inj-chip ' + daysClass + '">📅 ' +
                                       (days > 0 ? 'متبقي ' + days + ' يوم' : 'منتهي الصلاحية') + '</span>';
                        }

                        var cellKey = [
                            matchedMac,
                            displayName,
                            info.profile || '',
                            info.quota || '',
                            info.used || '',
                            info.balance || '',
                            info.loan || '',
                            info.ip || '',
                            info.session || '',
                            info.expiration || ''
                        ].join('_');
                        if (hostCell.getAttribute('data-sas-done') === cellKey) {
                            continue;
                        }
                        hostCell.setAttribute('data-sas-done', cellKey);

                        // Escaped too: this data comes from the RADIUS server,
                        // which is more trusted than a peer broadcast but is
                        // still remote input rendered into the admin's page.
                        var subIp = safeIp(info.ip) || safeIp(matchedIp);
                        hostCell.innerHTML = [
                            '<div class="h-inj-cell">',
                                '<div class="h-inj-row">',
                                    info.profile ? '<span class="h-inj-chip tone-success">📦 ' + esc(info.profile) + '</span>' : '',
                                    balanceHtml,
                                    quotaHtml,
                                    daysHtml,
                                    loanHtml,
                                '</div>',
                                '<div class="h-inj-row h-inj-muted" style="font-size:11px; margin-top:3px;">',
                                    subIp ? '<span>🌐 IP: <a href="http://' + subIp + '" target="_blank" class="h-inj-link" style="color:#38bdf8; font-family:monospace; font-weight:700; text-decoration:underline;" title="فتح عنوان الجهاز في المتصفح">' + subIp + ' ↗</a></span>' : '',
                                    info.session ? '<span>⏱ متصل: <span style="color:var(--h-text-muted, #64748b);">' + esc(formatSession(info.session)) + '</span></span>' : '',
                                '</div>',
                            '</div>'
                        ].join('');
                    }

                    var macCell = cells[macCellIndex];
                    var existingBadge = macCell.querySelector('.sas-badge-icon');
                    if (existingBadge) existingBadge.remove();
                    var badge = document.createElement('div');
                    badge.className = 'sas-badge-icon h-inj-badge tone-primary';
                    badge.style.display = 'inline-flex';
                    badge.style.alignItems = 'center';
                    badge.style.gap = '4px';
                    badge.style.marginTop = '4px';
                    badge.style.fontSize = '12px';
                    badge.style.fontWeight = '700';
                    badge.style.maxWidth = '220px';
                    badge.style.whiteSpace = 'normal';
                    badge.style.lineHeight = '1.3';
                    badge.style.wordBreak = 'break-word';
                    badge.title = displayName;
                    badge.innerHTML = '<span>' + (isCard ? '💳' : '👤') + '</span> <span style="unicode-bidi:plaintext;">' + esc(displayName) + '</span>';
                    macCell.appendChild(badge);
                } else {
                    // Unregistered / Guest / Disconnected / Disabled indicator
                    var unregIp = safeIp(matchedIp);
                    var ipLinkHtml = unregIp ? ' <span style="font-size:11px; margin-inline-start:6px;">🌐 <a href="http://' + unregIp + '" target="_blank" class="h-inj-link" style="color:#38bdf8; font-family:monospace; font-weight:700; text-decoration:underline;" title="فتح الجهاز في المتصفح">' + unregIp + ' ↗</a></span>' : '';

                    if (hostCell) {
                        if (!hostCell.hasAttribute('data-orig-content')) {
                            hostCell.setAttribute('data-orig-content', hostCell.innerHTML);
                        }
                        var unregKey = matchedMac + '_unreg_' + currentStatus + '_' + (unregIp || '');
                        if (hostCell.getAttribute('data-sas-done') !== unregKey) {
                            hostCell.setAttribute('data-sas-done', unregKey);
                            if (currentStatus === 'offline') {
                                hostCell.innerHTML = '<div style="text-align:start;"><span class="h-inj-chip tone-error" title="فشل الاتصال بسيرفر الريديس"><span>🔴</span><span>الريديس غير متصل</span></span>' + ipLinkHtml + '</div>';
                            } else if (currentStatus === 'disabled') {
                                hostCell.innerHTML = '<div style="text-align:start;"><span class="h-inj-chip tone-muted" title="مزامنة الريديس معطلة في الإعدادات"><span>⏸️</span><span>الريديس معطل</span></span>' + ipLinkHtml + '</div>';
                            } else {
                                hostCell.innerHTML = '<div style="text-align:start;"><span class="h-inj-chip tone-warning" title="الريديس متصل، ولكن هذا الماك غير مسجل في السيرفر أو لم يسجل دخوله بعد"><span>🟡</span><span>ضيف / غير مسجل بالريديس</span></span>' + ipLinkHtml + '</div>';
                            }
                        }
                    }

                    var macCell = cells[macCellIndex];
                    var existingBadge = macCell.querySelector('.sas-badge-icon');
                    if (existingBadge) existingBadge.remove();
                    var badge = document.createElement('div');
                    badge.style.marginTop = '4px';
                    badge.style.display = 'inline-flex';
                    badge.style.alignItems = 'center';
                    badge.style.gap = '4px';
                    if (currentStatus === 'offline') {
                        badge.className = 'sas-badge-icon h-inj-badge tone-error';
                        badge.innerHTML = '<span>🔴</span><span>غير متصل</span>';
                    } else if (currentStatus === 'disabled') {
                        badge.className = 'sas-badge-icon h-inj-badge tone-muted';
                        badge.innerHTML = '<span>⏸️</span><span>معطل</span>';
                    } else {
                        badge.className = 'sas-badge-icon h-inj-badge tone-warning';
                        badge.innerHTML = '<span>🟡</span><span>ضيف (غير مسجل)</span>';
                    }
                    macCell.appendChild(badge);
                }
            }
        }
    }

    // LuCI scopes its sysauth cookie to "path=/cgi-bin/luci/", so it never
    // reaches /cgi-bin/horus_* -- mirror the same session id into a cookie
    // scoped to /cgi-bin/ (SameSite=Strict). Re-synced before every poll
    // rather than once at load: this script runs on pages where LuCI's JS
    // may still be initialising, and re-logging in mid-session issues a new
    // id. See AI_AGENT_RULES.md rule 25.
    function syncHorusSid() {
        try {
            var sid = (window.L && L.env && L.env.sessionid) ? L.env.sessionid : null;
            if (sid) document.cookie = 'horus_sid=' + sid + '; path=/cgi-bin/; SameSite=Strict';
        } catch (e) {}
    }

    function fetchFreshData() {
        if (isFetching) return;
        isFetching = true;
        syncHorusSid();

        fetch('/cgi-bin/horus_mac_data?_=' + Date.now())
            .then(function(r) { return r.json(); })
            .then(function(raw) {
                isFetching = false;
                currentStatus = raw.status || (Array.isArray(raw.data) && raw.data.length > 0 ? 'online' : 'disabled');
                currentRadiusType = raw.radius_type || '';

                // ALWAYS parse peer APs and radius data into cachedMap regardless of RADIUS status!
                var res = buildMacMap(raw);
                if (res && res.macMap) {
                    cachedMap = res.macMap;
                    cachedMapByIp = res.ipMap || {};
                    cachedArp = res.arpMap || {};
                } else {
                    cachedMap = {};
                    cachedMapByIp = {};
                    cachedArp = {};
                }
                injectAll();
            })
            .catch(function() {
                isFetching = false;
            });
    }

    // Hook LuCI's cbi_update_table for synchronous 0-flicker updates
    function attachHook() {
        if (window.cbi_update_table && !window._cbi_hooked) {
            window._cbi_hooked = true;
            var orig = window.cbi_update_table;
            window.cbi_update_table = function() {
                var res = orig.apply(this, arguments);
                injectAll();
                return res;
            };
        }
    }

    // Never run on Horus Controller pages
    if (window.location.href.indexOf('horus_controller') !== -1) {
        return;
    }

    // Run hook & sync
    attachHook();
    fetchFreshData();
    injectAll();

    // Instantaneous DOM MutationObserver for 0ms flicker-free injection on LuCI table updates
    if (window.MutationObserver) {
        var obsTimeout = null;
        var observer = new MutationObserver(function() {
            if (!obsTimeout) {
                obsTimeout = setTimeout(function() {
                    obsTimeout = null;
                    injectAll();
                }, 50);
            }
        });
        observer.observe(document.body, { childList: true, subtree: true });
    }


    // Copy MAC / Name on click
    document.addEventListener('click', function(e) {
        var macCell = e.target.closest('td[data-name="macaddress"]') || e.target.closest('td[data-name="mac"]');
        if (!macCell) return;
        
        var badge = e.target.closest('.sas-badge-icon');
        var textToCopy = '';
        
        if (badge) {
            textToCopy = badge.innerText.replace(/^[^\w\u0600-\u06FF\d]+/g, '').trim();
        } else {
            var match = macCell.innerText.match(/([0-9A-Fa-f]{2}[:-]){5}([0-9A-Fa-f]{2})/i);
            if (match) {
                textToCopy = match[0].toUpperCase();
            }
        }
        
        if (textToCopy) {
            function visualFeedback() {
                var targetElement = badge || macCell;
                var origTrans = targetElement.style.transition;
                targetElement.style.transition = 'opacity 0.2s';
                targetElement.style.opacity = '0.5';
                setTimeout(function(){ 
                    targetElement.style.opacity = '1'; 
                    setTimeout(function(){targetElement.style.transition = origTrans;}, 200); 
                }, 200);
            }
            if (navigator.clipboard && window.isSecureContext) {
                navigator.clipboard.writeText(textToCopy).then(visualFeedback).catch(function(){});
            } else {
                var textArea = document.createElement("textarea");
                textArea.value = textToCopy;
                textArea.style.position = "fixed";
                textArea.style.left = "-999999px";
                textArea.style.top = "-999999px";
                document.body.appendChild(textArea);
                textArea.focus();
                textArea.select();
                try {
                    document.execCommand('copy');
                    visualFeedback();
                } catch (err) {}
                textArea.remove();
            }
        }
    });

    var copyStyle = document.createElement('style');
    copyStyle.innerHTML = 'td[data-name="macaddress"], td[data-name="mac"] { cursor: pointer; user-select: text !important; } .sas-badge-icon { cursor: pointer; transition: transform 0.1s, opacity 0.2s; } .sas-badge-icon:active { transform: scale(0.95); }';
    document.head.appendChild(copyStyle);

    // Regular checks
    setInterval(attachHook, 2000);
    setInterval(fetchFreshData, 15000); // Live poll from local router every 15 seconds to prevent python exhaustion
})();
