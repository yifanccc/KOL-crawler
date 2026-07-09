# KOL Signal Crawler Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build v1 of a small-scale financial KOL monitoring system that collects X and experimental Binance Square posts, structures them into trading signals, sends ntfy alerts, and presents a public signal-tape web UI with private management pages.

**Architecture:** Use a FastAPI modular monolith with a built-in scheduler, MySQL for durable state, Redis for per-KOL locks, and Next.js for the public and admin web UI. Keep X as the stable official API path and isolate Binance Square Playwright scraping as an experimental collector that cannot block the X path.

**Tech Stack:** Python 3.12, FastAPI, SQLAlchemy 2.x, Alembic, PyMySQL, Redis, httpx, Pydantic v2, pytest, Next.js 15, React 19, TypeScript, Tailwind CSS, Vitest, Playwright, Docker Compose, MySQL 8, Redis 7.

## Global Constraints

- Scale: 10-30 KOL subscriptions.
- Scheduling: per-KOL `interval_minutes`, minimum 1 minute.
- Access model: public read-only pages plus private logged-in management pages.
- Model integration: OpenAI-compatible provider configuration through `base_url`, `api_key`, `model`, and generation parameters.
- Database: MySQL. Docker Compose includes MySQL by default, but deployment can reuse an existing MySQL instance through `DATABASE_URL`.
- Runtime architecture: FastAPI modular monolith, MySQL, Redis, Next.js, and an optional Playwright worker for Binance Square.
- Homepage: trading signal feed, styled as a modern signal tape.
- Visual direction: Graphite / Cyan palette, not retro green terminal.
- Notification: ntfy pushes only actionable trading signals by default, with configurable rules.
- Binance Square support is experimental and must never block the stable X collector path.
- A-shares are supported for symbol recognition and filtering only in v1.
- The UI and notifications must present KOL-derived research signals, not investment advice or direct trade instructions.

---

## File Structure

Create this structure:

```text
backend/
  alembic.ini
  pyproject.toml
  Dockerfile
  alembic/
    env.py
    versions/
  app/
    __init__.py
    main.py
    core/
      __init__.py
      config.py
      crypto.py
      security.py
    db/
      __init__.py
      base.py
      session.py
    models/
      __init__.py
      asset.py
      crawl_run.py
      kol.py
      model_config.py
      notification.py
      raw_post.py
      signal.py
      subscription.py
      user.py
    schemas/
      __init__.py
      admin.py
      common.py
      signal.py
    services/
      __init__.py
      assets.py
      ingestion.py
      locks.py
      notifications.py
      scheduler.py
      structurer.py
    collectors/
      __init__.py
      base.py
      binance_square.py
      x_official.py
    routers/
      __init__.py
      admin.py
      public.py
  tests/
    conftest.py
    fixtures/
      binance_square_sample.html
    test_assets.py
    test_collectors.py
    test_ingestion.py
    test_models.py
    test_notifications.py
    test_public_api.py
    test_scheduler.py
    test_structurer.py

frontend/
  package.json
  next.config.ts
  tsconfig.json
  Dockerfile
  src/
    app/
      globals.css
      layout.tsx
      page.tsx
      admin/
        page.tsx
      assets/
        [symbol]/
          page.tsx
      kols/
        [id]/
          page.tsx
    components/
      AdminShell.tsx
      FilterRail.tsx
      SignalCard.tsx
      SignalTape.tsx
      TopNav.tsx
    lib/
      api.ts
      types.ts
    test/
      SignalCard.test.tsx

docs/
  architecture.md
  configuration.md
  data-sources.md
  deployment.md
  operations.md
  prompt-guide.md

docker-compose.yml
.env.example
README.md
```

Task boundaries:

- Task 1 creates a runnable empty stack.
- Task 2 creates durable schema and constraints.
- Task 3 adds auth and admin config primitives.
- Task 4 adds collector adapters.
- Task 5 adds scheduler locks and run selection.
- Task 6 adds LLM structuring and asset normalization.
- Task 7 adds ingestion orchestration and checkpoint behavior.
- Task 8 adds ntfy notification rules.
- Task 9 exposes public and admin APIs.
- Task 10 builds public web pages.
- Task 11 builds admin web pages.
- Task 12 finalizes Docker deployment and docs.

---

### Task 1: Runnable Project Scaffold

**Files:**
- Create: `backend/pyproject.toml`
- Create: `backend/app/main.py`
- Create: `backend/app/core/config.py`
- Create: `backend/tests/test_health.py`
- Create: `frontend/package.json`
- Create: `frontend/src/app/page.tsx`
- Create: `frontend/src/app/layout.tsx`
- Create: `frontend/src/app/globals.css`
- Create: `docker-compose.yml`
- Create: `.env.example`
- Create: `README.md`

**Interfaces:**
- Produces: `GET /health` returns `{"status": "ok", "service": "kol-signal-api"}`.
- Produces: frontend root page renders the text `Signal Tape`.
- Later tasks consume `Settings` from `backend/app/core/config.py`.

- [ ] **Step 1: Write the failing backend health test**

Create `backend/tests/test_health.py`:

```python
from fastapi.testclient import TestClient

from app.main import app


def test_health_endpoint_returns_service_status() -> None:
    client = TestClient(app)

    response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok", "service": "kol-signal-api"}
```

- [ ] **Step 2: Run the backend test and verify it fails before implementation**

Run:

```bash
cd backend
uv run pytest tests/test_health.py -v
```

Expected before implementation: import failure for `app.main` or `ModuleNotFoundError`.

- [ ] **Step 3: Create the backend package and health endpoint**

Create `backend/pyproject.toml`:

```toml
[project]
name = "kol-signal-api"
version = "0.1.0"
requires-python = ">=3.12"
dependencies = [
  "alembic>=1.13.2",
  "cryptography>=42.0.8",
  "fastapi>=0.115.0",
  "httpx>=0.27.0",
  "passlib[bcrypt]>=1.7.4",
  "pydantic>=2.8.0",
  "pydantic-settings>=2.4.0",
  "pymysql>=1.1.1",
  "python-jose[cryptography]>=3.3.0",
  "python-multipart>=0.0.9",
  "redis>=5.0.8",
  "sqlalchemy>=2.0.32",
  "uvicorn[standard]>=0.30.6"
]

[dependency-groups]
dev = [
  "pytest>=8.3.2",
  "pytest-mock>=3.14.0",
  "respx>=0.21.1",
  "ruff>=0.6.2"
]

[tool.pytest.ini_options]
pythonpath = ["."]
testpaths = ["tests"]

[tool.ruff]
line-length = 100
target-version = "py312"
```

Create `backend/app/core/config.py`:

```python
from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_name: str = "kol-signal-api"
    environment: str = "development"
    database_url: str = Field(
        default="mysql+pymysql://kol:kol@mysql:3306/kol_signal",
        alias="DATABASE_URL",
    )
    redis_url: str = Field(default="redis://redis:6379/0", alias="REDIS_URL")
    secret_key: str = Field(default="dev-secret-change-me", alias="SECRET_KEY")
    access_token_expire_minutes: int = Field(default=1440, alias="ACCESS_TOKEN_EXPIRE_MINUTES")

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")


@lru_cache
def get_settings() -> Settings:
    return Settings()
```

Create `backend/app/main.py`:

```python
from fastapi import FastAPI

from app.core.config import get_settings

settings = get_settings()

app = FastAPI(title="KOL Signal API")


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok", "service": settings.app_name}
```

- [ ] **Step 4: Run the backend health test and verify it passes**

Run:

```bash
cd backend
uv run pytest tests/test_health.py -v
```

Expected: `1 passed`.

- [ ] **Step 5: Create the minimal frontend**

Create `frontend/package.json`:

```json
{
  "name": "kol-signal-web",
  "version": "0.1.0",
  "private": true,
  "scripts": {
    "dev": "next dev",
    "build": "next build",
    "start": "next start",
    "test": "vitest run"
  },
  "dependencies": {
    "@vitejs/plugin-react": "^4.3.1",
    "lucide-react": "^0.468.0",
    "next": "^15.0.0",
    "react": "^19.0.0",
    "react-dom": "^19.0.0",
    "tailwindcss": "^3.4.13"
  },
  "devDependencies": {
    "@testing-library/jest-dom": "^6.4.8",
    "@testing-library/react": "^16.0.1",
    "@types/node": "^22.7.4",
    "@types/react": "^19.0.0",
    "@types/react-dom": "^19.0.0",
    "typescript": "^5.6.2",
    "vitest": "^2.1.1"
  }
}
```

Create `frontend/src/app/layout.tsx`:

```tsx
import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "Signal Tape",
  description: "Financial KOL signal monitor",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="zh-CN">
      <body>{children}</body>
    </html>
  );
}
```

Create `frontend/src/app/page.tsx`:

```tsx
export default function HomePage() {
  return (
    <main className="min-h-screen bg-[#101113] text-[#f2f4f8]">
      <h1>Signal Tape</h1>
    </main>
  );
}
```

Create `frontend/src/app/globals.css`:

```css
@tailwind base;
@tailwind components;
@tailwind utilities;

* {
  box-sizing: border-box;
}

body {
  margin: 0;
  background: #101113;
}
```

- [ ] **Step 6: Create Compose and environment defaults**

Create `.env.example`:

