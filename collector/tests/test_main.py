import runpy
from pathlib import Path

from collector_agent.config import CollectorSettings
from collector_agent.main import build_providers
from collector_agent.models import ProviderTarget
from collector_agent.providers.binance_square import BinanceSquareProvider
from collector_agent.providers.x_opencli import OpenCliXProvider


def test_build_providers_wires_opencli_and_binance_browser_client(monkeypatch):
    clients = []

    class Client:
        def __init__(self, **kwargs):
            clients.append(kwargs)

        def user_by_username(self, handle):
            return {"username": handle, "squareUid": "uid", "displayName": handle}

        def user_posts(self, square_uid):
            return {"contents": []}

    monkeypatch.setattr("collector_agent.main.BinanceSquareBrowserClient", Client)
    settings = CollectorSettings(
        public_api_url="https://api.example",
        collector_agent_id="home",
        collector_token="token",
        db_path=Path("collector.sqlite3"),
        binance_browser_executable="/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
        binance_square_lang="zh-CN",
    )
    providers = build_providers(settings)

    assert isinstance(providers["x"], OpenCliXProvider)
    assert isinstance(providers["binance_square"], BinanceSquareProvider)
    target = ProviderTarget(2, "binance_square", None, "btc7873")
    assert providers["binance_square"].fetch(target, None, 1).posts == []
    assert clients == [{
        "browser_executable": "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
        "lang": "zh-CN",
    }]


def test_package_module_entrypoint_invokes_main(monkeypatch):
    called = []
    monkeypatch.setattr("collector_agent.main.main", lambda: called.append(True))

    runpy.run_module("collector_agent", run_name="__main__")

    assert called == [True]
