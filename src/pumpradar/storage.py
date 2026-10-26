"""Small SQLite alert log; each operation opens its own connection."""

import sqlite3
from pathlib import Path


class AlertStore:
    def __init__(self, path: str | Path) -> None:
        self.path = str(path)
        with sqlite3.connect(self.path) as db:
            db.execute(
                """CREATE TABLE IF NOT EXISTS alerts (
                    id INTEGER PRIMARY KEY,
                    symbol TEXT NOT NULL,
                    close_time TEXT NOT NULL,
                    score REAL NOT NULL,
                    UNIQUE(symbol, close_time)
                )"""
            )

    def add(self, alert: dict) -> bool:
        with sqlite3.connect(self.path) as db:
            cursor = db.execute(
                "INSERT OR IGNORE INTO alerts (symbol, close_time, score) VALUES (?, ?, ?)",
                (alert["symbol"], alert["close_time"], alert["score"]),
            )
            return cursor.rowcount == 1

    def recent(self, limit: int = 100) -> list[dict]:
        with sqlite3.connect(self.path) as db:
            db.row_factory = sqlite3.Row
            rows = db.execute(
                "SELECT symbol, close_time, score FROM alerts ORDER BY id DESC LIMIT ?", (limit,)
            ).fetchall()
        return [dict(row, status="demo_stub") for row in rows]
