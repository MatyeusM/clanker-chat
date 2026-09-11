import os
from dataclasses import dataclass


@dataclass(frozen=True)
class Settings:
    db_path: str = "data/chat.sqlite3"
    attachment_dir: str = "data/attachments"
    max_bytes_per_user: int = 5 * 1024 * 1024
    max_bytes_total: int = 250 * 1024 * 1024


def load_settings() -> Settings:
    return Settings(
        db_path=os.environ.get("CHAT_DB_PATH", "data/chat.sqlite3"),
        attachment_dir=os.environ.get("CHAT_ATTACH_DIR", "data/attachments"),
        max_bytes_per_user=int(os.environ.get("CHAT_MAX_USER_MB", "5")) * 1024 * 1024,
        max_bytes_total=int(os.environ.get("CHAT_MAX_TOTAL_MB", "250")) * 1024 * 1024,
    )
