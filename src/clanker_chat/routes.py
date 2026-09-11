"""HTTP routes: landing, chat, polling fragments, uploads, moderation."""

import html
import time
from pathlib import Path

from starlette.requests import Request
from starlette.responses import (
    FileResponse,
    HTMLResponse,
    RedirectResponse,
    Response,
)
from starlette.templating import Jinja2Templates

from .attachments.store import QuotaExceeded
from .chat.format import valid_name
from .chat.render import channel_fill_pill, channel_pill, message_html
from .commands import err_html, handle_command
from .icons import PATHS

TEMPLATES = Jinja2Templates(directory=str(Path(__file__).parent / "templates"))
HISTORY_N = 10


def now() -> int:
    return int(time.time())


def uid_of(request: Request, form: dict | None = None) -> int | None:
    for src in (
        request.headers.get("x-user-id"),
        request.query_params.get("uid"),
        (form or {}).get("uid") or (form or {}).get("user_id"),
    ):
        try:
            if src is not None and str(src).isdigit():
                return int(src)
        except TypeError, ValueError:
            continue
    return None


def nick_of(request: Request, form: dict | None = None) -> str:
    return (
        (form or {}).get("nickname")
        or request.headers.get("x-nickname", "")
        or request.query_params.get("nick", "")
        or "anon"
    ).strip()[:32] or "anon"


def claim_nick(cache, uid: int, want: str) -> str:
    """Validated + unique nick for explicit identity changes (join/post/!nick)."""
    return cache.unique_nickname(uid, valid_name(want) or "anon")


def heartbeat(cache, uid: int, want: str, channel: str | None = None):
    """Presence refresh that never renames: keeps the known nick."""
    known = cache.users.get(uid, {}).get("nickname", "")
    cache.touch_user(uid, known or valid_name(want) or "anon", channel)


def channel_list(db) -> list[dict]:
    return [
        {"name": c["name"], "locked": bool(c["channel_password_hash"])}
        for c in db.list_channels()
    ]


def can_enter(db, cache, ch, uid: int | None, password: str | None) -> bool:
    if not db.channel_locked(ch):
        return True
    if uid is not None and cache.is_unlocked(uid, ch["name"]):
        return True
    return bool(password) and db.check_channel_password(ch["id"], password)


