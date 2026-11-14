"""Application error codes (spec §12.1). Each error carries the context fields."""

from __future__ import annotations

SERVICE_START_FAILED = "SERVICE_START_FAILED"
SERVICE_AUTH_FAILED = "SERVICE_AUTH_FAILED"
MODEL_IDENTITY_MISMATCH = "MODEL_IDENTITY_MISMATCH"
OPERATION_STATE_UNCERTAIN = "OPERATION_STATE_UNCERTAIN"
LAYOUT_WOULD_EJECT = "LAYOUT_WOULD_EJECT"
PREFORM_SERVER_VERSION_UNSUPPORTED = "PREFORM_SERVER_VERSION_UNSUPPORTED"
PREFORM_PORT_IN_USE = "PREFORM_PORT_IN_USE"
MATERIAL_NOT_SUPPORTED = "MATERIAL_NOT_SUPPORTED"
PATH_OUTSIDE_PROJECT = "PATH_OUTSIDE_PROJECT"
VALIDATION_BLOCKED = "VALIDATION_BLOCKED"
PRINTER_MISMATCH = "PRINTER_MISMATCH"
NOT_FOUND = "NOT_FOUND"
BAD_REQUEST = "BAD_REQUEST"
PREFORM_API_ERROR = "PREFORM_API_ERROR"
PREFORM_NOT_RUNNING = "PREFORM_NOT_RUNNING"


class ServiceError(Exception):
    """Wraps an application code plus the original API code/message (never discarded)."""

    def __init__(
        self,
        app_code: str,
        message: str = "",
        *,
        api_code: str | None = None,
        api_message: str | None = None,
        operation_id: str | None = None,
        build_id: str | None = None,
        model_id: str | None = None,
    ) -> None:
        super().__init__(f"{app_code}: {message}" if message else app_code)
        self.app_code = app_code
        self.message = message
        self.api_code = api_code
        self.api_message = api_message
        self.operation_id = operation_id
        self.build_id = build_id
        self.model_id = model_id

    def to_dict(self) -> dict:
        return {
            "app_code": self.app_code,
            "message": self.message,
            "api_code": self.api_code,
            "api_message": self.api_message,
            "operation_id": self.operation_id,
            "build_id": self.build_id,
            "model_id": self.model_id,
        }
