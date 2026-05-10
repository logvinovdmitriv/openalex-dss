from __future__ import annotations

from typing import Any


def describe(values: list[float]) -> dict[str, Any]:
    clean = sorted(float(value) for value in values if value == value)
    if not clean:
        return {
            "n": 0,
            "min": 0,
            "q1": 0,
            "median": 0,
            "mean": 0,
            "q3": 0,
            "p90": 0,
            "max": 0,
            "stddev": 0,
            "unique_count": 0,
            "zero_count": 0,
            "zero_rate": None,
            "chart_readiness": chart_readiness([], chart_type="distribution"),
        }
    mean = sum(clean) / len(clean)
    variance = sum((value - mean) ** 2 for value in clean) / (len(clean) - 1) if len(clean) > 1 else 0.0
    unique_count = len(set(clean))
    zero_count = sum(1 for value in clean if value == 0.0)
    return {
        "n": len(clean),
        "min": clean[0],
        "q1": quantile(clean, 0.25),
        "median": quantile(clean, 0.50),
        "mean": mean,
        "q3": quantile(clean, 0.75),
        "p90": quantile(clean, 0.90),
        "max": clean[-1],
        "stddev": variance**0.5,
        "unique_count": unique_count,
        "zero_count": zero_count,
        "zero_rate": zero_count / len(clean) if clean else None,
        "chart_readiness": chart_readiness(clean, chart_type="distribution"),
    }


def quantile(values: list[float], q: float) -> float:
    if not values:
        return 0.0
    sorted_values = sorted(values)
    if len(sorted_values) == 1:
        return sorted_values[0]
    pos = (len(sorted_values) - 1) * q
    lower = int(pos)
    upper = min(lower + 1, len(sorted_values) - 1)
    weight = pos - lower
    return sorted_values[lower] * (1 - weight) + sorted_values[upper] * weight


def histogram(values: list[float], bins: int) -> list[dict[str, Any]]:
    clean = [float(value) for value in values if value == value]
    readiness = chart_readiness(clean, chart_type="histogram")
    if readiness["status"] != "ok":
        return []
    bins = max(1, int(bins or 1))
    lo = min(clean)
    hi = max(clean)
    if lo == hi:
        return [{"label": f"{lo:.3g}", "min": lo, "max": hi, "count": len(clean)}]
    width = (hi - lo) / bins
    counts = [0] * bins
    for value in clean:
        index = min(bins - 1, int((value - lo) / width))
        counts[index] += 1
    return [
        {"label": f"{lo + index * width:.3g}-{lo + (index + 1) * width:.3g}", "min": lo + index * width, "max": lo + (index + 1) * width, "count": count}
        for index, count in enumerate(counts)
    ]


def chart_readiness(values: list[float], *, chart_type: str = "distribution") -> dict[str, Any]:
    clean = [float(value) for value in values if value == value]
    n = len(clean)
    unique_count = len(set(clean))
    zero_count = sum(1 for value in clean if value == 0.0)
    base = {
        "chart_type": chart_type,
        "n": n,
        "unique_count": unique_count,
        "zero_count": zero_count,
        "zero_rate": zero_count / n if n else None,
    }
    if n <= 0:
        return {**base, "status": "no_data", "is_chartable": False, "message": "Нет числовых данных для графика."}
    if n < 3:
        return {**base, "status": "not_enough_rows", "is_chartable": False, "message": "Недостаточно наблюдений для графика."}
    if unique_count <= 1:
        value = clean[0]
        if value == 0.0:
            return {**base, "status": "all_zero", "is_chartable": False, "message": "Все значения показателя равны 0; распределение неинформативно."}
        return {**base, "status": "constant_values", "is_chartable": False, "message": f"Все значения показателя одинаковые: {value:g}."}
    if chart_type == "boxplot":
        ordered = sorted(clean)
        iqr = quantile(ordered, 0.75) - quantile(ordered, 0.25)
        if n < 5:
            return {**base, "status": "not_enough_rows", "is_chartable": False, "message": "Для ящика с усами нужно минимум 5 наблюдений."}
        if iqr == 0.0:
            return {**base, "status": "zero_iqr", "is_chartable": False, "message": "Межквартильный размах равен 0; ящик с усами неинформативен."}
    return {**base, "status": "ok", "is_chartable": True, "message": ""}
