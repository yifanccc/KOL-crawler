from collector_agent.config import CollectorSettings


def test_config_poll_defaults_to_one_minute(monkeypatch, tmp_path):
    monkeypatch.setenv("PUBLIC_API_URL", "http://example.test/kol")
    monkeypatch.setenv("COLLECTOR_AGENT_ID", "home")
    monkeypatch.setenv("COLLECTOR_TOKEN", "token")
    monkeypatch.setenv("COLLECTOR_DB_PATH", str(tmp_path / "collector.sqlite3"))
    monkeypatch.delenv("CONFIG_POLL_SECONDS", raising=False)
    monkeypatch.delenv("CATCHUP_FETCH_LIMIT", raising=False)

    settings = CollectorSettings.from_env()

    assert settings.config_poll_seconds == 60
    assert settings.catchup_fetch_limit == 5


def test_catchup_fetch_limit_is_configurable_and_clamped(monkeypatch, tmp_path):
    monkeypatch.setenv("PUBLIC_API_URL", "http://example.test/kol")
    monkeypatch.setenv("COLLECTOR_AGENT_ID", "home")
    monkeypatch.setenv("COLLECTOR_TOKEN", "token")
    monkeypatch.setenv("COLLECTOR_DB_PATH", str(tmp_path / "collector.sqlite3"))
    monkeypatch.setenv("CATCHUP_FETCH_LIMIT", "7")

    assert CollectorSettings.from_env().catchup_fetch_limit == 7

    monkeypatch.setenv("CATCHUP_FETCH_LIMIT", "0")
    assert CollectorSettings.from_env().catchup_fetch_limit == 1
