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

    # 4.5) KOSPI 지수 종가 → 일별수익률 (방향주도 판정용). dates 와 정렬.
    try:
        time.sleep(THROTTLE_SEC)
        idx = stock.get_index_ohlcv(start, end, "1001")   # 1001=KOSPI
        close_by_date = {d.strftime("%Y-%m-%d"): float(c) for d, c in zip(idx.index, idx["종가"])}
        closes = [close_by_date.get(ds) for ds in out["dates"]]
        out["index_close"] = [round(c, 2) if c is not None else None for c in closes]
        out["index_ret"] = [None] + [   # 일별수익률(%), index_ret[i]=dates[i] 당일 등락
            round((closes[i] / closes[i - 1] - 1) * 100, 3)
            if closes[i] and closes[i - 1] else None for i in range(1, len(closes))]
    except Exception as e:
        out["index_error"] = str(e)[:120]
        out["index_close"], out["index_ret"] = [], []

    # 5) 시장 주도 주체(regime)
    #    ① dominant: 5일 최대 순매수 주체(자금 규모)  ② leader: 순매수 방향과 지수 방향이 일치하는 주체
    #    세 주체 순매수 합은 ~0(사는 쪽↔받아주는 쪽 짝) → 규모가 아니라 '가격이 누구 편이었나'로 주도성 판정.
    def _sum5(key):
        a = (out.get(key) or [])[-5:]
        return round(sum(x for x in a if x is not None) / 1e4, 1) if a else 0   # 억→조
    def _avg5(key):
        a = [x for x in (out.get(key) or [])[-5:] if x is not None]
        return round(sum(a) / len(a), 1) if a else 0
    nets = {"개인": _sum5("indiv_net"), "외국인": _sum5("foreign_net"), "기관": _sum5("inst_net")}
    shares = {"개인": _avg5("indiv_share"), "외국인": _avg5("foreign_share"), "기관": _avg5("inst_share")}
    dominant = max(nets, key=lambda k: nets[k])          # 5일 최대 순매수 주체 = 자금 주도

    def _corr(xs, ys):
        """Pearson corr — None-쌍 제외, 표본<2 또는 분산0이면 None."""
        ps = [(x, y) for x, y in zip(xs, ys) if x is not None and y is not None]
        if len(ps) < 2:
            return None
        mx = sum(p[0] for p in ps) / len(ps); my = sum(p[1] for p in ps) / len(ps)
        sxx = sum((p[0] - mx) ** 2 for p in ps); syy = sum((p[1] - my) ** 2 for p in ps)
        if sxx <= 0 or syy <= 0:
            return None
        sxy = sum((p[0] - mx) * (p[1] - my) for p in ps)
        return round(sxy / (sxx ** 0.5 * syy ** 0.5), 2)

    def _conc(ns, rs):
        """부호일치 비율 — 순매수·수익률 부호가 같은 날 비율(0 제외)."""
        ps = [(n, r) for n, r in zip(ns, rs) if n not in (None, 0) and r not in (None, 0)]
        if not ps:
            return None
        return round(sum(1 for n, r in ps if (n > 0) == (r > 0)) / len(ps), 2)

    nets_daily = {"개인": out.get("indiv_net") or [], "외국인": out.get("foreign_net") or [],
                  "기관": out.get("inst_net") or []}
    rets_daily = out.get("index_ret") or []
    leader: dict = {}
    for w in (5, 20):
        r_w = rets_daily[-w:]
        idx_ret_w = None
        cl = out.get("index_close") or []
        if len(cl) > w and cl[-1] and cl[-1 - w]:
            idx_ret_w = round((cl[-1] / cl[-1 - w] - 1) * 100, 2)   # 윈도우 지수 등락(%)
        corr = {k: _corr(v[-w:], r_w) for k, v in nets_daily.items()}
        conc = {k: _conc(v[-w:], r_w) for k, v in nets_daily.items()}
        valid = {k: c for k, c in corr.items() if c is not None}
        by_corr = max(valid, key=lambda k: valid[k]) if valid else None
        absorber = min(valid, key=lambda k: valid[k]) if valid else None
        vc = {k: c for k, c in conc.items() if c is not None}
        by_conc = max(vc, key=lambda k: vc[k]) if vc else None
        leader[str(w)] = {"by_corr": by_corr, "absorber_corr": absorber, "by_conc": by_conc,
                          "corr": corr, "conc": conc, "index_ret_pct": idx_ret_w}
    out["regime"] = {"dominant": dominant, "nets_5d": nets, "shares_5d": shares, "leader": leader}

    # 6) regime 전환 게이지 — 개인 norm β(행태) + 거래대금·flow강도(규모)
    #    예금→주식 이동이 ① 규모(거래대금·flow강도↑)로 오는지 ② 행태(개인 역추세 약화=β→0)로 오는지 분리.
    #    norm = 순매수(억)/거래대금(억) → 규모중립(거래량 증가 착시 제거). 8년 검증: analyze_norm_beta.py
    def _beta(xs, ys):
        ps = [(x, y) for x, y in zip(xs, ys) if x is not None and y is not None]
        if len(ps) < 10:
            return None
        n = len(ps); mx = sum(p[0] for p in ps) / n; my = sum(p[1] for p in ps) / n
        sxx = sum((p[0] - mx) ** 2 for p in ps)
        return round(sum((p[0] - mx) * (p[1] - my) for p in ps) / sxx, 2) if sxx > 0 else None
    rets = [(r / 100) if r is not None else None for r in (out.get("index_ret") or [])]  # %→소수(β 기준선과 일치)
    tv = out.get("total_value") or []   # 조원(매수기준 거래대금)
    def _norm(netkey):
        arr = out.get(netkey) or []
        return [(arr[i] / (tv[i] * 1e4)) if (i < len(tv) and tv[i] and arr[i] is not None) else None
                for i in range(len(arr))]
    ni, nf = _norm("indiv_net"), _norm("foreign_net")
    def _fi(series, w):   # flow강도(%) = 평균 |순매수|/거래대금
        s = [abs(x) for x in series[-w:] if x is not None]
        return round(sum(s) / len(s) * 100, 1) if s else None
    def _tavg(w):
        s = [x for x in tv[-w:] if x]
        return round(sum(s) / len(s), 1) if s else None
    W = 120   # 최근 ~6개월 윈도우
    # 롤링 개인 norm β 추세(2년 캐시 내 120일 윈도우, 20일 간격 샘플) — 즉시 시각화용
    btrend = []
    for j in range(W, len(ni), 20):
        b = _beta(ni[j - W:j], rets[j - W:j])
        if b is not None and j - 1 < len(out["dates"]):
            btrend.append({"date": out["dates"][j - 1], "beta": b})
    out["regime"]["gauge"] = {
        "win": W,
        "beta_indiv": _beta(ni[-W:], rets[-W:]),      # 개인 행태(음수 강할수록 역추세 흡수 강함, 0 접근=전환조짐)
        "beta_foreign": _beta(nf[-W:], rets[-W:]),
        "fi_indiv": _fi(ni, W), "fi_foreign": _fi(nf, W),
        "turnover_recent": _tavg(20), "turnover_base": _tavg(len(tv)),
        "beta_trend": btrend,
        # 8년(analyze_norm_beta) 기준선 — 참고 baseline
        "ref": {"beta_indiv": "-0.13~-0.29", "fi_indiv_2018": 2.9, "fi_indiv_2026": 5.9,
                "turnover_2025": 12.4, "turnover_2026": 33.8},
    }

    # regime 스냅샷 시계열 적재(전환 감지 장기 추적) — 같은 날 중복 방지, append-only
    try:
        g = out["regime"]["gauge"]; anchor = out["dates"][-1] if out["dates"] else None
        if anchor:
            hp = ROOT / "data" / "regime_history.jsonl"
            last = None
            if hp.exists():
                ls = hp.read_text(encoding="utf-8").strip().splitlines()
                last = json.loads(ls[-1]).get("date") if ls else None
            if last != anchor:
                snap = {"date": anchor, "leader5": leader["5"]["by_corr"], "leader20": leader["20"]["by_corr"],
                        "dominant": dominant, "beta_indiv": g["beta_indiv"], "beta_foreign": g["beta_foreign"],
                        "fi_indiv": g["fi_indiv"], "turnover": g["turnover_recent"]}
                with hp.open("a", encoding="utf-8") as f:
                    f.write(json.dumps(snap, ensure_ascii=False) + "\n")
    except Exception:
        pass

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
        ld = rg.get("leader", {})
        t5 = d["tops"].get("5", {}).get(dom, {}).get("top_value", [])
        print(f"[OK] {d['updated']} / {len(d['dates'])}거래일 / 누적순매수 {d['indiv_cum'][-1] if d['indiv_cum'] else 'NA'}조"
              f"\n  자금주도(최대순매수): {dom} / 5일순매수(조) {rg.get('nets_5d')} / 거래비중(%) {rg.get('shares_5d')}")
        for w in ("5", "20"):
            x = ld.get(w, {})
            print(f"  방향주도 {w}일: corr→{x.get('by_corr')} / 부호일치→{x.get('by_conc')} "
                  f"/ 받아주는쪽→{x.get('absorber_corr')} (지수 {x.get('index_ret_pct')}% · corr {x.get('corr')})")
        print(f"  [{dom}] 5일 거래대금상위 {[t['name'] for t in t5[:5]]}")
