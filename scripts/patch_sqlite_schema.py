# scripts/patch_sqlite_schema.py
"""
Patch SQLite schema in ./data/bot.sqlite3 to match current ORM models.

- Ensures TEXT timestamps exist with sane defaults:
  * applications: created_at, updated_at, reason
  * invites:      created_at, updated_at
  * blacklist:    created_at
  * roster:       id (INTEGER PRIMARY KEY AUTOINCREMENT) if missing (safety)

All new timestamp columns are added as:
  TEXT NOT NULL DEFAULT (CURRENT_TIMESTAMP)

Run:
    python scripts/patch_sqlite_schema.py
"""

from __future__ import annotations
import os
import sqlite3
from contextlib import closing

DB_PATH = os.environ.get("BOT_DB_PATH", "./data/bot.sqlite3")


def table_exists(cur: sqlite3.Cursor, table: str) -> bool:
    """Return True if table exists in SQLite schema."""
    cur.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name=?;",
        (table,),
    )
    return cur.fetchone() is not None


def column_names(cur: sqlite3.Cursor, table: str) -> set[str]:
    """Return a set of column names for given table (or empty set if table absent)."""
    if not table_exists(cur, table):
        return set()
    cur.execute(f"PRAGMA table_info({table});")
    return {row[1] for row in cur.fetchall()}  # row[1] = name


def add_column(cur: sqlite3.Cursor, table: str, ddl: str) -> bool:
    """
    Add column to table using provided column DDL snippet.

    Example:
        add_column(cur, "invites", "updated_at TEXT NOT NULL DEFAULT (CURRENT_TIMESTAMP)")
    Returns True if column was added, False if it already exists.
    """
    # Extract column name from DDL (first token before space)
    col = ddl.strip().split()[0]
    cols = column_names(cur, table)
    if col in cols:
        print(f"[{table}] ok: колонка '{col}' уже существует")
        return False
    cur.execute(f"ALTER TABLE {table} ADD COLUMN {ddl};")
    print(f"[{table}] ➕ добавлена колонка: {ddl}")
    return True


def ensure_roster_pk(cur: sqlite3.Cursor) -> None:
    """
    Safety: ensure roster has 'id' column. If нет — просто предупреждаем.
    (Добавлять PK в уже существующую таблицу без пересоздания нельзя.)
    """
    cols = column_names(cur, "roster")
    if "id" not in cols:
        print("[roster] ⚠️ нет колонки 'id'. "
              "Если понадобятся ссылочные ключи — пересоздайте таблицу с PK.")
    else:
        print("[roster] ok: 'id' присутствует")


def main() -> None:
    """Open DB and patch schema safely."""
    print(f"DB: {DB_PATH}")
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)

    with closing(sqlite3.connect(DB_PATH)) as con, closing(con.cursor()) as cur:
        con.execute("PRAGMA foreign_keys = ON;")

        # --- applications ---
        if table_exists(cur, "applications"):
            add_column(cur, "applications", "reason TEXT")
            add_column(cur, "applications", "created_at TEXT NOT NULL DEFAULT (CURRENT_TIMESTAMP)")
            add_column(cur, "applications", "updated_at TEXT NOT NULL DEFAULT (CURRENT_TIMESTAMP)")
        else:
            print("[applications] ⚠️ таблица не найдена — пропускаю")

        # --- invites ---
        if table_exists(cur, "invites"):
            add_column(cur, "invites", "created_at TEXT NOT NULL DEFAULT (CURRENT_TIMESTAMP)")
            add_column(cur, "invites", "updated_at TEXT NOT NULL DEFAULT (CURRENT_TIMESTAMP)")
        else:
            print("[invites] ⚠️ таблица не найдена — пропускаю")

        # --- blacklist ---
        if table_exists(cur, "blacklist"):
            add_column(cur, "blacklist", "created_at TEXT NOT NULL DEFAULT (CURRENT_TIMESTAMP)")
        else:
            print("[blacklist] ⚠️ таблица не найдена — пропускаю")

        # --- roster ---
        if table_exists(cur, "roster"):
            ensure_roster_pk(cur)
        else:
            print("[roster] ⚠️ таблица не найдена — пропускаю")

        con.commit()
        print("✅ Патч схемы завершён.")


if __name__ == "__main__":
    main()
