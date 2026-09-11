"""In-memory hot cache: last 10 msgs/channel, presence, mentions."""

import re
import time
from collections import defaultdict, deque

MENTION_RE = re.compile(r"@([A-Za-z0-9_\-]{1,32})")
LAST_N = 10


class ChatCache:
    def __init__(self):
        self.recent: dict[str, deque] = defaultdict(lambda: deque(maxlen=LAST_N))
        # user_id -> {"nickname": str, "last_seen": int, "channels": set[str]}
        self.users: dict[int, dict] = {}
        # channel -> set[user_id]
        self.members: dict[str, set[int]] = defaultdict(set)
        # user_id -> channel -> unread mention count
        self.mentions: dict[int, dict[str, int]] = defaultdict(lambda: defaultdict(int))
        # (user_id, channel) pairs that passed a channel-password gate
        self.unlocked: set[tuple[int, str]] = set()

    def touch_user(self, user_id: int, nickname: str, channel: str | None = None):
        now = int(time.time())
        entry = self.users.setdefault(
            user_id, {"nickname": nickname, "last_seen": now, "channels": set()}
        )
        if nickname == "anon" and entry["nickname"] not in ("anon", ""):
            nickname = entry["nickname"]  # "anon" means "no identity claimed"
        entry["nickname"] = nickname
        entry["last_seen"] = now
        if channel:
            entry["channels"].add(channel)
            self.members[channel].add(user_id)

    def leave(self, user_id: int, channel: str):
        self.users.get(user_id, {}).get("channels", set()).discard(channel)
        self.members[channel].discard(user_id)

    def unlock(self, user_id: int, channel: str):
        self.unlocked.add((user_id, channel))

    def lock_out(self, user_id: int, channel: str):
        self.unlocked.discard((user_id, channel))

    def is_unlocked(self, user_id: int, channel: str) -> bool:
        return (user_id, channel) in self.unlocked

    def user_channels(self, user_id: int) -> list[str]:
        return sorted(self.users.get(user_id, {}).get("channels", set()))

    def unique_nickname(self, user_id: int, want: str) -> str:
        """Slug-safe unique nick among active users; suffixes _1, _2… on clash."""
        want = want.strip()[:28] or "anon"
        taken = {
            u.get("nickname", "").lower() for i, u in self.users.items() if i != user_id
        }
        if want.lower() not in taken:
            return want
        i = 1
        while f"{want}_{i}".lower() in taken:
            i += 1
        return f"{want}_{i}"
        return sorted(self.users.get(user_id, {}).get("channels", set()))

    def channel_nicknames(self, channel: str) -> dict[str, int]:
        """lowercase nickname -> user_id for members of channel."""
        out = {}
        for uid in self.members.get(channel, set()):
            nick = self.users.get(uid, {}).get("nickname", "")
            if nick:
                out[nick.lower()] = uid
        return out

    def push_message(self, channel: str, msg: dict) -> list[int]:
        """Store msg, detect @mentions among channel members. Returns mentioned uids."""
        self.recent[channel].append(msg)
        lookup = self.channel_nicknames(channel)
        author = msg.get("author_id")
        mentioned = set()
        for m in MENTION_RE.findall(msg.get("content", "")):
            uid = lookup.get(m.lower())
            if uid is not None and uid != author:
                mentioned.add(uid)
        for uid in mentioned:
            self.mentions[uid][channel] += 1
        return sorted(mentioned)

    def get_recent(self, channel: str) -> list[dict]:
        return list(self.recent.get(channel, []))

    def mention_counts(self, user_id: int) -> dict[str, int]:
        return dict(self.mentions.get(user_id, {}))

    def clear_mentions(self, user_id: int, channel: str):
        if user_id in self.mentions and channel in self.mentions[user_id]:
            del self.mentions[user_id][channel]

    def active_in(self, channel: str) -> list[dict]:
        out = []
        for uid in sorted(self.members.get(channel, set())):
            u = self.users.get(uid, {})
            out.append({"id": uid, "nickname": u.get("nickname", "?")})
        return out

    def seed(self, channel: str, messages: list[dict]):
        dq = self.recent[channel]
        dq.clear()
        for m in messages[-LAST_N:]:
            dq.append(m)
