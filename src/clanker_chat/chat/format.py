"""Render chat message bodies: escape, #channel links, @mentions."""

import html
import re

CHANNEL_RE = re.compile(r"#([A-Za-z0-9_\-]{1,32})")
MENTION_RE = re.compile(r"@([A-Za-z0-9_\-]{1,32})")


def valid_name(name: str) -> str | None:
    name = (name or "").strip().lstrip("#@")[:32]
    if not name or not re.fullmatch(r"[A-Za-z0-9_\-]+", name):
        return None
    return name


def render_body(raw: str, members: set[str] | None = None) -> str:
    """Escape HTML then linkify #channels and highlight @mentions.

    members: lowercase nicknames present in channel (for highlight class).
    """
    members = members or set()
    esc = html.escape(raw or "")

    def chan(m: re.Match) -> str:
        name = m.group(1)
        return f'<a class="chan" href="/c/{name}">#{name}</a>'

    def ment(m: re.Match) -> str:
        name = m.group(1)
        cls = "mention hi" if name.lower() in members else "mention"
        return f'<span class="{cls}">@{name}</span>'

    esc = CHANNEL_RE.sub(chan, esc)
    esc = MENTION_RE.sub(ment, esc)
    return esc.replace("\n", "<br>")


def nick_color(nickname: str) -> str:
    """Deterministic ANSI palette slot 1..7 for a nickname."""
    palette = ["red", "green", "yellow", "blue", "magenta", "cyan", "white"]
    return palette[abs(hash(nickname)) % len(palette)]
