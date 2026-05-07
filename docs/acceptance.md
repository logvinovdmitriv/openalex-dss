# Acceptance Gate

This document defines the release-readiness gate for the scoped OpenAlex DSS.
The gate is intentionally local and reproducible: it checks the Python backend,
the frontend build, repository hygiene, and the deterministic scientometric
validation flow.

## Required Commands

Run from the repository root:

```bash
pytest tests/test_repository_hygiene.py -q
pytest tests/test_pipeline_integrity.py -q
pytest tests/test_edge_cases.py -q
pytest tests/test_slice_workbench.py -q
pytest tests/test_analytics_routes.py -q
pytest tests/test_local_data_routes.py -q
pytest tests/test_web_workbench_scope.py -q
pytest tests/test_api_surface.py -q
pytest tests/test_validation_script.py -q
pytest tests/test_scientometrics.py -q
```

Then run the frontend build:

```bash
cd apps/web
npm run build
cd ../..
```

Then run the deterministic end-to-end validation:

```bash
python scripts/validate_scientometric_dss.py --reset
```

## Acceptance Criteria

The DSS is ready for pilot handoff when all criteria below are true:

- The repository hygiene test passes.
- The backend test suite listed above passes.
- The frontend production build passes.
- The deterministic validation script returns `status: ok`.
- The validation output contains `report_bundle_schema: report_bundle`.
- The validation output contains `analysis_schema: scientometric_analysis`.
- The validation output contains `findings_schema: scientometric_findings`.
- The validation output contains `conclusion_schema: scientometric_conclusion`.
- The validation output includes artifact checksums for the report bundle,
  scientometric JSON, findings CSV, conclusion Markdown, and tabular exports.
- Report bundles are produced from explicit `run_id` and `dump_id` scope.
- Local-data and analytics routes require scoped inputs.

## Contract Invariants

The accepted system uses this artifact ownership model:

```text
dumps/<dump_id>/...
tables/<dump_id>/...
runs/<run_id>/tables/...
runs/<run_id>/passports/...
runs/<run_id>/reports/report_<report_scope_hash>.json
workbench/active_context.json
```

The accepted public table names are:

```text
works
authorships
work_topics
author_work
indices
ratings
```

The accepted report layer is:

```text
scientometric_analysis
findings
conclusion
checksums
exports
```

## Handoff Note

The deterministic validation fixture proves that the pipeline, scoped artifact
model, report bundle, exports, and checksums are internally consistent. It does
not prove any scientific claim about a real OpenAlex subject area. A real
analysis still requires a qualified corpus, accepted materialization signatures,
and review of the generated report bundle.