def make_routes(db, cache, store):
    async def landing(request: Request):
        return TEMPLATES.TemplateResponse(
            request,
            "landing.html",
            {"channels": channel_list(db), "lock": PATHS["lock"]},
        )

    async def channel_pills(request: Request):
        html = "".join(
            channel_fill_pill(c["name"], locked=c["locked"]) for c in channel_list(db)
        )
        return HTMLResponse(
            html or '<p class="dim">no channels yet — start one above.</p>'
        )

    async def join(request: Request):
        form = dict(await request.form())
        nickname = valid_name(nick_of(request, form)) or "anon"
        channel = valid_name(form.get("channel", ""))
        password = (form.get("password") or "").strip() or None
        if not channel:
            return HTMLResponse(err_html("pick a valid channel name."), status_code=422)
        uid = uid_of(request, form)
        ch = db.ensure_channel(channel)
        if not can_enter(db, cache, ch, uid, password):
            return HTMLResponse(
                err_html(f"#{channel} is locked — enter the password."), status_code=401
            )
        ip = request.client.host if request.client else "?"
        row = db.resolve_user(uid, ip)  # unknown id / IP mismatch → fresh id
        claimed = cache.unique_nickname(
            row["id"] if row else -1, valid_name(nickname) or "anon"
        )
        user = db.upsert_user(row["id"] if row else None, claimed, ip, now())
        db.add_member(ch["id"], user["id"], now())
        if not db.owner_ids(ch["id"]):
            db.add_owner(ch["id"], user["id"])  # first user owns by default
        cache.touch_user(user["id"], claimed, channel)
        cache.unlock(user["id"], channel)
        target = f"/c/{channel}?uid={user['id']}&nick={claimed}"
        if request.headers.get("hx-request"):
            return Response(f"joining #{channel}…", headers={"HX-Redirect": target})
        return RedirectResponse(target, status_code=303)

    async def chat_page(request: Request):
        channel = valid_name(request.path_params["channel"] or "")
        if not channel:
            return RedirectResponse("/", status_code=303)
        ch = db.ensure_channel(channel)
        uid = uid_of(request)
        nick = nick_of(request)
        password = (request.query_params.get("pw") or "").strip() or None
        if not can_enter(db, cache, ch, uid, password):
            return TEMPLATES.TemplateResponse(
                request,
                "locked.html",
                {"channel": channel, "lock": PATHS["lock"]},
                status_code=403,
            )
        ip = request.client.host if request.client else "?"
        if uid and db.resolve_user(uid, ip):
            claimed = claim_nick(cache, uid, nick)
            db.upsert_user(uid, claimed, ip, now())
            db.add_member(ch["id"], uid, now())
            cache.touch_user(uid, claimed, channel)
            cache.clear_mentions(uid, channel)
            cache.unlock(uid, channel)
        rows = db.get_recent_channel_messages(ch["id"], HISTORY_N)
        if not cache.get_recent(channel):
            cache.seed(channel, [dict(r) for r in rows])
        return TEMPLATES.TemplateResponse(
            request,
            "chat.html",
            {
                "channel": channel,
                "locked": db.channel_locked(ch),
                "messages": "".join(message_html(db, cache, channel, r) for r in rows),
                "clip": PATHS["clip"],
                "lock": PATHS["lock"],
            },
        )

    async def history(request: Request):
        """Full 24h history on demand; page loads only the last 10 instantly."""
        channel = valid_name(request.path_params["channel"] or "")
        ch = db.get_channel_by_name(channel) if channel else None
        if not ch:
            return HTMLResponse("", status_code=404)
        uid = uid_of(request)
        if (
            uid is not None
            and db.get_user(uid) is not None
            and not db.is_member(ch["id"], uid)
        ):
            return Response(status_code=204)
        try:
            before = int(request.query_params.get("before", "1000000000"))
        except ValueError:
            before = 1000000000
        rows = db.get_channel_messages_before(ch["id"], before)
        if not rows:
            return Response(status_code=204)
        return HTMLResponse("".join(message_html(db, cache, channel, r) for r in rows))

    async def poll_messages(request: Request):
        channel = valid_name(request.path_params["channel"] or "")
        ch = db.get_channel_by_name(channel) if channel else None
        if not ch:
            return HTMLResponse("", status_code=404)
        uid = uid_of(request)
        if db.channel_locked(ch):
            if uid is None or not cache.is_unlocked(uid, channel):
                return Response(status_code=204)
        elif (
            uid is not None
            and db.get_user(uid) is not None
            and not db.is_member(ch["id"], uid)
        ):
            return Response(status_code=204)
        if uid:
            heartbeat(cache, uid, nick_of(request), channel)
            cache.clear_mentions(uid, channel)
        try:
            after = int(request.query_params.get("after", "0"))
        except ValueError:
            after = 0
        rows = db.get_channel_messages_after(ch["id"], after)
        if not rows:
            return Response(status_code=204)
        for r in rows:
            cache.push_message(channel, dict(r))
        return HTMLResponse("".join(message_html(db, cache, channel, r) for r in rows))

    async def post_message(request: Request):
        channel = valid_name(request.path_params["channel"] or "")
        form = await request.form()
        strings = {k: v for k, v in form.items() if isinstance(v, str)}
        uid = uid_of(request, strings)
        nickname = nick_of(request, strings)
        content = str(form.get("content", ""))[:2000]
        ch = db.get_channel_by_name(channel) if channel else None
        if not ch:
            return HTMLResponse("no such channel", status_code=404)
        ip = request.client.host if request.client else "?"
        if uid is None or db.resolve_user(uid, ip) is None:
            return HTMLResponse(
                err_html(f"join #{channel} first (or rejoin)."), status_code=403
            )
        nickname = claim_nick(cache, uid, nickname)
        user = db.upsert_user(uid, nickname, ip, now())
        if not db.is_member(ch["id"], user["id"]):
            return HTMLResponse(
                err_html(f"you are not in #{channel} — rejoin to enter."),
                status_code=403,
            )
        cache.touch_user(user["id"], nickname, channel)
        upload = form.get("file")
        has_file = upload is not None and getattr(upload, "filename", "")
        if content.strip().startswith("!") and not has_file:
            eph = handle_command(
                db,
                cache,
                channel=channel,
                ch=ch,
                user_id=user["id"],
                nickname=nickname,
                text=content,
                now=now(),
                ip=ip,
            )
            if eph is not None:
                return HTMLResponse(eph)
        att_id = None
        if has_file:
            data = await upload.read()
            if len(data) > 0:
                try:
                    att = store.save(
                        user["id"], upload.filename, upload.content_type, data, now()
                    )
                    att_id = att["id"]
                except QuotaExceeded as e:
                    return HTMLResponse(err_html(str(e)), status_code=413)
        if not content.strip() and att_id is None:
            return HTMLResponse("", status_code=204)
        row = db.create_message(ch["id"], user["id"], content, att_id, now())
        full = db.connection.execute(
            "SELECT m.*, u.last_nickname AS nickname FROM messages m "
            "JOIN users u ON u.id=m.author_id WHERE m.id=?",
            (row["id"],),
        ).fetchone()
        cache.push_message(channel, dict(full))
        resp = HTMLResponse(message_html(db, cache, channel, full))
        resp.headers["HX-Trigger"] = "chat-sent"
        return resp

    async def sidebar(request: Request):
        channel = valid_name(request.path_params.get("channel") or "") or ""
        ch = db.get_channel_by_name(channel) if channel else None
        uid = uid_of(request)
        if (
            ch
            and db.channel_locked(ch)
            and not (uid and cache.is_unlocked(uid, channel))
        ):
            return Response(status_code=204)
        if uid:
            heartbeat(cache, uid, nick_of(request), channel or None)
        my = cache.user_channels(uid) if uid else []
        counts = cache.mention_counts(uid) if uid else {}
        flags = {c["name"]: c["locked"] for c in channel_list(db)}
        pills = "".join(
            channel_pill(
                c,
                locked=flags.get(c, False),
                here=c == channel,
                uid=uid or "",
                badge=counts.get(c, 0),
            )
            for c in my
        )
        members = cache.active_in(channel) if channel else []
        owners = db.owner_ids(ch["id"]) if ch else set()
        roster = (
            "".join(
                f'<li class="op">@{html.escape(m["nickname"])}</li>'
                if m["id"] in owners
                else f"<li>{html.escape(m['nickname'])}</li>"
                for m in members
            )
            or "<li>—</li>"
        )
        return HTMLResponse(
            f'<h2>channels</h2><div class="pills">{pills or "<p class=dim>join one.</p>"}</div>'
            f'<h2>who is here ({len(members)})</h2><ul class="roster">{roster}</ul>'
        )

    async def download(request: Request):
        att = db.get_attachment(int(request.path_params["attachment_id"]))
        if not att:
            return HTMLResponse("gone (pruned after 24h?)", status_code=404)
        return FileResponse(
            att["location"], filename=att["filename"], media_type=att["mime_type"]
        )

    return {
        "landing": landing,
        "channel_pills": channel_pills,
        "join": join,
        "chat_page": chat_page,
        "history": history,
        "poll_messages": poll_messages,
        "post_message": post_message,
        "sidebar": sidebar,
        "download": download,
    }
