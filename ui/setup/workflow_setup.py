"""
결재 워크플로우 설정 화면

ApprovalWorkflow + ApprovalStep 테이블의 CRUD 를 제공합니다.
일과계 선생님이 결재 단계 수와 각 단계의 승인자를 자유롭게 구성할 수 있습니다.

사용 예:
  1단계 — 일과계가 바로 최종 승인
  2단계 — 일과계 1차 승인 → 교감 최종 승인 (기본값)
  3단계 — 일과계 검토 → 교무부장 검토 → 교감 최종 승인
"""
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit,
    QPushButton, QTableWidget, QTableWidgetItem,
    QFrame, QDialog, QDialogButtonBox, QComboBox,
    QFormLayout, QMessageBox, QHeaderView, QSpinBox,
)
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QFont
from database.connection import get_session
from database.models import ApprovalWorkflow, ApprovalStep

BTN_PRIMARY = "background:#1B4F8A; color:white; border-radius:4px; padding:6px 14px; font-weight:bold;"
BTN_DANGER = "background:#C0392B; color:white; border-radius:4px; padding:6px 14px;"
BTN_SUCCESS = "background:#27AE60; color:white; border-radius:4px; padding:6px 14px; font-weight:bold;"

# 결재 단계에 할당 가능한 역할 목록
APPROVER_ROLES = ["admin (일과계)", "vice_principal (교감)", "department_head (교무부장)"]
# 실제 role 값 (콤보박스 표시 텍스트에서 추출)
ROLE_VALUES = {
    "admin (일과계)": "admin",
    "vice_principal (교감)": "vice_principal",
    "department_head (교무부장)": "department_head",
}
ROLE_DISPLAY = {v: k for k, v in ROLE_VALUES.items()}


