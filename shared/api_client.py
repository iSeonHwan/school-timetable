"""
HTTP + WebSocket API 클라이언트

admin_app 과 teacher_app 이 FastAPI 서버와 통신하기 위해 사용합니다.
httpx 를 동기 모드로 사용하므로 PyQt6 UI 스레드에서 직접 호출하면
블로킹이 발생합니다. 반드시 QThread 안에서 호출하세요.

사용 예:
    client = ApiClient("http://192.168.1.10:8000")
    client.login("admin", "password")
    terms = client.get("/terms")
"""
from __future__ import annotations
import json
from typing import Any, Optional
import httpx
import websocket  # websocket-client 패키지


class ApiError(Exception):
    """서버가 4xx / 5xx 를 반환했을 때 발생합니다."""
    def __init__(self, status_code: int, detail: str):
        self.status_code = status_code
        self.detail = detail
        super().__init__(f"[{status_code}] {detail}")


class ApiClient:
    """
    FastAPI 서버와 통신하는 동기 HTTP 클라이언트.

    ※ 블로킹 주의: get/post/patch/delete 메서드는 모두 네트워크 응답을
    기다리는 동기 호출입니다. PyQt6 UI 스레드에서 직접 호출하면 앱이
    응답 없음(freezing) 상태가 됩니다. 반드시 QThread 서브클래스의
    run() 메서드 안에서 호출하세요. (예: _SubmitWorker, _LoadWorker)

    Args:
        base_url: 서버 주소 (예: "http://192.168.1.10:8000")
        timeout : 요청 타임아웃 (초). 기본 10초.
    """

    def __init__(self, base_url: str, timeout: float = 10.0):
        self.base_url = base_url.rstrip("/")
        self._token: Optional[str] = None
        self._role: Optional[str] = None
        self._user_id: Optional[int] = None
        self._teacher_id: Optional[int] = None
        self._http = httpx.Client(base_url=self.base_url, timeout=timeout)

    # ── 인증 ─────────────────────────────────────────────────────────────

    def login(self, username: str, password: str) -> dict:
        """
        로그인하고 JWT 토큰을 내부에 저장합니다.
        Returns: TokenResponse 딕셔너리
        Raises: ApiError (자격 증명 오류 시)
        """
        resp = self._http.post("/auth/login", json={"username": username, "password": password})
        self._raise_for_status(resp)
        data = resp.json()
        self._token = data["access_token"]
        self._role = data["role"]
        self._user_id = data["user_id"]
        self._teacher_id = data.get("teacher_id")
        # 이후 모든 요청에 Authorization 헤더 자동 첨부
        self._http.headers.update({"Authorization": f"Bearer {self._token}"})
        return data

    def logout(self):
        """토큰을 삭제하고 Authorization 헤더를 제거합니다."""
        self._token = None
        self._role = None
        self._user_id = None
        self._teacher_id = None
        self._http.headers.pop("Authorization", None)

    @property
    def is_logged_in(self) -> bool:
        return self._token is not None

    @property
    def role(self) -> Optional[str]:
        return self._role

    @property
    def teacher_id(self) -> Optional[int]:
        return self._teacher_id

    # ── 범용 HTTP 메서드 ──────────────────────────────────────────────────

    def get(self, path: str, **params) -> Any:
        resp = self._http.get(path, params=params)
        self._raise_for_status(resp)
        return resp.json()

    def post(self, path: str, body: dict) -> Any:
        resp = self._http.post(path, json=body)
        self._raise_for_status(resp)
        return resp.json()

    def patch(self, path: str, body: dict) -> Any:
        resp = self._http.patch(path, json=body)
        self._raise_for_status(resp)
        return resp.json()

    def delete(self, path: str) -> Any:
        resp = self._http.delete(path)
        self._raise_for_status(resp)
        return resp.json() if resp.content else {}

    # ── WebSocket (채팅) ──────────────────────────────────────────────────

    def connect_chat(
        self,
        on_message,
        on_error=None,
        on_close=None,
    ) -> websocket.WebSocketApp:
        """
        채팅용 WebSocket 연결을 생성하고 반환합니다.
        실제 연결(run_forever)은 호출자가 별도 스레드에서 실행해야 합니다.

        Args:
            on_message: 메시지 수신 콜백 (ws, message_str)
            on_error  : 오류 콜백 (ws, error)
            on_close  : 연결 종료 콜백 (ws, close_status, close_msg)

        Returns:
            websocket.WebSocketApp 인스턴스
        """
        ws_url = self.base_url.replace("http://", "ws://").replace("https://", "wss://")
        ws_url = f"{ws_url}/chat/ws?token={self._token}"
        return websocket.WebSocketApp(
            ws_url,
            on_message=on_message,
            on_error=on_error,
            on_close=on_close,
        )

    def send_chat(self, ws_app: websocket.WebSocketApp, content: str, is_announcement: bool = False):
        """WebSocket 을 통해 채팅 메시지를 전송합니다."""
        payload = json.dumps({
            "type": "chat",
            "payload": {"content": content, "is_announcement": is_announcement},
        })
        ws_app.send(payload)

    # ── 내부 유틸 ─────────────────────────────────────────────────────────

    @staticmethod
    def _raise_for_status(resp: httpx.Response):
        if resp.status_code >= 400:
            try:
                detail = resp.json().get("detail", resp.text)
            except Exception:
                detail = resp.text
            raise ApiError(resp.status_code, detail)

    def close(self):
        """HTTP 클라이언트 연결을 닫습니다. 앱 종료 시 호출하세요."""
        self._http.close()
