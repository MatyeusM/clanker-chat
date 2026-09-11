"""Moderation mixin: membership in join order, owner set, passwords.

Owner model: the first user in a channel owns it by default. Anyone holding
the owner password can `!auth` into the owner set. If no owner password is
set, the earliest-joined member counts as owner (chronological fallback).
"""

import sqlite3


class ModerationMixin:
    connection: sqlite3.Connection

    def migrate_legacy_channels(self):
        info = self.connection.execute("PRAGMA table_info(channels)").fetchall()
        cols = {r["name"]: r for r in info}
        if "owner_password_hash" in cols and cols["owner_password_hash"]["notnull"]:
            self.connection.executescript(
                """
                ALTER TABLE channels RENAME TO channels_legacy;
                CREATE TABLE channels (
                    id INTEGER PRIMARY KEY,
                    name TEXT NOT NULL UNIQUE,
                    owner_password_hash TEXT,
                    channel_password_hash TEXT
                );
                INSERT INTO channels (id, name, owner_password_hash, channel_password_hash)
                    SELECT id, name, NULL, channel_password_hash FROM channels_legacy;
                DROP TABLE channels_legacy;
                """
            )
            self.connection.commit()

    # -- membership (chronological join order) --
    def add_member(self, channel_id: int, user_id: int, now: int) -> bool:
        cur = self.connection.execute(
            "INSERT OR IGNORE INTO channel_members (channel_id, user_id, joined_at)"
            " VALUES (?, ?, ?)",
            (channel_id, user_id, now),
        )
        self.connection.commit()
        return cur.rowcount > 0

    def is_member(self, channel_id: int, user_id: int) -> bool:
        return (
            self.connection.execute(
                "SELECT 1 FROM channel_members WHERE channel_id=? AND user_id=?",
                (channel_id, user_id),
            ).fetchone()
            is not None
        )

    def remove_member(self, channel_id: int, user_id: int):
        self.connection.execute(
            "DELETE FROM channel_members WHERE channel_id=? AND user_id=?",
            (channel_id, user_id),
        )
        self.connection.commit()

    def earliest_member(self, channel_id: int):
        return self.connection.execute(
            "SELECT user_id FROM channel_members WHERE channel_id=?"
            " ORDER BY joined_at ASC, rowid ASC LIMIT 1",
            (channel_id,),
        ).fetchone()

    # -- owners --
    def add_owner(self, channel_id: int, user_id: int):
        self.connection.execute(
            "INSERT OR IGNORE INTO channel_owners (channel_id, user_id) VALUES (?, ?)",
            (channel_id, user_id),
        )
        self.connection.commit()

    def owner_ids(self, channel_id: int) -> set[int]:
        return {
            r["user_id"]
            for r in self.connection.execute(
                "SELECT user_id FROM channel_owners WHERE channel_id=?", (channel_id,)
            ).fetchall()
        }

    # -- passwords --
    def owner_password_set(self, channel_row) -> bool:
        return bool(channel_row["owner_password_hash"])

    def channel_locked(self, channel_row) -> bool:
        return bool(channel_row["channel_password_hash"])

    def set_owner_password(self, channel_id: int, password: str | None):
        h = self.hash_password(password) if password else None
        self.connection.execute(
            "UPDATE channels SET owner_password_hash=? WHERE id=?", (h, channel_id)
        )
        self.connection.commit()

    def set_channel_password(self, channel_id: int, password: str | None):
        h = self.hash_password(password) if password else None
        self.connection.execute(
            "UPDATE channels SET channel_password_hash=? WHERE id=?", (h, channel_id)
        )
        self.connection.commit()

    def check_owner_password(self, channel_id: int, password: str) -> bool:
        ch = self.get_channel(channel_id)
        return (
            self._check_password(password, ch["owner_password_hash"]) if ch else False
        )

    def check_channel_password(self, channel_id: int, password: str) -> bool:
        ch = self.get_channel(channel_id)
        if not ch or not ch["channel_password_hash"]:
            return True
        return self._check_password(password, ch["channel_password_hash"])

    def is_owner(self, channel_id: int, user_id: int) -> bool:
        if user_id in self.owner_ids(channel_id):
            return True
        ch = self.get_channel(channel_id)
        if ch and not self.owner_password_set(ch):
            first = self.earliest_member(channel_id)
            if first and first["user_id"] == user_id:
                return True
        return False
