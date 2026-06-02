"""
시나리오 엔진 — 리서치 분류 + 시황 감지 + 수급↔리서치 브리지 + 고객 우선순위.

- 리서치 제목 → 카테고리(시황/매크로/섹터테마/개별종목) + 13 시황 시나리오 + 위험등급 분류
- detect_current_scenarios : 최근 시황·매크로 리포트에서 오늘의 시황 감지(💬 상담 메시지)
- flow_research_link       : 주도주체 순매수 + 외인/기관 매집 → 당사/타사 리서치·도시에 + 커버리지 GAP
- contact_priority         : 시황 기반 고객 세그먼트 우선순위 + 쏠림 경보

방법론: docs/MARKET_SCENARIO_ADVISORY_MANUAL.md (13 시장 시나리오).
self-contained — 외부 프로젝트 의존성 없음.
"""
from __future__ import annotations

import json
import re
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]   # research_based_sales/
DATA_DIR = ROOT / "data"
DB_PATH = DATA_DIR / "research_db.json"
TAXONOMY_PATH = DATA_DIR / "scenario_taxonomy.json"

# 제목 괄호: "(005930/매수)", "(9880 HK/Not Rated)", "(비중확대)", "(034730)"
_PAREN_RE = re.compile(r"\(([^)]*)\)")
_CODE_RE = re.compile(r"([0-9]{3,6})\s*(HK|US|JP)?")
_BARE_CODE_RE = re.compile(r"^[0-9]{3,6}(\s*(HK|US|JP|CH))?$")


# ── 로드 ──────────────────────────────────────────────────────────────────────

def load_taxonomy(path: Path = TAXONOMY_PATH) -> dict:
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def load_reports(path: Path = DB_PATH) -> list[dict]:
    """research_db.json 로드 + report_id/(title,date) 기준 중복 제거."""
    with open(path, encoding="utf-8") as f:
        raw = json.load(f)
    seen_id, seen_td, out = set(), set(), []
    for r in raw:
        rid = r.get("report_id")
        td = (r.get("title", "").strip(), (r.get("date") or "")[:10])
        if rid in seen_id or td in seen_td:
            continue
        seen_id.add(rid)
        seen_td.add(td)
        out.append(r)
    return out


# ── 분류 ──────────────────────────────────────────────────────────────────────

def _detect_category(title: str, tax: dict) -> tuple[str, str | None, str | None, str | None]:
    """returns (category_key, stock_code, opinion, name)."""
    cats = tax["categories"]
    name = title.split("(")[0].strip()
    stock_code = opinion = None

    # 괄호 내용 분석
    parens = _PAREN_RE.findall(title)
    for p in parens:
        if "/" in p:
            left, right = [x.strip() for x in p.split("/", 1)]
            cm = _CODE_RE.search(left)
            # 의견 추출
            for op in tax["opinion_keywords"]:
                if op.lower() in right.lower():
                    opinion = op
                    break
            if cm and cm.group(1) and not left.replace(" ", "").isalpha():
                stock_code = cm.group(1)
        else:
            for op in tax["opinion_keywords"]:
                if op.lower() in p.lower():
                    opinion = op
                    break
            # 코드만 있는 괄호: "(034730)", "(3659 JP)"
            if _BARE_CODE_RE.match(p.strip()):
                stock_code = _CODE_RE.search(p).group(1)

    # 개별종목: 종목코드 + 의견(또는 코드)이 괄호에 있으면
    if stock_code:
        return "single_stock", stock_code, opinion, name

    low = title.lower()
    # 섹터·테마 / 매크로 / 시황 순으로 키워드 매칭
    for cat_key in ("sector_theme", "macro_strategy", "market_view"):
        for kw in cats[cat_key]["keywords"]:
            if kw.lower() in low:
                return cat_key, None, opinion, name
    return "etc", None, opinion, name


def _detect_scenarios(title: str, tax: dict) -> dict[str, str]:
    """제목에서 매칭된 시나리오 → {scenario_key: 매칭 키워드}."""
    low = title.lower()
    hits: dict[str, str] = {}
    for skey, sval in tax["scenarios"].items():
        for kw in sval["keywords"]:
            if kw.lower() in low:
                hits[skey] = kw
                break
    return hits


