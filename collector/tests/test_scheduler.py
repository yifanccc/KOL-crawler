from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from collector_agent.db import CollectorStore
from collector_agent.models import CollectedPost, PostFetchResult, ProviderTarget
from collector_agent.scheduler import CollectorScheduler
from collector_agent.providers.base import ProviderHealth, TradeHistoryGap
from collector_agent.trade_models import TradeRecordFetchResult
from tests.trade_samples import checkpoint, sample_record


class Api:
    def __init__(self):
        self.heartbeats = []
        self.position_replacements = []

    def fetch_config(self): return {"agentId": "home", "pollSeconds": 60, "subscriptions": [{"id": 1, "platform": "x", "handle": "one", "intervalMinutes": 1, "enabled": True}, {"id": 2, "platform": "x", "handle": "two", "intervalMinutes": 2, "enabled": True}]}
    def upload(self, agent_id, posts): return {"items": [{"externalId": post["externalId"], "status": "accepted"} for post in posts]}
    def replace_positions(
        self,
        agent_id,
        subscription_id,
        positions,
        account=None,
        operations=None,
    ):
        self.position_replacements.append(
            (agent_id, subscription_id, positions, account, operations)
        )
        return {"count": len(positions)}
    def heartbeat(self, payload): self.heartbeats.append(payload); return {}


class Provider:
    def fetch(self, target, checkpoint, limit):
        handle = target.handle
        posts = [CollectedPost("x", handle + "-1", handle, handle, None, datetime(2026, 7, 10, tzinfo=UTC), "https://x.com", "$BTC", {}, handle)]
        return PostFetchResult(posts, posts[-1].external_id)

    def health(self):
        return ProviderHealth("authenticated")


class ReturnedHealthFailureProvider:
    def fetch(self, target, checkpoint, limit):
        return PostFetchResult([], checkpoint)

    def health(self):
        return ProviderHealth("failed", "OpenCLI timed out")


def test_scheduler_runs_intervals_independently(tmp_path):
    api = Api()
    scheduler = CollectorScheduler(CollectorStore(tmp_path / "db.sqlite"), api, {"x": Provider()})
    now = datetime(2026, 7, 10, tzinfo=UTC)
    assert scheduler.run_once(now) == [1, 2]
    assert scheduler.run_once(now + timedelta(minutes=1)) == [1]
    assert scheduler.run_once(now + timedelta(minutes=2)) == [1, 2]
    assert api.heartbeats[-1]["providers"] == [
        {"platform": "x", "status": "authenticated", "message": None}
    ]


def test_scheduler_logs_each_subscription_as_success_skipped_or_failed(tmp_path, capsys):
    api = Api()
    scheduler = CollectorScheduler(CollectorStore(tmp_path / "db.sqlite"), api, {"x": Provider()})
    now = datetime(2026, 7, 13, 10, 16, tzinfo=UTC)

    scheduler.run_once(now)
    success_log = capsys.readouterr().out
    scheduler.run_once(now + timedelta(seconds=30))
    skipped_log = capsys.readouterr().out

    assert "2026-07-13T10:16:00Z collector subscription=1 platform=x handle=one status=success fetched=1" in success_log
    assert "2026-07-13T10:16:30Z collector subscription=1 platform=x handle=one status=skipped reason=not_due" in skipped_log

    scheduler.providers["x"] = FailingProvider()
    scheduler.run_once(now + timedelta(minutes=2))
    failed_log = capsys.readouterr().out
    assert "2026-07-13T10:18:00Z collector subscription=1 platform=x handle=one status=failed error=RuntimeError" in failed_log


def test_scheduler_logs_returned_provider_failure_as_failed(tmp_path, capsys):
    api = Api()
    store = CollectorStore(tmp_path / "db.sqlite")
    scheduler = CollectorScheduler(store, api, {"x": ReturnedHealthFailureProvider()})
    now = datetime(2026, 7, 13, 10, 20, tzinfo=UTC)

    assert scheduler.run_once(now) == []

    output = capsys.readouterr().out
    assert "subscription=1 platform=x handle=one status=failed error=ProviderHealth provider_status=failed" in output
    assert "subscription=2 platform=x handle=two status=failed error=ProviderHealth provider_status=failed" in output
    assert "status=success" not in output
    assert store.checkpoint_for(1) is None
    assert store.checkpoint_for(2) is None
    assert api.heartbeats[-1]["providers"] == [
        {"platform": "x", "status": "failed", "message": "OpenCLI timed out"}
    ]


