"""
알림 패널

교사가 받은 실시간 알림 목록을 표시하고, 피교사 동의(consent) 요청을
승인/거절할 수 있는 위젯입니다.

사용 위치:
  - TeacherMainWindow 의 상단 벨 아이콘 클릭 시 다이얼로그로 표시
  - WebSocket 으로 notification 이벤트 수신 시 목록과 읽지 않은 개수를 갱신

알림 유형(type):
  - consent_request   : 다른 교사가 본인에게 교체/교환을 요청함
  - consent_approved  : 피교사가 동의함
  - consent_rejected  : 피교사가 거절함
  - status_update     : 변경 신청 상태 변화
  - approved          : 변경 신청 최종 승인
  - rejected          : 변경 신청 최종 거절

2026-06-20 변경 (연쇄 교체 지원):
  - 연쇄 교체 신청의 경우 한 알림이 여러 단계(step) 중 하나에 대한 동의 요청.
  - Notification 스키마는 step_id 를 직접 담지 않으므로, 동의/거절 버튼 클릭 시
    먼저 GET /timetable/requests 로 해당 신청을 조회해 본인(teacher_id)이
    affected_teacher_id 인 pending 단계를 찾아 step_id 로 전달합니다.
  - 단일 신청(기존 방식)은 step_id 없이 처리되어 하위 호환성 유지.
"""
from __future__ import annotations
from datetime import datetime
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel,
    QPushButton, QListWidget, QListWidgetItem,
    QMessageBox, QTextEdit,
)
from PyQt6.QtCore import Qt, QThread, pyqtSignal
from PyQt6.QtGui import QFont, QColor
from shared.api_client import ApiClient, ApiError


class _LoadNotificationsWorker(QThread):
    """GET /notifications 를 비동기로 조회하는 워커."""
    done = pyqtSignal(list)
    error = pyqtSignal(str)

    def __init__(self, client: ApiClient):
        super().__init__()
        self._client = client

    def run(self):
        try:
            rows = self._client.get("/notifications")
            self.done.emit(rows)
        except ApiError as e:
            self.error.emit(e.detail)
        except Exception as e:
            self.error.emit(str(e))


class _ResolveStepWorker(QThread):
    """
    동의/거절 클릭 시 본인에게 해당하는 단계(step_id)를 찾기 위한 워커.

    연쇄 교체 신청의 경우 Notification 은 step_id 를 직접 가지지 않으므로,
    GET /timetable/requests 에서 해당 change_request_id 의 신청을 찾아
    steps 배열 중 affected_teacher_id == client.teacher_id 이고
    consent_status == "pending" 인 단계를 선택합니다.

    찾은 step_id 를 done 시그널과 함께 전달합니다.
    단일 신청(steps 가 빈 리스트)이면 step_id = None 을 전달하여
    서버가 기존 단일 동의 로직으로 처리하도록 합니다.
    """
    done = pyqtSignal(int, object)  # (notification_id, step_id or None)
    error = pyqtSignal(int, str)    # (notification_id, message)

    def __init__(self, client: ApiClient, change_request_id: int,
                 teacher_id: int, notification_id: int):
        super().__init__()
        self._client = client
        self._request_id = change_request_id
        self._teacher_id = teacher_id
        self._notification_id = notification_id

    def run(self):
        try:
            # 서버의 GET /timetable/requests 는 모든 신청을 반환.
            # 클라이언트에서 id 일치 항목을 찾아 단계를 확인합니다.
            requests = self._client.get("/timetable/requests")
            target_req = None
            for r in requests:
                if r.get("id") == self._request_id:
                    target_req = r
                    break

            if target_req is None:
                # 신청이 삭제되었거나 알림이 오래된 경우
                self.error.emit(
                    self._notification_id,
                    f"변경 신청(id={self._request_id})을 찾을 수 없습니다. "
                    "이미 처리되었거나 취소되었을 수 있습니다.",
                )
                return

            steps = target_req.get("steps") or []
            if not steps:
                # 단일 신청 — step_id 없이 처리
                self.done.emit(self._notification_id, None)
                return

            # 본인이 affected_teacher 이고 동의 대기 중인 단계 찾기
            # (동의 완료/거절된 단계는 다시 응답할 수 없음)
            matching_step_id = None
            for step in steps:
                if (
                    step.get("affected_teacher_id") == self._teacher_id
                    and step.get("consent_status") == "pending"
                ):
                    matching_step_id = step.get("id")
                    break

            if matching_step_id is None:
                # 단계가 이미 처리되었거나 본인이 관련 단계가 아님
                self.error.emit(
                    self._notification_id,
                    "본인이 동의할 단계를 찾을 수 없습니다. "
                    "이미 동의하셨거나 신청이 취소되었을 수 있습니다.",
                )
                return

            self.done.emit(self._notification_id, matching_step_id)
        except ApiError as e:
            self.error.emit(self._notification_id, e.detail)
        except Exception as e:
            self.error.emit(self._notification_id, str(e))


