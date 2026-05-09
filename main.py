"""
학교 시간표 관리 시스템 — 진입점 (Entry Point)

실행 순서:
  1. QApplication 생성 (PyQt6 이벤트 루프 초기화)
  2. db_config.json 을 읽어 DB URL 구성
  3. SQLAlchemy 엔진 초기화 + 테이블 자동 생성
  4. DB 연결 실패 시 로컬 SQLite(timetable.db)로 폴백
  5. MainWindow 를 띄우고 이벤트 루프 진입
"""
import sys
import os

# PyInstaller로 패키징된 실행 파일에서도 프로젝트 루트를 import 경로에 포함시킵니다.
sys.path.insert(0, os.path.dirname(__file__))

from PyQt6.QtWidgets import QApplication, QMessageBox
from PyQt6.QtCore import Qt

from config import load_config, get_db_url
from database.connection import init_db
from ui.main_window import MainWindow


def main():
    # ── Qt 애플리케이션 초기화 ──────────────────────────────────
    app = QApplication(sys.argv)
    app.setApplicationName("학교 시간표 관리 시스템")
    # Fusion 스타일: macOS/Windows/Linux 에서 일관된 외관을 제공합니다.
    app.setStyle("Fusion")

    # ── 데이터베이스 초기화 ─────────────────────────────────────
    try:
        cfg = load_config()          # db_config.json 읽기 (없으면 기본값)
        init_db(get_db_url(cfg))     # SQLAlchemy 엔진 생성 + 테이블 CREATE IF NOT EXISTS
    except Exception as e:
        # DB 연결 실패 → 사용자에게 알리고 SQLite 폴백 시도
        QMessageBox.critical(
            None, "DB 연결 오류",
            f"데이터베이스 연결에 실패했습니다:\n{e}\n\n"
            "앱 실행 후 'DB 연결 설정'에서 다시 설정해 주세요."
        )
        try:
            # 프로젝트 루트의 timetable.db 를 기본 파일로 사용합니다.
            fallback_url = f"sqlite:///{os.path.join(os.path.dirname(__file__), 'timetable.db')}"
            init_db(fallback_url)
        except Exception:
            # 폴백 마저 실패하면 프로그램을 종료합니다.
            sys.exit(1)

    # ── 메인 윈도우 표시 및 이벤트 루프 시작 ───────────────────
    window = MainWindow()
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