```bash
DATABASE_URL=mysql+pymysql://kol:kol@mysql:3306/kol_signal
REDIS_URL=redis://redis:6379/0
SECRET_KEY=replace-with-a-long-random-string
ACCESS_TOKEN_EXPIRE_MINUTES=1440
NEXT_PUBLIC_API_BASE_URL=http://localhost:8000
MYSQL_DATABASE=kol_signal
MYSQL_USER=kol
MYSQL_PASSWORD=kol
MYSQL_ROOT_PASSWORD=kol_root
```

Create `docker-compose.yml`:

```yaml
services:
  mysql:
    image: mysql:8.4
    environment:
      MYSQL_DATABASE: ${MYSQL_DATABASE:-kol_signal}
      MYSQL_USER: ${MYSQL_USER:-kol}
      MYSQL_PASSWORD: ${MYSQL_PASSWORD:-kol}
      MYSQL_ROOT_PASSWORD: ${MYSQL_ROOT_PASSWORD:-kol_root}
    ports:
      - "3306:3306"
    volumes:
      - mysql_data:/var/lib/mysql
    healthcheck:
      test: ["CMD", "mysqladmin", "ping", "-h", "localhost"]
      interval: 10s
      timeout: 5s
      retries: 10

  redis:
    image: redis:7-alpine
    ports:
      - "6379:6379"

volumes:
  mysql_data:
```

Create `README.md`:

```markdown
# KOL Signal Crawler

Financial KOL signal monitoring system.

## Local checks

```bash
cd backend
uv run pytest
```
```

- [ ] **Step 7: Verify scaffold checks**

Run:

```bash
cd backend
uv run pytest -v
cd ../frontend
npm install
npm run build
```

Expected: backend tests pass and frontend build completes.

- [ ] **Step 8: Commit**

```bash
git add .env.example README.md docker-compose.yml backend frontend
git commit -m "chore: scaffold runnable project"
```

---

### Task 2: Database Models, Alembic Migration, And Constraints

**Files:**
- Create: `backend/app/db/base.py`
- Create: `backend/app/db/session.py`
- Create: `backend/app/models/*.py`
- Create: `backend/alembic.ini`
- Create: `backend/alembic/env.py`
- Create: `backend/alembic/versions/0001_initial_schema.py`
- Create: `backend/tests/test_models.py`

**Interfaces:**
- Produces SQLAlchemy models named `User`, `ModelConfig`, `KolProfile`, `Subscription`, `RawPost`, `Signal`, `Asset`, `SignalAsset`, `SignalTag`, `NotificationRule`, `NotificationEvent`, and `CrawlRun`.
- Produces `SessionLocal()` and `Base`.
- Later services import models from `app.models`.

- [ ] **Step 1: Write failing model constraint tests**

Create `backend/tests/test_models.py`:

```python
import pytest
from sqlalchemy import create_engine
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import sessionmaker

from app.db.base import Base
from app.models.raw_post import RawPost
from app.models.signal import Signal
from app.models.subscription import Subscription


@pytest.fixture()
def db_session():
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    session = Session()
    try:
        yield session
    finally:
        session.close()


def test_raw_post_platform_external_id_is_unique(db_session) -> None:
    db_session.add(
        RawPost(platform="x", external_id="100", url="https://x.com/a/100", raw_text="one")
    )
    db_session.add(
        RawPost(platform="x", external_id="100", url="https://x.com/a/100-copy", raw_text="two")
    )

    with pytest.raises(IntegrityError):
        db_session.commit()


def test_signal_raw_post_id_is_unique(db_session) -> None:
    post = RawPost(platform="x", external_id="101", url="https://x.com/a/101", raw_text="one")
    db_session.add(post)
    db_session.flush()
    db_session.add(Signal(raw_post_id=post.id, actionable=True, stance="多", summary="first"))
    db_session.add(Signal(raw_post_id=post.id, actionable=True, stance="多", summary="second"))

    with pytest.raises(IntegrityError):
        db_session.commit()


def test_subscription_interval_minimum_is_one(db_session) -> None:
    db_session.add(
        Subscription(
            platform="x",
            platform_handle="senerity",
            interval_minutes=0,
            enabled=True,
        )
    )

    with pytest.raises(IntegrityError):
        db_session.commit()
```

- [ ] **Step 2: Run the model tests and verify they fail**

Run:

```bash
cd backend
uv run pytest tests/test_models.py -v
```

Expected before implementation: import failure for `app.db.base` or missing models.

- [ ] **Step 3: Implement SQLAlchemy base and session**

Create `backend/app/db/base.py`:

```python
from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    pass
```

Create `backend/app/db/session.py`:

```python
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.core.config import get_settings

settings = get_settings()

engine = create_engine(settings.database_url, pool_pre_ping=True)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
```

- [ ] **Step 4: Implement model files with explicit constraints**

Each model file imports `Base` from `app.db.base`. Use SQLAlchemy `Mapped` and `mapped_column`.

Example for `backend/app/models/raw_post.py`:

```python
from datetime import datetime

from sqlalchemy import DateTime, String, Text, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class RawPost(Base):
    __tablename__ = "raw_posts"
    __table_args__ = (UniqueConstraint("platform", "external_id", name="uq_raw_posts_platform_external"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    platform: Mapped[str] = mapped_column(String(32), nullable=False)
    external_id: Mapped[str] = mapped_column(String(255), nullable=False)
    url: Mapped[str | None] = mapped_column(String(1024))
    author_handle: Mapped[str | None] = mapped_column(String(255))
    author_name: Mapped[str | None] = mapped_column(String(255))
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    raw_text: Mapped[str] = mapped_column(Text, nullable=False)
    raw_json: Mapped[str | None] = mapped_column(Text)
    content_hash: Mapped[str | None] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
```

Example for `backend/app/models/subscription.py`:

```python
from datetime import datetime

from sqlalchemy import Boolean, CheckConstraint, DateTime, ForeignKey, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class Subscription(Base):
    __tablename__ = "subscriptions"
    __table_args__ = (CheckConstraint("interval_minutes >= 1", name="ck_subscription_interval_min"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    kol_profile_id: Mapped[int | None] = mapped_column(ForeignKey("kol_profiles.id"))
    platform: Mapped[str] = mapped_column(String(32), nullable=False)
    platform_account_id: Mapped[str | None] = mapped_column(String(255))
    platform_handle: Mapped[str] = mapped_column(String(255), nullable=False)
    interval_minutes: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    prompt: Mapped[str | None] = mapped_column(Text)
    model_config_id: Mapped[int | None] = mapped_column(ForeignKey("model_configs.id"))
    checkpoint: Mapped[str | None] = mapped_column(Text)
    next_check_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_checked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_success_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
```

Example for `backend/app/models/signal.py`:

```python
from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, String, Text, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class Signal(Base):
    __tablename__ = "signals"
    __table_args__ = (UniqueConstraint("raw_post_id", name="uq_signals_raw_post"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    raw_post_id: Mapped[int] = mapped_column(ForeignKey("raw_posts.id"), nullable=False)
    subscription_id: Mapped[int | None] = mapped_column(ForeignKey("subscriptions.id"))
    actionable: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    stance: Mapped[str] = mapped_column(String(32), nullable=False)
    summary: Mapped[str] = mapped_column(Text, nullable=False)
    evidence_json: Mapped[str | None] = mapped_column(Text)
    horizon: Mapped[str | None] = mapped_column(String(32))
    confidence: Mapped[str | None] = mapped_column(String(32))
    risk_notes: Mapped[str | None] = mapped_column(Text)
    structured_json: Mapped[str | None] = mapped_column(Text)
    structured_status: Mapped[str] = mapped_column(String(32), nullable=False, default="ok")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
```

Create `backend/app/models/user.py`:

```python
from datetime import datetime

from sqlalchemy import DateTime, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True)
    email: Mapped[str] = mapped_column(String(255), nullable=False, unique=True)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
```

Create `backend/app/models/model_config.py`:

```python
from datetime import datetime

from sqlalchemy import Boolean, DateTime, Float, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class ModelConfig(Base):
    __tablename__ = "model_configs"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    base_url: Mapped[str] = mapped_column(String(1024), nullable=False)
    api_key_encrypted: Mapped[str | None] = mapped_column(Text)
    model: Mapped[str] = mapped_column(String(255), nullable=False)
    temperature: Mapped[float] = mapped_column(Float, nullable=False, default=0.2)
    is_default: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
```

Create `backend/app/models/kol.py`:

```python
from datetime import datetime

from sqlalchemy import DateTime, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class KolProfile(Base):
    __tablename__ = "kol_profiles"

    id: Mapped[int] = mapped_column(primary_key=True)
    display_name: Mapped[str] = mapped_column(String(255), nullable=False)
    avatar_url: Mapped[str | None] = mapped_column(String(1024))
    description: Mapped[str | None] = mapped_column(Text)
    primary_market: Mapped[str | None] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
```

Create `backend/app/models/asset.py`:

```python
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, String, Text, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class Asset(Base):
    __tablename__ = "assets"
    __table_args__ = (UniqueConstraint("symbol", "market", name="uq_assets_symbol_market"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    symbol: Mapped[str] = mapped_column(String(64), nullable=False)
    name: Mapped[str | None] = mapped_column(String(255))
    market: Mapped[str] = mapped_column(String(64), nullable=False)
    asset_type: Mapped[str] = mapped_column(String(64), nullable=False)
    aliases_json: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class SignalAsset(Base):
    __tablename__ = "signal_assets"
    __table_args__ = (UniqueConstraint("signal_id", "asset_id", name="uq_signal_assets_pair"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    signal_id: Mapped[int] = mapped_column(ForeignKey("signals.id"), nullable=False)
    asset_id: Mapped[int] = mapped_column(ForeignKey("assets.id"), nullable=False)


class SignalTag(Base):
    __tablename__ = "signal_tags"

    id: Mapped[int] = mapped_column(primary_key=True)
    signal_id: Mapped[int] = mapped_column(ForeignKey("signals.id"), nullable=False)
    tag: Mapped[str] = mapped_column(String(120), nullable=False)
    source: Mapped[str] = mapped_column(String(32), nullable=False, default="llm")
```

