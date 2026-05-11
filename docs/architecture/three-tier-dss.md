# Three-tier OpenAlex DSS architecture

## Target architecture

The system is split into three independently replaceable layers.

```text
apps/web   -> presentation layer
apps/api   -> application/domain layer
OPENALEX_DSS_DATA_DIR/* -> external lakehouse and warehouse layer
```

### Presentation layer

`apps/web` is a React + TypeScript application with Vite, TanStack Query,
Recharts, Framer Motion and Lucide icons. The first screen is a Russian
workspace: choose a slice, create or import a fixed local slice, inspect author
ratings, compare metric lines, inspect whitelisted local data previews, and export reproducible
tables, passports and report bundles.

The UI intentionally hides unsupported or noisy filters. It exposes only
OpenAlex-backed controls: subject object, keyword, institution, affiliation
mode, publication period, country code from authorship institutions, work type
`article` / `article|review`; конференционные публикации отбираются через
source type `conference`, fraction
mode and ranking metric.

### Application/domain layer

`apps/api` is a FastAPI backend under `/api/v1`; Swagger is available at
`/docs`. It owns:

- OpenAlex ID/autocomplete and explicit lookup access;
- compact OpenAlex Works slice creation;
- local OpenAlex Works JSONL/JSONL.GZ import;
- filesystem/lakehouse source catalog;
- normalization into works/authorships/author-work tables;
- author index calculation and scientometric analysis;
- report bundle assembly with passports, quality funnel, findings and conclusion exports;
- domain exports for rankings, author groups, local data tables and scientometric reports.

HTTP/REST is the primary UI-backend protocol. WebSocket or SSE should be added
later for long-running progress events. gRPC is reserved for future
backend-to-backend services, for example snapshot ingestion or metric
calculation workers.

The current implementation is intentionally a modular Python monolith. Go,
external queues and microservices are not part of the DSS runtime. The
replacement boundary is the run/job API, not a second backend stack.

Supported run contract:

```text
POST /api/v1/runs
GET  /api/v1/runs
GET  /api/v1/runs/{run_id}
```

`POST /runs` is public only for `recalculate`, i.e. recomputing indices from
an already materialized local slice. Its payload must include the target
`dump_id`; it is not a generic job dispatcher. OpenAlex downloads are launched
through the slice/materialization workflow:

```text
POST /api/v1/slices/{slice_id}/materialization-plans
POST /api/v1/materializations/{materialization_id}/run
```

Actions such as `plan`, `fetch_slice_dump`, and `build_from_openalex` are
internal orchestration/service paths, not public API actions.
Generic table browser endpoints are not public; local data inspection goes through
whitelisted `/api/v1/local-data/*` previews.
Jobs execute in one in-process worker and persist status JSON under
`$OPENALEX_DSS_DATA_DIR/runs/{run_id}/run_status.json`. This gives the UI and
future Go gateway a stable contract without adding Celery/RQ/Redis before they
are needed.

## Query planning and efficiency

The DSS treats OpenAlex as an external source, not as the working database.
Every heavy run should follow:

```text
resolve -> estimate -> plan -> materialize Works slice through a selected backend provider -> normalize minimal fields -> analyze locally
```

The supported estimate endpoint is:

```text
POST /api/v1/slices/{slice_id}/estimate
```

It sends lightweight `/works` estimate/sample/group_by requests, reads
`meta.count`, estimates records, API cost and raw JSONL size, then classifies the run as
`can_fetch`, `medium_slice`, `large_slice`, `very_large_slice` or `no_data`.
These statuses are user-facing guidance, not hard download caps.
The planner also records `estimate_signature` and `download_signature`.
If the selected backend provider cannot express the normalized request, the
planner either recommends a compatible provider or marks the plan as
non-final/exploratory instead of silently downloading a different corpus.
The same planner feeds slice estimates and materialization plans; it is not
exposed as a public `/runs` action.

OpenAlex GET responses are cached under:

```text
$OPENALEX_DSS_DATA_DIR/cache/openalex_api/
```

The cache key is based on endpoint and public query parameters; API keys are
not stored in the key or cached payload metadata. This prevents repeated
autocomplete/estimate/list calls from consuming time and API budget.

Execution limits are versioned in `configs/execution_limits.yaml`; supported
filter classes are documented in `configs/openalex_filter_registry.yaml`.

### Data layer

The local data layout is scoped under the external `OPENALEX_DSS_DATA_DIR`
directory. The repository-local `data/` directory is only a small
README/placeholder and is ignored by git.

