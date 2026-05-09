import sys
import os

# 프로젝트 루트를 sys.path에 추가
sys.path.insert(0, os.path.dirname(__file__))

from PyQt6.QtWidgets import QApplication, QMessageBox
from PyQt6.QtCore import Qt

from config import load_config, get_db_url
from database.connection import init_db
from ui.main_window import MainWindow


def main():
    app = QApplication(sys.argv)
    app.setApplicationName("학교 시간표 관리 시스템")
    app.setStyle("Fusion")

    # DB 초기화
    try:
        cfg = load_config()
        init_db(get_db_url(cfg))
    except Exception as e:
        QMessageBox.critical(
            None, "DB 연결 오류",
            f"데이터베이스 연결에 실패했습니다:\n{e}\n\n"
            "앱 실행 후 'DB 연결 설정'에서 다시 설정해 주세요."
        )
        # SQLite fallback
        try:
            fallback_url = f"sqlite:///{os.path.join(os.path.dirname(__file__), 'timetable.db')}"
            init_db(fallback_url)
        except Exception:
            sys.exit(1)

    window = MainWindow()
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