class _ConsentWorker(QThread):
    """
    PATCH /timetable/requests/{id}/consent 를 비동기로 호출하는 워커.

    2026-06-20 변경:
      - step_id 파라미터 추가. 연쇄 교체 신청의 경우 서버가 특정 단계에 대해
        동의를 처리하도록 step_id 를 본문에 포함합니다.
      - step_id 가 None 이면 기존 단일 신청 동의 로직으로 동작 (하위 호환).
    """
    done = pyqtSignal(dict)
    error = pyqtSignal(str)

    def __init__(self, client: ApiClient, request_id: int, action: str,
                 step_id: int | None = None):
        super().__init__()
        self._client = client
        self._request_id = request_id
        self._action = action
        self._step_id = step_id

    def run(self):
        try:
            body = {"action": self._action}
            if self._step_id is not None:
                body["step_id"] = self._step_id
            result = self._client.patch(
                f"/timetable/requests/{self._request_id}/consent",
                body,
            )
            self.done.emit(result)
        except ApiError as e:
            self.error.emit(e.detail)
        except Exception as e:
            self.error.emit(str(e))


class _MarkReadWorker(QThread):
    """PATCH /notifications/{id} 를 비동기로 호출하는 워커."""
    done = pyqtSignal(int)
    error = pyqtSignal(str)

    def __init__(self, client: ApiClient, notification_id: int, is_read: bool = True):
        super().__init__()
        self._client = client
        self._notification_id = notification_id
        self._is_read = is_read

    def run(self):
        try:
            self._client.patch(f"/notifications/{self._notification_id}", {"is_read": self._is_read})
            self.done.emit(self._notification_id)
        except ApiError as e:
            self.error.emit(e.detail)
        except Exception as e:
            self.error.emit(str(e))


