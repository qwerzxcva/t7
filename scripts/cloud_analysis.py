#!/usr/bin/env python3
"""
cloud_analysis.py — 纯统计云端分析引擎 (无AI, 可在GitHub Actions跑)
输入: t1-t13 公开仓 raw 数据 (index K线/涨停池/资金流/AI池)
输出: cloud_analysis.json = 市场统计 + 推演 + 预测(统计外推, 非投资建议)
用法: python3 cloud_analysis.py --out cloud_analysis.json [--src github|local]
"""
import json, os, sys, urllib.request, datetime
from collections import defaultdict

RAW = "https://raw.githubusercontent.com/qwerzxcva"
REPOS = {"index": ("t1", "data/index/sh000001.txt"),
         "latest": ("qwerzxcva/stocks-ai-view".split("/")[1], "data/latest.json"),
         "aipick": ("t7", "aipick/latest.json"),
         "westock": ("t7", "westock/latest.json"),
         "global": ("t7", "global/latest.json"),
         "moneyflow": ("t7", "moneyflow/latest.json")}

def fetch(key):
    repo, path = REPOS[key]
    if repo == "stocks-ai-view": repo = "stocks-ai-view"
    u = f"{RAW}/{repo}/main/{path}"
    try:
        return json.load(urllib.request.urlopen(urllib.request.Request(u, headers={"User-Agent":"cloud-analysis"}), timeout=20))
    except Exception as e:
        print(f"fetch {key} ERR {e}", file=sys.stderr)
        return None

def load_index_txt():
    """t1的指数txt(管道分隔) 或直接用腾讯接口兜底"""
    try:
        repo, path = REPOS["index"]
        u = f"{RAW}/{repo}/main/{path}"
        txt = urllib.request.urlopen(urllib.request.Request(u, headers={"User-Agent":"x"}), timeout=20).read().decode()
        rows = []
        for line in txt.splitlines():
            if line.startswith("#") or "|" not in line: continue
            f = line.split("|")
            if len(f) >= 7: rows.append((f[1], float(f[3])))
        if len(rows) > 100: return rows
    except Exception: pass
    # 兜底: 腾讯接口拉800日
    UA = {"User-Agent": "Mozilla/5.0", "Referer": "https://gu.qq.com/"}
    u = "https://web.ifzq.gtimg.cn/appstock/app/kline/kline?param=sh000001,day,,,800"
    d = json.load(urllib.request.urlopen(urllib.request.Request(u, headers=UA), timeout=20))
    return [(r[0], float(r[2])) for r in d["data"]["sh000001"]["day"]]