class RecordingLimitProvider(Provider):
    def __init__(self):
        self.limits = []
        self.sequence = 0

    def fetch(self, target, checkpoint, limit):
        self.limits.append(limit)
        self.sequence += 1
        posts = [
            CollectedPost(
                "x",
                str(self.sequence),
                target.handle,
                target.handle,
                None,
                datetime(2026, 7, 10, tzinfo=UTC),
                "https://x.com",
                "$BTC",
                {},
                None,
            )
        ]
        return PostFetchResult(posts, posts[-1].external_id)


def test_scheduler_uses_initial_then_catchup_limit(tmp_path):
    api = FlakyUploadApi()
    provider = RecordingLimitProvider()
    scheduler = CollectorScheduler(
        CollectorStore(tmp_path / "db.sqlite"),
        api,
        {"x": provider},
        initial_fetch_limit=1,
        catchup_fetch_limit=5,
    )
    now = datetime(2026, 7, 10, tzinfo=UTC)

    scheduler.run_once(now)
    scheduler.run_once(now + timedelta(minutes=5))

    assert provider.limits == [1, 5]


class RestartCatchupProvider(Provider):
    def __init__(self):
        self.calls = []

    def fetch(self, target, checkpoint, limit):
        handle = target.handle
        self.calls.append((handle, target.account_id, checkpoint, limit))
        posts = [
            CollectedPost(
                "x",
                str(external_id),
                handle,
                handle,
                None,
                datetime(2026, 7, 10, tzinfo=UTC),
                f"https://x.com/{handle}/status/{external_id}",
                "$BTC",
                {},
                None,
            )
            for external_id in range(101, 106)
        ]
        return PostFetchResult(posts, posts[-1].external_id)


class RestartCatchupApi(Api):
    def fetch_config(self):
        return {
            "agentId": "home",
            "pollSeconds": 60,
            "subscriptions": [
                {
                    "id": 1,
                    "platform": "x",
                    "handle": "one",
                    "intervalMinutes": 5,
                    "enabled": True,
                }
            ],
        }


def test_scheduler_uses_persisted_checkpoint_for_restart_catchup(tmp_path):
    path = tmp_path / "db.sqlite"
    before_restart = CollectorStore(path)
    before_restart.record_fetch(1, "100", [])
    before_restart.close()

    api = RestartCatchupApi()
    provider = RestartCatchupProvider()
    after_restart = CollectorStore(path)
    scheduler = CollectorScheduler(
        after_restart,
        api,
        {"x": provider},
        initial_fetch_limit=1,
        catchup_fetch_limit=5,
    )

    scheduler.run_once(datetime(2026, 7, 10, tzinfo=UTC))

    assert provider.calls == [("one", None, "100", 5)]
    assert after_restart.checkpoint_for(1) == "105"
    assert after_restart.pending_posts() == []


class FlakyUploadApi(Api):
    def __init__(self):
        super().__init__()
        self.upload_attempts = 0

    def fetch_config(self):
        return {
            "agentId": "home",
            "pollSeconds": 60,
            "subscriptions": [
                {"id": 1, "platform": "x", "handle": "one", "intervalMinutes": 5, "enabled": True}
            ],
        }

    def upload(self, agent_id, posts):
        self.upload_attempts += 1
        if self.upload_attempts == 1:
            raise RuntimeError("network unavailable")
        return super().upload(agent_id, posts)


def test_upload_failure_keeps_outbox_backs_off_and_still_sends_heartbeat(tmp_path):
    api = FlakyUploadApi()
    store = CollectorStore(tmp_path / "db.sqlite")
    scheduler = CollectorScheduler(store, api, {"x": Provider()})
    now = datetime(2026, 7, 10, tzinfo=UTC)

    assert scheduler.run_once(now) == [1]
    assert len(store.pending_posts()) == 1
    assert api.upload_attempts == 1
    assert len(api.heartbeats) == 1

    scheduler.run_once(now + timedelta(seconds=1))
    assert api.upload_attempts == 1
    assert len(store.pending_posts()) == 1
    assert len(api.heartbeats) == 2

    scheduler.run_once(now + timedelta(seconds=2))
    assert api.upload_attempts == 2
    assert store.pending_posts() == []


