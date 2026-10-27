import hashlib
import json
import re
from datetime import datetime, timezone
from pathlib import Path


def scheduled_date(now: datetime) -> bool:
    if now.tzinfo is None:
        raise ValueError("Timezone-aware datetime required")
    utc = now.astimezone(timezone.utc)
    return utc.year == 2026 and utc.month == 11 and utc.day in (1, 8)


def plan(directory: Path) -> dict:
    if not directory.is_dir():
        raise ValueError("Content directory missing")
    items, ids, slugs = [], set(), set()
    for path in sorted(directory.glob("*.json")):
        data = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            raise ValueError("Article must be an object")
        for field in ("id", "slug", "title", "html"):
            if not isinstance(data.get(field), str) or not data[field].strip():
                raise ValueError("Missing or invalid article field")
        if type(data.get("enabled")) is not bool:
            raise ValueError("Explicit boolean enabled required")
        if not re.fullmatch(r"[a-z0-9]+(?:-[a-z0-9]+)*", data["slug"]):
            raise ValueError("Invalid slug")
        if data["id"] in ids or data["slug"] in slugs:
            raise ValueError("Duplicate article id or slug")
        ids.add(data["id"])
        slugs.add(data["slug"])
        if data["enabled"]:
            canonical = json.dumps({key: data[key] for key in ("id", "slug", "title", "html")},
                                   sort_keys=True, ensure_ascii=False).encode()
            items.append({"id": data["id"], "slug": data["slug"],
                          "sha256": hashlib.sha256(canonical).hexdigest()})
    return {"mode": "dry-run", "publishing_enabled": False, "articles": items}
