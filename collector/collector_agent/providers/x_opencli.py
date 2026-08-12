import json
import subprocess
from datetime import datetime

from collector_agent.models import CollectedPost, PostFetchResult, ProviderTarget
from collector_agent.providers.base import ProviderHealth


def _parse_published_at(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return datetime.strptime(value, "%a %b %d %H:%M:%S %z %Y")


class OpenCliXProvider:
    def __init__(self, runner=None) -> None:
        self.runner = runner or self._run
        self._health = ProviderHealth("healthy")

    def _run(self, command):
        completed = subprocess.run(command, capture_output=True, text=True, timeout=60, check=False)
        return completed.returncode, completed.stdout, completed.stderr

    def fetch(
        self, target: ProviderTarget, checkpoint: str | None, limit: int
    ) -> PostFetchResult:
        handle = target.handle
        try:
            code, output, error = self.runner(["opencli", "twitter", "tweets", handle, "--limit", str(limit), "--format", "json"])
        except subprocess.TimeoutExpired:
            self._health = ProviderHealth("failed", "OpenCLI timed out")
            return PostFetchResult([], checkpoint)
        except OSError:
            self._health = ProviderHealth("failed", "OpenCLI could not be started")
            return PostFetchResult([], checkpoint)
        if code or "login required" in (output + error).lower() or "verification" in (output + error).lower():
            self._health = ProviderHealth("login_required" if "login" in (output + error).lower() else "failed")
            return PostFetchResult([], checkpoint)
        try:
            rows = json.loads(output)
            if not isinstance(rows, list):
                raise ValueError("OpenCLI JSON root is not a list")
            posts = [
                CollectedPost(
                    "x",
                    str(row["id"]),
                    row.get("author") or handle.lstrip("@"),
                    row.get("name") or row.get("author"),
                    row.get("avatar_url"),
                    _parse_published_at(row.get("created_at")),
                    row["url"],
                    row["text"],
                    row,
                    None,
                )
                for row in rows
                if isinstance(row, dict) and row.get("id") and row.get("text") and row.get("url")
            ]
            filtered = [post for post in posts if checkpoint is None or int(post.external_id) > int(checkpoint)]
        except (json.JSONDecodeError, KeyError, TypeError, ValueError):
            self._health = ProviderHealth("failed", "invalid OpenCLI JSON")
            return PostFetchResult([], checkpoint)
        self._health = ProviderHealth("authenticated")
        ordered = sorted(filtered, key=lambda post: int(post.external_id))
        selected = ordered[-limit:]
        candidate_checkpoint = selected[-1].external_id if selected else checkpoint
        return PostFetchResult(selected, candidate_checkpoint)

    def health(self) -> ProviderHealth:
        return self._health