class IsolatedProviderApi(Api):
    def fetch_config(self):
        return {
            "agentId": "home",
            "pollSeconds": 60,
            "subscriptions": [
                {"id": 1, "platform": "x", "handle": "broken", "intervalMinutes": 1, "enabled": True},
                {"id": 2, "platform": "binance_square", "handle": "working", "intervalMinutes": 1, "enabled": True},
            ],
        }


class FailingProvider:
    def fetch(self, target, checkpoint, limit):
        raise RuntimeError("provider internals must not escape")


class BinanceProvider(Provider):
    def fetch(self, target, checkpoint, limit):
        result = super().fetch(target, checkpoint, limit)
        post = result.posts[0]
        posts = [CollectedPost("binance_square", post.external_id, post.author_handle, post.author_name, post.author_avatar_url, post.published_at, post.url, post.raw_content, post.raw_payload, post.content_hash)]
        return PostFetchResult(posts, posts[-1].external_id)

    def health(self):
        return ProviderHealth("healthy")


def test_provider_failure_does_not_block_other_providers_or_heartbeat(tmp_path):
    api = IsolatedProviderApi()
    store = CollectorStore(tmp_path / "db.sqlite")
    scheduler = CollectorScheduler(
        store,
        api,
        {"x": FailingProvider(), "binance_square": BinanceProvider()},
    )

    assert scheduler.run_once(datetime(2026, 7, 10, tzinfo=UTC)) == [2]
    assert store.checkpoint_for(1) is None
    assert store.checkpoint_for(2) == "working-1"
    assert api.heartbeats[-1]["status"] == "degraded"
    assert api.heartbeats[-1]["providers"] == [
        {"platform": "binance_square", "status": "healthy", "message": None},
        {"platform": "x", "status": "failed", "message": "Provider fetch failed"},
    ]


class TradeApi(Api):
    def fetch_config(self):
        return {
            "agentId": "home",
            "pollSeconds": 60,
            "subscriptions": [
                {
                    "id": 21,
                    "platform": "binance_copy",
                    "handle": "熬鹰资本",
                    "accountId": "5075281354358777856",
                    "intervalMinutes": 1,
                    "enabled": True,
                }
            ],
        }


class TradeProvider:
    def __init__(self):
        self.targets: list[ProviderTarget] = []
        self._health = ProviderHealth("authenticated")

    def fetch(self, target, current_checkpoint, limit):
        self.targets.append(target)
        return TradeRecordFetchResult(
            records=[sample_record("1", "OPEN", "LONG", "0.10")],
            candidate_checkpoint=checkpoint("1"),
            history_complete=False,
        )

    def health(self):
        return self._health


def test_scheduler_creates_trade_baseline_with_fixed_account_target(tmp_path, capsys):
    provider = TradeProvider()
    api = TradeApi()
    store = CollectorStore(tmp_path / "db.sqlite")
    scheduler = CollectorScheduler(store, api, {"binance_copy": provider})
    now = datetime(2026, 8, 9, tzinfo=UTC)

    assert scheduler.run_once(now) == [21]

    assert provider.targets == [
        ProviderTarget(21, "binance_copy", "5075281354358777856", "熬鹰资本")
    ]
    assert store.pending_posts() == []
    assert store.checkpoint_for(21) == checkpoint("1")
    assert api.position_replacements[0][0:2] == ("home", 21)
    assert api.position_replacements[0][2][0]["symbol"] == "BTCUSDT"
    assert api.position_replacements[0][2][0]["status"] == "ACTIVE"
    assert api.position_replacements[0][3] is None
    assert api.position_replacements[0][4][0]["action"] == "OPEN"
    assert scheduler.next_check[21] == now + timedelta(minutes=1)
    assert "status=baseline_created" in capsys.readouterr().out


