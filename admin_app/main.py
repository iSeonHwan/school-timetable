"""
관리 프로그램 진입점 (교감·일과계용)

기존 시간표 관리 기능(편제·교사·교과·시간표 생성·변경 승인·이력)에
로그인 화면과 채팅 패널이 추가됩니다.

실행 방법:
  python -m admin_app.main

환경 변수:
  SERVER_URL: FastAPI 서버 주소 (기본 http://localhost:8000)
"""
import sys
import os
from PyQt6.QtWidgets import QApplication
from admin_app.ui.login_window import LoginWindow


def main():
    app = QApplication(sys.argv)
    app.setApplicationName("시간표 관리 시스템 — 관리자")

    server_url = os.getenv("SERVER_URL", "http://localhost:8000")
    window = LoginWindow(server_url=server_url)
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
