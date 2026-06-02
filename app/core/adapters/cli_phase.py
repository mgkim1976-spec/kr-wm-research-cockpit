"""
OECD 한국 경기선행지수(CLI) 국면 어댑터 — FRED KORLOLITOAASTSAM(월별, API키 불필요).

100기준 above/below × 전월대비 방향 → 4국면(회복/확장/둔화/수축).
+ 과거 8년(data/krx_history.json) 국면별 fwd 지수수익률 통계(시장중립 초과 포함).
→ data/cli_phase.json 캐시. 대시보드는 캐시만 읽음. daily_update 가 갱신(월1 변동이라 매일 호출해도 무방).

한계: CLI는 1~2개월 발표지연·사후수정 → 'current'는 최신 발표월 기준(as_of). 실시간 신호 아닌 국면 참고.
"""
from __future__ import annotations
import json
import urllib.request
import datetime as dt
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
OUT = ROOT / "data" / "cli_phase.json"
HIST = ROOT / "data" / "krx_history.json"
CLI_URL = "https://fred.stlouisfed.org/graph/fredgraph.csv?id=KORLOLITOAASTSAM"


def fetch_cli() -> list[tuple[str, float]]:
    raw = urllib.request.urlopen(CLI_URL, timeout=30).read().decode()
    out = []
    for line in raw.splitlines()[1:]:
        d, v = line.split(",")
        if v.strip() not in (".", ""):
            out.append((d, float(v)))
    return out


def _phase(v: float, pv: float) -> str:
    above, rising = v >= 100, v >= pv
    return ("확장" if above and rising else "둔화" if above and not rising
            else "회복" if not above and rising else "수축")


def phase_series(cli: list[tuple[str, float]]) -> dict[str, str]:
    return {cli[i][0][:7]: _phase(cli[i][1], cli[i - 1][1]) for i in range(1, len(cli))}


def fwd_stats(phases: dict[str, str], fwd: int = 20) -> tuple[dict, float]:
    """8년 KOSPI로 국면별 fwd일 수익률 통계."""
    if not HIST.exists():
        return {}, 0.0
    h = json.loads(HIST.read_text(encoding="utf-8"))
    dates, close = h["dates"], h["close"]
    N = len(dates)
    from collections import defaultdict
    by, allr = defaultdict(list), []
    for i in range(N - fwd):
        ph = phases.get(dates[i][:7])
        if not ph or not close[i] or not close[i + fwd]:
            continue
        r = (close[i + fwd] / close[i] - 1) * 100
        by[ph].append(r); allr.append(r)
    mkt = sum(allr) / len(allr) if allr else 0.0
    stats = {}
    for ph, xs in by.items():
        xs2 = sorted(xs)
        stats[ph] = {"mean": round(sum(xs) / len(xs), 1), "median": round(xs2[len(xs2) // 2], 1),
                     "excess": round(sum(xs) / len(xs) - mkt, 1),
                     "win": round(sum(1 for x in xs if x > 0) / len(xs) * 100), "n": len(xs)}
    return stats, round(mkt, 1)


def build(fwd: int = 20) -> dict:
    cli = fetch_cli()
    ph = phase_series(cli)
    cur_m, cur_v = cli[-1][0][:7], cli[-1][1]
    cur_p = ph[cur_m]
    # 현재 국면 지속 개월수
    months = sorted(ph)
    since = 0
    for m in reversed(months):
        if ph[m] == cur_p:
            since += 1
        else:
            break
    recent = [{"month": m, "cli": round(dict(((d[:7], v) for d, v in cli))[m], 1), "phase": ph[m]}
              for m in months[-13:]]
    stats, mkt = fwd_stats(ph, fwd)
    out = {"updated": dt.datetime.now().strftime("%Y-%m-%d %H:%M"),
           "current": {"phase": cur_p, "cli": round(cur_v, 1), "as_of": cur_m,
                       "months_in_phase": since, "rising": cur_v >= cli[-2][1]},
           "recent": recent, "fwd_window": fwd, "mkt_mean": mkt, "fwd_stats": stats}
    OUT.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
    return out


def load_cached() -> dict:
    try:
        return json.loads(OUT.read_text(encoding="utf-8"))
    except Exception:
        return {"error": "cli_phase.json 캐시 없음"}


if __name__ == "__main__":
    d = build()
    c = d["current"]
    print(f"[OK] CLI 국면: {c['phase']} (지수 {c['cli']}, {c['as_of']} 기준, {c['months_in_phase']}개월째)")
    print(f"  과거 {d['fwd_window']}일 수익(시장평균 {d['mkt_mean']:+.1f}%):")
    for ph in ["회복", "확장", "둔화", "수축"]:
        s = d["fwd_stats"].get(ph)
        if s:
            print(f"   {ph}: 평균 {s['mean']:+.1f}% · 초과 {s['excess']:+.1f}% · 승률 {s['win']}% (n{s['n']})")
