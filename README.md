# Clanker Chat

A chat application reminiscent of mIRC, built with Python (Starlette) and
htmx 4. No JavaScript framework, no websockets — the server returns HTML
fragments and htmx swaps them into the page. This started as a for-fun
project, but i like it so much so I want to archive it.

## Run it

Requires [mise](https://mise.jdx.dev) (pins node, pnpm, python, uv):

```sh
mise run setup   # install deps, vendor htmx + icons
mise run dev     # serve with reload on http://localhost:8000
```

Or manually:

```sh
pnpm install && uv sync && node scripts/build.mjs
uv run uvicorn clanker_chat.main:app --reload
```

`mise run check` is the full gate (ruff, pytest, oxlint, oxfmt,
stylelint) — it also runs in CI on every push and PR.
`mise run lint` lints, `mise run fmt` formats, `mise run clean` wipes all
generated files, caches, and the venv.

## How it works

- **Identity**: the server assigns you an integer user id stored in
  `localStorage`. Lose it and you get a new one. Claiming someone else's
  id fails soft verification (IP check) and issues a fresh id instead.
- **Nicknames**: latin only (`A–Z a–z 0–9 - _`), unique among active users
  (clashes get `_1`, `_2`, …).
- **Channels**: join any `#name` — it is created on demand. The first user
  in a channel owns it by default.
- **Polling**: new messages every 500ms, mention badges every 5s. The page
  loads the last 10 messages instantly; full 24h history loads on demand
  via the `⇪ 24h history` button.
- **Mentions**: `@nickname` highlights for members of the channel and shows
  up as a badge in the channel list. `#channel` renders as a join link.
- **Storage**: everything lives in sqlite and is pruned after 24h —
  messages and attachments alike. The hot cache keeps the last 10 messages
  per channel, presence, and mention counts in memory.
- **Attachments**: one per message, 5MB per user and 250MB total by
  default (`CHAT_MAX_USER_MB` / `CHAT_MAX_TOTAL_MB`, plus `CHAT_DB_PATH` /
  `CHAT_ATTACH_DIR`).

## Commands

Type these in the chat box (Tab completes them). Replies are ephemeral —
only you see them, except kick notices which are announced to the channel.

| Command                  | Who    | Effect                                  |
| ------------------------ | ------ | --------------------------------------- |
| `!help`                  | anyone | list commands                           |
| `!nick <newname>`        | anyone | change your nickname                    |
| `!auth <pw>`             | anyone | become a channel owner (needs owner pw) |
| `!owner <newpw>`         | owner  | set the owner password                  |
| `!setpassword <pw\|off>` | owner  | lock / unlock the channel               |
| `!kick <nick>`           | owner  | kick a non-owner (they can rejoin)      |

Locked channels show a lock icon in every channel list. Owners wear `@`
in the roster. Owners cannot be kicked.

## Look

Exactly 8 ANSI-like colors, each with a light and dark shade resolved via
`light-dark()` — toggle with the theme button. The only font is Lekton,
vendored in `static/font`. File-type icons come from `@mdi/js`, extracted
at build time by `scripts/build.mjs` (same pattern as the htmx bundle, no
runtime dependency).

## Layout

```text
src/clanker_chat/
  main.py            app factory, routes, 24h prune loop
  routes.py          landing, chat, polling fragments, uploads
  commands.py        !commands (sender-only replies)
  config.py          quotas + paths (env-overridable)
  chat/format.py     linkify #channels / @mentions, nickname rules
  chat/render.py     HTML fragments + channel pills
  cache/store.py     last-10, presence, mentions, unlocks
  attachments/store.py  disk store, quotas, prune
  db/database.py     sqlite access
  db/moderation.py   members, owners, passwords, legacy migration
  templates/         landing, chat, locked pages
static/              css (ANSI palette), js (identity, polling, completion)
tests/               pytest suite (ruff-clean, like everything else)
```
