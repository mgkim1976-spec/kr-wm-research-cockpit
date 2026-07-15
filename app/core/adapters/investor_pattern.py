"""
지수 변곡점 × 투자자 패턴 × forward 수익 base rate (pykrx + fdr).

큰 변곡점(낙폭·반등 12%↑) vs 작은 변곡점을 분리해, 각각:
  1. forward 지수 수익 6구간(1주~12개월) — 중앙값·사분위수(q25/q75) 중심(평균은 극단저점에 편향).
  2. 변곡점 전후 투자자 순매수 방향전환 승률·유의성(외국인·연기금·개인).
  3. 변곡점 간격(주기), 현재 국면 게이지(낙폭·반등·플로우).

⚙️ Rate-limit 안전: 시장당 순매수 1콜(=2콜) + fdr 지수. 대시보드는 investor_pattern.json 캐시만 조회.

⚠️ 정밀도(type1)까지 검증한 핵심 결론(중요):
  · 단일 자금흐름 전환은 예측력 없음(리프트<2, 헛신호 다수) — 재현율(승률)만 보면 착시.
  · 저점 예측력은 '가격 낙폭(-12%)'에 있음(리프트 2.9). +연기금 매수=3.4배·재현율79(최적 확인).
    (외국인은 정밀도 높으나 재현율29로 드묾. 사모·증권·투신도 2.5~3.0배 보조 유효.)
  · 고점은 예측 불가(상승존조차 1.2배) — 우상향 편향. 자금흐름 고점신호는 '진단용'으로만.
  · 하락장(60일-10%↓)에선 '항복=바닥' 성립 — 외국인·기관 투매 극심할수록 이후 반등↑(상관-0.47),
    개인 강한매수=반등↑(상관+0.46). 변곡점 예측과 별개의 진단 지표.
  · forward '평균 +36%'는 코로나급 극단 편향 → 중앙값(+13%) 기본 표기.
  → 이 도구는 '저점 매수 신호(낙폭+연기금)'·'하락장 항복 진단'이지, 고점 매도 예측기가 아니다.
"""
from __future__ import annotations

import json
from datetime import date
from pathlib import Path

import krx_market  # 같은 adapters — KRX 자격 로드 재사용

ROOT = Path(__file__).resolve().parents[3]
OUT_PATH = ROOT / "data" / "investor_pattern.json"

HZ = [5, 10, 21, 63, 126, 252]
HZL = ["1주", "2주", "1개월", "3개월", "6개월", "12개월"]
WIN, TH, W = 120, 0.12, 30          # 낙폭/반등 창·큰변곡점 임계·event study 창
MATCH = 30                          # 신호↔변곡점 매칭 허용일(±) — 정밀도/재현율 계산
MKTS = {"KOSPI": "KS11", "KOSDAQ": "KQ11"}
KEYINV = ["외국인", "연기금", "사모", "투신", "금융투자", "개인"]   # 전 주체 검증(사모·증권 포함)
# 저점 확인 최적 = 연기금(정밀도68·재현율79·리프트3.4). 외국인은 정밀도 높으나 재현율29(드묾).
CONFIRM = ["연기금", "금융투자", "사모", "투신", "외국인"]          # 저점 확인 주체(리프트순)


def _fwd_dist(arr, pts, N):
    """forward 수익 분포 — 중앙값·사분위수·평균·승률(평균은 극단편향이라 중앙값 우선)."""
    import numpy as np
    out = {}
    for i, h in enumerate(HZ):
        vals = [(arr[p + h] / arr[p] - 1) * 100 for p in pts if p + h < N]
        if vals:
            out[HZL[i]] = {"median": round(float(np.median(vals)), 1),
                           "q25": round(float(np.percentile(vals, 25)), 1),
                           "q75": round(float(np.percentile(vals, 75)), 1),
                           "mean": round(float(np.mean(vals)), 1),
                           "win": round(float(np.mean([v > 0 for v in vals])) * 100), "n": len(vals)}
    return out


def _inv_sig(fg, pts, N):
    """변곡점 전후 투자자 순매수 방향전환 승률(=재현율, 사후 관찰). ⚠️예측력 아님(정밀도는 _multi 참조).
    저점에서 매수전환하는 비율일 뿐, '전환하면 저점'은 아니다(단일 자금흐름 리프트<2)."""
    import numpy as np
    from scipy import stats
    out = {}
    for c in KEYINV:
        d = np.array([(fg[c].iloc[p:p + W].sum() - fg[c].iloc[p - W:p].sum())
                      for p in pts if p - W >= 0 and p + W < N])
        if len(d) < 3:
            continue
        _, pv = stats.ttest_1samp(d, 0)
        out[c] = {"recall_only": round(float((d > 0).mean()) * 100), "p": round(float(pv), 3), "n": len(d)}
    return out