Create `backend/app/models/notification.py`:

```python
from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class NotificationRule(Base):
    __tablename__ = "notification_rules"

    id: Mapped[int] = mapped_column(primary_key=True)
    subscription_id: Mapped[int | None] = mapped_column(ForeignKey("subscriptions.id"))
    ntfy_server: Mapped[str | None] = mapped_column(String(1024))
    ntfy_topic: Mapped[str | None] = mapped_column(String(255))
    ntfy_token_encrypted: Mapped[str | None] = mapped_column(Text)
    min_confidence: Mapped[str | None] = mapped_column(String(32))
    require_asset: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    allowed_markets_json: Mapped[str | None] = mapped_column(Text)
    allowed_stances_json: Mapped[str | None] = mapped_column(Text)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class NotificationEvent(Base):
    __tablename__ = "notification_events"

    id: Mapped[int] = mapped_column(primary_key=True)
    signal_id: Mapped[int] = mapped_column(ForeignKey("signals.id"), nullable=False)
    notification_rule_id: Mapped[int | None] = mapped_column(ForeignKey("notification_rules.id"))
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    error_message: Mapped[str | None] = mapped_column(Text)
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
```

Create `backend/app/models/crawl_run.py`:

```python
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class CrawlRun(Base):
    __tablename__ = "crawl_runs"

    id: Mapped[int] = mapped_column(primary_key=True)
    subscription_id: Mapped[int | None] = mapped_column(ForeignKey("subscriptions.id"))
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    fetched_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    inserted_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    structured_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    error_message: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
```

Create `backend/app/models/__init__.py`:

```python
from app.models.asset import Asset, SignalAsset, SignalTag
from app.models.crawl_run import CrawlRun
from app.models.kol import KolProfile
from app.models.model_config import ModelConfig
from app.models.notification import NotificationEvent, NotificationRule
from app.models.raw_post import RawPost
from app.models.signal import Signal
from app.models.subscription import Subscription
from app.models.user import User

__all__ = [
    "Asset",
    "CrawlRun",
    "KolProfile",
    "ModelConfig",
    "NotificationEvent",
    "NotificationRule",
    "RawPost",
    "Signal",
    "SignalAsset",
    "SignalTag",
    "Subscription",
    "User",
]
```

- [ ] **Step 5: Create Alembic config and initial migration**

Create `backend/alembic.ini` with `script_location = alembic` and `sqlalchemy.url = mysql+pymysql://kol:kol@mysql:3306/kol_signal`.

Create `backend/alembic/env.py`:

```python
from logging.config import fileConfig

from alembic import context
from sqlalchemy import engine_from_config, pool

from app.core.config import get_settings
from app.db.base import Base
from app import models  # noqa: F401

config = context.config
fileConfig(config.config_file_name)
target_metadata = Base.metadata


def run_migrations_offline() -> None:
    settings = get_settings()
    context.configure(url=settings.database_url, target_metadata=target_metadata, literal_binds=True)
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    settings = get_settings()
    config.set_main_option("sqlalchemy.url", settings.database_url)
    connectable = engine_from_config(
        config.get_section(config.config_ini_section),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    with connectable.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata)
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
```

Create the initial revision with:

```bash
cd backend
uv run alembic revision --autogenerate -m "initial schema"
```

Rename the generated file to `backend/alembic/versions/0001_initial_schema.py`.

- [ ] **Step 6: Run model tests**

Run:

```bash
cd backend
uv run pytest tests/test_models.py -v
```

Expected: `3 passed`.

- [ ] **Step 7: Commit**

```bash
git add backend
git commit -m "feat: add database schema"
```

---

### Task 3: Auth, Secret Encryption, And Admin Config Primitives

**Files:**
- Create: `backend/app/core/crypto.py`
- Create: `backend/app/core/security.py`
- Create: `backend/tests/test_admin_config.py`
- Modify: `backend/app/core/config.py`
- Modify: `backend/app/models/user.py`
- Modify: `backend/app/models/model_config.py`
- Modify: `backend/app/models/notification.py`

**Interfaces:**
- Produces `encrypt_secret(value: str) -> str`.
- Produces `decrypt_secret(value: str) -> str`.
- Produces `hash_password(password: str) -> str`.
- Produces `verify_password(password: str, password_hash: str) -> bool`.
- Produces `create_access_token(subject: str) -> str`.
- Produces `decode_access_token(token: str) -> str`.

- [ ] **Step 1: Write failing tests for secrets and tokens**

Create `backend/tests/test_admin_config.py`:

```python
from app.core.crypto import decrypt_secret, encrypt_secret
from app.core.security import create_access_token, decode_access_token, hash_password, verify_password


def test_secret_round_trip_does_not_store_plaintext() -> None:
    encrypted = encrypt_secret("sk-test-secret")

    assert encrypted != "sk-test-secret"
    assert decrypt_secret(encrypted) == "sk-test-secret"


def test_password_hash_verification() -> None:
    password_hash = hash_password("correct horse battery staple")

    assert verify_password("correct horse battery staple", password_hash) is True
    assert verify_password("wrong", password_hash) is False


def test_access_token_round_trip() -> None:
    token = create_access_token("admin@example.com")

    assert decode_access_token(token) == "admin@example.com"
```

- [ ] **Step 2: Run tests and verify they fail**

Run:

```bash
cd backend
uv run pytest tests/test_admin_config.py -v
```

Expected before implementation: import failure for `app.core.crypto`.

- [ ] **Step 3: Implement deterministic encryption helper for configured secret key**

Modify `backend/app/core/config.py` to add:

```python
encryption_key: str = Field(default="dev-encryption-key-change-me", alias="ENCRYPTION_KEY")
```

Create `backend/app/core/crypto.py`:

```python
import base64
import hashlib

from cryptography.fernet import Fernet

from app.core.config import get_settings


def _fernet() -> Fernet:
    settings = get_settings()
    digest = hashlib.sha256(settings.encryption_key.encode("utf-8")).digest()
    return Fernet(base64.urlsafe_b64encode(digest))


def encrypt_secret(value: str) -> str:
    return _fernet().encrypt(value.encode("utf-8")).decode("utf-8")


def decrypt_secret(value: str) -> str:
    return _fernet().decrypt(value.encode("utf-8")).decode("utf-8")
```

- [ ] **Step 4: Implement password and JWT helpers**

Create `backend/app/core/security.py`:

```python
from datetime import UTC, datetime, timedelta

from jose import JWTError, jwt
from passlib.context import CryptContext

from app.core.config import get_settings

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")


def hash_password(password: str) -> str:
    return pwd_context.hash(password)


def verify_password(password: str, password_hash: str) -> bool:
    return pwd_context.verify(password, password_hash)


def create_access_token(subject: str) -> str:
    settings = get_settings()
    expires_at = datetime.now(UTC) + timedelta(minutes=settings.access_token_expire_minutes)
    payload = {"sub": subject, "exp": expires_at}
    return jwt.encode(payload, settings.secret_key, algorithm="HS256")


def decode_access_token(token: str) -> str:
    settings = get_settings()
    try:
        payload = jwt.decode(token, settings.secret_key, algorithms=["HS256"])
    except JWTError as exc:
        raise ValueError("Invalid access token") from exc
    subject = payload.get("sub")
    if not isinstance(subject, str) or not subject:
        raise ValueError("Invalid access token subject")
    return subject
```

- [ ] **Step 5: Run tests**

Run:

```bash
cd backend
uv run pytest tests/test_admin_config.py -v
```

Expected: `3 passed`.

- [ ] **Step 6: Commit**

```bash
git add backend
git commit -m "feat: add admin security primitives"
```

---

### Task 4: Collector Adapter Interfaces For X And Binance Square

**Files:**
- Create: `backend/app/collectors/base.py`
- Create: `backend/app/collectors/x_official.py`
- Create: `backend/app/collectors/binance_square.py`
- Create: `backend/tests/fixtures/binance_square_sample.html`
- Create: `backend/tests/test_collectors.py`
- Modify: `backend/app/core/config.py`

**Interfaces:**
- Produces `CollectedPost` dataclass with `platform`, `external_id`, `url`, `author_handle`, `author_name`, `published_at`, `raw_text`, `raw_json`.
- Produces `CollectorAdapter.fetch_new(handle: str, checkpoint: str | None, limit: int) -> list[CollectedPost]`.
- Produces `XOfficialCollector`.
- Produces `parse_binance_square_html(html: str, author_hint: str | None) -> list[CollectedPost]`.

- [ ] **Step 1: Write failing collector tests**

Create `backend/tests/test_collectors.py`:

