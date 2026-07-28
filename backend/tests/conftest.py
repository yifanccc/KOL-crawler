import os
import tempfile
from pathlib import Path


test_db = Path(tempfile.gettempdir()) / "kol_signal_api_test.db"
if test_db.exists():
    test_db.unlink()

os.environ["DATABASE_URL"] = f"sqlite:///{test_db}"
os.environ["ENABLE_SCHEDULER"] = "false"
os.environ["STARTUP_BACKFILL_ENABLED"] = "false"
os.environ["OPENAI_API_KEY"] = ""
os.environ["DEEPSEEK_API_KEY"] = ""
os.environ["X_BEARER_TOKEN"] = ""
os.environ["ADMIN_USERNAME"] = "testadmin"
os.environ["ADMIN_PASSWORD_HASH"] = "$2b$12$qWWtEol5liK4xwfd6GCiaus9hxd59RVhIgRYPugppmoGOpIAX1VXq"
os.environ["JWT_SECRET"] = "test-jwt-secret-that-is-long-enough-for-tests"
os.environ["WEB_ORIGIN"] = "http://testserver"
os.environ["COLLECTOR_AGENT_ID"] = "home-mac-01"
os.environ["COLLECTOR_TOKEN_HASH"] = "472eaa3f00aac81a662b0f55ef6a3b0bed632761f5baac9d3ddd5b9adebb2495"
