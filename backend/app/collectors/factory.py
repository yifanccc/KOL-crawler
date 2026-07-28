from app.collectors.base import CollectorAdapter
from app.collectors.binance_square import BinanceSquareCollector
from app.collectors.bootstrap import BootstrapCollector
from app.collectors.opencli_twitter import OpenCliTwitterCollector
from app.collectors.x_official import XOfficialCollector
from app.core.config import get_settings


def _x_user_id_resolver(handle: str) -> str:
    import httpx

    settings = get_settings()
    response = httpx.get(
        f"https://api.x.com/2/users/by/username/{handle.lstrip('@')}",
        headers={"Authorization": f"Bearer {settings.x_bearer_token}"},
        timeout=20,
    )
    response.raise_for_status()
    return str(response.json()["data"]["id"])


def build_x_collectors(include_bootstrap: bool = False) -> list[CollectorAdapter]:
    settings = get_settings()
    collectors: list[CollectorAdapter] = []
    if settings.x_bearer_token:
        collectors.append(XOfficialCollector(settings.x_bearer_token, _x_user_id_resolver))
    if shutil.which("opencli"):
        collectors.append(OpenCliTwitterCollector())
    if include_bootstrap:
        collectors.append(BootstrapCollector(settings.bootstrap_file))
    return collectors


def build_collectors_for_platform(platform: str) -> list[CollectorAdapter]:
    if platform == "x":
        return build_x_collectors(include_bootstrap=False)
    if platform == "binance_square":
        return [BinanceSquareCollector()]
    return []
import shutil