```python
from datetime import UTC, datetime

import respx
from httpx import Response

from app.collectors.binance_square import parse_binance_square_html
from app.collectors.x_official import XOfficialCollector


def test_parse_binance_square_public_html_fixture() -> None:
    html = """
    <article data-post-id="sq-1">
      <a href="/square/post/123">Read</a>
      <time datetime="2026-07-09T12:00:00Z"></time>
      <p>BTC looks strong after spot demand improved.</p>
    </article>
    """

    posts = parse_binance_square_html(html, author_hint="binance_creator")

    assert len(posts) == 1
    assert posts[0].platform == "binance_square"
    assert posts[0].external_id == "sq-1"
    assert posts[0].author_handle == "binance_creator"
    assert "BTC looks strong" in posts[0].raw_text


@respx.mock
def test_x_official_collector_uses_since_id() -> None:
    route = respx.get("https://api.x.com/2/users/42/tweets").mock(
        return_value=Response(
            200,
            json={
                "data": [
                    {
                        "id": "200",
                        "text": "$SPCX order flow improving",
                        "created_at": "2026-07-09T12:00:00Z",
                    }
                ]
            },
        )
    )
    collector = XOfficialCollector(bearer_token="token", user_id_resolver=lambda handle: "42")

    posts = collector.fetch_new(handle="senerity", checkpoint="199", limit=10)

    assert route.called
    request = route.calls[0].request
    assert request.url.params["since_id"] == "199"
    assert posts[0].external_id == "200"
    assert posts[0].published_at == datetime(2026, 7, 9, 12, 0, tzinfo=UTC)
```

- [ ] **Step 2: Run tests and verify they fail**

Run:

```bash
cd backend
uv run pytest tests/test_collectors.py -v
```

Expected before implementation: import failure for collectors.

- [ ] **Step 3: Implement collector base dataclass and protocol**

Create `backend/app/collectors/base.py`:

```python
from dataclasses import dataclass
from datetime import datetime
from typing import Protocol


@dataclass(frozen=True)
class CollectedPost:
    platform: str
    external_id: str
    url: str | None
    author_handle: str | None
    author_name: str | None
    published_at: datetime | None
    raw_text: str
    raw_json: str | None = None


class CollectorAdapter(Protocol):
    def fetch_new(self, handle: str, checkpoint: str | None, limit: int = 20) -> list[CollectedPost]:
        raise NotImplementedError
```

- [ ] **Step 4: Implement X official collector with injectable resolver**

Create `backend/app/collectors/x_official.py`:

```python
from collections.abc import Callable
from datetime import datetime
import json

import httpx

from app.collectors.base import CollectedPost


class XOfficialCollector:
    def __init__(self, bearer_token: str, user_id_resolver: Callable[[str], str]) -> None:
        self.bearer_token = bearer_token
        self.user_id_resolver = user_id_resolver

    def fetch_new(self, handle: str, checkpoint: str | None, limit: int = 20) -> list[CollectedPost]:
        user_id = self.user_id_resolver(handle)
        params = {
            "max_results": str(min(max(limit, 5), 100)),
            "tweet.fields": "created_at",
            "exclude": "replies",
        }
        if checkpoint:
            params["since_id"] = checkpoint
        response = httpx.get(
            f"https://api.x.com/2/users/{user_id}/tweets",
            params=params,
            headers={"Authorization": f"Bearer {self.bearer_token}"},
            timeout=20,
        )
        response.raise_for_status()
        payload = response.json()
        posts: list[CollectedPost] = []
        for item in payload.get("data", []):
            post_id = item["id"]
            created_at = item.get("created_at")
            posts.append(
                CollectedPost(
                    platform="x",
                    external_id=post_id,
                    url=f"https://x.com/{handle.lstrip('@')}/status/{post_id}",
                    author_handle=handle.lstrip("@"),
                    author_name=None,
                    published_at=datetime.fromisoformat(created_at.replace("Z", "+00:00"))
                    if created_at
                    else None,
                    raw_text=item["text"],
                    raw_json=json.dumps(item, ensure_ascii=False),
                )
            )
        return sorted(posts, key=lambda post: post.published_at or datetime.min.replace(tzinfo=None))
```

- [ ] **Step 5: Implement Binance Square HTML parser**

Create `backend/app/collectors/binance_square.py`:

```python
from datetime import datetime
import hashlib
from html.parser import HTMLParser

from app.collectors.base import CollectedPost


class _SquareParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.posts: list[dict[str, str | None]] = []
        self._current: dict[str, str | None] | None = None
        self._capture_text = False
        self._text_parts: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attr = dict(attrs)
        if tag == "article":
            self._current = {"id": attr.get("data-post-id"), "url": None, "published_at": None}
            self._text_parts = []
        if self._current is None:
            return
        if tag == "a" and attr.get("href") and self._current["url"] is None:
            href = attr["href"] or ""
            self._current["url"] = href if href.startswith("http") else f"https://www.binance.com{href}"
        if tag == "time" and attr.get("datetime"):
            self._current["published_at"] = attr["datetime"]
        if tag in {"p", "span"}:
            self._capture_text = True

    def handle_endtag(self, tag: str) -> None:
        if tag in {"p", "span"}:
            self._capture_text = False
        if tag == "article" and self._current is not None:
            self._current["text"] = " ".join(part.strip() for part in self._text_parts if part.strip())
            self.posts.append(self._current)
            self._current = None

    def handle_data(self, data: str) -> None:
        if self._capture_text and self._current is not None:
            self._text_parts.append(data)


def parse_binance_square_html(html: str, author_hint: str | None = None) -> list[CollectedPost]:
    parser = _SquareParser()
    parser.feed(html)
    posts: list[CollectedPost] = []
    for item in parser.posts:
        text = item.get("text") or ""
        if not text:
            continue
        external_id = item.get("id")
        if not external_id:
            fingerprint = f"{author_hint or ''}|{item.get('published_at') or ''}|{text}"
            external_id = hashlib.sha256(fingerprint.encode("utf-8")).hexdigest()
        published_at = item.get("published_at")
        posts.append(
            CollectedPost(
                platform="binance_square",
                external_id=external_id,
                url=item.get("url"),
                author_handle=author_hint,
                author_name=None,
                published_at=datetime.fromisoformat(published_at.replace("Z", "+00:00"))
                if published_at
                else None,
                raw_text=text,
                raw_json=None,
            )
        )
    return posts
```

- [ ] **Step 6: Run collector tests**

Run:

```bash
cd backend
uv run pytest tests/test_collectors.py -v
```

Expected: `2 passed`.

- [ ] **Step 7: Commit**

```bash
git add backend
git commit -m "feat: add collector adapters"
```

---

### Task 5: Scheduler Selection And Redis Locking

**Files:**
- Create: `backend/app/services/locks.py`
- Create: `backend/app/services/scheduler.py`
- Create: `backend/tests/test_scheduler.py`

**Interfaces:**
- Produces `RedisLockManager.acquire(key: str, ttl_seconds: int) -> bool`.
- Produces `RedisLockManager.release(key: str) -> None`.
- Produces `due_subscriptions(session: Session, now: datetime) -> list[Subscription]`.
- Produces `compute_next_check(now: datetime, interval_minutes: int) -> datetime`.

- [ ] **Step 1: Write failing scheduler tests**

Create `backend/tests/test_scheduler.py`:

```python
from datetime import UTC, datetime, timedelta

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.db.base import Base
from app.models.subscription import Subscription
from app.services.scheduler import compute_next_check, due_subscriptions


def test_due_subscriptions_only_returns_enabled_due_items() -> None:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    session = Session()
    now = datetime(2026, 7, 9, 12, 0, tzinfo=UTC)
    session.add_all(
        [
            Subscription(platform="x", platform_handle="due", interval_minutes=1, enabled=True, next_check_at=now),
            Subscription(
                platform="x",
                platform_handle="future",
                interval_minutes=1,
                enabled=True,
                next_check_at=now + timedelta(minutes=5),
            ),
            Subscription(platform="x", platform_handle="disabled", interval_minutes=1, enabled=False, next_check_at=now),
        ]
    )
    session.commit()

    due = due_subscriptions(session, now)

    assert [subscription.platform_handle for subscription in due] == ["due"]


def test_compute_next_check_uses_subscription_interval() -> None:
    now = datetime(2026, 7, 9, 12, 0, tzinfo=UTC)

    assert compute_next_check(now, 5) == datetime(2026, 7, 9, 12, 5, tzinfo=UTC)
```

- [ ] **Step 2: Run tests and verify they fail**

Run:

```bash
cd backend
uv run pytest tests/test_scheduler.py -v
```

Expected before implementation: import failure for `app.services.scheduler`.

- [ ] **Step 3: Implement scheduler selection helpers**

Create `backend/app/services/scheduler.py`:

```python
from datetime import datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.subscription import Subscription


def due_subscriptions(session: Session, now: datetime) -> list[Subscription]:
    statement = (
        select(Subscription)
        .where(Subscription.enabled.is_(True))
        .where((Subscription.next_check_at.is_(None)) | (Subscription.next_check_at <= now))
        .order_by(Subscription.next_check_at.asc().nullsfirst(), Subscription.id.asc())
    )
    return list(session.scalars(statement).all())


def compute_next_check(now: datetime, interval_minutes: int) -> datetime:
    if interval_minutes < 1:
        raise ValueError("interval_minutes must be at least 1")
    return now + timedelta(minutes=interval_minutes)
```

- [ ] **Step 4: Implement Redis lock manager**

Create `backend/app/services/locks.py`:

```python
import redis


class RedisLockManager:
    def __init__(self, redis_url: str) -> None:
        self.client = redis.Redis.from_url(redis_url, decode_responses=True)

    def acquire(self, key: str, ttl_seconds: int) -> bool:
        return bool(self.client.set(key, "1", nx=True, ex=ttl_seconds))

    def release(self, key: str) -> None:
        self.client.delete(key)
```

- [ ] **Step 5: Run scheduler tests**

Run:

```bash
cd backend
uv run pytest tests/test_scheduler.py -v
```

Expected: `2 passed`.

