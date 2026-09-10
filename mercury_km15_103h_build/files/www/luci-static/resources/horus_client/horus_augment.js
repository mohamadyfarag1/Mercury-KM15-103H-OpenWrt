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
