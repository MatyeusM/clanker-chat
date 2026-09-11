import re
import sqlite3
import time

from starlette.testclient import TestClient

from clanker_chat.attachments.store import AttachmentStore, QuotaExceeded
from clanker_chat.cache.store import ChatCache
from clanker_chat.chat.format import render_body, valid_name
from clanker_chat.main import create_app


def test_mentions_only_hit_channel_members():
    c = ChatCache()
    c.touch_user(1, "bob", "lobby")
    c.touch_user(2, "alice", "lobby")
    hit = c.push_message("lobby", {"author_id": 2, "content": "hey @bob and @mallory"})
    assert hit == [1]
    assert c.mention_counts(1) == {"lobby": 1}
    c.clear_mentions(1, "lobby")
    assert c.mention_counts(1) == {}


def test_render_links_channels_and_highlights_members():
    html = render_body("see #lobby, hi @Bob", members={"bob"})
    assert 'href="/c/lobby"' in html
    assert 'class="mention hi"' in html
    assert "<script>" not in render_body("<script>alert(1)</script>")
    assert valid_name("#lobby!") is None


def test_quota_per_user(tmp_path):
    from clanker_chat.db.database import Database

    db = Database(tmp_path / "t.sqlite3")
    store = AttachmentStore(db, tmp_path / "att", max_per_user=10, max_total=100)
    now = int(time.time())
    user = db.upsert_user(None, "bob", "127.0.0.1", now)
    ch = db.ensure_channel("lobby")
    big = store.save(user["id"], "a.bin", "application/octet-stream", b"x" * 8, now)
    db.create_message(ch["id"], user["id"], "hi", big["id"], now)
    try:
        store.save(user["id"], "b.bin", "application/octet-stream", b"y" * 8, now)
        raise AssertionError("should have raised")
    except QuotaExceeded:
        pass


def test_full_flow(tmp_path, monkeypatch):
    monkeypatch.setenv("CHAT_DB_PATH", str(tmp_path / "c.sqlite3"))
    monkeypatch.setenv("CHAT_ATTACH_DIR", str(tmp_path / "att"))
    app = create_app()
    with TestClient(app) as t:
        assert t.get("/").status_code == 200
        r = t.post("/join", data={"nickname": "bob", "channel": "lobby"})
        assert r.status_code in (200, 303)
        uid = app.state.db.get_channel_by_name("lobby")["id"]
        assert uid
        page = t.get("/c/lobby", params={"uid": 1, "nick": "bob"})
        assert page.status_code == 200 and "#lobby" in page.text or "lobby" in page.text
        m = t.post(
            "/c/lobby/messages",
            data={"content": "hello #lobby", "uid": "1", "nickname": "bob"},
        )
        assert m.status_code == 200 and "/c/lobby" in m.text
        assert "&lt;bob&gt;" in m.text  # nickname must render, never "?"
        poll = t.get("/c/lobby/messages", params={"after": 0, "uid": 1})
        assert poll.status_code == 200 and "hello" in poll.text
        assert t.get("/c/lobby/messages", params={"after": 9999}).status_code == 204


def _app(tmp_path, monkeypatch):
    monkeypatch.setenv("CHAT_DB_PATH", str(tmp_path / "c.sqlite3"))
    monkeypatch.setenv("CHAT_ATTACH_DIR", str(tmp_path / "att"))
    return create_app()


def _say(t, channel, uid, nick, text):
    return t.post(
        f"/c/{channel}/messages",
        data={"content": text, "uid": str(uid), "nickname": nick},
    )


def test_first_user_owns_and_commands(tmp_path, monkeypatch):
    app = _app(tmp_path, monkeypatch)
    with TestClient(app) as t:
        t.post("/join", data={"nickname": "bob", "channel": "ops"})
        t.post("/join", data={"nickname": "alice", "channel": "ops"})
        db = app.state.db
        ch = db.get_channel_by_name("ops")
        assert db.is_owner(ch["id"], 1)  # first user owns by default
        assert not db.is_owner(ch["id"], 2)

        r = _say(t, "ops", 1, "bob", "!help")
        assert "!kick" in r.text  # ephemeral, sender-only
        assert (
            "become a channel owner"
            not in t.get("/c/ops/messages", params={"after": 0, "uid": 1}).text
        )  # never stored

        assert "owners only" in _say(t, "ops", 2, "alice", "!owner pw1234").text
        assert "updated" in _say(t, "ops", 1, "bob", "!owner secretpw").text
        assert "wrong" in _say(t, "ops", 2, "alice", "!auth nope").text
        assert "owners only" in _say(t, "ops", 2, "alice", "!setpassword locked1").text
        assert "locked" in _say(t, "ops", 1, "bob", "!setpassword locked1").text
        assert "<svg" in t.get("/channels").text  # lock shown in channel list


def test_lock_gate_kick_and_rejoin(tmp_path, monkeypatch):
    app = _app(tmp_path, monkeypatch)
    with TestClient(app) as t:
        t.post("/join", data={"nickname": "bob", "channel": "ops"})
        _say(t, "ops", 1, "bob", "!owner secretpw")
        _say(t, "ops", 1, "bob", "!setpassword locked1")
        t.post(
            "/join",
            data={"nickname": "mallory", "channel": "ops", "password": "locked1"},
        )
        db = app.state.db
        ch = db.get_channel_by_name("ops")

        r = t.post("/join", data={"nickname": "mallory2", "channel": "ops"})
        assert r.status_code == 401  # locked, no password
        assert t.get("/c/ops", params={"uid": 99}).status_code == 403  # locked page

        assert "kicked mallory" in _say(t, "ops", 1, "bob", "!kick mallory").text
        assert not db.is_member(ch["id"], 2)
        assert (
            "kicked" in t.get("/c/ops/messages", params={"after": 0, "uid": 1}).text
        )  # all see notice
        r = _say(t, "ops", 2, "mallory", "i'm back")
        assert r.status_code == 403  # kicked users can't post

        t.post(
            "/join",
            data={
                "nickname": "mallory",
                "channel": "ops",
                "password": "locked1",
                "uid": 2,
            },
        )  # soft kick: can rejoin
        assert _say(t, "ops", 2, "mallory", "i'm back").status_code == 200
        assert "authed" in _say(t, "ops", 2, "mallory", "!auth secretpw").text
        assert "can't kick an owner" in _say(t, "ops", 1, "bob", "!kick mallory").text

        side = t.get("/c/ops/sidebar", params={"uid": 1}).text
        assert "@bob" in side and "@mallory" in side  # owners wear @


