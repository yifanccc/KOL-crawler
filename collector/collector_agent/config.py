from dataclasses import dataclass
from pathlib import Path
import os


@dataclass(frozen=True)
class CollectorSettings:
    public_api_url: str
    collector_agent_id: str
    collector_token: str
    db_path: Path
    config_poll_seconds: int = 60
    initial_fetch_limit: int = 1
    catchup_fetch_limit: int = 5
    ntfy_server: str | None = None
    ntfy_topic: str | None = None
    ntfy_token: str | None = None
    provider_alert_cooldown_seconds: int = 300
    binance_browser_executable: str | None = None
    binance_square_lang: str = "zh-CN"

    @classmethod
    def from_env(cls) -> "CollectorSettings":
        return cls(
            public_api_url=os.environ["PUBLIC_API_URL"].rstrip("/"),
            collector_agent_id=os.environ["COLLECTOR_AGENT_ID"],
            collector_token=os.environ["COLLECTOR_TOKEN"],
            db_path=Path(os.environ.get("COLLECTOR_DB_PATH", "collector.sqlite3")),
            config_poll_seconds=max(1, int(os.environ.get("CONFIG_POLL_SECONDS", "60"))),
            initial_fetch_limit=max(1, int(os.environ.get("INITIAL_FETCH_LIMIT", "1"))),
            catchup_fetch_limit=max(1, int(os.environ.get("CATCHUP_FETCH_LIMIT", "5"))),
            ntfy_server=os.environ.get("NTFY_SERVER") or None,
            ntfy_topic=os.environ.get("NTFY_TOPIC") or None,
            ntfy_token=os.environ.get("NTFY_TOKEN") or None,
            provider_alert_cooldown_seconds=max(
                1, int(os.environ.get("PROVIDER_ALERT_COOLDOWN_SECONDS", "300"))
            ),
            binance_browser_executable=os.environ.get("BINANCE_BROWSER_EXECUTABLE") or None,
            binance_square_lang=os.environ.get("BINANCE_SQUARE_LANG", "zh-CN"),
        )
