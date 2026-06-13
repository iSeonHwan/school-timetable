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
from database.connection import init_db  # 관리자 앱은 DB에 직접 접근하므로 시작 시 초기화
from shared.theme import LIGHT_THEME_QSS   # 다크 모드 충돌 방지용 전역 라이트 테마


def main():
    app = QApplication(sys.argv)
    app.setApplicationName("시간표 관리 시스템 — 관리자")

    # macOS 다크 모드에서 시스템 팔레트가 PyQt6 위젯에 흰 텍스트를 적용하면
    # background:white 위젯에서 흰 글씨가 되는 문제를 방지합니다.
    app.setStyleSheet(LIGHT_THEME_QSS)

    # ui/ 위젯들(ClassSetupWidget 등)이 get_session()을 직접 호출합니다.
    # AdminMainWindow 생성 전에 반드시 init_db()를 호출해야 합니다.
    init_db()

    server_url = os.getenv("SERVER_URL", "http://localhost:8000")
    window = LoginWindow(server_url=server_url)
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
