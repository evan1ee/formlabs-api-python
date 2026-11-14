"""SQLite persistence with versioned migrations (spec §4.4). One database per project folder.

Rows are JSON documents keyed by id, with the few columns we query on pulled out.
"""

from __future__ import annotations

import json
import sqlite3
import threading
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator

MIGRATIONS: list[str] = [
    # v1
    """
    CREATE TABLE project (project_id TEXT PRIMARY KEY, doc TEXT NOT NULL);
    CREATE TABLE build (build_id TEXT PRIMARY KEY, key TEXT NOT NULL UNIQUE, doc TEXT NOT NULL);
    CREATE TABLE model (model_id TEXT PRIMARY KEY, build_id TEXT NOT NULL,
                        identity_key TEXT NOT NULL UNIQUE, doc TEXT NOT NULL);
    CREATE TABLE job (job_id TEXT PRIMARY KEY, build_id TEXT NOT NULL, doc TEXT NOT NULL);
    CREATE TABLE operation (op_id TEXT PRIMARY KEY, state TEXT NOT NULL, seq INTEGER NOT NULL, doc TEXT NOT NULL);
    CREATE TABLE catalog_cache (server_version TEXT PRIMARY KEY, doc TEXT NOT NULL);
    """,
]


class Database:
    def __init__(self, path: str | Path) -> None:
        self.path = str(path)
        self._lock = threading.RLock()
        self._conn = sqlite3.connect(self.path, check_same_thread=False, isolation_level=None)
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._migrate()

    def _migrate(self) -> None:
        with self._lock:
            current = self._conn.execute("PRAGMA user_version").fetchone()[0]
            for version, script in enumerate(MIGRATIONS, start=1):
                if version > current:
                    self._conn.executescript(
                        "BEGIN;" + script + f"PRAGMA user_version={version};COMMIT;"
                    )

    @property
    def schema_version(self) -> int:
        return self._conn.execute("PRAGMA user_version").fetchone()[0]

    @contextmanager
    def tx(self) -> Iterator[sqlite3.Connection]:
        with self._lock:
            self._conn.execute("BEGIN")
            try:
                yield self._conn
            except BaseException:
                self._conn.execute("ROLLBACK")
                raise
            else:
                self._conn.execute("COMMIT")

    def put(self, table: str, id_col: str, id_: str, doc: dict[str, Any], **cols: Any) -> None:
        names = [id_col, *cols, "doc"]
        vals = [id_, *cols.values(), json.dumps(doc, sort_keys=True)]
        sql = (
            f"INSERT OR REPLACE INTO {table} ({','.join(names)}) "
            f"VALUES ({','.join('?' * len(names))})"
        )
        with self._lock:
            self._conn.execute(sql, vals)

    def get(self, table: str, id_col: str, id_: str) -> dict[str, Any] | None:
        with self._lock:
            row = self._conn.execute(
                f"SELECT doc FROM {table} WHERE {id_col}=?", (id_,)
            ).fetchone()
        return json.loads(row[0]) if row else None

    def find(
        self, table: str, where: str = "1=1", args: tuple = (), order: str = "rowid"
    ) -> list[dict[str, Any]]:
        with self._lock:
            rows = self._conn.execute(
                f"SELECT doc FROM {table} WHERE {where} ORDER BY {order}", args
            ).fetchall()
        return [json.loads(r[0]) for r in rows]

    def delete(self, table: str, id_col: str, id_: str) -> None:
        with self._lock:
            self._conn.execute(f"DELETE FROM {table} WHERE {id_col}=?", (id_,))

    def next_seq(self) -> int:
        with self._lock:
            row = self._conn.execute("SELECT COALESCE(MAX(seq),0)+1 FROM operation").fetchone()
        return row[0]

    def close(self) -> None:
        with self._lock:
            self._conn.close()
