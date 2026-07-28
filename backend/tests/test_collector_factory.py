from pathlib import Path
from types import SimpleNamespace

from app.collectors.bootstrap import BootstrapCollector
from app.collectors.factory import build_x_collectors
from app.collectors import factory


def test_x_scheduler_collectors_do_not_include_static_bootstrap(monkeypatch) -> None:
    monkeypatch.setattr(
        factory,
        "get_settings",
        lambda: SimpleNamespace(x_bearer_token=None, bootstrap_file=Path("missing.json")),
    )
    monkeypatch.setattr(factory.shutil, "which", lambda command: None)

    assert build_x_collectors() == []
    assert isinstance(build_x_collectors(include_bootstrap=True)[0], BootstrapCollector)
