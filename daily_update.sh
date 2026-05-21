#!/bin/bash
# 미래에셋 리서치 일일 크롤 배치
#   - download_reports.py: 최근 리포트 수집 → research_db.json 갱신 + PDF 다운로드
#   - 서버(app/app.py)는 research_db.json의 mtime 변경을 감지해 자동 반영 (재시작 불필요)
# launchd(또는 cron)가 매일 아침(예: 07:30 KST) 실행 → 08:00 전 최신 시황 반영
set -uo pipefail
cd "$(dirname "$0")"
mkdir -p logs
LOG="logs/daily_update_$(date +%Y%m%d).log"
{
  echo "=== $(date '+%Y-%m-%d %H:%M:%S') 리서치 크롤 시작 ==="
  /usr/bin/env python3 download_reports.py
  echo "--- $(date '+%H:%M:%S') KRX 시장 수급 갱신 ---"
  /usr/bin/env python3 app/core/adapters/krx_market.py --years 2
  echo "--- $(date '+%H:%M:%S') 종목 Talking Points 도시에(당사+타사 본문, LLM) 생성 ---"
  /usr/bin/env python3 build_dossiers.py
  echo "=== $(date '+%Y-%m-%d %H:%M:%S') 완료 (exit $?) ==="
} >> "$LOG" 2>&1
