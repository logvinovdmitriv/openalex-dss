from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
API = ROOT / "apps/api"
if str(API) not in sys.path:
    sys.path.insert(0, str(API))

from app.domain.decision_support import CandidateProfile, DataQuality, Evidence, EvidenceMode, EvidenceSource


def test_decision_support_domain_objects_are_immutable_and_normalize_quality() -> None:
    quality = DataQuality(completeness=2.0, reliability=-1.0, notes=("openalex",)).normalized()
    evidence = Evidence(
        id="ev_1",
        label="Открытый наукометрический признак",
        source=EvidenceSource.OPEN_DATA,
        mode=EvidenceMode.EXPLANATORY,
        quality=quality,
        payload={"metric": "h"},
    )
    profile = CandidateProfile(id="A1", display_name="Иванов И. И.", metrics={"h": 5.0}, evidence=(evidence,))

    assert profile.evidence[0].quality.completeness == 1.0
    assert profile.evidence[0].quality.reliability == 0.0
    assert profile.evidence[0].mode == EvidenceMode.EXPLANATORY
