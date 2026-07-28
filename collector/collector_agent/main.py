import signal
import sys
import threading
from datetime import UTC, datetime

import httpx

from collector_agent.alerts import NtfyNotifier, ProviderAlerter
from collector_agent.api_client import CollectorApiClient
from collector_agent.binance_browser import BinanceSquareBrowserClient
from collector_agent.config import CollectorSettings
from collector_agent.db import CollectorStore
from collector_agent.providers.binance_square import BinanceSquareProvider
from collector_agent.providers.x_opencli import OpenCliXProvider
from collector_agent.scheduler import CollectorScheduler


def build_providers(settings: CollectorSettings) -> dict:
    return {
        "x": OpenCliXProvider(),
        "binance_square": BinanceSquareProvider(
            BinanceSquareBrowserClient(
                browser_executable=settings.binance_browser_executable,
                lang=settings.binance_square_lang,
            )
        ),
    }


def main() -> None:
    settings = CollectorSettings.from_env()
    store = CollectorStore(settings.db_path)
    api = CollectorApiClient(settings.public_api_url, settings.collector_token)
    provider_http = httpx.Client(timeout=20, headers={"User-Agent": "kol-collector-agent/0.1.0"})
    alerter = None
    if settings.ntfy_server and settings.ntfy_topic:
        alerter = ProviderAlerter(
            NtfyNotifier(
                settings.ntfy_server,
                settings.ntfy_topic,
                token=settings.ntfy_token,
                http=provider_http,
            ),
            cooldown_seconds=settings.provider_alert_cooldown_seconds,
        )
    scheduler = CollectorScheduler(
        store,
        api,
        build_providers(settings),
        alerter=alerter,
        initial_fetch_limit=settings.initial_fetch_limit,
        catchup_fetch_limit=settings.catchup_fetch_limit,
    )
    stop_event = threading.Event()
    signal.signal(signal.SIGTERM, lambda *_: stop_event.set())
    signal.signal(signal.SIGINT, lambda *_: stop_event.set())
    try:
        while not stop_event.is_set():
            try:
                scheduler.run_once(datetime.now(UTC))
            except Exception as exc:
                print(f"collector cycle failed: {type(exc).__name__}", file=sys.stderr, flush=True)
            stop_event.wait(settings.config_poll_seconds)
    finally:
        for provider in scheduler.providers.values():
            close = getattr(provider, "close", None)
            if close is not None:
                close()
        store.close()
        api.close()
        provider_http.close()


if __name__ == "__main__":
    main()
