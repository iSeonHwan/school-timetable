"""
DB 연결 설정 관리 모듈

설정은 프로젝트 루트의 db_config.json 파일에 JSON으로 저장됩니다.
파일이 없으면 DEFAULT_CONFIG 값이 사용됩니다(SQLite 로컬 모드).

지원 DB:
  - SQLite  : 별도 서버 없이 단일 파일로 동작. 소규모 / 단독 운용에 적합.
  - PostgreSQL : 여러 PC에서 공유하는 서버형 DB. 네트워크 환경에서 사용.
"""
import json
import os
from urllib.parse import quote_plus

# db_config.json 의 절대 경로 — 이 파일과 같은 디렉터리(프로젝트 루트)에 위치합니다.
CONFIG_FILE = os.path.join(os.path.dirname(__file__), "db_config.json")

DEFAULT_CONFIG = {
    "db_type": "sqlite",            # 기본값: SQLite (로컬 파일)
    "sqlite_path": "timetable.db",  # SQLite 파일명 (상대 경로면 프로젝트 루트 기준)
    "pg_host": "localhost",
    "pg_port": 5432,
    "pg_dbname": "school_timetable",
    "pg_user": "postgres",
    "pg_password": "",
}


def load_config() -> dict:
    """
    db_config.json 을 읽어 설정 딕셔너리를 반환합니다.
    파일이 없으면 DEFAULT_CONFIG 를 그대로 반환합니다.
    파일에 누락된 키가 있으면 기본값으로 채워 반환합니다.
    """
    if os.path.exists(CONFIG_FILE):
        with open(CONFIG_FILE, "r", encoding="utf-8") as f:
            cfg = json.load(f)
        # 기존 설정 파일에 새 키가 추가된 경우 기본값으로 채웁니다.
        for k, v in DEFAULT_CONFIG.items():
            cfg.setdefault(k, v)
        return cfg
    return dict(DEFAULT_CONFIG)


def save_config(cfg: dict) -> None:
    """설정 딕셔너리를 db_config.json 에 저장합니다."""
    with open(CONFIG_FILE, "w", encoding="utf-8") as f:
        json.dump(cfg, f, ensure_ascii=False, indent=2)


def get_db_url(cfg: dict | None = None) -> str:
    """
    설정 딕셔너리로부터 SQLAlchemy 연결 URL 문자열을 생성합니다.

    cfg 가 None 이면 load_config() 를 호출해 자동으로 읽습니다.
    반환 형식:
      SQLite    → "sqlite:////절대/경로/timetable.db"
      PostgreSQL → "postgresql+psycopg2://user:pw@host:port/dbname"
    """
    if cfg is None:
        cfg = load_config()

    if cfg["db_type"] == "postgresql":
        # 비밀번호에 @, :, # 등 특수문자가 포함된 경우 URL이 깨지는 것을 방지합니다.
        pw = quote_plus(cfg["pg_password"])
        return (
            f"postgresql+psycopg2://{cfg['pg_user']}:{pw}"
            f"@{cfg['pg_host']}:{cfg['pg_port']}/{cfg['pg_dbname']}"
        )

    # SQLite: 상대 경로가 주어지면 프로젝트 루트를 기준으로 절대 경로로 변환합니다.
    db_path = cfg.get("sqlite_path", "timetable.db")
    if not os.path.isabs(db_path):
        db_path = os.path.join(os.path.dirname(__file__), db_path)
    return f"sqlite:///{db_path}"
