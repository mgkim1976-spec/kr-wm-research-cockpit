"""
장기(8년) 주도세력 × 경기사이클 분석 — KRX 수급 + FRED OECD 한국 경기선행지수(CLI).

데이터(1회 수집 후 data/krx_history.json 캐시; --refetch 로 갱신):
  · KRX 일별 투자자 순매수(개인/외국인/기관) + KOSPI 종가  (pykrx, 로그인)
  · FRED KORLOLITOAASTSAM = OECD 한국 CLI(진폭조정, 월별, 100 기준)  (API키 불필요)

산출:
  ① 매일의 방향주도 주체 = 롤링 W일 corr(주체 순매수, 지수 수익률) 최대
  ② CLI 4국면(회복/확장/둔화/수축)별 주도세력 분포
  ③ 국면 전환행렬 + 평균 지속일
  ④ 전환 직후 fwd일 지수수익률 — 원시 & 시장중립(전체평균 대비 초과)

한계(정직): CLI는 1~2개월 발표지연·사후수정 → 본 분석은 '관계 기술(descriptive)'이지
  실시간 트레이딩 신호 아님. corr 라벨은 후행. 8년이라 각 국면 표본 여전히 제한적.
"""
from __future__ import annotations
import json
import time
import urllib.request
import datetime as dt
from pathlib import Path

ROOT = Path(__file__).parent
HIST = ROOT / "data" / "krx_history.json"
ACTORS = {"개인": "indiv_net", "외국인": "foreign_net", "기관": "inst_net"}
CLI_URL = "https://fred.stlouisfed.org/graph/fredgraph.csv?id=KORLOLITOAASTSAM"


# ── 수집 ──────────────────────────────────────────────────────────────────────
def fetch_history(years: int = 8) -> dict:
    import sys
    sys.path.insert(0, str(ROOT / "app" / "core" / "adapters"))
    import krx_market as km
    km._load_creds()
    from pykrx import stock
    end = dt.datetime.now(); start = end - dt.timedelta(days=365 * years + 30)
    s, e = start.strftime("%Y%m%d"), end.strftime("%Y%m%d")
    net = stock.get_market_trading_value_by_date(s, e, "KOSPI")
    time.sleep(0.6)
    idx = stock.get_index_ohlcv(s, e, "1001")
    close_by = {d.strftime("%Y-%m-%d"): float(c) for d, c in zip(idx.index, idx["종가"])}
    dates = [d.strftime("%Y-%m-%d") for d in net.index]
    out = {"dates": dates,
           "indiv_net": [round(float(v) / 1e8, 0) for v in net["개인"]],
           "foreign_net": [round(float(v) / 1e8, 0) for v in net["외국인합계"]],
           "inst_net": [round(float(v) / 1e8, 0) for v in net["기관합계"]],
           "close": [round(close_by.get(d), 2) if close_by.get(d) else None for d in dates]}
    HIST.write_text(json.dumps(out, ensure_ascii=False), encoding="utf-8")
    return out


def fetch_cli() -> list[tuple[str, float]]:
    raw = urllib.request.urlopen(CLI_URL, timeout=30).read().decode()
    rows = []
    for line in raw.splitlines()[1:]:
        d, v = line.split(",")
        if v.strip() in (".", ""):
            continue
        rows.append((d, float(v)))
    return rows


def classify_phases(cli: list[tuple[str, float]]) -> dict[str, str]:
    """월별 CLI → 4국면. 100 기준 above/below × 전월대비 방향."""
    ph = {}
    for i in range(1, len(cli)):
        (d, v), (_, pv) = cli[i], cli[i - 1]
        above, rising = v >= 100, v >= pv
        ph[d[:7]] = ("확장" if above and rising else "둔화" if above and not rising
                     else "회복" if not above and rising else "수축")
    return ph


# ── 분석 ──────────────────────────────────────────────────────────────────────
def _corr(xs, ys):
    ps = [(x, y) for x, y in zip(xs, ys) if x is not None and y is not None]
    if len(ps) < 3:
        return None
    n = len(ps); mx = sum(p[0] for p in ps) / n; my = sum(p[1] for p in ps) / n
    sxx = sum((p[0] - mx) ** 2 for p in ps); syy = sum((p[1] - my) ** 2 for p in ps)
    if sxx <= 0 or syy <= 0:
        return None
    return sum((p[0] - mx) * (p[1] - my) for p in ps) / (sxx ** 0.5 * syy ** 0.5)


def rolling_leader(h: dict, win: int) -> list:
    dates, close = h["dates"], h["close"]
    nets = {a: h[k] for a, k in ACTORS.items()}
    N = len(dates)
    ret = [None] + [(close[i] / close[i - 1] - 1) if close[i] and close[i - 1] else None
                    for i in range(1, N)]
    leader = [None] * N
    for i in range(win, N):
        sl = slice(i - win + 1, i + 1)
        cors = {a: _corr(nets[a][sl], ret[sl]) for a in ACTORS}
        cors = {a: c for a, c in cors.items() if c is not None}
        if cors:
            leader[i] = max(cors, key=lambda a: cors[a])
    return leader, ret


