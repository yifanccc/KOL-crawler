from __future__ import annotations

import json
import sys
from datetime import datetime
from pathlib import Path
from typing import Any


def parse_time(value: str | None) -> str | None:
    if not value:
        return None
    for fmt in ("%a %b %d %H:%M:%S %z %Y", "%Y-%m-%dT%H:%M:%S%z"):
        try:
            return datetime.strptime(value, fmt).isoformat()
        except ValueError:
            continue
    return None


def main() -> int:
    if len(sys.argv) != 4:
        print("usage: build_bootstrap_from_opencli.py <input-json> <output-json> <handle>")
        return 2

    input_path = Path(sys.argv[1])
    output_path = Path(sys.argv[2])
    handle = sys.argv[3].lstrip("@")
    payload: list[dict[str, Any]] = json.loads(input_path.read_text())
    posts = []
    for item in payload[:10]:
        post_id = str(item.get("id") or "")
        text = str(item.get("text") or "").strip()
        if not post_id or not text:
            continue
        author = str(item.get("author") or handle).lstrip("@")
        posts.append(
            {
                "platform": "x",
                "external_id": post_id,
                "url": item.get("url") or f"https://x.com/{author}/status/{post_id}",
                "author_handle": author,
                "author_name": item.get("name") or author,
                "published_at": parse_time(item.get("created_at")),
                "raw_text": text,
            }
        )

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(posts, ensure_ascii=False, indent=2) + "\n")
    print(f"wrote {len(posts)} posts to {output_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
