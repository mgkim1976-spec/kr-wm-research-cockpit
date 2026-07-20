"""
KR WM Research Cockpit — 시황 → 필요 컨텐츠 → 고객 관리 우선순위 대시보드 (Flask)

① 시황(KRX 수급·주도주체) → ② 필요 컨텐츠(당사+타사 리서치·LLM Talking Points·요청)
→ ③ 고객 관리 우선순위(세그먼트) → 💬 상담 메시지

실행:  python3 app/app.py    →  http://localhost:8768
방법론: docs/MARKET_SCENARIO_ADVISORY_MANUAL.md (13 시장 시나리오)
"""
from __future__ import annotations

import datetime
import subprocess
import sys
import threading
from pathlib import Path

import json
from flask import Flask, jsonify, render_template, request

APP_DIR = Path(__file__).resolve().parent
ROOT = APP_DIR.parent
sys.path.insert(0, str(APP_DIR / "core" / "engine"))
sys.path.insert(0, str(APP_DIR / "core" / "adapters"))
import scenario_engine as se   # noqa: E402
import krx_market              # noqa: E402
import cli_phase               # noqa: E402

app = Flask(__name__, template_folder=str(APP_DIR / "templates"))
PORT = 8768

# 데이터 수집(크롤+KRX+LLM) 비동기 실행 상태 — '데이터 수집·반영' 버튼용
COLLECT = {"running": False, "started": None, "finished": None, "rc": None, "error": None}


def _run_collect() -> None:
    COLLECT.update(running=True, started=datetime.datetime.now().strftime("%H:%M:%S"),
                   finished=None, rc=None, error=None)
    try:
        r = subprocess.run([sys.executable, str(ROOT / "daily_update.py")],
                           cwd=str(ROOT), capture_output=True, text=True, timeout=1800)
        COLLECT["rc"] = r.returncode
    except Exception as e:   # noqa: BLE001
        COLLECT["error"], COLLECT["rc"] = str(e)[:200], -1
    finally:
        COLLECT["running"] = False
        COLLECT["finished"] = datetime.datetime.now().strftime("%H:%M:%S")


@app.route("/")
def index():
    return render_template("index.html")


@app.route("/api/state")
def api_state():
    """오늘의 시황 자동감지(상담 메시지용) + 기준일·리서치 수."""
    return jsonify(se.get_state())


@app.route("/api/krx")
def api_krx():
    """① KRX 시장 수급 (캐시). daily_update.sh 가 갱신, 대시보드는 캐시만 읽음."""
    return jsonify(krx_market.load_cached())


@app.route("/api/cli")
def api_cli():
    """OECD 한국 경기선행지수(CLI) 4국면 + 국면별 과거 fwd 지수수익. daily_update 가 갱신."""
    return jsonify(cli_phase.load_cached())


@app.route("/api/investor")
def api_investor():
    """투자자 자금이동 — 변곡점 예측(낙폭+연기금)·하락장 항복·외국인 지분율. daily_update 가 갱신."""
    import investor_flow
    import investor_pattern
    return jsonify({"pattern": investor_pattern.load_cached(), "flow": investor_flow.load_cached()})


@app.route("/api/flow_link")
def api_flow_link():
    """② 수급↔리서치: 주도주체 순매수상위+외인/기관 매집 → 당사/타사 리서치·도시에 + 커버리지 GAP."""
    days = request.args.get("days", default=45, type=int)
    win = request.args.get("win", default="5", type=str)
    return jsonify(se.flow_research_link(days=days, win=win))


@app.route("/api/brief")
def api_brief():
    """③ 고객 관리 우선순위: 시황 기반 고객 세그먼트 우선순위 + 쏠림 경보."""
    days = request.args.get("days", default=45, type=int)
    return jsonify(se.contact_priority(days=days))


# 업종 브리핑북 — Alpha_Stream 의 sector_book.py 가 네이버 산업분석 리포트를 정리해 둔 파일.
# 생성은 그쪽에서, 열람은 여기서. dossiers.json 을 Alpha_Stream 이 읽어가는 것과 대칭이다.
SECTOR_BOOK = Path.home() / "MGPrj" / "Alpha_Stream" / "data" / "sector_book.json"


@app.route("/api/sectors")
def api_sectors():
    try:
        return jsonify(json.loads(SECTOR_BOOK.read_text(encoding="utf-8")))
    except Exception as e:
        return jsonify({"_error": str(e)})


@app.route("/api/collect", methods=["POST"])
def api_collect():
    """데이터 수집(크롤+KRX+LLM 도시에) 비동기 시작. 이미 실행 중이면 중복 방지."""
    if COLLECT["running"]:
        return jsonify({"status": "running", **COLLECT})
    threading.Thread(target=_run_collect, daemon=True).start()
    return jsonify({"status": "started", **COLLECT})


@app.route("/api/collect/status")
def api_collect_status():
    return jsonify(COLLECT)


if __name__ == "__main__":
    print(f"\n  KR WM Research Cockpit\n  http://localhost:{PORT}\n")
    se.get_state()   # 캐시 워밍업
    app.run(host="127.0.0.1", port=PORT, debug=False)