def _multi_cond(arr, fg, BL, BH, N, match=MATCH, roll=60):
    """다중조건 정밀도 — 저점: 낙폭(주신호 2.9배)+각 주체 매수(연기금 3.4배 최적).
    ⚠️고점: 상승존+매도는 전부 리프트<2(우상향 편향으로 예측 불가) → 진단용으로만. 리프트≥2=유효."""
    import pandas as pd

    def near(i, pts):
        return any(abs(i - p) <= match for p in pts)

    def _c(mask, pts):
        base = sum(near(i, pts) for i in range(N)) / N * 100 if pts else 1
        sig = [i for i in range(N) if mask[i]]
        if not sig:
            return None
        prec = sum(near(s, pts) for s in sig) / len(sig) * 100
        rec = sum(near(p, sig) for p in pts) / len(pts) * 100 if pts else 0
        return {"precision": round(prec), "recall": round(rec),
                "lift": round(prec / base, 1), "n_sig": len(sig)}

    rollmax = pd.Series(arr).rolling(WIN, min_periods=1).max().values
    rollmin = pd.Series(arr).rolling(WIN, min_periods=1).min().values
    in_low = (arr / rollmax - 1) <= -TH
    in_high = (arr / rollmin - 1) >= TH
    rl = {c: fg[c].rolling(roll).sum().values for c in KEYINV}

    low = {"낙폭존": _c(in_low, BL)}                          # 주신호(예측)
    for c in CONFIRM:                                          # 낙폭 + 각 주체 매수(확인)
        low[f"낙폭+{c}"] = _c(in_low & (rl[c] > 0), BL)
    high = {"상승존": _c(in_high, BH)}                        # ⚠️ 다 리프트<2(예측 불가)
    for c in CONFIRM:
        high[f"상승+{c}매도"] = _c(in_high & (rl[c] < 0), BH)
    return {"low_predictive": low, "high_diagnostic_only": high}


def _down_market(arr, fg, N, down=-10, fwd=20):
    """하락장(60일 수익<-10%)에서 주체 순매수 vs 이후 20일 수익 상관 — '항복=바닥' 검증.
    스마트머니(외국인·기관) 투매 극심 → 이후 반등 큼(상관 음=역발상). 개인 강한매수 → 반등(상관 양).
    변곡점 예측(리프트)과 별개로, 하락 진행 중 '바닥 근접'을 주체 행태로 읽는 진단 지표."""
    import numpy as np
    import pandas as pd
    ret60 = pd.Series(arr).pct_change(60).values * 100
    dp = [i for i in range(60, N - fwd) if ret60[i] < down]
    if len(dp) < 20:
        return {}
    out = {"n_days": len(dp),
           "fwd_mean": round(float(np.mean([(arr[i + fwd] / arr[i] - 1) * 100 for i in dp])), 1)}
    corr = {}
    for c in KEYINV:
        r20 = pd.Series(fg[c].values).rolling(20).sum().values
        pr = [(r20[i], (arr[i + fwd] / arr[i] - 1) * 100) for i in dp if not np.isnan(r20[i])]
        if len(pr) >= 10:
            corr[c] = round(float(np.corrcoef([p[0] for p in pr], [p[1] for p in pr])[0, 1]), 2)
    out["corr"] = corr   # 음수=순매도 심할수록 이후↑(스마트머니 항복=바닥) · 양수=순매수 강할수록 이후↑
    return out


