"""
KRX 시장 수급 어댑터 (pykrx) — 일일 배치에서 호출해 data/krx_market.json 캐시.

수집(전부 일별, 최근 N영업일):
  1. 거래대금 추이 (전체 시장, 매수 기준 one-side)
  2. 개인/외국인/기관 순매수 거래대금 추이
  3. 개인 거래대금 비중 추이
  4. 개인 순매수 상위/하위 종목

⚙️ Rate-limit 안전 설계: KRX 호출 총 4회(일별 루프 없음). 호출 간 throttle.
   대시보드는 캐시(JSON)만 읽고 KRX를 직접 호출하지 않는다 → 일 1회 배치만 접속.

🔑 KRX 로그인 자격: 로컬 .env(KRX_ID/KRX_PW) 우선, 없으면 환경변수/형제 .env.
"""
from __future__ import annotations

import datetime as dt
import json
import os
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
OUT_PATH = ROOT / "data" / "krx_market.json"

THROTTLE_SEC = 0.6   # KRX 호출 간 최소 간격 (rate-limit 회피)

def _load_creds() -> bool:
    """KRX_ID/KRX_PW 로드: 환경변수 → 로컬 .env."""
    if os.environ.get("KRX_ID") and os.environ.get("KRX_PW"):
        return True
    env_path = ROOT / ".env"
    if env_path.exists():
        try:
            for line in env_path.read_text(encoding="utf-8").splitlines():
                s = line.strip()
                if s.startswith("KRX_ID=") and not os.environ.get("KRX_ID"):
                    os.environ["KRX_ID"] = s.split("=", 1)[1].strip()
                elif s.startswith("KRX_PW=") and not os.environ.get("KRX_PW"):
                    os.environ["KRX_PW"] = s.split("=", 1)[1].strip()
        except Exception:
            pass
    return bool(os.environ.get("KRX_ID") and os.environ.get("KRX_PW"))


