"""
교사 프로그램 진입점

기능:
  - 로그인 (아이디·비밀번호)
  - 본인 시간표 / 학반 시간표 조회
  - 당일 시간표 교체 신청 및 결과 확인
  - 전체 공동 채팅 (오른쪽 패널)

실행 방법:
  python -m teacher_app.main

환경 변수:
  SERVER_URL: FastAPI 서버 주소 (기본 http://localhost:8000)
"""
import sys
import os
from PyQt6.QtWidgets import QApplication
from teacher_app.ui.login_window import TeacherLoginWindow
from shared.theme import LIGHT_THEME_QSS   # 다크 모드 충돌 방지용 전역 라이트 테마


def main():
    app = QApplication(sys.argv)
    app.setApplicationName("시간표 확인 — 교사용")

    # macOS 다크 모드에서 시스템 팔레트가 PyQt6 위젯에 흰 텍스트를 적용하면
    # background:white 위젯에서 흰 글씨가 되는 문제를 방지합니다.
    app.setStyleSheet(LIGHT_THEME_QSS)

    server_url = os.getenv("SERVER_URL", "http://localhost:8000")
    window = TeacherLoginWindow(server_url=server_url)
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