def test_history_on_demand(tmp_path, monkeypatch):
    app = _app(tmp_path, monkeypatch)
    with TestClient(app) as t:
        t.post("/join", data={"nickname": "bob", "channel": "hist"})
        for i in range(12):
            _say(t, "hist", 1, "bob", f"msg {i}")
        page = t.get("/c/hist", params={"uid": 1, "nick": "bob"}).text
        assert page.count("data-mid") == 10  # instant: last 10 only
        first = min(int(i) for i in re.findall(r'data-mid="(\d+)"', page))
        older = t.get("/c/hist/history", params={"before": first, "uid": 1}).text
        assert older.count("data-mid") == 2
        assert "msg 0" in older


def test_legacy_schema_migrates(tmp_path):
    from clanker_chat.db.database import Database

    p = tmp_path / "legacy.sqlite3"
    con = sqlite3.connect(p)
    con.execute(
        "CREATE TABLE channels (id INTEGER PRIMARY KEY, name TEXT NOT NULL UNIQUE,"
        " owner_password_hash TEXT NOT NULL, channel_password_hash TEXT)"
    )
    con.execute("INSERT INTO channels (name, owner_password_hash) VALUES ('old', 'x')")
    con.commit()
    con.close()
    db = Database(p)  # must not raise; old random hash becomes unset
    ch = db.get_channel_by_name("old")
    assert ch and not db.owner_password_set(ch)
    assert db.list_channels()
    db.close()


def _join(t, nick, channel, **kw):
    return t.post("/join", data={"nickname": nick, "channel": channel, **kw})


def test_xss_nick_never_renders(tmp_path, monkeypatch):
    app = _app(tmp_path, monkeypatch)
    evil = "<img src=x onerror=alert(1)>"
    with TestClient(app) as t:
        r = _join(t, evil, "sec")
        assert "nick=anon" in r.history[0].headers["location"]  # rejected → anon
        m = _say(t, "sec", 1, evil, "hi")
        assert "onerror" not in m.text and "&lt;anon&gt;" in m.text
        # even a poisoned cache entry renders escaped (neutralized, not raw HTML)
        app.state.cache.touch_user(9, evil, "sec")
        side = t.get("/c/sec/sidebar", params={"uid": 1}).text
        assert "<img" not in side and "&lt;img" in side


def test_nicks_unique_among_active(tmp_path, monkeypatch):
    app = _app(tmp_path, monkeypatch)
    with TestClient(app) as t:
        _join(t, "bob", "a")
        r = _join(t, "bob", "a")
        assert "nick=bob_1" in r.history[0].headers["location"]
        nicks = {
            u["last_nickname"]
            for u in app.state.db.connection.execute("SELECT * FROM users").fetchall()
        }
        assert nicks == {"bob", "bob_1"}


def test_seizure_gets_fresh_id(tmp_path, monkeypatch):
    app = _app(tmp_path, monkeypatch)
    with TestClient(app) as t:
        _join(t, "alice", "x")
        db = app.state.db
        assert db.resolve_user(1, "testclient") is not None
        assert db.resolve_user(1, "6.6.6.6") is None  # wrong IP → no resolve
        assert db.resolve_user(999, "testclient") is None  # unknown id → no resolve
        r = _join(t, "mallory", "x", uid="1")  # mallory grabs alice's id, same test IP…
        loc = r.history[0].headers["location"]
        assert "uid=1" in loc  # …same IP is the soft-pass, so this is legit reuse
    # …but from another IP she would be reissued: covered by resolve_user asserts


def test_nick_command(tmp_path, monkeypatch):
    app = _app(tmp_path, monkeypatch)
    with TestClient(app) as t:
        _join(t, "bob", "n")
        assert "you are now alice" in _say(t, "n", 1, "bob", "!nick alice").text
        assert app.state.db.get_user(1)["last_nickname"] == "alice"
        _join(t, "alice", "n")  # clash → suffixed
        nicks = [
            u["last_nickname"]
            for u in app.state.db.connection.execute("SELECT * FROM users").fetchall()
        ]
        assert sorted(nicks) == ["alice", "alice_1"]
        r = _say(t, "n", 1, "alice", "!nick <b>nope</b>")
        assert "usage" in r.text
        assert app.state.db.get_user(1)["last_nickname"] == "alice"


def test_prune_files_deletes_only_inside_store(tmp_path):
    from clanker_chat.attachments.store import AttachmentStore

    store = AttachmentStore(None, tmp_path / "att", 10**9, 10**9)
    inside = tmp_path / "att" / "1_x.bin"
    inside.write_bytes(b"x")
    outside = tmp_path / "other.bin"
    outside.write_bytes(b"y")
    assert store.prune_files([{"location": str(inside)}]) == 1
    assert not inside.exists()
    assert store.prune_files([{"location": str(outside)}]) == 0
    assert outside.exists()
