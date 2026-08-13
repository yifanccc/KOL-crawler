import httpx


class CollectorApiClient:
    def __init__(self, base_url: str, token: str, http: httpx.Client | None = None) -> None:
        self.base_url = base_url.rstrip("/")
        self.headers = {"Authorization": f"Bearer {token}"}
        self.http = http or httpx.Client(timeout=20)

    def fetch_config(self) -> dict:
        response = self.http.get(f"{self.base_url}/api/v1/collector/config", headers=self.headers)
        response.raise_for_status()
        return response.json()

    def upload(self, agent_id: str, posts: list[dict]) -> dict:
        response = self.http.post(f"{self.base_url}/api/v1/collector/posts", headers=self.headers, json={"agentId": agent_id, "posts": posts})
        response.raise_for_status()
        return response.json()

    def replace_positions(
        self,
        agent_id: str,
        subscription_id: int,
        positions: list[dict],
        account: dict | None = None,
        operations: list[dict] | None = None,
    ) -> dict:
        payload = {"agentId": agent_id, "positions": positions}
        if account is not None:
            payload["account"] = account
        if operations is not None:
            payload["operations"] = operations
        response = self.http.put(
            f"{self.base_url}/api/v1/collector/subscriptions/{subscription_id}/positions",
            headers=self.headers,
            json=payload,
        )
        response.raise_for_status()
        return response.json()

    def heartbeat(self, payload: dict) -> dict:
        response = self.http.post(f"{self.base_url}/api/v1/collector/heartbeat", headers=self.headers, json=payload)
        response.raise_for_status()
        return response.json()

    def close(self) -> None:
        self.http.close()
