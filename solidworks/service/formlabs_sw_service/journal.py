"""Crash-safe operation journal: written BEFORE every mutating call (spec §12.2, rule 14)."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any

from attrs import asdict

from .db import Database
from .models import OperationRecord, OpState


def now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds")


def _to_doc(rec: OperationRecord) -> dict[str, Any]:
    d = asdict(rec)
    d["state"] = rec.state.value
    return d


def _from_doc(d: dict[str, Any]) -> OperationRecord:
    return OperationRecord(**{**d, "state": OpState(d["state"])})


class Journal:
    def __init__(self, db: Database) -> None:
        self._db = db

    def begin(
        self, kind: str, build_id: str, model_id: str | None = None, payload: dict[str, Any] | None = None
    ) -> OperationRecord:
        ts = now()
        rec = OperationRecord(
            op_id=uuid.uuid4().hex,
            kind=kind,
            build_id=build_id,
            model_id=model_id,
            state=OpState.INTENT,
            created_at=ts,
            updated_at=ts,
            payload=payload or {},
        )
        self._write(rec)
        return rec

    def mark(self, rec: OperationRecord, state: OpState, **changes: Any) -> OperationRecord:
        new = rec.but(state=state, updated_at=now(), **changes)
        self._write(new)
        return new

    def open_ops(self) -> list[OperationRecord]:
        docs = self._db.find("operation", "state IN (?,?)", (OpState.INTENT.value, OpState.SENT.value), "seq")
        return [_from_doc(d) for d in docs]

    def all_ops(self) -> list[OperationRecord]:
        return [_from_doc(d) for d in self._db.find("operation", order="seq")]

    def _write(self, rec: OperationRecord) -> None:
        existing = self._db.get("operation", "op_id", rec.op_id)
        seq = self._db.next_seq() if existing is None else self._seq_of(rec.op_id)
        self._db.put("operation", "op_id", rec.op_id, _to_doc(rec), state=rec.state.value, seq=seq)

    def _seq_of(self, op_id: str) -> int:
        with self._db._lock:  # noqa: SLF001 - same package
            return self._db._conn.execute("SELECT seq FROM operation WHERE op_id=?", (op_id,)).fetchone()[0]
