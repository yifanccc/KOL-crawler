import time
from typing import Any
from uuid import uuid4


REPLAY_HEADER_KEYS = {
    "bnc-uuid",
    "bnc-time-zone",
    "csrftoken",
    "clienttype",
    "lang",
    "versioncode",
    "device-info",
    "fvideo-id",
    "fvideo-token",
}


class BinanceSquareBrowserClient:
    def __init__(self, browser_executable: str | None = None, lang: str = "zh-CN") -> None:
        self.browser_executable = browser_executable
        self.lang = lang
        self._playwright = None
        self._browser = None
        self._context = None
        self._page = None
        self._headers: dict[str, str] = {}

    def _ensure_page(self) -> None:
        if self._page is not None:
            return
        from playwright.sync_api import sync_playwright

        self._playwright = sync_playwright().start()
        launch_options: dict[str, Any] = {
            "headless": True,
            "args": [
                "--no-sandbox",
                "--disable-dev-shm-usage",
                "--disable-blink-features=AutomationControlled",
            ],
        }
        if self.browser_executable:
            launch_options["executable_path"] = self.browser_executable
        self._browser = self._playwright.chromium.launch(**launch_options)
        self._context = self._browser.new_context(
            user_agent=(
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/129.0.0.0 Safari/537.36"
            ),
            locale=self.lang,
            viewport={"width": 1440, "height": 900},
            extra_http_headers={"accept-language": f"{self.lang},en;q=0.5"},
        )
        self._page = self._context.new_page()

        def capture_headers(request) -> None:
            if "/bapi/composite/" not in request.url or "device-info" in self._headers:
                return
            self._headers.update(
                {
                    key: value
                    for key, value in request.headers.items()
                    if key in REPLAY_HEADER_KEYS
                }
            )

        self._page.on("request", capture_headers)
        self._page.goto(
            f"https://www.binance.com/{self.lang}/square",
            wait_until="domcontentloaded",
            timeout=30_000,
        )
        deadline = time.monotonic() + 15
        while "device-info" not in self._headers and time.monotonic() < deadline:
            self._page.wait_for_timeout(200)
        if "device-info" not in self._headers:
            self.close()
            raise RuntimeError("Binance browser fingerprint headers were not available")

    def _request(
        self,
        method: str,
        path: str,
        payload: dict[str, Any] | None = None,
    ) -> dict[str, Any] | None:
        self._ensure_page()
        trace_id = str(uuid4())
        headers = {
            **self._headers,
            "x-trace-id": trace_id,
            "x-ui-request-trace": trace_id,
        }
        if payload is not None:
            headers["content-type"] = "application/json"
        result = self._page.evaluate(
            """async ({method, path, payload, headers}) => {
                const response = await fetch(path, {
                    method,
                    headers,
                    body: payload ? JSON.stringify(payload) : undefined,
                    credentials: "include",
                });
                return {status: response.status, text: await response.text()};
            }""",
            {"method": method, "path": path, "payload": payload, "headers": headers},
        )
        if not 200 <= result["status"] < 300:
            raise RuntimeError(f"Binance API returned HTTP {result['status']}")
        import json

        response = json.loads(result["text"])
        if not response.get("success"):
            raise RuntimeError(response.get("message") or "Binance API request failed")
        data = response.get("data")
        return data if isinstance(data, dict) else None

    def user_by_username(self, username: str) -> dict[str, Any] | None:
        return self._request(
            "POST",
            "/bapi/composite/v3/friendly/pgc/user/client",
            {
                "username": username,
                "getFollowCount": True,
                "queryFollowersInfo": True,
                "queryRelationTokens": True,
            },
        )

    def user_posts(self, square_uid: str) -> dict[str, Any] | None:
        return self._request(
            "GET",
            "/bapi/composite/v2/friendly/pgc/content/"
            "queryUserProfilePageContentsWithFilter"
            f"?targetSquareUid={square_uid}&timeOffset={int(time.time() * 1000)}&filterType=ALL",
        )

    def close(self) -> None:
        if self._page is not None:
            self._page.close()
        if self._context is not None:
            self._context.close()
        if self._browser is not None:
            self._browser.close()
        if self._playwright is not None:
            self._playwright.stop()
        self._page = None
        self._context = None
        self._browser = None
        self._playwright = None
        self._headers = {}
