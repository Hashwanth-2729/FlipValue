"""Request and response models for POST /v1/valuations (INTEGRATION_CONTRACT.md §3-§6)."""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Annotated, Literal, get_args

from pydantic import BaseModel, ConfigDict, Field, PlainSerializer, model_validator

from flipvalue.condition import Assessment

# Money is computed with Decimal but sent as a JSON number (contract §4: major units, JSON numbers).
Money = Annotated[Decimal, PlainSerializer(float, return_type=float, when_used="json")]

Grade = Literal["excellent", "good", "fair", "poor", "faulty"]
Fault = Literal[
    "software_instability",
    "storage_pressure",
    "battery_wear",
    "charging_path",
    "display_damage",
    "camera_fault",
    "audio_fault",
    "connectivity_issue",
    "liquid_damage",
]
RepairType = Literal[
    "battery_replacement",
    "charging_port_replacement",
    "screen_replacement",
    "camera_module_replacement",
    "audio_component_replacement",
    "liquid_damage_service",
    "software_reset",
]

GRADES: tuple[str, ...] = get_args(Grade)


class _Request(BaseModel):
    # Strict: unknown fields are rejected so typos surface as 422 instead of being ignored.
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class Device(_Request):
    manufacturer: str = Field(min_length=1, max_length=80, examples=["Samsung"])
    model: str = Field(min_length=1, max_length=80, examples=["SM-G991B"])
    storage_gb: int | None = Field(default=None, ge=1, le=4096, strict=True)
    age_months: int | None = Field(default=None, ge=0, le=240, strict=True)


class Condition(_Request):
    grade: Grade
    faults: list[Fault] = Field(max_length=20)


class RepairScenario(_Request):
    repair_type: RepairType


class ValuationRequest(_Request):
    device: Device
    region: str = Field(pattern=r"^[A-Z]{2}$", examples=["IN"])
    currency: str = Field(pattern=r"^[A-Z]{3}$", examples=["INR"])
    condition: Condition
    repair_scenario: RepairScenario | None = None


def _is_none(value: object) -> bool:
    return value is None


class ValueBand(BaseModel):
    # Like the request side of the contract: an unknown range is omitted, not sent as null.
    value: float = Field(ge=0)
    low: float | None = Field(default=None, ge=0, exclude_if=_is_none)
    high: float | None = Field(default=None, ge=0, exclude_if=_is_none)

    @model_validator(mode="after")
    def _ordered(self) -> ValueBand:
        if self.low is not None and self.low > self.value:
            raise ValueError("low must be <= value")
        if self.high is not None and self.high < self.value:
            raise ValueError("high must be >= value")
        return self


class Valuation(BaseModel):
    api_version: str = "1"
    valuation_id: str = Field(max_length=100)
    currency: str = Field(pattern=r"^[A-Z]{3}$")
    as_is: ValueBand
    after_repair: ValueBand | None = None
    data_timestamp: datetime
    method: str = Field(max_length=200)
    status: Literal["ok", "partial"]
    warnings: list[str] = Field(default_factory=list, max_length=20)
    mock: bool = Field(default=False, description="True only when the values come from mock rows.")


class ErrorBody(BaseModel):
    code: str
    message: str
    request_id: str


class ErrorResponse(BaseModel):
    error: ErrorBody


# --- public website API (/api) ---------------------------------------------------------------
# Richer than the partner contract: it carries the evidence and explanation the website shows.


class PublicDevice(_Request):
    model_id: str = Field(min_length=1, max_length=80)
    storage_gb: int | None = Field(default=None, ge=1, le=4096, strict=True)


class PublicValuationRequest(_Request):
    device: PublicDevice
    region: str = Field(pattern=r"^[A-Z]{2}$")
    currency: str = Field(pattern=r"^[A-Z]{3}$")
    assessment: Assessment
    repair_type: RepairType | None = None


class SourceRef(BaseModel):
    id: str
    name: str
    source_type: str
    verified: bool
    is_mock: bool


class EstimateOut(BaseModel):
    value: Money
    low: Money
    high: Money
    range_method: Literal["p10_p90", "min_max"]
    basis: str
    basis_label: str
    quality: Literal["evidence_backed", "limited", "modelled"]
    observation_count: int
    oldest_observation: date
    newest_observation: date
    sources: list[SourceRef]


class DeviceOut(BaseModel):
    model_id: str
    manufacturer: str
    name: str
    storage_gb: int
    storage_inferred: bool


class ConditionOut(BaseModel):
    grade: Grade
    faults: list[str]
    reasons: list[str]
    uncertainties: list[str]
    not_used: list[str]
    safety: list[str]
    customer_reported: bool = True


