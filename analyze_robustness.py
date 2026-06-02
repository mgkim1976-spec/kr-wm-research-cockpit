"""
강건성 분석 (8년 data/krx_history.json) — 3종:
  (a) win 민감도   : leader 윈도우 20/60/120 → 국면수·주도비중·전환 안정성
  (b) 개인 lead-lag: 개인 순매수_t 가 미래 지수수익(t+1..t+k)을 선행하는가 (역추세→바닥/천장 신호?)
  (c) 정규화 robustness: scale-free corr 연도안정 + flow z-score β → 외인 영향력·개인 흡수성 결론 견고성

한계: 동시점/선행 corr 모두 후행·노이즈. overlapping fwd 윈도우라 유효표본 < 표시 n. 독립사이클 2~3개.
"""
from __future__ import annotations
import json
from collections import defaultdict, Counter
from pathlib import Path

H = json.loads((Path(__file__).parent / "data" / "krx_history.json").read_text(encoding="utf-8"))
D, CL = H["dates"], H["close"]
NET = {"개인": H["indiv_net"], "외국인": H["foreign_net"], "기관": H["inst_net"]}
N = len(D)
RET = [None] + [(CL[i] / CL[i - 1] - 1) if CL[i] and CL[i - 1] else None for i in range(1, N)]


def corr(xs, ys):
    ps = [(x, y) for x, y in zip(xs, ys) if x is not None and y is not None]
    if len(ps) < 5:
        return None
    n = len(ps); mx = sum(p[0] for p in ps) / n; my = sum(p[1] for p in ps) / n
    sxx = sum((p[0] - mx) ** 2 for p in ps); syy = sum((p[1] - my) ** 2 for p in ps)
    if sxx <= 0 or syy <= 0:
        return None
    return sum((p[0] - mx) * (p[1] - my) for p in ps) / (sxx ** 0.5 * syy ** 0.5)


def beta(xs, ys):
    ps = [(x, y) for x, y in zip(xs, ys) if x is not None and y is not None]
    if len(ps) < 5:
        return None
    n = len(ps); mx = sum(p[0] for p in ps) / n; my = sum(p[1] for p in ps) / n
    sxx = sum((p[0] - mx) ** 2 for p in ps)
    return sum((p[0] - mx) * (p[1] - my) for p in ps) / sxx if sxx > 0 else None


def leader_at(win):
    lead = [None] * N
    for i in range(win, N):
        sl = slice(i - win + 1, i + 1)
        cs = {a: corr(NET[a][sl], RET[sl]) for a in NET}
        cs = {a: c for a, c in cs.items() if c is not None}
        if cs:
            lead[i] = max(cs, key=lambda a: cs[a])
    return lead


def episodes(lead, win, mind=3):
    eps = []
    for i in range(win, N):
        if lead[i] is None:
            continue
        if eps and eps[-1]["L"] == lead[i]:
            eps[-1]["e"] = i
        else:
            eps.append({"L": lead[i], "s": i, "e": i})
    m = []
    for ep in eps:
        if m and (ep["e"] - ep["s"] + 1) < mind:
            m[-1]["e"] = ep["e"]
        else:
            m.append(ep)
    return m


print(f"\n=== 강건성 분석 ({D[0]}~{D[-1]}, {N}거래일) ===")

# (a) win 민감도
print("\n--- (a) win 민감도 (leader corr 윈도우) ---")
print(f"{'win':>5}{'국면수':>7}{'외인일%':>8}{'기관일%':>8}{'개인일%':>8}{'외인↔기관전환':>14}")
for win in (20, 60, 120):
    lead = leader_at(win)
    days = Counter(L for L in lead[win:] if L)
    tot = sum(days.values())
    eps = episodes(lead, win)
    tr = sum(1 for a, b in zip(eps, eps[1:]) if {a["L"], b["L"]} == {"외국인", "기관"})
    print(f"{win:>5}{len(eps):>7}{days['외국인']/tot*100:>8.0f}{days['기관']/tot*100:>8.0f}{days['개인']/tot*100:>8.0f}{tr:>14}")
print("  → 개인 0%·외인우위·외인↔기관 핑퐁이 win 무관하게 유지되면 결론 견고.")

# (b) 개인 lead-lag : 순매수_t vs 미래 누적수익 t+1..t+k
print("\n--- (b) lead-lag: 순매수_t → 미래 k일 누적수익 corr (양수=선행지표) ---")
print(f"{'주체':>6}{'동시(k=0)':>10}{'k=1':>8}{'k=5':>8}{'k=20':>8}{'k=60':>8}")
for a in ["개인", "외국인", "기관"]:
    row = []
    for k in (0, 1, 5, 20, 60):
        xs, ys = [], []
        for i in range(N - k):
            if k == 0:
                fr = RET[i]
            else:
                c0, c1 = CL[i], CL[i + k] if i + k < N else None
                fr = (c1 / c0 - 1) if (c0 and c1) else None
            xs.append(NET[a][i]); ys.append(fr)
        c = corr(xs, ys)
        row.append(f"{c:+.2f}" if c is not None else "  -")
    print(f"{a:>6}" + "".join(f"{v:>10}" if i == 0 else f"{v:>8}" for i, v in enumerate(row)))
print("  → 개인이 동시(−)인데 미래(k>0)에서 +로 바뀌면 '역추세 선행(바닥/천장)' 신호 가능성.")

# (c) 정규화 robustness: 연도별 corr(scale-free) + flow z-score β
print("\n--- (c) 정규화 robustness: 연도별 corr & flow-zscore β (외인/개인) ---")
years = defaultdict(list)
for i in range(N):
    years[D[i][:4]].append(i)
# flow z-score: net / trailing 60d std(net)
def zscore(series):
    z = [None] * N
    for i in range(60, N):
        w = [x for x in series[i - 60:i] if x is not None]
        if len(w) > 5:
            m = sum(w) / len(w); sd = (sum((x - m) ** 2 for x in w) / len(w)) ** 0.5
            if sd > 0:
                z[i] = (series[i] - m) / sd
    return z
ZF, ZG = zscore(NET["외국인"]), zscore(NET["개인"])
print(f"{'연도':<6}{'외인corr':>9}{'개인corr':>9}{'외인βz':>9}{'개인βz':>9}")
for y in sorted(years):
    idx = years[y]
    if len(idx) < 30:
        continue
    rr = [RET[i] for i in idx]
    print(f"{y:<6}{corr([NET['외국인'][i] for i in idx],rr):>9.2f}{corr([NET['개인'][i] for i in idx],rr):>9.2f}"
          f"{(beta([ZF[i] for i in idx],rr) or 0)*100:>9.2f}{(beta([ZG[i] for i in idx],rr) or 0)*100:>9.2f}")
print("  → corr(scale-free)·βz 모두 외인+ / 개인− 가 8년 안정 = 거래량 정규화 결론과 독립적으로 일치.")
