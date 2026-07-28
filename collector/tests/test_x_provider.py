import json
import subprocess
from pathlib import Path

from collector_agent.providers.x_opencli import OpenCliXProvider


def test_x_provider_parses_fixture_filters_checkpoint_and_detects_login_required():
    output = (Path(__file__).parent / "fixtures/opencli_x.yaml").read_text()
    provider = OpenCliXProvider(runner=lambda command: (0, output, ""))
    posts = provider.fetch("senerity", "100", 20)
    assert [post.external_id for post in posts] == ["101"]
    assert posts[0].author_handle == "senerity"
    assert posts[0].author_name == "Senerity"
    assert provider.health().status == "authenticated"
    failed = OpenCliXProvider(runner=lambda command: (1, "login required", ""))
    assert failed.fetch("senerity", None, 20) == []
    assert failed.health().status == "login_required"


def test_x_provider_reports_timeout_without_advancing_checkpoint():
    def timeout(_command):
        raise subprocess.TimeoutExpired(cmd="opencli", timeout=60)

    provider = OpenCliXProvider(runner=timeout)
    assert provider.fetch("senerity", "100", 20) == []
    assert provider.health().status == "failed"
    assert provider.health().message == "OpenCLI timed out"


def test_x_provider_keeps_only_latest_posts_within_limit():
    rows = [
        {
            "id": str(external_id),
            "author": "senerity",
            "name": "Senerity",
            "created_at": f"2026-07-14T00:{external_id - 100:02d}:00Z",
            "url": f"https://x.com/senerity/status/{external_id}",
            "text": f"post {external_id}",
        }
        for external_id in range(101, 113)
    ]
    commands = []

    def runner(command):
        commands.append(command)
        return 0, json.dumps(rows), ""

    provider = OpenCliXProvider(runner=runner)
    posts = provider.fetch("senerity", "100", 5)

    assert commands == [
        ["opencli", "twitter", "tweets", "senerity", "--limit", "5", "--format", "json"]
    ]
    assert [post.external_id for post in posts] == ["108", "109", "110", "111", "112"]
