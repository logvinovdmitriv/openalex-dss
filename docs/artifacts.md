# Artifact Model

The MVP uses scoped artifacts as the source of truth. Global latest-view files
still exist as a compatibility layer for preview/UI fallback, but final analysis
and reports should be addressed by explicit `dump_id`, `run_id`, and
`report_scope_hash`.

## Artifact Classes

| Artifact | Class | Scope | Used by |
| --- | --- | --- | --- |
| `raw/openalex_cli/{slice_id}/works.jsonl.gz` | canonical | dump | OpenAlex CLI materialization, immutable raw mini-dump |
| `raw/openalex_cli/{slice_id}/dump_manifest.json` | canonical | dump | download provenance, signatures, final-analysis eligibility |
| `dumps/{dump_id}/dump_manifest.json` | canonical | dump | reproducibility checks and analysis eligibility recovery |
| `tables/{dump_id}/works.parquet` | canonical | dump | local-data preview, ranking/scientometrics input |
| `tables/{dump_id}/authorships.parquet` | canonical | dump | local-data preview, author-work materialization |
| `tables/{dump_id}/work_topics.parquet` | canonical | dump | topic diagnostics for the local corpus |
| `runs/{run_id}/tables/author_work.csv` | canonical | run | author-work evidence and local exports |
| `runs/{run_id}/tables/indices.csv` | canonical | run | rankings, cohorts, scientometrics |
| `runs/{run_id}/tables/ratings.csv` | canonical | run | rank table and ranking exports |
| `runs/{run_id}/passports/slice_passport.json` | canonical | run | slice passport for report bundles |
| `runs/{run_id}/passports/calculation_passport.json` | canonical | run | analysis/run passport and final-analysis eligibility |
| `runs/{run_id}/passports/checksums.json` | canonical | run | scoped checksum manifest for report bundles |
| `runs/{run_id}/passports/pipeline_summary.json` | canonical | run | pipeline summary for report bundles |
| `runs/{run_id}/results/stats_summary.json` | legacy/internal | run | compatibility statistics, not the primary scientometric layer |
| `runs/{run_id}/results/theory_validation.json` | legacy/internal | run | compatibility diagnostics, not the primary report layer |
| `runs/{run_id}/reports/report_{report_scope_hash}.json` | canonical | report | reproducible report bundle for an analysis scope |
| `results/author_indices.csv` | compatibility latest-view | latest | UI fallback only when no explicit scope is selected |
| `results/rating_positions.csv` | compatibility latest-view | latest | UI fallback only when no explicit scope is selected |
| `normalized/*.csv`, `parquet/*.parquet`, `marts/*` | compatibility latest-view | latest | current preview/read compatibility |
| `passports/*.json` | compatibility latest-view | latest | latest UI/passport preview |
| `workbench/active_context.json` | pointer | active context | small pointer to the latest active `run_id` and `dump_id` |

## Rules

- `dump_id` owns the local corpus: raw manifest plus `works`,
  `authorships`, and `work_topics`.
- `run_id` owns derived calculations: author-work rows, author indices,
  ratings, run passports, and run-local diagnostic outputs.
- Slice, calculation and checksum passports are written directly under
  `runs/{run_id}/passports`. Pipeline summary is also mirrored there when a
  `run_id` is available. Compatibility latest passport paths are not the source
  for these run-scoped passport artifacts.
- Run checksum passports are built from scoped dump/run artifacts when the
  pipeline provides a scoped artifact map. Compatibility latest-view paths are
  used only by legacy `build_passports(...)` calls that do not provide scoped
  primary artifacts.
- Run archiving records/copies `run_id` artifacts from scoped compute outputs
  and dump tables from the scoped input table manifest. It does not use
  compatibility latest-view table paths as the archive source.
- `author_work` belongs to `run_id`; it must not be archived as a dump-owned
  table under `tables/{dump_id}`.
- `report_scope_hash` owns report reproducibility for a selected metric,
  filters, cohort, baseline, rank Top-N, and scientometric version set.
- Latest-view files are compatibility artifacts. They are not a stable source
  for dissertation-grade reports.
- Local-data preview routes may still read latest-view files during the
  transition, but no-scope responses are marked as
  `scope_status=implicit_latest_preview` and `reproducible=false`.
- Local-data CSV exports require explicit `run_id`/`dump_id`; compatibility
  latest CSV export is available only with `allow_latest_preview=true`.
- Analytics CSV and Markdown exports require explicit `run_id`/`dump_id` or a
  cohort-resolved scope; compatibility latest exports require
  `allow_latest_preview=true`.
- `/workbench` table summaries are resolved from `active_context` when it has
  an active `run_id` or `dump_id`. Without active context, `/workbench` does not
  expose latest-view table counts as current scoped data.
- `/workbench` quality summary is resolved from the active `run_id`. Without an
  active run, `/workbench` does not read compatibility latest-view quality
  reports.
- Final report and analytics paths must prefer explicit `run_id`/`dump_id` and
  avoid implicit latest fallback.

## Active Context Pointer

`workbench/active_context.json` is intentionally small:

```json
{
  "active_run_id": "run_...",
  "active_dump_id": "dump_...",
  "source": "materialization|recalculate|import_local_file|dev_import_file",
  "analysis_eligibility_status": "final",
  "allowed_for_final_analysis": true,
  "updated_at_utc": "2026-05-07T00:00:00Z"
}
```

It can replace large latest-view copies in a later storage cleanup. During the
transition, latest-view files remain a compatibility layer while scoped
artifacts remain the source of truth. `/workbench` exposes this pointer for UI
state. The UI may use active context as the default preview scope for local
data, rankings, cohorts, and scientometrics, but final reports should still use
explicit scope parameters. `/workbench` uses the pointer to read scoped table
counts and returns an empty table summary when the pointer is absent, rather
than deriving status from compatibility latest-view files. Run quality is read
from the active run only; dump-only or missing active context returns an empty
quality summary instead of using latest-view quality.
