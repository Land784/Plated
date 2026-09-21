"""SQLite-backed menu history (roadmap step 6).

Kept intentionally minimal: a single table of (date, dining_hall,
meal_period, item_name, protein_g, calories, serving_size) rows,
enough to later answer "which days had the best high-protein options".
"""

from __future__ import annotations

import sqlite3
from datetime import date as Date
from pathlib import Path

DEFAULT_DB_PATH = Path("menu_history.sqlite3")

SCHEMA = """
CREATE TABLE IF NOT EXISTS menu_item_history (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    date TEXT NOT NULL,
    dining_hall TEXT,
    meal_period TEXT,
    item_name TEXT NOT NULL,
    protein_g REAL,
    calories REAL,
    serving_size_amount REAL,
    serving_size_unit TEXT,
    UNIQUE(date, dining_hall, meal_period, item_name)
);
"""


def get_connection(db_path: Path = DEFAULT_DB_PATH) -> sqlite3.Connection:
    conn = sqlite3.connect(db_path)
    conn.execute(SCHEMA)
    return conn


def record_items(
    conn: sqlite3.Connection,
    d: Date,
    dining_hall: str,
    meal_period: str,
    rows: list[dict],
) -> None:
    """Insert rows of {name, protein_g, calories, serving_size_amount, serving_size_unit}.

    Duplicate (date, hall, meal, item) rows are ignored rather than
    overwritten, since we never want to silently rewrite history with
    a later, possibly-estimated value.
    """
    conn.executemany(
        """
        INSERT OR IGNORE INTO menu_item_history
            (date, dining_hall, meal_period, item_name, protein_g, calories,
             serving_size_amount, serving_size_unit)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        [
            (
                d.isoformat(),
                dining_hall,
                meal_period,
                row["name"],
                row.get("protein_g"),
                row.get("calories"),
                row.get("serving_size_amount"),
                row.get("serving_size_unit"),
            )
            for row in rows
        ],
    )
    conn.commit()
