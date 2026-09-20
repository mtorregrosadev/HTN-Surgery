from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
import math
from typing import Any
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field, model_validator


def to_camel(value: str) -> str:
    first, *rest = value.split("_")
    return first + "".join(word.capitalize() for word in rest)


class ApiModel(BaseModel):
    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)


class Vector3(ApiModel):
    x: float
    y: float
    z: float


class Quaternion(ApiModel):
    qx: float
    qy: float
    qz: float
    qw: float

    @model_validator(mode="after")
    def unit_length(self) -> "Quaternion":
        magnitude = math.sqrt(self.qx**2 + self.qy**2 + self.qz**2 + self.qw**2)
        if not 0.99 <= magnitude <= 1.01:
            raise ValueError("orientation must be a unit quaternion")
        return self


class CalibrationCreate(ApiModel):
    device_id: str = Field(min_length=1)
    coordinate_frame: str = "right-handed-x-right-y-up-z-away"
    transform: list[float] = Field(min_length=16, max_length=16)
    rms_error_mm: float = Field(ge=0)
    valid: bool = True


class Calibration(CalibrationCreate):
    calibration_id: str
    version: int
    created_at: datetime


class SessionStatus(str, Enum):
    active = "active"
    completed = "completed"
    aborted = "aborted"


class SessionCreate(ApiModel):
    exercise_id: str = Field(min_length=1)
    calibration_id: str = Field(min_length=1)
    tool_id: str = Field(min_length=1)
    device_id: str = Field(min_length=1)


class Session(SessionCreate):
    session_id: str
    status: SessionStatus
    created_at: datetime
    completed_at: datetime | None = None
    last_sequence: int | None = None


SHOWCASE_TOOL_IDS = ("scalpel", "blunt-dissector", "chest-tube")


class ToolSample(ApiModel):
    contract_version: str = Field(default="1.1", pattern=r"^1\.(0|1)$")
    session_id: str = Field(min_length=1)
    tool_id: str = Field(min_length=1)
    device_id: str = Field(min_length=1)
    calibration_id: str = Field(min_length=1)
    sequence: int = Field(ge=0)
    timestamp_ms: int = Field(ge=0)
    received_at_ms: int | None = Field(default=None, ge=0)
    position_mm: Vector3
    orientation: Quaternion
    force_n: float = Field(ge=0)
    contact: bool
    quality: float = Field(default=1.0, ge=0, le=1)
    source_healthy: bool = True
    input_mode: str = Field(default="pose-only", pattern=r"^(pose-only|calibrated-hardware)$")
    force_measurement_valid: bool = False


class ToolState(ApiModel):
    tool_id: str = "scalpel"
    position_mm: Vector3
    orientation: Quaternion
    force_n: float = Field(ge=0)
    contact: bool
    contact_point_mm: Vector3 | None = None
    contact_normal: Vector3 | None = None
    reaction_force_n: float = Field(default=0, ge=0)
    penetration_depth_mm: float = Field(default=0, ge=0)


class TissueLayerState(ApiModel):
    layer_id: str
    opened: bool = False
    opening_progress: float = Field(default=0, ge=0, le=1)
    deformation_mm: float = Field(default=0, ge=0)


class TissueState(ApiModel):
    deformation_mm: float = Field(ge=0)
    incision_progress: float = Field(default=0, ge=0, le=1)
    incision_length_mm: float = Field(default=0, ge=0)
    incision_depth_mm: float = Field(default=0, ge=0)
    interaction_mode: str = "approach"
    active_layer: str = "none"
    layers: list[TissueLayerState] = Field(default_factory=list)


class DeformableMeshState(ApiModel):
    object_id: str = Field(min_length=1)
    topology_revision: int = Field(ge=1)
    vertices_mm: list[Vector3]
    triangle_indices: list[int]

    @model_validator(mode="after")
    def triangles_reference_existing_vertices(self) -> "DeformableMeshState":
        if len(self.triangle_indices) % 3:
            raise ValueError("triangleIndices must contain complete triangles")
        if self.triangle_indices and max(self.triangle_indices) >= len(self.vertices_mm):
            raise ValueError("triangleIndices references a missing vertex")
        if self.triangle_indices and min(self.triangle_indices) < 0:
            raise ValueError("triangleIndices cannot be negative")
        return self


class SimulationSnapshot(ApiModel):
    contract_version: str = Field(default="1.1", pattern=r"^1\.(0|1)$")
    session_id: str
    tick: int = Field(ge=0)
    simulation_time_ms: int = Field(ge=0)
    simulation_backend: str = "memory-development-only"
    procedure_stage: str = "approach"
    session_degraded: bool = False
    tool: ToolState
    tissue: TissueState
    deformable_meshes: list[DeformableMeshState] = Field(default_factory=list)
    events: list[str] = Field(default_factory=list)


class SessionMetrics(ApiModel):
    sample_count: int
    duration_ms: int
    contact_time_ms: int
    peak_force_n: float
    mean_contact_force_n: float
    mean_target_offset_mm: float
    peak_target_offset_mm: float
    force_consistency_n: float
    controlled_contact_percent: float
    illustrative_score_percent: float
    incision_length_mm: float = 0
    max_incision_depth_mm: float = 0
    incision_progress_percent: float = 0
    mean_instrument_angle_deg: float = 0
    mean_reaction_force_n: float = 0
    outside_corridor_contacts: int = 0
    layer_violations: int = 0
    tube_placement_complete: bool = False


class SessionResult(ApiModel):
    session: Session
    metrics: SessionMetrics


class Health(ApiModel):
    status: str
    persistence: str
    simulation: str


def new_id(prefix: str) -> str:
    return f"{prefix}-{uuid4().hex[:12]}"


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def mongo_document(model: ApiModel) -> dict[str, Any]:
    return model.model_dump(by_alias=True, mode="json")


class ResultRecord(ApiModel):
    """A stored scorecard. Derived from the samples/snapshots, kept so progress can be charted."""

    session_id: str
    exercise_id: str
    device_id: str
    tool_id: str
    completed_at: datetime
    metrics: SessionMetrics


class TrendPoint(ApiModel):
    session_id: str
    completed_at: datetime
    score_percent: float


class ProgressSummary(ApiModel):
    attempts: int
    latest_score_percent: float | None = None
    best_score_percent: float | None = None
    average_score_percent: float | None = None
    improvement_points: float | None = None     # latest minus first attempt
    weakest_component: str | None = None
    component_averages: dict[str, float] = Field(default_factory=dict)
    trend: list[TrendPoint] = Field(default_factory=list)
