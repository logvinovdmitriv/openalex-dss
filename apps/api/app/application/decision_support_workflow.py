from __future__ import annotations

import hashlib
import json
from typing import Any

from app.domain.decision_support import DecisionCase, DecisionPassport, DecisionRun, RuleProfile
from app.domain.scientometric_contract import RankingUseCase


SCIENTOMETRIC_RANKING_RULE = RuleProfile(
    id="scientometric_ranking",
    label="Предметный рейтинг исследователей",
    parameters={
        "scope_required": True,
        "primary_metric_required": True,
        "tie_breaker": "author_id",
    },
)


def ranking_decision_case(
    use_case: RankingUseCase,
    *,
    label: str = "Предметный рейтинг исследователей",
    rule_profile: RuleProfile = SCIENTOMETRIC_RANKING_RULE,
    candidate_ids: tuple[str, ...] | list[str] = (),
) -> DecisionCase:
    """Represent a ready ranking use case as a formal decision case."""

    ready = use_case.require_ready()
    normalized_candidates = tuple(str(item).strip() for item in candidate_ids if str(item).strip())
    context = {
        "run_id": ready.context.run_id,
        "dump_id": ready.context.dump_id,
        "primary_metric": ready.primary_metric,
        "fraction_mode": ready.fraction_mode,
        "data_selection": ready.data_selection.to_query_kwargs(),
        "metric_models": [model.__dict__ for model in ready.metric_models],
    }
    case_id = f"case_{_stable_hash({'rule': rule_profile.id, 'context': context, 'candidates': normalized_candidates})}"
    return DecisionCase(
        id=case_id,
        label=str(label or rule_profile.label).strip(),
        rule_profile_id=rule_profile.id,
        candidates=normalized_candidates,
        context=context,
    )


def ranking_decision_run(
    use_case: RankingUseCase,
    *,
    decision_run_id: str = "",
    label: str = "Предметный рейтинг исследователей",
    rule_profile: RuleProfile = SCIENTOMETRIC_RANKING_RULE,
    candidate_ids: tuple[str, ...] | list[str] = (),
    input_artifacts: dict[str, str] | None = None,
    status: str = "draft",
) -> DecisionRun:
    """Create a decision-run envelope without changing scoped storage ownership."""

    case = ranking_decision_case(use_case, label=label, rule_profile=rule_profile, candidate_ids=candidate_ids)
    artifacts = dict(input_artifacts or {})
    run_id = str(case.context.get("run_id") or "").strip()
    dump_id = str(case.context.get("dump_id") or "").strip()
    if run_id:
        artifacts.setdefault("run_id", run_id)
    if dump_id:
        artifacts.setdefault("dump_id", dump_id)
    decision_id = str(decision_run_id or f"decision_{_stable_hash({'case_id': case.id, 'artifacts': artifacts})}").strip()
    return DecisionRun(
        id=decision_id,
        case_id=case.id,
        rule_profile_id=case.rule_profile_id,
        input_artifacts={str(key): str(value) for key, value in artifacts.items() if str(value).strip()},
        selected_candidates=case.candidates,
        status=str(status or "draft").strip(),
    )


def decision_passport(
    decision_run: DecisionRun,
    *,
    input_checksums: dict[str, str] | None = None,
    public_summary: dict[str, Any] | None = None,
    internal_trace: dict[str, Any] | None = None,
) -> DecisionPassport:
    """Build a minimal reproducibility envelope for a decision-support run."""

    checksums = {str(key): str(value) for key, value in (input_checksums or {}).items() if str(value).strip()}
    trace = {
        "decision_run_id": decision_run.id,
        "case_id": decision_run.case_id,
        "rule_profile_id": decision_run.rule_profile_id,
        "input_artifacts": decision_run.input_artifacts,
        "selected_candidates": decision_run.selected_candidates,
        "status": decision_run.status,
        "input_checksums": checksums,
        **dict(internal_trace or {}),
    }
    return DecisionPassport(
        schema="decision_passport",
        decision_run_id=decision_run.id,
        trace_hash=_stable_hash(trace),
        input_checksums=checksums,
        public_summary=dict(public_summary or {}),
        internal_trace=trace,
    )


def _stable_hash(payload: Any) -> str:
    normalized = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()[:16]
