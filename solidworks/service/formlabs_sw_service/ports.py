"""The PreForm port: the only interface the service core uses to talk to PreForm (spec §3.4).

`sdk_adapter.SdkAdapter` implements it with formlabs-sdk; tests use an in-memory fake.
"""

from __future__ import annotations

from typing import Any, Protocol

from attrs import frozen


@frozen
class RemoteModel:
    model_id: str
    name: str
    lock: str
    fingerprint: dict[str, Any]


@frozen
class CheckResult:
    """Outcome of one validate_* call. `flagged` maps preform model id -> detail."""

    check: str
    passed: bool
    flagged: dict[str, Any]
    raw: dict[str, Any]


@frozen
class Device:
    serial: str
    machine_type: str
    ready_to_print_now: bool | None


@frozen
class LayoutResult:
    ok: bool
    unplaced_model_ids: list[str]


class PreformPort(Protocol):
    def server_version(self) -> str: ...

    def list_print_settings(self) -> dict[str, Any]: ...

    def validate_print_setting(
        self, machine_type: str, material_code: str, layer: float | str, print_setting: str
    ) -> tuple[bool, dict[str, Any]]: ...

    def create_scene(
        self, machine_type: str, material_code: str, layer: float | str, print_setting: str
    ) -> str: ...

    def open_form_file(self, path: str) -> str: ...

    def scene_exists(self, scene_id: str) -> bool: ...

    def save_form_file(self, scene_id: str, path: str, project_name: str = "") -> None: ...

    def delete_scene(self, scene_id: str) -> None: ...

    def import_model(
        self,
        scene_id: str,
        file: str,
        *,
        name: str,
        lock: str,
        units: str,
        chordal_tolerance_um: float,
        angle_tolerance_deg: float,
    ) -> str: ...

    def replace_model(self, scene_id: str, model_id: str, replacement_model_id: str) -> None: ...

    def delete_models(self, scene_id: str, model_ids: list[str]) -> None: ...

    def list_models(self, scene_id: str) -> list[RemoteModel]: ...

    def auto_support(self, scene_id: str, params: dict[str, Any], model_ids: list[str] | None = None) -> None: ...

    def regenerate_supports(self, scene_id: str, model_ids: list[str]) -> None: ...

    def auto_layout(
        self, scene_id: str, *, lock_rotation: bool, seed: int, model_spacing_mm: float
    ) -> LayoutResult: ...

    def run_check(self, scene_id: str, check: str) -> CheckResult: ...

    def list_devices(self) -> list[Device]: ...

    def print_scene(self, scene_id: str, printer: str, job_name: str) -> str | None:
        """Queue the scene. The implementation MUST send print_now=False (spec rule 9)."""
        ...