def fetch_market(years: float = 2, market: str = "KOSPI", top_n: int = 12,
                 top_days: int = 5) -> dict:
    """추이 차트: 최근 years년 / 거래대금 상위종목: 최근 top_days영업일(수수료 직결=단기 거래활발).
    핵심: indiv_cum(개인 누적 순매수, 조원) — 우상향=현금→주식 매집 / 우하향=주식→현금 현금화."""
    _load_creds()   # 로그인형 pykrx면 자격 사용 / 표준 pip pykrx는 익명(자격 불필요)
    try:
        from pykrx import stock
    except Exception as e:   # noqa: BLE001
        return {"error": f"pykrx 임포트 실패: {e}"}

    end_d = dt.datetime.now()
    start_d = end_d - dt.timedelta(days=int(365 * years) + 30)
    start, end = start_d.strftime("%Y%m%d"), end_d.strftime("%Y%m%d")

    out: dict = {"market": market, "updated": dt.datetime.now().strftime("%Y-%m-%d %H:%M"),
                 "years": years, "windows": [1, 5, 20], "sankey_days": 5,
                 "dates": [], "indiv_net": [], "indiv_cum": [], "foreign_net": [], "inst_net": [],
                 "total_value": [], "indiv_value": [], "indiv_share": [], "foreign_share": [],
                 "inst_share": [], "tops": {}}
    bdays: list = []

    def _tv(on: str | None = None):
        time.sleep(THROTTLE_SEC)
        if on:
            return stock.get_market_trading_value_by_date(start, end, market, on=on)
        return stock.get_market_trading_value_by_date(start, end, market)

    # 1) 순매수 추이 + 누적 순매수(현금화/매집 방향)
    try:
        net = _tv()
        bdays = list(net.index)
        out["dates"] = [d.strftime("%Y-%m-%d") for d in net.index]
        gae = net["개인"].astype(float)
        out["indiv_net"] = [round(float(v) / 1e8, 0) for v in gae]            # 억원(일별)
        out["indiv_cum"] = [round(float(v) / 1e12, 1) for v in gae.cumsum()]  # 조원(누적)
        for col, key in [("외국인합계", "foreign_net"), ("기관합계", "inst_net")]:
            if col in net.columns:
                out[key] = [round(float(v) / 1e8, 0) for v in net[col]]
    except Exception as e:
        out["net_error"] = str(e)[:120]

    # 2~3) gross 매수/매도 → 전체 거래대금 + 개인 거래대금(수수료 직결) + 개인 비중 (2콜)
    try:
        buy = _tv("매수")
        sell = _tv("매도")
        out["total_value"] = [round(float(v) / 1e12, 2) for v in buy["전체"]]   # 조원(매수 기준)
        gi = buy["개인"].values + sell["개인"].values                            # 개인 gross(매수+매도)
        gt = buy["전체"].values + sell["전체"].values
        gf = buy["외국인합계"].values + sell["외국인합계"].values
        gn = buy["기관합계"].values + sell["기관합계"].values
        out["indiv_value"] = [round(float(gi[i]) / 1e12, 2) for i in range(len(buy))]   # 조원
        def _share(arr):
            return [round(float(arr[i]) / float(gt[i]) * 100, 1) if gt[i] else None for i in range(len(buy))]
        out["indiv_share"] = _share(gi)
        out["foreign_share"] = _share(gf)
        out["inst_share"] = _share(gn)
    except Exception as e:
        out["gross_error"] = str(e)[:120]

    # 4) 주체별(개인/외국인/기관) × 윈도우별(1/5/20영업일) 거래대금/순매수/순매도 상위
    investors = [("개인", "개인"), ("외국인", "외국인"), ("기관", "기관합계")]
    end_b = bdays[-1].strftime("%Y%m%d") if bdays else end
    for w in out["windows"]:
        if not bdays:
            break
        w_start = (bdays[-w] if len(bdays) >= w else bdays[0]).strftime("%Y%m%d")
        out["tops"][str(w)] = {}
        for disp, inv in investors:
            try:
                time.sleep(THROTTLE_SEC)
                npe = stock.get_market_net_purchases_of_equities(w_start, end_b, market, inv)
                npe = npe.assign(_gross=npe["매수거래대금"] + npe["매도거래대금"])

                def _val(tk, _n=npe):
                    r = _n.loc[tk]
                    return {"ticker": tk, "name": r.get("종목명", ""),
                            "trade_value": round(float(r["_gross"]) / 1e12, 2)}
                def _net(tk, _n=npe):
                    r = _n.loc[tk]
                    return {"ticker": tk, "name": r.get("종목명", ""),
                            "net_value": round(float(r["순매수거래대금"]) / 1e8)}

                by_val = npe.sort_values("_gross", ascending=False)
                by_net = npe.sort_values("순매수거래대금", ascending=False)
                out["tops"][str(w)][disp] = {
                    "top_value": [_val(tk) for tk in by_val.head(top_n).index],
                    "top_buy": [_net(tk) for tk in by_net.head(top_n).index],
                    "top_sell": [_net(tk) for tk in by_net.tail(top_n).index][::-1],
                }
            except Exception as e:
                out.setdefault("top_error", {})[f"{w}_{disp}"] = str(e)[:120]

    # 5) 시장 주도 주체(regime) — 최근 5영업일 순매수 합(조) + 거래비중 평균(%)
    def _sum5(key):
        a = (out.get(key) or [])[-5:]
        return round(sum(x for x in a if x is not None) / 1e4, 1) if a else 0   # 억→조
    def _avg5(key):
        a = [x for x in (out.get(key) or [])[-5:] if x is not None]
        return round(sum(a) / len(a), 1) if a else 0
    nets = {"개인": _sum5("indiv_net"), "외국인": _sum5("foreign_net"), "기관": _sum5("inst_net")}
    shares = {"개인": _avg5("indiv_share"), "외국인": _avg5("foreign_share"), "기관": _avg5("inst_share")}
    dominant = max(nets, key=lambda k: nets[k])          # 5일 최대 순매수 주체 = 자금 주도
    out["regime"] = {"dominant": dominant, "nets_5d": nets, "shares_5d": shares}

    return out


def save(years: float = 2, market: str = "KOSPI") -> dict:
    data = fetch_market(years=years, market=market)
    if "error" not in data:
        OUT_PATH.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    return data


def load_cached() -> dict:
    try:
        return json.loads(OUT_PATH.read_text(encoding="utf-8"))
    except Exception:
        return {"error": "krx_market.json 캐시 없음 — daily_update.sh 실행 필요"}


if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--years", type=float, default=2)
    ap.add_argument("--market", default="KOSPI")
    args = ap.parse_args()
    d = save(years=args.years, market=args.market)
    if "error" in d:
        print("실패:", d["error"])
    else:
        rg = d.get("regime", {})
        dom = rg.get("dominant", "개인")
        t5 = d["tops"].get("5", {}).get(dom, {}).get("top_value", [])
        print(f"[OK] {d['updated']} / {len(d['dates'])}거래일 / 누적순매수 {d['indiv_cum'][-1] if d['indiv_cum'] else 'NA'}조"
              f"\n  주도주체: {dom} / 5일순매수(조) {rg.get('nets_5d')} / 거래비중(%) {rg.get('shares_5d')}"
              f"\n  [{dom}] 5일 거래대금상위 {[t['name'] for t in t5[:5]]}")
