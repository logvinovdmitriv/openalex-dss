from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class EvidenceMode(str, Enum):
    BLOCKING = "blocking"
    REVIEW_REQUIRED = "review_required"
    EXPLANATORY = "explanatory"
    NOT_APPLICABLE = "not_applicable"


class EvidenceSource(str, Enum):
    OPEN_DATA = "open_data"
    LOCAL_CONFIRMED = "local_confirmed"
    USER_DECLARED = "user_declared"
    SYSTEM_EVENT = "system_event"


@dataclass(frozen=True)
class DataQuality:
    completeness: float
    reliability: float
    notes: tuple[str, ...] = ()

    def normalized(self) -> "DataQuality":
        return DataQuality(
            completeness=max(0.0, min(1.0, float(self.completeness))),
            reliability=max(0.0, min(1.0, float(self.reliability))),
            notes=tuple(str(item) for item in self.notes),
        )


@dataclass(frozen=True)
class Evidence:
    id: str
    label: str
    source: EvidenceSource
    mode: EvidenceMode
    quality: DataQuality
    payload: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class CandidateProfile:
    id: str
    display_name: str
    metrics: dict[str, float] = field(default_factory=dict)
    evidence: tuple[Evidence, ...] = ()


@dataclass(frozen=True)
class RuleProfile:
    id: str
    label: str
    version: str = "current"
    parameters: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class DecisionCase:
    id: str
    label: str
    rule_profile_id: str
    candidates: tuple[str, ...] = ()
    context: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class DecisionRun:
    id: str
    case_id: str
    rule_profile_id: str
    input_artifacts: dict[str, str]
    selected_candidates: tuple[str, ...] = ()
    status: str = "draft"


@dataclass(frozen=True)
class DecisionPassport:
    schema: str
    decision_run_id: str
    trace_hash: str
    input_checksums: dict[str, str]
    public_summary: dict[str, Any]
    internal_trace: dict[str, Any] = field(default_factory=dict)

