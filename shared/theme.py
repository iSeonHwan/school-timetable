"""
앱 전역 라이트 테마 스타일시트

macOS 다크 모드 환경에서 PyQt6는 일부 위젯의 텍스트 색상을
시스템 팔레트(흰색)에서 가져오면서 배경은 코드에서 흰색으로 고정합니다.
결과적으로 흰 배경 + 흰 글씨가 되어 내용이 보이지 않는 문제가 발생합니다.

QApplication.setStyleSheet()로 이 스타일시트를 적용하면 모든 위젯이
명시적인 라이트 테마 색상을 사용하므로 문제가 해결됩니다.
개별 위젯에서 setStyleSheet()로 지정한 스타일은 이 전역 스타일보다 우선합니다.
"""

LIGHT_THEME_QSS = """
/* ── 기본 위젯 ─────────────────────────────────────────────── */
QWidget {
    background-color: #F4F7FB;
    color: #1A1A1A;
}

/* 배경이 투명해야 하는 컨테이너는 명시적으로 투명 지정 */
QFrame, QGroupBox, QStackedWidget, QScrollArea {
    background-color: #F4F7FB;
}

/* ── 텍스트 레이블 ───────────────────────────────────────────── */
QLabel {
    color: #1A1A1A;
    background: transparent;
}

/* ── 입력 위젯 ─────────────────────────────────────────────── */
QLineEdit, QTextEdit, QPlainTextEdit {
    background-color: #FFFFFF;
    color: #1A1A1A;
    border: 1px solid #CCCCCC;
    border-radius: 3px;
    padding: 3px 5px;
    selection-background-color: #1B4F8A;
    selection-color: #FFFFFF;
}

QSpinBox, QDoubleSpinBox, QDateEdit, QTimeEdit, QDateTimeEdit {
    background-color: #FFFFFF;
    color: #1A1A1A;
    border: 1px solid #CCCCCC;
    border-radius: 3px;
    padding: 2px 4px;
}

QComboBox {
    background-color: #FFFFFF;
    color: #1A1A1A;
    border: 1px solid #CCCCCC;
    border-radius: 3px;
    padding: 3px 5px;
}
QComboBox QAbstractItemView {
    background-color: #FFFFFF;
    color: #1A1A1A;
    selection-background-color: #1B4F8A;
    selection-color: #FFFFFF;
    border: 1px solid #CCCCCC;
}
QComboBox::drop-down {
    border: none;
}

/* ── 체크박스·라디오버튼 ──────────────────────────────────────── */
QCheckBox, QRadioButton {
    color: #1A1A1A;
    background: transparent;
}

/* ── 버튼 ──────────────────────────────────────────────────── */
QPushButton {
    background-color: #E8ECF0;
    color: #1A1A1A;
    border: 1px solid #C0C8D0;
    border-radius: 4px;
    padding: 5px 12px;
}
QPushButton:hover {
    background-color: #D5DCE5;
}
QPushButton:pressed {
    background-color: #C0CAD5;
}
QPushButton:disabled {
    background-color: #F0F0F0;
    color: #AAAAAA;
    border-color: #DDDDDD;
}
QPushButton:checked {
    background-color: #1B4F8A;
    color: #FFFFFF;
}

/* ── 테이블 ────────────────────────────────────────────────── */
QTableWidget, QTableView {
    background-color: #FFFFFF;
    color: #1A1A1A;
    gridline-color: #E0E0E0;
    border: 1px solid #CCCCCC;
    alternate-background-color: #F5F8FF;
}
QTableWidget::item, QTableView::item {
    color: #1A1A1A;
    padding: 2px 4px;
}
QTableWidget::item:selected, QTableView::item:selected {
    background-color: #1B4F8A;
    color: #FFFFFF;
}

QHeaderView {
    background-color: #1B4F8A;
}
QHeaderView::section {
    background-color: #1B4F8A;
    color: #FFFFFF;
    font-weight: bold;
    padding: 4px;
    border: none;
    border-right: 1px solid #2460A5;
    border-bottom: 1px solid #2460A5;
}

/* ── 리스트·트리 ────────────────────────────────────────────── */
QListWidget, QListView {
    background-color: #FFFFFF;
    color: #1A1A1A;
    border: 1px solid #CCCCCC;
}
QListWidget::item, QListView::item {
    color: #1A1A1A;
}
QListWidget::item:selected, QListView::item:selected {
    background-color: #1B4F8A;
    color: #FFFFFF;
}
QTreeWidget, QTreeView {
    background-color: #FFFFFF;
    color: #1A1A1A;
    border: 1px solid #CCCCCC;
}
QTreeWidget::item, QTreeView::item {
    color: #1A1A1A;
}
QTreeWidget::item:selected, QTreeView::item:selected {
    background-color: #1B4F8A;
    color: #FFFFFF;
}

/* ── 탭 ────────────────────────────────────────────────────── */
QTabWidget::pane {
    border: 1px solid #CCCCCC;
    background-color: #FFFFFF;
}
QTabBar::tab {
    background-color: #E0E6EF;
    color: #1A1A1A;
    padding: 6px 14px;
    border: 1px solid #CCCCCC;
    border-bottom: none;
    margin-right: 2px;
}
QTabBar::tab:selected {
    background-color: #1B4F8A;
    color: #FFFFFF;
    font-weight: bold;
}
QTabBar::tab:hover:!selected {
    background-color: #C8D5E5;
}

/* ── 스크롤바 ──────────────────────────────────────────────── */
QScrollBar:vertical {
    background: #F0F0F0;
    width: 10px;
    margin: 0;
}
QScrollBar::handle:vertical {
    background: #BBBBBB;
    min-height: 24px;
    border-radius: 5px;
}
QScrollBar::handle:vertical:hover {
    background: #999999;
}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {
    height: 0;
}
QScrollBar:horizontal {
    background: #F0F0F0;
    height: 10px;
}
QScrollBar::handle:horizontal {
    background: #BBBBBB;
    min-width: 24px;
    border-radius: 5px;
}
QScrollBar::handle:horizontal:hover {
    background: #999999;
}
QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal {
    width: 0;
}

/* ── 스플리터 ──────────────────────────────────────────────── */
QSplitter::handle {
    background-color: #CCCCCC;
}

/* ── 다이얼로그·메시지박스 ──────────────────────────────────── */
QDialog {
    background-color: #F4F7FB;
}
QMessageBox {
    background-color: #F4F7FB;
}
QMessageBox QLabel {
    color: #1A1A1A;
}

/* ── 툴팁 ──────────────────────────────────────────────────── */
QToolTip {
    background-color: #FFFFF0;
    color: #1A1A1A;
    border: 1px solid #CCCCCC;
}

/* ── 메뉴 ──────────────────────────────────────────────────── */
QMenu {
    background-color: #FFFFFF;
    color: #1A1A1A;
    border: 1px solid #CCCCCC;
}
QMenu::item:selected {
    background-color: #1B4F8A;
    color: #FFFFFF;
}
"""
