from __future__ import annotations

from typing import Any

import duckdb

from app.core.paths import BI_WAREHOUSE, TABLE_FILES


SUPERSET_URL = "http://127.0.0.1:8088"
METABASE_URL = "http://127.0.0.1:3000"
SUPERSET_DOCKER_URI = "duckdb:////app/openalex-dss/data/warehouse/openalex_dss_bi.duckdb"
METABASE_DOCKER_PATH = "/app/openalex-dss/data/warehouse/openalex_dss_bi.duckdb"

RECOMMENDED_DASHBOARDS = [
    {
        "title": "Обзор предметного среза",
        "datasets": ["works", "authorships"],
        "charts": ["работы по годам", "страны организаций авторов", "источники публикаций"],
    },
    {
        "title": "Рейтинги авторов",
        "datasets": ["indices", "ratings"],
        "charts": ["top-N по выбранной метрике", "сравнение P/C/C_frac/h/i10/g", "разброс score"],
    },
    {
        "title": "Согласованность индексов",
        "datasets": ["ratings"],
        "charts": ["Spearman между метриками", "top-N overlap", "сравнение рангов"],
    },
    {
        "title": "Качество и воспроизводимость",
        "datasets": ["works", "authorships", "author_work"],
        "charts": ["NULL/deleted authors", "truncated authorships", "проверка размеров плоских таблиц"],
    },
]


def superset_status() -> dict[str, Any]:
    tables = _table_counts() if BI_WAREHOUSE.exists() else {}
    return {
        "enabled": True,
        "prepared": BI_WAREHOUSE.exists(),
        "superset_url": SUPERSET_URL,
        "bi_warehouse_path": str(BI_WAREHOUSE),
        "duckdb_sqlalchemy_uri_local": f"duckdb:///{BI_WAREHOUSE}",
        "duckdb_sqlalchemy_uri_docker": SUPERSET_DOCKER_URI,
        "tables": tables,
        "recommended_dashboards": RECOMMENDED_DASHBOARDS,
        "admin_hint": {"username": "admin", "password": "admin"},
        "tools": [
            {
                "name": "Apache Superset",
                "role": "BI-дашборды, SQL Lab, сложные графики и публикация аналитических панелей",
                "url": SUPERSET_URL,
                "connection": SUPERSET_DOCKER_URI,
                "ops_path": "ops/superset/docker-compose.yml",
                "status": "готов к запуску",
            },
            {
                "name": "Metabase",
                "role": "self-service аналитика, быстрые вопросы к данным, простые управленческие дашборды",
                "url": METABASE_URL,
                "connection": METABASE_DOCKER_PATH,
                "ops_path": "ops/metabase/docker-compose.yml",
                "status": "опционально, через MotherDuck DuckDB driver",
            },
        ],
    }


def prepare_warehouse() -> dict[str, Any]:
    BI_WAREHOUSE.parent.mkdir(parents=True, exist_ok=True)
    created: dict[str, int] = {}
    with duckdb.connect(str(BI_WAREHOUSE)) as conn:
        for name, path in TABLE_FILES.items():
            if not path.exists():
                continue
            csv_path = str(path).replace("'", "''")
            conn.execute(f"DROP TABLE IF EXISTS {name}")
            conn.execute(
                f"""
                CREATE TABLE {name} AS
                SELECT * FROM read_csv_auto('{csv_path}', header=true, ignore_errors=true)
                """
            )
            created[name] = int(conn.execute(f"SELECT count(*) FROM {name}").fetchone()[0])
    return {**superset_status(), "created_tables": created}


def _table_counts() -> dict[str, int]:
    with duckdb.connect(str(BI_WAREHOUSE), read_only=True) as conn:
        names = [row[0] for row in conn.execute("SHOW TABLES").fetchall()]
        return {name: int(conn.execute(f"SELECT count(*) FROM {name}").fetchone()[0]) for name in names}