def _detect_risk_tier(title: str, category: str, tax: dict) -> str:
    """리포트 대상의 위험등급: 정보/저위험/중위험/고위험/초고위험."""
    rc = tax.get("risk_classification")
    if not rc:
        return "정보"
    low = title.lower()
    if any(k.lower() in low for k in rc["very_high_keywords"]):
        return "초고위험"
    has_low = any(k.lower() in low for k in rc["low_keywords"])
    if category == "single_stock":
        return "저위험" if has_low else "고위험"
    if category == "sector_theme":
        return "저위험" if has_low else "중위험"
    return rc["category_default_tier"].get(category, "정보")


def profile_level(name: str, tax: dict) -> int:
    """투자성향 → 레벨(안정형1 ~ 공격투자형5). 미상=0."""
    order = tax["risk_classification"]["profiles_order"]
    return order.index(name) + 1 if name in order else 0


def classify_report(report: dict, tax: dict) -> dict:
    title = report.get("title", "")
    cat, code, opinion, name = _detect_category(title, tax)
    scenarios = _detect_scenarios(title, tax)
    date = (report.get("date") or "")[:10]
    tier = _detect_risk_tier(title, cat, tax)
    rc = tax.get("risk_classification", {})
    min_profile = rc.get("tier_to_min_profile", {}).get(tier, "안정형")
    return {
        "risk_tier": tier,
        "min_profile": min_profile,
        "min_profile_level": profile_level(min_profile, tax) if rc else 1,
        "report_id": report.get("report_id"),
        "title": title,
        "name": name,
        "date": date,
        "author": report.get("author", ""),
        "source_url": report.get("source_url", ""),
        "attachment_urls": report.get("attachment_urls", []),
        "category": cat,
        "category_label": tax["categories"].get(cat, {}).get("label", "기타"),
        "stock_code": code,
        "opinion": opinion,
        "scenarios": list(scenarios.keys()),
        "scenario_hits": scenarios,
    }


def enrich_all(reports: list[dict], tax: dict) -> list[dict]:
    return [classify_report(r, tax) for r in reports]


# ── 시황 자동 감지 ────────────────────────────────────────────────────────────

def anchor_date(enriched: list[dict]) -> str:
    dates = [e["date"] for e in enriched if e["date"]]
    return max(dates) if dates else datetime.today().strftime("%Y-%m-%d")


def _days_between(d1: str, d2: str) -> int:
    try:
        return abs((datetime.strptime(d1, "%Y-%m-%d") - datetime.strptime(d2, "%Y-%m-%d")).days)
    except Exception:
        return 999


def detect_current_scenarios(enriched: list[dict], tax: dict, days: int = 7) -> list[dict]:
    """최근 days일 시황·매크로 리포트에서 시나리오 빈도 집계 → 오늘의 시황."""
    anchor = anchor_date(enriched)
    score: dict[str, float] = {}
    for e in enriched:
        if e["category"] not in ("market_view", "macro_strategy"):
            continue
        gap = _days_between(e["date"], anchor)
        if gap > days:
            continue
        w = 1.0 if gap <= 2 else (0.6 if gap <= 4 else 0.3)
        for s in e["scenarios"]:
            score[s] = score.get(s, 0.0) + w
    ranked = sorted(score.items(), key=lambda x: x[1], reverse=True)
    out = []
    for skey, sc in ranked[:5]:
        sv = tax["scenarios"][skey]
        out.append({"key": skey, "label": sv["label"], "emoji": sv["emoji"],
                    "group": sv["group"], "score": round(sc, 1),
                    "advisory_hook": sv["advisory_hook"]})
    return out


# ── 엔진 캐시 (mtime 자동 갱신) ────────────────────────────────────────────────

_CACHE: dict = {}
_DB_MTIME = None


def _ensure_loaded() -> None:
    """research_db.json 변경(mtime) 감지 시 자동 재로딩 — 일일 크롤 후 서버 재시작 불필요."""
    global _DB_MTIME
    try:
        mtime = DB_PATH.stat().st_mtime
    except OSError:
        mtime = None
    if "enriched" not in _CACHE or mtime != _DB_MTIME:
        tax = load_taxonomy()
        reports = load_reports()
        _CACHE["tax"] = tax
        _CACHE["enriched"] = enrich_all(reports, tax)
        _DB_MTIME = mtime


def get_state() -> dict:
    """엔진 로드(변경 시 자동 갱신) → 오늘의 시황 시나리오(💬 상담 메시지용) + 기준일·리서치 수."""
    _ensure_loaded()
    tax, enriched = _CACHE["tax"], _CACHE["enriched"]
    return {"anchor_date": anchor_date(enriched), "report_count": len(enriched),
            "detected": detect_current_scenarios(enriched, tax, 7)}


