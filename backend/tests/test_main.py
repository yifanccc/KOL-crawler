import asyncio
import time

from app import main


def test_analysis_loop_keeps_event_loop_responsive(monkeypatch) -> None:
    class FakeSession:
        def close(self) -> None:
            pass

    def slow_process_pending_posts(_session, _structurer) -> None:
        time.sleep(0.2)

    monkeypatch.setattr(main, "SessionLocal", FakeSession)
    monkeypatch.setattr(main, "build_structurer", object)
    monkeypatch.setattr(main, "process_pending_posts", slow_process_pending_posts)

    async def exercise() -> float:
        stop_event = asyncio.Event()
        started_at = time.monotonic()
        task = asyncio.create_task(main.analysis_loop(stop_event, poll_seconds=60))
        await asyncio.sleep(0.01)
        elapsed = time.monotonic() - started_at
        stop_event.set()
        await task
        return elapsed

    assert asyncio.run(exercise()) < 0.1
