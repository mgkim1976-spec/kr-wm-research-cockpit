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
        "위 리포트의 **본문 내용**(제목이 아니라 목표가·투자의견·요약)을 근거로 개인투자자 자산관리 상담용 요약을 작성하라. "
        "각 항목 1~2문장, 간결하게. 본문에 없는 사실을 지어내지 말 것. "
        'JSON으로만: {'
        '"opportunity":"기회(성과) 요인 종합",'
        '"risk":"리스크 요인 종합",'
        '"gap_opportunity":"기회/성과 요인에 대해 증권사 간 견해가 갈리는 지점 — 누가 무엇을 더/덜 강조하는지, 목표가 차이 포함",'
        '"gap_risk":"리스크 요인에 대해 증권사 간 견해가 갈리는 지점 — 신중 vs 낙관이 갈리는 곳",'
        '"catalysts":"향후 카탈리스트·이벤트(실적발표·신규수주·제품출시·정책 등), 가능하면 시점. 본문에 없으면 \'명시적 카탈리스트 언급 없음\'"}'
        " (당사 리포트 없으면 gap_* 는 \'당사 커버리지 없음 — 타사 견해만\'으로)"
    )
    try:
        resp = client.chat.completions.create(
            model=MODEL, temperature=0.3, response_format={"type": "json_object"},
            messages=[{"role": "system", "content": "너는 한국 주식 리서치를 요약하는 신중한 애널리스트다. 과장·창작 금지. 제목이 아니라 제공된 본문 내용·목표가·투자의견을 근거로만 작성."},
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
    summ = _llm_summarize(g["name"], ticker, g["house"], g["others"])
    rec = {"ticker": ticker, "name": g["name"], "date": today,
           "has_house": g["has_house"], "n_others": g["n_others"],
           "house": g["house"], "others": g["others"],
           "opportunity": summ.get("opportunity", ""), "risk": summ.get("risk", ""),
           "gap_opportunity": summ.get("gap_opportunity", ""), "gap_risk": summ.get("gap_risk", ""),
           "catalysts": summ.get("catalysts", ""), "llm_error": summ.get("error", "")}
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
    print("⚖️ 기회요인 견해차:", d["gap_opportunity"])
    print("⚖️ 리스크요인 견해차:", d["gap_risk"])
    print("📅 카탈리스트:", d["catalysts"])
