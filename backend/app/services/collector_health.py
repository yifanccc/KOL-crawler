import json
from datetime import UTC

from sqlalchemy import desc, select
from sqlalchemy.orm import Session

from app.models import CollectorAgent


def collector_health_payload(session: Session) -> dict | None:
    agent = session.scalar(
        select(CollectorAgent).order_by(desc(CollectorAgent.last_heartbeat_at)).limit(1)
    )
    if agent is None:
        return None
    try:
        providers = json.loads(agent.providers_json)
    except json.JSONDecodeError:
        providers = []
    if not isinstance(providers, list):
        providers = []
    last_seen = agent.last_heartbeat_at
    if last_seen.tzinfo is None:
        last_seen = last_seen.replace(tzinfo=UTC)
    else:
        last_seen = last_seen.astimezone(UTC)
    return {
        "agentId": agent.agent_id,
        "status": agent.status,
        "providers": providers,
        "outboxPending": agent.outbox_pending,
        "lastSeenAt": last_seen.isoformat().replace("+00:00", "Z"),
    }
