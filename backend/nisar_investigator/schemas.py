"""Pydantic models. These are the source of truth for the API contract in docs/spec.md."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field

Tier = Literal["validated", "provisional", "beta"]
Direction = Literal["ascending", "descending"]
BBox = tuple[float, float, float, float]  # west, south, east, north


# ---------------------------------------------------------------- catalogue


class Granule(BaseModel):
    granule_id: str
    product: str  # GCOV, GUNW, GOFF, SME2
    tier: Tier
    url: str
    size_gb: float | None = None
    track: int
    frame: int
    direction: Direction
    mode: str
    polarizations: list[str] = Field(default_factory=list)  # frequency A
    # single-date products
    date: str | None = None
    start_time: str | None = None
    # pair products (GUNW, GOFF)
    reference_date: str | None = None
    secondary_date: str | None = None
    footprint: list[tuple[float, float]] = Field(default_factory=list)  # lon, lat


class Stack(BaseModel):
    """Acquisitions that share track, direction and frame, so their pixel grids line up."""

    product: str
    track: int
    direction: Direction
    frame: int
    dates: list[str]
    tiers: dict[str, int]
    polarizations: list[str]


class Coverage(BaseModel):
    query: dict[str, Any]
    products: dict[str, list[Granule]]
    stacks: list[Stack]
    notes: list[str] = Field(default_factory=list)


# ------------------------------------------------------------------ results


class Metric(BaseModel):
    key: str
    label: str
    unit: str = ""
    central: float | None = None
    low: float | None = None
    high: float | None = None


class Summary(BaseModel):
    headline: str
    metrics: list[Metric] = Field(default_factory=list)


class Legend(BaseModel):
    type: Literal["continuous", "categorical"] = "continuous"
    unit: str = ""
    min: float | None = None
    max: float | None = None
    colormap: str | None = None
    classes: list[dict[str, str]] = Field(default_factory=list)  # [{"label": ..., "color": "#rrggbb"}]


class Layer(BaseModel):
    id: str
    title: str
    kind: Literal["image"] = "image"
    url: str
    corners: list[tuple[float, float]]  # top-left, top-right, bottom-right, bottom-left (lon, lat)
    legend: Legend | None = None
    default_visible: bool = False
    date: str | None = None


class SeriesPoint(BaseModel):
    date: str
    value: float | None
    spread: float | None = None
    tier: Tier | None = None
    granule_id: str | None = None


class Series(BaseModel):
    id: str
    label: str
    unit: str = "dB"
    track: int | None = None
    direction: Direction | None = None
    polarization: str | None = None
    points: list[SeriesPoint]


class Sensitivity(BaseModel):
    parameter: str
    value: float | str
    result: float | None
    unit: str = ""


class Uncertainty(BaseModel):
    method: str
    sensitivity: list[Sensitivity] = Field(default_factory=list)
    noise_floor_fraction: float | None = None
    notes: list[str] = Field(default_factory=list)


class Caveat(BaseModel):
    code: str
    text: str


class ReceiptStep(BaseModel):
    name: str
    params: dict[str, Any] = Field(default_factory=dict)
    seconds: float | None = None


class ReceiptGranule(BaseModel):
    granule_id: str
    url: str
    tier: Tier
    product: str
    date: str | None = None
    reference_date: str | None = None
    secondary_date: str | None = None
    track: int
    frame: int
    direction: Direction
    polarizations: list[str] = Field(default_factory=list)


class Receipt(BaseModel):
    granules: list[ReceiptGranule] = Field(default_factory=list)
    steps: list[ReceiptStep] = Field(default_factory=list)
    software: dict[str, str] = Field(default_factory=dict)
    generated_at: str = ""
    reproduce: str = ""


class Download(BaseModel):
    label: str
    url: str
    format: str


class WorkflowResult(BaseModel):
    id: str
    workflow: Literal["change", "timeseries", "motion"]
    status: Literal["ok", "unsupported", "error"] = "ok"
    request: dict[str, Any] = Field(default_factory=dict)
    summary: Summary
    layers: list[Layer] = Field(default_factory=list)
    series: list[Series] = Field(default_factory=list)
    stats: dict[str, Any] = Field(default_factory=dict)
    uncertainty: Uncertainty | None = None
    caveats: list[Caveat] = Field(default_factory=list)
    receipt: Receipt = Field(default_factory=Receipt)
    downloads: list[Download] = Field(default_factory=list)


# ----------------------------------------------------------------- requests


class ChangeRequest(BaseModel):
    bbox: BBox
    date_before: str
    date_after: str
    track: int | None = None
    polarization: Literal["auto", "HH", "HV", "VV", "VH"] = "auto"


class TimeSeriesRequest(BaseModel):
    bbox: BBox
    geometry: dict[str, Any] | None = None  # GeoJSON Polygon, optional refinement inside bbox
    start: str | None = None
    end: str | None = None
    polarizations: list[str] = Field(default_factory=lambda: ["HH", "HV"])


class MotionRequest(BaseModel):
    bbox: BBox
    reference_date: str | None = None
    track: int | None = None


class InvestigateRequest(BaseModel):
    question: str
    bbox: BBox
    place_name: str | None = None


# ------------------------------------------------------------ investigation


class InvestigationStep(BaseModel):
    title: str
    detail: str = ""
    result_ref: str | None = None


class Report(BaseModel):
    answer: str
    observed: list[str] = Field(default_factory=list)
    possible_explanations: list[str] = Field(default_factory=list)
    unknown: list[str] = Field(default_factory=list)
    confidence: str = ""


class Investigation(BaseModel):
    id: str
    question: str
    place_name: str | None = None
    bbox: BBox
    steps: list[InvestigationStep] = Field(default_factory=list)
    results: dict[str, Any] = Field(default_factory=dict)
    report: Report | None = None
    model: str | None = None  # which language model planned the steps and wrote the report
