#!/usr/bin/env python3
"""focus 종목(주도주체 순매수 + 피난처)에 대해 LLM Talking Points 도시에 일괄 생성/캐시.
daily_update.sh 가 KRX 갱신 후 호출. (LLM 호출은 일 1회 배치만)"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / "app" / "core" / "engine"))
import scenario_engine as se  # noqa: E402
import dossier  # noqa: E402


def main():
    link = se.flow_research_link(days=45)
    if "error" in link:
        print("KRX 캐시 없음:", link["error"]); return
    seen, n = set(), 0
    for f in link.get("focus", []):
        tk = f["ticker"]
        if tk in seen:
            continue
        seen.add(tk)
        d = dossier.build(tk, f.get("name", ""))
        err = f" [LLM오류:{d['llm_error']}]" if d.get("llm_error") else ""
        print(f"  {d['name']}({tk}) 당사{len(d['house'])}/타사{d['n_others']}{err}")
        n += 1
    print(f"[OK] 도시에 {n}종목 생성/캐시 (주도주체 {link['regime']})")


if __name__ == "__main__":
    main()
