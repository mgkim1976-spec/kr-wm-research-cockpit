# KR WM Research Cockpit

한국 주식시장 **Wealth Manager / PB를 위한 의사결정 지원 대시보드**.
시장 수급(누가 사고파나)부터 시작해 **필요한 리서치 → 우선 접촉할 고객**까지 한 화면으로 잇는다.

> ⚠️ 투자 조언이 아닌 **리서치 큐레이션·영업 의사결정 보조 도구**입니다. 매매 판단·적합성(suitability)은 사용자 책임입니다.

---

## 무엇을 하나 — 3단 깔때기 + 상담 메시지

```
🌐 경기국면        OECD 한국 경기선행지수(FRED CLI) 4국면(회복/확장/둔화/수축)
                  · 국면별 과거 fwd 지수 초과수익 — 방향 베팅 1차 신호는 주도세력보다 '국면'
   ↓
① 시황            KRX 투자자별 수급으로 시장 주도주체 판별 (1·5·20·50영업일 토글)
                  · 🚦 방향주도(leader) = corr(주체 순매수, 지수 수익률) 최대 주체
                    ↔ 받아주는 쪽(absorber). cf. 자금주도(최대순매수)는 받아주는 쪽일 수 있음
                  · 🛰️ regime 전환 게이지: 개인 norm β(행태) + flow강도·거래대금(규모) + β추세
                  · 개인 누적 순매수 · 거래대금/비중 추이 · 자금 회전 Sankey
   ↓
② 필요 컨텐츠      방향주도 순매수 + 외인/기관 매집 종목 → 당사+타사 리서치 자동 연결
                  · 종목별 수급 주도주체 배지: 개인/외국인/기관 + 동반/단독(트랩) +
                    매집/이탈 궤적(지속매집·둔화·이탈 수익실현/손절, 50일 실적사이클 기준)
                  · LLM(OpenAI) Talking Points: 🟢기회 / 🔴리스크 / ⚖️견해차 / 📅카탈리스트
                  · 당사 리서치 없음/오래됨 → 📮 리서치센터 요청서 자동 생성
   ↓
③ 고객 관리 우선순위  국면·주도 기반 고객 '세그먼트' 우선순위 + 🟠개인 쏠림·과열 경보
   ↓
💬 상담 메시지      오늘 시황 주요 이슈별 상담 톤(방법론 매뉴얼 기반)
```

데이터 출처: **KRX 투자자별 수급(pykrx)** · **FRED OECD 한국 CLI**(KORLOLITOAASTSAM) · **네이버 금융 리서치**(당사=미래에셋 + 타사) · **OpenAI**(요약).
방법론(13 시장 시나리오): [`docs/MARKET_SCENARIO_ADVISORY_MANUAL.md`](docs/MARKET_SCENARIO_ADVISORY_MANUAL.md).

> **주도세력 = 방향(corr) 판정** — 외인+기관+개인 순매수 합은 ~0이라 *최대순매수*는 받아주는 쪽일 수 있음. 8년 검증: 개인은 동시점 corr 기준 단 하루도 방향주도였던 적 없음(항상 흡수자), forward 수익을 가르는 건 주도세력보다 **CLI 국면**. 예금→주식 이동은 규모(거래대금 3배)로 오나 행태전환(개인 norm β→0)은 아직 아님. 분석 스크립트: `analyze_*.py`.

---

## 빠른 시작

```bash
# 1. 의존성
pip install -r requirements.txt

# 2. 자격정보 (.env)
cp .env.example .env          # KRX_ID/KRX_PW (data.krx.co.kr), OPENAI_API_KEY 채우기

# 3. 데이터 수집 (최초 1회 / 이후 매일) — 한 번에:  python3 daily_update.py
python3 download_reports.py                       # 당사(미래에셋) 리서치 메타
python3 app/core/adapters/krx_market.py --years 2 # KRX 수급(1·5·20·50일) → data/krx_market.json
python3 app/core/adapters/cli_phase.py            # OECD CLI 4국면 → data/cli_phase.json
python3 build_dossiers.py                          # 종목 Talking Points(LLM) → data/dossiers.json

# (선택) 장기 분석용 8년 히스토리 — CLI 국면별 fwd 통계가 이 파일을 사용
python3 analyze_regime_cycle.py --refetch          # → data/krx_history.json

# 4. 대시보드 실행
python3 app/app.py            # → http://localhost:8768
```