class WorkflowSetupWidget(QWidget):
    """결재 워크플로우 관리 위젯."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._init_ui()
        self._load_data()

    def refresh(self):
        """페이지 전환 시 호출됩니다."""
        self._load_data()

    def _init_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(14)

        title = QLabel("결재 라인 설정")
        title.setFont(QFont("", 14, QFont.Weight.Bold))
        title.setStyleSheet("color: #1B4F8A;")
        layout.addWidget(title)

        desc = QLabel("변경 신청(수업 교체·결보강)의 결재 단계를 설정합니다. "
                       "활성화된 워크플로우가 실제 승인/거절 처리에 사용됩니다.")
        desc.setWordWrap(True)
        desc.setStyleSheet("color: #555; margin-bottom: 4px;")
        layout.addWidget(desc)

        # ── 워크플로우 목록 테이블 ─────────────────────────────────
        frame = QFrame()
        frame.setStyleSheet("border:1px solid #CCCCCC; border-radius:6px; background:white;")
        f_layout = QVBoxLayout(frame)
        f_layout.setContentsMargins(12, 10, 12, 10)

        self._table = QTableWidget(0, 4)
        self._table.setHorizontalHeaderLabels(["이름", "설명", "단계 수", "활성"])
        self._table.horizontalHeader().setStretchLastSection(False)
        self._table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self._table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        self._table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.Fixed)
        self._table.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeMode.Fixed)
        self._table.setColumnWidth(2, 80)
        self._table.setColumnWidth(3, 80)
        self._table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self._table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self._table.setSelectionMode(QTableWidget.SelectionMode.SingleSelection)
        self._table.setStyleSheet("QHeaderView::section { background:#1B4F8A; color:white; padding:4px; }")
        f_layout.addWidget(self._table)

        # ── 액션 버튼 행 ───────────────────────────────────────────
        btn_row = QHBoxLayout()

        self._btn_new = QPushButton("새 워크플로우")
        self._btn_new.setStyleSheet(BTN_PRIMARY)
        self._btn_new.clicked.connect(self._on_new)
        btn_row.addWidget(self._btn_new)

        self._btn_activate = QPushButton("활성화")
        self._btn_activate.setStyleSheet(BTN_SUCCESS)
        self._btn_activate.clicked.connect(self._on_activate)
        btn_row.addWidget(self._btn_activate)

        self._btn_delete = QPushButton("삭제")
        self._btn_delete.setStyleSheet(BTN_DANGER)
        self._btn_delete.clicked.connect(self._on_delete)
        btn_row.addWidget(self._btn_delete)

        btn_row.addStretch()
        f_layout.addLayout(btn_row)

        layout.addWidget(frame)
        layout.addStretch()

    def _load_data(self):
        """DB 에서 워크플로우 목록을 읽어 테이블에 표시합니다."""
        session = get_session()
        try:
            workflows = session.query(ApprovalWorkflow).order_by(
                ApprovalWorkflow.created_at.desc()
            ).all()

            self._table.setRowCount(len(workflows))
            for row, wf in enumerate(workflows):
                self._table.setItem(row, 0, QTableWidgetItem(wf.name))
                self._table.setItem(row, 1, QTableWidgetItem(wf.description or ""))
                self._table.setItem(row, 2, QTableWidgetItem(str(len(wf.steps))))
                active_text = "★ 활성" if wf.is_active else ""
                item = QTableWidgetItem(active_text)
                if wf.is_active:
                    item.setForeground(Qt.GlobalColor.darkGreen)
                self._table.setItem(row, 3, item)
        finally:
            session.close()

    def _get_selected_workflow_id(self) -> int | None:
        """현재 선택된 워크플로우의 ID 를 반환합니다."""
        row = self._table.currentRow()
        if row < 0:
            return None
        # 이름으로 조회 (이름은 고유하지 않을 수 있으나 실용적으로 충분)
        name = self._table.item(row, 0).text()
        session = get_session()
        try:
            wf = session.query(ApprovalWorkflow).filter_by(name=name).first()
            return wf.id if wf else None
        finally:
            session.close()

    def _on_activate(self):
        """선택한 워크플로우를 활성화합니다."""
        wf_id = self._get_selected_workflow_id()
        if wf_id is None:
            QMessageBox.warning(self, "선택 필요", "활성화할 워크플로우를 먼저 선택하세요.")
            return

        session = get_session()
        try:
            # 기존 활성 워크플로우 비활성화
            session.query(ApprovalWorkflow).filter_by(is_active=True).update(
                {"is_active": False}, synchronize_session="evaluate"
            )
            # 대상 활성화
            wf = session.get(ApprovalWorkflow, wf_id)
            wf.is_active = True
            session.commit()
            QMessageBox.information(self, "활성화 완료", f"'{wf.name}' 워크플로우가 활성화되었습니다.")
        finally:
            session.close()
        self._load_data()

    def _on_delete(self):
        """선택한 워크플로우를 삭제합니다."""
        wf_id = self._get_selected_workflow_id()
        if wf_id is None:
            QMessageBox.warning(self, "선택 필요", "삭제할 워크플로우를 먼저 선택하세요.")
            return

        session = get_session()
        try:
            wf = session.get(ApprovalWorkflow, wf_id)
            if wf.is_active:
                QMessageBox.warning(self, "삭제 불가",
                                     "활성화된 워크플로우는 삭제할 수 없습니다.\n"
                                     "먼저 다른 워크플로우를 활성화한 후 다시 시도하세요.")
                return

            reply = QMessageBox.question(
                self, "삭제 확인",
                f"'{wf.name}' 워크플로우를 삭제하시겠습니까?\n"
                f"포함된 {len(wf.steps)}개 단계도 함께 삭제됩니다.",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            )
            if reply == QMessageBox.StandardButton.Yes:
                session.delete(wf)  # cascade 로 steps 도 삭제
                session.commit()
        finally:
            session.close()
        self._load_data()

    def _on_new(self):
        """새 워크플로우 생성 다이얼로그를 엽니다."""
        dlg = WorkflowEditDialog(self)
        if dlg.exec() == QDialog.DialogCode.Accepted:
            self._load_data()


class WorkflowEditDialog(QDialog):
    """워크플로우 생성/편집 다이얼로그."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("새 워크플로우 생성")
        self.setMinimumSize(550, 480)
        self._init_ui()

    def _init_ui(self):
        layout = QVBoxLayout(self)
        layout.setSpacing(12)

        # ── 기본 정보 ──────────────────────────────────────────────
        form = QFormLayout()
        self._edit_name = QLineEdit()
        self._edit_name.setPlaceholderText("예: 기본 2단계 결재, 3단계 결재")
        form.addRow("워크플로우 이름:", self._edit_name)

        self._edit_desc = QLineEdit()
        self._edit_desc.setPlaceholderText("예: 일과계 1차 승인 → 교감 최종 승인")
        form.addRow("설명:", self._edit_desc)
        layout.addLayout(form)

        # ── 단계 목록 ──────────────────────────────────────────────
        step_header = QHBoxLayout()
        step_header.addWidget(QLabel("결재 단계 목록"))
        step_header.addStretch()

        btn_add_step = QPushButton("+ 단계 추가")
        btn_add_step.setStyleSheet(BTN_PRIMARY)
        btn_add_step.clicked.connect(self._add_step)
        step_header.addWidget(btn_add_step)
        layout.addLayout(step_header)

        self._step_table = QTableWidget(0, 3)
        self._step_table.setHorizontalHeaderLabels(["순서", "승인 역할", "단계 이름"])
        self._step_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Fixed)
        self._step_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        self._step_table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        self._step_table.setColumnWidth(0, 60)
        self._step_table.setStyleSheet(
            "QHeaderView::section { background:#1B4F8A; color:white; padding:4px; }"
        )
        layout.addWidget(self._step_table)

        btn_remove_step = QPushButton("선택 단계 삭제")
        btn_remove_step.setStyleSheet(BTN_DANGER)
        btn_remove_step.clicked.connect(self._remove_step)
        layout.addWidget(btn_remove_step)

        # 기본 단계 2개 추가 (2단계 결재)
        self._add_step_row("admin", "1차 승인 (일과계)")
        self._add_step_row("vice_principal", "최종 승인 (교감)")

        # ── 활성화 체크박스 ─────────────────────────────────────────
        layout.addSpacing(4)

        # ── 확인/취소 버튼 ─────────────────────────────────────────
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self._on_save)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def _add_step_row(self, role: str = "admin", step_name: str = ""):
        """단계 테이블에 한 행을 추가합니다."""
        row = self._step_table.rowCount()
        self._step_table.insertRow(row)

        # 순서 (1부터 자동)
        order_item = QTableWidgetItem(str(row + 1))
        order_item.setFlags(order_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
        self._step_table.setItem(row, 0, order_item)

        # 역할 콤보박스
        cb = QComboBox()
        for display in APPROVER_ROLES:
            cb.addItem(display)
        if role in ROLE_VALUES.values():
            display = ROLE_DISPLAY.get(role, APPROVER_ROLES[0])
            cb.setCurrentText(display)
        self._step_table.setCellWidget(row, 1, cb)

        # 단계 이름
        name_item = QTableWidgetItem(step_name)
        self._step_table.setItem(row, 2, name_item)

    def _add_step(self):
        self._add_step_row("admin", "")
        self._renumber_steps()

    def _remove_step(self):
        row = self._step_table.currentRow()
        if row < 0:
            QMessageBox.warning(self, "선택 필요", "삭제할 단계를 선택하세요.")
            return
        if self._step_table.rowCount() <= 1:
            QMessageBox.warning(self, "최소 1단계", "결재 단계는 최소 1개 이상이어야 합니다.")
            return
        self._step_table.removeRow(row)
        self._renumber_steps()

    def _renumber_steps(self):
        """모든 행의 순서 번호를 1부터 다시 매깁니다."""
        for row in range(self._step_table.rowCount()):
            self._step_table.item(row, 0).setText(str(row + 1))

    def _on_save(self):
        """워크플로우를 DB 에 저장합니다."""
        name = self._edit_name.text().strip()
        if not name:
            QMessageBox.warning(self, "입력 필요", "워크플로우 이름을 입력하세요.")
            return

        # 단계 정보 수집
        steps = []
        for row in range(self._step_table.rowCount()):
            cb = self._step_table.cellWidget(row, 1)
            role_display = cb.currentText() if cb else APPROVER_ROLES[0]
            role_value = ROLE_VALUES.get(role_display, "admin")
            step_name = self._step_table.item(row, 2).text().strip()
            if not step_name:
                QMessageBox.warning(self, "입력 필요", f"{row + 1}단계의 이름을 입력하세요.")
                return
            steps.append({
                "step_order": row + 1,
                "role_required": role_value,
                "step_name": step_name,
            })

        # DB 저장
        session = get_session()
        try:
            wf = ApprovalWorkflow(
                name=name,
                description=self._edit_desc.text().strip(),
                is_active=False,  # 새 워크플로우는 비활성 상태로 생성
            )
            session.add(wf)
            session.flush()

            for s in steps:
                step = ApprovalStep(
                    workflow_id=wf.id,
                    step_order=s["step_order"],
                    role_required=s["role_required"],
                    step_name=s["step_name"],
                )
                session.add(step)

            session.commit()
            QMessageBox.information(self, "생성 완료",
                                     f"'{name}' 워크플로우가 생성되었습니다.\n"
                                     "사용하려면 목록에서 선택 후 '활성화' 버튼을 클릭하세요.")
        except Exception as e:
            session.rollback()
            QMessageBox.critical(self, "오류", f"워크플로우 생성 중 오류가 발생했습니다:\n{e}")
            return
        finally:
            session.close()

        self.accept()