- [ ] **Step 6: Commit**

```bash
git add backend
git commit -m "feat: add scheduler selection and locks"
```

---

### Task 6: Asset Normalization And LLM Structuring

**Files:**
- Create: `backend/app/services/assets.py`
- Create: `backend/app/services/structurer.py`
- Create: `backend/tests/test_assets.py`
- Create: `backend/tests/test_structurer.py`

**Interfaces:**
- Produces `normalize_asset_symbol(text: str) -> str | None`.
- Produces `detect_assets(text: str) -> list[AssetCandidate]`.
- Produces `StructuredSignal` Pydantic model.
- Produces `Structurer.structure(raw_text: str, prompt: str) -> StructuredSignal`.

- [ ] **Step 1: Write failing asset tests**

Create `backend/tests/test_assets.py`:

```python
from app.services.assets import detect_assets, normalize_asset_symbol


def test_normalize_us_stock_cashtag() -> None:
    assert normalize_asset_symbol("$tsla") == "TSLA"


def test_detect_a_share_by_numeric_symbol_and_name() -> None:
    assets = detect_assets("宁德时代 300750 订单改善")

    assert {"symbol": "300750", "market": "A_SHARE", "asset_type": "stock", "name": "宁德时代"} in [
        asset.model_dump() for asset in assets
    ]


def test_detect_crypto_symbol() -> None:
    assets = detect_assets("BTC and ETH both look strong")

    assert [asset.symbol for asset in assets] == ["BTC", "ETH"]
```

- [ ] **Step 2: Write failing structurer tests with fake model client**

Create `backend/tests/test_structurer.py`:

```python
import pytest

from app.services.structurer import Structurer, StructuredSignal


class FakeModelClient:
    def __init__(self, responses: list[str]) -> None:
        self.responses = responses
        self.calls = 0

    def complete(self, prompt: str) -> str:
        response = self.responses[self.calls]
        self.calls += 1
        return response


def test_structurer_parses_valid_json() -> None:
    client = FakeModelClient(
        [
            '{"actionable":true,"stance":"多","assets":[{"symbol":"SPCX","market":"US_STOCK","asset_type":"stock","name":null}],"evidence":["大订单"],"horizon":"短线","confidence":"高","summary":"订单流偏强","risk_notes":null,"custom_tags":["订单流"]}'
        ]
    )

    signal = Structurer(client).structure("$SPCX order flow strong", "Analyze")

    assert isinstance(signal, StructuredSignal)
    assert signal.actionable is True
    assert signal.assets[0].symbol == "SPCX"


def test_structurer_retries_once_after_invalid_json() -> None:
    client = FakeModelClient(
        [
            "not json",
            '{"actionable":false,"stance":"无明确观点","assets":[],"evidence":[],"horizon":"未说明","confidence":"低","summary":"没有明确交易观点","risk_notes":null,"custom_tags":[]}',
        ]
    )

    signal = Structurer(client).structure("hello", "Analyze")

    assert client.calls == 2
    assert signal.actionable is False


def test_structurer_raises_after_two_invalid_outputs() -> None:
    client = FakeModelClient(["not json", "still not json"])

    with pytest.raises(ValueError, match="Model output did not match schema"):
        Structurer(client).structure("hello", "Analyze")
```

- [ ] **Step 3: Run tests and verify they fail**

Run:

```bash
cd backend
uv run pytest tests/test_assets.py tests/test_structurer.py -v
```

Expected before implementation: import failures for asset and structurer services.

- [ ] **Step 4: Implement asset detection**

Create `backend/app/services/assets.py`:

```python
import re

from pydantic import BaseModel


class AssetCandidate(BaseModel):
    symbol: str
    market: str
    asset_type: str
    name: str | None = None


A_SHARE_ALIASES = {
    "300750": "宁德时代",
    "600519": "贵州茅台",
}

CRYPTO_SYMBOLS = {"BTC", "ETH", "SOL"}


def normalize_asset_symbol(text: str) -> str | None:
    cleaned = text.strip().upper()
    if cleaned.startswith("$") and len(cleaned) > 1:
        return cleaned[1:]
    if re.fullmatch(r"\d{6}", cleaned):
        return cleaned
    if cleaned in CRYPTO_SYMBOLS:
        return cleaned
    return None


def detect_assets(text: str) -> list[AssetCandidate]:
    found: list[AssetCandidate] = []
    seen: set[str] = set()

    for match in re.findall(r"\$[A-Za-z]{1,8}", text):
        symbol = normalize_asset_symbol(match)
        if symbol and symbol not in seen:
            found.append(AssetCandidate(symbol=symbol, market="US_STOCK", asset_type="stock"))
            seen.add(symbol)

    upper_text = text.upper()
    for symbol in CRYPTO_SYMBOLS:
        if re.search(rf"\b{symbol}\b", upper_text) and symbol not in seen:
            found.append(AssetCandidate(symbol=symbol, market="CRYPTO", asset_type="crypto"))
            seen.add(symbol)

    for symbol, name in A_SHARE_ALIASES.items():
        if (symbol in text or name in text) and symbol not in seen:
            found.append(
                AssetCandidate(symbol=symbol, market="A_SHARE", asset_type="stock", name=name)
            )
            seen.add(symbol)

    return found
```

- [ ] **Step 5: Implement structurer schema and retry logic**

Create `backend/app/services/structurer.py`:

```python
import json
from typing import Protocol

from pydantic import BaseModel, Field, ValidationError


class ModelClient(Protocol):
    def complete(self, prompt: str) -> str:
        raise NotImplementedError


class StructuredAsset(BaseModel):
    symbol: str
    market: str
    asset_type: str
    name: str | None = None


class StructuredSignal(BaseModel):
    actionable: bool
    stance: str
    assets: list[StructuredAsset] = Field(default_factory=list)
    evidence: list[str] = Field(default_factory=list)
    horizon: str
    confidence: str
    summary: str
    risk_notes: str | None = None
    custom_tags: list[str] = Field(default_factory=list)


class Structurer:
    def __init__(self, model_client: ModelClient) -> None:
        self.model_client = model_client

    def structure(self, raw_text: str, prompt: str) -> StructuredSignal:
        full_prompt = f"{prompt}\n\n原文:\n{raw_text}\n\n只输出 JSON。"
        last_error: Exception | None = None
        for _ in range(2):
            output = self.model_client.complete(full_prompt)
            try:
                return StructuredSignal.model_validate(json.loads(output))
            except (json.JSONDecodeError, ValidationError) as exc:
                last_error = exc
        raise ValueError("Model output did not match schema") from last_error
```

- [ ] **Step 6: Run asset and structurer tests**

Run:

```bash
cd backend
uv run pytest tests/test_assets.py tests/test_structurer.py -v
```

Expected: all tests pass.

- [ ] **Step 7: Commit**

```bash
git add backend
git commit -m "feat: add asset detection and structuring"
```

---

### Task 7: Ingestion Pipeline, Checkpoint Advancement, And Failure Isolation

**Files:**
- Create: `backend/app/services/ingestion.py`
- Create: `backend/tests/test_ingestion.py`
- Modify: `backend/app/models/crawl_run.py`

**Interfaces:**
- Produces `IngestionResult(fetched_count, inserted_count, structured_count, checkpoint)`.
- Produces `ingest_subscription(session, subscription, collector, structurer, now) -> IngestionResult`.
- Consumes `CollectedPost` from Task 4 and `Structurer` from Task 6.

- [ ] **Step 1: Write failing ingestion tests**

Create `backend/tests/test_ingestion.py`:

```python
from datetime import UTC, datetime

from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from app.collectors.base import CollectedPost
from app.db.base import Base
from app.models.raw_post import RawPost
from app.models.signal import Signal
from app.models.subscription import Subscription
from app.services.ingestion import ingest_subscription
from app.services.structurer import StructuredSignal


class FakeCollector:
    def fetch_new(self, handle: str, checkpoint: str | None, limit: int = 20):
        return [
            CollectedPost(
                platform="x",
                external_id="200",
                url="https://x.com/senerity/status/200",
                author_handle="senerity",
                author_name=None,
                published_at=datetime(2026, 7, 9, 12, 0, tzinfo=UTC),
                raw_text="$SPCX order flow strong",
                raw_json='{"id":"200"}',
            )
        ]


class FakeStructurer:
    def structure(self, raw_text: str, prompt: str) -> StructuredSignal:
        return StructuredSignal(
            actionable=True,
            stance="多",
            assets=[],
            evidence=["大订单"],
            horizon="短线",
            confidence="高",
            summary="订单流偏强",
            custom_tags=["订单流"],
        )


def make_session():
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine)()


def test_ingestion_inserts_raw_post_and_signal_once() -> None:
    session = make_session()
    subscription = Subscription(platform="x", platform_handle="senerity", interval_minutes=1, enabled=True)
    session.add(subscription)
    session.commit()

    first = ingest_subscription(session, subscription, FakeCollector(), FakeStructurer(), datetime.now(UTC))
    second = ingest_subscription(session, subscription, FakeCollector(), FakeStructurer(), datetime.now(UTC))

    assert first.inserted_count == 1
    assert second.inserted_count == 0
    assert session.scalar(select(RawPost).where(RawPost.external_id == "200")) is not None
    assert len(session.scalars(select(Signal)).all()) == 1
    assert subscription.checkpoint == "200"
```

- [ ] **Step 2: Run ingestion test and verify it fails**

Run:

```bash
cd backend
uv run pytest tests/test_ingestion.py -v
```

Expected before implementation: import failure for `app.services.ingestion`.

