from datetime import timedelta

from collector_agent.db import CollectorStore


class CollectorScheduler:
    def __init__(
        self,
        store: CollectorStore,
        api,
        providers: dict,
        alerter=None,
        initial_fetch_limit: int = 1,
        catchup_fetch_limit: int = 5,
    ) -> None:
        self.store, self.api, self.providers = store, api, providers
        self.alerter = alerter
        self.initial_fetch_limit = initial_fetch_limit
        self.catchup_fetch_limit = catchup_fetch_limit
        self.subscriptions: list[dict] = []
        self.next_check: dict[int, object] = {}
        self.active: set[int] = set()
        self.upload_failures = 0
        self.next_upload_at = None
        self.provider_failures: dict[str, str] = {}

    @staticmethod
    def _log_subscription(now, subscription: dict, status: str, **details) -> None:
        timestamp = now.isoformat().replace("+00:00", "Z")
        fields = [
            timestamp,
            "collector",
            f"subscription={subscription['id']}",
            f"platform={subscription['platform']}",
            f"handle={subscription['handle']}",
            f"status={status}",
        ]
        fields.extend(f"{key}={value}" for key, value in details.items())
        print(" ".join(fields), flush=True)

    def _provider_statuses(self, now) -> list[dict]:
        statuses = []
        for platform, provider in sorted(self.providers.items()):
            if platform in self.provider_failures:
                status = "failed"
                message = self.provider_failures[platform]
            else:
                health = provider.health() if hasattr(provider, "health") else None
                status = health.status if health else "healthy"
                message = health.message if health else None
            statuses.append({"platform": platform, "status": status, "message": message})
            if self.alerter is not None:
                self.alerter.update(platform, status, now.timestamp())
        return statuses

    def run_once(self, now) -> list[int]:
        config = self.api.fetch_config()
        self.subscriptions = config["subscriptions"]
        ran = []
        for subscription in self.subscriptions:
            subscription_id = subscription["id"]
            if not subscription["enabled"]:
                self._log_subscription(now, subscription, "skipped", reason="disabled")
                continue
            if subscription_id in self.active:
                self._log_subscription(now, subscription, "skipped", reason="active")
                continue
            if now < self.next_check.get(subscription_id, now):
                self._log_subscription(now, subscription, "skipped", reason="not_due")
                continue
            provider = self.providers.get(subscription["platform"])
            if provider is None:
                self._log_subscription(now, subscription, "skipped", reason="provider_missing")
                continue
            self.active.add(subscription_id)
            try:
                checkpoint_before = self.store.checkpoint_for(subscription_id)
                limit = (
                    self.initial_fetch_limit
                    if checkpoint_before is None
                    else self.catchup_fetch_limit
                )
                posts = provider.fetch(subscription["handle"], checkpoint_before, limit)
                health = provider.health() if hasattr(provider, "health") else None
                if health is not None and health.status not in {"healthy", "authenticated"}:
                    self.provider_failures.pop(subscription["platform"], None)
                    self._log_subscription(
                        now,
                        subscription,
                        "failed",
                        error="ProviderHealth",
                        provider_status=health.status,
                    )
                    continue
                checkpoint = posts[-1].external_id if posts else checkpoint_before
                self.store.record_fetch(subscription_id, checkpoint, posts)
                self.provider_failures.pop(subscription["platform"], None)
                ran.append(subscription_id)
                self._log_subscription(now, subscription, "success", fetched=len(posts))
            except Exception as exc:
                self.provider_failures[subscription["platform"]] = "Provider fetch failed"
                self._log_subscription(
                    now,
                    subscription,
                    "failed",
                    error=type(exc).__name__,
                )
            finally:
                self.next_check[subscription_id] = now + timedelta(minutes=max(1, subscription["intervalMinutes"]))
                self.active.remove(subscription_id)
        pending = self.store.pending_posts()
        if pending and (self.next_upload_at is None or now >= self.next_upload_at):
            try:
                response = self.api.upload(config["agentId"], [post.payload for post in pending])
            except Exception:
                self.upload_failures += 1
                delay_seconds = min(300, 2 ** min(self.upload_failures, 8))
                self.next_upload_at = now + timedelta(seconds=delay_seconds)
            else:
                self.store.apply_upload_results(response.get("items", []))
                self.upload_failures = 0
                self.next_upload_at = None
        providers = self._provider_statuses(now)
        overall_status = "healthy" if all(row["status"] in {"healthy", "authenticated"} for row in providers) else "degraded"
        self.api.heartbeat({"agentId": config["agentId"], "version": "0.1.0", "status": overall_status, "providers": providers, "outboxPending": len(self.store.pending_posts()), "checkedAt": now.isoformat()})
        return ran