def episodes(dates, close, leader, win, min_dur=3):
    eps = []
    for i in range(win, len(dates)):
        L = leader[i]
        if L is None:
            continue
        if eps and eps[-1]["leader"] == L:
            eps[-1]["end_i"] = i
        else:
            eps.append({"leader": L, "start_i": i, "end_i": i})
    merged = []
    for ep in eps:
        if merged and (ep["end_i"] - ep["start_i"] + 1) < min_dur:
            merged[-1]["end_i"] = ep["end_i"]
        else:
            merged.append(ep)
    for ep in merged:
        ep["dur"] = ep["end_i"] - ep["start_i"] + 1
        ep["start"], ep["end"] = dates[ep["start_i"]], dates[ep["end_i"]]
    return merged


def main(win=60, fwd=20, refetch=False):
    h = fetch_history() if (refetch or not HIST.exists()) else json.loads(HIST.read_text(encoding="utf-8"))
    dates, close = h["dates"], h["close"]
    N = len(dates)
    phases = classify_phases(fetch_cli())
    leader, ret = rolling_leader(h, win)

    print(f"\n=== 장기 주도세력 × 경기사이클 (롤링 {win}일 / {N}거래일 {dates[0]}~{dates[-1]}) ===")

    # ② 국면별 주도세력 분포 (거래일 카운트)
    from collections import Counter, defaultdict
    by_phase = defaultdict(Counter); phase_days = Counter()
    fwd_all = []
    fwd_by_phase_leader = defaultdict(list)
    for i in range(win, N):
        ph = phases.get(dates[i][:7]); L = leader[i]
        if not ph or not L:
            continue
        by_phase[ph][L] += 1; phase_days[ph] += 1
        if i + fwd < N and close[i] and close[i + fwd]:
            fr = (close[i + fwd] / close[i] - 1) * 100
            fwd_all.append(fr); fwd_by_phase_leader[(ph, L)].append(fr)
    mkt_mean = sum(fwd_all) / len(fwd_all) if fwd_all else 0

    print(f"\n--- ② CLI 국면별 주도세력 비중(거래일%) | 전체 평균 {fwd}일 지수수익 {mkt_mean:+.1f}% ---")
    for ph in ["회복", "확장", "둔화", "수축"]:
        tot = phase_days[ph]
        if not tot:
            continue
        dist = " ".join(f"{a} {by_phase[ph][a]/tot*100:>4.0f}%" for a in ["외국인", "기관", "개인"])
        print(f"  {ph}({tot:>4}일): {dist}")

    # ③ 전환행렬 + 지속일
    eps = episodes(dates, close, leader, win)
    trans = defaultdict(Counter); dwell = defaultdict(list)
    for a, b in zip(eps, eps[1:]):
        trans[a["leader"]][b["leader"]] += 1
    for ep in eps:
        dwell[ep["leader"]].append(ep["dur"])
    print(f"\n--- ③ 국면 {len(eps)}개 · 평균 지속일 ---")
    for a in ["외국인", "기관", "개인"]:
        if dwell[a]:
            print(f"  {a}: {len(dwell[a])}회 · 평균 {sum(dwell[a])/len(dwell[a]):.0f}일 · 최장 {max(dwell[a])}일")
    print("  전환행렬(행→열):    " + "".join(f"{a:>8}" for a in ["외국인", "기관", "개인"]))
    for a in ["외국인", "기관", "개인"]:
        print(f"    {a:<6}" + "".join(f"{trans[a].get(b,0):>8}" for b in ["외국인", "기관", "개인"]))

    # ④ 전환 직후 수익률 — 원시 & 시장중립(초과)
    fwd_to = defaultdict(list)
    for ep in eps[1:]:
        si = ep["start_i"]
        if si + fwd < N and close[si] and close[si + fwd]:
            fwd_to[ep["leader"]].append((close[si + fwd] / close[si] - 1) * 100)
    print(f"\n--- ④ 전환 직후 {fwd}일 지수수익률 (시장평균 {mkt_mean:+.1f}% 차감=초과) ---")
    for a in ["외국인", "기관", "개인"]:
        xs = fwd_to.get(a, [])
        if xs:
            m = sum(xs) / len(xs)
            print(f"  →{a} 전환 {len(xs):>2}회: 원시 {m:+.1f}% · 초과 {m-mkt_mean:+.1f}% · 승률 {sum(1 for x in xs if x>0)/len(xs)*100:.0f}%")

    # 국면별 forward 초과수익 (주도세력×국면 상호작용)
    print(f"\n--- ④b 국면×주도 {fwd}일 초과수익(시장중립) — 표본≥5만 ---")
    for ph in ["회복", "확장", "둔화", "수축"]:
        cells = []
        for a in ["외국인", "기관", "개인"]:
            xs = fwd_by_phase_leader.get((ph, a), [])
            if len(xs) >= 5:
                cells.append(f"{a} {sum(xs)/len(xs)-mkt_mean:+.1f}%(n{len(xs)})")
        if cells:
            print(f"  {ph}: " + " · ".join(cells))


if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--win", type=int, default=60)
    ap.add_argument("--fwd", type=int, default=20)
    ap.add_argument("--refetch", action="store_true")
    a = ap.parse_args()
    main(a.win, a.fwd, a.refetch)
