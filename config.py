import json
import os

CONFIG_FILE = os.path.join(os.path.dirname(__file__), "db_config.json")

DEFAULT_CONFIG = {
    "db_type": "sqlite",          # "sqlite" or "postgresql"
    "sqlite_path": "timetable.db",
    "pg_host": "localhost",
    "pg_port": 5432,
    "pg_dbname": "school_timetable",
    "pg_user": "postgres",
    "pg_password": "",
}


def load_config() -> dict:
    if os.path.exists(CONFIG_FILE):
        with open(CONFIG_FILE, "r", encoding="utf-8") as f:
            cfg = json.load(f)
        # fill missing keys with defaults
        for k, v in DEFAULT_CONFIG.items():
            cfg.setdefault(k, v)
        return cfg
    return dict(DEFAULT_CONFIG)


def save_config(cfg: dict) -> None:
    with open(CONFIG_FILE, "w", encoding="utf-8") as f:
        json.dump(cfg, f, ensure_ascii=False, indent=2)


def get_db_url(cfg: dict | None = None) -> str:
    if cfg is None:
        cfg = load_config()
    if cfg["db_type"] == "postgresql":
        return (
            f"postgresql+psycopg2://{cfg['pg_user']}:{cfg['pg_password']}"
            f"@{cfg['pg_host']}:{cfg['pg_port']}/{cfg['pg_dbname']}"
        )
    # default: SQLite
    db_path = cfg.get("sqlite_path", "timetable.db")
    if not os.path.isabs(db_path):
        db_path = os.path.join(os.path.dirname(__file__), db_path)
    return f"sqlite:///{db_path}"
