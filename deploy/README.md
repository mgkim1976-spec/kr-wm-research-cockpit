# 매일 자동 업데이트 배포 (macOS launchd)

매일 아침 미래에셋 리서치를 크롤해 `research_db.json`을 갱신하고, 대시보드(http://localhost:8768)가 이를 자동 반영하도록 한다.

## 구성
- **`daily_update.py`** — 4단계 배치: ① 리서치 메타(download_reports) ② KRX 수급(krx_market, 1·5·20·50일 + 종목 주도주체) ③ OECD CLI 국면(cli_phase) ④ 종목 도시에(build_dossiers)
- **`com.pbcopilot.dailyupdate.plist`** — 매일 **07:30** 배치 실행
- **`com.pbcopilot.server.plist`** — 대시보드 서버 상시 가동(죽으면 자동 재시작, 부팅 시 시작)
- 서버는 `data/*.json` 변경(mtime)을 감지해 **데이터는 재시작 없이 자동 반영** (scenario_engine._ensure_loaded)
- ⚠️ **코드(.py)·템플릿(.html) 변경 시엔 서버 재시작 필요** (debug=False → Jinja 템플릿 캐시):
  `launchctl kickstart -k gui/$(id -u)/com.pbcopilot.server`
- ⚠️ **KRX 로그인**: `.env`의 KRX_ID/KRX_PW. 비번 만료 시 배치가 0거래일·빈배열로 조용히 실패 → `data/krx_market.json`의 `"dates":[]`/`net_error`로 확인, krx.co.kr에서 비번 변경 후 .env 갱신.

> 즉, 07:30 크롤 → DB 갱신 → 다음 화면 새로고침 시 최신 시황 반영 → **08:00 전 준비 완료**.

## 설치 (1회)
```bash
chmod +x /ABSOLUTE/PATH/TO/kr-wm-research-cockpit/daily_update.sh

# launchd 에이전트 등록
cp deploy/com.pbcopilot.dailyupdate.plist ~/Library/LaunchAgents/
cp deploy/com.pbcopilot.server.plist      ~/Library/LaunchAgents/
launchctl load ~/Library/LaunchAgents/com.pbcopilot.dailyupdate.plist
launchctl load ~/Library/LaunchAgents/com.pbcopilot.server.plist
```

## 확인 / 운영
```bash
launchctl list | grep pbcopilot          # 등록 확인
bash daily_update.sh                      # 크롤 수동 1회 테스트
tail -f logs/daily_update_$(date +%Y%m%d).log
open http://localhost:8768                # 대시보드
```

## 해제
```bash
launchctl unload ~/Library/LaunchAgents/com.pbcopilot.dailyupdate.plist
launchctl unload ~/Library/LaunchAgents/com.pbcopilot.server.plist
```

## 참고
- 크롤은 `securities.miraeasset.com` 접속이 필요(네트워크). 실패해도 기존 DB로 서버는 계속 동작.
- 시간대는 시스템 로컬타임 기준(KST면 07:30 KST).
- cron 선호 시: `30 7 * * * /ABSOLUTE/PATH/TO/kr-wm-research-cockpit/daily_update.sh`
