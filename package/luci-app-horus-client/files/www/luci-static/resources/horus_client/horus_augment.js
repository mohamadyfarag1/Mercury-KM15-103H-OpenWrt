setInterval(function() {
    if (window.location.href.indexOf('network/wireless') === -1 && window.location.href.indexOf('status/overview') === -1) return;
    // LuCI's sysauth cookie is scoped to /cgi-bin/luci/ and never reaches
    // /cgi-bin/horus_* -- mirror the session id into a /cgi-bin/-scoped
    // cookie so cgi_auth.sh sees it. See AI_AGENT_RULES.md rule 24.
    try {
        var sid = (window.L && L.env && L.env.sessionid) ? L.env.sessionid : null;
        if (sid) document.cookie = 'horus_sid=' + sid + '; path=/cgi-bin/; SameSite=Strict';
    } catch (e) {}
    fetch('/cgi-bin/horus_peers').then(r => r.json()).then(peers => {
        var peersList = Object.keys(peers).map(k => peers[k]);
        if (peersList.length === 0) return;
        var walker = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT, null, false);
        var node;
        var nodesToAugment = [];
        while (node = walker.nextNode()) {
            var txt = node.nodeValue;
            if (txt && txt.match(/([0-9A-Fa-f]{2}[:-]){5}([0-9A-Fa-f]{2})/)) {
                if (node.parentNode && !node.parentNode.hasAttribute('data-horus-augmented')) {
                    nodesToAugment.push(node);
                }
            }
        }
        nodesToAugment.forEach(function(node) {
            var txt = node.nodeValue;
            var macMatch = txt.match(/([0-9A-Fa-f]{2}[:-]){5}([0-9A-Fa-f]{2})/);
            if (macMatch) {
                var mac = macMatch[0].toUpperCase().replace(/-/g, ':');
                var peer = peers[mac] || peersList.find(p => (p.src_mac && p.src_mac.toUpperCase() === mac) || (p.mac_5g && p.mac_5g.toUpperCase() === mac) || (p.macs && p.macs.includes(mac)));
                if (peer) {
                    node.parentNode.setAttribute('data-horus-augmented', '1');
                    var badge = document.createElement('span');
                    badge.innerHTML = ' <span style="background:#0055ff; color:#fff; padding:2px 6px; border-radius:4px; font-size:11px; margin-left:5px; margin-right:5px; white-space:nowrap;">📡 ' + (peer.hostname || 'Horus-AP') + ' (' + (peer.ip || '') + ')</span>';
                    node.parentNode.insertBefore(badge, node.nextSibling);
                }
            }
        });
    }).catch(function(){});
}, 15000);
// ==========================================
// ==========================================
// ==========================================
// HORUS BRANDING REPLACER (v11)
// ==========================================
(function() {
    function replaceLogo() {
        if (!window.__horus_anti_flicker) {
            window.__horus_anti_flicker = true;
            var s = document.createElement('style');
            s.innerHTML = '#menubar { background-image: none !important; padding-left: 15px !important; min-height: 68px !important; height: auto !important; display: flex !important; align-items: center !important; } ' +
                          '.navbar-static-top, header.navbar { min-height: 68px !important; height: auto !important; } ' +
                          '.horus-brand-badge { display: inline-flex !important; align-items: center !important; text-decoration: none !important; margin-right: 20px !important; flex: 0 0 auto !important; } ' +
                          '.horus-brand-text { font-weight: 800 !important; font-size: 1.8rem !important; color: #ffffff !important; letter-spacing: 2px !important; margin-left: 14px !important; text-shadow: 0 2px 4px rgba(0,0,0,0.4) !important; }';
            if (document.head) document.head.appendChild(s);
        }

        var logoSrc = '/luci-static/resources/horus_client/logo_white.png';
        var badgeHtml = '<img src="' + logoSrc + '" onerror="this.src=\'/luci-static/resources/horus_client/logo.svg\'; this.style.filter=\'brightness(0) invert(1)\';" style="height:60px !important; width:auto !important; max-height:60px !important; display:inline-block !important; vertical-align:middle !important; filter: drop-shadow(0 0 4px rgba(0,0,0,0.4)) drop-shadow(0 0 2px rgba(255,255,255,0.8)) !important;" />' +
                        '<span class="horus-brand-text" style="font-weight:800 !important; font-size:1.8rem !important; color:#ffffff !important; letter-spacing:2px !important; margin-left:14px !important; text-shadow:0 2px 4px rgba(0,0,0,0.4) !important; display:inline-block !important; vertical-align:middle !important;">HORUS</span>';

        // 1. Theme OpenWrt2020: #menubar
        var menubar = document.getElementById('menubar');
        if (menubar && !document.getElementById('horus_brand_node')) {
            var brandNode = document.createElement('a');
            brandNode.id = 'horus_brand_node';
            brandNode.className = 'horus-brand-badge';
            brandNode.href = '/cgi-bin/luci/';
            brandNode.innerHTML = badgeHtml;

            var hostname = menubar.querySelector('.hostname');
            if (hostname) {
                menubar.insertBefore(brandNode, hostname);
            } else {
                menubar.insertBefore(brandNode, menubar.firstChild);
            }
        }

        // 2. Themes with a.brand (Bootstrap, Argon, Material etc.) where #menubar doesn't exist
        if (!menubar) {
            var genericBrand = document.querySelector('a.brand, .navbar-brand');
            if (genericBrand && !genericBrand.hasAttribute('data-horus-logo')) {
                genericBrand.innerHTML = badgeHtml;
                genericBrand.setAttribute('data-horus-logo', '1');
                genericBrand.style.display = 'inline-flex';
                genericBrand.style.alignItems = 'center';
                genericBrand.style.textDecoration = 'none';
            }
        }

        // 3. Tab enhancements when on horus_client page
        if (window.location.href.includes('horus_client')) {
            document.querySelectorAll('.cbi-tabmenu').forEach(function(t) {
                t.classList.add('horus-enhanced-tabs');
                t.querySelectorAll('li a *').forEach(function(c) {
                    c.style.pointerEvents = 'none';
                });
            });
            var otaDiv = document.querySelector('.cbi-map');
            if (otaDiv && !otaDiv.classList.contains('horus-settings-view')) {
                otaDiv.classList.add('horus-settings-view');
            }
        }

        // 4. Override Model to HORUS-NEXT-GEN across status & overview tables
        document.querySelectorAll('td, th').forEach(function(cell) {
            var txt = cell.textContent.trim();
            if (txt === 'Model' || txt === 'الموديل') {
                var valCell = cell.nextElementSibling;
                if (valCell && valCell.textContent !== 'HORUS-NEXT-GEN') {
                    valCell.textContent = 'HORUS-NEXT-GEN';
                    valCell.setAttribute('data-horus-model', '1');
                }
            }
        });

        // 5. Enhance Network Card Buttons (Enable = Red, Disable = Glowing Blue)
        document.querySelectorAll('.ifacebox .cbi-button, .box .cbi-button, .node-system-board .cbi-button').forEach(function(b) {
            var txt = b.textContent.trim();
            if (!b.hasAttribute('data-horus-btn')) {
                b.setAttribute('data-horus-btn', '1');
                b.style.transition = 'all 0.3s ease';
            }
            if (txt === 'تفعيل / Enable' || txt === 'Enable' || txt === 'تفعيل' || txt === 'Turn On') {
                b.style.background = '#d64550';
                b.style.color = '#ffffff';
                b.style.border = '1px solid rgba(214,69,80,0.5)';
                b.style.boxShadow = '0 0 8px rgba(214,69,80,0.4)';
            } else if (txt === 'إيقاف / Disable' || txt === 'Disable' || txt === 'إيقاف' || txt === 'Turn Off / إيقاف' || txt === 'Turn Off') {
                b.style.background = 'linear-gradient(135deg, #0284c7, #2563eb)';
                b.style.color = '#ffffff';
                b.style.border = '1px solid rgba(255,255,255,0.2)';
                b.style.boxShadow = '0 0 12px rgba(14, 165, 233, 0.7)';
            }
        });

        // 6. Fix empty "No link" text on inactive LAN ports (like LAN2)
        document.querySelectorAll('.ifacebox').forEach(function(box) {
            var icon = box.querySelector('img[src*="port_down"]');
            if (icon) {
                var small = box.querySelector('small');
                if (small && small.textContent.trim() === '') {
                    small.innerHTML = 'No link / لا يوجد رابط';
                    small.style.color = '#888';
                }
            }
        });

        // 7. Hide CPU card (MT7621 data is unrealistic / not useful)
        document.querySelectorAll('.ifacebox, .node-system-board').forEach(function(box) {
            if (box.hasAttribute('data-horus-cpu-checked')) return;
            box.setAttribute('data-horus-cpu-checked', '1');
            var head = box.querySelector('.ifacebox-head, h4, [data-title]');
            if (!head) return;
            var title = (head.textContent || head.getAttribute('data-title') || '').trim();
            if (title.indexOf('CPU') !== -1 || title.indexOf('\u0627\u0644\u0645\u0639\u0627\u0644\u062c') !== -1) {
                box.style.setProperty('display', 'none', 'important');
            }
        });

        // 8. Hide temperature "-°C" on WiFi cards (MT7915 doesn't expose temp via nl80211)
        document.querySelectorAll('.ifacebox-body small, .ifacebox-body span, .ifacebox-body b').forEach(function(el) {
            if (el.hasAttribute('data-horus-temp-checked')) return;
            el.setAttribute('data-horus-temp-checked', '1');
            var txt = el.textContent || '';
            if (txt.match(/^-\s*\xb0C$/) || txt.trim() === '-\xb0C' || txt.trim() === '- \xb0C') {
                el.style.setProperty('display', 'none', 'important');
                // Also hide the thermometer icon next to it
                var prev = el.previousElementSibling;
                if (prev && (prev.tagName === 'IMG' || prev.tagName === 'I')) {
                    prev.style.setProperty('display', 'none', 'important');
                }
            }
        });

    }

    replaceLogo();
    if (window.MutationObserver) {
        var obs = new MutationObserver(function() {
            replaceLogo();
        });
        obs.observe(document.documentElement, { childList: true, subtree: true });
    }
    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', replaceLogo);
    }
    setInterval(replaceLogo, 1500);
})();
