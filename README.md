# KR WM Research Cockpit

한국 주식시장 **Wealth Manager / PB를 위한 의사결정 지원 대시보드**.
시장 수급(누가 사고파나)부터 시작해 **필요한 리서치 → 우선 접촉할 고객**까지 한 화면으로 잇는다.

> ⚠️ 투자 조언이 아닌 **리서치 큐레이션·영업 의사결정 보조 도구**입니다. 매매 판단·적합성(suitability)은 사용자 책임입니다.

---

## 무엇을 하나 — 3단 깔때기 + 상담 메시지

```
① 시황            KRX 투자자별 수급으로 '시장 주도주체(개인/외국인/기관)' 자동 판별
                  · 개인 누적 순매수(현금화↔매수) · 거래대금/비중 추이 · 자금 회전 Sankey
                  · 주체별 거래대금/순매수/순매도 상위 (1·5·20영업일 토글)
   ↓
② 필요 컨텐츠      주도주체 순매수 + 외인/기관 매집 종목 → 당사+타사 리서치 자동 연결
                  · LLM(OpenAI) 종목별 Talking Points: 🟢기회 / 🔴리스크 /
                    ⚖️기회·리스크 견해차(당사 vs 타사 본문 기준) / 📅카탈리스트
                  · 당사 리서치 없음/오래됨 → 📮 리서치센터 요청서 자동 생성
   ↓
③ 고객 관리 우선순위  시황 기반 고객 '세그먼트' 우선순위 + 🟠개인 쏠림·과열 경보
   ↓
💬 상담 메시지      오늘 시황 주요 이슈별 상담 톤(방법론 매뉴얼 기반)
```

데이터 출처: **KRX 투자자별 수급(pykrx)** · **네이버 금융 리서치**(당사=미래에셋 + 타사) · **OpenAI**(요약).
방법론(13 시장 시나리오): [`docs/MARKET_SCENARIO_ADVISORY_MANUAL.md`](docs/MARKET_SCENARIO_ADVISORY_MANUAL.md).

---

## 빠른 시작

```bash
# 1. 의존성
pip install -r requirements.txt

# 2. 자격정보 (.env)
cp .env.example .env          # KRX_ID/KRX_PW (data.krx.co.kr), OPENAI_API_KEY 채우기

# 3. 데이터 수집 (최초 1회 / 이후 매일)
python3 download_reports.py                       # 당사(미래에셋) 리서치 메타
python3 app/core/adapters/krx_market.py --years 2 # KRX 수급 → data/krx_market.json
python3 build_dossiers.py                          # 종목 Talking Points(LLM) → data/dossiers.json
#   또는 한 번에:  bash daily_update.sh

# 4. 대시보드 실행
python3 app/app.py            # → http://localhost:8768
```

> 데이터 파일(`data/*.json`, `research_reports/`)은 크롤로 생성되며 저장소에 포함되지 않습니다(.gitignore). 위 3단계를 먼저 실행하세요.

---

## 매일 자동화 (선택, macOS launchd)

`daily_update.sh`(크롤+수급+도시에) 를 매일 아침 실행하고 서버를 상시 가동:

```bash
chmod +x daily_update.sh
cp deploy/*.plist ~/Library/LaunchAgents/
launchctl load ~/Library/LaunchAgents/com.pbcopilot.dailyupdate.plist   # 매일 07:30
launchctl load ~/Library/LaunchAgents/com.pbcopilot.server.plist        # 상시 서버
```
서버는 `data/*.json` 변경을 감지해 자동 반영(재시작 불필요). 자세한 내용은 [`deploy/README.md`](deploy/README.md).

---

## 구조

```
app/
  app.py                       Flask (포트 8768) — /api/state /api/krx /api/flow_link /api/brief
  templates/index.html         대시보드 (Tailwind + Chart.js + Sankey)
  core/
    engine/
      scenario_engine.py       시황 감지 · 수급↔리서치 브리지 · 고객 우선순위
      dossier.py               OpenAI Talking Points (당사+타사 본문 기반)
    adapters/
      krx_market.py            KRX 투자자별 수급 (pykrx, rate-limit safe)
      kr_research.py           네이버 금융 리서치 크롤 (당사+타사, 본문 포함)
      research_crawler.py      미래에셋 리서치 메타 크롤
  models/resources.py          데이터 모델
data/scenario_taxonomy.json    13 시나리오 키워드 사전 (유일하게 커밋되는 데이터)
docs/MARKET_SCENARIO_ADVISORY_MANUAL.md   방법론(13 시장 시나리오)
download_reports.py / download_3months.py / build_dossiers.py / daily_update.sh
deploy/                        launchd 배포
```

---

## 주의 / 면책

- 본 도구는 **정보 제공·영업 의사결정 보조**용이며 투자 권유가 아닙니다.
- KRX·네이버·증권사 리서치는 각 제공자의 이용약관을 따릅니다. 수집 데이터는 **개인 학습/연구 범위** 내에서 사용하세요(저작권 자료 재배포 금지 — 그래서 데이터/PDF는 저장소에 포함하지 않습니다).
- LLM 요약은 리포트 제목·요약 본문 근거이며 오류가 있을 수 있습니다. 원문 링크로 확인하세요.

## 라이선스
MIT — [LICENSE](LICENSE)