def analyze():
    out = {"ts": datetime.datetime.now(datetime.timezone(datetime.timedelta(hours=8))).isoformat(timespec="seconds"),
           "engine": "cloud_analysis v1 (纯统计, 不构成投资建议)"}
    # 1) 指数统计+预测
    rows = load_index_txt()
    rets = [(rows[i][0], (rows[i][1]/rows[i-1][1]-1)*100) for i in range(1, len(rows))]
    wd = defaultdict(list); mo = defaultdict(list)
    for d, p in rets:
        wd[datetime.datetime.strptime(d, "%Y-%m-%d").weekday()].append(p)
        mo[int(d[5:7])].append(p)
    last = rows[-1]; prev = rows[-2]
    chg = (last[1]/prev[1]-1)*100
    streak_up = chg > 0; n = 0
    for d, p in reversed(rets):
        if (p > 0) == streak_up: n += 1
        else: break
    # 连段→明日概率
    seq = []; up = rets[0][1] > 0; k = 1
    for _, p in rets[1:]:
        if (p > 0) == up: k += 1
        else: seq.append((up, k)); up = p > 0; k = 1
    seq.append((up, k))
    cont = defaultdict(lambda: [0, 0])
    for i, (u2, ln) in enumerate(seq):
        if i+1 < len(seq):
            cont[(u2, ln)][1] += 1
            if seq[i+1][0] == u2: cont[(u2, ln)][0] += 1
    cp = cont.get((streak_up, n), [0, 0])
    cont_prob = round(100*cp[0]/cp[1], 1) if cp[1] >= 8 else None
    wd_today = datetime.datetime.strptime(last[0], "%Y-%m-%d").weekday()
    # 期望日(明日=交易日下一档, 简化: 按自然日+1的weekday)
    wd_next = (wd_today + 1) % 7
    wd_stat = wd.get(wd_next, {})
    mo_stat = mo.get(int(last[0][5:7]), {})
    mp20 = sum(p for _, p in rets[-20:])
    # 综合预测(统计外推)
    score = 0
    if wd_stat: score += 1 if wd_stat and sum(wd_stat)/len(wd_stat) > 0.05 else (-1 if sum(wd_stat)/len(wd_stat) < -0.05 else 0)
    if cont_prob is not None:
        score += 1 if (streak_up and cont_prob < 40) or (not streak_up and cont_prob < 40) else 0
    score += 1 if mp20 > 3 else (-1 if mp20 < -3 else 0)
    out["index_forecast"] = {
        "as_of": last[0], "close": last[1], "chg_pct": round(chg, 2),
        "streak": ("连涨" if streak_up else "连跌") + f"{n}天",
        "streak_continue_prob": cont_prob,
        "next_weekday_stat": {"avg": round(sum(wd_stat)/len(wd_stat), 3), "win": round(100*sum(1 for x in wd_stat if x > 0)/len(wd_stat), 1), "n": len(wd_stat)} if wd_stat else None,
        "month_stat": {"avg": round(sum(mo_stat)/len(mo_stat), 3), "n": len(mo_stat)} if mo_stat else None,
        "mom20": round(mp20, 1),
        "composite": score,
        "bias": "偏多" if score >= 2 else ("偏空" if score <= -2 else "中性"),
        "note": "统计外推, 历史规律不保证未来, 不构成投资建议"}
    # 2) 市场情绪(从latest取涨停池/全球)
    lat = fetch("latest")
    if lat:
        mkt = lat.get("market", {})
        out["sentiment"] = {"limit_up": mkt.get("limit_up"), "limit_down": mkt.get("limit_down"),
                            "phase": (lat.get("phase") or {}).get("stage"),
                            "global_score": ((lat.get("global") or {}).get("metrics") or {}).get("global_score"),
                            "zt_rate": mkt.get("zt_rate")}
        # 涨停池题材聚类
        picks = lat.get("picks") or []
        themes = defaultdict(int)
        for p in picks:
            for t in (p.get("theme") or []):
                themes[t] += 1
        out["theme_heat"] = sorted(themes.items(), key=lambda x: -x[1])[:8]
    # 3) 行业资金(Westock)
    ws = fetch("westock")
    if ws:
        sr = (ws.get("sector_ranking") or {}).get("data") or []
        out["sector_top"] = [{"name": x.get("name"), "chg": x.get("changePct"), "inflow": x.get("mainNetInflow"), "leader": x.get("leader")} for x in sr[:8]]
        out["sector_bottom"] = [{"name": x.get("name"), "chg": x.get("changePct"), "inflow": x.get("mainNetInflow")} for x in sr[-5:]]
    # 4) 全球传导
    g = fetch("global")
    if g:
        items = (g.get("items") or {})
        gv = []
        for k in ("idx_dji", "idx_ixic", "idx_sp500", "idx_vix", "fx_susdcnh"):
            it = items.get(k)
            if it: gv.append({"name": it.get("name"), "pct": it.get("pct")})
        out["global_pulse"] = gv
    # 5) 观察池(未涨停主板, 从ai_pick)
    ap = fetch("aipick")
    if ap and ap.get("picks"):
        out["watchlist"] = [{"code": p.get("symbol"), "score": p.get("score"), "vratio": p.get("vratio"), "pos240": p.get("pos240")} for p in ap["picks"][:10]]
    return out

if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="cloud_analysis.json")
    args = ap.parse_args()
    res = analyze()
    json.dump(res, open(args.out, "w"), ensure_ascii=False, indent=1)
    print("written", args.out, json.dumps({k: (list(v.keys()) if isinstance(v, dict) else type(v).__name__) for k, v in res.items()}, ensure_ascii=False))
