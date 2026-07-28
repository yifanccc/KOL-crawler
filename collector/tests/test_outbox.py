from datetime import UTC, datetime

from collector_agent.db import CollectorStore
from collector_agent.models import CollectedPost


def post(external_id: str) -> CollectedPost:
    return CollectedPost(
        platform="x", external_id=external_id, author_handle="senerity", author_name="Senerity",
        author_avatar_url=None, published_at=datetime(2026, 7, 10, tzinfo=UTC),
        url=f"https://x.com/senerity/status/{external_id}", raw_content=f"post {external_id}", raw_payload={"id": external_id}, content_hash=external_id,
    )


def test_outbox_persists_checkpoint_and_retries_after_restart(tmp_path) -> None:
    path = tmp_path / "collector.sqlite3"
    store = CollectorStore(path)
    inserted = store.record_fetch(1, "10", [post("9"), post("10")])
    store.close()

    restarted = CollectorStore(path)
    assert inserted == 2
    assert restarted.checkpoint_for(1) == "10"
    assert [row.external_id for row in restarted.pending_posts()] == ["9", "10"]
    assert restarted.record_fetch(1, "10", [post("10")]) == 0
    restarted.apply_upload_results([
        {"externalId": "9", "status": "accepted"},
        {"externalId": "10", "status": "invalid", "reason": "bad payload"},
    ])
    assert restarted.pending_posts() == []
    assert restarted.dead_letter_count() == 1


def test_upload_results_match_same_external_id_in_submission_order(tmp_path) -> None:
    store = CollectorStore(tmp_path / "collector.sqlite3")
    assert store.record_fetch(1, "same", [post("same")]) == 1
    assert store.record_fetch(2, "same", [post("same")]) == 1

    store.apply_upload_results(
        [
            {"externalId": "same", "status": "accepted"},
            {"externalId": "same", "status": "invalid", "reason": "wrong subscription"},
        ]
    )

    assert store.pending_posts() == []
    assert store.dead_letter_count() == 1
