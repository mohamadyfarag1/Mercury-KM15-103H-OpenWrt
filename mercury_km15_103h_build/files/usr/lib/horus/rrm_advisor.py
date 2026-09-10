# -*- coding: utf-8 -*-
import os
import json
import time
from .system import get_5g_channel_health, get_scan_data

def evaluate_channel_score(channel, local_health, peers_5g):
    """
    Computes a cleanliness score (0-100) for a given 5GHz channel across all APs.
    100 = perfectly clean, 0 = heavily congested/noisy.
    """
    score = 90
    
    # 1. Check local scan counts for this channel
    local_scans = local_health.get("scan_counts", {})
    overlap_count = local_scans.get(str(channel), 0)
    score -= (overlap_count * 15)
    
    # 2. Check peers scan counts & noise
    for p in peers_5g:
        p_scans = p.get("scan_counts", {})
        p_overlap = p_scans.get(str(channel), 0)
        score -= (p_overlap * 12)
        
        # If peer is currently on this channel, factor in its noise
        if p.get("channel") == channel:
            p_noise = p.get("noise", -90)
            if p_noise > -80:
                score -= 30
            elif p_noise > -85:
                score -= 15
                
    return max(10, min(100, score))

def analyze_spectrum_and_advise():
    local_5g = get_5g_channel_health()
    if not local_5g.get("has_5g"):
        return {"has_5g": False, "status": "no_5g", "message_ar": "لا يوجد كرت وايرليس 5GHz في هذا الجهاز"}

    # Load peers from /tmp/horus_ap_peers.json
    peers_5g = []
    if os.path.exists("/tmp/horus_ap_peers.json"):
        try:
            with open("/tmp/horus_ap_peers.json", "r") as f:
                raw_peers = json.load(f)
            seen_hosts = set()
            for mac, p in raw_peers.items():
                host = p.get("hostname", mac)
                if host not in seen_hosts and p.get("band") == "5GHz":
                    seen_hosts.add(host)
                    peers_5g.append(p)
        except Exception:
            pass

    cur_ch = local_5g.get("channel", 36)
    cur_noise = local_5g.get("noise", -90)
    
    # Evaluate current status
    if cur_noise <= -88:
        cur_status = "excellent"
        cur_status_ar = "ممتاز 🟢 (طيف نقي ومستقر)"
    elif cur_noise <= -82:
        cur_status = "moderate"
        cur_status_ar = "متوسط 🟡 (تشويش خفيف)"
    else:
        cur_status = "noisy"
        cur_status_ar = "تشويش عالي 🔴 (يؤثر على البنج والسرعة)"

    cur_score = evaluate_channel_score(cur_ch, local_5g, peers_5g)
    
    # Evaluate candidate non-DFS channels
    candidates = local_5g.get("supported_channels", [36, 40, 44, 48, 149, 153, 157, 161])
    channel_scores = {}
    for ch in candidates:
        channel_scores[ch] = evaluate_channel_score(ch, local_5g, peers_5g)
        
    best_ch = max(channel_scores, key=channel_scores.get)
    best_score = channel_scores[best_ch]
    
    improvement_pct = 0
    if cur_score > 0:
        improvement_pct = int(((best_score - cur_score) / cur_score) * 100)
    
    is_switch_recommended = False
    if best_ch != cur_ch and improvement_pct >= 15 and cur_noise > -86:
        is_switch_recommended = True
        reason_ar = f"القناة الحالية ({cur_ch}) تعاني من تشويش ({cur_noise} dBm)، بينما القناة ({best_ch}) أنظف بنسبة +{improvement_pct}% لجميع الإكسسات."
    else:
        reason_ar = f"القناة الحالية ({cur_ch}) تعمل بأعلى كفاءة واستقرار ممكن ولا داعي للتغيير حالياً."

    advice_data = {
        "timestamp": int(time.time()),
        "has_5g": True,
        "local": local_5g,
        "receivers": peers_5g,
        "current_channel": cur_ch,
        "current_noise": cur_noise,
        "current_status": cur_status,
        "current_status_ar": cur_status_ar,
        "current_score": cur_score,
        "recommended_channel": best_ch,
        "recommended_score": best_score,
        "improvement_pct": max(0, improvement_pct),
        "is_switch_recommended": is_switch_recommended,
        "reason_ar": reason_ar,
        "channel_scores": channel_scores,
        "candidates": candidates
    }

    try:
        tmp_p = "/tmp/horus_rrm_advice.json.tmp"
        with open(tmp_p, "w") as f:
            json.dump(advice_data, f, ensure_ascii=False, indent=2)
        os.replace(tmp_p, "/tmp/horus_rrm_advice.json")
    except Exception:
        pass

    return advice_data