- [ ] **Step 3: Implement ingestion pipeline**

Create `backend/app/services/ingestion.py`:

```python
import json
from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.collectors.base import CollectorAdapter
from app.models.raw_post import RawPost
from app.models.signal import Signal
from app.models.subscription import Subscription
from app.services.structurer import Structurer


@dataclass(frozen=True)
class IngestionResult:
    fetched_count: int
    inserted_count: int
    structured_count: int
    checkpoint: str | None


def ingest_subscription(
    session: Session,
    subscription: Subscription,
    collector: CollectorAdapter,
    structurer: Structurer,
    now: datetime,
) -> IngestionResult:
    posts = collector.fetch_new(subscription.platform_handle, subscription.checkpoint, limit=20)
    inserted_count = 0
    structured_count = 0
    latest_checkpoint = subscription.checkpoint

    for post in posts:
        existing = session.scalar(
            select(RawPost).where(
                RawPost.platform == post.platform,
                RawPost.external_id == post.external_id,
            )
        )
        if existing is not None:
            latest_checkpoint = post.external_id
            continue

        raw_post = RawPost(
            platform=post.platform,
            external_id=post.external_id,
            url=post.url,
            author_handle=post.author_handle,
            author_name=post.author_name,
            published_at=post.published_at,
            raw_text=post.raw_text,
            raw_json=post.raw_json,
        )
        session.add(raw_post)
        try:
            session.flush()
        except IntegrityError:
            session.rollback()
            latest_checkpoint = post.external_id
            continue

        inserted_count += 1
        structured = structurer.structure(post.raw_text, subscription.prompt or "")
        session.add(
            Signal(
                raw_post_id=raw_post.id,
                subscription_id=subscription.id,
                actionable=structured.actionable,
                stance=structured.stance,
                summary=structured.summary,
                evidence_json=json.dumps(structured.evidence, ensure_ascii=False),
                horizon=structured.horizon,
                confidence=structured.confidence,
                risk_notes=structured.risk_notes,
                structured_json=structured.model_dump_json(),
                structured_status="ok",
            )
        )
        structured_count += 1
        latest_checkpoint = post.external_id

    subscription.checkpoint = latest_checkpoint
    subscription.last_checked_at = now
    subscription.last_success_at = now
    session.commit()
    return IngestionResult(
        fetched_count=len(posts),
        inserted_count=inserted_count,
        structured_count=structured_count,
        checkpoint=latest_checkpoint,
    )
```

- [ ] **Step 4: Run ingestion tests**

Run:

```bash
cd backend
uv run pytest tests/test_ingestion.py -v
```

Expected: `1 passed`.

- [ ] **Step 5: Commit**

```bash
git add backend
git commit -m "feat: add ingestion pipeline"
```

---

### Task 8: ntfy Notification Rules And Retryable Events

**Files:**
- Create: `backend/app/services/notifications.py`
- Create: `backend/tests/test_notifications.py`

**Interfaces:**
- Produces `should_notify(signal: Signal, rule: NotificationRule, asset_markets: list[str]) -> bool`.
- Produces `NtfyClient.publish(server: str, topic: str, title: str, message: str, token: str | None) -> None`.
- Produces `record_notification_event(...)`.

- [ ] **Step 1: Write failing notification tests**

Create `backend/tests/test_notifications.py`:

```python
import respx
from httpx import Response

from app.models.notification import NotificationRule
from app.models.signal import Signal
from app.services.notifications import NtfyClient, should_notify


def test_should_notify_requires_actionable_and_asset_when_configured() -> None:
    rule = NotificationRule(min_confidence="中", require_asset=True, enabled=True)
    signal = Signal(raw_post_id=1, actionable=True, stance="多", confidence="高", summary="订单流偏强")

    assert should_notify(signal, rule, ["US_STOCK"]) is True


def test_should_notify_blocks_non_actionable_signal() -> None:
    rule = NotificationRule(min_confidence="低", require_asset=False, enabled=True)
    signal = Signal(raw_post_id=1, actionable=False, stance="无明确观点", confidence="低", summary="闲聊")

    assert should_notify(signal, rule, []) is False


@respx.mock
def test_ntfy_client_publishes_to_topic() -> None:
    route = respx.post("https://ntfy.example.com/signals").mock(return_value=Response(200))

    NtfyClient().publish(
        server="https://ntfy.example.com",
        topic="signals",
        title="$SPCX 多",
        message="订单流偏强",
        token="secret",
    )

    assert route.called
    assert route.calls[0].request.headers["Authorization"] == "Bearer secret"
```

- [ ] **Step 2: Run notification tests and verify they fail**

Run:

```bash
cd backend
uv run pytest tests/test_notifications.py -v
```

Expected before implementation: import failure for `app.services.notifications`.

- [ ] **Step 3: Implement notification rule evaluator and client**

Create `backend/app/services/notifications.py`:

```python
import httpx

from app.models.notification import NotificationRule
from app.models.signal import Signal

CONFIDENCE_RANK = {"低": 1, "中": 2, "高": 3, None: 0}


def should_notify(signal: Signal, rule: NotificationRule, asset_markets: list[str]) -> bool:
    if not rule.enabled or not signal.actionable:
        return False
    if rule.require_asset and not asset_markets:
        return False
    min_rank = CONFIDENCE_RANK.get(rule.min_confidence, 0)
    signal_rank = CONFIDENCE_RANK.get(signal.confidence, 0)
    if signal_rank < min_rank:
        return False
    if rule.allowed_markets_json and not any(market in rule.allowed_markets_json for market in asset_markets):
        return False
    if rule.allowed_stances_json and signal.stance not in rule.allowed_stances_json:
        return False
    return True


class NtfyClient:
    def publish(
        self,
        server: str,
        topic: str,
        title: str,
        message: str,
        token: str | None = None,
    ) -> None:
        headers = {"Title": title}
        if token:
            headers["Authorization"] = f"Bearer {token}"
        response = httpx.post(
            f"{server.rstrip('/')}/{topic}",
            content=message.encode("utf-8"),
            headers=headers,
            timeout=15,
        )
        response.raise_for_status()
```

- [ ] **Step 4: Run notification tests**

Run:

```bash
cd backend
uv run pytest tests/test_notifications.py -v
```

Expected: `3 passed`.

- [ ] **Step 5: Commit**

```bash
git add backend
git commit -m "feat: add ntfy notification rules"
```

---

### Task 9: Public And Admin API Endpoints

**Files:**
- Create: `backend/app/routers/public.py`
- Create: `backend/app/routers/admin.py`
- Create: `backend/app/schemas/common.py`
- Create: `backend/app/schemas/signal.py`
- Create: `backend/app/schemas/admin.py`
- Create: `backend/tests/test_public_api.py`
- Modify: `backend/app/main.py`

**Interfaces:**
- Produces `GET /api/signals`.
- Produces `GET /api/signals/{id}`.
- Produces `GET /api/kols`.
- Produces `GET /api/assets`.
- Produces `POST /api/admin/login`.
- Produces authenticated admin route group under `/api/admin`.

- [ ] **Step 1: Write failing public API tests**

Create `backend/tests/test_public_api.py`:

```python
from fastapi.testclient import TestClient

from app.main import app


def test_public_signals_endpoint_returns_list() -> None:
    client = TestClient(app)

    response = client.get("/api/signals")

    assert response.status_code == 200
    assert response.json() == {"items": []}


def test_admin_health_requires_login() -> None:
    client = TestClient(app)

    response = client.get("/api/admin/health")

    assert response.status_code == 401
```

- [ ] **Step 2: Run API tests and verify they fail**

Run:

```bash
cd backend
uv run pytest tests/test_public_api.py -v
```

Expected before implementation: `/api/signals` returns 404.

- [ ] **Step 3: Implement public router**

Create `backend/app/schemas/common.py`:

```python
from pydantic import BaseModel


class ListResponse(BaseModel):
    items: list[dict]
```

Create `backend/app/routers/public.py`:

```python
from fastapi import APIRouter

router = APIRouter(prefix="/api")


@router.get("/signals")
def list_signals() -> dict[str, list[dict]]:
    return {"items": []}


@router.get("/kols")
def list_kols() -> dict[str, list[dict]]:
    return {"items": []}


@router.get("/assets")
def list_assets() -> dict[str, list[dict]]:
    return {"items": []}
```

- [ ] **Step 4: Implement admin router with bearer auth dependency**

Create `backend/app/routers/admin.py`:

```python
from fastapi import APIRouter, Depends, Header, HTTPException

from app.core.security import decode_access_token

router = APIRouter(prefix="/api/admin")


def require_admin(authorization: str | None = Header(default=None)) -> str:
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Authentication required")
    token = authorization.removeprefix("Bearer ").strip()
    try:
        return decode_access_token(token)
    except ValueError as exc:
        raise HTTPException(status_code=401, detail="Invalid token") from exc


@router.get("/health")
def admin_health(_: str = Depends(require_admin)) -> dict[str, str]:
    return {"status": "ok"}
```

Modify `backend/app/main.py`:

```python
from fastapi import FastAPI

from app.core.config import get_settings
from app.routers import admin, public

settings = get_settings()

app = FastAPI(title="KOL Signal API")
app.include_router(public.router)
app.include_router(admin.router)


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok", "service": settings.app_name}
```

- [ ] **Step 5: Run API tests**

Run:

```bash
cd backend
uv run pytest tests/test_public_api.py -v
```

Expected: `2 passed`.

- [ ] **Step 6: Commit**

```bash
git add backend
git commit -m "feat: add public and admin api routes"
```

