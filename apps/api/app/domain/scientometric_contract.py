from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class ScopedAnalysisContext:
    """Scoped ownership contract for all analytical use cases."""

    run_id: str = ""
    dump_id: str = ""

    def normalized(self) -> "ScopedAnalysisContext":
        return ScopedAnalysisContext(
            run_id=str(self.run_id or "").strip(),
            dump_id=str(self.dump_id or "").strip(),
        )

    @property
    def has_scope(self) -> bool:
        scoped = self.normalized()
        return bool(scoped.run_id or scoped.dump_id)

    def require(self) -> "ScopedAnalysisContext":
        scoped = self.normalized()
        if not scoped.has_scope:
            raise ValueError("Для аналитики нужен выбранный расчет или локальный срез.")
        return scoped


@dataclass(frozen=True)
class MetricModel:
    """Current metric model description used by rankings and future decision support."""

    id: str
    label: str
    expression: str = ""
    description: str = ""
    enabled: bool = True

    def normalized(self) -> "MetricModel":
        return MetricModel(
            id=str(self.id or "").strip(),
            label=str(self.label or self.id or "").strip(),
            expression=str(self.expression or "").strip(),
            description=str(self.description or "").strip(),
            enabled=bool(self.enabled),
        )


@dataclass(frozen=True)
class DataSelectionPolicy:
    """Table-selection policy shared by data, ranking, analytics and reports."""

    search: str = ""
    sort: str = ""
    direction: str = "desc"
    limit: int = 0
    filters: dict[str, Any] = field(default_factory=dict)
    author_ids: tuple[str, ...] = ()

    @classmethod
    def from_kwargs(cls, **kwargs: Any) -> "DataSelectionPolicy":
        author_ids = kwargs.get("author_ids") or ()
        if isinstance(author_ids, str):
            author_ids = tuple(item.strip() for item in author_ids.split(",") if item.strip())
        return cls(
            search=str(kwargs.get("data_search") or kwargs.get("search") or "").strip(),
            sort=str(kwargs.get("data_sort") or kwargs.get("sort") or "").strip(),
            direction="asc" if str(kwargs.get("data_direction") or kwargs.get("direction") or "desc").lower() == "asc" else "desc",
            limit=max(0, int(kwargs.get("data_limit") or kwargs.get("limit") or 0)),
            filters=dict(kwargs.get("data_filters") or kwargs.get("filters") or {}),
            author_ids=tuple(str(item).strip() for item in author_ids if str(item).strip()),
        )

    def to_query_kwargs(self) -> dict[str, Any]:
        return {
            "data_search": self.search,
            "data_sort": self.sort,
            "data_direction": self.direction,
            "data_limit": self.limit,
            "data_filters": self.filters,
        }


@dataclass(frozen=True)
class RankingUseCase:
    """Explicit use-case envelope for current MVP rankings and later DSS rules."""

    context: ScopedAnalysisContext
    primary_metric: str
    fraction_mode: str
    data_selection: DataSelectionPolicy = field(default_factory=DataSelectionPolicy)
    metric_models: tuple[MetricModel, ...] = ()

    def require_ready(self) -> "RankingUseCase":
        context = self.context.require()
        metric = str(self.primary_metric or "").strip()
        if not metric:
            raise ValueError("Для рейтинга нужен выбранный показатель.")
        return RankingUseCase(
            context=context,
            primary_metric=metric,
            fraction_mode=str(self.fraction_mode or "").strip() or "strict_authors_count",
            data_selection=self.data_selection,
            metric_models=tuple(normalized for model in self.metric_models if (normalized := model.normalized()).id),
        )
