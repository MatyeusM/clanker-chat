"""App factory: static, routes, 24h prune loop."""

import asyncio
import sqlite3
import time
from contextlib import asynccontextmanager
from pathlib import Path

from starlette.applications import Starlette
from starlette.routing import Mount, Route
from starlette.staticfiles import StaticFiles

from .attachments.store import AttachmentStore
from .cache.store import ChatCache
from .config import load_settings
from .db.database import Database
from .routes import make_routes

BASE = Path(__file__).resolve().parent.parent.parent


def create_app(db_path: str | None = None) -> Starlette:
    settings = load_settings()
    db = Database(db_path or settings.db_path)
    cache = ChatCache()
    store = AttachmentStore(
        db,
        settings.attachment_dir,
        settings.max_bytes_per_user,
        settings.max_bytes_total,
    )

    @asynccontextmanager
    async def lifespan(app):
        app.state.db = db
        app.state.cache = cache
        app.state.store = store
        stop = asyncio.Event()

        async def prune_loop():
            while not stop.is_set():
                try:
                    expired = db.prune(int(time.time()))
                    store.prune_files(expired)
                except sqlite3.Error:
                    continue
                try:
                    await asyncio.wait_for(stop.wait(), timeout=120)
                except TimeoutError:
                    continue

        task = asyncio.create_task(prune_loop())
        yield
        stop.set()
        await task

    h = make_routes(db, cache, store)
    routes = [
        Route("/", h["landing"], methods=["GET"]),
        Route("/join", h["join"], methods=["POST"]),
        Route("/channels", h["channel_pills"], methods=["GET"]),
        Route("/c/{channel}", h["chat_page"], methods=["GET"]),
        Route("/c/{channel}/history", h["history"], methods=["GET"]),
        Route("/c/{channel}/messages", h["poll_messages"], methods=["GET"]),
        Route("/c/{channel}/messages", h["post_message"], methods=["POST"]),
        Route("/c/{channel}/sidebar", h["sidebar"], methods=["GET"]),
        Route("/attachments/{attachment_id:int}", h["download"], methods=["GET"]),
        Mount("/static", StaticFiles(directory=str(BASE / "static")), name="static"),
    ]
    return Starlette(routes=routes, lifespan=lifespan)


app = create_app()
