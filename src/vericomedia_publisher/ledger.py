"""Reference local ledger. Production requires shared durable storage.

Claim before remote writing. Never retry an unresolved claim automatically.
Reconcile an interrupted operation against the remote destination first.
"""
import sqlite3
from pathlib import Path


class Ledger:
    def __init__(self, path: Path):
        self.path = path
        with sqlite3.connect(path) as db:
            db.execute("""CREATE TABLE IF NOT EXISTS publications (
                target TEXT NOT NULL, article_id TEXT NOT NULL, digest TEXT NOT NULL,
                status TEXT NOT NULL CHECK(status IN ('claimed', 'published')),
                remote_id TEXT, PRIMARY KEY(target, article_id))""")

    def claim(self, target: str, article_id: str, digest: str) -> bool:
        if not all((target, article_id, digest)):
            raise ValueError("Nonempty publication identity required")
        with sqlite3.connect(self.path, timeout=30) as db:
            cursor = db.execute("""INSERT INTO publications
                (target, article_id, digest, status) VALUES (?, ?, ?, 'claimed')
                ON CONFLICT(target, article_id) DO NOTHING""", (target, article_id, digest))
            return cursor.rowcount == 1

    def mark_published(self, target: str, article_id: str, digest: str, remote_id: str):
        if not remote_id:
            raise ValueError("Verified remote identity required")
        with sqlite3.connect(self.path) as db:
            cursor = db.execute("""UPDATE publications SET status='published', remote_id=?
                WHERE target=? AND article_id=? AND digest=? AND status='claimed'""",
                                (remote_id, target, article_id, digest))
            if cursor.rowcount != 1:
                raise ValueError("Matching pending claim required")
