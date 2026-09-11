import hashlib
import hmac
import secrets
import sqlite3
from pathlib import Path

from .moderation import ModerationMixin

RETENTION_SECONDS = 24 * 60 * 60


class Database(ModerationMixin):
    def __init__(self, path: str | Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)

        self.connection = sqlite3.connect(self.path, check_same_thread=False)
        self.connection.row_factory = sqlite3.Row
        self.connection.execute("PRAGMA foreign_keys = ON")

        schema = Path(__file__).with_name("schema.sql").read_text()
        self.connection.executescript(schema)
        self.connection.commit()
        self.migrate_legacy_channels()

    def close(self):
        self.connection.close()

    def get_expired_attachments(self, now: int) -> list[sqlite3.Row]:
        cutoff = now - RETENTION_SECONDS

        return self.connection.execute(
            """
            SELECT *
            FROM attachments
            WHERE uploaded_at < ?
            """,
            (cutoff,),
        ).fetchall()

    def delete_messages_before(self, timestamp: int) -> None:
        self.connection.execute(
            "DELETE FROM messages WHERE created_at < ?",
            (timestamp,),
        )

    def delete_attachments(self, attachment_ids: list[int]) -> None:
        self.connection.executemany(
            "DELETE FROM attachments WHERE id = ?",
            ((attachment_id,) for attachment_id in attachment_ids),
        )

    def prune(self, now: int) -> list[sqlite3.Row]:
        cutoff = now - RETENTION_SECONDS

        attachments = self.get_expired_attachments(now)

        self.delete_messages_before(cutoff)
        self.delete_attachments([attachment["id"] for attachment in attachments])

        self.connection.commit()

        return attachments

    def get_channel(self, channel_id: int):
        return self.connection.execute(
            """
            SELECT *
            FROM channels
            WHERE id = ?
            """,
            (channel_id,),
        ).fetchone()

    def check_channel_owner(self, channel_id: int, password: str) -> bool:
        channel = self.get_channel(channel_id)

        if channel is None:
            return False

        return self._check_password(
            password,
            channel["owner_password_hash"],
        )

    def get_user(self, user_id: int):
        return self.connection.execute(
            """
            SELECT *
            FROM users
            WHERE id = ?
            """,
            (user_id,),
        ).fetchone()

    def get_attachment(self, attachment_id: int):
        return self.connection.execute(
            """
            SELECT *
            FROM attachments
            WHERE id = ?
            """,
            (attachment_id,),
        ).fetchone()

    def get_message(self, message_id: int):
        return self.connection.execute(
            """
            SELECT *
            FROM messages
            WHERE id = ?
            """,
            (message_id,),
        ).fetchone()

    def get_channel_messages(self, channel_id: int):
        return self.connection.execute(
            """
            SELECT *
            FROM messages
            WHERE channel_id = ?
            ORDER BY created_at ASC, id ASC
            """,
            (channel_id,),
        ).fetchall()

    def get_channel_messages_before(
        self, channel_id: int, before_id: int, limit: int = 200
    ):
        return self.connection.execute(
            """
            SELECT m.*, u.last_nickname AS nickname
            FROM messages m
            JOIN users u ON u.id = m.author_id
            WHERE m.channel_id = ? AND m.id < ?
            ORDER BY m.created_at ASC, m.id ASC
            LIMIT ?
            """,
            (channel_id, before_id, limit),
        ).fetchall()

    def get_channel_messages_after(
        self, channel_id: int, after_id: int, limit: int = 50
    ):
        return self.connection.execute(
            """
            SELECT m.*, u.last_nickname AS nickname
            FROM messages m
            JOIN users u ON u.id = m.author_id
            WHERE m.channel_id = ? AND m.id > ?
            ORDER BY m.created_at ASC, m.id ASC
            LIMIT ?
            """,
            (channel_id, after_id, limit),
        ).fetchall()

    def get_recent_channel_messages(self, channel_id: int, limit: int = 50):
        return self.connection.execute(
            """
            SELECT m.*, u.last_nickname AS nickname
            FROM messages m
            JOIN users u ON u.id = m.author_id
            WHERE m.channel_id = ?
            ORDER BY m.created_at DESC, m.id DESC
            LIMIT ?
            """,
            (channel_id, limit),
        ).fetchall()[::-1]

    def list_channels(self):
        return self.connection.execute(
            "SELECT * FROM channels ORDER BY name ASC"
        ).fetchall()

    def get_channel_by_name(self, name: str):
        return self.connection.execute(
            "SELECT * FROM channels WHERE name = ?", (name,)
        ).fetchone()

    def ensure_channel(self, name: str) -> sqlite3.Row:
        existing = self.get_channel_by_name(name)
        if existing:
            return existing
        cur = self.connection.execute(
            "INSERT INTO channels (name, owner_password_hash) VALUES (?, NULL)", (name,)
        )
        self.connection.commit()
        return self.get_channel(cur.lastrowid)

    def resolve_user(self, user_id: int | None, ip: str):
        """Return the user row only if the id exists AND the IP matches.

        Unknown ids or IP mismatches (seizure attempts) resolve to None so
        callers assign a fresh id instead of seizing someone else's.
        """
        if user_id is None:
            return None
        row = self.get_user(user_id)
        if row is None or (ip != "?" and row["last_ip"] not in ("?", ip)):
            return None
        return row

    def upsert_user(
        self, user_id: int | None, nickname: str, ip: str, now: int
    ) -> sqlite3.Row:
        if user_id is not None:
            row = self.get_user(user_id)
            if row is not None:
                self.connection.execute(
                    "UPDATE users SET last_nickname=?, last_ip=?, last_seen=? WHERE id=?",
                    (nickname, ip, now, user_id),
                )
                self.connection.commit()
                return self.get_user(user_id)
        cur = self.connection.execute(
            "INSERT INTO users (last_nickname, last_ip, last_seen) VALUES (?, ?, ?)",
            (nickname, ip, now),
        )
        self.connection.commit()
        return self.get_user(cur.lastrowid)

    def create_message(
        self,
        channel_id: int,
        author_id: int,
        content: str,
        attachment_id: int | None,
        now: int,
    ) -> sqlite3.Row:
        cur = self.connection.execute(
            """INSERT INTO messages (channel_id, author_id, content, attachment_id, created_at)
               VALUES (?, ?, ?, ?, ?)""",
            (channel_id, author_id, content, attachment_id, now),
        )
        self.connection.commit()
        return self.get_message(cur.lastrowid)

    def create_attachment(
        self, filename: str, mime: str, location: str, size: int, now: int
    ) -> sqlite3.Row:
        cur = self.connection.execute(
            """INSERT INTO attachments (filename, mime_type, uploaded_at, location, size)
               VALUES (?, ?, ?, ?, ?)""",
            (filename, mime, now, location, size),
        )
        self.connection.commit()
        return self.get_attachment(cur.lastrowid)

    def user_storage_bytes(self, now: int, user_id: int) -> int:
        cutoff = now - RETENTION_SECONDS
        row = self.connection.execute(
            """SELECT COALESCE(SUM(a.size),0) AS total FROM attachments a
               JOIN messages m ON m.attachment_id = a.id
               WHERE m.author_id = ? AND a.uploaded_at >= ?""",
            (user_id, cutoff),
        ).fetchone()
        return row["total"] if row else 0

    def total_storage_bytes(self, now: int) -> int:
        cutoff = now - RETENTION_SECONDS
        row = self.connection.execute(
            "SELECT COALESCE(SUM(size),0) AS total FROM attachments WHERE uploaded_at >= ?",
            (cutoff,),
        ).fetchone()
        return row["total"] if row else 0

    @staticmethod
    def hash_password(password: str) -> str:
        salt = secrets.token_bytes(16)
        digest = hashlib.scrypt(
            password.encode(),
            salt=salt,
            n=2**14,
            r=8,
            p=1,
        )

        return f"scrypt${salt.hex()}${digest.hex()}"

    @staticmethod
    def _check_password(password: str, stored: str | None) -> bool:
        if not stored:
            return False

        try:
            algorithm, salt_hex, digest_hex = stored.split("$", 2)

            if algorithm != "scrypt":
                return False

            salt = bytes.fromhex(salt_hex)
            expected = bytes.fromhex(digest_hex)

            actual = hashlib.scrypt(
                password.encode(),
                salt=salt,
                n=2**14,
                r=8,
                p=1,
            )

            return hmac.compare_digest(actual, expected)
        except ValueError, TypeError:
            return False