def _style_by_phase(arr, fg, index, N, pbm, look=20, fwd_w=20, sm=5):
    """국면 조건부 투자스타일 — 모멘텀축(순매수 vs 과거수익)·예측축(vs 미래수익). ⚠️스타일은 국면 의존
    (전체 상관은 상쇄 착시). 발견: 외국인=확장에만 역추세(차익), 개인=확장에만 추격(FOMO),
    증권=확장에만 선행. → '확장 후반=외국인 이탈+개인 추격'이 실전 경보. 상관 ±0.3~0.5(경향, 결정론 아님)."""
    import numpy as np
    import pandas as pd
    past = np.array([arr[i] / arr[i - look] - 1 if i >= look else np.nan for i in range(N)]) * 100
    fwd = np.array([arr[i + fwd_w] / arr[i] - 1 if i + fwd_w < N else np.nan for i in range(N)]) * 100
    pod = np.array([pbm.get(d.strftime("%Y-%m")) for d in index])
    out = {}
    for ph in ("회복", "확장", "둔화", "수축"):
        mask = pod == ph
        if mask.sum() < 20:
            continue
        d = {}
        for c in KEYINV:
            ns = fg[c].rolling(sm).sum().values
            m = pd.Series(ns)[mask].corr(pd.Series(past)[mask])
            f = pd.Series(ns)[mask].corr(pd.Series(fwd)[mask])
            d[c] = {"mom": None if pd.isna(m) else round(float(m), 2),
                    "pred": None if pd.isna(f) else round(float(f), 2)}
        out[ph] = d
    return out