---

### Task 10: Public Signal Tape Web UI

**Files:**
- Create: `frontend/src/lib/types.ts`
- Create: `frontend/src/lib/api.ts`
- Create: `frontend/src/components/SignalCard.tsx`
- Create: `frontend/src/components/SignalTape.tsx`
- Create: `frontend/src/components/FilterRail.tsx`
- Create: `frontend/src/components/TopNav.tsx`
- Create: `frontend/src/test/SignalCard.test.tsx`
- Modify: `frontend/src/app/page.tsx`
- Modify: `frontend/src/app/globals.css`

**Interfaces:**
- Produces `SignalItem` TypeScript type.
- Produces `SignalCard({ signal }: { signal: SignalItem })`.
- Produces public homepage using Graphite / Cyan signal tape layout.

- [ ] **Step 1: Write failing component test**

Create `frontend/src/test/SignalCard.test.tsx`:

```tsx
import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { SignalCard } from "../components/SignalCard";
import type { SignalItem } from "../lib/types";

const signal: SignalItem = {
  id: 1,
  title: "$SPCX 订单异动，短线偏多",
  sourceName: "senerity",
  platform: "X",
  summary: "KOL 提到大订单触发后的延续信号。",
  stance: "多",
  confidence: "高",
  ageLabel: "1m ago",
  tags: ["美股", "大订单", "短线"],
  assets: ["$SPCX"],
};

describe("SignalCard", () => {
  it("renders trading signal content and tags", () => {
    render(<SignalCard signal={signal} />);

    expect(screen.getByText("$SPCX 订单异动，短线偏多")).toBeInTheDocument();
    expect(screen.getByText("senerity · X")).toBeInTheDocument();
    expect(screen.getByText("多")).toBeInTheDocument();
    expect(screen.getByText("$SPCX")).toBeInTheDocument();
  });
});
```

- [ ] **Step 2: Run component test and verify it fails**

Run:

```bash
cd frontend
npm run test -- SignalCard.test.tsx
```

Expected before implementation: import failure for `SignalCard`.

- [ ] **Step 3: Define frontend types**

Create `frontend/src/lib/types.ts`:

```ts
export type SignalItem = {
  id: number;
  title: string;
  sourceName: string;
  platform: string;
  summary: string;
  stance: "多" | "空" | "中性" | "无明确观点";
  confidence: "高" | "中" | "低";
  ageLabel: string;
  tags: string[];
  assets: string[];
};
```

- [ ] **Step 4: Implement SignalCard**

Create `frontend/src/components/SignalCard.tsx`:

```tsx
import type { SignalItem } from "../lib/types";

const stanceClass: Record<SignalItem["stance"], string> = {
  多: "border-l-[#37d67a]",
  空: "border-l-[#ff5b5b]",
  中性: "border-l-[#00c2ff]",
  无明确观点: "border-l-[#98a3af]",
};

export function SignalCard({ signal }: { signal: SignalItem }) {
  return (
    <article className={`border-l-4 ${stanceClass[signal.stance]} border-b border-[#2a2e35] py-4 pl-4`}>
      <div className="flex items-start justify-between gap-4">
        <div className="min-w-0">
          <div className="flex flex-wrap items-center gap-2">
            <h2 className="text-sm font-semibold text-[#f2f4f8]">{signal.title}</h2>
            <span className="text-xs text-[#98a3af]">
              {signal.sourceName} · {signal.platform}
            </span>
          </div>
          <p className="mt-2 text-sm leading-6 text-[#b8c1cc]">{signal.summary}</p>
          <div className="mt-3 flex flex-wrap gap-2">
            <span className="rounded border border-[#303741] px-2 py-1 text-xs text-[#f2f4f8]">
              {signal.stance}
            </span>
            {signal.assets.map((asset) => (
              <span key={asset} className="rounded border border-[#00c2ff]/50 px-2 py-1 text-xs text-[#bdeeff]">
                {asset}
              </span>
            ))}
            {signal.tags.map((tag) => (
              <span key={tag} className="rounded border border-[#303741] px-2 py-1 text-xs text-[#dce5ef]">
                {tag}
              </span>
            ))}
          </div>
        </div>
        <div className="shrink-0 text-right font-mono text-xs text-[#98a3af]">
          <div>{signal.ageLabel}</div>
          <div className="mt-2 rounded border border-[#00c2ff]/40 bg-[#00c2ff]/10 px-2 py-1 text-[#f2f4f8]">
            {signal.confidence}
          </div>
        </div>
      </div>
    </article>
  );
}
```

- [ ] **Step 5: Implement SignalTape, filters, and homepage**

Create `frontend/src/components/SignalTape.tsx`:

```tsx
import { SignalCard } from "./SignalCard";
import type { SignalItem } from "../lib/types";

export function SignalTape({ signals }: { signals: SignalItem[] }) {
  return (
    <section className="min-w-0">
      <div className="border-b border-[#2a2e35] px-6 py-4">
        <h1 className="text-xl font-semibold text-[#f2f4f8]">Market signal tape</h1>
        <p className="mt-1 text-sm text-[#98a3af]">按时间展示结构化观点，默认隐藏噪音内容。</p>
      </div>
      <div className="px-6">
        {signals.map((signal) => (
          <SignalCard key={signal.id} signal={signal} />
        ))}
      </div>
    </section>
  );
}
```

Create `frontend/src/components/TopNav.tsx`:

```tsx
export function TopNav() {
  return (
    <header className="flex h-14 items-center justify-between border-b border-[#2a2e35] bg-[#111317] px-5">
      <div className="font-mono text-sm font-bold tracking-widest text-[#f2f4f8]">SIGNAL TAPE</div>
      <nav className="hidden gap-2 md:flex">
        {["全部信号", "美股", "Crypto", "A 股", "KOL", "标的"].map((item, index) => (
          <span
            key={item}
            className={`rounded-lg border px-3 py-2 text-xs ${
              index === 0
                ? "border-[#00c2ff]/60 bg-[#00c2ff]/10 text-[#f2f4f8]"
                : "border-[#2a2e35] bg-[#17191d] text-[#98a3af]"
            }`}
          >
            {item}
          </span>
        ))}
      </nav>
    </header>
  );
}
```

Create `frontend/src/components/FilterRail.tsx`:

```tsx
export function FilterRail() {
  const filters = ["有交易价值", "高置信度", "多", "空", "中性 / 观察"];
  return (
    <aside className="hidden w-60 border-r border-[#2a2e35] bg-[#121418] p-4 lg:block">
      <div className="font-mono text-xs uppercase tracking-widest text-[#6f7a86]">Signal filters</div>
      <div className="mt-3 grid gap-2">
        {filters.map((filter, index) => (
          <button
            key={filter}
            className={`rounded-lg border px-3 py-2 text-left text-sm ${
              index === 0
                ? "border-[#00c2ff]/50 bg-[#00c2ff]/10 text-[#f2f4f8]"
                : "border-[#2a2e35] bg-[#17191d] text-[#98a3af]"
            }`}
          >
            {filter}
          </button>
        ))}
      </div>
    </aside>
  );
}
```

Modify `frontend/src/app/page.tsx`:

```tsx
import { FilterRail } from "../components/FilterRail";
import { SignalTape } from "../components/SignalTape";
import { TopNav } from "../components/TopNav";
import type { SignalItem } from "../lib/types";

const signals: SignalItem[] = [
  {
    id: 1,
    title: "$SPCX 订单异动，短线偏多",
    sourceName: "senerity",
    platform: "X",
    summary: "KOL 提到大订单触发后的延续信号，观点偏短线多头；需要确认后续成交量能是否维持。",
    stance: "多",
    confidence: "高",
    ageLabel: "1m ago",
    tags: ["美股", "大订单", "短线"],
    assets: ["$SPCX"],
  },
  {
    id: 2,
    title: "BTC 宏观语气转谨慎",
    sourceName: "macro voice",
    platform: "X",
    summary: "美元流动性和风险资产相关表述偏收紧，短线对 BTC 风险偏负面。",
    stance: "空",
    confidence: "中",
    ageLabel: "4m ago",
    tags: ["Crypto", "宏观"],
    assets: ["BTC"],
  },
];

export default function HomePage() {
  return (
    <main className="min-h-screen bg-[#101113] text-[#f2f4f8]">
      <TopNav />
      <div className="grid lg:grid-cols-[240px_minmax(0,1fr)]">
        <FilterRail />
        <SignalTape signals={signals} />
      </div>
    </main>
  );
}
```

- [ ] **Step 6: Run frontend tests and build**

Run:

```bash
cd frontend
npm run test -- SignalCard.test.tsx
npm run build
```

Expected: component test passes and Next.js build completes.

- [ ] **Step 7: Commit**

```bash
git add frontend
git commit -m "feat: build public signal tape ui"
```

---

### Task 11: Private Management UI Shell

**Files:**
- Create: `frontend/src/components/AdminShell.tsx`
- Create: `frontend/src/app/admin/page.tsx`
- Modify: `frontend/src/lib/types.ts`

**Interfaces:**
- Produces `/admin` page with sections for subscriptions, prompts, models, notifications, runs, and tests.
- Produces static management shell that can later bind to admin APIs.

- [ ] **Step 1: Create AdminShell component**

Create `frontend/src/components/AdminShell.tsx`:

```tsx
const sections = [
  "订阅",
  "Prompts",
  "模型",
  "ntfy",
  "采集运行",
  "测试工具",
];

