#!/usr/bin/env python3
"""크로스플랫폼 일일 업데이트 (Windows/macOS/Linux 공통).

    python daily_update.py

3단계: ① 당사 리서치 메타(download_reports) ② KRX 수급(krx_market) ③ 종목 도시에(build_dossiers).
대시보드 서버는 data/*.json 변경을 감지해 자동 반영(재시작 불필요).
스케줄링: Windows=작업 스케줄러 / macOS=launchd(deploy/) / Linux=cron — README 참고.
"""
import subprocess
import sys
from datetime import datetime
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8")   # 윈도우 콘솔 한글/이모지
except Exception:
    pass

ROOT = Path(__file__).resolve().parent
STEPS = [
    ["download_reports.py"],
    [str(Path("app") / "core" / "adapters" / "krx_market.py"), "--years", "2"],
    [str(Path("app") / "core" / "adapters" / "cli_phase.py")],
    [str(Path("app") / "core" / "adapters" / "investor_flow.py")],
    [str(Path("app") / "core" / "adapters" / "investor_pattern.py")],
    ["build_dossiers.py"],
]


def main():
    print(f"=== {datetime.now():%Y-%m-%d %H:%M:%S} 일일 업데이트 시작 ===")
    for args in STEPS:
        print(f"\n>>> python {' '.join(args)}")
        r = subprocess.run([sys.executable, *args], cwd=str(ROOT))
        if r.returncode != 0:
            print(f"  [경고] 종료코드 {r.returncode} — 계속 진행")
    print(f"\n=== {datetime.now():%Y-%m-%d %H:%M:%S} 완료 ===")


if __name__ == "__main__":
    main()
