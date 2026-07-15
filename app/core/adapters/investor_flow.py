"""
투자자별 자금 이동 어댑터 (pykrx) — 지분이 '누구에게서 누구로' 넘어가는지 추적.

2010~현재, KOSPI·KOSDAQ 각각:
  1. 투자자 세분 순매수(외국인·연기금·사모·투신·금융투자·개인) — 시장당 1콜(rate-limit 무관)
     → 주별 순매수 / 누적(스톡 변화 근사) / 최근 롤링(현재 이동 강도)
  2. 외국인 지분율(시총가중) — 월말 샘플(절대 스톡, 유일하게 확정되는 지분율)

⚙️ Rate-limit 안전: 순매수는 기간 전체 1콜(시장당) = 2콜. 외국인 지분율만 월별 루프(throttle).
   대시보드는 data/investor_flow.json 캐시만 읽고 KRX 직접 호출 안 함(일 1회 배치만 접속).

⚠️ 순매수 누적은 '금액 플로우의 적분'이라 절대 지분율이 아니다(주가 변동 무시). 이동 방향·강도는
   정확하나 '누가 몇 %'는 알 수 없다. 절대 지분율이 확정되는 건 외국인(foreign_pct)뿐.
"""
from __future__ import annotations

import json
import time
from datetime import date
from pathlib import Path

import krx_market  # 같은 adapters 디렉토리 — 자격 로드 재사용

ROOT = Path(__file__).resolve().parents[3]
OUT_PATH = ROOT / "data" / "investor_flow.json"

START = "20100101"
THROTTLE = 0.4               # 외국인 지분율 월별 루프 간격(rate-limit 회피)
MARKETS = ("KOSPI", "KOSDAQ")
# 표시 주요 투자자(자금 이동의 핵심 주체). pykrx detail 컬럼명과 일치.
INVESTORS = ["외국인", "연기금", "사모", "투신", "금융투자", "개인"]
ROLL = 60                    # 롤링 윈도우(거래일) — 현재 자금 이동 강도


def _foreign_pct(stock, d: str, market: str) -> float | None:
    """그날 시총가중 외국인 지분율(%) — Σ(지분율×시총)/Σ시총."""
    try:
        ex = stock.get_exhaustion_rates_of_foreign_investment(d, market=market)
        cap = stock.get_market_cap_by_ticker(d, market=market)
        m = ex.join(cap[["시가총액"]], how="inner")
        tot = m["시가총액"].sum()
        return round((m["지분율"] / 100 * m["시가총액"]).sum() / tot * 100, 2) if tot else None
    except Exception:
        return None


def build_cache(today: date | None = None) -> dict:
    """KOSPI·KOSDAQ 투자자 순매수 세분(2010~) + 외국인 지분율 월별 → JSON 캐시."""
    import pandas as pd
    krx_market._load_creds()
    from pykrx import stock

    today = today or date.today()
    end = today.strftime("%Y%m%d")
    out = {"updated": today.isoformat(), "start": START[:4], "investors": INVESTORS,
           "roll": ROLL, "markets": {}}

    for mkt in MARKETS:
        # 1) 순매수 세분 — 시장당 1콜(rate-limit 무관)
        fv = stock.get_market_trading_value_by_date(START, end, mkt, detail=True)
        time.sleep(THROTTLE)
        cols = [c for c in INVESTORS if c in fv.columns]
        inv = fv[cols].astype("float64") / 1e8            # 억원
        weekly = inv.resample("W").sum().round(0)          # 주별 순매수
        cum = inv.cumsum().resample("W").last().round(0)   # 누적(주별 포인트) = 스톡 변화 근사
        roll = inv.rolling(ROLL).sum().round(0)            # 롤링 순매수

        def _ser(df):  # {날짜: {투자자: 값}} (NaN 제거)
            return {ix.strftime("%Y-%m-%d"): {c: (None if pd.isna(r[c]) else float(r[c])) for c in cols}
                    for ix, r in df.iterrows()}

        roll_latest = {c: (None if pd.isna(roll[c].iloc[-1]) else float(roll[c].iloc[-1])) for c in cols}

        # 2) 외국인 지분율 — 월말 영업일 시총가중(절대 스톡)
        fpct = {}
        for m in pd.date_range(START, end, freq="BME"):
            ds = m.strftime("%Y%m%d")
            v = _foreign_pct(stock, ds, mkt)
            if v is not None:
                fpct[m.strftime("%Y-%m")] = v
            time.sleep(THROTTLE)

        out["markets"][mkt] = {
            "weekly": _ser(weekly),
            "cumulative": _ser(cum),
            "rolling_latest": roll_latest,
            "foreign_pct": fpct,
            "last_flow": _ser(inv.tail(5)),    # 최근 5일 일별 순매수(요약)
            "daily20": _ser(inv.tail(20)),     # 최근 20거래일 일별 순매수(대시보드 추이차트)
        }

    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUT_PATH.write_text(json.dumps(out, ensure_ascii=False), encoding="utf-8")
    return out


def load_cached() -> dict:
    try:
        return json.loads(OUT_PATH.read_text(encoding="utf-8"))
    except Exception:
        return {}


if __name__ == "__main__":
    o = build_cache()
    for mkt, d in o["markets"].items():
        print(f"\n[{mkt}] 주별 {len(d['weekly'])}주 · 외국인지분율 {len(d['foreign_pct'])}개월")
        print(f"  최근 {ROLL}일 롤링 순매수(억): " +
              " · ".join(f"{k} {int(v):+d}" for k, v in d["rolling_latest"].items() if v is not None))
        fp = list(d["foreign_pct"].items())
        if fp:
            print(f"  외국인 지분율: {fp[0][0]} {fp[0][1]}% → {fp[-1][0]} {fp[-1][1]}%")