# ── 페르소나 × 시황 큐레이션 ───────────────────────────────────────────────────

# ── 수급 ↔ 리서치 브리지 + 커버리지 GAP (WM 하단) ──────────────────────────────

KRX_CACHE_PATH = DATA_DIR / "krx_market.json"


def load_krx() -> dict:
    try:
        return json.loads(KRX_CACHE_PATH.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _reports_for(enriched: list[dict], ticker: str, name: str, anchor: str, days: int) -> list[dict]:
    """종목코드 일치(우선) 또는 종목명이 제목에 포함 + 최근 days일 리서치."""
    out = []
    for e in enriched:
        if _days_between(e["date"], anchor) > days:
            continue
        if (ticker and e.get("stock_code") == ticker) or (name and len(name) >= 2 and name in e.get("title", "")):
            out.append(e)
    return sorted(out, key=lambda x: x["date"], reverse=True)


def crowding_alert(krx: dict, win: str = "5") -> list[dict]:
    """개인 고객 쏠림·과열 경보: 개인 순매수 상위인데 외국인·기관이 받쳐주지 않는(동반 순매도) 종목.
    = 고객이 몰렸으나 매수 주체 부재 → 과열·조정 위험. (외인 매도 자체가 아니라 '고객 쏠림'이 기준)
    액션은 전량매도가 아니라 비중 점검·차익실현·분산."""
    tops = krx.get("tops", {}).get(win, {})
    indiv_buy = {x["ticker"]: x for x in tops.get("개인", {}).get("top_buy", []) if x.get("net_value", 0) > 0}
    f_sell = {x["ticker"] for x in tops.get("외국인", {}).get("top_sell", []) if x.get("net_value", 0) < 0}
    i_sell = {x["ticker"] for x in tops.get("기관", {}).get("top_sell", []) if x.get("net_value", 0) < 0}
    out = []
    for tk, x in indiv_buy.items():
        who = [w for w, s in (("외국인", f_sell), ("기관", i_sell)) if tk in s]
        if who:
            out.append({"ticker": tk, "name": x["name"],
                        "reason": f"개인 순매수 상위인데 {'·'.join(who)} 순매도 — 매수주체 부재(과열·쏠림)"})
    return out


def compute_havens(krx: dict, win: str = "5") -> list[dict]:
    """외인·기관 매집 종목: 개인은 순매도하나 외국인·기관이 사 모으는 종목 — 개인주도 국면의 분산 대안."""
    tops = krx.get("tops", {}).get(win, {})
    indiv_sell = {x["ticker"]: x for x in tops.get("개인", {}).get("top_sell", [])}
    f_buy = {x["ticker"] for x in tops.get("외국인", {}).get("top_buy", []) if x.get("net_value", 0) > 0}
    i_buy = {x["ticker"] for x in tops.get("기관", {}).get("top_buy", []) if x.get("net_value", 0) > 0}
    havens = []
    for tk, x in indiv_sell.items():
        who = [w for w, s in (("외국인", f_buy), ("기관", i_buy)) if tk in s]
        if who:
            havens.append({"ticker": tk, "name": x["name"],
                           "reason": f"개인 순매도 + {'·'.join(who)} 순매수(매집)"})
    return havens


def active_actor(krx: dict, win: str = "5") -> dict:
    """시장을 '끄는' 주체 = 방향주도(leader by_corr: 순매수 방향과 지수 방향 일치).
    세 주체 순매수 합은 ~0(사는 쪽↔받아주는 쪽) → 최대순매수(dominant)는 받아주는 쪽일 수 있어
    종목 선별 기준으로 부적합. leader 없으면(지수 미수집 등) dominant 폴백."""
    rg = krx.get("regime", {})
    lw = "20" if str(win) == "20" else "5"
    ld = (rg.get("leader") or {}).get(lw) or {}
    actor = ld.get("by_corr")
    if actor:
        return {"actor": actor, "basis": "leader", "window": lw,
                "corr": (ld.get("corr") or {}).get(actor), "index_ret_pct": ld.get("index_ret_pct"),
                "absorber": ld.get("absorber_corr"), "dominant": rg.get("dominant")}
    return {"actor": rg.get("dominant", "개인"), "basis": "dominant_fallback", "window": lw,
            "corr": None, "index_ret_pct": None, "absorber": None, "dominant": rg.get("dominant")}


def flow_research_link(days: int = 45, win: str = "5") -> dict:
    """방향주도 주체 순매수 상위 + 외인·기관 매집 종목 → 리서치 매칭 + 커버리지 GAP(요청 대상) 도출."""
    _ensure_loaded()
    en = _CACHE["enriched"]
    anchor = anchor_date(en)
    krx = load_krx()
    if not krx or "regime" not in krx:
        return {"error": "KRX 캐시 없음 — daily_update.sh 실행 필요"}
    act = active_actor(krx, win)
    dom = act["actor"]
    tops = krx.get("tops", {}).get(win, {})

    focus = []
    for x in tops.get(dom, {}).get("top_buy", [])[:8]:
        if x.get("net_value", 0) > 0:
            focus.append({"ticker": x["ticker"], "name": x["name"],
                          "reason": f"{dom} 순매수 상위", "tag": "주도"})
    havens = compute_havens(krx, win)
    for h in havens[:6]:
        focus.append({**h, "tag": "외인·기관 매집"})

    STALE_DAYS = 14   # 당사 리포트가 이보다 오래되면 '최신 리포트 없음'
    try:
        import dossier as _dossier
    except Exception:
        _dossier = None

    def _src(r):
        return {"broker": r.get("broker") or r.get("author", ""), "title": r.get("title", ""),
                "date": r.get("date", ""),
                "url": r.get("read_url") or r.get("pdf_url") or r.get("source_url", "")}

    seen, items, gaps = set(), [], []
    for f in focus:
        if f["ticker"] in seen:
            continue
        seen.add(f["ticker"])
        d = _dossier.get_cached(f["ticker"]) if _dossier else None
        if d:   # 당사 판정 = 네이버 미래에셋(도시에) 기준
            hsrc = [_src(r) for r in (d.get("house") or [])]
            osrc = [_src(r) for r in (d.get("others") or [])]
            n_others = d.get("n_others", len(osrc))
            dos = {k: d.get(k, "") for k in ("opportunity", "risk", "gap", "catalysts")}
        else:   # 폴백: research_db(미래에셋 사이트)
            reps = _reports_for(en, f["ticker"], f["name"], anchor, days)
            hsrc = [{"broker": "미래에셋증권", "title": r["title"], "date": r["date"],
                     "url": r.get("source_url", "")} for r in reps[:3]]
            osrc, n_others, dos = [], 0, None
        has_house = len(hsrc) > 0
        house_latest = hsrc[0]["date"] if hsrc else None
        stale = bool(has_house and house_latest and _days_between(house_latest, anchor) > STALE_DAYS)
        items.append({**f, "has_house": has_house, "house_latest": house_latest, "house_stale": stale,
                      "house_src": hsrc, "others_src": osrc, "n_others": n_others, "dossier": dos})
        # 요청 대상: 당사 전무(신규) 또는 오래됨(업데이트)
        if not has_house:
            gaps.append({"ticker": f["ticker"], "name": f["name"], "reason": f["reason"],
                         "tag": f["tag"], "last_report": None, "kind": "신규"})
        elif stale:
            gaps.append({"ticker": f["ticker"], "name": f["name"], "reason": f["reason"],
                         "tag": f["tag"], "last_report": house_latest, "kind": "업데이트"})
    return {"regime": dom, "regime_meta": act, "window": win, "days": days, "anchor": anchor,
            "stale_days": STALE_DAYS, "focus": items, "havens": havens, "gaps": gaps}


def contact_priority(days: int = 45, win: str = "5") -> dict:
    """고객 데이터 없이 WM이 접촉 우선순위를 판단하도록 — 시황 기반 고객 '세그먼트' 우선순위 + 이탈경보 watch-list.
    (실제 고객 명단이 들어오면 각 고객이 세그먼트에 매핑되어 그대로 우선순위가 부여됨)"""
    _ensure_loaded()
    en = _CACHE["enriched"]
    anchor = anchor_date(en)
    krx = load_krx()
    if not krx or "regime" not in krx:
        return {"error": "KRX 캐시 없음 — daily_update.sh 실행 필요"}
    regime = krx["regime"]
    act = active_actor(krx, win)
    dom = act["actor"]
    tops = krx.get("tops", {}).get(win, {})
    REGIME_RISK = {"개인": "고변동(리스크)", "외국인": "보통(인덱스)", "기관": "보통(가치)"}

    # 경보 기준 = '외인이 판다'가 아니라 '우리 고객(개인)이 몰렸는데 매수주체가 없다'(쏠림·과열)
    crowd = crowding_alert(krx, win)[:8]
    watch = crowd
    opp = [{"ticker": x["ticker"], "name": x["name"]} for x in tops.get(dom, {}).get("top_buy", [])[:6] if x.get("net_value", 0) > 0]
    havens = [{"ticker": h["ticker"], "name": h["name"]} for h in compute_havens(krx, win)[:6]]   # 분산 대안(우량 매집)

    def content_for(items):
        cov, req = [], []
        for it in items:
            reps = _reports_for(en, it["ticker"], it["name"], anchor, days)
            if reps:
                cov.append({**it, "date": reps[0]["date"], "title": reps[0]["title"], "source_url": reps[0].get("source_url")})
            else:
                req.append(it)
        return {"covered": cov, "request": req}

    if dom == "개인":
        segs = [
            {"level": "점검", "label": "개인 쏠림·과열 종목 보유 고객", "why": "고객이 몰린 종목 중 외인·기관이 받쳐주지 않는 종목 — 과열·조정 위험(매수주체 부재). ※외인 매도 '추종'이 아니라 본인 쏠림 점검", "action": "비중 점검·일부 차익실현·분산 (전량매도 아님)", "items": crowd},
            {"level": "높음", "label": "공격·테마 트레이더 (공격투자형)", "why": "개인 주도 모멘텀 — 단기 기회와 과열 리스크 공존", "action": "추격 자제·손절 규율·일부 차익실현", "items": opp},
            {"level": "높음", "label": "보수·은퇴/인출기 (안정형·안정추구형)", "why": "개인 주도 고변동 — 투매·변동성 위험", "action": "현금비중·방어 점검 + 분산 대안(우량 매집주) 제시", "items": havens},
            {"level": "보통", "label": "중립·균형 (위험중립형)", "why": "변동성 주의", "action": "비중·리밸런싱 점검", "items": []},
        ]
    elif dom == "외국인":
        segs = [
            {"level": "높음", "label": "성장·코어 추구 고객", "why": "외국인 주도 대형주 인덱스 장세 — 외인 매집 대형주 동참 기회", "action": "수출 대형주 코어 편입", "items": opp},
            {"level": "점검", "label": "개인 집중·외국인 미매수 종목 보유 고객", "why": "개인이 몰렸으나 외국인이 사지 않는 종목 — 개인이 매도 물량을 떠안을 위험", "action": "외국인이 안 사는 개인 집중주 비중 점검·차익실현", "items": crowd},
            {"level": "보통", "label": "보수·안정형", "why": "안정적 인덱스 참여", "action": "대형주/인덱스 비중 점검", "items": []},
        ]
    else:
        segs = [
            {"level": "높음", "label": "인컴·가치 추구 고객", "why": "기관 주도 — 정책·가치/배당 국면", "action": "저평가 가치주·배당 픽 제안", "items": opp},
            {"level": "점검", "label": "성장·테마 쏠림 고객", "why": "가치 로테이션 국면 — 기관이 외면하는 성장·테마 편중 위험", "action": "성장↔가치 리밸런싱·비중 점검", "items": crowd},
            {"level": "보통", "label": "균형형", "why": "섹터 순환매 대응", "action": "로테이션 점검", "items": []},
        ]
    for i, s in enumerate(segs):
        s["rank"] = i + 1
        s["content"] = content_for(s.get("items", []))
        s.pop("items", None)
    return {"regime": {**regime, "active": dom, "active_meta": act},
            "regime_risk": REGIME_RISK.get(dom, ""), "anchor": anchor,
            "watch": watch, "segments": segs}


# ── CLI (검증용) ──────────────────────────────────────────────────────────────

if __name__ == "__main__":
    tax = load_taxonomy()
    enriched = enrich_all(load_reports(), tax)
    print(f"[로드] 중복제거 후 {len(enriched)}건 / 기준일 {anchor_date(enriched)}")
    print("\n[오늘의 시황 자동감지]")
    for d in detect_current_scenarios(enriched, tax, 7):
        print(f"  {d['emoji']} {d['label']} (score {d['score']})")
    b = contact_priority()
    if "error" not in b:
        print(f"\n[고객 우선순위] 시황 {b['regime']['dominant']} 주도 / {b['regime_risk']}")
        for s in b["segments"]:
            print(f"  {s['rank']}순위[{s['level']}] {s['label']} → {s['action']}")