class NotificationPanel(QWidget):
    """
    알림 목록 위젯.

    QListWidget 에 알림을 한 줄씩 표시하며,
    consent_request 타입일 경우 승인/거절 버튼이 포함된 행 위젯을 만듭니다.

    Signals:
        unread_count_changed(int): 읽지 않은 알림 개수가 변경되면 발송됩니다.
    """

    unread_count_changed = pyqtSignal(int)

    def __init__(self, client: ApiClient, parent=None):
        super().__init__(parent)
        self._client = client
        self._worker = None
        self._resolve_worker = None
        self._notifications: list[dict] = []
        # 알림 ID → (동의 버튼, 거절 버튼)
        self._consent_buttons: dict[int, tuple[QPushButton, QPushButton]] = {}
        # 알림 ID → (change_request_id, action) — 단계 찾은 후 이어서 처리
        self._pending_action: dict[int, tuple[int, str]] = {}
        self._init_ui()
        self.refresh()

    def _init_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(10)

        title = QLabel("🔔 알림")
        title.setFont(QFont("", 13, QFont.Weight.Bold))
        layout.addWidget(title)

        self.lbl_count = QLabel("읽지 않은 알림: 0개")
        self.lbl_count.setStyleSheet("color:#C0392B; font-weight:bold;")
        layout.addWidget(self.lbl_count)

        self.list_widget = QListWidget()
        self.list_widget.setSpacing(4)
        layout.addWidget(self.list_widget, stretch=1)

        btn_refresh = QPushButton("새로고침")
        btn_refresh.setStyleSheet(
            "background:#1B4F8A; color:white; border-radius:4px; padding:6px 14px;"
        )
        btn_refresh.clicked.connect(self.refresh)
        layout.addWidget(btn_refresh, alignment=Qt.AlignmentFlag.AlignRight)

    def refresh(self):
        """서버에서 최신 알림 목록을 불러옵니다."""
        self._worker = _LoadNotificationsWorker(self._client)
        self._worker.done.connect(self._populate)
        self._worker.error.connect(lambda m: QMessageBox.warning(self, "알림 조회 오류", m))
        self._worker.start()

    def _populate(self, notifications: list):
        """알림 목록을 UI에 표시합니다."""
        self._notifications = notifications
        self.list_widget.clear()
        self._consent_buttons.clear()

        unread = sum(1 for n in notifications if not n.get("is_read"))
        self.lbl_count.setText(f"읽지 않은 알림: {unread}개")
        self.unread_count_changed.emit(unread)

        if not notifications:
            item = QListWidgetItem("알림이 없습니다.")
            item.setFlags(Qt.ItemFlag.NoItemFlags)
            self.list_widget.addItem(item)
            return

        for notif in notifications:
            widget = self._build_item_widget(notif)
            item = QListWidgetItem()
            # 행 높이를 내용에 맞춰 조금 확보
            item.setSizeHint(widget.sizeHint())
            self.list_widget.addItem(item)
            self.list_widget.setItemWidget(item, widget)

    def _build_item_widget(self, notif: dict) -> QWidget:
        """개별 알림을 표시하는 행 위젯을 만듭니다."""
        container = QWidget()
        layout = QVBoxLayout(container)
        layout.setContentsMargins(8, 6, 8, 6)
        layout.setSpacing(4)

        ntype = notif.get("type", "")
        message = notif.get("message", "")
        is_read = notif.get("is_read", False)
        created_at = notif.get("created_at", "")
        notification_id = notif.get("id", 0)
        change_request_id = notif.get("change_request_id")

        # 상단: 유형 + 시간
        header = QHBoxLayout()
        type_label = QLabel(self._type_label(ntype))
        type_label.setFont(QFont("", 10, QFont.Weight.Bold))
        type_colors = {
            "consent_request": "#E74C3C",
            "consent_approved": "#27AE60",
            "consent_rejected": "#7F8C8D",
            "approved": "#27AE60",
            "rejected": "#C0392B",
        }
        type_label.setStyleSheet(f"color:{type_colors.get(ntype, '#1B4F8A')}; margin-right:8px;")
        header.addWidget(type_label)

        time_str = self._format_time(created_at)
        if time_str:
            header.addWidget(QLabel(f"<span style='color:#999; font-size:10px;'>{time_str}</span>"))
        header.addStretch()

        if not is_read:
            badge = QLabel("●")
            badge.setStyleSheet("color:#E74C3C; font-size:10px;")
            badge.setToolTip("읽지 않음")
            header.addWidget(badge)

        layout.addLayout(header)

        # 본문 메시지
        msg_label = QLabel(message)
        msg_label.setWordWrap(True)
        msg_label.setStyleSheet("font-size:12px; color:#2C3E50;")
        layout.addWidget(msg_label)

        # consent_request 일 경우 승인/거절 버튼 추가
        # 연쇄 교체인 경우 단계(step_id)를 먼저 찾은 뒤 동의 요청을 전송합니다.
        if ntype == "consent_request" and change_request_id:
            btn_row = QHBoxLayout()
            btn_row.addStretch()

            btn_approve = QPushButton("동의")
            btn_approve.setStyleSheet(
                "background:#27AE60; color:white; border-radius:3px; padding:4px 12px; font-size:11px;"
            )
            btn_approve.clicked.connect(
                lambda _, rid=change_request_id, nid=notification_id:
                self._respond_consent(rid, "approve", nid)
            )
            btn_row.addWidget(btn_approve)

            btn_reject = QPushButton("거절")
            btn_reject.setStyleSheet(
                "background:#C0392B; color:white; border-radius:3px; padding:4px 12px; font-size:11px;"
            )
            btn_reject.clicked.connect(
                lambda _, rid=change_request_id, nid=notification_id:
                self._respond_consent(rid, "reject", nid)
            )
            btn_row.addWidget(btn_reject)

            layout.addLayout(btn_row)
            self._consent_buttons[notification_id] = (btn_approve, btn_reject)

        # 배경색: 읽음/안읽음
        if is_read:
            container.setStyleSheet("background:#F8F9FA; border-bottom:1px solid #E5E7E9;")
        else:
            container.setStyleSheet("background:#FFF9E6; border-bottom:1px solid #FAD7A0;")

        return container

    def _respond_consent(self, request_id: int, action: str, notification_id: int):
        """
        피교사 동의(승인/거절) 처리를 시작합니다.

        연쇄 교체 신청인 경우 먼저 _ResolveStepWorker 로 본인 단계(step_id)를
        찾은 뒤 _ConsentWorker 를 호출합니다. 단일 신청은 step_id=None 으로
        바로 _ConsentWorker 를 호출합니다.

        진행 중 버튼 중복 클릭을 방지하기 위해 두 버튼을 모두 비활성화합니다.
        """
        # 버튼 중복 클릭 방지
        buttons = self._consent_buttons.get(notification_id)
        if buttons:
            buttons[0].setEnabled(False)
            buttons[1].setEnabled(False)

        # 본인 teacher_id 가 없는 경우 (예: 관리자 계정으로 교사 알림을 볼 때)
        # 즉시 오류 처리
        teacher_id = self._client.teacher_id
        if teacher_id is None:
            QMessageBox.warning(
                self, "처리 불가",
                "현재 계정에 연결된 교사 정보가 없어 동의 처리를 할 수 없습니다.",
            )
            if buttons:
                buttons[0].setEnabled(True)
                buttons[1].setEnabled(True)
            return

        # 다음 단계(단계 찾기 → 동의 제출)에서 사용할 액션 보관
        self._pending_action[notification_id] = (request_id, action)

        # 연쇄 교체 여부 확인을 위해 신청 정보 조회
        self._resolve_worker = _ResolveStepWorker(
            self._client, request_id, teacher_id, notification_id,
        )
        self._resolve_worker.done.connect(self._on_step_resolved)
        self._resolve_worker.error.connect(self._on_resolve_error)
        self._resolve_worker.start()

    def _on_step_resolved(self, notification_id: int, step_id):
        """
        단계 조회 완료 후 실제 동의/거절 API 호출을 진행합니다.

        step_id 가 None 이면 단일 신청 — 기존 로직과 동일하게 처리.
        step_id 가 int 이면 연쇄 교체의 특정 단계에 대한 동의.
        """
        pending = self._pending_action.pop(notification_id, None)
        if pending is None:
            # 비정상 상황 — 보관된 액션이 없으면 버튼 복구 후 종료
            self._restore_buttons(notification_id)
            return

        request_id, action = pending
        self._worker = _ConsentWorker(
            self._client, request_id, action, step_id=step_id,
        )
        self._worker.done.connect(
            lambda _, nid=notification_id: self._on_consent_done(action, nid)
        )
        self._worker.error.connect(
            lambda m, nid=notification_id: self._on_consent_error(m, nid)
        )
        self._worker.start()

    def _on_resolve_error(self, notification_id: int, message: str):
        """단계 조회 실패 시 버튼을 복원하고 에러 메시지를 표시합니다."""
        self._pending_action.pop(notification_id, None)
        self._restore_buttons(notification_id)
        QMessageBox.warning(self, "처리 실패", message)

    def _restore_buttons(self, notification_id: int):
        """알림 행의 동의/거절 버튼을 다시 활성화합니다."""
        buttons = self._consent_buttons.get(notification_id)
        if buttons:
            buttons[0].setEnabled(True)
            buttons[1].setEnabled(True)

    def _on_consent_done(self, action: str, notification_id: int):
        """동의 처리 성공 후 알림을 읽음 처리하고 목록을 갱신합니다."""
        action_text = "동의" if action == "approve" else "거절"
        QMessageBox.information(self, "처리 완료", f"교체 요청을 {action_text}했습니다.")
        self._mark_read(notification_id)

    def _on_consent_error(self, message: str, notification_id: int):
        """동의 처리 실패 시 버튼을 복원합니다."""
        self._restore_buttons(notification_id)
        QMessageBox.critical(self, "처리 실패", message)

    def _mark_read(self, notification_id: int):
        """특정 알림을 읽음 처리합니다."""
        worker = _MarkReadWorker(self._client, notification_id, True)
        worker.done.connect(lambda nid: self.refresh())
        worker.error.connect(lambda m: None)
        worker.start()

    def mark_all_read(self):
        """현재 목록의 모든 안읽은 알림을 읽음 처리합니다."""
        for n in self._notifications:
            if not n.get("is_read"):
                self._mark_read(n["id"])

    @staticmethod
    def _type_label(ntype: str) -> str:
        """알림 유형을 한글로 변환합니다."""
        labels = {
            "consent_request": "동의 요청",
            "consent_approved": "동의 완료",
            "consent_rejected": "동의 거절",
            "status_update": "상태 변경",
            "approved": "승인 완료",
            "rejected": "거절됨",
        }
        return labels.get(ntype, ntype)

    @staticmethod
    def _format_time(created_at) -> str:
        """ISO 시간을 'MM/DD HH:MM' 형식으로 변환합니다."""
        if not created_at:
            return ""
        try:
            dt = datetime.fromisoformat(str(created_at).replace("Z", "+00:00"))
            return dt.strftime("%m/%d %H:%M")
        except (ValueError, TypeError):
            return str(created_at)[:16]