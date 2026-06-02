"""
정규화 β 검증 — 외인 가격영향력 하락이 '구조적'인가 '거래량 증가 착시'인가.

raw β    : ret = a + b·net(억원)            → 거래량 커지면 b 자동 하락(착시 가능)
norm β   : ret = a + b·(net/거래대금)        → 거래대금 대비 flow → 규모 중립(착시 제거)
flow강도 : mean(|net|/거래대금)              → 그 주체 flow가 거래량의 몇 %인지(추세)

norm β 가 그대로 떨어지면 → 진짜 구조 변화(외인 지배력 약화).
norm β 가 평평하면 → β 하락은 단순 거래량 증가 산물.
"""
from __future__ import annotations
import json
import time
import datetime as dt
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).parent
HIST = ROOT / "data" / "krx_history.json"


def fetch_turnover(dates: list[str]) -> dict[str, float]:
    import sys
    sys.path.insert(0, str(ROOT / "app" / "core" / "adapters"))
    import krx_market as km
    km._load_creds()
    from pykrx import stock
    s, e = dates[0].replace("-", ""), dates[-1].replace("-", "")
    buy = stock.get_market_trading_value_by_date(s, e, "KOSPI", on="매수")   # 매수 전체 = 一側 거래대금
    return {d.strftime("%Y-%m-%d"): float(v) / 1e8 for d, v in zip(buy.index, buy["전체"])}   # 억원


def beta(xs, ys):
    ps = [(x, y) for x, y in zip(xs, ys) if x is not None and y is not None]
    if len(ps) < 10:
        return None
    n = len(ps); mx = sum(p[0] for p in ps) / n; my = sum(p[1] for p in ps) / n
    sxx = sum((p[0] - mx) ** 2 for p in ps)
    if sxx <= 0:
        return None
    return sum((p[0] - mx) * (p[1] - my) for p in ps) / sxx


def main():
    h = json.loads(HIST.read_text(encoding="utf-8"))
    d, cl = h["dates"], h["close"]
    nets = {"외국인": h["foreign_net"], "개인": h["indiv_net"], "기관": h["inst_net"]}
    N = len(d)
    tov_map = fetch_turnover(d)
    tov = [tov_map.get(x) for x in d]
    ret = [None] + [(cl[i] / cl[i - 1] - 1) if cl[i] and cl[i - 1] else None for i in range(1, N)]

    # net/거래대금 정규화 시리즈
    norm = {a: [(nets[a][i] / tov[i]) if (tov[i] and nets[a][i] is not None) else None for i in range(N)]
            for a in nets}

    years = defaultdict(list)
    for i in range(N):
        years[d[i][:4]].append(i)

    print(f"\n=== 정규화 β 검증 ({d[0]}~{d[-1]}) ===")
    print(f"{'연도':<6}{'거래대금조':>9}{'  외인raw':>9}{'외인norm':>9}{'개인norm':>9}{'외인flow%':>10}{'개인flow%':>10}")
    for y in sorted(years):
        idx = years[y]
        if len(idx) < 30:
            continue
        rr = [ret[i] for i in idx]
        tov_avg = sum(tov[i] for i in idx if tov[i]) / sum(1 for i in idx if tov[i]) / 1e4  # 조원
        bf_raw = beta([nets["외국인"][i] for i in idx], rr)
        bf_n = beta([norm["외국인"][i] for i in idx], rr)
        bg_n = beta([norm["개인"][i] for i in idx], rr)
        # flow강도: 평균 |net|/거래대금 (%)
        fi_f = sum(abs(norm["외국인"][i]) for i in idx if norm["외국인"][i] is not None) / len(idx) * 100
        fi_g = sum(abs(norm["개인"][i]) for i in idx if norm["개인"][i] is not None) / len(idx) * 100
        print(f"{y:<6}{tov_avg:>9.1f}{bf_raw*1e6:>9.2f}{bf_n:>9.2f}{bg_n:>9.2f}{fi_f:>10.1f}{fi_g:>10.1f}")

    print("\n해석: 외인norm β 가 우하향이면 구조적(거래대금 대비 영향력 실제 하락),")
    print("      평평하면 raw β 하락은 거래량 증가 착시. flow% = 그 주체 순매수의 거래대금 대비 크기.")


if __name__ == "__main__":
    main()
