from datetime import datetime, timezone

from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from app.collectors.base import CollectedPost
from app.db.base import Base
from app.models import RawPost, Signal, Subscription
from app.services.assets import detect_assets
from app.services.ingestion import ingest_subscription
from app.services.structurer import FallbackStructurer, HeuristicStructurer, Structurer


class FakeCollector:
    def fetch_new(self, handle, checkpoint=None, limit=20):
        return [
            CollectedPost(
                platform="x",
                external_id=str(index),
                url=f"https://x.com/{handle}/status/{index}",
                author_handle=handle,
                author_name=handle,
                published_at=datetime(2026, 7, 9, 12, index, tzinfo=timezone.utc),
                raw_text=f"$AXTI and $IQE supply chain pricing update {index}",
                raw_json=None,
            )
            for index in range(10)
        ]


def session_factory():
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    return Session()


def test_detect_assets_supports_us_crypto_and_a_shares():
    assets = [asset.model_dump() for asset in detect_assets("$AXTI $BTC NVDA AAPL 宁德时代 300750")]

    assert {"symbol": "AXTI", "market": "US_STOCK", "asset_type": "stock", "name": None} in assets
    assert {"symbol": "BTC", "market": "CRYPTO", "asset_type": "crypto", "name": None} in assets
    assert {"symbol": "NVDA", "market": "US_STOCK", "asset_type": "stock", "name": None} in assets
    assert {"symbol": "AAPL", "market": "US_STOCK", "asset_type": "stock", "name": None} in assets
    assert {"symbol": "300750", "market": "A_SHARE", "asset_type": "stock", "name": "宁德时代"} in assets


def test_invalid_subscription_schema_uses_fallback_without_model_call():
    class OnePostCollector:
        def fetch_new(self, handle, checkpoint=None, limit=20):
            return [
                CollectedPost(
                    platform="x",
                    external_id="schema-invalid-1",
                    url=f"https://x.com/{handle}/status/schema-invalid-1",
                    author_handle=handle,
                    author_name=handle,
                    published_at=datetime(2026, 7, 9, 12, 0, tzinfo=timezone.utc),
                    raw_text="$BTC 的方向暂不明确",
                    raw_json=None,
                )
            ]

    class ModelClient:
        calls = 0

        def complete(self, system_prompt, user_prompt, output_schema):
            self.calls += 1
            raise AssertionError("invalid schema must not reach the model")

    session = session_factory()
    subscription = Subscription(
        platform="x",
        platform_handle="schema-check",
        interval_minutes=1,
        output_schema_json="{not valid json",
    )
    session.add(subscription)
    session.commit()
    client = ModelClient()

    ingest_subscription(
        session=session,
        subscription=subscription,
        collector=OnePostCollector(),
        structurer=FallbackStructurer(Structurer(client), HeuristicStructurer()),
    )

    signal = session.scalar(select(Signal).where(Signal.raw_post_id.is_not(None)))
    assert signal is not None
    assert signal.structured_status == "fallback"
    assert client.calls == 0


def test_ingestion_backfills_ten_posts_once_and_advances_checkpoint():
    session = session_factory()
    subscription = Subscription(platform="x", platform_handle="aleabitoreddit", interval_minutes=1)
    session.add(subscription)
    session.commit()

    result = ingest_subscription(
        session=session,
        subscription=subscription,
        collector=FakeCollector(),
        structurer=HeuristicStructurer(),
        limit=10,
    )
    duplicate = ingest_subscription(
        session=session,
        subscription=subscription,
        collector=FakeCollector(),
        structurer=HeuristicStructurer(),
        limit=10,
    )

    assert result.fetched_count == 10
    assert result.inserted_count == 10
    assert result.structured_count == 10
    assert duplicate.inserted_count == 0
    assert session.scalar(select(RawPost).where(RawPost.external_id == "9")) is not None
    assert len(session.scalars(select(Signal)).all()) == 10
    assert subscription.checkpoint == "9"