def build_cache(today: date | None = None) -> dict:
    import FinanceDataReader as fdr
    import numpy as np
    import pandas as pd
    from scipy.signal import argrelextrema

    krx_market._load_creds()
    from pykrx import stock
    today = today or date.today()
    try:
        import cli_phase
        pbm = cli_phase.phase_series(cli_phase.fetch_cli())    # {월: 국면} — 국면별 스타일용(1회 로드)
    except Exception:
        pbm = {}
    cur_phase = pbm.get(sorted(pbm)[-1]) if pbm else None
    out = {"updated": today.isoformat(), "win_th": int(TH * 100), "hz": HZL,
           "cur_phase": cur_phase, "markets": {}}

    for mkt, code in MKTS.items():
        idx = fdr.DataReader(code, "2010-01-01", today.isoformat())["Close"]
        fv = stock.get_market_trading_value_by_date("20100101", today.strftime("%Y%m%d"), mkt, detail=True)
        fg = (fv[KEYINV].astype("float64") / 1e8)
        fg.index = pd.to_datetime(fg.index)
        idx.index = pd.to_datetime(idx.index)
        common = fg.index.intersection(idx.index)
        fg, ix = fg.loc[common], idx.loc[common]
        arr = ix.values
        N = len(arr)
        lows0 = argrelextrema(arr, np.less, order=40)[0]
        highs0 = argrelextrema(arr, np.greater, order=40)[0]

        def biglow(p):
            ph = arr[max(0, p - WIN):p].max() if p > 0 else arr[p]
            return (arr[p] / ph - 1) <= -TH and (arr[p:min(N, p + WIN)].max() / arr[p] - 1) >= TH

        def bighigh(p):
            pl = arr[max(0, p - WIN):p].min() if p > 0 else arr[p]
            return (arr[p] / pl - 1) >= TH and (arr[p] / arr[p:min(N, p + WIN)].min() - 1) >= TH

        BL = [p for p in lows0 if biglow(p)]
        SL = [p for p in lows0 if not biglow(p)]
        BH = [p for p in highs0 if bighigh(p)]
        SH = [p for p in highs0 if not bighigh(p)]
        turning = {}
        for nm, pts in (("big_low", BL), ("small_low", SL), ("big_high", BH), ("small_high", SH)):
            turning[nm] = {"n": len(pts), "forward": _fwd_dist(arr, pts, N), "investors": _inv_sig(fg, pts, N)}

        allp = sorted(np.concatenate([lows0, highs0]))
        bigp = sorted(BL + BH)
        interval = {"all": round(float(np.mean(np.diff(allp)))) if len(allp) > 1 else None,
                    "big": round(float(np.mean(np.diff(bigp)))) if len(bigp) > 1 else None}

        # 다중조건 정밀도(예측력 검증) — 저점: 낙폭+연기금(3.4배 최적). 고점: 예측불가(진단용).
        multi = _multi_cond(arr, fg, BL, BH, N)
        down_mkt = _down_market(arr, fg, N)   # 하락장 항복=바닥 진단
        style = _style_by_phase(arr, fg, ix.index, N, pbm) if pbm else {}

        # 현재 국면: 최근 250일 고점 → 그 이후 저점 → 현재 (낙폭·반등)
        seg = arr[-250:] if N >= 250 else arr
        pi = int(np.argmax(seg))
        low_after = seg[pi:].min()
        peak, cur = seg[pi], arr[-1]
        f60 = float(fg["외국인"].tail(60).sum())
        p60 = float(fg["연기금"].tail(60).sum())
        dd = float(low_after / peak - 1) * 100
        current = {"peak": round(float(peak)), "low": round(float(low_after)), "cur": round(float(cur)),
                   "drawdown": round(dd, 1), "rebound": round(float(cur / low_after - 1) * 100, 1),
                   "foreign_60": round(f60), "pension_60": round(p60),
                   "indiv_60": round(float(fg["개인"].tail(60).sum()))}
        # 2단계 신호: 1차=낙폭존(예측·재현율100·정밀도59), 2차=연기금 매수(확인·정밀도68·재현율79 최적)
        low = multi["low_predictive"]
        m_conf = low.get("낙폭+연기금") or {}
        m_zone = low.get("낙폭존") or {}
        ret60_now = float(arr[-1] / arr[-61] - 1) * 100 if N > 60 else 0.0
        current["ret60"] = round(ret60_now, 1)
        current["in_downmarket"] = ret60_now < -10
        # 하락장 항복 여부: 스마트머니(외국인+투신) 최근 20일 순매도 중인가
        fx20 = float(fg["외국인"].tail(20).sum())
        capit = ret60_now < -10 and fx20 < 0
        s1 = dd <= -TH * 100                       # 1차 낙폭존
        s2 = p60 > 0                               # 2차 확인(연기금 매수)
        if s1 and s2:
            current["signal"] = (f"저점 확인(낙폭+연기금 매수) — 과거 정밀도 {m_conf.get('precision','?')}%"
                                 f"·재현율 {m_conf.get('recall','?')}%")
        elif s1 and capit:
            current["signal"] = (f"큰 저점존+하락장 항복(낙폭 {dd:.0f}%·외국인 투매 중) — 바닥 근접, "
                                 f"연기금 매수전환 확인 대기(확인 시 {m_conf.get('precision','?')}%)")
        elif s1:
            current["signal"] = (f"큰 저점존 진입(낙폭 {dd:.0f}%) — 저점가능성 {m_zone.get('precision','?')}%, "
                                 f"연기금 매수전환 대기(확인 시 {m_conf.get('precision','?')}%)")
        else:
            current["signal"] = "정상 구간(낙폭 -12% 미만)"
        # 현재 국면 스타일 경보 (확장=외국인 이탈+개인 추격 = 강세장 후반)
        if cur_phase == "확장" and style.get("확장"):
            sx = style["확장"]
            fxm = (sx.get("외국인") or {}).get("mom")
            pim = (sx.get("개인") or {}).get("mom")
            if fxm is not None and fxm < 0 and pim is not None and pim > 0:
                current["phase_alert"] = (f"확장국면 — 외국인 역추세({fxm:+.2f}, 차익)·개인 추격({pim:+.2f}, FOMO) "
                                          "= 강세장 후반 신호")
        out["markets"][mkt] = {"turning": turning, "interval": interval, "multi_cond": multi,
                               "down_market": down_mkt, "style_by_phase": style, "current": current}

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
        bl = d["turning"]["big_low"]
        f = bl["forward"].get("12개월", {})
        print(f"\n[{mkt}] 큰저점 n={bl['n']} · 12개월 중앙값 {f.get('median')}%"
              f"(q25 {f.get('q25')}~q75 {f.get('q75')}) 평균 {f.get('mean')}%")
        print("  [저점] 다중조건 정밀도(리프트≥2=예측유효):")
        for k, v in d["multi_cond"]["low_predictive"].items():
            if v:
                tag = "✅" if v["lift"] >= 2 else ""
                print(f"    {k:14}: 정밀도 {v['precision']}% 재현율 {v['recall']}% 리프트 {v['lift']}배 {tag}")
        hz = d["multi_cond"]["high_diagnostic_only"].get("상승존") or {}
        print(f"  [고점] 예측 불가 — 상승존조차 리프트 {hz.get('lift','?')}배(<2). 진단용만.")
        dm = d.get("down_market") or {}
        if dm.get("corr"):
            cc = dm["corr"]
            print(f"  [하락장] {dm['n_days']}일·이후평균 {dm['fwd_mean']}% — 항복=바닥 상관: "
                  f"외국인 {cc.get('외국인')} · 개인 {cc.get('개인')} (음수=투매일수록 반등↑)")
        print(f"  현재: {d['current']['signal']}")
