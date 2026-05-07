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
- `report_scope_hash` owns report reproducibility for a selected metric,
  filters, cohort, baseline, rank Top-N, and scientometric version set.
- Latest-view files are compatibility artifacts. They are not a stable source
  for dissertation-grade reports.
- Local-data preview routes may still read latest-view files during the
  transition, but no-scope responses are marked as
  `scope_status=implicit_latest_preview` and `reproducible=false`.
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
explicit scope parameters.
