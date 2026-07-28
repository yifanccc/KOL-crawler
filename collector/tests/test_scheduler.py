from datetime import UTC, datetime, timedelta

from collector_agent.db import CollectorStore
from collector_agent.models import CollectedPost
from collector_agent.scheduler import CollectorScheduler
from collector_agent.providers.base import ProviderHealth


class Api:
    def __init__(self):
        self.heartbeats = []

    def fetch_config(self): return {"agentId": "home", "pollSeconds": 60, "subscriptions": [{"id": 1, "platform": "x", "handle": "one", "intervalMinutes": 1, "enabled": True}, {"id": 2, "platform": "x", "handle": "two", "intervalMinutes": 2, "enabled": True}]}
    def upload(self, agent_id, posts): return {"items": [{"externalId": post["externalId"], "status": "accepted"} for post in posts]}
    def heartbeat(self, payload): self.heartbeats.append(payload); return {}


class Provider:
    def fetch(self, handle, checkpoint, limit):
        return [CollectedPost("x", handle + "-1", handle, handle, None, datetime(2026, 7, 10, tzinfo=UTC), "https://x.com", "$BTC", {}, handle)]

    def health(self):
        return ProviderHealth("authenticated")


class ReturnedHealthFailureProvider:
    def fetch(self, handle, checkpoint, limit):
        return []

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

    def fetch(self, handle, checkpoint, limit):
        self.limits.append(limit)
        self.sequence += 1
        return [
            CollectedPost(
                "x",
                str(self.sequence),
                handle,
                handle,
                None,
                datetime(2026, 7, 10, tzinfo=UTC),
                "https://x.com",
                "$BTC",
                {},
                None,
            )
        ]


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

    def fetch(self, handle, checkpoint, limit):
        self.calls.append((handle, checkpoint, limit))
        return [
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

    assert provider.calls == [("one", "100", 5)]
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
    def fetch(self, handle, checkpoint, limit):
        raise RuntimeError("provider internals must not escape")


class BinanceProvider(Provider):
    def fetch(self, handle, checkpoint, limit):
        post = super().fetch(handle, checkpoint, limit)[0]
        return [CollectedPost("binance_square", post.external_id, post.author_handle, post.author_name, post.author_avatar_url, post.published_at, post.url, post.raw_content, post.raw_payload, post.content_hash)]

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
