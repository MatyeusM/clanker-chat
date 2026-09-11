"""Attachment disk store with per-user + global quotas, 24h prune."""

import time
from pathlib import Path


class QuotaExceeded(Exception):
    pass


class AttachmentStore:
    def __init__(self, db, directory: str | Path, max_per_user: int, max_total: int):
        self.db = db
        self.dir = Path(
            directory
        ).resolve()  # resolved: prune containment check needs it
        self.dir.mkdir(parents=True, exist_ok=True)
        self.max_per_user = max_per_user
        self.max_total = max_total

    def check_quota(self, user_id: int, size: int, now: int | None = None):
        now = now if now is not None else int(time.time())
        if self.db.user_storage_bytes(now, user_id) + size > self.max_per_user:
            raise QuotaExceeded("per-user quota exceeded (5MB default)")
        if self.db.total_storage_bytes(now) + size > self.max_total:
            raise QuotaExceeded("server quota exceeded (250MB default)")

    def save(
        self,
        user_id: int,
        filename: str,
        mime: str,
        data: bytes,
        now: int | None = None,
    ):
        now = now if now is not None else int(time.time())
        self.check_quota(user_id, len(data), now)
        safe = "".join(c for c in filename if c.isalnum() or c in "._-")[-80:] or "file"
        row = self.db.create_attachment(
            safe, mime or "application/octet-stream", "pending", len(data), now
        )
        dest = self.dir / f"{row['id']}_{safe}"
        dest.write_bytes(data)
        self.db.connection.execute(
            "UPDATE attachments SET location=? WHERE id=?", (str(dest), row["id"])
        )
        self.db.connection.commit()
        return self.db.get_attachment(row["id"])

    def prune_files(self, rows) -> int:
        n = 0
        for r in rows:
            try:
                p = Path(r["location"])
                if p.exists() and self.dir in p.resolve().parents:
                    p.unlink()
                    n += 1
            except OSError:
                continue
        return n


def guess_icon(mime: str, filename: str) -> str:
    """Icon key for the attachment chip (client renders inline SVG)."""
    m = (mime or "").lower()
    ext = (filename or "").rsplit(".", 1)[-1].lower() if "." in (filename or "") else ""
    if m.startswith("image/") or ext in {"png", "jpg", "jpeg", "gif", "webp", "svg"}:
        return "img"
    if m.startswith("audio/") or ext in {"mp3", "wav", "ogg"}:
        return "audio"
    if m.startswith("video/") or ext in {"mp4", "webm", "mkv"}:
        return "video"
    if ext == "pdf" or m == "application/pdf":
        return "pdf"
    if ext in {"zip", "tar", "gz", "7z"}:
        return "zip"
    if ext in {"txt", "md", "log"}:
        return "txt"
    return "file"
