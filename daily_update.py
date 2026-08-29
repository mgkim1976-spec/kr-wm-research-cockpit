#!/usr/bin/env python3
"""크로스플랫폼 일일 업데이트 (Windows/macOS/Linux 공통).

    python daily_update.py

3단계: ① 당사 리서치 메타(download_reports) ② KRX 수급(krx_market) ③ 종목 도시에(build_dossiers).
대시보드 서버는 data/*.json 변경을 감지해 자동 반영(재시작 불필요).
스케줄링: Windows=작업 스케줄러 / macOS=launchd(deploy/) / Linux=cron — README 참고.
"""
import os
import subprocess
import sys
from datetime import datetime
from pathlib import Path

# .env 를 환경으로 올린다. 단계는 자식 프로세스로 도니 여기서 올려야 상속된다.
#
# 왜 필요해졌나: pykrx 1.2.7 부터 **import 시점에** KRX 로그인을 시도한다.
# 자격증명이 환경에 없으면 로그인이 실패하고, 1.2.7 은 거기서 JSONDecodeError 로
# 죽어 잡 전체가 멈췄다(2026-08-13 이후 17일). 1.2.8 은 실패해도 익명으로
# 넘어가지만, 로그인이 필요한 조회가 조용히 비므로 어차피 실어 줘야 한다.
def _load_env(path: Path) -> int:
    if not path.exists():
        return 0
    n = 0
    for ln in path.read_text(encoding="utf-8", errors="ignore").splitlines():
        ln = ln.strip()
        if not ln or ln.startswith("#") or "=" not in ln:
            continue
        k, v = ln.split("=", 1)
        k, v = k.strip(), v.strip().strip('"').strip("'")
        if k and k not in os.environ:
            os.environ[k] = v
            n += 1
    return n

try:
    sys.stdout.reconfigure(encoding="utf-8")   # 윈도우 콘솔 한글/이모지
except Exception:
    pass

ROOT = Path(__file__).resolve().parent
_n = _load_env(ROOT / ".env")
print(f"[env] {_n}개 로드")     # 값은 찍지 않는다
STEPS = [
    ["download_reports.py"],
    [str(Path("app") / "core" / "adapters" / "krx_market.py"), "--years", "2"],
    [str(Path("app") / "core" / "adapters" / "cli_phase.py")],
    [str(Path("app") / "core" / "adapters" / "investor_flow.py")],
    [str(Path("app") / "core" / "adapters" / "investor_pattern.py")],
    ["build_dossiers.py"],
    # 업종 브리핑북 — 산출물은 Alpha_Stream 에 있지만 대시보드가 읽어 쓰므로
    # '데이터 수집·반영' 버튼 한 번으로 화면 전체가 같은 시점이 되도록 여기서 함께 돌린다.
    # (별도로 두면 버튼을 눌러도 ④ 업종 섹션만 낡은 상태로 남는다)
    [str(Path.home() / "MGPrj" / "Alpha_Stream" / "sector_book.py")],
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
