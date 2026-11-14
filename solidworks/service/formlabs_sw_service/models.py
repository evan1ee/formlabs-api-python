"""Domain data structures (spec §4.4). Frozen value objects; updates return copies."""

from __future__ import annotations

from enum import Enum
from typing import Any

from attrs import asdict, evolve, field, frozen


class Lock(str, Enum):
    """Per-model orientation lock (spec §6.4, D-09). Values are the API enum names (OD-02)."""

    ROTATION_LOCKED = "LOCKED_ROTATION_FREE_TRANSLATION"
    XY_ROTATION_FREE = "LOCKED_XY_ROTATION_FREE_TRANSLATION"
    FREE = "FREE"
    FULLY_LOCKED = "FULLY_LOCKED"  # hidden until OD-01 is resolved

    @property
    def rotation_locked(self) -> bool:
        return self is not Lock.FREE


# The default offered to users; FULLY_LOCKED is not selectable in the MVP.
DEFAULT_LOCK = Lock.ROTATION_LOCKED
SELECTABLE_LOCKS = (Lock.ROTATION_LOCKED, Lock.XY_ROTATION_FREE, Lock.FREE)


class BuildStatus(str, Enum):
    EMPTY = "EMPTY"
    HAS_MODELS = "HAS_MODELS"
    SUPPORTED = "SUPPORTED"
    LAID_OUT = "LAID_OUT"
    VALIDATED = "VALIDATED"
    BLOCKED = "BLOCKED"
    SAVED = "SAVED"
    SUBMITTED = "SUBMITTED"


class ValidationStatus(str, Enum):
    NOT_RUN = "NOT_RUN"
    PASSED = "PASSED"
    WARNINGS_ACKED = "WARNINGS_ACKED"
    BLOCKED = "BLOCKED"


class ModelStatus(str, Enum):
    IMPORTED = "IMPORTED"
    SUPPORTS_STALE = "SUPPORTS_STALE"
    SUPPORTED = "SUPPORTED"


class JobStatus(str, Enum):
    PENDING = "PENDING"
    IN_FLIGHT = "IN_FLIGHT"
    SUCCEEDED = "SUCCEEDED"
    FAILED = "FAILED"
    UNKNOWN = "UNKNOWN"


class OpState(str, Enum):
    INTENT = "INTENT"
    SENT = "SENT"
    SUCCEEDED = "SUCCEEDED"
    FAILED = "FAILED"
    UNCERTAIN = "UNCERTAIN"


@frozen
class PrintProject:
    project_id: str
    name: str
    folder: str
    created_at: str
    updated_at: str
    status: str = "ACTIVE"


@frozen
class Build:
    build_id: str
    project_id: str
    key: str
    machine_type: str
    material_code: str
    layer_thickness_mm: float | str
    print_setting: str
    print_setting_fingerprint: str
    form_file: str
    preform_scene_id: str | None = None  # session-only, never trusted after restart
    name: str = ""  # date-time-material; also the .form file name
    dirty: bool = False
    status: BuildStatus = BuildStatus.EMPTY
    validation_status: ValidationStatus = ValidationStatus.NOT_RUN
    support_params: dict[str, Any] = field(factory=dict)
    acked_warnings: list[str] = field(factory=list)

    def but(self, **changes: Any) -> "Build":
        return evolve(self, **changes)


@frozen
class PrintModel:
    model_id: str
    build_id: str
    source_document: str
    source_configuration: str
    source_body_name: str | None
    source_identity_key: str
    source_file: str
    source_file_hash: str
    export_format: str
    export_settings: dict[str, Any]
    import_chordal_tolerance_um: float
    import_angle_tolerance_deg: float
    print_cs_transform: list[list[float]]
    preform_model_id: str | None = None  # session-only
    preform_fingerprint: dict[str, Any] | None = None
    orientation_mode: str = "CAD"
    lock_mode: Lock = DEFAULT_LOCK
    status: ModelStatus = ModelStatus.IMPORTED

    def but(self, **changes: Any) -> "PrintModel":
        return evolve(self, **changes)


@frozen
class PrintJob:
    job_id: str
    build_id: str
    printer_id: str
    job_name: str
    form_file_snapshot: str
    print_now: bool = False  # always False in MVP
    submitted_at: str | None = None
    preform_operation_id: str | None = None
    status: JobStatus = JobStatus.PENDING
    error_code: str | None = None
    error_detail: str | None = None
    printer_job_id: str | None = None

    def but(self, **changes: Any) -> "PrintJob":
        return evolve(self, **changes)


@frozen
class OperationRecord:
    op_id: str
    kind: str
    build_id: str
    model_id: str | None
    state: OpState
    created_at: str
    updated_at: str
    preform_operation_id: str | None = None
    payload: dict[str, Any] = field(factory=dict)

    def but(self, **changes: Any) -> "OperationRecord":
        return evolve(self, **changes)


def to_plain(obj: Any) -> dict[str, Any]:
    return asdict(obj, value_serializer=lambda _i, _a, v: v.value if isinstance(v, Enum) else v)