export function AdminShell() {
  return (
    <main className="min-h-screen bg-[#101113] text-[#f2f4f8]">
      <header className="border-b border-[#2a2e35] bg-[#111317] px-6 py-4">
        <h1 className="text-lg font-semibold">Management</h1>
        <p className="mt-1 text-sm text-[#98a3af]">配置 KOL、prompt、模型、ntfy 与采集状态。</p>
      </header>
      <div className="grid gap-4 p-6 md:grid-cols-2 xl:grid-cols-3">
        {sections.map((section) => (
          <section key={section} className="rounded-lg border border-[#2a2e35] bg-[#17191d] p-4">
            <h2 className="text-base font-semibold">{section}</h2>
            <p className="mt-2 text-sm leading-6 text-[#98a3af]">
              登录后管理 {section} 配置；所有写操作通过 admin API 完成。
            </p>
          </section>
        ))}
      </div>
    </main>
  );
}
```

- [ ] **Step 2: Create admin page**

Create `frontend/src/app/admin/page.tsx`:

```tsx
import { AdminShell } from "../../components/AdminShell";

export default function AdminPage() {
  return <AdminShell />;
}
```

- [ ] **Step 3: Verify frontend build**

Run:

```bash
cd frontend
npm run build
```

Expected: build completes and includes `/admin`.

- [ ] **Step 4: Commit**

```bash
git add frontend
git commit -m "feat: add management ui shell"
```

---

### Task 12: Docker Images, Deployment Docs, And Final Verification

**Files:**
- Create: `backend/Dockerfile`
- Create: `frontend/Dockerfile`
- Modify: `docker-compose.yml`
- Create: `docs/architecture.md`
- Create: `docs/deployment.md`
- Create: `docs/configuration.md`
- Create: `docs/data-sources.md`
- Create: `docs/prompt-guide.md`
- Create: `docs/operations.md`
- Modify: `README.md`

**Interfaces:**
- Produces `docker compose up --build` stack with `web`, `api`, `mysql`, and `redis`.
- Documents built-in MySQL and external MySQL deployment paths.

- [ ] **Step 1: Create backend Dockerfile**

Create `backend/Dockerfile`:

```dockerfile
FROM python:3.12-slim

WORKDIR /app

RUN pip install --no-cache-dir uv

COPY pyproject.toml ./
RUN uv sync --no-dev

COPY app ./app
COPY alembic ./alembic
COPY alembic.ini ./alembic.ini

EXPOSE 8000

CMD ["uv", "run", "uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
```

- [ ] **Step 2: Create frontend Dockerfile**

Create `frontend/Dockerfile`:

```dockerfile
FROM node:22-alpine AS deps
WORKDIR /app
COPY package.json package-lock.json* ./
RUN npm install

FROM node:22-alpine AS builder
WORKDIR /app
COPY --from=deps /app/node_modules ./node_modules
COPY . .
RUN npm run build

FROM node:22-alpine AS runner
WORKDIR /app
ENV NODE_ENV=production
COPY --from=builder /app/.next ./.next
COPY --from=builder /app/package.json ./package.json
COPY --from=builder /app/node_modules ./node_modules
EXPOSE 3000
CMD ["npm", "run", "start"]
```

- [ ] **Step 3: Extend docker-compose services**

Modify `docker-compose.yml`:

```yaml
services:
  mysql:
    image: mysql:8.4
    environment:
      MYSQL_DATABASE: ${MYSQL_DATABASE:-kol_signal}
      MYSQL_USER: ${MYSQL_USER:-kol}
      MYSQL_PASSWORD: ${MYSQL_PASSWORD:-kol}
      MYSQL_ROOT_PASSWORD: ${MYSQL_ROOT_PASSWORD:-kol_root}
    ports:
      - "3306:3306"
    volumes:
      - mysql_data:/var/lib/mysql
    healthcheck:
      test: ["CMD", "mysqladmin", "ping", "-h", "localhost"]
      interval: 10s
      timeout: 5s
      retries: 10

  redis:
    image: redis:7-alpine
    ports:
      - "6379:6379"

  api:
    build:
      context: ./backend
    env_file:
      - .env
    depends_on:
      mysql:
        condition: service_healthy
      redis:
        condition: service_started
    ports:
      - "8000:8000"

  web:
    build:
      context: ./frontend
    environment:
      NEXT_PUBLIC_API_BASE_URL: ${NEXT_PUBLIC_API_BASE_URL:-http://localhost:8000}
    depends_on:
      - api
    ports:
      - "3000:3000"

volumes:
  mysql_data:
```

- [ ] **Step 4: Write docs**

Create `docs/deployment.md`:

```markdown
# Deployment

## Built-in MySQL

1. Copy `.env.example` to `.env`.
2. Replace `SECRET_KEY`, `ENCRYPTION_KEY`, and database passwords.
3. Run `docker compose up --build`.
4. Open `http://localhost:3000`.

## Existing MySQL

1. Create a dedicated database and user.
2. Set `DATABASE_URL=mysql+pymysql://user:password@host:3306/database`.
3. Remove or disable the `mysql` service in Compose.
4. Run `docker compose up --build api web redis`.
```

Create `docs/data-sources.md`:

```markdown
# Data Sources

X uses the official API and is the stable collector path.

Binance Square uses an isolated Playwright-compatible collector path. It is experimental, prefers public pages without login state, and failures must not block X collection.

A-shares are recognized in text for v1. A-share social sources are not collected in v1.
```

Create `docs/operations.md`:

```markdown
# Operations

Check crawl health in the admin runs view.

If ntfy delivery fails, retry the failed notification event from the admin UI.

If a collector fails, inspect `crawl_runs.error_message`; X failures and Binance Square failures are isolated per subscription.
```

Create `docs/architecture.md`:

```markdown
# Architecture

KOL Signal Crawler is a modular monolith.

## Services

- `web`: Next.js public and admin UI.
- `api`: FastAPI API, scheduler, ingestion, structuring, and notification logic.
- `mysql`: durable business data, checkpoints, raw posts, signals, and notification history.
- `redis`: per-KOL crawl locks and lightweight runtime state.
- `playwright-worker`: optional Binance Square experimental collector runtime.

## Data Flow

1. Scheduler finds due subscriptions.
2. Redis lock prevents the same KOL from running concurrently.
3. Collector fetches new posts.
4. Raw posts are inserted with `(platform, external_id)` uniqueness.
5. LLM structurer validates JSON output.
6. Signals and tags are stored.
7. ntfy rules decide whether to push.
8. Checkpoint advances after successful processing.
```

Create `docs/configuration.md`:

```markdown
# Configuration

## Required Environment

- `DATABASE_URL`: MySQL connection string.
- `REDIS_URL`: Redis connection string.
- `SECRET_KEY`: JWT signing secret.
- `ENCRYPTION_KEY`: secret used to encrypt provider and ntfy tokens.
- `NEXT_PUBLIC_API_BASE_URL`: browser-visible API URL.

## Optional Runtime Settings

- `ACCESS_TOKEN_EXPIRE_MINUTES`: admin session lifetime in minutes.
- `MYSQL_DATABASE`: built-in MySQL database name.
- `MYSQL_USER`: built-in MySQL app user.
- `MYSQL_PASSWORD`: built-in MySQL app password.
- `MYSQL_ROOT_PASSWORD`: built-in MySQL root password.

## Secret Handling

Management APIs must never return decrypted model API keys or ntfy tokens.
```

Create `docs/prompt-guide.md`:

```markdown
# Prompt Guide

Prompts should classify financial KOL posts into structured research signals.

## Required Output

The model must return JSON with:

- `actionable`
- `stance`
- `assets`
- `evidence`
- `horizon`
- `confidence`
- `summary`
- `risk_notes`
- `custom_tags`

## Recommended Instruction

Ask the model to summarize the KOL's view without turning it into a buy or sell instruction. Use `无明确观点` when the post is news, humor, reply chatter, or vague commentary.

## KOL-Specific Prompts

Use recent posts to identify the KOL's common market, terminology, and signal style. Save suggested prompts manually after review.
```

- [ ] **Step 5: Run final verification**

Run:

```bash
cd backend
uv run pytest -v
cd ../frontend
npm run test
npm run build
cd ..
docker compose config
```

Expected:

- Backend tests pass.
- Frontend tests pass.
- Frontend build completes.
- `docker compose config` prints resolved configuration without errors.

- [ ] **Step 6: Commit**

```bash
git add backend frontend docker-compose.yml docs README.md
git commit -m "chore: add deployment docs and docker images"
```

---

## Self-Review Checklist

Spec coverage:

- Data source support is covered by Tasks 4 and 7.
- MySQL schema and deduplication constraints are covered by Task 2.
- Per-KOL interval and non-overlap design are covered by Task 5.
- LLM structuring, prompt behavior, and A-share recognition are covered by Task 6.
- ntfy rules and retryable events are covered by Task 8.
- Public and admin API surfaces are covered by Task 9.
- Public Graphite / Cyan signal-tape UI is covered by Task 10.
- Private management shell is covered by Task 11.
- Docker deployment and documentation are covered by Task 12.

Type consistency:

- Collector tasks produce `CollectedPost`; ingestion consumes `CollectedPost`.
- Structurer tasks produce `StructuredSignal`; ingestion consumes `StructuredSignal`.
- Scheduler tasks produce `due_subscriptions` and `compute_next_check`; ingestion task uses subscription fields from the schema task.
- Frontend `SignalItem` is consumed by `SignalCard` and `SignalTape`.

Execution rule:

- Implement tasks in order.
- Commit after each task.
- Do not begin Task N+1 until Task N tests pass and its commit exists.
