from __future__ import annotations

from pathlib import Path
from typing import Any, Iterable, Iterator

from .io_utils import ensure_parent


def sql_literal(value: object) -> str:
    return "'" + str(value).replace("'", "''") + "'"


def table_expression(path: str | Path) -> str:
    p = Path(path)
    literal = sql_literal(p)
    if p.suffix == ".parquet":
        return f"read_parquet({literal})"
    return (
        f"read_csv_auto({literal}, header=true, sample_size=-1, "
        "quote='\"', escape='\"')"
    )


def copy_query(query: str, csv_path: str | Path, parquet_path: str | Path | None = None) -> None:
    import duckdb

    csv_target = ensure_parent(csv_path)
    parquet_target = ensure_parent(parquet_path) if parquet_path else None
    con = duckdb.connect(database=":memory:")
    try:
        if parquet_target is not None:
            con.execute(f"COPY ({query}) TO {sql_literal(parquet_target)} (FORMAT PARQUET)")
            con.execute(
                f"COPY (SELECT * FROM read_parquet({sql_literal(parquet_target)})) "
                f"TO {sql_literal(csv_target)} (HEADER, DELIMITER ',')"
            )
        else:
            con.execute(f"COPY ({query}) TO {sql_literal(csv_target)} (HEADER, DELIMITER ',')")
    finally:
        con.close()


def iter_query(query: str, *, chunk_size: int = 10_000) -> Iterator[dict[str, Any]]:
    import duckdb

    con = duckdb.connect(database=":memory:")
    try:
        cursor = con.execute(query)
        fields = [item[0] for item in cursor.description]
        while True:
            rows: Iterable[tuple[Any, ...]] = cursor.fetchmany(chunk_size)
            if not rows:
                break
            for row in rows:
                yield dict(zip(fields, row, strict=False))
    finally:
        con.close()