> 데이터 파일(`data/*.json`, `research_reports/`)은 크롤로 생성되며 저장소에 포함되지 않습니다(.gitignore). 위 3단계를 먼저 실행하세요.

---

## 플랫폼 (Windows / macOS / Linux)

코어(Flask·pykrx·requests)는 크로스플랫폼입니다.
- **데이터 수집(3단계)을 한 번에**: `python daily_update.py` (OS 공통). `daily_update.sh`는 macOS/Linux 전용.
- **KRX 자격**: pip 표준 `pykrx`는 **로그인 불필요**(익명) — `KRX_ID/KRX_PW` 없이도 동작합니다. (`.env`엔 `OPENAI_API_KEY`만 채워도 됨)
- **Windows venv**: `py -m venv .venv && .venv\Scripts\activate && pip install -r requirements.txt`
- **스케줄링**: Windows=작업 스케줄러(매일 `python daily_update.py` + 부팅 시 `python app\app.py`) / macOS=launchd(`deploy/`) / Linux=cron.

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
  app.py                       Flask (8768) — /api/state /api/krx /api/cli /api/flow_link /api/brief
  templates/index.html         대시보드 (Tailwind + Chart.js + Sankey) — CLI국면·게이지·종목 주도주체 배지
  core/
    engine/
      scenario_engine.py       시황 감지 · active_actor(방향주도) · 수급↔리서치 브리지 · 고객 우선순위
      dossier.py               OpenAI Talking Points (당사+타사 본문 기반)
    adapters/
      krx_market.py            KRX 수급(pykrx) — leader/absorber · regime 게이지 · 종목별 주도주체·궤적
      cli_phase.py             OECD 한국 CLI(FRED) 4국면 + 국면별 fwd 통계
      kr_research.py           네이버 금융 리서치 크롤 (당사+타사, 본문 포함)
      research_crawler.py      미래에셋 리서치 메타 크롤
  models/resources.py          데이터 모델
analyze_regime.py              2년 주도세력 전환 패턴
analyze_regime_cycle.py        8년 × CLI 경기사이클 (국면별 주도세력·forward)
analyze_norm_beta.py           정규화 β — 외인 영향력 하락이 거래량 착시인지 검증
analyze_robustness.py          강건성(win 민감도 · 개인 lead-lag · 정규화)
data/scenario_taxonomy.json    13 시나리오 키워드 사전 (유일하게 커밋되는 데이터)
data/regime_history.jsonl      regime 일별 스냅샷(전환 장기추적, .gitignore)
docs/MARKET_SCENARIO_ADVISORY_MANUAL.md   방법론(13 시장 시나리오)
download_reports.py / build_dossiers.py / daily_update.py(.sh)
deploy/                        launchd 배포 (server 상시 + dailyupdate 07:30)
```

---

## 주의 / 면책

- 본 도구는 **정보 제공·영업 의사결정 보조**용이며 투자 권유가 아닙니다.
- KRX·네이버·증권사 리서치는 각 제공자의 이용약관을 따릅니다. 수집 데이터는 **개인 학습/연구 범위** 내에서 사용하세요(저작권 자료 재배포 금지 — 그래서 데이터/PDF는 저장소에 포함하지 않습니다).
- LLM 요약은 리포트 제목·요약 본문 근거이며 오류가 있을 수 있습니다. 원문 링크로 확인하세요.

## 라이선스
MIT — [LICENSE](LICENSE)
