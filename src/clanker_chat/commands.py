"""Bang commands: self-serve moderation with sender-only replies.

handle_command returns ephemeral HTML appended only to the sender's log
(or None when the text is not a command). Side effects like kick notices
are stored as regular messages and reach everyone through polling.
"""

from html import escape

HELP_LINES = [
    "<b>!help</b> — this list",
    "<b>!nick &lt;newname&gt;</b> — change your nickname",
    "<b>!auth &lt;pw&gt;</b> — become a channel owner",
    "<b>!owner &lt;newpw&gt;</b> — (owner) set the owner password",
    "<b>!setpassword &lt;pw|off&gt;</b> — (owner) lock/unlock the channel",
    "<b>!kick &lt;nick&gt;</b> — (owner) kick a non-owner",
]


def sys_html(text: str) -> str:
    return f'<article class="msg sys"><span class="body">{text}</span></article>'


def err_html(text: str) -> str:
    return f'<article class="msg sys err"><span class="body">{text}</span></article>'


def _password(arg: str) -> str | None:
    pw = arg.strip()[:64]
    return pw if pw else None


def handle_command(
    db,
    cache,
    *,
    channel: str,
    ch,
    user_id: int,
    nickname: str,
    text: str,
    now: int,
    ip: str = "?",
):
    stripped = (text or "").strip()
    if not stripped.startswith("!"):
        return None
    parts = stripped.split(None, 1)
    cmd, arg = parts[0].lower(), (parts[1] if len(parts) > 1 else "").strip()

    if cmd == "!help":
        return sys_html("<br>".join(HELP_LINES))

    if cmd == "!nick":
        from .chat.format import valid_name

        clean = valid_name(arg)
        if not clean:
            return err_html("usage: !nick &lt;newname&gt; (A–Z a–z 0–9 - _ only).")
        claimed = cache.unique_nickname(user_id, clean)
        db.upsert_user(user_id, claimed, ip, now)
        cache.touch_user(user_id, claimed, channel)
        note = "" if claimed == clean else f" (taken, you got {escape(claimed)})"
        return sys_html(f"you are now {escape(claimed)}{note}.")

    if cmd == "!auth":
        pw = _password(arg)
        if pw and db.check_owner_password(ch["id"], pw):
            db.add_owner(ch["id"], user_id)
            cache.unlock(user_id, channel)
            return sys_html(f"authed as owner of #{channel}.")
        return err_html("wrong owner password.")

    if cmd == "!owner":
        if not db.is_owner(ch["id"], user_id):
            return err_html("owners only.")
        pw = _password(arg)
        if not pw or len(pw) < 4:
            return err_html("usage: !owner &lt;newpw&gt; (min 4 chars).")
        db.set_owner_password(ch["id"], pw)
        return sys_html(f"owner password for #{channel} updated.")

    if cmd == "!setpassword":
        if not db.is_owner(ch["id"], user_id):
            return err_html("owners only.")
        if arg.lower() == "off":
            db.set_channel_password(ch["id"], None)
            return sys_html(f"#{channel} is now open.")
        pw = _password(arg)
        if not pw or len(pw) < 4:
            return err_html("usage: !setpassword &lt;pw|off&gt; (min 4 chars).")
        db.set_channel_password(ch["id"], pw)
        return sys_html(f"#{channel} is now locked behind a password.")

    if cmd == "!kick":
        if not db.is_owner(ch["id"], user_id):
            return err_html("owners only.")
        target_nick = arg.lstrip("@").strip()
        lookup = cache.channel_nicknames(channel)
        target = lookup.get(target_nick.lower()) if target_nick else None
        if target is None:
            return err_html(f"no '{escape(target_nick)}' in #{channel}.")
        if db.is_owner(ch["id"], target):
            return err_html("can't kick an owner.")
        db.remove_member(ch["id"], target)
        cache.leave(target, channel)
        cache.lock_out(target, channel)
        db.create_message(
            ch["id"], user_id, f"* {nickname} kicked {target_nick}", None, now
        )
        return sys_html(f"kicked {escape(target_nick)} from #{channel}.")

    return err_html(f"unknown command '{escape(parts[0])}' — try !help.")
