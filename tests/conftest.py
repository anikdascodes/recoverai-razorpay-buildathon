import os
from pathlib import Path

# Must run before any app import: bind the engine to a fresh test DB.
os.environ["DATABASE_URL"] = "sqlite:///./test_suite.db"
_db = Path("test_suite.db")
if _db.exists():
    _db.unlink()
