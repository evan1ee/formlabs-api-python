"""Typed repository over Database for Build / PrintModel / PrintJob (spec §4.4)."""

from __future__ import annotations

from typing import Any

from attrs import asdict

from .db import Database
from .models import (
    Build,
    BuildStatus,
    JobStatus,
    Lock,
    ModelStatus,
    PrintJob,
    PrintModel,
    ValidationStatus,
)


def _doc(obj: Any) -> dict[str, Any]:
    d = asdict(obj)
    for k, v in list(d.items()):
        if hasattr(v, "value"):
            d[k] = v.value
    return d


class Store:
    def __init__(self, db: Database) -> None:
        self.db = db

    # builds
    def put_build(self, b: Build) -> None:
        self.db.put("build", "build_id", b.build_id, _doc(b), key=b.key)

    def get_build(self, build_id: str) -> Build | None:
        d = self.db.get("build", "build_id", build_id)
        return self._build(d) if d else None

    def build_by_key(self, key: str) -> Build | None:
        rows = self.db.find("build", "key=?", (key,))
        return self._build(rows[0]) if rows else None

    def builds(self) -> list[Build]:
        return [self._build(d) for d in self.db.find("build")]

    @staticmethod
    def _build(d: dict[str, Any]) -> Build:
        return Build(
            **{
                **d,
                "status": BuildStatus(d["status"]),
                "validation_status": ValidationStatus(d["validation_status"]),
                "preform_scene_id": None,  # never trusted across restarts
            }
        )

    # models
    def put_model(self, m: PrintModel) -> None:
        self.db.put(
            "model", "model_id", m.model_id, _doc(m), build_id=m.build_id, identity_key=m.source_identity_key
        )

    def get_model(self, model_id: str) -> PrintModel | None:
        d = self.db.get("model", "model_id", model_id)
        return self._model(d) if d else None

    def model_by_identity(self, identity: str) -> PrintModel | None:
        rows = self.db.find("model", "identity_key=?", (identity,))
        return self._model(rows[0]) if rows else None

    def models_of(self, build_id: str) -> list[PrintModel]:
        return [self._model(d) for d in self.db.find("model", "build_id=?", (build_id,))]

    def delete_model(self, model_id: str) -> None:
        self.db.delete("model", "model_id", model_id)

    @staticmethod
    def _model(d: dict[str, Any]) -> PrintModel:
        return PrintModel(
            **{**d, "lock_mode": Lock(d["lock_mode"]), "status": ModelStatus(d["status"]), "preform_model_id": None}
        )

    # jobs
    def put_job(self, j: PrintJob) -> None:
        self.db.put("job", "job_id", j.job_id, _doc(j), build_id=j.build_id)

    def jobs_of(self, build_id: str | None = None) -> list[PrintJob]:
        rows = self.db.find("job", "build_id=?", (build_id,)) if build_id else self.db.find("job")
        return [PrintJob(**{**d, "status": JobStatus(d["status"])}) for d in rows]
