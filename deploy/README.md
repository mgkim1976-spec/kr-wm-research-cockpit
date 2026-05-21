# 매일 자동 업데이트 배포 (macOS launchd)

매일 아침 미래에셋 리서치를 크롤해 `research_db.json`을 갱신하고, 대시보드(http://localhost:8768)가 이를 자동 반영하도록 한다.

## 구성
- **`daily_update.sh`** — 크롤 배치 (download_reports.py 실행 → DB 갱신 + PDF 다운로드)
- **`com.pbcopilot.dailyupdate.plist`** — 매일 **07:30** 크롤 실행
- **`com.pbcopilot.server.plist`** — 대시보드 서버 상시 가동(죽으면 자동 재시작, 부팅 시 시작)
- 서버는 `research_db.json` 변경(mtime)을 감지해 **재시작 없이 자동 반영** (scenario_engine._ensure_loaded)

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