class CutoffTradeApi(TradeApi):
    def __init__(self, position_start_at: str):
        super().__init__()
        self.position_start_at = position_start_at
        self.uploaded_batches: list[list[dict]] = []

    def fetch_config(self):
        config = super().fetch_config()
        config["subscriptions"][0]["positionStartAt"] = self.position_start_at
        return config

    def upload(self, agent_id, posts):
        self.uploaded_batches.append(posts)
        return super().upload(agent_id, posts)


def test_scheduler_skips_trade_fetch_before_configured_cutoff(tmp_path, capsys):
    provider = TradeProvider()
    api = CutoffTradeApi("2026-08-09T01:00:00Z")
    store = CollectorStore(tmp_path / "db.sqlite")
    scheduler = CollectorScheduler(store, api, {"binance_copy": provider})
    now = datetime(2026, 8, 9, tzinfo=UTC)

    assert scheduler.run_once(now) == []

    assert provider.targets == []
    assert store.trade_start_for(21) == datetime(2026, 8, 9, 1, tzinfo=UTC)
    assert store.trade_baseline_initialized_for(21) is False
    assert scheduler.next_check[21] == datetime(2026, 8, 9, 1, tzinfo=UTC)
    assert "reason=before_position_start" in capsys.readouterr().out


def test_scheduler_cutoff_change_rebuilds_silent_baseline(tmp_path):
    store = CollectorStore(tmp_path / "db.sqlite")
    store.record_trade_fetch(
        21,
        ProviderTarget(21, "binance_copy", "5075281354358777856", "熬鹰资本"),
        TradeRecordFetchResult(
            [sample_record("1", "OPEN", "LONG", "0.10")],
            checkpoint("1"),
            history_complete=False,
        ),
    )
    store.record_trade_fetch(
        21,
        ProviderTarget(21, "binance_copy", "5075281354358777856", "熬鹰资本"),
        TradeRecordFetchResult(
            [
                sample_record("1", "OPEN", "LONG", "0.10"),
                sample_record("2", "INCREASE", "LONG", "0.05"),
            ],
            checkpoint("2"),
            history_complete=False,
        ),
    )
    assert len(store.pending_posts()) == 1

    position_start_at = datetime(2026, 8, 8, tzinfo=UTC)
    api = CutoffTradeApi(position_start_at.isoformat())
    provider = TradeProvider()
    scheduler = CollectorScheduler(store, api, {"binance_copy": provider})

    assert scheduler.run_once(datetime(2026, 8, 9, 3, tzinfo=UTC)) == [21]

    assert provider.targets == [
        ProviderTarget(
            21,
            "binance_copy",
            "5075281354358777856",
            "熬鹰资本",
            position_start_at,
        )
    ]
    assert store.checkpoint_for(21) == checkpoint("1")
    assert len(store.trade_operation_snapshots_for(21)) == 1
    assert store.pending_posts() == []
    assert api.uploaded_batches == []


class UnhealthyTradeProvider(TradeProvider):
    def fetch(self, target, current_checkpoint, limit):
        self.targets.append(target)
        return TradeRecordFetchResult([], current_checkpoint, history_complete=False)

    def health(self):
        return ProviderHealth("access_limited", "read access unavailable")


class RaisingTradeProvider(TradeProvider):
    def fetch(self, target, current_checkpoint, limit):
        raise RuntimeError("temporary Binance failure")


class GapTradeProvider(TradeProvider):
    def fetch(self, target, current_checkpoint, limit):
        self._health = ProviderHealth("access_limited", "checkpoint missing from overlap")
        raise TradeHistoryGap("checkpoint missing from overlap")


