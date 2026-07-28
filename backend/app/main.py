import asyncio
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.core.config import configured_web_origins, get_settings, validate_runtime_settings
from app.db.base import Base
from app.db.migrations import run_schema_migrations
from app.db.session import SessionLocal, engine
from app.routers import admin, auth, collector, public
from app.services.bootstrap import backfill_subscription, ensure_defaults
from app.services.scheduler import scheduler_loop
from app.services.analysis_queue import process_pending_posts
from app.services.structurer import build_structurer


def process_analysis_batch() -> None:
    session = SessionLocal()
    try:
        process_pending_posts(session, build_structurer())
    finally:
        session.close()


async def analysis_loop(stop_event: asyncio.Event, poll_seconds: int) -> None:
    while not stop_event.is_set():
        await asyncio.to_thread(process_analysis_batch)
        try:
            await asyncio.wait_for(stop_event.wait(), timeout=poll_seconds)
        except TimeoutError:
            pass


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    validate_runtime_settings(settings)
    Base.metadata.create_all(bind=engine)
    run_schema_migrations(engine)
    session = SessionLocal()
    try:
        subscription = ensure_defaults(session)
        if settings.startup_backfill_enabled:
            backfill_subscription(session, subscription)
    finally:
        session.close()
    stop_event = asyncio.Event()
    scheduler_task = None
    analysis_task = asyncio.create_task(analysis_loop(stop_event, settings.analysis_poll_seconds))
    if settings.enable_scheduler:
        scheduler_task = asyncio.create_task(scheduler_loop(stop_event))
    yield
    if scheduler_task is not None:
        stop_event.set()
        await scheduler_task
    stop_event.set()
    await analysis_task


app = FastAPI(title="KOL Signal API", lifespan=lifespan)
settings = get_settings()
app.add_middleware(
    CORSMiddleware,
    allow_origins=configured_web_origins(settings),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.include_router(auth.router)
app.include_router(collector.router)
app.include_router(public.router)
app.include_router(admin.router)


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok", "service": "kol-signal-api"}
