import httpx


class NtfyNotifier:
    def __init__(self, server: str, topic: str, token: str | None = None, http=None) -> None:
        self.server = server.rstrip("/")
        self.topic = topic
        self.token = token
        self.http = http or httpx.Client(timeout=15)

    def __call__(self, title: str, message: str) -> None:
        headers = {}
        if self.token:
            headers["Authorization"] = f"Bearer {self.token}"
        response = self.http.post(
            self.server,
            headers=headers,
            json={"topic": self.topic, "title": title, "message": message},
        )
        response.raise_for_status()


class ProviderAlerter:
    def __init__(self, send, cooldown_seconds: int = 300) -> None:
        self.send, self.cooldown_seconds, self.states = send, cooldown_seconds, {}

    def update(self, platform: str, status: str, now: float) -> bool:
        status = "healthy" if status in {"healthy", "authenticated"} else status
        previous, last = self.states.get(platform, ("healthy", -self.cooldown_seconds))
        if status == "healthy" and previous != "healthy":
            self.send(f"{platform} 已恢复", "Provider 已恢复健康状态")
            self.states[platform] = (status, now)
            return True
        if status in {"login_required", "failed"} and (previous != status or now - last >= self.cooldown_seconds):
            self.send(f"{platform} 需要处理", f"Provider 状态：{status}")
            self.states[platform] = (status, now)
            return True
        self.states[platform] = (status, last)
        return False