@pytest.mark.parametrize(
    "failed_provider",
    [UnhealthyTradeProvider(), RaisingTradeProvider()],
)
def test_scheduler_marks_trade_position_stale_without_advancing_checkpoint(
    tmp_path, failed_provider
):
    store = CollectorStore(tmp_path / "db.sqlite")
    store.record_trade_fetch(
        21,
        ProviderTarget(21, "binance_copy", "5075281354358777856", "熬鹰资本"),
        TradeRecordFetchResult(
            [sample_record("1", "OPEN", "LONG", "0.10")],
            checkpoint("1"),
            history_complete=False,
        ),
    )
    scheduler = CollectorScheduler(
        store,
        TradeApi(),
        {"binance_copy": failed_provider},
    )
    before = store.checkpoint_for(21)

    assert scheduler.run_once(datetime(2026, 8, 9, 1, tzinfo=UTC)) == []

    assert store.checkpoint_for(21) == before
    position = store.position_for(21, "BTCUSDT", "LONG")
    assert position is not None
    assert position.status == "STALE"
    assert position.quantity == Decimal("0.10")


def test_scheduler_marks_trade_position_unknown_when_overlap_has_a_gap(tmp_path):
    store = CollectorStore(tmp_path / "db.sqlite")
    store.record_trade_fetch(
        21,
        ProviderTarget(21, "binance_copy", "5075281354358777856", "熬鹰资本"),
        TradeRecordFetchResult(
            [sample_record("1", "OPEN", "LONG", "0.10")],
            checkpoint("1"),
            history_complete=False,
        ),
    )
    scheduler = CollectorScheduler(
        store,
        TradeApi(),
        {"binance_copy": GapTradeProvider()},
    )

    assert scheduler.run_once(datetime(2026, 8, 9, 1, tzinfo=UTC)) == []

    position = store.position_for(21, "BTCUSDT", "LONG")
    assert position is not None
    assert position.status == "UNKNOWN"
    assert position.quantity is None
    assert store.checkpoint_for(21) == checkpoint("1")


class OfflineTradeApi(TradeApi):
    def __init__(self):
        super().__init__()
        self.uploaded_batches: list[list[dict]] = []

    def upload(self, agent_id, posts):
        self.uploaded_batches.append(posts)
        raise RuntimeError("backend unavailable")


class SequencedTradeProvider(TradeProvider):
    def __init__(self):
        super().__init__()
        self.round = 0
        self._health = ProviderHealth("healthy")

    def fetch(self, target, current_checkpoint, limit):
        self.targets.append(target)
        self.round += 1
        first = sample_record("1", "OPEN", "LONG", "0.10")
        if self.round == 1:
            return TradeRecordFetchResult(
                [first], checkpoint("1"), history_complete=False
            )
        second = sample_record("2", "INCREASE", "LONG", "0.05")
        if self.round in {2, 3}:
            return TradeRecordFetchResult(
                [first, second], checkpoint("2"), history_complete=False
            )
        self._health = ProviderHealth("login_required", "read access unavailable")
        return TradeRecordFetchResult(
            [], current_checkpoint, history_complete=False
        )


def test_trade_scheduler_end_to_end_baseline_dedupes_and_marks_stale(tmp_path):
    api = OfflineTradeApi()
    provider = SequencedTradeProvider()
    store = CollectorStore(tmp_path / "db.sqlite")
    scheduler = CollectorScheduler(store, api, {"binance_copy": provider})
    started_at = datetime(2026, 8, 9, tzinfo=UTC)

    assert scheduler.run_once(started_at) == [21]
    assert store.checkpoint_for(21) == checkpoint("1")
    assert store.pending_posts() == []

    assert scheduler.run_once(started_at + timedelta(minutes=1)) == [21]
    pending_after_change = store.pending_posts()
    assert len(pending_after_change) == 1
    assert pending_after_change[0].external_id == "5075281354358777856:2:r1"
    assert "熬鹰资本" not in pending_after_change[0].external_id
    assert pending_after_change[0].payload["rawPayload"]["action"] == "ADD"
    assert store.checkpoint_for(21) == checkpoint("2")

    assert scheduler.run_once(started_at + timedelta(minutes=2)) == [21]
    assert [post.id for post in store.pending_posts()] == [
        pending_after_change[0].id
    ]
    assert store.checkpoint_for(21) == checkpoint("2")

    assert scheduler.run_once(started_at + timedelta(minutes=3)) == []
    assert store.checkpoint_for(21) == checkpoint("2")
    position = store.position_for(21, "BTCUSDT", "LONG")
    assert position is not None
    assert position.status == "STALE"
    assert position.quantity == Decimal("0.15")
    assert len(store.pending_posts()) == 1
