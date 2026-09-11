"""HTML fragments for messages, pills, and icons."""

import time
from html import escape

from ..attachments.store import guess_icon
from ..icons import PATHS
from .format import nick_color, render_body


def icon(key: str) -> str:
    return f'<svg viewBox="0 0 24 24" aria-hidden="true"><path d="{PATHS[key]}"/></svg>'


def enrich(db, cache, channel: str, row) -> dict:
    members = set(cache.channel_nicknames(channel))
    att = db.get_attachment(row["attachment_id"]) if row["attachment_id"] else None
    nick = row["nickname"] if "nickname" in row.keys() else "?"  # noqa: SIM118 (Row has no .get)
    return {
        "id": row["id"],
        "nickname": nick,
        "color": nick_color(nick),
        "body": render_body(row["content"], members),
        "created": row["created_at"],
        "attachment": dict(att)
        | {"icon": guess_icon(att["mime_type"], att["filename"])}
        if att
        else None,
    }


def message_html(db, cache, channel: str, row) -> str:
    m = enrich(db, cache, channel, row)
    att = ""
    if m["attachment"]:
        a = m["attachment"]
        att = (
            f'<a class="att att-{a["icon"]}" href="/attachments/{a["id"]}">'
            f"{icon(a['icon'])}"
            f"<span>{a['filename']}</span></a>"
        )
    return (
        f'<article class="msg" data-mid="{m["id"]}">'
        f'<span class="ts">{time.strftime("%H:%M", time.localtime(m["created"]))}</span>'
        f'<span class="nick c-{m["color"]}">&lt;{escape(m["nickname"])}&gt;</span>'
        f'<span class="body">{m["body"]}{att}</span></article>'
    )


def channel_pill(
    name: str, *, locked: bool, here: bool = False, uid: str | int = "", badge: int = 0
) -> str:
    lock = icon("lock") if locked else ""
    cls = "pill" + (" here" if here else "")
    b = f' <b class="badge">{badge}</b>' if badge else ""
    return f'<a class="{cls}" href="/c/{name}?uid={uid}">{lock}#{name}{b}</a>'


def channel_fill_pill(name: str, *, locked: bool) -> str:
    """Landing page: clicking fills the join form instead of navigating."""
    lock = icon("lock") if locked else ""
    return f'<button type="button" class="pill" onclick="fillChannel(\'{name}\')">{lock}#{name}</button>'
