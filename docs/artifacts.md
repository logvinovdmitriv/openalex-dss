# Artifact Model

The MVP uses scoped artifacts as the source of truth. Data access is addressed
by explicit `dump_id`, `run_id`, and `report_scope_hash`; endpoints do not read
global fallback files.

## Artifact Classes

| Artifact | Class | Scope | Used by |
| --- | --- | --- | --- |
| `raw/openalex_cli/{slice_id}/works.jsonl.gz` | canonical | dump | OpenAlex CLI materialization, immutable raw mini-dump |
| `raw/openalex_cli/{slice_id}/dump_manifest.json` | canonical | dump | download provenance, signatures, final-analysis eligibility |
| `dumps/{dump_id}/dump_manifest.json` | canonical | dump | reproducibility checks and analysis eligibility recovery |
| `dumps/{dump_id}/normalized/*.csv` | canonical | dump | dump-scoped normalized CSV staging for import |
| `dumps/{dump_id}/parquet/*_flat.parquet` | canonical | dump | dump-scoped normalized parquet staging for canonical tables |
| `dumps/{dump_id}/quality_report.json` | canonical | dump | normalization quality report for the local corpus |
| `dumps/{dump_id}/fetch_meta.json` | canonical | dump | import/fetch provenance for the local corpus |
| `tables/{dump_id}/works.parquet` | canonical | dump | local-data preview, ranking/scientometrics input |
| `tables/{dump_id}/authorships.parquet` | canonical | dump | local-data preview, author-work materialization |
| `tables/{dump_id}/work_topics.parquet` | canonical | dump | topic diagnostics for the local corpus |
| `runs/{run_id}/tables/author_work.csv` | canonical | run | author-work evidence and local exports |
| `runs/{run_id}/tables/indices.csv` | canonical | run | rankings, cohorts, scientometrics |
| `runs/{run_id}/tables/ratings.csv` | canonical | run | rank table and ranking exports |
| `runs/{run_id}/passports/slice_passport.json` | canonical | run | slice passport for report bundles |
| `runs/{run_id}/passports/calculation_passport.json` | canonical | run | analysis/run passport and final-analysis eligibility |
| `runs/{run_id}/passports/checksums.json` | canonical | run | scoped checksum manifest for report bundles |
| `runs/{run_id}/passports/sha256_manifest.txt` | canonical | run | plain-text SHA-256 manifest beside `checksums.json` |
| `runs/{run_id}/passports/pipeline_summary.json` | canonical | run | pipeline summary for report bundles |
| `runs/{run_id}/reports/report_{report_scope_hash}.json` | canonical | report | reproducible report bundle for an analysis scope |
| `workbench/active_context.json` | pointer | active context | small pointer to the current active `run_id` and `dump_id` |

## Rules

- `dump_id` owns the local corpus: raw manifest plus `works`,
  `authorships`, and `work_topics`.
- Raw imports normalize directly into `dumps/{dump_id}/normalized` and
  `dumps/{dump_id}/parquet`, then materialize canonical parquet tables under
  `tables/{dump_id}`. The import path does not use global `data/normalized` or
  `data/parquet` as staging.
- Import/fetch metadata is written under `dumps/{dump_id}/fetch_meta.json` and
  copied into `runs/{run_id}/passports/fetch_meta.json` from that scoped source.
  It is not written to a global passport path.
- Import runs include `dumps/{dump_id}/fetch_meta.json` and
  `dumps/{dump_id}/quality_report.json` in scoped checksum passports alongside
  dump tables and run outputs. If a dump manifest is provided during import, it
  is written before calculation and included as `dump/dump_manifest.json`.
- Recalculation runs include existing dump provenance files from
  `dumps/{dump_id}` in scoped checksum passports when those files are present.
- `run_id` owns derived calculations: author-work rows, indices,
  ratings, run passports, and scoped report bundles.
- Slice, calculation, checksum, and pipeline summary passports are written
  directly under `runs/{run_id}/passports` when a `run_id` is available.
  Global passport paths are not the source for these run-scoped passport
  artifacts.
- Run checksum passports are built from scoped dump/run artifacts. Scoped
  checksum manifests are written beside
  `runs/{run_id}/passports/checksums.json` as
  `runs/{run_id}/passports/sha256_manifest.txt`.
- Passport generation requires the pipeline to provide an explicit scoped
  primary artifact map. It does not scan global normalized/results/passport
  paths and does not write shared checksum manifests outside the run scope.
- Run archiving records/copies `run_id` artifacts from scoped compute outputs
  and dump tables from the scoped input table manifest. It does not use
  global fallback table paths as the archive source.
- `author_work` belongs to `run_id`; it must not be archived as a dump-owned
  table under `tables/{dump_id}`.
- `report_scope_hash` owns report reproducibility for a selected metric,
  filters, cohort, baseline, rank Top-N, and scientometric analysis parameters.
- Local-data preview and CSV routes require explicit `run_id`/`dump_id`.
- Analytics JSON, CSV, and Markdown routes require explicit `run_id`/`dump_id`
  or a cohort-resolved scope.
- `/workbench` table summaries are resolved from `active_context` when it has
  an active `run_id` or `dump_id`. Without active context, `/workbench` does not
  expose global fallback table counts as current scoped data.
- `/workbench` quality summary is resolved from the active `run_id`. Without an
  active run, `/workbench` does not read global fallback quality reports.
- Final report and analytics paths require scoped artifacts and avoid implicit
  fallback.

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

`/workbench` exposes this pointer for UI state. The UI may use active context as
the default preview scope for local data, rankings, cohorts, and
scientometrics, but final reports should still use explicit scope parameters.
`/workbench` uses the pointer to read scoped table counts and returns an empty
table summary when the pointer is absent. Run quality is read from the active
run only; dump-only or missing active context returns an empty quality summary.