class PublicValuation(BaseModel):
    valuation_id: str
    method_version: str
    mock: bool
    generated_at: datetime
    region: str
    currency: str
    status: Literal["ok", "partial", "unavailable"]
    device: DeviceOut
    condition: ConditionOut
    as_is: EstimateOut | None
    as_is_unavailable_reason: str | None
    repair_type: RepairType | None
    assumed_grade_after_repair: Grade | None
    after_repair: EstimateOut | None
    after_repair_unavailable_reason: str | None
    trade_in: EstimateOut | None
    explanation: list[str]
    warnings: list[str]
    value_types: PublicValueTypes | None = None


# --- developer API (/api/v1) -----------------------------------------------------------------------------------

Confidence = Literal["high", "medium", "low", "insufficient"]
ValueType = Literal["private_sale", "buyback", "refurbished_retail", "after_repair", "original_retail"]


class ApiDevice(_Request):
    """Identify the phone by catalogue `product_id`, or by `manufacturer` + `model` (name or OEM code)."""

    product_id: str | None = Field(default=None, min_length=1, max_length=80, examples=["samsung-galaxy-s21"])
    manufacturer: str | None = Field(default=None, min_length=1, max_length=80, examples=["Samsung"])
    model: str | None = Field(default=None, min_length=1, max_length=80, examples=["SM-G991B"])
    storage_gb: int | None = Field(default=None, ge=1, le=4096, strict=True)
    age_months: int | None = Field(default=None, ge=0, le=240, strict=True)

    @model_validator(mode="after")
    def _identity(self) -> ApiDevice:
        if self.product_id is None and not (self.manufacturer and self.model):
            raise ValueError("give device.product_id, or device.manufacturer and device.model")
        return self


class ApiValuationRequest(_Request):
    device: ApiDevice
    region: str = Field(pattern=r"^[A-Z]{2}$", examples=["IN"])
    currency: str = Field(pattern=r"^[A-Z]{3}$", examples=["INR"])
    condition: Condition
    repair_scenario: RepairScenario | None = None


class EvidenceSource(BaseModel):
    id: str
    name: str
    source_type: str
    verified: bool
    is_mock: bool


class ValueEstimateV1(BaseModel):
    type: ValueType
    available: bool
    value: Money | None = None
    low: Money | None = None
    high: Money | None = None
    basis: str | None = None
    basis_label: str | None = None
    range_method: str | None = None
    confidence: Confidence
    observation_count: int = 0
    oldest_observation: date | None = None
    newest_observation: date | None = None
    sources: list[EvidenceSource] = []
    reason: str | None = Field(default=None, description="Why the value is unavailable or limited.")


class PublicValueTypes(BaseModel):
    """Other kinds of value for the same phone. Each is unavailable (with a reason) rather than guessed."""

    buyback: ValueEstimateV1
    refurbished_retail: ValueEstimateV1
    original_retail: ValueEstimateV1


class ProductRef(BaseModel):
    id: str
    manufacturer: str
    name: str
    storage_gb: int
    storage_inferred: bool


class RepairComparison(BaseModel):
    repair_type: RepairType
    assumed_grade_after_repair: Grade
    value_uplift: Money | None = Field(description="after_repair.value - private_sale.value; null when either is "
                                                   "unavailable. Excludes the repair cost.")
    confidence: Confidence
    note: str


class ValuationV1(BaseModel):
    id: str = Field(description="Random id; GET /api/v1/valuations/{id} works only for the same account or key.")
    object: Literal["valuation"] = "valuation"
    api_version: str = "1"
    created_at: datetime
    method: str
    status: Literal["ok", "partial", "unavailable"]
    mock: bool
    region: str
    currency: str
    product: ProductRef
    condition: Condition
    private_sale: ValueEstimateV1
    buyback: ValueEstimateV1
    refurbished_retail: ValueEstimateV1
    original_retail: ValueEstimateV1
    after_repair: ValueEstimateV1 | None
    repair: RepairComparison | None
    confidence: Confidence
    data_timestamp: date | None
    assumptions: list[str]
    limitations: list[str]
    missing_data: list[str]
    how_to_improve: list[str]
    warnings: list[str]


class CatalogueModelOut(BaseModel):
    id: str
    manufacturer: str
    name: str
    release_date: date | None
    storage_gb: list[int]
    oem_codes: list[str]
    evidence: dict[str, Literal["evidence_backed", "limited", "estimated", "mock_only", "insufficient"]]


class TrendPoint(BaseModel):
    month: str
    median: Money
    count: int


class TrendOut(BaseModel):
    model_id: str
    storage_gb: int
    region: str
    currency: str
    grade: Grade
    available: bool
    reason: str | None
    series: dict[str, list[TrendPoint]]
    min_observations_per_month: int
    mock_data_excluded: bool = True


class SavedValuationOut(BaseModel):
    id: str
    created_at: datetime
    result: PublicValuation


class SaveResponse(BaseModel):
    id: str
    delete_token: str = Field(description="Shown once. Needed to delete the saved valuation; keep it private.")
    result: PublicValuation


PublicValuation.model_rebuild()
