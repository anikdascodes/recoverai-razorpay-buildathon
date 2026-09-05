import json
import os
from datetime import datetime, timezone
from pathlib import Path

AUDIT_FILE = Path(os.getenv("AUDIT_FILE", "audit.jsonl"))


def audit(record: dict) -> None:
    record = {"ts": datetime.now(timezone.utc).isoformat(), **record}
    with AUDIT_FILE.open("a", encoding="utf-8") as f:
        f.write(json.dumps(record, ensure_ascii=False, default=str) + "\n")