```text
$OPENALEX_DSS_DATA_DIR/raw/openalex_cli/{slice_id}/     raw JSONL.GZ files from OpenAlex CLI provider
$OPENALEX_DSS_DATA_DIR/raw/openalex_api/{slice_id}/     API cursor and ids-then-hydrate chunks/manifests
$OPENALEX_DSS_DATA_DIR/raw/openalex_snapshot/{slice_id}/ local snapshot-scan result files
$OPENALEX_DSS_DATA_DIR/dumps/{dump_id}/                 slice manifest, fetch metadata and quality report
$OPENALEX_DSS_DATA_DIR/tables/{dump_id}/                canonical Parquet tables: works, authorships, topics, institutions, countries
$OPENALEX_DSS_DATA_DIR/runs/{run_id}/tables/            derived author_work, indices and ratings
$OPENALEX_DSS_DATA_DIR/runs/{run_id}/passports/         passports and checksums
$OPENALEX_DSS_DATA_DIR/runs/{run_id}/analytics/         reusable analysis cache manifests
$OPENALEX_DSS_DATA_DIR/runs/{run_id}/reports/           report bundles keyed by report_scope_hash
$OPENALEX_DSS_DATA_DIR/workbench/active_context.json    UI pointer to the active run/dump
```

Canonical slice tables are Parquet. Run tables and passports stay scoped to
`run_id`. Run-table materialization and interactive table access use DuckDB or
streaming reads where possible; the frontend receives only the requested page or
compact analytical payload. CSV is an export format, not the main analytical
store.

SQLite is used only for local metadata catalogs, entity suggestions and slice
metadata. It is not the analytical store. PostgreSQL is reserved for a later
multi-user server mode with roles, durable jobs and permissions.

## Works-Based Contract

`strict_works` is the research mode. It loads Works, flattens authorships and
calculates local author metrics only inside the current slice. Mathematical
conclusions about indices must use this mode.

For reproducible DSS runs,
`POST /api/v1/materializations/{materialization_id}/run` materializes the strict
Works request through the provider selected by the materialization plan:
OpenAlex CLI, API cursor, ids-then-hydrate, local snapshot partition scan or
import of an already downloaded JSONL file. API calls are used for field
catalogs, entity resolving, estimates, rate-limit visibility, cursor downloads
and explicit selected-entity lookup. Provider output is packed as a fixed
`works.jsonl.gz` with manifest, passport and checksum. The local materialization
path then imports this fixed file, normalizes works/authorships/topics/
institutions/countries and writes run-scoped author tables, ratings, passports
and checksums.

## Primary Workflow

The primary DSS workflow is:

1. choose OpenAlex field, subfield or topic by name;
2. choose filter mode: primary topic, any topic, keyword, ID-based hydration or
   explicitly exploratory text-search workflow;
3. optionally restrict by organization and country code;
4. materialize the Works request as a fixed JSONL.GZ local slice through the
   selected backend provider;
5. import the fixed local slice with streaming JSONL normalization and scoped
   staging cleanup;
6. build canonical `tables/{dump_id}` once, then build run-scoped
   `author_work`, `indices`, `ratings`, passports and checksums;
7. precompute the default report bundle and analytical cache once per run so
   reopening the same slice does not repeat the heavy work;
8. use backend filtering, sorting, TOP-N selection and custom metric evaluation
   for interactive tables and analysis;
9. visualize author-level distributions, boxplots, rank/correlation matrices,
   ranking tables and quality diagnostics.

Gender and age are not implemented because OpenAlex does not provide those
fields. City is not a primary OpenAlex filter in this DSS; it should be added
later through an external institution dictionary that resolves a city to a list
of institution IDs. The pipeline uses observed `authorships` and records
quality flags for missing/deleted/truncated author information.

## Visualization layer

The core DSS UI remains the main working area. It should provide a small set of
purpose-built visualizations instead of a separate BI layer:

- subject-slice overview: works by year, country and source;
- author rankings: top-N by selected index and author table selection;
- relation between indicators: rank-correlation matrices and concise interpretation findings;
- data quality: NULL/deleted authors, truncated authorships and row-count
  checks.

## OpenAlex snapshot best practice

OpenAlex stores the snapshot in the public S3 bucket `openalex`. Entity data is
gzip-compressed JSON Lines and partitioned by `updated_date`. Incremental
updates should download the manifest, identify new partitions, verify the
manifest did not change during download, and upsert by OpenAlex entity ID.

The DSS supports local JSONL/JSONL.GZ snapshot partition scan as an explicit
provider for large or repeatable workloads. Full managed snapshot ingestion,
incremental changefile upserts and multi-user warehouse maintenance remain
production extensions. Regardless of provider, analytical calculations run only
from the fixed local raw file and normalized local tables.
