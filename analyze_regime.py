"""
주도세력 전환 패턴 분석 (프로토타입) — data/krx_market.json 캐시만 읽음(읽기전용).

매일의 '방향주도 주체' = 최근 W영업일 corr(주체 일별순매수, 지수 일별수익률) 최대 주체.
→ 국면(episode) 타임라인 / 전환행렬 / 평균 지속일 / 전환 직후 지수 수익률 분포.

한계(정직): 롤링 corr은 후행·노이즈, 윈도우 선택 민감. 2년 503일이라 독립 국면 수 적음
→ 전환행렬은 표본 작음. 동시점 corr은 기술적 기술(descriptive)이지 인과·예측 아님.
"""
from __future__ import annotations
import json
from pathlib import Path

ACTORS = {"개인": "indiv_net", "외국인": "foreign_net", "기관": "inst_net"}


def _corr(xs, ys):
    ps = [(x, y) for x, y in zip(xs, ys) if x is not None and y is not None]
    if len(ps) < 3:
        return None
    n = len(ps); mx = sum(p[0] for p in ps) / n; my = sum(p[1] for p in ps) / n
    sxx = sum((p[0] - mx) ** 2 for p in ps); syy = sum((p[1] - my) ** 2 for p in ps)
    if sxx <= 0 or syy <= 0:
        return None
    sxy = sum((p[0] - mx) * (p[1] - my) for p in ps)
    return sxy / (sxx ** 0.5 * syy ** 0.5)


def analyze(win: int = 20, fwd: int = 20):
    d = json.loads((Path(__file__).parent / "data" / "krx_market.json").read_text(encoding="utf-8"))
    dates = d["dates"]
    nets = {a: d.get(k) or [] for a, k in ACTORS.items()}
    ret = d.get("index_ret") or []
    close = d.get("index_close") or []
    N = len(dates)

    # 매일의 방향주도 주체 (롤링 win일 corr 최대)
    leader = [None] * N
    for i in range(win, N):
        sl = slice(i - win + 1, i + 1)
        r = ret[sl]
        cors = {a: _corr(nets[a][sl], r) for a in ACTORS}
        cors = {a: c for a, c in cors.items() if c is not None}
        if cors:
            leader[i] = max(cors, key=lambda a: cors[a])

    # 국면(episode) 압축: 연속 동일 주도 구간
    eps = []
    for i in range(win, N):
        L = leader[i]
        if L is None:
            continue
        if eps and eps[-1]["leader"] == L:
            eps[-1]["end_i"] = i
        else:
            eps.append({"leader": L, "start_i": i, "end_i": i})
    # 너무 짧은(노이즈) 국면 병합: 1~2일 국면은 직전 국면에 흡수
    MIN = 3
    merged = []
    for e in eps:
        dur = e["end_i"] - e["start_i"] + 1
        if merged and dur < MIN:
            merged[-1]["end_i"] = e["end_i"]   # 흡수(직전 주도 유지)
        else:
            merged.append(e)
    for e in merged:
        e["dur"] = e["end_i"] - e["start_i"] + 1
        e["start"] = dates[e["start_i"]]; e["end"] = dates[e["end_i"]]
        c0, c1 = close[e["start_i"]], close[e["end_i"]]
        e["idx_ret"] = round((c1 / c0 - 1) * 100, 1) if c0 and c1 else None

    # 전환행렬 + 지속일 통계
    from collections import Counter, defaultdict
    trans = defaultdict(Counter)
    for a, b in zip(merged, merged[1:]):
        trans[a["leader"]][b["leader"]] += 1
    dwell = defaultdict(list)
    for e in merged:
        dwell[e["leader"]].append(e["dur"])

    # 전환 직후 fwd일 지수 수익률 (전환 시점 = 새 국면 시작일)
    fwd_by_to = defaultdict(list)
    for e in merged[1:]:
        si = e["start_i"]
        if si + fwd < N and close[si] and close[si + fwd]:
            fwd_by_to[e["leader"]].append((close[si + fwd] / close[si] - 1) * 100)

    return {"dates": dates, "win": win, "fwd": fwd, "episodes": merged,
            "trans": trans, "dwell": dwell, "fwd_by_to": fwd_by_to, "N": N}


if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--win", type=int, default=20)
    ap.add_argument("--fwd", type=int, default=20)
    args = ap.parse_args()
    R = analyze(args.win, args.fwd)
    eps = R["episodes"]
    print(f"\n=== 주도세력 전환 패턴 (롤링 {R['win']}일 corr / {R['N']}거래일 / 국면 {len(eps)}개) ===\n")
    print(f"{'기간':<24}{'주도':<8}{'지속(일)':>8}{'지수등락%':>10}")
    for e in eps:
        print(f"{e['start']}~{e['end']:<12}{e['leader']:<8}{e['dur']:>6}{(e['idx_ret'] if e['idx_ret'] is not None else 0):>10.1f}")

    print("\n--- 평균 지속일(국면 dwell) ---")
    for a, ds in R["dwell"].items():
        print(f"  {a}: 국면 {len(ds)}회 · 평균 {sum(ds)/len(ds):.0f}일 · 최장 {max(ds)}일")

    print("\n--- 전환행렬 (행=현재주도 → 열=다음주도) ---")
    acts = ["개인", "외국인", "기관"]
    print("        " + "".join(f"{a:>8}" for a in acts))
    for a in acts:
        row = R["trans"].get(a, {})
        print(f"  {a:<6}" + "".join(f"{row.get(b,0):>8}" for b in acts))

    print(f"\n--- 전환 직후 {R['fwd']}일 지수 수익률(새 주도 기준) ---")
    for a, xs in R["fwd_by_to"].items():
        if xs:
            xs2 = sorted(xs)
            print(f"  →{a} 전환 {len(xs)}회: 평균 {sum(xs)/len(xs):+.1f}% · 중앙 {xs2[len(xs2)//2]:+.1f}% · 승률 {sum(1 for x in xs if x>0)/len(xs)*100:.0f}%")
