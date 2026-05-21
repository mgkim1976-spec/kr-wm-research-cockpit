"""
KR 멀티-브로커 리서치 어댑터 — 네이버 금융 종목분석 리포트 직접 크롤.

종목코드별로 당사(미래에셋) + 타사(신한·하나·키움·교보 등) 리포트를 한 번에 수집.
출처: https://finance.naver.com/research/company_list.naver?searchType=itemCode&itemCode={code}
(self-contained — 외부 프로젝트 의존성 없음. 인코딩 EUC-KR.)
"""
from __future__ import annotations

import re
import time
from datetime import datetime

import requests
from bs4 import BeautifulSoup

BASE = "https://finance.naver.com/research/company_list.naver"
_HDR = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15) AppleWebKit/537.36"}
_DATE_RE = re.compile(r"^\d{2}\.\d{2}\.\d{2}$")
_THROTTLE = 0.25


def fetch_content(read_url: str) -> dict:
    """리포트 상세 페이지 본문 — 목표가/투자의견 + 요약 본문(제목이 아닌 '내용')."""
    if not read_url:
        return {}
    try:
        time.sleep(_THROTTLE)
        r = requests.get(read_url, headers=_HDR, timeout=15)
        r.encoding = r.apparent_encoding or "euc-kr"
        el = BeautifulSoup(r.text, "html.parser").select_one("div.box_type_m")
        if not el:
            return {}
        txt = el.get_text(" ", strip=True)
        tgt = re.search(r"목표가\s*([\d,]+)", txt)
        opn = re.search(r"투자의견\s*([가-힣A-Za-z\.]+)", txt)
        m = re.search(r"투자의견\s*[가-힣A-Za-z\.]+\s*(.+)$", txt)   # 의견 뒤 = 본문 요약
        body = (m.group(1) if m else txt).strip()
        return {"target": tgt.group(1) if tgt else "", "opinion": opn.group(1) if opn else "",
                "body": body[:600]}
    except Exception:
        return {}


def _norm_date(s: str) -> str | None:
    s = s.strip()
    if not _DATE_RE.match(s):
        return None
    yy, mm, dd = s.split(".")
    return f"20{yy}-{mm}-{dd}"


def reports_for_ticker(code: str, days: int = 150, limit: int = 12) -> list[dict]:
    """네이버 금융에서 해당 종목의 최근 리서치(증권사별) 수집."""
    try:
        r = requests.get(BASE, params={"searchType": "itemCode", "itemCode": code},
                         headers=_HDR, timeout=15)
        r.encoding = r.apparent_encoding or "euc-kr"
    except Exception:
        return []
    soup = BeautifulSoup(r.text, "html.parser")
    today = datetime.today().date()
    out = []
    for tr in soup.find_all("tr"):
        tds = tr.find_all("td")
        if len(tds) < 5:
            continue
        txt = [td.get_text(strip=True) for td in tds]
        date = _norm_date(txt[4]) if len(txt) > 4 else None
        if not date:
            continue
        name, title, broker = txt[0], txt[1], txt[2]
        if not title or not broker:
            continue
        try:
            if (today - datetime.strptime(date, "%Y-%m-%d").date()).days > days:
                continue
        except Exception:
            continue
        # 링크(읽기/PDF)
        read_url = pdf_url = ""
        a_title = tds[1].find("a")
        if a_title and a_title.get("href"):
            href = a_title["href"]
            read_url = href if href.startswith("http") else "https://finance.naver.com/research/" + href.lstrip("/")
        a_pdf = tds[3].find("a") if len(tds) > 3 else None
        if a_pdf and a_pdf.get("href"):
            pdf_url = a_pdf["href"]
        out.append({"name": name, "title": title, "broker": broker, "date": date,
                    "read_url": read_url, "pdf_url": pdf_url})
    out.sort(key=lambda x: x["date"], reverse=True)
    return out[:limit]


def _is_house(broker: str) -> bool:
    return "미래에셋" in broker


def gather(ticker: str, name: str = "", with_content: bool = True) -> dict:
    """종목별 당사/타사 분리 + 상세 본문(with_content) 크롤."""
    reps = reports_for_ticker(ticker)
    house = [r for r in reps if _is_house(r["broker"])][:3]
    others, seen = [], set()
    for r in reps:
        if _is_house(r["broker"]) or r["broker"] in seen:
            continue
        seen.add(r["broker"])
        others.append(r)
    others = others[:6]
    if with_content:
        for r in house + others:
            r["content"] = fetch_content(r.get("read_url", ""))
    return {"ticker": ticker, "name": name or (reps[0]["name"] if reps else ticker),
            "house": house, "others": others,
            "has_house": len(house) > 0, "n_others": len(others)}


if __name__ == "__main__":
    import sys
    tk = sys.argv[1] if len(sys.argv) > 1 else "005930"
    g = gather(tk)
    print(f"=== {tk} {g['name']} === 당사 {len(g['house'])} / 타사 {g['n_others']}")
    for r in g["house"]:
        print(f"  [당사] {r['date']} {r['broker']} | {r['title']}")
    for r in g["others"]:
        print(f"  [{r['broker']}] {r['date']} | {r['title']}")
