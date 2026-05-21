"""
종목 Talking Points 도시에 — 당사(미래에셋)+타사 네이버 리서치 → OpenAI 요약.

산출(개인 자산관리 상담용):
  - opportunity : 기회 요인 (1~2줄)
  - risk        : 리스크 요인 (1~2줄)
  - gap         : 당사(미래에셋) vs 타사 의견 GAP (1~2줄). 당사 없으면 '당사 커버리지 없음'.

배치(build_dossiers.py)가 focus 종목에 대해 생성 → data/dossiers.json 캐시.
대시보드는 캐시만 읽음(LLM 호출은 일 1회 배치). 키 없음/오프라인 시 graceful degrade.
"""
from __future__ import annotations

import json
import os
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
CACHE_PATH = ROOT / "data" / "dossiers.json"
MODEL = os.environ.get("DOSSIER_MODEL", "gpt-4o-mini")

import sys
sys.path.insert(0, str(ROOT / "app" / "core" / "adapters"))
import kr_research  # noqa: E402


def _load_key() -> str | None:
    if os.environ.get("OPENAI_API_KEY"):
        return os.environ["OPENAI_API_KEY"]
    env = ROOT / ".env"
    if env.exists():
        for line in env.read_text(encoding="utf-8").splitlines():
            if line.strip().startswith("OPENAI_API_KEY="):
                k = line.split("=", 1)[1].strip()
                os.environ["OPENAI_API_KEY"] = k
                return k
    return None


def _load_cache() -> dict:
    try:
        return json.loads(CACHE_PATH.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _save_cache(c: dict) -> None:
    CACHE_PATH.write_text(json.dumps(c, ensure_ascii=False, indent=2), encoding="utf-8")


def get_cached(ticker: str) -> dict | None:
    return _load_cache().get(ticker)


def _llm_summarize(name: str, ticker: str, house: list, others: list) -> dict:
    key = _load_key()
    if not key:
        return {"error": "OPENAI_API_KEY 없음"}
    from openai import OpenAI
    client = OpenAI(api_key=key)

    def _fmt(r):
        c = r.get("content") or {}
        tag = f" [목표가 {c['target']}/{c.get('opinion','')}]" if c.get("target") else ""
        body = c.get("body", "")
        return f"- {r['date']} {r['broker']}{tag}: {r['title']}\n  내용: {body}" if body else f"- {r['date']} {r['broker']}{tag}: {r['title']}"

    h = "\n".join(_fmt(r) for r in house) or "(당사 리포트 없음)"
    o = "\n".join(_fmt(r) for r in others) or "(타사 리포트 없음)"
    prompt = (
        f"종목: {name}({ticker})\n\n[당사(미래에셋증권) 리포트 — 목표가/의견/본문]\n{h}\n\n"
        f"[타사 리포트 — 목표가/의견/본문]\n{o}\n\n"
        "위 리포트의 **본문 내용**(목표가·투자의견·요약)을 근거로 개인투자자 상담용 요약을 작성하라.\n"
        "■ 절대 규칙(구체성):\n"
        "  - 모호어 금지: '외부 요인', '대외 불확실성', '시장 변동성', '신중한 접근', '낙관 vs 신중', '경쟁 심화' 같은 표현을 "
        "그 자체로 쓰지 말 것. 반드시 **무엇인지 구체적으로** 적시(예: 미국 관세율 인상, 원/달러 환율, 메모리 공급병목, "
        "NAND 가격, MS사업부 적자, 중동 종전, 천궁-II 납품, 특정 사업부/제품/수치).\n"
        "  - 견해차는 **증권사명 + 구체 근거(목표가 숫자·강조 포인트)**로. 단순 '낙관/신중 갈림'은 금지.\n"
        "  - 본문에 구체 근거가 없으면 지어내지 말고 gap은 \"대체로 의견 일치\"로 짧게.\n"
        "  - 카탈리스트: 본문에 **구체적 향후 이벤트**(실적발표·신규수주·신제품·계약·정책·학회 등, 가능하면 시점)가 "
        "있을 때만 적되, **없으면 반드시 빈 문자열(\"\")**. '예정된 일정 없음' 같은 문구나 억지 생성 금지.\n"
        "  - 각 항목 1~2문장, 본문에 없는 사실 창작 금지.\n"
        'JSON으로만: {'
        '"opportunity":"기회 요인(구체 수치·사건)",'
        '"risk":"리스크 요인(무엇이 위험인지 구체적으로)",'
        '"gap":"당사(미래에셋) vs 타사 의견 차이 — 증권사명+목표가 숫자+강조점으로 구체적으로. '
        '당사 리포트 없으면 \'당사 커버리지 없음 — 타사 목표가 범위 X~Y\'. 차이가 없으면 \'대체로 의견 일치\'",'
        '"catalysts":"본문에 구체적 향후 이벤트가 있으면 시점과 함께. 없으면 빈 문자열"}'
    )
    try:
        resp = client.chat.completions.create(
            model=MODEL, temperature=0.2, response_format={"type": "json_object"},
            messages=[{"role": "system", "content": "너는 한국 주식 리서치를 요약하는 신중한 애널리스트다. 과장·창작 금지. "
                       "제공된 본문 내용·목표가·투자의견만 근거로 하고, **항상 구체적**으로 쓴다. "
                       "모호한 채움말('외부 요인','불확실성','신중한 접근','낙관 vs 신중')은 금지 — 근거가 없으면 '특이 견해차 없음'으로 비운다."},
                      {"role": "user", "content": prompt}])
        return json.loads(resp.choices[0].message.content)
    except Exception as e:
        return {"error": str(e)[:160]}


def build(ticker: str, name: str = "", force: bool = False) -> dict:
    """종목 도시에 생성(+캐시). 같은 날 캐시 있으면 재사용."""
    cache = _load_cache()
    today = date.today().isoformat()
    if not force and ticker in cache and cache[ticker].get("date") == today:
        return cache[ticker]
    g = kr_research.gather(ticker, name)
    if not g["house"] and not g["others"]:   # 리서치 0건 → LLM 호출/창작 금지
        summ = {"opportunity": "리서치 자료 없음", "risk": "", "gap": "리서치 자료 없음", "catalysts": ""}
    else:
        summ = _llm_summarize(g["name"], ticker, g["house"], g["others"])
    rec = {"ticker": ticker, "name": g["name"], "date": today,
           "has_house": g["has_house"], "n_others": g["n_others"],
           "house": g["house"], "others": g["others"],
           "opportunity": summ.get("opportunity", ""), "risk": summ.get("risk", ""),
           "gap": summ.get("gap", ""), "catalysts": summ.get("catalysts", ""),
           "llm_error": summ.get("error", "")}
    cache[ticker] = rec
    _save_cache(cache)
    return rec


if __name__ == "__main__":
    import sys
    tk = sys.argv[1] if len(sys.argv) > 1 else "005930"
    nm = sys.argv[2] if len(sys.argv) > 2 else ""
    d = build(tk, nm, force=True)
    print(f"=== {d['name']}({tk}) 당사 {len(d['house'])}/타사 {d['n_others']} ===")
    if d.get("llm_error"):
        print("LLM 오류:", d["llm_error"])
    print("🟢 기회:", d["opportunity"])
    print("🔴 리스크:", d["risk"])
    print("⚖️ 당사 vs 타사 견해차:", d["gap"])
    print("📅 카탈리스트:", d.get("catalysts") or "(없음)")
